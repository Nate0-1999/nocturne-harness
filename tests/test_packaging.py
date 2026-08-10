from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

from harness import __version__, packaged
from harness.packaged import BUNDLED_WEB_DIST

ROOT = Path(__file__).resolve().parents[1]


def test_public_distribution_and_lockstep_dependency_metadata() -> None:
    """F031 and SPEC D.2 100 keep the public 0.1.1 package in Spine lockstep."""
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = metadata["project"]

    assert project["name"] == "nocturne-ai"
    assert project["dynamic"] == ["version"]
    assert __version__ == "0.1.1"
    assert "nocturne-spine==0.1.1" in project["dependencies"]
    assert project["scripts"]["nocturne"] == "harness.cli:main"
    assert metadata["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"] == {
        "web/dist": "harness/_web"
    }
    assert metadata["tool"]["hatch"]["build"]["targets"]["sdist"]["include"] == [
        "/CHANGELOG.md",
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


def test_wheel_bundle_keeps_its_private_asset_path() -> None:
    """ADR-019 keeps the built wheel's web bundle private to its package path."""
    assert BUNDLED_WEB_DIST == Path(__file__).resolve().parents[1] / "src/harness/_web"
    assert "web/dist" not in BUNDLED_WEB_DIST.as_posix()


def test_editable_checkout_uses_its_canonical_web_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-019 keeps source-checkout startup equivalent to the bundled owner app."""

    bundled = tmp_path / "src" / "harness" / "_web"
    web_root = tmp_path / "web"
    (web_root / "dist").mkdir(parents=True)
    (web_root / "package.json").write_text("{}", encoding="utf-8")
    (web_root / "dist" / "index.html").write_text("owner rack", encoding="utf-8")
    monkeypatch.setattr(packaged, "BUNDLED_WEB_DIST", bundled)
    monkeypatch.setattr(packaged, "_CANONICAL_WEB_ROOT", web_root)

    resolved, refusal = packaged._runtime_web_assets()

    assert resolved == web_root / "dist"
    assert refusal is None
    assert not bundled.exists()


def test_editable_checkout_builds_when_node_is_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-019 keeps a cold editable checkout self-materializing when Node.js is present."""

    bundled = tmp_path / "src" / "harness" / "_web"
    web_root = tmp_path / "web"
    web_root.mkdir()
    (web_root / "package.json").write_text("{}", encoding="utf-8")
    builds: list[Path] = []

    def build(root: Path) -> None:
        builds.append(root)
        (root / "dist").mkdir()
        (root / "dist" / "index.html").write_text("built rack", encoding="utf-8")

    monkeypatch.setattr(packaged, "BUNDLED_WEB_DIST", bundled)
    monkeypatch.setattr(packaged, "_CANONICAL_WEB_ROOT", web_root)
    monkeypatch.setattr(packaged.shutil, "which", lambda command: "/usr/bin/npm")
    monkeypatch.setattr(packaged, "_build_web", build)

    resolved, refusal = packaged._runtime_web_assets()

    assert builds == [web_root]
    assert resolved == web_root / "dist"
    assert refusal is None


def test_doctor_asset_inspection_is_read_only_when_startup_can_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SPEC D.2 099 makes doctor prove buildability without performing the startup build."""

    web_root = tmp_path / "web"
    web_root.mkdir()
    (web_root / "package.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(packaged, "BUNDLED_WEB_DIST", tmp_path / "missing-wheel-assets")
    monkeypatch.setattr(packaged, "_CANONICAL_WEB_ROOT", web_root)
    monkeypatch.setattr(packaged.shutil, "which", lambda command: "/usr/bin/npm")
    monkeypatch.setattr(
        packaged,
        "_build_web",
        lambda root: pytest.fail("read-only inspection performed a web build"),
    )

    readiness = packaged.inspect_runtime_web_assets()

    assert not readiness.ready
    assert readiness.buildable
    assert readiness.refusal is None
    assert not (web_root / "dist").exists()


def test_editable_checkout_without_node_returns_one_plain_remedy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SPEC D.2 095 requires a cold source checkout refusal to include its next action."""

    web_root = tmp_path / "web"
    web_root.mkdir()
    (web_root / "package.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(packaged, "BUNDLED_WEB_DIST", tmp_path / "missing-wheel-assets")
    monkeypatch.setattr(packaged, "_CANONICAL_WEB_ROOT", web_root)
    monkeypatch.setattr(packaged.shutil, "which", lambda command: None)

    resolved, refusal = packaged._runtime_web_assets()

    assert resolved == web_root / "dist"
    assert refusal is not None
    assert "Install Node.js" in refusal
    assert "npm ci && npm run build" in refusal
    assert "\n" not in refusal
