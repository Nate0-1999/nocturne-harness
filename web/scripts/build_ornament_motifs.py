#!/usr/bin/env python3
"""Build the motif layer of the two ornament themes (M3GT, SD-078, D.2 180).

Art Deco and Bellagio Lobby Ceiling wear procedural SVG ornaments — seeded, deterministic,
drawn here rather than copied — on the Stage background, the module frames, the Stage grid
and the head strip that follows each module name. Every ornament sits behind or around data,
never on it, and each theme carries a dark and a light face (the system's appearance picks).
"""

from __future__ import annotations

import argparse
import math
import random
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "src" / "themes" / "ornament.generated.css"

GOLD, INK = "#d6b04a", "#15120d"
JEWELS_NIGHT = ("#ff5468", "#ffb43a", "#6f97ff", "#3ccf86", "#c08cff", "#ff8a4a")
JEWELS_DAY = ("#a3122e", "#c98a00", "#143c9c", "#0f6a3a", "#5a2384", "#b8470f")


def uri(svg: str) -> str:
    return 'url("data:image/svg+xml,' + quote(svg, safe="") + '")'


def svg(width: float, height: float, body: str, aspect: str = "xMidYMid meet") -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:g}" height="{height:g}" '
        f'viewBox="0 0 {width:g} {height:g}" preserveAspectRatio="{aspect}">{body}</svg>'
    )


# ---- Art Deco: the sun with an empty disc, fans, chevrons --------------------------------


def deco_sun(color: str, opacity: float, wedges: float) -> str:
    """A sun rising from the foot of the Stage: rays from an empty double-ringed disc, every
    other ray-gap leafed, stepped rings around it (the owner's 'empty disk')."""
    width, height, cx, cy, rays, disc = 1600, 1000, 800, 1000, 96, 180
    parts, leaf = [], []
    inner, outer = disc + 22, 1300
    for index in range(rays):
        angle = math.pi * index / rays
        x1, y1 = cx - inner * math.cos(angle), cy - inner * math.sin(angle)
        x2, y2 = cx - outer * math.cos(angle), cy - outer * math.sin(angle)
        parts.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke-width="{2.2 if index % 4 == 0 else 0.9}"/>'
        )
        if index % 2 == 0:
            following = math.pi * (index + 1) / rays
            leaf.append(
                f"M{x1:.1f},{y1:.1f} L{x2:.1f},{y2:.1f} "
                f"L{cx - outer * math.cos(following):.1f},{cy - outer * math.sin(following):.1f} "
                f"L{cx - inner * math.cos(following):.1f},{cy - inner * math.sin(following):.1f}Z"
            )
    for radius in (disc + 60, disc + 150, disc + 270):
        points: list[str] = []
        for step in range(19):
            angle = math.pi * step / 18
            x, y = cx - radius * math.cos(angle), cy - radius * math.sin(angle)
            if points:
                points.append(f"{x:.1f},{points[-1].split(',')[1]}")
            points.append(f"{x:.1f},{y:.1f}")
        parts.append(f'<polyline points="{" ".join(points)}" stroke-width="1.5"/>')
    disc_rings = "".join(
        f'<circle cx="{cx}" cy="{cy}" r="{disc * share:.1f}" fill="none" stroke="{color}" '
        f'stroke-opacity="{min(1.0, opacity + 0.35):.2f}" '
        f'stroke-width="{3 if share == 1 else 1.4}"/>'
        for share in (1, 0.93)
    )
    body = (
        f'<path d="{" ".join(leaf)}" fill="{color}" fill-opacity="{wedges}"/>'
        f'<g fill="none" stroke="{color}" stroke-opacity="{opacity}" stroke-linecap="square">'
        f"{''.join(parts)}</g>{disc_rings}"
    )
    return svg(width, height, body, "xMidYMax slice")


