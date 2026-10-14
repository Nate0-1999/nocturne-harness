"""Bounded pydantic-ai chat and the direct C.6 `/remember` command."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr
from pydantic_ai import Agent, PromptedOutput, UsageLimits, capture_run_messages
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import RunUsage
from spine.tokens import cl100k_token_count

from harness.commands import remember_command_text
from harness.config import HarnessSettings
from harness.context_window import ReturnShareBounds, bounds_from
from harness.memory_outbox import QueuedForPalace, never_reached_palace
from harness.model_router import (
    CompletionRouter,
)
from harness.model_router import (
    ModelConfigurationError as ModelConfigurationError,
)
from harness.pydantic_ai_adapter import (
    MemoryCapability,
    ReturnShareCapability,
    WorkspaceCapability,
    adopted_skill_capabilities,
)
from harness.pydantic_harness_adapter import COMPACTION_SUMMARY_PROMPT
from harness.spine_client import (
    CreateMemoryConflictError,
    CreateMemoryRequest,
    DuplicateMemoryConflict,
    ListMemoriesParams,
    MemorySplitChild,
    MemorySplitRequest,
    MemorySplitResponse,
    MemoryStatus,
    MemoryUnit,
    PatchMemoryConflictError,
    PatchMemoryRequest,
    RevisionConflict,
    SearchRequest,
    SimilarMemoriesResponse,
    SpineClientError,
)
from harness.tools_memory import (
    MemoryToolContext,
    create_remembered_memory,
    create_remembered_memory_split,
    render_create_conflict,
    render_spine_error,
)

REMEMBER_DRAFT_INSTRUCTION = (
    "Generate one short label and 2-5 lowercase searchable keywords for the "
    "supplied memory. Identify whether it contains multiple distinct durable facts; set "
    "multiple_facts true only for independent facts, never merely because the text is long. "
    "A single rule can list several dates, alternatives or exceptions; these are values of "
    "the same rule, not separate facts. For example, a service being closed on two holidays "
    "is one closure schedule. Different subjects or independently stated properties are "
    "separate facts. "
    "Keywords must be distinct nouns or terms. Return only "
    "the requested structured result with no commentary."
)
REMEMBER_SPLIT_INSTRUCTION = (
    "Divide the complete /remember source into durable facts in source order. Write each as a "
    "self-contained fact sentence that names its own subject and keeps every claim and "
    "qualifier. Split only where there is more than one distinct fact; a fact over the body "
    "limit is broken at its cleanest seam into finer facts that each stand alone, and only "
    "repetition is shortened. Directions about remembering, saving or splitting are "
    "instructions for this operation, never facts. Give each candidate a short retrieval "
    "label (prefer 2-5 words and under 40 characters; 64 Unicode code points at most), 2-5 "
    "distinct lowercase searchable keywords, and a body within the supplied cl100k_base "
    "token limit. The application keeps the exact source; return only the candidates."
)
REMEMBER_SPLIT_GUIDANCE = (
    "Nothing was saved: the memory draft could not be completed. "
    "Your text is still in the composer; try again."
)
EXTRACTION_INSTRUCTION = (
    "Compact the supplied conversation in ONE pass, following the supplied summary strategy. "
    "Still-live context for the current work goes in working_summary and open_loops. In "
    "candidates, keep the things an agent continuing this problem in the future would want "
    "to know: write each as a self-contained fact sentence that names its own subject and "
    "gets at the problem and its solution concisely. If the information will not fit in one "
    "fact of at most 128 cl100k_base tokens, break it at the cleanest place into two or more "
    "facts that each stand alone. Give each independent fact its own candidate, even when "
    "several would fit together under the cap. Keep what the user stated, decided or "
    "corrected unless it "
    "only mattered for the moment. Leave out step-by-step progress and common knowledge. "
    "Never write a secret, credential, token, password or key into any field, not even to "
    "say that one was shared. A fact you derived lists in source_message_ids the message or "
    "tool result that verified it; a claim nothing in the conversation verified begins "
    "with 'Unverified:'. Give "
    "each candidate a label of at most 64 characters and 2-5 distinct lowercase keywords. "
    "Every transcript message has an id (its message_id or its [mN] label); list in each "
    "candidate's source_message_ids the ids of the messages its fact was drawn from."
)
SEED_SPLIT_INSTRUCTION = (
    "Semantically split the complete Markdown document into durable atomic memories. Preserve "
    "a stated correction as one change: keep its old and replacement values together, with "
    "the update relationship intact, rather than separating them into historical and current "
    "claims. The reviewer must see what changed. Preserve "
    "every durable claim without summarizing or mechanical token chopping. Every child must "
    "stand alone with no unresolved references, contain one claim, use at most 128 cl100k_base "
    "tokens, and include its own short label, kind, and 2-5 distinct lowercase searchable "
    "keywords. Return one to 64 children in source order and structured data only."
)


class RememberDraft(BaseModel):
    """One tools-free model completion for a `/remember` write."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    label: StrictStr
    keywords: list[StrictStr]
    multiple_facts: StrictBool = False


