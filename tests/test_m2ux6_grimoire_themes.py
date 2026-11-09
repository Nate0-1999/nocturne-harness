"""M2UX6 contract tests for the two frozen grimoire themes."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).parents[1]
WEB = ROOT / "web"
CSS_PATH = WEB / "src" / "themes" / "grimoire.generated.css"
EXPECTED_FORGE_SHA = "d14f9b4167b7d317007a7d7ab82fa7bf8b13fad3fb74afe1a25295e030055250"


def run_script(name: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(WEB / "scripts" / name), *arguments],
        cwd=WEB,
        check=True,
        capture_output=True,
        text=True,
    )


def load_forge() -> ModuleType:
    path = WEB / "scripts" / "sigil_forge.py"
    spec = importlib.util.spec_from_file_location("m2ux6_sigil_forge", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_frozen_forge_and_generated_css_are_byte_reproducible() -> None:
    """SPEC D.2 118 freezes both hands; regeneration must not improvise glyphs."""
    forge = load_forge()
    strips = [
        forge.elvish_strip(16, "#d9a45c", "wiz-head"),
        forge.elvish_strip(6, "#9a8768", "wiz-margin", vertical=True),
        forge.elvish_strip(20, "#d9a45c", "wiz-breath"),
        forge.elvish_strip(8, "#9a8768", "wiz-col", vertical=True),
        forge.elvish_strip(1, "#d9a45c", "wiz-one"),
        forge.elvish_strip(8, "#d9a45c", "wiz-comp"),
        forge.elvish_strip(3, "#9a8768", "wiz-top"),
        forge.strip_svg(13, "#4be08a", "tec-head"),
        forge.strip_svg(11, "#4be08a", "tec-hex"),
        forge.strip_svg(12, "#4be08a", "tec-rain1", vertical=True),
        forge.strip_svg(10, "#b46cf0", "tec-rain2", vertical=True),
        forge.strip_svg(7, "#4be08a", "tec-comp"),
        forge.strip_svg(3, "#b46cf0", "tec-top"),
    ]
    assert hashlib.sha256("".join(strips).encode()).hexdigest() == EXPECTED_FORGE_SHA
    before = CSS_PATH.read_bytes()
    run_script("build_grimoire_motifs.py")
    assert CSS_PATH.read_bytes() == before
    run_script("build_grimoire_motifs.py", "--check")


def test_both_palettes_pass_all_six_checks_with_one_danger_family() -> None:
    """SPEC B.6 r12 and D.2 115 require six checks and one danger per theme."""
    result = json.loads(run_script("validate_theme_palettes.py").stdout)
    for theme in ("wizard-mode", "technomancer"):
        checks = result["themes"][theme]["checks"]
        assert len(checks) == 6
        assert checks["6_one_danger_family"] is True
        assert all(checks.values())


def test_conjurations_are_state_bound_and_data_surfaces_remain_still() -> None:
    """SPEC B.6 r7 and D.2 116-117 reserve loops for empty/background air."""
    css = CSS_PATH.read_text()
    assert ".message__content" not in css
    assert ".memory-card" not in css
    assert ".thread-row" not in css
    assert css.count(" infinite;") == 9
    assert css.count(":has(.thread-empty)") >= 8
    assert "rack-ambient::after" in css
    assert ".rack-module:hover .rack-module__content::after" in css
    assert ".composer:focus-within::before" in css
    assert "flex: 0 1000000 auto" in css
    assert "min-width: 0" in css
    assert ".rack-module__drag > .rack-module__attunement" in css
    assert "width: 7.5rem" in css


def test_module_names_read_whole_beside_the_head_strip() -> None:
    """SPEC D.2 115 and ADR-018 clause 7: a theme styles meaning, never cuts the module name."""
    css = CSS_PATH.read_text()
    rack = (WEB / "src" / "assets" / "rack.css").read_text()
    assert ".rack-module__chrome::before" not in css
    assert 'html[data-theme="wizard-mode"] .rack-module__drag::after' in css
    name_rule = rack.split(".rack-module__drag strong {", maxsplit=1)[1].split("}", maxsplit=1)[0]
    assert "flex-shrink: 0;" in name_rule


def test_stage_rain_falls_behind_the_modules_and_rests() -> None:
    """SPEC D.2 115 and 117: the elder scripts fall behind the Stage modules, off data surfaces."""
    css = CSS_PATH.read_text()
    main = (WEB / "src" / "main.tsx").read_text()
    for theme in ("wizard-mode", "technomancer"):
        stage = f'html[data-theme="{theme}"] .stage-viewport:not(.stage-viewport--sheet)'
        assert f"{stage} {{\n  isolation: isolate;\n}}" in css
        for pseudo in ("::before", "::after"):
            rule = css.split(f"{stage}{pseudo} {{", maxsplit=1)[1].split("}", maxsplit=1)[0]
            assert "z-index: -1;" in rule
            assert "pointer-events: none;" in rule
            assert rule.count("var(--grimoire-stage-rain-") == 8
            assert f'html[data-page-hidden][data-theme="{theme}"]' in css
    assert "toggleAttribute('data-page-hidden', document.hidden)" in main


def test_reduced_motion_stops_every_grimoire_loop_and_conjuration() -> None:
    """SPEC B.6 r7 requires a legible static rest under reduced motion."""
    css = CSS_PATH.read_text()
    reduced = css.split("@media (prefers-reduced-motion: reduce)", maxsplit=1)[1]
    assert "animation: none !important" in reduced
    for surface in (
        ".rack-module__drag::after",
        ".rack-module__content::after",
        ".rack-module__content::before",
        ".message__label::after",
        ".composer::before",
        ".topbar::after",
        ".transcript__inner:has(.thread-empty)::after",
        ".transcript__inner:has(.thread-empty)::before",
        ".rack-ambient::after",
        ".stage-viewport::before",
        ".stage-viewport::after",
    ):
        assert surface in reduced
