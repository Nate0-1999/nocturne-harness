from __future__ import annotations

import stat
from pathlib import Path

import pytest

from harness import onboarding


def _v1_config() -> str:
    return """NOCTURNE_CONFIG_VERSION="1"
OPENROUTER_API_KEY="owner-secret"
SPINE_TOKEN="spine-secret"
NOCTURNE_DB_PASSWORD="database-secret"
NOCTURNE_POSTGRES_PORT="5432"
MACHINE_ID="owner-machine"
"""


def test_v1_config_upgrades_atomically_without_replacing_owner_values(tmp_path: Path) -> None:
    """A-041 preserves every owner value while adding bounded backup retention."""
    path = tmp_path / "env"
    tmp_path.chmod(0o700)
    path.write_text(_v1_config())
    path.chmod(0o600)

    config = onboarding.load_config(home=tmp_path)
    upgraded = path.read_text()

    assert config.backup_generations == 5
    assert 'NOCTURNE_CONFIG_VERSION="4"' in upgraded
    assert 'NOCTURNE_BACKUP_GENERATIONS="5"' in upgraded
    assert f'NOCTURNE_POSTGRES_VOLUME="{config.active_postgres_volume}"' in upgraded
    assert 'NOCTURNE_PALACE_MODE="local"' in upgraded
    assert 'SPINE_URL="http://127.0.0.1:8000"' in upgraded
    for owner_line in _v1_config().splitlines()[1:]:
        assert owner_line in upgraded
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not list(tmp_path.glob(".env.*"))


def test_future_config_is_refused_without_mutation(tmp_path: Path) -> None:
    """A-041 prevents an older binary from guessing at future config law or rewriting secrets."""
    path = tmp_path / "env"
    source = _v1_config().replace('VERSION="1"', 'VERSION="99"')
    path.write_text(source)
    path.chmod(0o600)

    with pytest.raises(onboarding.OnboardingError, match="Unsupported Nocturne config version"):
        onboarding.load_config(home=tmp_path)

    assert path.read_text() == source


def test_v2_config_adds_the_existing_compose_volume_without_changing_owner_values(
    tmp_path: Path,
) -> None:
    """A-045 makes the side-by-side switch durable without orphaning the current Palace."""
    path = tmp_path / "env"
    source = _v1_config().replace('VERSION="1"', 'VERSION="2"')
    source += 'NOCTURNE_BACKUP_GENERATIONS="7"\n'
    path.write_text(source)
    path.chmod(0o600)

    config = onboarding.load_config(home=tmp_path)

    assert config.backup_generations == 7
    assert config.active_postgres_volume == f"{config.compose_project}_nocturne_postgres"
    assert 'NOCTURNE_CONFIG_VERSION="4"' in path.read_text()
    assert "owner-secret" in path.read_text()


def test_v3_config_makes_its_existing_local_palace_explicit(tmp_path: Path) -> None:
    """M2S upgrades existing owners into the capability ladder without changing their rung."""

    path = tmp_path / "env"
    source = _v1_config().replace('VERSION="1"', 'VERSION="3"')
    source += 'NOCTURNE_BACKUP_GENERATIONS="5"\n'
    source += (
        f'NOCTURNE_POSTGRES_VOLUME="{onboarding._compose_project(tmp_path)}_nocturne_postgres"\n'
    )
    path.write_text(source)
    path.chmod(0o600)

    config = onboarding.load_config(home=tmp_path)

    assert config.palace_mode == "local"
    assert config.spine_url == onboarding.SPINE_URL
    assert 'NOCTURNE_CONFIG_VERSION="4"' in path.read_text()


@pytest.mark.parametrize("value", ["0", "51", "many"])
def test_config_rejects_invalid_backup_retention(tmp_path: Path, value: str) -> None:
    """A-041 bounds retained generations so lifecycle configuration cannot be inert or unbounded."""
    path = tmp_path / "env"
    source = _v1_config().replace('VERSION="1"', 'VERSION="2"')
    path.write_text(source + f'NOCTURNE_BACKUP_GENERATIONS="{value}"\n')
    path.chmod(0o600)

    with pytest.raises(onboarding.OnboardingError, match="NOCTURNE_BACKUP_GENERATIONS"):
        onboarding.load_config(home=tmp_path)
