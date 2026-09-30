"""Named Palace isolation and the irreversible-delete boundary."""

import io
import json
from dataclasses import replace

import pytest

from harness.onboarding import NocturneConfig, OnboardingError, _write_config, load_config
from harness.palaces import PalaceCloud, palace_home, palace_nocturne


def test_palace_name_reaches_sandboxed_modules_without_credentials():
    """SPEC D.2 166 / ADR-023: the public rack exposes only the selected Palace name."""
    from fastapi.testclient import TestClient

    from harness.daemon import create_app

    with TestClient(create_app(palace_name="test-learning")) as client:
        assert client.get("/v1/rack/query?resource=palace").json() == {
            "status": "live",
            "as_of": None,
            "data": "test-learning",
        }


def test_selection_preserves_main_identity_and_separates_journals(tmp_path, monkeypatch):
    """SPEC D.2 166: selecting another Palace never reuses main's local journal or identity."""
    monkeypatch.setenv("NOCTURNE_HOME", str(tmp_path))
    main = NocturneConfig(tmp_path, "broker", "main-token", "db", "main-machine")
    _write_config(main)
    original = (tmp_path / "env").read_bytes()
    other = palace_home(tmp_path, "test-learning")
    _write_config(
        replace(
            main,
            home=other,
            palace_name="test-learning",
            spine_token="other-token",
            principal_id="other-owner",
        )
    )

    class Cloud:
        def services(self):
            return {name: {} for name in ("main", "test-learning")}

    palace_nocturne("use", "test-learning", cloud=Cloud(), stdout=io.StringIO())
    selected = load_config()
    assert selected.home == other
    assert selected.principal_id == "other-owner"
    assert selected.process_environment()["NOCTURNE_PALACE_NAME"] == "test-learning"
    palace_nocturne("use", "main", cloud=Cloud(), stdout=io.StringIO())
    assert load_config().home == tmp_path
    assert (tmp_path / "env").read_bytes() == original


def test_main_and_invalid_names_refuse_before_cloud_mutation(tmp_path):
    """SPEC D.2 166: the main Palace cannot be dropped, including path/SQL aliases."""
    for name in ("main", "../main", "MAIN", "a/b", "x;drop database spine"):
        with pytest.raises(OnboardingError):
            PalaceCloud.resource(name)


def test_drop_names_count_and_cancel_preserves_everything(tmp_path, monkeypatch):
    """SPEC D.2 166: destructive confirmation identifies the Palace and its memory count."""
    monkeypatch.setenv("NOCTURNE_HOME", str(tmp_path))
    _write_config(NocturneConfig(tmp_path, "broker", "token", "db", "machine"))
    home = palace_home(tmp_path, "test-learning")
    home.mkdir(parents=True)
    record = {
        "database": "nocturne_palace_test_learning",
        "service": "nocturne-palace-test-learning",
    }
    (home / "custody.json").write_text(json.dumps(record))
    prompts = []

    class Cloud:
        resource = staticmethod(PalaceCloud.resource)

        def memory_count(self, observed):
            assert observed == record
            return 7

        def drop(self, name, observed):
            pytest.fail("cancel must not mutate the cloud")

    palace_nocturne(
        "drop",
        "test-learning",
        cloud=Cloud(),
        stdout=io.StringIO(),
        prompt=lambda message: prompts.append(message) or "no",
    )
    assert "test-learning and its 7 memories" in prompts[0]
    assert (home / "custody.json").exists()


def test_palace_for_url_names_owner_services_and_nothing_else():
    """SPEC D.2 166: a Palace URL is main, a named Palace, or not one of the owner's."""
    from harness.palaces import palace_for_url

    main = "https://n8-memory-palace-spine-713925718873.us-central1.run.app"
    assert palace_for_url(main) == "main"
    assert palace_for_url("https://n8-memory-palace-spine-7wq3wmgcoq-uc.a.run.app") == "main"
    assert palace_for_url("https://nocturne-palace-test-m3exf2-7wq3wmgcoq-uc.a.run.app") == (
        "test-m3exf2"
    )
    assert palace_for_url("https://nocturne-palace-test-a-713925718873.us-central1.run.app") == (
        "test-a"
    )
    for foreign in ("https://spine.example.test", "https://other-service-abc-uc.a.run.app", ""):
        assert palace_for_url(foreign) is None


def test_remote_init_against_a_named_palace_carries_its_name(tmp_path, monkeypatch):
    """SPEC D.2 166: an identity pointed at a test Palace never reports itself as main."""
    from harness import onboarding

    monkeypatch.setattr(onboarding, "_ensure_tool_runtimes", lambda home, stdout: None)
    for url, name in (
        ("https://nocturne-palace-test-m3exf2-7wq3wmgcoq-uc.a.run.app", "test-m3exf2"),
        ("https://spine.example.test", "main"),
    ):
        home = tmp_path / name
        onboarding.init_nocturne(
            home=home,
            remote=url,
            environ={"OPENROUTER_API_KEY": "broker", "SPINE_TOKEN": "bearer"},
            prompt=lambda message: "n",
            stdout=io.StringIO(),
        )
        config = load_config(home=home)
        assert config.palace_name == name
        assert config.process_environment({})["NOCTURNE_PALACE_NAME"] == name
