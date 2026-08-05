from __future__ import annotations

import re
import tomllib
from pathlib import Path

from harness import __version__
from harness.packaged import BUNDLED_WEB_DIST

ROOT = Path(__file__).resolve().parents[1]


def test_public_distribution_and_lockstep_dependency_metadata() -> None:
    """ADR-019 is defended by verifying that public distribution and lockstep dependency
    metadata; this prevents drift in the public package and bundled-owner-app contract.
    """
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = metadata["project"]

    assert project["name"] == "nocturne-ai"
    assert project["dynamic"] == ["version"]
    assert __version__ == "0.1.0"
    assert "nocturne-spine==0.1.0" in project["dependencies"]
    assert project["scripts"]["nocturne"] == "harness.cli:main"
    assert metadata["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"] == {
        "web/dist": "harness/_web"
    }
    assert metadata["tool"]["hatch"]["build"]["targets"]["sdist"]["include"] == [
        "/README.md",
        "/pyproject.toml",
        "/src/harness",
        "/web/dist",
    ]


def test_committed_web_build_has_every_referenced_asset() -> None:
    """ADR-019 is defended by verifying that committed web build has every referenced asset;
    this prevents drift in the public package and bundled-owner-app contract.
    """
    web_dist = ROOT / "web" / "dist"
    index = (web_dist / "index.html").read_text(encoding="utf-8")
    references = re.findall(r'(?:src|href)="/([^"?#]+)', index)

    assert references
    assert all((web_dist / reference).is_file() for reference in references)
    assert not any(path.name == "node_modules" for path in web_dist.rglob("*"))


def test_packaged_factory_uses_only_the_private_wheel_asset_path() -> None:
    """ADR-019 is defended by verifying that packaged factory uses only the private wheel asset
    path; this prevents drift in the public package and bundled-owner-app contract.
    """
    assert BUNDLED_WEB_DIST == Path(__file__).resolve().parents[1] / "src/harness/_web"
    assert "web/dist" not in BUNDLED_WEB_DIST.as_posix()
