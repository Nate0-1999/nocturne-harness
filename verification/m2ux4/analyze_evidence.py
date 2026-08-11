"""Analyze retained M2UX4 pixels against the plate, shine, and stability laws."""

from __future__ import annotations

import collections
import json
import runpy
from pathlib import Path

ROOT = Path(__file__).parents[2]
EVIDENCE = Path(__file__).parent
EXTRACTOR = runpy.run_path(str(ROOT / "web" / "scripts" / "extract_cobalt_seraph.py"))
read_rgb_png = EXTRACTOR["read_rgb_png"]
rgb_to_oklab = EXTRACTOR["rgb_to_oklab"]

EMULATION_BOUND = 0.395
FAMILIES = {
    "dark": ["#0b0a0b", "#122039"],
    "cool": ["#14316c", "#2a54a4"],
    "silver": ["#98a1b5", "#75798d", "#574f56", "#eaecec", "#bcc2cd"],
    "warm": ["#b66872", "#3c2828"],
    "precious": ["#ad8659", "#db9969"],
    "danger": ["#a34f4c", "#cd352b"],
}
PLATE_SHARES = {
    "dark": 0.557,
    "cool": 0.125,
    "silver": 0.1885,
    "warm": 0.1156,
    "precious": 0.00061,
    "danger": 0.0137,
}
RIM_RECTS = [
    (7, 67, 204, 522),
    (219, 67, 841, 522),
    (1068, 67, 205, 522),
    (7, 597, 948, 296),
    (963, 597, 310, 296),
]


def rgb(hex_value: str) -> tuple[int, int, int]:
    return tuple(bytes.fromhex(hex_value[1:]))  # type: ignore[return-value]


def distance(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    return sum((a_value - b_value) ** 2 for a_value, b_value in zip(left, right, strict=True))


def palette_projection(pixels: list[tuple[int, int, int]]) -> dict[str, float]:
    centers = {
        family: [rgb_to_oklab(rgb(value)) for value in values]
        for family, values in FAMILIES.items()
    }
    counts: collections.Counter[str] = collections.Counter()
    for pixel in pixels[::4]:
        lab = rgb_to_oklab(pixel)
        family = min(
            centers, key=lambda name: min(distance(lab, center) for center in centers[name])
        )
        counts[family] += 1
    total = sum(counts.values())
    return {family: counts[family] / total for family in FAMILIES}


def luminance(pixel: tuple[int, int, int]) -> float:
    def linear(channel: int) -> float:
        value = channel / 255
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    red, green, blue = (linear(channel) for channel in pixel)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def main() -> None:
    pre_width, pre_height, pre = read_rgb_png(EVIDENCE / "neo-noir-pre-seam.png")
    post_width, post_height, post = read_rgb_png(EVIDENCE / "neo-noir-post-seam.png")
    if (pre_width, pre_height) != (post_width, post_height):
        raise SystemExit("NEO-NOIR comparison dimensions drifted")
    dynamic_rows = ((0, 64), (120, 132), (296, 310), (776, 792))
    mismatches = [
        index for index, pair in enumerate(zip(pre, post, strict=True)) if pair[0] != pair[1]
    ]
    stable_mismatches = [
        index
        for index in mismatches
        if not any(start <= index // pre_width <= end for start, end in dynamic_rows)
    ]
    if stable_mismatches:
        count = len(stable_mismatches)
        raise SystemExit(
            f"NEO-NOIR changed outside the new control/dynamic fixture masks: {count} pixels"
        )

    width, height, pixels = read_rgb_png(EVIDENCE / "seraph-analysis-1280x900.png")
    actual = palette_projection(pixels)
    normalization = sum(PLATE_SHARES.values())
    expected = {family: share / normalization for family, share in PLATE_SHARES.items()}
    emulation_distance = 0.5 * sum(abs(actual[family] - expected[family]) for family in FAMILIES)
    if emulation_distance > EMULATION_BOUND:
        raise SystemExit(
            f"Seraph palette-area distance {emulation_distance:.6f} exceeds {EMULATION_BOUND}"
        )
    if actual["precious"] > 0.001:
        raise SystemExit(f"Seraph gold area {actual['precious']:.6%} exceeds the 0.1% budget")

    rim_pixels: list[tuple[int, int, int]] = []
    for x_value, y_value, rect_width, rect_height in RIM_RECTS:
        for sample_x in range(x_value, x_value + rect_width):
            for sample_y in (y_value, y_value + rect_height - 1):
                rim_pixels.append(pixels[sample_y * width + sample_x])
        for sample_y in range(y_value, y_value + rect_height):
            for sample_x in (x_value, x_value + rect_width - 1):
                rim_pixels.append(pixels[sample_y * width + sample_x])
    bands = collections.Counter(
        "low" if luminance(pixel) < 0.18 else "high" if luminance(pixel) > 0.65 else "mid"
        for pixel in rim_pixels
    )
    rim_total = len(rim_pixels)
    band_shares = {band: bands[band] / rim_total for band in ("low", "mid", "high")}
    if band_shares["low"] < 0.80 or band_shares["high"] < 0.02 or band_shares["mid"] > 0.05:
        raise SystemExit(f"chrome rim is not dark/blaze bimodal: {band_shares}")
    specular_screen_share = bands["high"] / (width * height)
    if specular_screen_share > 0.012:
        raise SystemExit(f"specular area {specular_screen_share:.6%} exceeds the plate ceiling")

    rendered = json.loads((EVIDENCE / "themes-rendered.json").read_text())
    reflection = rendered["observations"]["reflection"]
    if (
        reflection["before"]["attachment"] != "fixed"
        or reflection["after"]["attachment"] != "fixed"
        or reflection["before"]["x"] == reflection["after"]["x"]
        or reflection["before"]["image"] != reflection["after"]["image"]
    ):
        raise SystemExit(f"rim reflection did not stay fixed under drag: {reflection}")

    result = {
        "chrome_bimodality": {
            "band_shares": band_shares,
            "specular_screen_share": specular_screen_share,
        },
        "emulation": {
            "actual": actual,
            "bound": EMULATION_BOUND,
            "distance": emulation_distance,
            "plate": expected,
        },
        "neo_noir_pixel_stability": {
            "masked_dynamic_rows": dynamic_rows,
            "raw_mismatches": len(mismatches),
            "stable_mismatches": len(stable_mismatches),
        },
        "schema_version": 1,
    }
    (EVIDENCE / "theme-analysis.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    print("M2UX4 pixel analysis PASS")


if __name__ == "__main__":
    main()