def fans(color: str, count: int = 7) -> str:
    """The head strip: small rising fans, the sunburst in miniature."""
    unit, height = 22, 18
    parts = []
    for index in range(count):
        cx, cy = index * unit + 11, 16
        for ray in range(7):
            angle = math.pi * (ray + 0.5) / 7
            parts.append(
                f'<line x1="{cx:.1f}" y1="{cy}" x2="{cx - 9 * math.cos(angle):.1f}" '
                f'y2="{cy - 9 * math.sin(angle):.1f}" stroke-width="0.9"/>'
            )
        parts.append(
            f'<path d="M{cx - 10},{cy} A10,10 0 0 1 {cx + 10},{cy}" stroke-width="1.3"/>'
        )
    return svg(count * unit, height, f'<g fill="none" stroke="{color}">{"".join(parts)}</g>')


def zigzag(color: str) -> str:
    """A band of small chevrons for the foot of a module head."""
    path = "M0,5.4 L3,1 L6,5.4 L9,1 L12,5.4"
    return svg(12, 6.4, f'<path d="{path}" fill="none" stroke="{color}" stroke-width="1.1"/>')


def lozenge(color: str, size: int) -> str:
    """The Stage grid's mark: a small lozenge where the fine lines cross."""
    half = size / 2
    body = (
        f'<path d="M0,0 L1.6,1.6 L0,3.2 L-1.6,1.6Z" transform="translate({half} {half - 1.6})" '
        f'fill="{color}"/>'
    )
    return svg(size, size, body)


# ---- Bellagio: blown glass — Persian discs, horns, trumpets, tendrils ---------------------


def mix(color: str, other: str, share: float) -> str:
    left = [int(color[index : index + 2], 16) for index in (1, 3, 5)]
    right = [int(other[index : index + 2], 16) for index in (1, 3, 5)]
    return "#" + "".join(
        f"{round(a + (b - a) * share):02x}" for a, b in zip(left, right, strict=True)
    )


def polar(radius: float, angle: float) -> str:
    return f"{radius * math.cos(angle):.1f},{radius * math.sin(angle):.1f}"


def wavy(radius: float, ruffles: int, phase: float, depth: float, steps: int) -> str:
    return " ".join(
        polar(
            radius * (1 + depth * math.sin(ruffles * step / steps * math.tau + phase)),
            step / steps * math.tau,
        )
        for step in range(steps)
    )


def persian(rng: random.Random, color: int, lip: int) -> str:
    """A ruffled glass disc: a wavy rim, striations from the throat, a lip of another colour."""
    ruffles, phase = rng.randint(9, 14), rng.uniform(0, math.tau)
    rim, inner = wavy(50, ruffles, phase, 0.07, 72), wavy(33, ruffles, phase, 0.06, 48)
    striae = "".join(
        f'<line x1="{polar(9, angle).split(",")[0]}" y1="{polar(9, angle).split(",")[1]}" '
        f'x2="{polar(47, angle).split(",")[0]}" y2="{polar(47, angle).split(",")[1]}"/>'
        for angle in (index / ruffles * math.tau + phase for index in range(ruffles))
    )
    return (
        f'<polygon points="{rim}" fill="url(#g{color})" stroke="url(#g{lip})" stroke-width="3"/>'
        f'<polygon points="{inner}" fill="none" stroke="#ffffff" stroke-opacity="0.35" '
        'stroke-width="1.5"/>'
        f'<g stroke="#000000" stroke-opacity="0.18" stroke-width="1.2">{striae}</g>'
        f'<polygon points="{inner}" fill="none" stroke="url(#g{lip})" stroke-opacity="0.7" '
        'stroke-width="5" transform="scale(1.22)"/>'
        f'<circle r="8" fill="url(#g{lip})"/>'
        '<path d="M-30,-22 Q-12,-38 14,-36" fill="none" stroke="#ffffff" stroke-opacity="0.55" '
        'stroke-width="3" stroke-linecap="round"/>'
    )


def horn(color: int) -> str:
    """A spiral horn: a tapered glass tube curling into itself."""
    turns, outer, inner = [], [], []
    for step in range(40):
        share = step / 39
        angle = share * 2.6 * math.pi
        radius = 50 * (1 - share * 0.82)
        width = 13 * (1 - share * 0.85)
        x, y = radius * math.cos(angle), radius * math.sin(angle)
        nx, ny = math.cos(angle), math.sin(angle)
        outer.append(f"{x + nx * width:.1f},{y + ny * width:.1f}")
        inner.append(f"{x - nx * width:.1f},{y - ny * width:.1f}")
        turns.append(f"{x + nx * width * 0.45:.1f},{y + ny * width * 0.45:.1f}")
    return (
        f'<polygon points="{" ".join(outer + inner[::-1])}" fill="url(#g{color})"/>'
        f'<polyline points="{" ".join(turns)}" fill="none" stroke="#ffffff" stroke-opacity="0.5" '
        'stroke-width="2.2" stroke-linecap="round"/>'
    )


