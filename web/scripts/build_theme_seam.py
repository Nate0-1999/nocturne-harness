"""Record and verify the exhaustive CSS color-token seam for M2UX4/M2UX6.

The one-time --record operation moves every literal from the three production
stylesheets into one generated built-in-theme variable table. Ordinary --check is
read-only and fails on either a new literal or generated-table drift.
"""

from __future__ import annotations

import argparse
import colorsys
import hashlib
import json
import re
from pathlib import Path

ASSET_FILES = (
    Path("src/assets/base.css"),
    Path("src/assets/shell.css"),
    Path("src/assets/rack.css"),
)
MANIFEST = Path("src/themes/seam-colors.json")
THEMES_CSS = Path("src/themes/themes.css")
COLOR = re.compile(r"#[0-9a-fA-F]{3,8}\b|(?:rgba?|hsla?)\([^()]*\)")
GRIMOIRE_HEX = re.compile(r"#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")
GRIMOIRE_RGBA = re.compile(r"rgba?\(([^)]+)\)")

SERAPH_HEX = {
    "#03070c": "#05060f",
    "#050c13": "#0a0d1a",
    "#07121b": "#0d1226",
    "#0b1b27": "#141d3a",
    "#0a0b0d": "#07080f",
    "#e8f8ff": "#eef4fb",
    "#95adbb": "#9fb0c9",
    "#627c8b": "#6b7a99",
    "#78939d": "#7f8ba8",
    "#38d7ff": "#5d8cf2",
    "#7ce8ff": "#a5c4ff",
    "#74f2ff": "#83aaf6",
    "#9df8ff": "#bcd4ff",
    "#777a80": "#dbe5ee",
    "#f2479b": "#db9969",
    "#ff91c5": "#e8c39a",
    "#ffd2e7": "#f2e0c8",
    "#ff405f": "#d94048",
    "#ff9ca4": "#eda0a4",
    "#e68a4c": "#db9969",
    "#dad8d2": "#eef4fb",
    "#c9dce4": "#eef4fb",
}
GOLD_HEX = {
    "#03070c": "#d7e0ee",
    "#050c13": "#e6ecf5",
    "#07121b": "#f2f5fa",
    "#0b1b27": "#ffffff",
    "#0a0b0d": "#cfd9e8",
    "#e8f8ff": "#101c3a",
    "#95adbb": "#3e5170",
    "#627c8b": "#5a6b8a",
    "#78939d": "#4a5d80",
    "#38d7ff": "#1c3fa8",
    "#7ce8ff": "#2a54a4",
    "#74f2ff": "#2b58ba",
    "#9df8ff": "#16307e",
    "#777a80": "#1c3fa8",
    "#f2479b": "#b07a3f",
    "#ff91c5": "#8a5f2e",
    "#ffd2e7": "#5f421f",
    "#ff405f": "#b02a24",
    "#ff9ca4": "#8f221d",
    "#e68a4c": "#b07a3f",
    "#dad8d2": "#263452",
    "#c9dce4": "#263452",
}
SERAPH_RGB = {
    (56, 215, 255): (93, 140, 242),
    (60, 210, 255): (219, 229, 238),
    (242, 71, 155): (219, 153, 105),
    (255, 64, 95): (217, 64, 72),
    (7, 18, 27): (7, 8, 15),
}
GOLD_RGB = {
    (56, 215, 255): (150, 104, 44),
    (60, 210, 255): (150, 104, 44),
    (242, 71, 155): (176, 122, 63),
    (255, 64, 95): (176, 42, 36),
    (7, 18, 27): (245, 248, 252),
}

ANCHORS = [
    ((3, 7, 12), (5, 6, 15), (215, 224, 238)),
    ((5, 12, 19), (10, 13, 26), (230, 236, 245)),
    ((7, 18, 27), (13, 18, 38), (242, 245, 250)),
    ((11, 27, 39), (20, 29, 58), (255, 255, 255)),
    ((232, 248, 255), (238, 244, 251), (16, 28, 58)),
    ((149, 173, 187), (159, 176, 201), (62, 81, 112)),
    ((98, 124, 139), (107, 122, 153), (90, 107, 138)),
    ((56, 215, 255), (93, 140, 242), (28, 63, 168)),
    ((242, 71, 155), (219, 153, 105), (176, 122, 63)),
    ((255, 64, 95), (217, 64, 72), (176, 42, 36)),
    ((230, 138, 76), (219, 153, 105), (176, 122, 63)),
]


def variable(value: str) -> str:
    return f"--seam-{hashlib.sha256(value.lower().encode()).hexdigest()[:12]}"


def map_function(value: str, mapping: dict[tuple[int, int, int], tuple[int, int, int]]) -> str:
    if not value.lower().startswith(("rgb(", "rgba(")):
        return value
    numbers = list(re.finditer(r"(?<![.\w])\d+(?![.\w])", value))
    if len(numbers) < 3:
        return value
    rgb = tuple(int(match.group()) for match in numbers[:3])
    replacement = mapping.get(rgb)
    if replacement is None:
        return value
    result = value
    for match, channel in reversed(list(zip(numbers[:3], replacement, strict=True))):
        result = result[: match.start()] + str(channel) + result[match.end() :]
    return result


