"""THE SIGIL FORGE from the D.2 118-119 FINAL grimoire kit.

The machine hand is the owner-blessed v1 chamfered-walk algorithm. The
elvish hand is the stable v2.1 featural alphabet. Both are deterministic
and original-by-grammar rather than derived from protected letterforms.
"""

from __future__ import annotations

import random
from urllib.parse import quote

CELL = 10
W, H = 3, 4
STROKE = 3.4


def forge_sigil(seed: str) -> list[str]:
    """Return one machine-hand sigil; D.2 119 freezes this algorithm verbatim."""
    rng = random.Random(seed)
    paths = []
    x = rng.choice([0, 1, 2])
    y = 0
    points = [(x, y)]
    for _ in range(rng.randint(3, 5)):
        dx, dy = rng.choice([(1, 0), (-1, 0), (0, 1), (0, 1), (1, 1), (-1, 1)])
        next_x = max(0, min(W - 1, x + dx))
        next_y = max(0, min(H - 1, y + dy))
        if (next_x, next_y) != (x, y):
            points.append((next_x, next_y))
            x, y = next_x, next_y
    path = f"M{points[0][0] * CELL},{points[0][1] * CELL}" + "".join(
        f"L{point_x * CELL},{point_y * CELL}" for point_x, point_y in points[1:]
    )
    paths.append(path)
    for _ in range(rng.randint(1, 2)):
        anchor_x, anchor_y = rng.randint(0, W - 1), rng.randint(0, H - 1)
        kind = rng.choice(["hstub", "vstub", "chamfer", "dot"])
        if kind == "hstub":
            paths.append(
                f"M{anchor_x * CELL - 4},{anchor_y * CELL}L{anchor_x * CELL + 4},{anchor_y * CELL}"
            )
        elif kind == "vstub":
            paths.append(
                f"M{anchor_x * CELL},{anchor_y * CELL - 4}L{anchor_x * CELL},{anchor_y * CELL + 4}"
            )
        elif kind == "chamfer":
            paths.append(
                f"M{anchor_x * CELL - 4},{anchor_y * CELL + 4}"
                f"L{anchor_x * CELL + 4},{anchor_y * CELL - 4}"
            )
        else:
            paths.append(f"M{anchor_x * CELL},{anchor_y * CELL}l0.1,0")
    return paths


def strip_svg(n: int, color: str, seed_base: str, vertical: bool = False, gap: int = 14) -> str:
    """Emit a deterministic machine-hand SVG data-URI strip."""
    glyph_width, glyph_height = (W - 1) * CELL, (H - 1) * CELL
    pad = 6
    if vertical:
        total_width, total_height = glyph_width + 2 * pad, n * (glyph_height + gap) + pad
    else:
        total_width, total_height = n * (glyph_width + gap) + pad, glyph_height + 2 * pad
    parts = []
    for index in range(n):
        offset_x = pad + (0 if vertical else index * (glyph_width + gap))
        offset_y = pad + (index * (glyph_height + gap) if vertical else 0)
        for path in forge_sigil(f"{seed_base}-{index}"):
            parts.append(f'<path transform="translate({offset_x},{offset_y})" d="{path}"/>')
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{total_width}" height="{total_height}" '
        f'viewBox="0 0 {total_width} {total_height}"><g fill="none" stroke="{color}" '
        f'stroke-width="{STROKE}" stroke-linecap="square" stroke-linejoin="miter">'
        + "".join(parts)
        + "</g></svg>"
    )
    return "data:image/svg+xml," + quote(svg, safe="")