class RememberSplitCandidate(BaseModel):
    """One atomic fact proposed for a multi-fact or oversized `/remember`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    # WALL Palace writes / A-049: every split child must fit the atomic save contract.
    label: StrictStr = Field(
        min_length=1,
        max_length=64,
        description=(
            "A short retrieval handle, preferably 2-5 words and under 40 characters; one "
            "nonblank line with 64 Unicode code points as the hard maximum."
        ),
    )
    body: StrictStr = Field(
        description="One self-contained fact within the supplied token limit, keeping its "
        "meaning and qualifiers; a source fact within the limit is copied verbatim."
    )
    # WALL Palace writes / A-049: each split child keeps the required retrieval keywords.
    keywords: list[StrictStr] = Field(min_length=2, max_length=5)


class RememberSplitDraft(BaseModel):
    """The source-ordered facts of a multi-fact or oversized `/remember`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidates: list[RememberSplitCandidate]


class ExtractionCandidateDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    # WALL Palace writes / C.4: model retries must enforce the stored label limit.
    label: StrictStr = Field(min_length=1, max_length=64)
    body: StrictStr = Field(
        description="Exactly one independently editable fact. Two properties of the same "
        "subject are separate candidates: changing one must not require editing the other."
    )
    kind: Literal["fact", "preference", "procedure", "project_note", "persona"]
    # WALL Palace writes / ADR-022: extracted candidates retain the memory keyword contract.
    keywords: list[StrictStr] = Field(min_length=2, max_length=5)
    # SD-072: the messages a fact came from decide the folder its memory is born in.
    source_message_ids: list[StrictStr] = Field(
        default_factory=list,
        description="The ids of the transcript messages this fact was drawn from.",
    )


class ExtractionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    working_summary: StrictStr
    open_loops: list[StrictStr]
    # v2.133: no count cap; the curator, not the extractor, limits the Palace's growth.
    candidates: list[ExtractionCandidateDraft]


class SeedSplitDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    candidates: list[ExtractionCandidateDraft]


class ExtractionVerdictDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    verdict: Literal["new", "already_known", "merge", "supersede", "contradict"]
    target_ids: list[UUID] = Field(
        description="For already_known, cite the existing memory containing the fact. "
        "For merge/supersede/contradict, cite affected neighbors. Only new has no targets."
    )


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


class BoundaryIntent(BaseModel):
    """The PermissionJudge's reading of an explicit outside-path request: the paths it asks to
    change; the runtime checks which are outside the root. [ADR-015, F198]"""

    model_config = ConfigDict(extra="forbid")
    written_paths: list[StrictStr]
    reason: StrictStr


type DispatchResult = ChatResult | RememberResult