def bloom(rng: random.Random, color: int, lip: int) -> str:
    """A ruffled trumpet seen from below: broad overlapping petals around a bright throat."""
    petals, turn, parts = rng.randint(5, 7), rng.uniform(0, math.tau), []
    for index in range(petals):
        angle = turn + index / petals * math.tau
        spread = math.pi / petals * 1.35
        tip, left, right = polar(50, angle), polar(46, angle - spread), polar(46, angle + spread)
        parts.append(
            f'<path d="M0,0 Q{left} {tip} Q{right} 0,0Z" fill="url(#g{color})" '
            f'stroke="url(#g{lip})" stroke-width="2"/>'
        )
    return "".join(parts) + f'<circle r="11" fill="url(#g{lip})"/>'


def tendril(rng: random.Random, color: int) -> str:
    """A long glass tendril: a tapering rod that sways and ends in a curl."""
    outer, inner, spine = [], [], []
    sway = rng.uniform(18, 28)
    for step in range(48):
        share = step / 47
        if share < 0.7:
            along = share / 0.7
            x, y = -58 + 96 * along, sway * math.sin(along * math.pi * 1.2)
            heading = math.atan2(sway * math.pi * 1.2 / 96 * math.cos(along * math.pi * 1.2), 1)
        else:
            turn = (share - 0.7) / 0.3 * 1.6 * math.pi
            radius = 14 * (1 - (share - 0.7) / 0.3 * 0.6)
            x = 38 + radius * math.sin(turn)
            y = sway * math.sin(math.pi * 1.2) - radius + radius * math.cos(turn)
            heading = -turn
        width = 8 * (1 - share * 0.8)
        nx, ny = -math.sin(heading), math.cos(heading)
        outer.append(f"{x + nx * width:.1f},{y + ny * width:.1f}")
        inner.append(f"{x - nx * width:.1f},{y - ny * width:.1f}")
        spine.append(f"{x + nx * width * 0.4:.1f},{y + ny * width * 0.4:.1f}")
    return (
        f'<polygon points="{" ".join(outer + inner[::-1])}" fill="url(#g{color})"/>'
        f'<polyline points="{" ".join(spine)}" fill="none" stroke="#ffffff" stroke-opacity="0.45" '
        'stroke-width="1.6" stroke-linecap="round"/>'
    )


# One light for the whole ceiling, high at the top-left: a specular sheen across each piece's
# swell and a bright edge where the glass turns away — what reads as glass.
GLOSS = (
    '<filter id="gloss" x="-10%" y="-10%" width="120%" height="120%" '
    'color-interpolation-filters="sRGB">'
    '<feGaussianBlur in="SourceAlpha" stdDeviation="5" result="swell"/>'
    '<feSpecularLighting in="swell" surfaceScale="6" specularConstant="1.3" '
    'specularExponent="42" lighting-color="#ffffff" result="sheen">'
    '<feDistantLight azimuth="225" elevation="52"/></feSpecularLighting>'
    '<feComposite in="sheen" in2="SourceAlpha" operator="in" result="lit"/>'
    '<feMorphology in="SourceAlpha" operator="erode" radius="1" result="core"/>'
    '<feComposite in="SourceAlpha" in2="core" operator="out" result="edge"/>'
    '<feFlood flood-color="#ffffff" flood-opacity="0.38"/>'
    '<feComposite in2="edge" operator="in" result="rim"/>'
    '<feMerge><feMergeNode in="SourceGraphic"/><feMergeNode in="rim"/>'
    '<feMergeNode in="lit"/></feMerge></filter>'
)


