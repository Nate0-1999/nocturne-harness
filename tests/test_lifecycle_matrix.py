from __future__ import annotations

import io
from dataclasses import dataclass
from itertools import product
from pathlib import Path
from types import SimpleNamespace

import pytest

from harness import onboarding


@dataclass(frozen=True, slots=True)
class LifecycleState:
    app: str
    palace: str
    guard: str
    journal: str
    port: str
    assets: str
    ground: str
    probe: str = "warm"

    @property
    def id(self) -> str:
        return "-".join(
            (
                self.app,
                self.palace,
                self.guard,
                self.journal,
                self.port,
                self.assets,
                self.ground,
                self.probe,
            )
        )

    @property
    def reachable(self) -> bool:
        return (self.app, self.guard) in {("released", "pass"), ("dev", "block")}


ALL_STATES = tuple(
    LifecycleState(*values)
    for values in product(
        ("released", "dev"),
        ("current", "behind", "ahead", "legacy"),
        ("pass", "block"),
        ("writable", "read-only"),
        ("free", "held-healthy", "held-dead"),
        ("present", "absent"),
        ("clean-room", "host"),
        ("warm", "cold"),
    )
)
REACHABLE_STATES = tuple(state for state in ALL_STATES if state.reachable)
UNREACHABLE_STATES = tuple(state for state in ALL_STATES if not state.reachable)

INCIDENT_ROWS = {
    "F016": LifecycleState("released", "behind", "pass", "writable", "free", "present", "host"),
    "F018": LifecycleState(
        "released", "behind", "pass", "writable", "free", "present", "clean-room"
    ),
    "F019": LifecycleState("released", "current", "pass", "writable", "free", "present", "host"),
    "F031": LifecycleState("dev", "current", "block", "writable", "free", "present", "host"),
    "M2V-503": LifecycleState("released", "current", "pass", "writable", "free", "absent", "host"),
    "M2CI-clean-room": LifecycleState(
        "released", "current", "pass", "writable", "free", "present", "clean-room"
    ),
    "prompt-guard-dead-end": LifecycleState(
        "dev", "legacy", "block", "writable", "free", "present", "host"
    ),
    "M2LC2-silent-preflight": LifecycleState(
        "dev", "legacy", "block", "writable", "free", "present", "host"
    ),
    "PALACE-COLD": LifecycleState(
        "released",
        "current",
        "pass",
        "writable",
        "free",
        "present",
        "host",
        "cold",
    ),
}


def _case_id(state: LifecycleState) -> str:
    incident = next((name for name, row in INCIDENT_ROWS.items() if row == state), None)
    return f"{incident or 'matrix'}::{state.id}"


class _Process:
    def poll(self) -> None:
        return None


def _expected_action(state: LifecycleState) -> str:
    if state.port == "held-healthy":
        return "adopt"
    if state.assets == "absent":
        return "refuse-assets"
    if state.port == "held-dead":
        return "refuse-port"
    if state.journal == "read-only":
        return "refuse-journal"
    if state.palace == "ahead":
        return "refuse-ahead"
    if state.palace in {"behind", "legacy"}:
        return "dev-start" if state.guard == "block" else "postpone-start"
    return "start"


def _expected_first_line(state: LifecycleState, action: str) -> str:
    if action == "adopt":
        return f"Nocturne is already running at {onboarding.LOCAL_URL}; using it."
    if action == "refuse-assets":
        return "Nocturne's web app is unavailable; reinstall Nocturne."
    if action == "refuse-port":
        return "Port 8765 is occupied by another process; stop that process."
    if action == "refuse-journal":
        return "Conversation journal is not writable"
    return onboarding.PALACE_CHECKING_LINE


