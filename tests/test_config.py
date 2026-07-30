import pytest
from pydantic import ValidationError

from harness.config import HarnessSettings


def test_c5_defaults_are_local_minimax_with_bounded_runs_and_spine(monkeypatch) -> None:
    for name in (
        "CHAT_MODEL",
        "MODEL_POLICY_CHAT",
        "SPINE_URL",
        "PRINCIPAL_ID",
        "MACHINE_ID",
        "AGENT_ID",
        "MODEL_CONTEXT_TOKENS",
        "RUN_REQUEST_LIMIT",
        "RUN_TOTAL_TOKENS_LIMIT",
        "LABEL_MAX",
    ):
        monkeypatch.delenv(name, raising=False)
    settings = HarnessSettings(
        _env_file=None,
        spine_token=None,
        anthropic_api_key=None,
        openai_api_key=None,
        openrouter_api_key=None,
    )

    assert settings.chat_model == "openrouter:minimax/minimax-m3"
    assert settings.model_policy_chat is None
    assert settings.effective_model_policy_chat == "pinned:openrouter:minimax/minimax-m3"
    assert settings.spine_url == "http://localhost:8000"
    assert settings.principal_id == "local"
    assert settings.machine_id == "local-machine"
    assert settings.agent_id == "harness-agent"
    assert settings.model_context_tokens == 1_000_000
    assert settings.run_request_limit == 40
    assert settings.run_total_tokens_limit == 500_000
    assert settings.label_max == 64


def test_settings_accept_environment_model_spine_and_limit_overrides(monkeypatch) -> None:
    monkeypatch.setenv("CHAT_MODEL", "anthropic:claude-sonnet-4-6")
    monkeypatch.setenv("MODEL_POLICY_CHAT", "elbow")
    monkeypatch.setenv("SPINE_URL", "https://spine.example.test")
    monkeypatch.setenv("PRINCIPAL_ID", "principal-test")
    monkeypatch.setenv("MACHINE_ID", "machine-test")
    monkeypatch.setenv("AGENT_ID", "agent-test")
    monkeypatch.setenv("MODEL_CONTEXT_TOKENS", "262144")
    monkeypatch.setenv("RUN_REQUEST_LIMIT", "12")
    monkeypatch.setenv("RUN_TOTAL_TOKENS_LIMIT", "3456")

    settings = HarnessSettings(_env_file=None)

    assert settings.chat_model == "anthropic:claude-sonnet-4-6"
    assert settings.model_policy_chat == "elbow"
    assert settings.effective_model_policy_chat == "elbow"
    assert settings.spine_url == "https://spine.example.test"
    assert settings.principal_id == "principal-test"
    assert settings.machine_id == "machine-test"
    assert settings.agent_id == "agent-test"
    assert settings.model_context_tokens == 262_144
    assert settings.run_request_limit == 12
    assert settings.run_total_tokens_limit == 3456


@pytest.mark.parametrize(
    "field",
    ["model_context_tokens", "run_request_limit", "run_total_tokens_limit", "label_max"],
)
def test_positive_configured_limits_are_enforced(field: str) -> None:
    with pytest.raises(ValidationError):
        HarnessSettings(_env_file=None, **{field: 0})


@pytest.mark.parametrize("value", [True, 1.5])
def test_model_context_tokens_requires_a_real_integer(value: object) -> None:
    with pytest.raises(ValidationError):
        HarnessSettings(_env_file=None, model_context_tokens=value)


@pytest.mark.parametrize("field", ["principal_id", "machine_id", "agent_id"])
def test_configured_runtime_identities_cannot_be_empty(field: str) -> None:
    with pytest.raises(ValidationError):
        HarnessSettings(_env_file=None, **{field: ""})


@pytest.mark.parametrize(
    "value",
    ["", " max", "MAX", "pinned:", "slope:0", "floor:NaN", "budget:10"],
)
def test_model_policy_chat_rejects_values_outside_a021(value: str) -> None:
    with pytest.raises(ValidationError):
        HarnessSettings(_env_file=None, model_policy_chat=value)


def test_superseded_model_policy_fields_do_not_exist() -> None:
    settings = HarnessSettings(_env_file=None)

    assert not hasattr(settings, "model_intelligence_floor")
    assert not hasattr(settings, "provider_quantizations")
