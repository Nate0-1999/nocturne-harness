"""Bounded pydantic-ai chat and the direct C.6 `/remember` command."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictBool, StrictInt, StrictStr
from pydantic_ai import Agent, PromptedOutput, UsageLimits, capture_run_messages
from pydantic_ai.exceptions import UnexpectedModelBehavior, UserError
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models import Model, infer_model
from pydantic_ai.providers import Provider, infer_provider
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.providers.openrouter import OpenRouterProvider
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import RunUsage
from spine.tokens import cl100k_token_count

from harness.commands import remember_command_text
from harness.config import HarnessSettings
from harness.openrouter_runtime import PreservingOpenRouterModel
from harness.pydantic_ai_adapter import MemoryCapability
from harness.spine_client import (
    CreatedMemoryResponse,
    CreateMemoryConflictError,
    MemorySplitChild,
    MemorySplitResponse,
    SimilarMemoriesResponse,
    SpineClientError,
)
from harness.tools_memory import (
    MemoryToolContext,
    create_remembered_memory,
    create_remembered_memory_split,
    render_create_conflict,
    render_create_response,
    render_spine_error,
)

REMEMBER_DRAFT_INSTRUCTION = (
    "Generate one short label and 2-5 lowercase searchable keywords for the "
    "supplied memory. Keywords must be distinct nouns or terms. Return only "
    "the requested structured result with no commentary."
)
REMEMBER_SPLIT_INSTRUCTION = (
    "Semantically divide the complete /remember source into durable atomic facts in source "
    "order. Preserve every claim and qualifier without summarizing, omitting, truncating, or "
    "mechanically chopping the source. Every candidate must stand alone, contain one claim, "
    "and have its own short retrieval label: prefer 2-5 words and under 40 characters, with "
    "64 Unicode code points as the hard maximum. Also return 2-5 "
    "distinct lowercase searchable keywords. Every split candidate body must be at most 128 "
    "cl100k_base tokens. If the "
    "candidate itself names an object before referring back to it, that internal reference is "
    "resolved and the candidate can still stand alone (for example, 'the ledger ... its cover' "
    "or 'the eastern shelf ... returned there'). Source-order words such as First, Second, and "
    "Third do not by themselves make otherwise independent facts unsafe; when they are part "
    "of a durable coverage segment, retain them byte-for-byte in that candidate body. "
    "source includes directions or commentary about remembering, saving, or splitting, treat "
    "them as instructions for this operation, never as durable facts or candidates. Keep every "
    "actual claim and qualifier. Also return source-ordered coverage segments whose exact text "
    "concatenates byte-for-byte to the complete source. Classify each segment as durable with "
    "one zero-based candidate_index, or operation with candidate_index null. Operation text "
    "is excluded from candidate bodies but MUST still appear byte-for-byte in coverage; never "
    "drop an instruction-only introduction, transition, or ending from the witness. "
    "Boundary whitespace is source text: preserve it inside an adjacent coverage text value. "
    "For example, when the source boundary is '. ' the preceding text must end with that space "
    "or the following text must begin with it; JSON strings must never trim it. "
    "Attach whitespace and separators to a neighboring nonblank segment; never emit a blank "
    "or whitespace-only segment. Durable candidate "
    "indices must be nondecreasing, every candidate must own durable text, and each candidate "
    "body must equal its assigned durable text concatenated in source order with outer "
    "whitespace trimmed only. Never add or rewrite body text. Set safe_to_save true only when "
    "every extractive candidate stands alone and every semantic, coverage, and body rule is "
    "satisfied; set it false whenever an extractive unit cannot stand alone or any requirement "
    "cannot be met. If the source is one indivisible claim that cannot fit the supplied body "
    "limit, return exactly one candidate containing that complete claim even though it exceeds "
    "the limit; never shorten it to fit. Return one to 64 candidates and structured data only."
)
REMEMBER_SPLIT_GUIDANCE = (
    "I couldn't split this into standalone memories without changing its meaning, so I didn't "
    "save it. Please break it into separate facts and try /remember again."
)
EXTRACTION_INSTRUCTION = (
    "Read the complete thread transcript. Return a concise working summary, open loops, and at "
    "most five durable memory candidates. Each candidate must be atomic, stand alone, preserve "
    "uncertainty, and include 2-5 distinct lowercase searchable keywords. Do not extract transient "
    "chat or facts that are not useful beyond this thread."
)
SEED_SPLIT_INSTRUCTION = (
    "Semantically split the complete Markdown document into durable atomic memories. Preserve "
    "every durable claim without summarizing or mechanical token chopping. Every child must "
    "stand alone with no unresolved references, contain one claim, use at most 128 cl100k_base "
    "tokens, and include its own short label, kind, and 2-5 distinct lowercase searchable "
    "keywords. Return one to 64 children in source order and structured data only."
)


class ModelConfigurationError(ValueError):
    """The selected model cannot be constructed from its provider configuration."""


class RememberDraft(BaseModel):
    """One tools-free model completion for a `/remember` write."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    label: StrictStr
    keywords: list[StrictStr]