def glass_kit(jewels: tuple[str, ...], body: str, glow: bool = False, lucent: bool = False) -> str:
    """Gradients lit from within (the ceiling's a little translucent) and one symbol per form
    and colour the body uses; one seed for the forms, so every surface draws the same glass."""
    rng = random.Random("bellagio-kit")
    core, middle = ("0.88", "0.94") if lucent else ("1.00", "1.00")
    defs = [
        f'<radialGradient id="g{index}" cx="0.4" cy="0.35" r="0.75">'
        f'<stop offset="0" stop-color="{mix(color, "#ffffff", 0.35)}" stop-opacity="{core}"/>'
        f'<stop offset="0.5" stop-color="{color}" stop-opacity="{middle}"/>'
        f'<stop offset="1" stop-color="{mix(color, "#000000", 0.45)}"/></radialGradient>'
        for index, color in enumerate(jewels)
    ]
    for index in range(len(jewels)):
        lip = (index + 2) % len(jewels)
        for kind, shape in (
            ("p", persian(rng, index, lip)),
            ("h", horn(index)),
            ("b", bloom(rng, index, lip)),
            ("t", tendril(rng, index)),
        ):
            if f'href="#{kind}{index}"' in body:
                defs.append(
                    f'<symbol id="{kind}{index}" viewBox="-60 -60 120 120" overflow="visible">'
                    f"{shape}</symbol>"
                )
    if glow:
        defs.append(
            '<filter id="glow" x="-20%" y="-20%" width="140%" height="140%">'
            '<feGaussianBlur stdDeviation="9"/></filter>'
        )
    if 'filter="url(#gloss)"' in body:
        defs.append(GLOSS)
    return "<defs>" + "".join(defs) + "</defs>"


def ceiling(jewels: tuple[str, ...], glow: bool, blend: str) -> str:
    """The Stage as the lobby ceiling: 34 large pieces on a jittered grid, each lit by GLOSS,
    the largest hung first; by night a soft glow behind, by day the glass multiplies the sand."""
    width, height, count, scale = 1600, 1000, 34, 340
    rng = random.Random("canopy-l2")
    columns = round(math.sqrt(count * width / height))
    rows = math.ceil(count / columns)
    pieces = []
    for index in range(count):
        row, column = divmod(index, columns)
        x = (column + rng.uniform(0, 1)) * width / columns
        y = (row + rng.uniform(0, 1)) * height / rows
        size = scale * rng.uniform(0.6, 1.15)
        kind = rng.choices("phbt", weights=(6, 3, 1, 3))[0]
        use = (
            f'<use href="#{kind}{rng.randrange(6)}" width="120" height="120" '
            f'transform="translate({x:.0f} {y:.0f}) rotate({rng.randrange(360)}) '
            f'scale({size / 100:.2f}) translate(-60 -60)"/>'
        )
        pieces.append((size, f'<g filter="url(#gloss)">{use}</g>'))
    uses = "".join(use for _, use in sorted(pieces, key=lambda item: -item[0]))
    halo = f'<g filter="url(#glow)" opacity="0.8">{uses}</g>' if glow else ""
    style = f' style="mix-blend-mode:{blend}"' if blend != "normal" else ""
    body = glass_kit(jewels, uses, glow, lucent=True) + halo + f"<g{style}>{uses}</g>"
    return svg(width, height, body, "xMidYMid slice")


def glass_strip(jewels: tuple[str, ...]) -> str:
    """The head strip: six small pieces of glass, discs and horns, in a row."""
    rng = random.Random("strip-l2")
    uses = "".join(
        f'<use href="#{"ph"[index % 2]}{(index * 2 + 1) % 6}" width="120" height="120" '
        f'transform="translate({index * 20 + 10} 9) rotate({rng.randrange(360)}) scale(0.16) '
        'translate(-60 -60)"/>'
        for index in range(6)
    )
    return svg(120, 18, glass_kit(jewels, uses) + uses)


# ---- the themes -------------------------------------------------------------------------


def face_css(theme: str, light: bool, values: dict[str, str]) -> str:
    lines = "".join(f"  --ornament-{name}: {value};\n" for name, value in values.items())
    block = f'html[data-theme="{theme}"] {{\n{lines}}}'
    if light:
        return "@media (prefers-color-scheme: light) {\n" + block.replace("\n", "\n  ") + "\n}"
    return block


