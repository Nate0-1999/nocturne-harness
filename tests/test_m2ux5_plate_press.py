"""Standing evidence for the M2UX5 in-product plate press."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
WEB = ROOT / "web"
sys.path.insert(0, str(WEB / "scripts"))

from extract_cobalt_seraph import read_rgb_png  # noqa: E402

from verification.m2ux5.scenario_app import _monochrome_png, _route_around_html  # noqa: E402

EXPECTED_PLATE_SHA = "40bfc4414de3fe5d252060dc806cf5c795180d6fcd20aae37ac059a69498e069"


def _derive(path: Path, tmp_path: Path) -> dict[str, object]:
    width, height, rgb_pixels = read_rgb_png(path)
    rgba_path = tmp_path / f"{path.stem}.rgba"
    rgba_path.write_bytes(b"".join(bytes((*rgb, 255)) for rgb in rgb_pixels))
    result = subprocess.run(
        [
            "node",
            "--experimental-strip-types",
            str(WEB / "tests" / "derivePlateFixture.mjs"),
            str(rgba_path),
            str(width),
            str(height),
            hashlib.sha256(path.read_bytes()).hexdigest(),
            str(WEB / "src" / "themes" / "seam-colors.json"),
        ],
        cwd=WEB,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_canonical_plate_reuses_the_exact_m2ux4_clusters_and_shares(tmp_path: Path) -> None:
    """SPEC B.6 and PLAN M2UX5 bind product intake to the ratified extractor."""
    plate = WEB / "src" / "themes" / "cobalt-seraph-plate.png"
    expected = json.loads((WEB / "src" / "themes" / "plate.generated.json").read_text())
    first = _derive(plate, tmp_path)
    second = _derive(plate, tmp_path)
    assert hashlib.sha256(plate.read_bytes()).hexdigest() == EXPECTED_PLATE_SHA
    assert first == second
    assert first["ok"] is True
    assert first["colorway"]["clusters"] == expected["clusters"]
    assert first["colorway"]["validation"]["passed"] is True


def test_second_real_image_yields_a_lawful_named_colorway(tmp_path: Path) -> None:
    """SPEC B.6 and PLAN M2UX5 require a real second image, not a synthetic-only pass."""
    image = ROOT / "verification" / "m2ux4" / "02-seraph-dressed-1280x900.png"
    result = _derive(image, tmp_path)
    assert result["ok"] is True
    assert result["colorway"]["id"].startswith("pressed-")
    assert result["colorway"]["validation"]["passed"] is True


def test_fixture_route_around_only_bypasses_native_selection() -> None:
    """SPEC B.6 and report 071 keep the real handler and audit repeat persistence."""
    html = _route_around_html("canonical")
    assert "/__scenario__/plate/canonical" in html
    assert "input.dispatchEvent(new Event('change'" in html
    assert "nocturne.colorways.v1" in html
    assert "m2ux5StorageDigest" in html
    assert _monochrome_png().startswith(b"\x89PNG\r\n\x1a\n")
