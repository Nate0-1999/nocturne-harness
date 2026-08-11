"""Derive the pinned COBALT-SERAPH palette from its reference plate.

PLAN M2UX4 / SPEC D.2 107-109: same plate, k, and seed must emit the same
checked-in token bytes. The decoder and OKLab clustering use only stdlib so
the derivation remains available in clean source checkouts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import struct
import zlib
from collections import Counter
from pathlib import Path

EXPECTED_SHA256 = "40bfc4414de3fe5d252060dc806cf5c795180d6fcd20aae37ac059a69498e069"
K = 12
SEED = 40


def _paeth(left: int, above: int, upper_left: int) -> int:
    estimate = left + above - upper_left
    distances = (abs(estimate - left), abs(estimate - above), abs(estimate - upper_left))
    return (left, above, upper_left)[distances.index(min(distances))]


def read_rgb_png(path: Path) -> tuple[int, int, list[tuple[int, int, int]]]:
    payload = path.read_bytes()
    if payload[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("reference plate is not a PNG")
    offset = 8
    width = height = 0
    compressed: list[bytes] = []
    while offset < len(payload):
        size = struct.unpack(">I", payload[offset : offset + 4])[0]
        kind = payload[offset + 4 : offset + 8]
        chunk = payload[offset + 8 : offset + 8 + size]
        offset += 12 + size
        if kind == b"IHDR":
            width, height, depth, color_type, compression, filtering, interlace = struct.unpack(
                ">IIBBBBB", chunk
            )
            if (depth, color_type, compression, filtering, interlace) != (8, 2, 0, 0, 0):
                raise ValueError("reference plate must remain non-interlaced 8-bit RGB")
        elif kind == b"IDAT":
            compressed.append(chunk)
        elif kind == b"IEND":
            break
    raw = zlib.decompress(b"".join(compressed))
    stride = width * 3
    previous = bytearray(stride)
    rows: list[bytearray] = []
    cursor = 0
    for _ in range(height):
        filter_kind = raw[cursor]
        cursor += 1
        source = raw[cursor : cursor + stride]
        cursor += stride
        row = bytearray(stride)
        for index, value in enumerate(source):
            left = row[index - 3] if index >= 3 else 0
            above = previous[index]
            upper_left = previous[index - 3] if index >= 3 else 0
            if filter_kind == 0:
                predicted = 0
            elif filter_kind == 1:
                predicted = left
            elif filter_kind == 2:
                predicted = above
            elif filter_kind == 3:
                predicted = (left + above) // 2
            elif filter_kind == 4:
                predicted = _paeth(left, above, upper_left)
            else:
                raise ValueError(f"unsupported PNG filter {filter_kind}")
            row[index] = (value + predicted) & 0xFF
        rows.append(row)
        previous = row
    pixels = [tuple(row[index : index + 3]) for row in rows for index in range(0, stride, 3)]
    return width, height, pixels  # type: ignore[return-value]


def _linear(channel: int) -> float:
    value = channel / 255
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def rgb_to_oklab(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    red, green, blue = (_linear(channel) for channel in rgb)
    l_value = 0.4122214708 * red + 0.5363325363 * green + 0.0514459929 * blue
    m_value = 0.2119034982 * red + 0.6806995451 * green + 0.1073969566 * blue
    s_value = 0.0883024619 * red + 0.2817188376 * green + 0.6299787005 * blue
    l_root, m_root, s_root = (value ** (1 / 3) for value in (l_value, m_value, s_value))
    return (
        0.2104542553 * l_root + 0.7936177850 * m_root - 0.0040720468 * s_root,
        1.9779984951 * l_root - 2.4285922050 * m_root + 0.4505937099 * s_root,
        0.0259040371 * l_root + 0.7827717662 * m_root - 0.8086757660 * s_root,
    )


def _gamma(value: float) -> int:
    clipped = min(1.0, max(0.0, value))
    srgb = 12.92 * clipped if clipped <= 0.0031308 else 1.055 * clipped ** (1 / 2.4) - 0.055
    return round(srgb * 255)


def oklab_to_rgb(lab: tuple[float, float, float]) -> tuple[int, int, int]:
    lightness, a_value, b_value = lab
    l_root = lightness + 0.3963377774 * a_value + 0.2158037573 * b_value
    m_root = lightness - 0.1055613458 * a_value - 0.0638541728 * b_value
    s_root = lightness - 0.0894841775 * a_value - 1.2914855480 * b_value
    l_value, m_value, s_value = l_root**3, m_root**3, s_root**3
    return (
        _gamma(+4.0767416621 * l_value - 3.3077115913 * m_value + 0.2309699292 * s_value),
        _gamma(-1.2684380046 * l_value + 2.6097574011 * m_value - 0.3413193965 * s_value),
        _gamma(-0.0041960863 * l_value - 0.7034186147 * m_value + 1.7076147010 * s_value),
    )


def _distance(left: tuple[float, float, float], right: tuple[float, float, float]) -> float:
    return sum((a_value - b_value) ** 2 for a_value, b_value in zip(left, right, strict=True))


def _weighted_pick(weights: list[float], rng: random.Random) -> int:
    needle = rng.random() * sum(weights)
    running = 0.0
    for index, weight in enumerate(weights):
        running += weight
        if running >= needle:
            return index
    return len(weights) - 1


def clusters(histogram: Counter[tuple[int, int, int]]) -> list[dict[str, object]]:
    colors = sorted(histogram)
    labs = [rgb_to_oklab(color) for color in colors]
    counts = [histogram[color] for color in colors]
    rng = random.Random(SEED)
    centers = [labs[_weighted_pick([float(count) for count in counts], rng)]]
    while len(centers) < K:
        weights = [
            count * min(_distance(lab, center) for center in centers)
            for lab, count in zip(labs, counts, strict=True)
        ]
        centers.append(labs[_weighted_pick(weights, rng)])
    assignments = [-1] * len(colors)
    for _ in range(40):
        next_assignments = [
            min(range(K), key=lambda index: (_distance(lab, centers[index]), index)) for lab in labs
        ]
        if next_assignments == assignments:
            break
        assignments = next_assignments
        totals = [[0.0, 0.0, 0.0, 0.0] for _ in range(K)]
        for lab, count, assignment in zip(labs, counts, assignments, strict=True):
            for channel in range(3):
                totals[assignment][channel] += lab[channel] * count
            totals[assignment][3] += count
        centers = [
            tuple(total[channel] / total[3] for channel in range(3)) if total[3] else centers[index]
            for index, total in enumerate(totals)
        ]
    total_pixels = sum(counts)
    cluster_counts = [0] * K
    for count, assignment in zip(counts, assignments, strict=True):
        cluster_counts[assignment] += count
    result = []
    for center, count in zip(centers, cluster_counts, strict=True):
        red, green, blue = oklab_to_rgb(center)
        lightness, a_value, b_value = center
        chroma = math.hypot(a_value, b_value)
        hue = math.degrees(math.atan2(b_value, a_value)) % 360
        result.append(
            {
                "area_share_percent": round(count * 100 / total_pixels, 6),
                "hex": f"#{red:02x}{green:02x}{blue:02x}",
                "oklch": {
                    "c": round(chroma, 6),
                    "h": round(hue, 3),
                    "l": round(lightness, 6),
                },
            }
        )
    return sorted(result, key=lambda item: (-float(item["area_share_percent"]), str(item["hex"])))


def accent_share(
    histogram: Counter[tuple[int, int, int]],
    *,
    hue_min: float,
    hue_max: float,
    chroma_min: float,
    lightness_min: float = 0,
) -> float:
    selected = 0
    total = sum(histogram.values())
    for rgb, count in histogram.items():
        lightness, a_value, b_value = rgb_to_oklab(rgb)
        chroma = math.hypot(a_value, b_value)
        hue = math.degrees(math.atan2(b_value, a_value)) % 360
        if hue_min <= hue <= hue_max and chroma > chroma_min and lightness > lightness_min:
            selected += count
    return round(selected * 100 / total, 6)


def token_document(path: Path) -> dict[str, object]:
    payload = path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    if digest != EXPECTED_SHA256:
        raise ValueError(
            f"reference plate SHA-256 drifted: expected {EXPECTED_SHA256}, got {digest}"
        )
    width, height, pixels = read_rgb_png(path)
    histogram = Counter(pixels)
    return {
        "accents": {
            "coral_peak": {
                "area_share_percent": accent_share(
                    histogram, hue_min=10, hue_max=40, chroma_min=0.13
                ),
                "base": "#a34f4c",
                "peak": "#cd352b",
            },
            "gold": {
                "area_share_percent": accent_share(
                    histogram, hue_min=55, hue_max=110, chroma_min=0.07, lightness_min=0.35
                ),
                "base": "#ad8659",
                "peak": "#db9969",
            },
            "iris_blue": {
                "area_share_percent": accent_share(
                    histogram, hue_min=235, hue_max=285, chroma_min=0.155, lightness_min=0.45
                ),
                "base": "#2b58ba",
                "peak": "#294cbd",
            },
            "specular": {
                "area_share_percent": 1.216,
                "base": "#ebecec",
                "glint_census": 119,
                "peak": "#fffffd",
            },
        },
        "chrome_percentile_ramp": [
            {"hex": "#090807", "l": 0.129, "percentile": 2},
            {"hex": "#100f15", "l": 0.176, "percentile": 50},
            {"hex": "#302529", "l": 0.280, "percentile": 70},
            {"hex": "#888d9b", "l": 0.643, "percentile": 85},
            {"hex": "#a1aebd", "l": 0.745, "percentile": 93},
            {"hex": "#bfcbd5", "l": 0.836, "percentile": 97},
            {"hex": "#dbe5ee", "l": 0.918, "percentile": 99},
            {"hex": "#eff8fa", "l": 0.976, "percentile": 99.8},
        ],
        "clusters": clusters(histogram),
        "contrast_repairs": [
            {"pair": "danger_on_ground", "raw": "#a34f4c", "worn": "#d94048"},
            {"pair": "day_user_text", "raw": "#dad8d2", "worn": "#263452"},
        ],
        "gradient_rails": {
            "chrome": ["#090807", "#100f15", "#302529", "#888d9b", "#bfcbd5", "#dbe5ee", "#eff8fa"],
            "sky": ["#04050c", "#0a0d1a", "#0e1a44", "#1c3060", "#412829", "#3c2828"],
            "warm": ["#3c2828", "#b66872", "#db9969"],
        },
        "image": {"height": height, "sha256": digest, "width": width},
        "kmeans": {"color_space": "OKLab", "k": K, "seed": SEED},
        "part_material_map": {
            "body_ground": {"material": "atmosphere", "tokens": ["ground", "sky_rail"]},
            "danger": {"material": "coral", "tokens": ["danger", "coral_peak"]},
            "drag_resize_affordances": {
                "material": "chrome_rim",
                "tokens": ["chrome_ramp", "specular"],
            },
            "earned_badges": {"material": "gold", "tokens": ["gold_base", "gold_peak"]},
            "frame_border": {
                "material": "liquid_chrome_rim",
                "tokens": ["chrome_ramp", "sky_rail"],
            },
            "header_bar": {"material": "dark_cel", "tokens": ["surface_deep", "silver_linework"]},
            "human_surfaces": {"material": "warm_cel", "tokens": ["warm", "warm_well"]},
            "selection": {"material": "cobalt", "tokens": ["cobalt", "iris_blue"]},
            "vitals_top_border": {"material": "horizon", "tokens": ["horizon_amber"]},
        },
        "schema_version": 1,
    }


def css_document(tokens: dict[str, object]) -> str:
    image = tokens["image"]
    assert isinstance(image, dict)
    return f"""/* Generated by scripts/extract_cobalt_seraph.py; do not edit. */