# The worn fine-grid mark (rack.css), kept where a theme does not mark its own grid.
WORN_GRID_MARK = "radial-gradient(circle at 1px 1px, var(--line-strong) 0 0.8px, transparent 1px)"


def theme_css(theme: str, dark: dict[str, str], light: dict[str, str], frame: str) -> str:
    """One theme: its two faces' ornaments, then where they sit — the Stage background under
    the canvas, the grid, the head strip in the name's yielding slot, the frame."""
    root = f'html[data-theme="{theme}"]'
    stage = f"{root} .stage-viewport:not(.stage-viewport--sheet)"
    return f"""{face_css(theme, False, dark)}

{face_css(theme, True, light)}

{root} .rack-shell {{
  background: var(--ground) fixed;
}}

{stage} {{
  isolation: isolate;
}}

{stage}::before {{
  position: absolute;
  z-index: -1;
  inset: 0;
  background: var(--ornament-stage) center / cover no-repeat;
  content: "";
  pointer-events: none;
}}

{root} .stage-canvas {{
  background-image:
    var(--ornament-grid, {WORN_GRID_MARK}),
    linear-gradient(var(--line) 1px, transparent 1px),
    linear-gradient(90deg, var(--line) 1px, transparent 1px);
}}

{root} .rack-module__drag::after {{
  order: 1;
  flex: 0 1000000 auto;
  min-width: 0;
  width: 7.5rem;
  height: 1.15rem;
  background: var(--ornament-strip) left center / auto 100% repeat-x;
  content: "";
  opacity: 0.9;
  pointer-events: none;
}}

{root} .rack-module__drag > .rack-module__attunement {{
  order: 2;
}}

{frame.replace("ROOT", root)}"""


# Art Deco's frame: a double rule (the border and a ring outside it), square corners, and a
# band of chevrons under every module head.
DECO_FRAME = """ROOT .rack-module {
  border-color: var(--accent);
  box-shadow: 0 0 0 2px var(--ground), 0 0 0 3px var(--accent);
}

ROOT .rack-module::before,
ROOT .rack-module::after {
  display: none;
}

ROOT .rack-module__chrome {
  background-image: var(--ornament-band);
  background-position: left bottom;
  background-repeat: repeat-x;
  background-size: 0.75rem 0.4rem;
}"""

# Bellagio's frame: one hairline in the accent, square corners; the glass is the ornament.
GLASS_FRAME = """ROOT .rack-module {
  border-color: var(--accent);
  box-shadow: none;
}

ROOT .rack-module::before,
ROOT .rack-module::after {
  display: none;
}"""


def render() -> str:
    deco = theme_css(
        "art-deco",
        {
            "stage": uri(deco_sun(GOLD, 0.45, 0.04)),
            "strip": uri(fans(GOLD)),
            "grid": uri(lozenge(GOLD, 16)),
            "band": uri(zigzag(GOLD)),
        },
        {
            "stage": uri(deco_sun(INK, 0.28, 0.03)),
            "strip": uri(fans(INK)),
            "grid": uri(lozenge(INK, 16)),
            "band": uri(zigzag(INK)),
        },
        DECO_FRAME,
    )
    bellagio = theme_css(
        "bellagio",
        {
            "stage": uri(ceiling(JEWELS_NIGHT, True, "normal")),
            "strip": uri(glass_strip(JEWELS_NIGHT)),
        },
        {
            "stage": uri(ceiling(JEWELS_DAY, False, "multiply")),
            "strip": uri(glass_strip(JEWELS_DAY)),
        },
        GLASS_FRAME,
    )
    return "\n\n".join(
        [
            "/* Generated by web/scripts/build_ornament_motifs.py; do not edit. */",
            "/* M3GT / SD-078 / D.2 180: Art Deco (E2) and Bellagio Lobby Ceiling (L2). */",
            deco,
            bellagio,
        ]
    ) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = render()
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text() != expected:
            print(f"stale generated ornament CSS: {OUTPUT}")
            return 1
        print(f"ornament CSS is current: {OUTPUT}")
        return 0
    OUTPUT.write_text(expected)
    print(f"wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
