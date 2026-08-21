"""Build-time theme law for M2UX4."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
WEB = ROOT / "web"
EXPECTED_PLATE_SHA = "40bfc4414de3fe5d252060dc806cf5c795180d6fcd20aae37ac059a69498e069"


def run_script(name: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(WEB / "scripts" / name), *arguments],
        cwd=WEB,
        check=True,
        capture_output=True,
        text=True,
    )


def test_plate_extraction_is_pinned_and_byte_reproducible(tmp_path: Path) -> None:
    """P2 and SPEC D.2 107-109 require the exact plate to produce identical tokens twice."""
    plate = WEB / "src" / "themes" / "cobalt-seraph-plate.png"
    assert hashlib.sha256(plate.read_bytes()).hexdigest() == EXPECTED_PLATE_SHA
    outputs = []
    for index in range(2):
        json_path = tmp_path / f"tokens-{index}.json"
        css_path = tmp_path / f"tokens-{index}.css"
        run_script(
            "extract_cobalt_seraph.py",
            "--plate",
            str(plate),
            "--json",
            str(json_path),
            "--css",
            str(css_path),
        )
        outputs.append((json_path.read_bytes(), css_path.read_bytes()))
    assert outputs[0] == outputs[1]
    assert outputs[0][0] == (WEB / "src" / "themes" / "plate.generated.json").read_bytes()
    assert outputs[0][1] == (WEB / "src" / "themes" / "plate.generated.css").read_bytes()


def test_generated_plate_contract_keeps_shine_ratio_and_material_law() -> None:
    """P2 and SPEC D.2 108-110 bind percentile chrome, rarity, and part materials."""
    tokens = json.loads((WEB / "src" / "themes" / "plate.generated.json").read_text())
    assert tokens["image"]["sha256"] == EXPECTED_PLATE_SHA
    assert tokens["kmeans"] == {"color_space": "OKLab", "k": 12, "seed": 40}
    assert len(tokens["clusters"]) == 12
    assert round(sum(cluster["area_share_percent"] for cluster in tokens["clusters"]), 5) == 100
    assert [stop["hex"] for stop in tokens["chrome_percentile_ramp"]] == [
        "#090807",
        "#100f15",
        "#302529",
        "#888d9b",
        "#a1aebd",
        "#bfcbd5",
        "#dbe5ee",
        "#eff8fa",
    ]
    assert tokens["chrome_percentile_ramp"][-1]["l"] >= 0.97
    assert tokens["accents"]["specular"]["glint_census"] == 119
    assert tokens["part_material_map"]["frame_border"]["material"] == "liquid_chrome_rim"
    assert tokens["part_material_map"]["header_bar"]["material"] == "dark_cel"


def test_css_seam_and_built_in_palette_checks_are_closed() -> None:
    """PLAN M2UX4/M2UX6, ADR-018 clause 7, and D.2 112-115 forbid unsafe themes."""
    run_script("build_theme_seam.py")
    result = json.loads(run_script("validate_theme_palettes.py").stdout)
    assert set(result["themes"]) == {
        "neo-noir",
        "seraph-dressed",
        "gold-lines",
        "wizard-mode",
        "technomancer",
    }
    assert all(theme["passed"] for theme in result["themes"].values())


def test_retained_theme_pixels_meet_stability_emulation_and_shine_bounds() -> None:
    """P2, SPEC B.6 r7, and SPEC D.2 107-113 bind retained pixels to plate and worn skin."""
    subprocess.run(
        [sys.executable, str(ROOT / "verification" / "m2ux4" / "analyze_evidence.py")],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    analysis = json.loads((ROOT / "verification" / "m2ux4" / "theme-analysis.json").read_text())
    assert analysis["neo_noir_pixel_stability"]["stable_mismatches"] == 0
    assert analysis["emulation"]["distance"] <= analysis["emulation"]["bound"]
    assert analysis["chrome_bimodality"]["band_shares"]["mid"] <= 0.05