class RememberSplitCandidate(BaseModel):
    """One semantic child proposed only for an oversized `/remember`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    label: StrictStr = Field(
        min_length=1,
        max_length=64,
        description=(
            "A short retrieval handle, preferably 2-5 words and under 40 characters; one "
            "nonblank line with 64 Unicode code points as the hard maximum."
        ),
    )
    body: StrictStr
    keywords: list[StrictStr] = Field(min_length=2, max_length=5)


class RememberCoverageSegment(BaseModel):
    """One exact source span proving durable ownership or operation-only text."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    text: StrictStr = Field(
        min_length=1,
        description=(
            "Exact source text. Never whitespace-only: attach every separator to the previous "
            "or following nonblank segment so all segments still concatenate byte-for-byte. "
            "Preserve leading and trailing boundary whitespace inside this string; for a '. ' "
            "source boundary, one adjacent segment must carry the space. Never trim it."
        ),
    )
    classification: Literal["durable", "operation"]
    candidate_index: StrictInt | None


class RememberSplitDraft(BaseModel):
    """The complete source-ordered A-049/A-050 split proposal and witness."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidates: list[RememberSplitCandidate] = Field(min_length=1, max_length=64)
    coverage: list[RememberCoverageSegment] = Field(min_length=1)
    safe_to_save: StrictBool


class ExtractionCandidateDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    label: StrictStr
    body: StrictStr
    kind: Literal["fact", "preference", "procedure", "project_note", "persona"]
    keywords: list[StrictStr] = Field(min_length=2, max_length=5)


class ExtractionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    working_summary: StrictStr
    open_loops: list[StrictStr]
    candidates: list[ExtractionCandidateDraft] = Field(max_length=5)


class SeedSplitDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    candidates: list[ExtractionCandidateDraft] = Field(min_length=1, max_length=64)


class ExtractionVerdictDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    verdict: Literal["new", "merge", "supersede", "contradict"]
    target_ids: list[UUID] = Field(max_length=5)


@dataclass(frozen=True, slots=True)
class ChatResult:
    """Framework-neutral output plus the opaque history needed by the next turn."""

    output: str
    message_history: tuple[object, ...]


@dataclass(frozen=True, slots=True)
class RememberResult:
    """A truthful chat confirmation or visible non-save result."""

    ok: bool
    message: str
    memory_id: UUID | None = None
    label: str | None = None


type DispatchResult = ChatResult | RememberResult


class HarnessAgent:
    """Own the chat agent, tools-free remember agent, and C.5 usage walls."""

    def __init__(
        self,
        settings: HarnessSettings,
        *,
        model: Model | None = None,
    ) -> None:
        self._settings = settings
        self._default_model = model
        self._models_by_name: dict[str, Model] = (
            {settings.chat_model: model} if model is not None else {}
        )
        self._usage_limits = UsageLimits(
            request_limit=settings.run_request_limit,
            total_tokens_limit=settings.run_total_tokens_limit,
        )
        self._label_usage_limits = UsageLimits(
            request_limit=1,
            total_tokens_limit=settings.run_total_tokens_limit,
        )
        self._remember_split_usage_limits = UsageLimits(
            request_limit=2,
            total_tokens_limit=settings.run_total_tokens_limit,
        )
        self._chat_agent = Agent(
            self._default_model,
            deps_type=MemoryToolContext,
            capabilities=[MemoryCapability()],
            name="harness-chat",
        )
        self._label_agent = Agent(
            self._default_model,
            output_type=PromptedOutput(RememberDraft),
            instructions=REMEMBER_DRAFT_INSTRUCTION,
            name="harness-memory-label",
        )
        self._remember_splitter_agent = Agent(
            self._default_model,
            output_type=PromptedOutput(RememberSplitDraft),
            instructions=REMEMBER_SPLIT_INSTRUCTION,
            name="harness-remember-splitter",
            retries=0,
        )
        self._extraction_agent = Agent(
            self._default_model,
            output_type=PromptedOutput(ExtractionDraft),
            instructions=EXTRACTION_INSTRUCTION,
            name="harness-thread-extractor",
        )
        self._extraction_verdict_agent = Agent(
            self._default_model,
            output_type=PromptedOutput(ExtractionVerdictDraft),
            instructions=(
                "Compare one extracted candidate with machine-fetched corpus neighbors. "
                "Propose exactly one verdict: new, merge, supersede, or contradict. Target IDs "
                "must be selected only from the supplied neighbors. Use new with no targets when "
                "the candidate stands alone. Return structured data only."
            ),
            name="harness-extraction-verdict",
        )
        self._seed_splitter_agent = Agent(
            self._default_model,
            output_type=PromptedOutput(SeedSplitDraft),
            instructions=SEED_SPLIT_INSTRUCTION,
            name="harness-seed-splitter",
        )

    @property
    def chat_agent(self) -> Agent[MemoryToolContext, str]:
        """Expose the vanilla agent for inspection and later daemon assembly."""

        return self._chat_agent

    @property
    def label_agent(self) -> Agent[None, RememberDraft]:
        """Expose the separate, tools-free remember agent for inspection."""

        return self._label_agent

    @property
    def remember_splitter_agent(self) -> Agent[None, RememberSplitDraft]:
        """Expose the separate, tools-free A-049 semantic splitter for inspection."""

        return self._remember_splitter_agent

    @property
    def usage_limits(self) -> UsageLimits:
        return self._usage_limits

    def model_for(self, model: Model | str | None = None) -> Model:
        """Return one cached settings-owned model instance for a resolved route."""

        return self._select_model(model)

    async def chat(
        self,
        prompt: str,
        *,
        context: MemoryToolContext,
        message_history: Sequence[Any] | None = None,
        model: Model | str | None = None,
        model_settings: ModelSettings | None = None,
    ) -> ChatResult:
        """Run one ordinary chat turn with memory tools and bounded usage."""

        result = await self._chat_agent.run(
            prompt,
            deps=context,
            message_history=message_history,
            model=self._select_model(model),
            model_settings=model_settings,
            usage_limits=self._usage_limits,
        )
        if not isinstance(result.output, str):
            raise TypeError("chat agent returned a non-text output")
        return ChatResult(
            output=result.output,
            message_history=tuple(result.all_messages()),
        )

    async def remember(
        self,
        text: str,
        *,
        context: MemoryToolContext,
        model: Model | str | None = None,
        model_settings: ModelSettings | None = None,
        usage: RunUsage | None = None,
        raise_model_errors: bool = False,
        captured_messages: list[ModelMessage] | None = None,
    ) -> RememberResult:
        """Generate one valid draft, save one global user fact, and confirm honestly."""

        body = text.strip()
        if not body:
            return RememberResult(False, "Nothing to remember; add text after /remember.")

        selected_model = self._select_model(model)
        remember_usage = usage if usage is not None else RunUsage()
        if cl100k_token_count(body) > self._settings.memory_max_tokens:
            return await self._split_or_guide_remember(
                body,
                context=context,
                model=selected_model,
                model_settings=model_settings,
                usage=remember_usage,
                raise_model_errors=raise_model_errors,
                captured_messages=captured_messages,
            )
        try:
            draft_result = await _run_structured_agent(
                self._label_agent,
                f"Memory:\n{body}",
                model=selected_model,
                model_settings=model_settings,
                usage_limits=self._label_usage_limits,
                usage=remember_usage,
                captured_messages=captured_messages,
            )
        except Exception:
            if raise_model_errors:
                raise
            return RememberResult(False, "Could not remember: metadata generation failed.")

        draft = draft_result.output
        if not isinstance(draft, RememberDraft):  # pragma: no cover - pydantic-ai type guard
            return RememberResult(
                False,
                "Could not remember: metadata generation returned no data.",
            )
        label = draft.label.strip()
        if not label:
            return RememberResult(False, "Could not remember: the generated label was blank.")
        if "\n" in label or "\r" in label:
            return RememberResult(
                False,
                "Could not remember: the generated label was not one line.",
            )
        if len(label) > self._settings.label_max:
            return await self._split_or_guide_remember(
                body,
                context=context,
                model=selected_model,
                model_settings=model_settings,
                usage=remember_usage,
                raise_model_errors=raise_model_errors,
                captured_messages=captured_messages,
            )
        keywords = _normalize_keywords(draft.keywords)
        if keywords is None:
            return RememberResult(
                False,
                "Could not remember: generated keywords must contain 2-5 distinct nonblank terms.",
            )

        return await self._create_single_remember(
            body,
            label=label,
            keywords=keywords,
            context=context,
        )

    async def _split_or_guide_remember(
        self,
        body: str,
        *,
        context: MemoryToolContext,
        model: Model,
        model_settings: ModelSettings | None,
        usage: RunUsage,
        raise_model_errors: bool,
        captured_messages: list[ModelMessage] | None,
    ) -> RememberResult:
        """Plan one semantic family, then write all children or guide without a write."""

        try:
            draft_result = await _run_structured_agent(
                self._remember_splitter_agent,
                (
                    f"Label limit: {self._settings.label_max} Unicode code points\n"
                    f"Body limit: {self._settings.memory_max_tokens} cl100k_base tokens\n"
                    f"Memory source:\n{body}"
                ),
                model=model,
                model_settings=model_settings,
                usage_limits=self._remember_split_usage_limits,
                usage=usage,
                captured_messages=captured_messages,
            )
        except UnexpectedModelBehavior:
            return RememberResult(False, REMEMBER_SPLIT_GUIDANCE)
        except Exception:
            if raise_model_errors:
                raise
            return RememberResult(False, REMEMBER_SPLIT_GUIDANCE)

        draft = draft_result.output
        if not isinstance(draft, RememberSplitDraft):  # pragma: no cover - type guard
            return RememberResult(False, REMEMBER_SPLIT_GUIDANCE)
        children = _validated_remember_split(
            draft,
            source_body=body,
            label_max=self._settings.label_max,
            memory_max_tokens=self._settings.memory_max_tokens,
        )
        if children is None:
            return RememberResult(False, REMEMBER_SPLIT_GUIDANCE)

        if len(children) == 1:
            child = children[0]
            if cl100k_token_count(body) > self._settings.memory_max_tokens or child.body != body:
                return RememberResult(False, REMEMBER_SPLIT_GUIDANCE)
            return await self._create_single_remember(
                body,
                label=child.label,
                keywords=child.keywords,
                context=context,
            )

        try:
            response = await create_remembered_memory_split(
                context,
                source_body=body,
                children=children,
            )
        except CreateMemoryConflictError as exc:
            return RememberResult(False, f"Could not remember: {render_create_conflict(exc)}")
        except SpineClientError as exc:
            return RememberResult(False, f"Could not remember: {render_spine_error('save', exc)}")

        if not isinstance(response, MemorySplitResponse):
            if isinstance(response, SimilarMemoriesResponse) and response.similar:
                existing = response.similar[0]
                return RememberResult(
                    False,
                    "Not saved: a proposed split memory is similar to existing memory "
                    f"{existing.label!r} ({existing.memory_id}), so none of the split was "
                    "saved. Review or update the existing memory as needed, remove that "
                    "already-covered claim from the source, then try /remember again with "
                    "the remaining facts.",
                )
            return RememberResult(False, "Not saved: none of the split was saved.")
        labels = ", ".join(repr(created.label) for created in response.created)
        return RememberResult(
            True,
            f"Remembered {len(response.created)} linked memories: {labels}.",
            memory_id=response.source.memory_id,
            label=response.source.label,
        )

    @staticmethod
    async def _create_single_remember(
        body: str,
        *,
        label: str,
        keywords: list[str],
        context: MemoryToolContext,
    ) -> RememberResult:
        """Persist the exact source through the unchanged ordinary create boundary."""

        try:
            response = await create_remembered_memory(
                context,
                label=label,
                body=body,
                keywords=keywords,
            )
        except CreateMemoryConflictError as exc:
            return RememberResult(False, f"Could not remember: {render_create_conflict(exc)}")
        except SpineClientError as exc:
            return RememberResult(False, f"Could not remember: {render_spine_error('save', exc)}")

        if not isinstance(response, CreatedMemoryResponse):
            return RememberResult(False, f"Not saved: {render_create_response(response)}")
        created = response.created
        return RememberResult(
            True,
            f"Remembered {created.label!r} ({created.memory_id}).",
            memory_id=created.memory_id,
            label=created.label,
        )

    async def extract_thread(
        self,
        transcript: str,
        *,
        model: Model | str | None = None,
    ) -> ExtractionDraft:
        """Run the tools-free cheap-model extraction pass over one durable transcript."""

        result = await self._extraction_agent.run(
            transcript,
            model=self._select_model(model),
            usage_limits=self._usage_limits,
        )
        if not isinstance(result.output, ExtractionDraft):
            raise TypeError("extraction agent returned no structured result")
        return result.output

    async def propose_extraction_verdict(
        self,
        candidate: ExtractionCandidateDraft,
        neighbors: list[dict[str, str]],
        *,
        model: Model | str | None = None,
    ) -> ExtractionVerdictDraft:
        """Give the thread-aware extractor the corpus neighborhood before queue birth."""

        result = await self._extraction_verdict_agent.run(
            f"Candidate: {candidate.model_dump_json()}\nNeighbors: {neighbors!r}",
            model=self._select_model(model),
            usage_limits=self._label_usage_limits,
        )
        if not isinstance(result.output, ExtractionVerdictDraft):
            raise TypeError("extraction verdict agent returned no structured result")
        allowed = {UUID(item["memory_id"]) for item in neighbors}
        if any(target not in allowed for target in result.output.target_ids):
            raise ValueError("extraction verdict targeted a memory outside its fetched neighbors")
        if result.output.verdict == "new" and result.output.target_ids:
            raise ValueError("new extraction verdict cannot have targets")
        if result.output.verdict != "new" and not result.output.target_ids:
            raise ValueError("non-new extraction verdict requires a target")
        return result.output

    async def split_seed(
        self,
        source_name: str,
        markdown: str,
        *,
        model: Model | str | None = None,
    ) -> SeedSplitDraft:
        """Produce a lossless semantic split or fail before any queue write."""

        result = await self._seed_splitter_agent.run(
            f"Source: {source_name}\n\n{markdown}",
            model=self._select_model(model),
            usage_limits=self._usage_limits,
        )
        if not isinstance(result.output, SeedSplitDraft):
            raise TypeError("seed splitter returned no structured result")
        for candidate in result.output.candidates:
            invalid_label = (
                not candidate.label.strip()
                or len(candidate.label.strip()) > self._settings.label_max
            )
            if invalid_label:
                raise ValueError("seed splitter produced an invalid label")
            if cl100k_token_count(candidate.body.strip()) > 128:
                raise ValueError("seed splitter produced a child above the 128-token limit")
            if _normalize_keywords(candidate.keywords) is None:
                raise ValueError("seed splitter produced invalid keywords")
        return result.output

    async def dispatch(
        self,
        text: str,
        *,
        context: MemoryToolContext,
        message_history: Sequence[Any] | None = None,
        model: Model | str | None = None,
        model_settings: ModelSettings | None = None,
        usage: RunUsage | None = None,
        raise_model_errors: bool = False,
        captured_messages: list[ModelMessage] | None = None,
    ) -> DispatchResult:
        """Route only the exact `/remember` command; all other text is chat."""

        remembered_text = remember_command_text(text)
        if remembered_text is not None:
            return await self.remember(
                remembered_text,
                context=context,
                model=model,
                model_settings=model_settings,
                usage=usage,
                raise_model_errors=raise_model_errors,
                captured_messages=captured_messages,
            )
        return await self.chat(
            text,
            context=context,
            message_history=message_history,
            model=model,
            model_settings=model_settings,
        )

    def _select_model(self, model: Model | str | None) -> Model:
        if model is None:
            model = self._settings.chat_model
        if not isinstance(model, str):
            return model
        resolved = self._models_by_name.get(model)
        if resolved is None:
            resolved = resolve_model(model, self._settings)
            self._models_by_name[model] = resolved
        return resolved


def resolve_model(model: Model | str, settings: HarnessSettings) -> Model:
    """Resolve default routes from settings and explicit others through Pydantic AI."""

    if not isinstance(model, str):
        return model
    if not model or model != model.strip():
        raise ModelConfigurationError("chat model must be nonblank without surrounding whitespace")

    def provider_factory(name: str) -> Provider[Any]:
        if name == "openrouter":
            return OpenRouterProvider(
                api_key=_required_secret(settings.openrouter_api_key, "OPENROUTER_API_KEY")
            )
        if name == "anthropic":
            return AnthropicProvider(
                api_key=_required_secret(settings.anthropic_api_key, "ANTHROPIC_API_KEY")
            )
        if name in {"openai", "openai-chat", "openai-responses"}:
            return OpenAIProvider(
                api_key=_required_secret(settings.openai_api_key, "OPENAI_API_KEY")
            )
        return infer_provider(name)

    try:
        if model.startswith("openrouter:"):
            return PreservingOpenRouterModel(
                model.removeprefix("openrouter:"),
                provider=provider_factory("openrouter"),
            )
        return infer_model(model, provider_factory=provider_factory)
    except ModelConfigurationError:
        raise
    except (UserError, ValueError) as exc:
        raise ModelConfigurationError(str(exc)) from exc
    except ImportError as exc:
        raise ModelConfigurationError(
            f"provider dependency is unavailable for {model!r}: {exc}"
        ) from exc


def _required_secret(value: SecretStr | None, name: str) -> str:
    if value is None or not value.get_secret_value().strip():
        raise ModelConfigurationError(f"{name} is required for the selected model provider")
    return value.get_secret_value()


async def _run_structured_agent(
    agent: Agent[None, Any],
    prompt: str,
    *,
    model: Model,
    model_settings: ModelSettings | None,
    usage_limits: UsageLimits,
    usage: RunUsage,
    captured_messages: list[ModelMessage] | None,
) -> Any:
    """Run one structured pass and append its complete messages to a caller-owned turn sink."""

    async def run() -> Any:
        return await agent.run(
            prompt,
            model=model,
            model_settings=model_settings,
            usage_limits=usage_limits,
            usage=usage,
        )

    if captured_messages is None:
        return await run()
    with capture_run_messages() as call_messages:
        try:
            return await run()
        finally:
            captured_messages.extend(call_messages)


def _validated_remember_split(
    draft: RememberSplitDraft,
    *,
    source_body: str,
    label_max: int,
    memory_max_tokens: int,
) -> list[MemorySplitChild] | None:
    """Validate one exact A-050 coverage witness or reject it before any write."""

    children: list[MemorySplitChild] = []
    labels: set[str] = set()
    bodies: set[str] = set()
    is_split = len(draft.candidates) >= 2
    if not draft.safe_to_save:
        return None
    if "".join(segment.text for segment in draft.coverage) != source_body:
        return None

    assigned_text: list[list[str]] = [[] for _ in draft.candidates]
    last_durable_index = -1
    for segment in draft.coverage:
        if not segment.text.strip():
            return None
        if segment.classification == "operation":
            if segment.candidate_index is not None:
                return None
            continue
        index = segment.candidate_index
        if index is None or index < 0 or index >= len(draft.candidates):
            return None
        if index < last_durable_index:
            return None
        last_durable_index = index
        assigned_text[index].append(segment.text)

    for index, candidate in enumerate(draft.candidates):
        label = candidate.label.strip()
        body = candidate.body.strip()
        keywords = _normalize_keywords(candidate.keywords)
        expected_body = "".join(assigned_text[index]).strip()
        invalid = (
            not label
            or "\n" in label
            or "\r" in label
            or len(label) > label_max
            or not body
            or not expected_body
            or body != expected_body
            or keywords is None
            or len(keywords) != len(candidate.keywords)
            or (is_split and cl100k_token_count(body) > memory_max_tokens)
        )
        if invalid:
            return None
        if is_split and (label in labels or body in bodies):
            return None
        labels.add(label)
        bodies.add(body)
        children.append(MemorySplitChild(label=label, body=body, keywords=keywords))
    return children


def _normalize_keywords(values: Sequence[str]) -> list[str] | None:
    keywords: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip().lower()
        if not normalized:
            return None
        if normalized not in seen:
            keywords.append(normalized)
            seen.add(normalized)
    return keywords if 2 <= len(keywords) <= 5 else None