def fallback_rgb(rgb: tuple[int, int, int], theme_index: int) -> tuple[int, int, int]:
    red, green, blue = (channel / 255 for channel in rgb)
    hue, saturation, lightness = colorsys.rgb_to_hls(red, green, blue)
    degrees = hue * 360
    # Preserve semantic categorical colors outside the skin's cyan/magenta/red families.
    if (
        saturation > 0.38
        and lightness > 0.22
        and not (165 <= degrees <= 215 or degrees >= 315 or degrees <= 15)
    ):
        return rgb
    source, seraph, gold = min(
        ANCHORS,
        key=lambda anchor: sum(
            (left - right) ** 2 for left, right in zip(rgb, anchor[0], strict=True)
        ),
    )
    del source
    return (seraph, gold)[theme_index]


def map_hex(value: str, explicit: dict[str, str], theme_index: int) -> str:
    lowered = value.lower()
    if lowered in explicit:
        return explicit[lowered]
    digits = lowered[1:]
    if len(digits) in (3, 4):
        digits = "".join(character * 2 for character in digits)
    rgb = tuple(int(digits[index : index + 2], 16) for index in (0, 2, 4))
    alpha = digits[6:8]
    mapped_rgb = fallback_rgb(rgb, theme_index)  # type: ignore[arg-type]
    return "#" + "".join(f"{channel:02x}" for channel in mapped_rgb) + alpha


def mapped(
    value: str,
    *,
    hex_map: dict[str, str],
    rgb_map: dict[tuple[int, int, int], tuple[int, int, int]],
    theme_index: int,
) -> str:
    lowered = value.lower()
    if lowered.startswith("#"):
        return map_hex(value, hex_map, theme_index)
    explicitly_mapped = map_function(value, rgb_map)
    if explicitly_mapped != value:
        return explicitly_mapped
    if lowered.startswith(("rgb(", "rgba(")):
        numbers = list(re.finditer(r"(?<![.\w])\d+(?![.\w])", value))
        if len(numbers) >= 3:
            rgb = tuple(int(match.group()) for match in numbers[:3])
            replacement = fallback_rgb(rgb, theme_index)  # type: ignore[arg-type]
            result = value
            for match, channel in reversed(list(zip(numbers[:3], replacement, strict=True))):
                result = result[: match.start()] + str(channel) + result[match.end() :]
            return result
    return value


def grimoire_transform(rgb: tuple[float, float, float], theme: str) -> tuple[float, float, float]:
    """D.2 116 freezes the FINAL kit's palette transform verbatim."""
    hue, lightness, saturation = colorsys.rgb_to_hls(*rgb)
    degrees = hue * 360
    if theme == "wizard-mode":
        if lightness < 0.16:
            target, changed_saturation = 28, min(saturation + 0.18, 0.45)
        elif lightness > 0.80:
            target, changed_saturation = 42, min(max(saturation, 0.12), 0.35)
        elif 150 <= degrees <= 215:
            target, changed_saturation = 40, min(saturation, 0.85)
        elif 215 < degrees <= 275:
            target, changed_saturation = 35, saturation * 0.8
        elif 275 < degrees <= 345:
            target, changed_saturation = 158, saturation * 0.75
        elif degrees > 345 or degrees <= 20:
            target, changed_saturation = 355, min(saturation, 0.8)
        else:
            target, changed_saturation = 40, saturation
    else:
        if lightness < 0.16:
            target, changed_saturation = 268, min(saturation + 0.22, 0.5)
        elif lightness > 0.80:
            target, changed_saturation = 140, min(max(saturation, 0.10), 0.3)
        elif 150 <= degrees <= 215:
            target, changed_saturation = 140, min(saturation, 0.95)
        elif 215 < degrees <= 275:
            target, changed_saturation = 275, saturation
        elif 275 < degrees <= 345:
            target, changed_saturation = 285, min(saturation, 0.95)
        elif degrees > 345 or degrees <= 20:
            target, changed_saturation = 350, min(saturation, 0.9)
        else:
            target, changed_saturation = 95, saturation * 0.9
    return colorsys.hls_to_rgb(target / 360, lightness, changed_saturation)


