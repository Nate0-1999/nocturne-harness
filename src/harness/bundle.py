"""A-084 / SD-092: a workflow as a folder (recipe, skills, tools, key names) and its vault."""

from __future__ import annotations

import asyncio
import hashlib
import io
import os
import re
import shlex
import shutil
import signal
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path

from spine.jobs import BundleRecord, BundleTool, WorkflowDefinition

from harness.onboarding import OnboardingError, _atomic_write_config, nocturne_home
from harness.toolset import ToolsetError

_PARTS = ("workflow.json", "keys.example", "tools", ".agents/skills")
_LITTER = frozenset({"__pycache__", ".DS_Store"})
_KEY_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_OPERATORS = frozenset("();<>|&")
# The tool reads its keys and the owner's PATH; nothing else of the daemon's environment.
_TOOL_ENVIRONMENT = ("PATH", "LANG", "HOME")


def vault_path(workflow: str, home: Path | None = None) -> Path:
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", workflow).strip("-.")
    if not name:
        raise OnboardingError("Name the workflow whose vault this is.")
    return (home or nocturne_home()) / "vault" / f"{name}.env"


def read_vault(workflow: str, home: Path | None = None) -> dict[str, str]:
    path = vault_path(workflow, home)
    try:
        lines = path.read_text().splitlines() if path.exists() else []
    except OSError as exc:
        # WALL credentials / A-084: an agent's shell cannot read the vault.
        raise OnboardingError(
            "The vault is sealed from an agent's shell. In a saved job, run a bundle tool as "
            "one plain command: nocturne tool run <name> [args]."
        ) from exc
    return dict(line.split("=", 1) for line in lines if "=" in line)


def set_vault(workflow: str, name: str, value: str, home: Path | None = None) -> Path:
    if not _KEY_NAME.fullmatch(name):
        raise OnboardingError("A key name is letters, digits and underscores, like API_KEY.")
    if not value or "\n" in value:
        raise OnboardingError("Pipe the key's value, one line, into `nocturne vault set`.")
    values = {**read_vault(workflow, home), name: value}
    path = vault_path(workflow, home)
    _atomic_write_config(path, "".join(f"{key}={item}\n" for key, item in values.items()))
    return path


def bundle_definition(root: Path) -> WorkflowDefinition:
    """The folder's recipe, working in the folder itself."""
    try:
        definition = WorkflowDefinition.model_validate_json((root / "workflow.json").read_text())
    except (OSError, ValueError) as exc:
        raise OnboardingError(f"Cannot read workflow: {exc}") from exc
    if definition.bundle is not None:
        raise OnboardingError("workflow.json never carries `bundle`; `jobs save` records it.")
    if Path(definition.folder) != Path("."):
        raise OnboardingError('A bundle works in its own folder: set "folder" to ".".')
    return definition.model_copy(update={"folder": str(root)})


def _files(root: Path) -> list[Path]:
    found: list[Path] = []
    for part in _PARTS:
        path = root / part
        found.extend(
            item
            for item in ([path] if not path.is_dir() else sorted(path.rglob("*")))
            if (item.is_symlink() or item.exists())
            and not item.is_dir()
            and not _LITTER.intersection(item.relative_to(root).parts)
        )
    for item in found:
        name = item.relative_to(root)
        if item.is_symlink() or not item.is_file():
            raise OnboardingError(f"A bundle carries plain files only: {name}")
        if item.name == ".env" or item.name.startswith(".env."):
            # WALL credentials / A-084: key values live in the vault, never in the bundle.
            raise OnboardingError(f"Keys live in the vault, never in the bundle: {name}")
    return found


