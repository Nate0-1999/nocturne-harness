#!/usr/bin/env python3
"""Check the two M3SL owner captures against pinned visual-character bounds."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BOUNDS = json.loads((ROOT / "emulation-bounds.json").read_text())


def rgb_pixels(path: Path) -> tuple[int, int, bytes]:
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    stream = json.loads(probe.stdout)["streams"][0]
    width, height = int(stream["width"]), int(stream["height"])
    rendered = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        check=True,
        capture_output=True,
    )
    return width, height, rendered.stdout


def metrics(path: Path) -> dict[str, float]:
    width, height, raw = rgb_pixels(path)
    sample_step = 4
    total = dark = light = chromatic = ink = edges = comparisons = 0
    for y in range(0, height, sample_step):
        for x in range(0, width, sample_step):
            offset = (y * width + x) * 3
            red, green, blue = raw[offset : offset + 3]
            luma = 0.2126 * red + 0.7152 * green + 0.0722 * blue
            total += 1
            dark += luma < 45
            light += luma > 180
            ink += luma < 110
            chromatic += max(red, green, blue) - min(red, green, blue) > 25
            if x + sample_step < width:
                next_offset = (y * width + x + sample_step) * 3
                nr, ng, nb = raw[next_offset : next_offset + 3]
                next_luma = 0.2126 * nr + 0.7152 * ng + 0.0722 * nb
                edges += abs(luma - next_luma) > 20
                comparisons += 1
    return {
        "dark_ratio": round(dark / total, 6),
        "light_ratio": round(light / total, 6),
        "ink_ratio": round(ink / total, 6),
        "chromatic_ratio": round(chromatic / total, 6),
        "horizontal_edge_ratio": round(edges / comparisons, 6),
    }


def main() -> int:
    failures: list[str] = []
    observed: dict[str, dict[str, float]] = {}
    for capture, rules in BOUNDS["captures"].items():
        observed[capture] = metrics(ROOT / capture)
        for name, limits in rules.items():
            value = observed[capture][name]
            if not limits["min"] <= value <= limits["max"]:
                failures.append(
                    f"{capture}: {name}={value} outside "
                    f"[{limits['min']}, {limits['max']}]"
                )
    print(json.dumps(observed, indent=2, sort_keys=True))
    if failures:
        print("M3SL emulation check failed:")
        print("\n".join(f"- {failure}" for failure in failures))
        return 1
    print("M3SL emulation bounds: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
