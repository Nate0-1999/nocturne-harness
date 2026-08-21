"""Run the six shipped-theme palette checks required by ADR-018 clause 7."""

from __future__ import annotations

import json
import math

PALETTES = {
    "neo-noir": {
        "ground": "#03070c",
        "ink": "#e8f8ff",
        "muted": "#95adbb",
        "accent": "#38d7ff",
        "danger": "#ff405f",
        "fleet": ["#279e84", "#4f8fe8", "#b08324", "#ff405f"],
    },
    "seraph-dressed": {
        "ground": "#05060f",
        "ink": "#eef4fb",
        "muted": "#9fb0c9",
        "accent": "#5d8cf2",
        "danger": "#d94048",
        "fleet": ["#279e84", "#5d8cf2", "#db9969", "#d94048"],
    },
    "gold-lines": {
        "ground": "#d7e0ee",
        "ink": "#101c3a",
        "muted": "#3e5170",
        "accent": "#1c3fa8",
        "danger": "#b02a24",
        "fleet": ["#176b5b", "#1c3fa8", "#76501f", "#b02a24"],
    },
    "wizard-mode": {
        "ground": "#0b0704",
        "ink": "#f8f5ef",
        "muted": "#bbae95",
        "accent": "#f0b847",
        "danger": "#ec5360",
        "fleet": ["#5cddae", "#8ea7ff", "#f0b847", "#ec5360"],
    },
    "technomancer": {
        "ground": "#07040b",
        "ink": "#f0f7f2",
        "muted": "#95bba2",
        "accent": "#3dfa7c",
        "danger": "#f54a66",
        "fleet": ["#3dfa7c", "#7c8cff", "#c747f2", "#f54a66"],
    },
}


def rgb(value: str) -> tuple[float, float, float]:
    return tuple(channel / 255 for channel in bytes.fromhex(value[1:]))  # type: ignore[return-value]


def linear(channel: float) -> float:
    return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4


def luminance(value: str) -> float:
    red, green, blue = (linear(channel) for channel in rgb(value))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(left: str, right: str) -> float:
    bright, dark = sorted((luminance(left), luminance(right)), reverse=True)
    return (bright + 0.05) / (dark + 0.05)


def distance(left: str, right: str) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(rgb(left), rgb(right), strict=True)))


def deuteranopia(value: str) -> tuple[float, float, float]:
    red, green, blue = rgb(value)
    return (
        0.625 * red + 0.375 * green,
        0.700 * red + 0.300 * green,
        blue,
    )


def tuple_distance(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right, strict=True)))


def validate() -> dict[str, object]:
    results: dict[str, object] = {}
    for name, palette in PALETTES.items():
        ground = str(palette["ground"])
        fleet = list(palette["fleet"])
        pairs = [
            (fleet[left], fleet[right])
            for left in range(len(fleet))
            for right in range(left + 1, len(fleet))
        ]
        checks = {
            "1_ink_contrast": contrast(str(palette["ink"]), ground) >= 7,
            "2_muted_contrast": contrast(str(palette["muted"]), ground) >= 4.5,
            "3_fleet_ground_contrast": min(contrast(color, ground) for color in fleet) >= 3,
            "4_fleet_pair_separation": min(distance(left, right) for left, right in pairs) >= 0.20,
            "5_deuteranopia_separation": min(
                tuple_distance(deuteranopia(left), deuteranopia(right)) for left, right in pairs
            )
            >= 0.10,
            "6_one_danger_family": contrast(str(palette["danger"]), ground) >= 3
            and str(palette["danger"]) in fleet,
        }
        results[name] = {"checks": checks, "passed": all(checks.values())}
    return {"schema_version": 1, "themes": results}


def main() -> None:
    result = validate()
    print(json.dumps(result, indent=2, sort_keys=True))
    if not all(theme["passed"] for theme in result["themes"].values()):
        raise SystemExit("theme palette validation failed")


if __name__ == "__main__":
    main()
