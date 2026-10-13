"""M3GT contract tests for the two ornament themes (Art Deco, Bellagio Lobby Ceiling)."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
WEB = ROOT / "web"
ORNAMENTS = WEB / "src" / "themes" / "ornament.generated.css"
SEAM = WEB / "src" / "themes" / "themes.css"
THEMES = ("art-deco", "bellagio")


def run_script(name: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(WEB / "scripts" / name), *arguments],
        cwd=WEB,
        check=True,
        capture_output=True,
        text=True,
    )


def light_blocks(css: str, theme: str) -> list[str]:
    opening = r'@media \(prefers-color-scheme: light\) \{\s*\S*\[data-theme="%s"\] \{'
    return [
        css[match.end() : css.index("}", match.end())]
        for match in re.finditer(opening % re.escape(theme), css)
    ]


def test_ornaments_and_seam_regenerate_byte_for_byte() -> None:
    """SPEC D.2 180 freezes the picked candidates; regeneration must not redraw them."""
    run_script("build_ornament_motifs.py", "--check")
    run_script("build_theme_seam.py")


def test_both_faces_of_both_themes_pass_the_six_checks() -> None:
    """ADR-018 clause 7 and SPEC B.6 r12: each face is validated on its own grounds."""
    result = json.loads(run_script("validate_theme_palettes.py").stdout)
    for theme in THEMES:
        for face in (theme, f"{theme}-light"):
            checks = result["themes"][face]["checks"]
            assert len(checks) == 6
            assert all(checks.values()), face


def test_a_face_changes_colours_and_ornaments_never_sizes() -> None:
    """SPEC D.2 180 and FL-201's one scale: the light face holds only custom properties."""
    for css, prefix in ((SEAM.read_text(), "--seam-"), (ORNAMENTS.read_text(), "--ornament-")):
        for theme in THEMES:
            blocks = light_blocks(css, theme)
            assert len(blocks) == 1, theme
            declarations = [line.strip() for line in blocks[0].splitlines() if line.strip()]
            assert declarations
            assert all(line.startswith(prefix) for line in declarations), theme


def test_ornaments_sit_behind_data_and_the_name_reads_whole() -> None:
    """SPEC D.2 115 (no motion or ornament on a data surface) and TASTE-09 (names read whole)."""
    css = ORNAMENTS.read_text()
    for theme in THEMES:
        stage = f'html[data-theme="{theme}"] .stage-viewport:not(.stage-viewport--sheet)::before'
        rule = css.split(stage + " {", maxsplit=1)[1].split("}", maxsplit=1)[0]
        assert "z-index: -1;" in rule
        assert "pointer-events: none;" in rule
        strip = css.split(f'html[data-theme="{theme}"] .rack-module__drag::after {{')[1]
        assert "flex: 0 1000000 auto;" in strip.split("}", maxsplit=1)[0]
    for surface in (".message__content", ".memory-card", ".thread-row", "@keyframes"):
        assert surface not in css