def pack(root: Path) -> bytes:
    """One plain tar of the bundle's parts: same bytes, same digest, on any machine."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.GNU_FORMAT) as archive:
        for item in _files(root):
            info = tarfile.TarInfo(item.relative_to(root).as_posix())
            data = item.read_bytes()
            info.size, info.mode = len(data), 0o755 if os.access(item, os.X_OK) else 0o644
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def digest(root: Path) -> str:
    return "sha256:" + hashlib.sha256(pack(root)).hexdigest()


def key_names(root: Path) -> list[str]:
    path = root / "keys.example"
    names = []
    for line in path.read_text().splitlines() if path.is_file() else []:
        name, _, value = line.strip().partition("=")
        if not name or name.startswith("#"):
            continue
        if value.strip() or not _KEY_NAME.fullmatch(name.strip()):
            # Never echo the line: it may hold a value someone pasted by mistake.
            raise OnboardingError(
                "keys.example lists key NAMES only, one per line; values go in the vault "
                "with `nocturne vault set`."
            )
        names.append(name.strip())
    return names


def _summary(tool: Path) -> str:
    """The first line the tool prints for --help: what the agent reads about it."""
    if not os.access(tool, os.X_OK):
        raise OnboardingError(f"tools/{tool.name} is not executable; run chmod +x on it.")
    try:
        shown = subprocess.run(
            [str(tool), "--help"],
            capture_output=True,
            text=True,
            timeout=30,
            stdin=subprocess.DEVNULL,
            env={name: os.environ[name] for name in _TOOL_ENVIRONMENT if name in os.environ},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OnboardingError(f"tools/{tool.name} --help did not run: {exc}") from exc
    lines = [line.strip() for line in (shown.stdout or shown.stderr).splitlines() if line.strip()]
    if not lines:
        raise OnboardingError(
            f"tools/{tool.name} --help printed nothing; its first line tells the agent "
            "what the tool does."
        )
    return lines[0][:200]


def bundle_record(root: Path) -> BundleRecord:
    tools = root / "tools"
    return BundleRecord(
        digest=digest(root),
        tools=[
            BundleTool(name=tool.name, summary=_summary(tool))
            for tool in (sorted(tools.iterdir()) if tools.is_dir() else [])
            if tool.is_file() and tool.name not in _LITTER
        ],
        keys=key_names(root),
    )


def check(root: Path, home: Path | None = None) -> tuple[WorkflowDefinition, BundleRecord]:
    """The recipe is valid, every tool runs, and every named key is in the vault."""
    definition = bundle_definition(root)
    record = bundle_record(root)
    held = read_vault(definition.name, home)
    if missing := [name for name in record.keys if name not in held]:
        raise OnboardingError(
            "The vault lacks "
            + ", ".join(missing)
            + f". Set each with: nocturne vault set {shlex.quote(definition.name)} <NAME>"
        )
    return definition, record


@dataclass(frozen=True, slots=True)
class SealedTools:
    """A saved job's tools, copied where its agent cannot write, run with its vault's keys."""

    directory: Path
    names: frozenset[str]
    workflow: str

    @classmethod
    def seal(cls, root: Path, record: BundleRecord, workflow: str) -> SealedTools:
        if digest(root) != record.digest:
            # ADR-015: only what the owner saved runs with the owner's keys.
            raise ValueError(
                "The bundle changed since it was saved; save its folder again with "
                "`nocturne jobs save <folder> --job-id <id>`."
            )
        directory = Path(tempfile.mkdtemp(prefix="nocturne-tools-"))
        if (root / "tools").is_dir():
            shutil.copytree(root / "tools", directory / "tools")
        return cls(directory, frozenset(tool.name for tool in record.tools), workflow)

    def close(self) -> None:
        shutil.rmtree(self.directory, ignore_errors=True)

    def call(self, command: object) -> list[str] | None:
        """The tool and its arguments when the whole command is `nocturne tool run …`."""
        if not isinstance(command, str):
            return None
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        try:
            words = list(lexer)
        except ValueError:
            return None
        if words[:3] != ["nocturne", "tool", "run"]:
            return None
        if len(words) < 4 or words[3] not in self.names:
            raise ToolsetError(
                "This workflow's tools are: " + (", ".join(sorted(self.names)) or "none") + "."
            )
        if any(word and _OPERATORS.issuperset(word) for word in words):
            raise ToolsetError(
                "Run a bundle tool as one plain command, `nocturne tool run <name> [args]`, "
                "with no pipe or redirect; its output comes back to you."
            )
        return words[3:]

    async def run(self, call: list[str], *, cwd: Path, timeout: float | None) -> str:
        """Owner's code, outside the agent's fence; the keys exist in this process only."""
        vault = read_vault(self.workflow)
        process = await asyncio.create_subprocess_exec(
            str(self.directory / "tools" / call[0]),
            *call[1:],
            cwd=cwd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env={
                **{name: os.environ[name] for name in _TOOL_ENVIRONMENT if name in os.environ},
                **vault,
            },
            start_new_session=True,
        )
        try:
            output, _ = await asyncio.wait_for(process.communicate(), timeout)
        except (asyncio.CancelledError, TimeoutError) as exc:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except OSError:
                pass
            await process.wait()
            if isinstance(exc, TimeoutError):
                raise ToolsetError(f"{call[0]} ran past its {timeout} second limit.") from None
            raise
        text = output.decode(errors="replace")
        for name, value in vault.items():
            # WALL credentials / A-084: a tool that prints its key does not hand it to the agent.
            text = text.replace(value, f"[vault:{name}]")
        text = text[:200_000]  # WALL money / F034: tool output enters paid context.
        return text if process.returncode == 0 else f"{text}\nExit code: {process.returncode}"