def _elvish_glyph(rng: random.Random) -> list[tuple[str, str]]:
    paths: list[tuple[str, str]] = []
    stem_kind = rng.choice(["tall", "short", "descender", "full", "tall", "descender"])
    top = {"tall": 2, "short": 9, "descender": 9, "full": 2}[stem_kind]
    bottom = {"tall": 22, "short": 22, "descender": 30, "full": 30}[stem_kind]
    stem_x = 9.0
    sway = rng.uniform(1.6, 2.8) * rng.choice([-1, 1])
    stem = (
        f"M{stem_x:.1f},{top}C{stem_x + sway:.1f},{top + (bottom-top)*0.33:.1f} "
        f"{stem_x - sway:.1f},{top + (bottom-top)*0.66:.1f} {stem_x:.1f},{bottom}"
    )
    paths.append((stem, "thick"))
    doubled = rng.random() < 0.22
    if doubled:
        paths.append(
            (
                f"M{stem_x+3.4:.1f},{top}C{stem_x+3.4+sway:.1f},{top+(bottom-top)*0.33:.1f} "
                f"{stem_x+3.4-sway:.1f},{top+(bottom-top)*0.66:.1f} {stem_x+3.4:.1f},{bottom}",
                "thick",
            )
        )
    side = rng.choice([-1, 1])
    lobe_count = rng.choice([1, 1, 2])
    fractions = [0.40] if lobe_count == 1 else [0.28, 0.60]
    attach_points = [top + (bottom - top) * fraction for fraction in fractions]
    for attach_y in attach_points:
        gap = 1.5 * side
        radius = rng.uniform(5.0, 6.8)
        start_x = stem_x + gap + (3.4 if doubled and side > 0 else 0)
        if rng.random() < 0.55:
            paths.append(
                (
                    f"M{start_x:.1f},{attach_y:.1f}"
                    f"C{start_x+side*radius*1.6:.1f},{attach_y-radius*0.85:.1f} "
                    f"{start_x+side*radius*1.6:.1f},{attach_y+radius*1.25:.1f} "
                    f"{start_x:.1f},{attach_y+radius:.1f}",
                    "thin",
                )
            )
            paths.append(
                (
                    f"M{start_x:.1f},{attach_y+radius:.1f}"
                    f"L{start_x:.1f},{attach_y+radius*0.45:.1f}",
                    "thick",
                )
            )
        else:
            paths.append(
                (
                    f"M{start_x:.1f},{attach_y:.1f}"
                    f"C{start_x+side*radius*1.6:.1f},{attach_y-radius*0.75:.1f} "
                    f"{start_x+side*radius*1.5:.1f},{attach_y+radius*1.15:.1f} "
                    f"{start_x+side*1.4:.1f},{attach_y+radius*0.95:.1f}",
                    "thin",
                )
            )
    if rng.random() < 0.3:
        cross_y = top + (bottom - top) * rng.uniform(0.3, 0.55)
        paths.append(
            (
                f"M{stem_x-4.6:.1f},{cross_y:.1f}"
                f"L{stem_x+4.6+(3.4 if doubled else 0):.1f},{cross_y:.1f}",
                "thin",
            )
        )
    if stem_kind in ("descender", "full") and rng.random() < 0.75:
        paths.append(
            (
                f"M{stem_x:.1f},{bottom}c{-side*2.4:.1f},2.6 "
                f"{-side*5.6:.1f},2.4 {-side*6.6:.1f},0.2",
                "thin",
            )
        )
    tehta = rng.choice(["none", "dot", "ddot", "tdots", "tilde", "arc"])
    tehta_y = top - 3.0
    if tehta == "dot":
        paths.append((f"M{stem_x:.1f},{tehta_y:.1f}l0.1,0", "thick"))
    elif tehta == "ddot":
        paths.extend(
            [
                (f"M{stem_x-2.6:.1f},{tehta_y:.1f}l0.1,0", "thick"),
                (f"M{stem_x+2.6:.1f},{tehta_y:.1f}l0.1,0", "thick"),
            ]
        )
    elif tehta == "tdots":
        paths.extend(
            [
                (f"M{stem_x:.1f},{tehta_y-2.2:.1f}l0.1,0", "thick"),
                (f"M{stem_x-2.4:.1f},{tehta_y+0.6:.1f}l0.1,0", "thick"),
                (f"M{stem_x+2.4:.1f},{tehta_y+0.6:.1f}l0.1,0", "thick"),
            ]
        )
    elif tehta == "tilde":
        paths.append((f"M{stem_x-3.8:.1f},{tehta_y:.1f}c2.3,-2.7 5.2,2.7 7.6,0", "thin"))
    elif tehta == "arc":
        paths.append((f"M{stem_x-3.4:.1f},{tehta_y+0.7:.1f}c1.5,-3.1 5.3,-3.1 6.8,0", "thin"))
    return paths


def build_alphabet(n: int = 24, version: str = "v2") -> list[list[tuple[str, str]]]:
    """Build the stable 24-glyph elvish-hand alphabet."""
    rng = random.Random(f"nocturne-elvish-{version}")
    return [_elvish_glyph(rng) for _ in range(n)]


_ELVISH = build_alphabet()


def _sequence(n: int, seed: str) -> list[list[tuple[str, str]]]:
    rng = random.Random(seed)
    weights = [1.0 / (index + 2) for index in range(len(_ELVISH))]
    return [_ELVISH[index] for index in rng.choices(range(len(_ELVISH)), weights=weights, k=n)]


def elvish_strip(n: int, color: str, seed_base: str, vertical: bool = False, gap: int = 4) -> str:
    """Emit a deterministic elvish-hand SVG data-URI strip."""
    glyph_width, glyph_height = 17, 34
    pad = 4
    if vertical:
        total_width, total_height = glyph_width + 2 * pad, n * (glyph_height + gap) + pad
    else:
        total_width, total_height = n * (glyph_width + gap) + pad, glyph_height + 2 * pad
    thick: list[str] = []
    thin: list[str] = []
    for index, glyph in enumerate(_sequence(n, seed_base)):
        offset_x = pad + (0 if vertical else index * (glyph_width + gap))
        offset_y = pad + (index * (glyph_height + gap) if vertical else 0)
        for path, weight in glyph:
            (thick if weight == "thick" else thin).append(
                f'<path transform="translate({offset_x},{offset_y})" d="{path}"/>'
            )
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{total_width}" height="{total_height}" '
        f'viewBox="0 0 {total_width} {total_height}">'
        f'<g fill="none" stroke="{color}" stroke-width="2.6" '
        'stroke-linecap="round" stroke-linejoin="round">'
        + "".join(thick)
        + "</g>"
        f'<g fill="none" stroke="{color}" stroke-width="1.3" '
        'stroke-linecap="round" stroke-linejoin="round">'
        + "".join(thin)
        + "</g></svg>"
    )
    return "data:image/svg+xml," + quote(svg, safe="")


__all__ = ["build_alphabet", "elvish_strip", "forge_sigil", "strip_svg"]