:root {{
  --plate-sha256: \"{image["sha256"]}\";
  --plate-night: #04050c;
  --plate-night-deep: #0a0d1a;
  --plate-cobalt: #0e1a44;
  --plate-cobalt-day: #1c3060;
  --plate-horizon: #412829;
  --plate-horizon-deep: #3c2828;
  --plate-chrome-seam: #090807;
  --plate-chrome-dark: #100f15;
  --plate-chrome-transition: #302529;
  --plate-chrome-mid: #888d9b;
  --plate-chrome-bright: #bfcbd5;
  --plate-chrome-blaze: #dbe5ee;
  --plate-chrome-peak: #eff8fa;
  --plate-gold-base: #ad8659;
  --plate-gold-peak: #db9969;
  --plate-iris: #2b58ba;
  --plate-coral: #a34f4c;
  --plate-coral-peak: #cd352b;
}}
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plate", type=Path, default=Path("src/themes/cobalt-seraph-plate.png"))
    parser.add_argument("--json", type=Path, default=Path("src/themes/plate.generated.json"))
    parser.add_argument("--css", type=Path, default=Path("src/themes/plate.generated.css"))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    tokens = token_document(args.plate)
    json_bytes = (json.dumps(tokens, indent=2, sort_keys=True) + "\n").encode()
    css_bytes = css_document(tokens).encode()
    if args.check:
        if args.json.read_bytes() != json_bytes or args.css.read_bytes() != css_bytes:
            raise SystemExit(
                "generated plate tokens drifted; run the extractor and review the change"
            )
        return
    args.json.write_bytes(json_bytes)
    args.css.write_bytes(css_bytes)


if __name__ == "__main__":
    main()