class HarnessAgent:
    """Own the chat agent, tools-free remember agent, and C.5 usage walls."""

    def __init__(
        self,
        settings: HarnessSettings,
        *,
        model: Model | None = None,
        router: CompletionRouter | None = None,
        skill_directories: Sequence[Path] = (),
    ) -> None:
        self._settings = settings
        self._router = router or CompletionRouter(settings)
        self._default_model = model
        self._skill_directories = tuple(skill_directories)
        self._models_by_name: dict[str, Model] = (
            {settings.chat_model: model} if model is not None else {}
        )
        # WALL money / C.5: enforce the owner's configured request and token budgets.
        self._usage_limits = UsageLimits(
            request_limit=settings.run_request_limit,
            total_tokens_limit=settings.run_total_tokens_limit,
        )
        # WALL money / A-049: oversized remember is explicitly limited to two requests.
        self._remember_split_usage_limits = UsageLimits(
            request_limit=2,
            total_tokens_limit=settings.run_total_tokens_limit,
        )
        chat_capabilities = [
            MemoryCapability(),
            ReturnShareCapability(),
        ]
        self._chat_agent = Agent(
            self._default_model,
            deps_type=MemoryToolContext,
            capabilities=chat_capabilities,
            name="harness-chat",
        )
        self._boundary_judge = Agent(
            self._default_model,
            output_type=PromptedOutput(BoundaryIntent),
            instructions=(
                "You are the PermissionJudge applying ADR-015 to an explicit outside-path request. "
                "List in written_paths every file or folder the user's request asks to create, "
                "edit, delete, or change with a command, as the user wrote it. A path that is only "
                "read, inspected, imported, installed from, depended on, mentioned, or the place "
                "a command runs is not written: leave it out. Committing writes only the files "
                "being committed. Classify the user's actual requested action, not quoted "
                "examples. Give the concrete reason in one sentence; do not ask a chat question."
            ),
            name="permission-judge",
        )
        self.worker_agent = Agent(
            self._default_model,
            deps_type=MemoryToolContext,
            capabilities=[WorkspaceCapability(), ReturnShareCapability()],
            instructions=(
                "Complete only the delegated task. Return a concise distillate: findings, "
                "evidence paths, and unresolved questions. Keep bulk output in files. "
                "You have no memory tools and may not make memories or address the owner."
            ),
            name="harness-worker",
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
            # INCIDENT F047: a malformed draft is retried once, then guidance; never a write.
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
                "Propose exactly one verdict: new, already_known, merge, supersede, or contradict. "
                "First check whether any neighbor already contains the candidate's fact. "
                "If so, use already_known and cite that neighbor's ID. This includes a rephrase "
                "or just one clause of a memory containing several facts: extracting one clause "
                "does not add information. Words like 'settled' do not make a fact new. "
                "Otherwise, use new with no targets for an independent fact. Shared subject "
                "words do not make different attributes the same fact. Merge only when the "
                "candidate adds information absent from the existing fact; "
                "supersede or contradict only when "
                "both statements give incompatible values for the same attribute. "
                "All target IDs must be selected from the supplied neighbors. "
                "Return structured data only."
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

    @property
    def memory_max_tokens(self) -> int:
        """The Palace's body cap, for code that marks a fact after the check loop."""

        return self._settings.memory_max_tokens

    @property
    def return_share_bounds(self) -> ReturnShareBounds:
        """FL-198: the system bounds on one return's share of the compaction limit."""
        return bounds_from(self._settings)

    def model_for(self, model: Model | str | None = None) -> Model:
        """Return one cached settings-owned model instance for a resolved route."""

        return self._select_model(model)

    def tool_capabilities(self, context: MemoryToolContext):
        """Select coding, browser and skills as one unit. [PLAN M3TH]"""
        if not context.toolset_enabled:
            return []
        return [
            WorkspaceCapability(),
            *adopted_skill_capabilities(context.skill_directories or self._skill_directories),
        ]

    async def judge_boundary(self, prompt: str, *, model, usage, model_settings):
        """Triage only explicit outside-path requests in a fresh, tools-free judge session."""
        return await self._boundary_judge.run(
            prompt,
            model=model,
            usage=usage,
            model_settings=model_settings,
            usage_limits=self._usage_limits,
        )

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
            capabilities=self.tool_capabilities(context),
            message_history=message_history,
            model=self._select_model(model),
            model_settings=model_settings,
            usage_limits=self._usage_limits,
        )
        return ChatResult(
            output=result.output,
            message_history=tuple(result.all_messages()),
        )

    async def remember(
        self,
        text: str,
        *,
        context: MemoryToolContext,
        force: bool = False,
        model: Model | str | None = None,
        model_settings: ModelSettings | None = None,
        usage: RunUsage | None = None,
        raise_model_errors: bool = False,
        captured_messages: list[ModelMessage] | None = None,
    ) -> RememberResult:
        """Generate one valid draft, save it in the thread project, and confirm honestly."""

        body = text.strip()
        # WALL money / C.6: an empty /remember must not purchase a metadata request.
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
                force=force,
            )
        try:
            draft_result = await _run_structured_agent(
                self._label_agent,
                f"Memory:\n{body}",
                model=selected_model,
                model_settings=model_settings,
                usage_limits=self._usage_limits,
                usage=remember_usage,
                captured_messages=captured_messages,
            )
        except Exception:
            if raise_model_errors:
                raise
            return RememberResult(False, "Could not remember: metadata generation failed.")

        draft = draft_result.output
        label = draft.label.strip()
        # WALL Palace writes / A-049: do not save generated metadata that loses the source handle.
        if not label:
            return RememberResult(False, "Could not remember: the generated label was blank.")
        if "\n" in label or "\r" in label:
            return RememberResult(
                False,
                "Could not remember: the generated label was not one line.",
            )
        if (
            draft.multiple_facts
            or len(label) > self._settings.label_max
            or fact_problems(body, self._settings.memory_max_tokens)
        ):
            return await self._split_or_guide_remember(
                body,
                context=context,
                model=selected_model,
                model_settings=model_settings,
                usage=remember_usage,
                raise_model_errors=raise_model_errors,
                captured_messages=captured_messages,
                force=force,
            )
        keywords = _normalize_keywords(draft.keywords)
        if keywords is None:
            # F165: a /remember lost its fact to keywords the person never sees. Generate them
            # once more, then keep the first five distinct terms; the label's words fill a short
            # list. Only a fact too short for two distinct terms is refused.
            retried: Sequence[str] = ()
            try:
                retry = await _run_structured_agent(
                    self._label_agent,
                    f"Memory:\n{body}\n\nThe last keywords {list(draft.keywords)!r} broke the "
                    "rule; give 2-5 distinct nonblank lowercase keywords.",
                    model=selected_model,
                    model_settings=model_settings,
                    usage_limits=self._usage_limits,
                    usage=remember_usage,
                    captured_messages=captured_messages,
                )
                retried = retry.output.keywords
            except Exception:
                pass  # the first draft's terms still save the fact
            keywords = _normalize_keywords(retried) or _repaired_keywords(
                [*retried, *draft.keywords], label, body
            )
            if keywords is None:
                return RememberResult(
                    False,
                    "Could not remember: add a few words to the fact so it can be found again.",
                )

        return await self._create_single_remember(
            body,
            label=label,
            keywords=keywords,
            context=context,
            force=force,
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
        force: bool = False,
    ) -> RememberResult:
        """Plan one semantic family, then write all children or guide without a write."""

        # M3MQ: a whole fact saved earlier must reinforce before a new splitter changes it.
        if cl100k_token_count(body) <= self._settings.memory_max_tokens:
            try:
                neighbors = await context.spine.search(
                    SearchRequest(principal_id=context.principal_id, query=body, k=5)
                )
            except SpineClientError as exc:
                # M4BW: unreached, the split still runs and waits in the outbox; the Palace
                # dedups the family when it arrives.
                if context.outbox is None or not never_reached_palace(exc):
                    return RememberResult(
                        False, f"Could not remember: {render_spine_error('search', exc)}"
                    )
                neighbors = None
            for neighbor in neighbors.results if neighbors is not None else ():
                if neighbor.body == body:
                    return await self._reinforce_duplicate_remember(context, neighbor.memory_id)

        try:
            # INCIDENT F047: bound the splitter that previously stranded oversized /remember.
            async with asyncio.timeout(self._settings.remember_split_timeout_seconds):
                requests_before = usage.requests
                try:
                    # F178: a stalled first request must leave time for the permitted second.
                    first_timeout = self._settings.remember_split_timeout_seconds / (
                        2 if requests_before == 0 else 1
                    )
                    async with asyncio.timeout(first_timeout):
                        draft_result = await _run_structured_agent(
                            self._remember_splitter_agent,
                            (
                                f"Label limit: {self._settings.label_max} Unicode code points\n"
                                f"Body limit: {self._settings.memory_max_tokens} "
                                "cl100k_base tokens\n"
                                f"Source length: {cl100k_token_count(body)} cl100k_base tokens\n"
                                f"Memory source:\n{body}"
                            ),
                            model=model,
                            model_settings=model_settings,
                            usage_limits=self._remember_split_usage_limits,
                            usage=usage,
                            captured_messages=captured_messages,
                        )
                except (UnexpectedModelBehavior, TimeoutError) as exc:
                    if isinstance(exc, TimeoutError):
                        # The SDK counts completed responses; the cancelled attempt still counts.
                        usage.requests = max(usage.requests, requests_before + 1)
                    if usage.requests >= 2:
                        raise
                    draft_result = None
                if usage.requests < 2 and (
                    draft_result is None or not draft_result.output.candidates
                ):
                    draft_result = await _run_structured_agent(
                        self._remember_splitter_agent,
                        "Your draft did not finish or returned no candidates. Re-read the "
                        f"source. Each body must fit {self._settings.memory_max_tokens} "
                        f"cl100k_base tokens and each label {self._settings.label_max} "
                        f"characters.\nMemory source:\n{body}",
                        model=model,
                        model_settings=model_settings,
                        usage_limits=self._remember_split_usage_limits,
                        usage=usage,
                        captured_messages=captured_messages,
                    )
        except TimeoutError:
            return RememberResult(
                False,
                "The memory draft took too long, so nothing was saved. "
                "Your text is still in the composer; try again.",
            )
        except UnexpectedModelBehavior:
            return RememberResult(False, REMEMBER_SPLIT_GUIDANCE)
        except Exception:
            if raise_model_errors:
                raise
            return RememberResult(False, REMEMBER_SPLIT_GUIDANCE)

        if draft_result.response.state != "complete" or not draft_result.output.candidates:
            return RememberResult(False, REMEMBER_SPLIT_GUIDANCE)
        try:
            async with asyncio.timeout(self._settings.remember_split_timeout_seconds):
                checked = await self._checked_facts(
                    self._remember_splitter_agent,
                    draft_result.output.candidates,
                    pieces_type=RememberSplitDraft,
                    model=model,
                    usage=usage,
                    model_settings=model_settings,
                    captured_messages=captured_messages,
                )
        except TimeoutError:
            return RememberResult(
                False,
                "The memory draft took too long, so nothing was saved. "
                "Your text is still in the composer; try again.",
            )
        except Exception:
            if raise_model_errors:
                raise
            return RememberResult(False, REMEMBER_SPLIT_GUIDANCE)
        children = _split_children(checked, label_max=self._settings.label_max)
        if children is None:
            return RememberResult(
                False,
                "Could not remember: add a few words to the fact so it can be found again.",
            )

        if len(children) == 1:
            child = children[0]
            return await self._create_single_remember(
                child.body,
                label=child.label,
                keywords=child.keywords,
                context=context,
                force=force,
            )

        return await self._create_split_remember(body, children, context=context)

    @staticmethod
    async def _create_split_remember(
        body: str,
        children: list[MemorySplitChild],
        *,
        context: MemoryToolContext,
        queued: MemorySplitRequest | None = None,
    ) -> RememberResult:
        """Write one split family, or say why none of it was saved."""

        try:
            response = await create_remembered_memory_split(
                context,
                source_body=body,
                children=children,
                queued=queued,
            )
        except QueuedForPalace as waiting:
            return RememberResult(True, str(waiting))
        except CreateMemoryConflictError as exc:
            return RememberResult(False, f"Could not remember: {render_create_conflict(exc)}")
        except SpineClientError as exc:
            if queued is not None:
                raise
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
    async def replay_remember(
        context: MemoryToolContext, payload: Mapping[str, object]
    ) -> str | None:
        """M4BW: a queued /remember meets the Palace's create law now (reinforce, ask, refuse).

        Returns what it did not accept, in its own words, or None when it was saved.
        """

        if payload["shape"] == "split":
            split = MemorySplitRequest.model_validate(payload["request"])
            result = await HarnessAgent._create_split_remember(
                split.source_body, split.children, context=context, queued=split
            )
        else:
            single = CreateMemoryRequest.model_validate(payload["request"])
            result = await HarnessAgent._create_single_remember(
                single.body,
                label=single.label,
                keywords=single.keywords,
                context=context,
                force=single.force,
                queued=single,
            )
        return None if result.ok else result.message

    @staticmethod
    async def _create_single_remember(
        body: str,
        *,
        label: str,
        keywords: list[str],
        context: MemoryToolContext,
        force: bool = False,
        queued: CreateMemoryRequest | None = None,
    ) -> RememberResult:
        """Persist the exact source through the unchanged ordinary create boundary."""

        try:
            response = await create_remembered_memory(
                context,
                label=label,
                body=body,
                keywords=keywords,
                force=force,
                queued=queued,
            )
        except QueuedForPalace as waiting:
            return RememberResult(True, str(waiting))
        except CreateMemoryConflictError as exc:
            if isinstance(exc.conflict, DuplicateMemoryConflict):
                return await HarnessAgent._reinforce_duplicate_remember(
                    context,
                    exc.conflict.duplicate_of.memory_id,
                )
            conflict = exc.conflict.label_conflict
            # A generated handle must not hide the Palace's semantic duplicate decision.
            source_label = body.splitlines()[0][:64].strip()
            if source_label != label:
                return await HarnessAgent._create_single_remember(
                    body,
                    label=source_label,
                    keywords=keywords,
                    context=context,
                    force=force,
                    queued=None
                    if queued is None
                    else queued.model_copy(update={"label": source_label}),
                )
            return RememberResult(
                False,
                "Not saved: that label already belongs to "
                f"{conflict.label!r}. Open Memory and edit the existing memory, or try "
                "/remember again with a more specific fact.",
            )
        except SpineClientError as exc:
            if queued is not None:
                raise  # an outbox replay stops here and keeps its place in the queue
            return RememberResult(False, f"Could not remember: {render_spine_error('save', exc)}")

        if isinstance(response, SimilarMemoriesResponse):
            if not response.similar:
                return RememberResult(False, "Not saved: Memory returned no similar memory.")
            existing = response.similar[0]
            similarity = f"{existing.score:.3f}" if existing.score is not None else "unavailable"
            return RememberResult(
                False,
                "Not saved: this looks similar to "
                f"{existing.label!r} (similarity {similarity}): {existing.body}\n\n"
                "Open Memory and edit that memory, or save anyway by sending:\n"
                f"`/remember --save-anyway {body}`",
            )
        created = response.created
        return RememberResult(
            True,
            f"Remembered {created.label!r} ({created.memory_id}).",
            memory_id=created.memory_id,
            label=created.label,
        )

    @staticmethod
    async def _reinforce_duplicate_remember(
        context: MemoryToolContext,
        memory_id: UUID,
    ) -> RememberResult:
        """Record one deliberate re-derivation through the existing CAS lineage seam."""

        try:
            target = await HarnessAgent._active_memory_by_id(context, memory_id)
        except SpineClientError as exc:
            return RememberResult(
                False,
                f"Could not reinforce the existing memory: {render_spine_error('refresh', exc)}",
            )
        if target is None:
            return RememberResult(
                False,
                "Not saved: the matching memory changed before it could be reinforced. "
                "Refresh Memory and try again.",
            )
        previous_reinforcements = _reinforcement_count(target)
        if previous_reinforcements is None:
            return RememberResult(
                False,
                "Not saved: the matching memory has invalid reinforcement history. "
                "Refresh Memory and try again.",
            )

        try:
            updated = await context.spine.patch_memory(
                target.memory_id,
                PatchMemoryRequest(
                    expected_revision=target.revision,
                    body=target.body,
                    editor="user",
                    reason="remember/reinforce",
                    machine_id=context.machine_id,
                ),
            )
        except PatchMemoryConflictError as exc:
            if isinstance(exc.conflict, RevisionConflict):
                return RememberResult(
                    False,
                    "Not saved: the matching memory changed before it could be reinforced. "
                    "Review its latest body in Memory, then try again.",
                )
            return RememberResult(
                False,
                "Not saved: the matching memory could not be reinforced because it now "
                "conflicts with another memory. Review it in Memory.",
            )
        except SpineClientError as exc:
            return RememberResult(
                False,
                f"Could not reinforce the existing memory: {render_spine_error('save', exc)}",
            )

        if (
            updated.memory_id != target.memory_id
            or updated.principal_id != context.principal_id
            or updated.status is not MemoryStatus.ACTIVE
            or updated.body != target.body
            or updated.revision != target.revision + 1
            or _reinforcement_count(updated) != previous_reinforcements + 1
        ):
            return RememberResult(
                False,
                "Not saved: Memory did not confirm the reinforcement. Refresh and try again.",
            )
        return RememberResult(
            True,
            f"Already known — reinforced {updated.label!r}.",
            memory_id=updated.memory_id,
            label=updated.label,
        )

    @staticmethod
    async def _active_memory_by_id(
        context: MemoryToolContext,
        memory_id: UUID,
    ) -> MemoryUnit | None:
        offset = 0
        while True:
            page = await context.spine.list_memories(
                ListMemoriesParams(status=MemoryStatus.ACTIVE, limit=200, offset=offset)
            )
            for memory in page.items:
                if (
                    memory.memory_id == memory_id
                    and memory.principal_id == context.principal_id
                    and memory.status is MemoryStatus.ACTIVE
                ):
                    return memory
            if not page.items or offset + len(page.items) >= page.total:
                return None
            offset += len(page.items)

    async def extract_thread(
        self,
        transcript: str,
        *,
        model: Model | str | None = None,
        usage: RunUsage | None = None,
        model_settings: ModelSettings | None = None,
        on_result=None,
        summary_prompt: str = COMPACTION_SUMMARY_PROMPT,
    ) -> ExtractionDraft:
        """Run the tools-free cheap-model extraction pass over one durable transcript."""

        extraction_settings = {
            **(model_settings or {}),
            "openrouter_usage": {"include": True},
            "temperature": 0,
        }
        result = await self._extraction_agent.run(
            summary_prompt.replace("{messages}", transcript),
            model=self._select_model(model),
            usage_limits=self._usage_limits,
            usage=usage,
            model_settings=extraction_settings,
        )
        if on_result is not None:
            await on_result(result.all_messages())
        # INCIDENT M3EX-22: one shortening pass left a fact over the cap; v2.133 repairs instead.
        candidates = await self._checked_facts(
            self._extraction_agent,
            result.output.candidates,
            pieces_type=SeedSplitDraft,
            model=self._select_model(model),
            usage=usage if usage is not None else RunUsage(),
            model_settings=extraction_settings,
            on_result=on_result,
        )
        return result.output.model_copy(update={"candidates": candidates})

    async def _checked_facts(
        self,
        agent: Agent[Any, Any],
        facts: Sequence[Any],
        *,
        pieces_type: type[BaseModel],
        model: Model,
        usage: RunUsage,
        model_settings: ModelSettings | None,
        on_result=None,
        captured_messages: list[ModelMessage] | None = None,
    ) -> list[Any]:
        """v2.133: one loop for compaction, /remember and seeds. A fact that fails a check goes
        back through the SAME prompt with the rule it broke, up to three rounds; then the
        shortest valid form is saved, any secret replaced. Never a silent drop, never a bare
        refusal; only a fact that was nothing but a secret may be withdrawn."""

        limit = self._settings.memory_max_tokens
        checked: list[Any] = []
        for fact in facts:
            pieces = [fact]
            for _ in range(3):
                if not any(fact_problems(piece.body, limit) for piece in pieces):
                    break
                repaired: list[Any] = []
                for piece in pieces:
                    problems = fact_problems(piece.body, limit)
                    if not problems:
                        repaired.append(piece)
                        continue
                    try:
                        result = await _run_structured_agent(
                            agent,
                            "; ".join(problems).capitalize()
                            + ". Split it finer first and shorten only repetition. Return the "
                            "memories that replace it, each standing alone:\n"
                            + piece.model_dump_json(exclude={"source_message_ids"}),
                            model=model,
                            model_settings=model_settings,
                            usage_limits=self._usage_limits,
                            usage=usage,
                            captured_messages=captured_messages,
                            output_type=pieces_type,
                        )
                    except UnexpectedModelBehavior:
                        repaired.append(piece)
                        continue
                    if on_result is not None:
                        await on_result(result.all_messages())
                    replacements = [_with_sources(item, piece) for item in result.output.candidates]
                    # A fact that was only a secret is withdrawn; any other is never dropped.
                    if replacements or LEAVE_SECRET_OUT not in problems:
                        repaired.extend(replacements or [piece])
                pieces = repaired
            checked.extend(
                piece.model_copy(
                    update={
                        "body": _within_cap(
                            _SECRET.sub("[secret left out]", piece.body.strip()), limit
                        )
                    }
                )
                for piece in pieces
            )
        return checked

    async def propose_extraction_verdict(
        self,
        candidate: ExtractionCandidateDraft,
        neighbors: list[dict[str, str]],
        *,
        model: Model | str | None = None,
        usage: RunUsage | None = None,
        on_result=None,
        model_settings: ModelSettings | None = None,
    ) -> ExtractionVerdictDraft:
        """Give the thread-aware extractor the corpus neighborhood before queue birth."""

        result = await self._extraction_verdict_agent.run(
            f"Candidate: {candidate.model_dump_json()}\nNeighbors: {neighbors!r}",
            model=self._select_model(model),
            usage_limits=self._usage_limits,
            usage=usage,
            model_settings={
                "openrouter_usage": {"include": True},
                **(model_settings or {}),
                "temperature": 0,
            },
        )
        if on_result is not None:
            await on_result(result.all_messages())
        allowed = {UUID(item["memory_id"]) for item in neighbors}
        output = result.output
        if any(target not in allowed for target in output.target_ids) or (
            output.verdict == "new"
        ) == bool(output.target_ids):
            # WALL Palace writes / ADR-022: affect only fetched candidates. INCIDENT M3EX-22:
            # an unusable verdict is the owner's new card, never a failed archive.
            return ExtractionVerdictDraft(verdict="new", target_ids=[])
        return output

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
        for candidate in result.output.candidates:
            invalid_label = (
                not candidate.label.strip()
                or len(candidate.label.strip()) > self._settings.label_max
            )
            if invalid_label:
                # WALL Palace writes / A-033: validate a whole seed batch before creating any child.
                raise ValueError("seed splitter produced an invalid label")
            if _normalize_keywords(candidate.keywords) is None:
                # WALL Palace writes / A-033: validate a whole seed batch before creating any child.
                raise ValueError("seed splitter produced invalid keywords")
        candidates = await self._checked_facts(
            self._seed_splitter_agent,
            result.output.candidates,
            pieces_type=SeedSplitDraft,
            model=self._select_model(model),
            usage=RunUsage(),
            model_settings=None,
        )
        return result.output.model_copy(update={"candidates": candidates})

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
            force = remembered_text.startswith("--save-anyway ")
            if force:
                remembered_text = remembered_text.removeprefix("--save-anyway ").strip()
            return await self.remember(
                remembered_text,
                context=context,
                force=force,
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
            resolved = self._router.model_for(model)
            self._models_by_name[model] = resolved
        return resolved


def resolve_model(model: Model | str, settings: HarnessSettings) -> Model:
    """Compatibility wrapper over the explicit completion-router seam."""

    if not isinstance(model, str):
        return model
    return CompletionRouter(settings).model_for(model)


async def _run_structured_agent(
    agent: Agent[None, Any],
    prompt: str,
    *,
    model: Model,
    model_settings: ModelSettings | None,
    usage_limits: UsageLimits,
    usage: RunUsage,
    captured_messages: list[ModelMessage] | None,
    output_type: Any = None,
) -> Any:
    """Run one structured pass and append its complete messages to a caller-owned turn sink."""

    async def run() -> Any:
        return await agent.run(
            prompt,
            model=model,
            model_settings=model_settings,
            usage_limits=usage_limits,
            usage=usage,
            **({} if output_type is None else {"output_type": PromptedOutput(output_type)}),
        )

    if captured_messages is None:
        return await run()
    with capture_run_messages() as call_messages:
        try:
            return await run()
        finally:
            captured_messages.extend(call_messages)


TOO_LONG = "this memory is too long, break it down into finer pieces"
# v2.133: a fact opening on a bare pronoun leans on context it does not carry.
_BARE_PRONOUNS = frozenset(
    {"it", "its", "they", "them", "their", "theirs", "he", "him", "his", "she", "her", "hers"}
)
_LIST_ITEM = re.compile(r"(?m)^\s*(?:[-*\u2022]|\d+[.)])\s")
# v2.133 "secrets left out": the credential shapes a fact must never carry to the Palace.
_SECRET = re.compile(
    r"\b(?:(?:sk|pk|rk)-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9]{16,}|github_pat_\w{20,}"
    r"|xox[abprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,}"
    r"|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})"
)
LEAVE_SECRET_OUT = "this memory contains a secret; leave the secret out"


def fact_problems(body: str, memory_max_tokens: int) -> list[str]:
    """v2.133 THE CHECK BEFORE THE PALACE: fits the cap, names its own subject, one claim."""

    problems = []
    if cl100k_token_count(body) > memory_max_tokens:
        problems.append(TOO_LONG)
    opener = re.match(r"\W*(\w+)", body)
    if opener is None or opener.group(1).lower() in _BARE_PRONOUNS:
        problems.append(
            "this memory does not name its own subject; begin it with the thing it is about"
        )
    if len(_LIST_ITEM.findall(body)) > 1:
        problems.append("this memory lists several claims; give each claim its own memory")
    if _SECRET.search(body):
        problems.append(LEAVE_SECRET_OUT)
    return problems


def _within_cap(body: str, memory_max_tokens: int) -> str:
    """The form saved when three repairs still leave a fact over the cap: its longest
    whole-word opening that fits, ended at a sentence where one closes past halfway."""

    if cl100k_token_count(body) <= memory_max_tokens:
        return body
    words = body.split()
    low, high = 1, len(words)
    while low < high:
        middle = (low + high + 1) // 2
        if cl100k_token_count(" ".join(words[:middle]) + "\u2026") <= memory_max_tokens:
            low = middle
        else:
            high = middle - 1
    opening = " ".join(words[:low])
    sentence_end = max(opening.rfind(". "), opening.rfind("; "))
    if sentence_end > len(opening) // 2:
        return opening[: sentence_end + 1]
    return opening + "\u2026"


def _with_sources(piece: Any, parent: Any) -> Any:
    """A repaired piece keeps the messages its parent fact was drawn from."""

    if getattr(piece, "source_message_ids", None) == [] and getattr(
        parent, "source_message_ids", None
    ):
        return piece.model_copy(update={"source_message_ids": list(parent.source_message_ids)})
    return piece


def _split_children(
    candidates: Sequence[RememberSplitCandidate], *, label_max: int
) -> list[MemorySplitChild] | None:
    """v2.133: checked facts become one family; the Palace keeps the exact source beside it."""

    children: list[MemorySplitChild] = []
    labels: set[str] = set()
    bodies: set[str] = set()
    for candidate in candidates:
        body = candidate.body.strip()
        if not body or body in bodies:
            continue  # an exact repeat adds nothing the family does not already hold
        label = (candidate.label.strip().splitlines() or [""])[0][:label_max].strip()
        if not label or label in labels:
            label = f"{label or body.splitlines()[0]}"[: label_max - 4].strip()
            label = f"{label} ({len(children) + 1})"
        keywords = _normalize_keywords(candidate.keywords) or _repaired_keywords(
            candidate.keywords, label, body
        )
        if keywords is None:
            return None
        labels.add(label)
        bodies.add(body)
        children.append(MemorySplitChild(label=label, body=body, keywords=keywords))
    return children or None


def _normalize_keywords(values: Sequence[str]) -> list[str] | None:
    # WALL Palace writes / A-049: require the indexed terms promised by an atomic remember.
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


def _repaired_keywords(generated: Sequence[str], *fallbacks: str) -> list[str] | None:
    # F165: the first five distinct generated terms; words of the fallbacks fill to two.
    keywords: list[str] = []
    for value in generated:
        term = value.strip().lower()
        if term and term not in keywords and len(keywords) < 5:
            keywords.append(term)
    for word in (word for text in fallbacks for word in re.findall(r"\w+", text.lower())):
        if len(keywords) >= 2:
            break
        if word not in keywords:
            keywords.append(word)
    return keywords if len(keywords) >= 2 else None


def _reinforcement_count(memory: MemoryUnit) -> int | None:
    value = memory.stats.get("reinforcements", 0)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value