def grimoire_mapped(value: str, theme: str) -> str:
    """Apply the reference kit's exact hex/comma-rgb rewrite behavior."""

    def replace_hex(match: re.Match[str]) -> str:
        digits = match.group(1)
        if len(digits) == 3:
            digits = "".join(character * 2 for character in digits)
        source = tuple(int(digits[index : index + 2], 16) / 255 for index in (0, 2, 4))
        changed = grimoire_transform(source, theme)  # type: ignore[arg-type]
        return "#" + "".join(
            f"{max(0, min(255, round(channel * 255))):02x}" for channel in changed
        )

    def replace_rgb(match: re.Match[str]) -> str:
        parts = [part.strip() for part in match.group(1).split(",")]
        if len(parts) < 3:
            return match.group(0)
        try:
            source = tuple(float(part.split("/")[0]) / 255 for part in parts[:3])
        except ValueError:
            return match.group(0)
        changed = grimoire_transform(source, theme)  # type: ignore[arg-type]
        alpha = parts[3] if len(parts) == 4 else None
        values = ", ".join(str(round(channel * 255)) for channel in changed)
        return f"rgba({values}, {alpha})" if alpha else f"rgb({values})"

    return GRIMOIRE_RGBA.sub(replace_rgb, GRIMOIRE_HEX.sub(replace_hex, value))


def manifest_from_literals(literals: list[str]) -> dict[str, object]:
    unique = list(dict.fromkeys(literals))
    colors = []
    for value in unique:
        colors.append(
            {
                "gold_lines": mapped(value, hex_map=GOLD_HEX, rgb_map=GOLD_RGB, theme_index=1),
                "neo_noir": value,
                "seraph_dressed": mapped(
                    value, hex_map=SERAPH_HEX, rgb_map=SERAPH_RGB, theme_index=0
                ),
                "technomancer": grimoire_mapped(value, "technomancer"),
                "variable": variable(value),
                "wizard_mode": grimoire_mapped(value, "wizard-mode"),
            }
        )
    return {
        "colors": colors,
        "schema_version": 1,
        "source_files": [str(path) for path in ASSET_FILES],
    }


def css_from_manifest(manifest: dict[str, object]) -> str:
    colors = manifest["colors"]
    assert isinstance(colors, list)
    blocks = ["/* Generated by scripts/build_theme_seam.py --record; do not edit. */"]
    for theme, key in (
        ("neo-noir", "neo_noir"),
        ("seraph-dressed", "seraph_dressed"),
        ("gold-lines", "gold_lines"),
        ("wizard-mode", "wizard_mode"),
        ("technomancer", "technomancer"),
    ):
        selector = ":root" if theme == "neo-noir" else f':root[data-theme="{theme}"]'
        if theme == "neo-noir":
            selector += f', :root[data-theme="{theme}"]'
        blocks.append(f"{selector} {{")
        for entry in colors:
            assert isinstance(entry, dict)
            blocks.append(f"  {entry['variable']}: {entry[key]};")
        blocks.append("}")
    return "\n".join(blocks) + "\n"


def record() -> None:
    texts = {path: path.read_text() for path in ASSET_FILES}
    literals = [match.group() for path in ASSET_FILES for match in COLOR.finditer(texts[path])]
    if not literals:
        raise SystemExit("no literals found; the seam appears to have already been recorded")
    manifest = manifest_from_literals(literals)
    entries = manifest["colors"]
    assert isinstance(entries, list)
    replacements = {
        str(entry["neo_noir"]): f"var({entry['variable']})"
        for entry in entries
        if isinstance(entry, dict)
    }
    for path, source in texts.items():
        path.write_text(COLOR.sub(lambda match: replacements[match.group()], source))
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    THEMES_CSS.write_text(css_from_manifest(manifest))


def check() -> None:
    leaks = {
        str(path): COLOR.findall(path.read_text())
        for path in ASSET_FILES
        if COLOR.search(path.read_text())
    }
    if leaks:
        raise SystemExit(
            f"color literals escaped the theme seam: {json.dumps(leaks, sort_keys=True)}"
        )
    manifest = json.loads(MANIFEST.read_text())
    expected_css = css_from_manifest(manifest)
    if THEMES_CSS.read_text() != expected_css:
        raise SystemExit("generated theme seam drifted from seam-colors.json")
    defined = {str(entry["variable"]) for entry in manifest["colors"]}
    used = {
        match.group(1)
        for path in ASSET_FILES
        for match in re.finditer(r"var\((--seam-[0-9a-f]{12})\)", path.read_text())
    }
    if used != defined:
        missing = sorted(used - defined)
        unused = sorted(defined - used)
        raise SystemExit(f"theme seam use/definition mismatch: missing={missing}, unused={unused}")


def refresh() -> None:
    manifest = json.loads(MANIFEST.read_text())
    colors = manifest["colors"]
    for entry in colors:
        value = str(entry["neo_noir"])
        entry["seraph_dressed"] = mapped(
            value, hex_map=SERAPH_HEX, rgb_map=SERAPH_RGB, theme_index=0
        )
        entry["gold_lines"] = mapped(value, hex_map=GOLD_HEX, rgb_map=GOLD_RGB, theme_index=1)
        entry["wizard_mode"] = grimoire_mapped(value, "wizard-mode")
        entry["technomancer"] = grimoire_mapped(value, "technomancer")
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    THEMES_CSS.write_text(css_from_manifest(manifest))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--record", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    if args.record and args.refresh:
        raise SystemExit("choose only one mutation mode")
    if args.record:
        record()
    elif args.refresh:
        refresh()
    else:
        check()


if __name__ == "__main__":
    main()