@pytest.mark.parametrize("state", REACHABLE_STATES, ids=_case_id)
def test_every_reachable_lifecycle_state_has_one_voice_and_action(
    state: LifecycleState,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """SPEC D.2 112 and B.6 rule 12 require every reachable startup combination to
    have one table-tested voice and action; this prevents a later lifecycle guard from
    contradicting an earlier prompt.
    """

    config = onboarding.NocturneConfig(
        home=tmp_path,
        openrouter_api_key="openrouter-fixture",
        spine_token="palace-token",
        database_password="unused-local-password",
        machine_id="fixture-machine",
        palace_mode="remote",
        spine_url="https://spine.example.test",
    )
    events: list[str] = []
    failures: list[str] = []
    if state.assets == "absent":
        failures.append("Nocturne's web app is unavailable; reinstall Nocturne.")
    if state.port == "held-dead":
        failures.append("Port 8765 is occupied by another process; stop that process.")
    preflight = onboarding.DaemonPreflight(
        existing=state.port == "held-healthy",
        web_assets="ready" if state.assets == "present" else "not ready",
        port=state.port,
        toolchain=f"{state.ground} ready",
        failures=tuple(failures),
    )
    relation = {
        "current": ("0.1.7", "compatible"),
        "behind": ("0.0.9", "older"),
        "ahead": ("0.2.0", "newer"),
        "legacy": (None, "older"),
    }[state.palace]

    monkeypatch.setattr(onboarding, "load_config", lambda **kwargs: config)
    monkeypatch.setattr(onboarding, "_warn_if_low_disk", lambda *args, **kwargs: None)
    monkeypatch.setattr(onboarding, "_daemon_preflight", lambda candidate: preflight)

    def palace_status(
        candidate: onboarding.NocturneConfig,
        *,
        stdout: io.StringIO,
    ) -> tuple[str | None, str]:
        events.append("health")
        if state.probe == "cold":
            print(onboarding.PALACE_WARMING_LINE, file=stdout)
        return relation

    monkeypatch.setattr(onboarding, "_remote_palace_status", palace_status)
    monkeypatch.setattr(
        onboarding,
        "_require_writable_journal",
        lambda home: (
            (_ for _ in ()).throw(
                onboarding.OnboardingError("Conversation journal is not writable")
            )
            if state.journal == "read-only"
            else events.append("journal")
        ),
    )
    monkeypatch.setattr(
        "harness.deploy.preflight_release_guard",
        lambda **kwargs: (
            events.append("guard"),
            SimpleNamespace(blocked=state.guard == "block"),
        )[1],
    )
    monkeypatch.setattr(
        onboarding,
        "_start_service",
        lambda *args, **kwargs: (events.append("start"), _Process())[1],
    )
    monkeypatch.setattr(onboarding, "_wait_for_url", lambda *args, **kwargs: None)
    monkeypatch.setattr(onboarding, "_supervise", lambda processes: None)
    monkeypatch.setattr(onboarding, "_stop_processes", lambda processes: None)
    prompts: list[str] = []
    output = io.StringIO()

    action = _expected_action(state)
    if action.startswith("refuse-"):
        with pytest.raises(onboarding.OnboardingError) as caught:
            onboarding.up_nocturne(
                home=tmp_path,
                open_browser=False,
                prompt=lambda message: prompts.append(message) or "no",
                stdout=output,
            )
        rendered = str(caught.value)
    else:
        assert (
            onboarding.up_nocturne(
                home=tmp_path,
                open_browser=False,
                prompt=lambda message: prompts.append(message) or "no",
                stdout=output,
            )
            == 0
        )
        rendered = output.getvalue()

    spoken = output.getvalue() or rendered
    assert spoken.splitlines()[0] == _expected_first_line(state, action)
    assert onboarding.STARTUP_SPEAKING_BUDGET_SECONDS == 2.0

    if action == "adopt":
        assert "already running" in rendered
        assert events == []
    elif action == "refuse-assets":
        assert "web app is unavailable" in rendered
        assert events == []
    elif action == "refuse-port":
        assert "Port 8765 is occupied" in rendered
        assert events == []
    elif action == "refuse-journal":
        assert "Conversation journal is not writable" in rendered
        assert events == []
    elif action == "refuse-ahead":
        assert "app is older than your Palace" in rendered
        assert events == ["journal", "health"]
    elif action == "dev-start":
        expected = f"{onboarding.PALACE_CHECKING_LINE}\n"
        if state.probe == "cold":
            expected += f"{onboarding.PALACE_WARMING_LINE}\n"
        expected += (
            "Your app includes unreleased changes; your Palace is compatible; "
            "Nocturne will start normally.\n"
        )
        assert output.getvalue().startswith(expected)
        assert prompts == []
        assert events == ["journal", "health", "guard", "start"]
    elif action == "postpone-start":
        assert len(prompts) == 1
        assert "Update now?" in prompts[0]
        assert "update was postponed" in rendered
        assert events == ["journal", "health", "guard", "start"]
    else:
        assert prompts == []
        expected = f"{onboarding.PALACE_CHECKING_LINE}\n"
        if state.probe == "cold":
            expected += f"{onboarding.PALACE_WARMING_LINE}\n"
        expected += f"Nocturne is running at {onboarding.LOCAL_URL}. Press Ctrl-C to stop it.\n"
        assert rendered == expected
        assert events == ["journal", "health", "start"]


@pytest.mark.parametrize("state", UNREACHABLE_STATES, ids=lambda state: state.id)
def test_unreachable_lifecycle_states_are_asserted_unreachable(state: LifecycleState) -> None:
    """SPEC D.2 112 and B.6 rule 12 require impossible matrix combinations to be
    named rather than silently omitted, preserving the app/guard and running-daemon laws.
    """

    assert (state.app, state.guard) in {("released", "block"), ("dev", "pass")}


def test_each_historical_lifecycle_incident_is_a_named_reachable_row() -> None:
    """SPEC D.2 112 and B.6 rule 12 require F016, F018, F019, F031, M2V, M2CI,
    the prompt/guard dead end, and PALACE-COLD to remain named rows before their fixes may
    stay closed.
    """

    assert set(INCIDENT_ROWS) == {
        "F016",
        "F018",
        "F019",
        "F031",
        "M2V-503",
        "M2CI-clean-room",
        "prompt-guard-dead-end",
        "M2LC2-silent-preflight",
        "PALACE-COLD",
    }
    assert all(row in REACHABLE_STATES for row in INCIDENT_ROWS.values())
    assert len(ALL_STATES) == 768
    assert len(REACHABLE_STATES) == 384
    assert len(UNREACHABLE_STATES) == 384
