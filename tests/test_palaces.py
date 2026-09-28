"""Named Palace isolation and the irreversible-delete boundary."""

import io
import json
from dataclasses import replace

import pytest

from harness.onboarding import NocturneConfig, OnboardingError, _write_config, load_config
from harness.palaces import PalaceCloud, palace_home, palace_nocturne


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
