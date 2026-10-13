#!/usr/bin/env python3
"""Build the motif layer of the two authored ornament themes (M3GT, SD-078).

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


def uri(svg: str) -> str:
    return 'url("data:image/svg+xml,' + quote(svg, safe="") + '")'


def svg(width: float, height: float, body: str, aspect: str = "xMidYMid meet") -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:g}" height="{height:g}" '
        f'viewBox="0 0 {width:g} {height:g}" preserveAspectRatio="{aspect}">{body}</svg>'
    )


# ---- Art Deco: rays, steps, chevrons, fans --------------------------------------------------


def sunburst(color: str, opacity: float, rays: int, rings: tuple[int, ...], crown: bool = False,
             alternate: str | None = None, wedges: float = 0.0) -> str:
    """A stepped sunburst rising from the bottom edge — or, as a crown, hanging from the top."""
    width, height, cx = 1600, 1000, 800
    cy, rise = (0, -1) if crown else (1000, 1)
    parts, fills = [], []
    inner, outer = (rings[0] if rings else 90), 1250
    for index in range(rays + 1):
        angle = math.pi * index / rays
        x1, y1 = cx - inner * math.cos(angle), cy - rise * inner * math.sin(angle)
        x2, y2 = cx - outer * math.cos(angle), cy - rise * outer * math.sin(angle)
        stroke = 2.2 if index % 4 == 0 else 0.9
        tint = f' stroke="{alternate}"' if alternate and index % 4 == 0 else ""
        parts.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke-width="{stroke}"{tint}/>'
        )
        if wedges and index % 2 == 0 and index < rays:
            following = math.pi * (index + 1) / rays
            x3, y3 = cx - outer * math.cos(following), cy - rise * outer * math.sin(following)
            x4, y4 = cx - inner * math.cos(following), cy - rise * inner * math.sin(following)
            fills.append(f"M{x1:.1f},{y1:.1f} L{x2:.1f},{y2:.1f} L{x3:.1f},{y3:.1f} L{x4:.1f},{y4:.1f}Z")
    for radius in rings:
        steps, points = 14, []
        for step in range(steps + 1):
            angle = math.pi * step / steps
            x, y = cx - radius * math.cos(angle), cy - rise * radius * math.sin(angle)
            if points:
                points.append(f"{x:.1f},{points[-1].split(',')[1]}")
            points.append(f"{x:.1f},{y:.1f}")
        parts.append(f'<polyline points="{" ".join(points)}" stroke-width="1.6"/>')
        parts.append(
            f'<path d="M{cx - radius - 14},{cy} A{radius + 14},{radius + 14} 0 0 {0 if crown else 1} '
            f'{cx + radius + 14},{cy}" stroke-width="0.8"/>'
        )
    leaf = (
        f'<path d="{" ".join(fills)}" fill="{alternate or color}" fill-opacity="{wedges}"/>'
        if fills
        else ""
    )
    body = leaf + (
        f'<g fill="none" stroke="{color}" stroke-opacity="{opacity}" '
        f'stroke-linecap="square">{"".join(parts)}</g>'
    )
    return svg(width, height, body, "xMidYMin slice" if crown else "xMidYMax slice")


def deco_sun(color: str, opacity: float, rays: int, disc: int, style: str, full: bool = False,
             metal: str | None = None, wedges: float = 0.0, steps: bool = True) -> str:
    """The sun with its disc: rays from the disc's edge, stepped rings, a solid, ringed or
    striped disc — rising from the foot of the Stage, or whole in its middle."""
    width, height = 1600, 1000
    cx, cy = (800, 560) if full else (800, 1000)
    sweep = math.tau if full else math.pi
    fill = metal or color
    parts, wedge_paths = [], []
    inner, outer = disc + 22, 1300
    for index in range(rays):
        angle = sweep * index / rays
        x1, y1 = cx - inner * math.cos(angle), cy - inner * math.sin(angle)
        x2, y2 = cx - outer * math.cos(angle), cy - outer * math.sin(angle)
        parts.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke-width="{2.2 if index % 4 == 0 else 0.9}"/>'
        )
        if wedges and index % 2 == 0:
            following = sweep * (index + 1) / rays
            wedge_paths.append(
                f"M{x1:.1f},{y1:.1f} L{x2:.1f},{y2:.1f} "
                f"L{cx - outer * math.cos(following):.1f},{cy - outer * math.sin(following):.1f} "
                f"L{cx - inner * math.cos(following):.1f},{cy - inner * math.sin(following):.1f}Z"
            )
    for radius in (disc + 60, disc + 150, disc + 270) if steps else ():
        steps, points = (40 if full else 18), []
        for step in range(steps + 1):
            angle = sweep * step / steps
            x, y = cx - radius * math.cos(angle), cy - radius * math.sin(angle)
            if points:
                points.append(f"{x:.1f},{points[-1].split(',')[1]}")
            points.append(f"{x:.1f},{y:.1f}")
        parts.append(f'<polyline points="{" ".join(points)}" stroke-width="1.5"/>')
    defs = (
        f'<defs><radialGradient id="sun" cx="0.5" cy="{0.5 if full else 1}" r="{0.5 if full else 1}">'
        f'<stop offset="0" stop-color="{fill}" stop-opacity="0.75"/>'
        f'<stop offset="1" stop-color="{fill}" stop-opacity="0.35"/></radialGradient>'
    )
    if style == "striped":
        bands = "".join(
            f'<rect x="0" y="{cy - disc + band * disc / 7 + band * 1.6:.1f}" width="{width}" '
            f'height="{2 + band * 1.6:.1f}" fill="#000"/>'
            for band in range(3, 8)
        )
        defs += f'<mask id="bands"><rect width="{width}" height="{height}" fill="#fff"/>{bands}</mask>'
    defs += "</defs>"
    if style.startswith("empty"):
        rings = (1, 0.93) if style == "empty-double" else (1,)
        orb = "".join(
            f'<circle cx="{cx}" cy="{cy}" r="{disc * share:.1f}" fill="none" stroke="{fill}" '
            f'stroke-opacity="{min(1.0, opacity + 0.35):.2f}" stroke-width="{3 if share == 1 else 1.4}"/>'
            for share in rings
        )
    elif style == "rings":
        orb = "".join(
            f'<circle cx="{cx}" cy="{cy}" r="{disc * share:.1f}" fill="none" stroke="{fill}" '
            f'stroke-opacity="{opacity + 0.2:.2f}" stroke-width="{2.4 if share == 1 else 1.4}"/>'
            for share in (1, 0.8, 0.6, 0.4, 0.2)
        )
    else:
        mask = ' mask="url(#bands)"' if style == "striped" else ""
        orb = (
            f'<circle cx="{cx}" cy="{cy}" r="{disc}" fill="url(#sun)"{mask}/>'
            f'<circle cx="{cx}" cy="{cy}" r="{disc + 10}" fill="none" stroke="{fill}" '
            f'stroke-opacity="{opacity + 0.2:.2f}" stroke-width="1.6"/>'
        )
    leaf = (
        f'<path d="{" ".join(wedge_paths)}" fill="{fill}" fill-opacity="{wedges}"/>'
        if wedge_paths
        else ""
    )
    body = defs + leaf + (
        f'<g fill="none" stroke="{color}" stroke-opacity="{opacity}" '
        f'stroke-linecap="square">{"".join(parts)}</g>'
    ) + orb
    return svg(width, height, body, "xMidYMid slice" if full else "xMidYMax slice")


def chevrons(color: str, count: int = 9) -> str:
    """The head strip: a double chevron run with a lozenge between each pair."""
    unit, height = 16, 18
    parts = []
    for index in range(count):
        x = index * unit
        parts.append(f'<path d="M{x + 2},5 L{x + 8},11 L{x + 14},5" stroke-width="1.4"/>')
        parts.append(f'<path d="M{x + 2},9 L{x + 8},15 L{x + 14},9" stroke-width="0.9"/>')
        parts.append(f'<path d="M{x + 8},1.5 L{x + 9.6},3.2 L{x + 8},4.9 L{x + 6.4},3.2Z" stroke-width="0.8"/>')
    return svg(count * unit, height, f'<g fill="none" stroke="{color}">{"".join(parts)}</g>')


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
        parts.append(f'<path d="M{cx - 10},{cy} A10,10 0 0 1 {cx + 10},{cy}" stroke-width="1.3"/>')
    return svg(count * unit, height, f'<g fill="none" stroke="{color}">{"".join(parts)}</g>')


def steps_strip(color: str, count: int = 6) -> str:
    """The head strip: stepped towers, a skyline in miniature."""
    unit, height = 26, 18
    parts = []
    for index in range(count):
        x = index * unit
        parts.append(
            f'<path d="M{x + 1},17 V11 H{x + 5} V7 H{x + 9} V3 H{x + 13} V1 V3 H{x + 17} V7 H{x + 21} '
            f'V11 H{x + 25} V17" stroke-width="1.1"/>'
        )
        parts.append(f'<line x1="{x + 13}" y1="5" x2="{x + 13}" y2="17" stroke-width="0.7"/>')
    return svg(count * unit, height, f'<g fill="none" stroke="{color}">{"".join(parts)}</g>')


def rule_strip(color: str) -> str:
    """The head strip: a double rule ending in a lozenge."""
    body = (
        f'<g fill="none" stroke="{color}"><line x1="0" y1="7.5" x2="104" y2="7.5" stroke-width="1"/>'
        f'<line x1="0" y1="10.5" x2="104" y2="10.5" stroke-width="1"/>'
        f'<path d="M104,9 L109,4 L114,9 L109,14Z" stroke-width="1.1"/></g>'
    )
    return svg(116, 18, body)


def herringbone(color: str, opacity: float) -> str:
    """A lacquer field of nested chevrons, one tile."""
    parts = [
        f'<path d="M0,{y} L20,{y - 12} L40,{y}" stroke-width="{1.2 if y % 24 == 12 else 0.6}"/>'
        for y in (12, 24, 36)
    ]
    body = f'<g fill="none" stroke="{color}" stroke-opacity="{opacity}">{"".join(parts)}</g>'
    return svg(40, 24, body)


def skyline(color: str, opacity: float) -> str:
    """Fluted pilasters and stepped crowns along the bottom of the Stage."""
    width, height = 1600, 1000
    rng = random.Random("deco-skyline")
    parts = []
    for x in range(0, width, 18):
        parts.append(f'<line x1="{x}" y1="0" x2="{x}" y2="{height}" stroke-width="0.5"/>')
    x = 0
    while x < width:
        tower = rng.choice((90, 120, 150))
        top = height - rng.randint(260, 560)
        crown = []
        for step in range(4):
            inset = step * tower / 9
            crown.append(f"{x + inset:.1f},{top + step * 34 + 34} {x + inset:.1f},{top + step * 34}")
        parts.append(
            f'<path d="M{x},{height} V{top + 136} H{x + tower / 3:.1f} V{top} H{x + 2 * tower / 3:.1f} '
            f'V{top + 136} H{x + tower} V{height}" stroke-width="1.6"/>'
        )
        apex = x + tower / 2
        for arch in range(3):
            radius = tower / 6 + arch * 9
            parts.append(
                f'<path d="M{apex - radius:.1f},{top + 60 + arch * 22} A{radius:.1f},{radius:.1f} 0 0 1 '
                f'{apex + radius:.1f},{top + 60 + arch * 22}" stroke-width="1"/>'
            )
        x += tower + rng.randint(30, 80)
    body = f'<g fill="none" stroke="{color}" stroke-opacity="{opacity}">{"".join(parts)}</g>'
    return svg(width, height, body, "xMidYMax slice")


def lone_fan(color: str, opacity: float) -> str:
    """One small sunburst at the foot of the Stage — the single gesture of the sparse face."""
    return sunburst(color, opacity, 24, (70, 120))


def lozenge(color: str, size: int) -> str:
    half = size / 2
    body = (
        f'<path d="M0,0 L1.6,1.6 L0,3.2 L-1.6,1.6Z" transform="translate({half} {half - 1.6})" '
        f'fill="{color}"/>'
    )
    return svg(size, size, body)


# ---- Bellagio: blown glass — Persian discs, spiral horns, ruffled blossoms ------------------


def mix(color: str, other: str, share: float) -> str:
    left = [int(color[index : index + 2], 16) for index in (1, 3, 5)]
    right = [int(other[index : index + 2], 16) for index in (1, 3, 5)]
    return "#" + "".join(
        f"{round(a + (b - a) * share):02x}" for a, b in zip(left, right, strict=True)
    )


def polar(radius: float, angle: float) -> str:
    return f"{radius * math.cos(angle):.1f},{radius * math.sin(angle):.1f}"


def persian(rng: random.Random, color: int, lip: int) -> str:
    """A ruffled glass disc: a wavy rim, striations from the throat, a lip of another colour."""
    ruffles, phase = rng.randint(9, 14), rng.uniform(0, math.tau)
    rim = " ".join(
        polar(50 * (1 + 0.07 * math.sin(ruffles * step / 72 * math.tau + phase)), step / 72 * math.tau)
        for step in range(72)
    )
    inner = " ".join(
        polar(33 * (1 + 0.06 * math.sin(ruffles * step / 48 * math.tau + phase)), step / 48 * math.tau)
        for step in range(48)
    )
    striae = "".join(
        f'<line x1="{polar(9, angle).split(",")[0]}" y1="{polar(9, angle).split(",")[1]}" '
        f'x2="{polar(47, angle).split(",")[0]}" y2="{polar(47, angle).split(",")[1]}"/>'
        for angle in (index / ruffles * math.tau + phase for index in range(ruffles))
    )
    return (
        f'<polygon points="{rim}" fill="url(#g{color})" stroke="url(#g{lip})" stroke-width="3"/>'
        f'<polygon points="{inner}" fill="none" stroke="#ffffff" stroke-opacity="0.35" stroke-width="1.5"/>'
        f'<g stroke="#000000" stroke-opacity="0.18" stroke-width="1.2">{striae}</g>'
        f'<polygon points="{inner}" fill="none" stroke="url(#g{lip})" stroke-opacity="0.7" '
        'stroke-width="5" transform="scale(1.22)"/>'
        f'<circle r="8" fill="url(#g{lip})"/>'
        '<path d="M-30,-22 Q-12,-38 14,-36" fill="none" stroke="#ffffff" stroke-opacity="0.55" '
        'stroke-width="3" stroke-linecap="round"/>'
    )


def horn(rng: random.Random, color: int) -> str:
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
    del rng
    return (
        f'<polygon points="{" ".join(outer + inner[::-1])}" fill="url(#g{color})"/>'
        f'<polyline points="{" ".join(turns)}" fill="none" stroke="#ffffff" stroke-opacity="0.5" '
        'stroke-width="2.2" stroke-linecap="round"/>'
    )


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
            x, y = 38 + radius * math.sin(turn), sway * math.sin(math.pi * 1.2) - radius + radius * math.cos(turn)
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


def glass_kit(petals: tuple[str, ...], glow: bool, body: str, lucent: float = 0.0) -> str:
    """Gradients lit from within and one symbol per form and colour the body uses."""
    rng = random.Random("bellagio-kit")
    defs = []
    for index, color in enumerate(petals):
        defs.append(
            f'<radialGradient id="g{index}" cx="0.4" cy="0.35" r="0.75">'
            f'<stop offset="0" stop-color="{mix(color, "#ffffff", 0.35)}" stop-opacity="{1 - lucent * 0.5:.2f}"/>'
            f'<stop offset="0.5" stop-color="{color}" stop-opacity="{1 - lucent * 0.25:.2f}"/>'
            f'<stop offset="1" stop-color="{mix(color, "#000000", 0.45)}"/></radialGradient>'
        )
    count = len(petals)
    for index in range(count):
        lip = (index + 2) % count
        for kind, shape in (
            ("p", persian(rng, index, lip)),
            ("h", horn(rng, index)),
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
        # One light for the whole ceiling, high at the top-left: a specular sheen across each
        # piece's swell and a bright edge where the glass turns away — what reads as glass.
        defs.append(
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
    return "<defs>" + "".join(defs) + "</defs>"


def placements(rng: random.Random, count: int, width: float, height: float, scale: float,
               corner: bool = False, kinds: str = "phb", gloss: bool = False) -> list[str]:
    """Where the glass hangs: a jittered canopy, or a bouquet gathered into the bottom-right."""
    uses = []
    columns = max(1, round(math.sqrt(count * width / height)))
    rows = max(1, math.ceil(count / columns))
    for index in range(count):
        if corner:
            distance = rng.random() ** 0.7
            angle = rng.uniform(math.pi, 1.5 * math.pi)
            x = width + distance * width * math.cos(angle)
            y = height + distance * height * math.sin(angle)
            size = scale * rng.uniform(0.55, 1.0) * (1.25 - distance * 0.7)
        else:
            row, column = divmod(index, columns)
            x = (column + rng.uniform(0, 1)) * width / columns
            y = (row + rng.uniform(0, 1)) * height / rows
            size = scale * rng.uniform(0.6, 1.15)
        kind = rng.choices(kinds, weights=(6, 3, 1, 3)[: len(kinds)])[0]
        use = (
            f'<use href="#{kind}{rng.randrange(6)}" width="120" height="120" '
            f'transform="translate({x:.0f} {y:.0f}) rotate({rng.randrange(360)}) '
            f'scale({size / 100:.2f}) translate(-60 -60)"/>'
        )
        uses.append((size, f'<g filter="url(#gloss)">{use}</g>' if gloss else use))
    return [use for _, use in sorted(uses, key=lambda item: -item[0])]


def glass_field(seed: str, petals: tuple[str, ...], glow: bool, count: int, scale: float,
                width: int = 1600, height: int = 1000, corner: bool = False, alpha: float = 1.0,
                blend: str = "normal", shadow: bool = False, lucent: float = 0.0,
                kinds: str = "phb", gloss: bool = False) -> str:
    uses = "".join(
        placements(random.Random(seed), count, width, height, scale, corner, kinds, gloss)
    )
    halo = f'<g filter="url(#glow)" opacity="0.8">{uses}</g>' if glow else ""
    style = f' opacity="{alpha}" style="mix-blend-mode:{blend}"' if alpha < 1 or blend != "normal" else ""
    depth = ' filter="url(#shadow)"' if shadow else ""
    body = f"<g{style}{depth}>{uses}</g>"
    shade = (
        '<defs><filter id="shadow" x="-10%" y="-10%" width="130%" height="130%">'
        '<feDropShadow dx="5" dy="10" stdDeviation="7" flood-color="#3a2410" flood-opacity="0.35"/>'
        "</filter></defs>"
        if shadow
        else ""
    )
    aspect = "xMaxYMax meet" if corner else "xMidYMid slice"
    return svg(width, height, glass_kit(petals, glow, uses, lucent) + shade + halo + body, aspect)


def glass_strip(seed: str, petals: tuple[str, ...], kinds: str, count: int) -> str:
    """The head strip: small glass forms in a row."""
    rng = random.Random(seed)
    uses = "".join(
        f'<use href="#{kinds[index % len(kinds)]}{(index * 2 + 1) % 6}" width="120" height="120" '
        f'transform="translate({index * 20 + 10} 9) rotate({rng.randrange(360)}) scale(0.16) '
        'translate(-60 -60)"/>'
        for index in range(count)
    )
    return svg(count * 20, 18, glass_kit(petals, False, uses) + uses)


# ---- the candidates --------------------------------------------------------------------------

GOLD, INK, NICKEL, CHARCOAL = "#d6b04a", "#15120d", "#cfd3d8", "#2c3036"
PETALS_NIGHT = ("#ff4d5e", "#ffc93c", "#4d8dff", "#45d17a", "#b07cff", "#ff8a3d")
PETALS_DAY = ("#d62839", "#f2b705", "#1f5fbf", "#2e9e4f", "#7b3fa0", "#e8702a")


def face_css(theme: str, light: bool, values: dict[str, str]) -> str:
    lines = "".join(f"  --ornament-{name}: {value};\n" for name, value in values.items())
    block = f'html[data-theme="{theme}"] {{\n{lines}}}'
    if light:
        return "@media (prefers-color-scheme: light) {\n" + block.replace("\n", "\n  ") + "\n}"
    return block


def candidate(theme: str, dark: dict[str, str], light: dict[str, str], frame: str) -> str:
    """One theme: its two faces' ornaments, then the shared placement rules."""
    root = f'html[data-theme="{theme}"]'
    stage = f"{root} .stage-viewport:not(.stage-viewport--sheet)"
    return f"""{face_css(theme, False, dark)}

{face_css(theme, True, light)}

{root} .rack-shell {{
  background: var(--ornament-wash, var(--ground)) fixed;
}}

{stage} {{
  isolation: isolate;
}}

{stage}::before {{
  position: absolute;
  z-index: -1;
  inset: 0;
  background: var(--ornament-stage) var(--ornament-stage-place, center / cover no-repeat);
  content: "";
  opacity: var(--ornament-stage-opacity, 1);
  mask-image: var(--ornament-stage-mask, none);
  pointer-events: none;
}}

{root} .stage-canvas {{
  background-image:
    var(--ornament-grid, radial-gradient(circle at 1px 1px, var(--line-strong) 0 0.8px, transparent 1px)),
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


DOUBLE_RULE = """ROOT .rack-module {
  border-color: var(--accent);
  box-shadow: 0 0 0 2px var(--ground), 0 0 0 3px var(--accent);
}

ROOT .rack-module::before,
ROOT .rack-module::after {
  display: none;
}"""

SINGLE_RULE = """ROOT .rack-module {
  border-color: var(--accent);
  box-shadow: none;
}

ROOT .rack-module::before,
ROOT .rack-module::after {
  display: none;
}"""

LACQUER = """ROOT .rack-module {
  border-color: var(--accent-secondary);
  box-shadow: 0 0 0 1px var(--ground);
}

ROOT .rack-module__chrome {
  border-bottom: 3px double var(--accent);
  background: var(--surface-raised);
}

ROOT .rack-module::before,
ROOT .rack-module::after {
  display: none;
}"""

STEPPED_CORNERS = """ROOT .rack-module {
  border-color: var(--accent);
  box-shadow: none;
}

ROOT .rack-module::before {
  clip-path: polygon(0 0, 100% 0, 100% 100%, 75% 100%, 75% 75%, 50% 75%, 50% 50%, 25% 50%, 25% 25%, 0 25%);
  filter: drop-shadow(-1px 1px 0 var(--accent));
}

ROOT .rack-module::after {
  clip-path: polygon(0 0, 25% 0, 25% 25%, 50% 25%, 50% 50%, 75% 50%, 75% 75%, 100% 75%, 100% 100%, 0 100%);
  filter: drop-shadow(1px -1px 0 var(--accent));
}"""

GLASS_RIM = """ROOT .rack-module {
  border-color: transparent;
  box-shadow: none;
}

ROOT .rack-module::after {
  z-index: 5;
  inset: 0;
  width: auto;
  height: auto;
  padding: 2px;
  background: var(--ornament-rim);
  clip-path: none;
  filter: none;
  mask: linear-gradient(currentColor 0 0) content-box exclude, linear-gradient(currentColor 0 0);
}

ROOT .rack-module::before {
  display: none;
}"""

SILVER_GOLD = """ROOT .rack-module {
  border-color: var(--accent);
  box-shadow: 0 0 0 2px var(--ground), 0 0 0 3px var(--accent-secondary);
}

ROOT .rack-module::before,
ROOT .rack-module::after {
  display: none;
}"""

FULL_DECO = DOUBLE_RULE + """

ROOT .rack-module__chrome {
  background-image: var(--ornament-band);
  background-position: left bottom;
  background-repeat: repeat-x;
  background-size: 0.75rem 0.4rem;
}"""

HEADER_BAND = """

ROOT .rack-stage-header::after {
  position: absolute;
  right: 0;
  bottom: 0;
  left: 0;
  height: 4px;
  background: var(--ornament-band) left bottom / 9rem 4px repeat-x;
  content: "";
  pointer-events: none;
}"""

GLASS_HEADERS = """ROOT .rack-module {
  border-color: var(--line-strong);
  box-shadow: none;
}

ROOT .rack-module__chrome {
  border-bottom: 0;
  box-shadow: inset 0 -3px 0 0 transparent;
  background-image: var(--ornament-band);
  background-position: left bottom;
  background-repeat: repeat-x;
  background-size: 6rem 3px;
}

ROOT .rack-module::before,
ROOT .rack-module::after {
  display: none;
}"""


def deco(name: str, accent_night: str, accent_day: str, stage_night: str, stage_day: str,
         strip, frame: str, extra_night: dict[str, str] | None = None,
         extra_day: dict[str, str] | None = None) -> str:
    night = {
        "stage": uri(stage_night),
        "strip": uri(strip(accent_night)),
        "grid": uri(lozenge(accent_night, 16)),
        **(extra_night or {}),
    }
    day = {
        "stage": uri(stage_day),
        "strip": uri(strip(accent_day)),
        "grid": uri(lozenge(accent_day, 16)),
        **(extra_day or {}),
    }
    return candidate(name, night, day, frame)


def glass(name: str, stage_night: str, stage_day: str, strip_night: str, strip_day: str,
          frame: str, extra_night: dict[str, str] | None = None,
          extra_day: dict[str, str] | None = None) -> str:
    night = {
        "stage": uri(stage_night),
        "strip": uri(strip_night),
        **(extra_night or {}),
    }
    day = {
        "stage": uri(stage_day),
        "strip": uri(strip_day),
        **(extra_day or {}),
    }
    return candidate(name, night, day, frame)


def rim(petals: tuple[str, ...]) -> str:
    stops = ", ".join(f"{color} {round(index * 100 / (len(petals) - 1))}%" for index, color in enumerate(petals))
    return f"linear-gradient(135deg, {stops}) fixed"


def band(petals: tuple[str, ...]) -> str:
    """Glass beads under a head: one segment per petal colour."""
    share = 100 / len(petals)
    stops = ", ".join(
        f"{color} {index * share:.2f}% {(index + 1) * share - 2:.2f}%, transparent 0 {(index + 1) * share:.2f}%"
        for index, color in enumerate(petals)
    )
    return f"linear-gradient(90deg, {stops})"


def zigzag(color: str) -> str:
    """A band of small chevrons for the foot of a module head."""
    return svg(12, 6.4, f'<path d="M0,5.4 L3,1 L6,5.4 L9,1 L12,5.4" fill="none" stroke="{color}" stroke-width="1.1"/>')


LEAF_NIGHT = (
    "linear-gradient(135deg, #7a5a14 0%, #f3d98a 18%, #b8902e 34%, #fff2c2 50%, #a37b22 68%, "
    "#e6c66a 84%, #7a5a14 100%) fixed"
)
LEAF_DAY = (
    "linear-gradient(135deg, #5e4510 0%, #c9a24a 18%, #7e5f14 34%, #e2c06a 50%, #6b4f12 68%, "
    "#b8902e 84%, #5e4510 100%) fixed"
)
SILVER = "#cfd3d8"
PETALS_JEWEL_NIGHT = ("#ff5468", "#ffb43a", "#6f97ff", "#3ccf86", "#c08cff", "#ff8a4a")
PETALS_JEWEL_DAY = ("#a3122e", "#c98a00", "#143c9c", "#0f6a3a", "#5a2384", "#b8470f")


def render() -> str:
    leaf_bands = GLASS_RIM + FULL_DECO.split("}", 2)[2]
    blocks = [
        "/* Generated by web/scripts/build_ornament_motifs.py; do not edit. */",
        "/* M3GT / SD-078: audition round 4 — Deco's empty disc; Bellagio's glass, lit. */",
        # E1 — gold leaf around an empty disc: S1's leafed rims and filled rays, the sun hollow.
        deco(
            "art-deco-e1", GOLD, INK,
            deco_sun(GOLD, 0.4, 64, 170, "empty", wedges=0.07),
            deco_sun(INK, 0.24, 64, 170, "empty", metal="#8a6a1c", wedges=0.06),
            chevrons, GLASS_RIM,
            {"rim": LEAF_NIGHT}, {"rim": LEAF_DAY},
        ),
        # E2 — full deco around a double empty disc: double rules, chevron bands, two rings.
        deco(
            "art-deco-e2", GOLD, INK,
            deco_sun(GOLD, 0.45, 96, 180, "empty-double", wedges=0.04),
            deco_sun(INK, 0.28, 96, 180, "empty-double", wedges=0.03),
            fans, FULL_DECO,
            {"band": uri(zigzag(GOLD))}, {"band": uri(zigzag(INK))},
        ),
        # E3 — A1 and A4 together: leafed rims, chevron bands, an empty disc in stepped rings.
        deco(
            "art-deco-e3", GOLD, INK,
            deco_sun(GOLD, 0.42, 72, 190, "empty", wedges=0.05),
            deco_sun(INK, 0.26, 72, 190, "empty", metal="#8a6a1c", wedges=0.04),
            chevrons, leaf_bands,
            {"rim": LEAF_NIGHT, "band": uri(zigzag(GOLD))},
            {"rim": LEAF_DAY, "band": uri(zigzag(INK))},
        ),
        # E4 — the great ring: a large empty disc rising above the lower modules, long rays.
        deco(
            "art-deco-e4", GOLD, INK,
            deco_sun(GOLD, 0.38, 48, 320, "empty-double", wedges=0.06, steps=False),
            deco_sun(INK, 0.24, 48, 320, "empty-double", metal="#8a6a1c", wedges=0.05, steps=False),
            fans, GLASS_RIM,
            {"rim": LEAF_NIGHT}, {"rim": LEAF_DAY},
        ),
        # L1 — the lit canopy: every piece shaded by one light, the whole Stage a ceiling of glass.
        glass(
            "bellagio-l1",
            glass_field("canopy-l1", PETALS_JEWEL_NIGHT, True, 120, 190, lucent=0.25,
                        kinds="phbt", gloss=True),
            glass_field("canopy-l1", PETALS_JEWEL_DAY, False, 120, 190, blend="multiply",
                        lucent=0.25, kinds="phbt", gloss=True),
            glass_strip("strip-l1", PETALS_JEWEL_NIGHT, "p", 6),
            glass_strip("strip-l1", PETALS_JEWEL_DAY, "p", 6),
            SINGLE_RULE,
        ),
        # L2 — the big pieces: fewer, larger forms, so the glass itself is what you see.
        glass(
            "bellagio-l2",
            glass_field("canopy-l2", PETALS_JEWEL_NIGHT, True, 34, 340, lucent=0.25,
                        kinds="phbt", gloss=True),
            glass_field("canopy-l2", PETALS_JEWEL_DAY, False, 34, 340, blend="multiply",
                        lucent=0.25, kinds="phbt", gloss=True),
            glass_strip("strip-l2", PETALS_JEWEL_NIGHT, "ph", 6),
            glass_strip("strip-l2", PETALS_JEWEL_DAY, "ph", 6),
            SINGLE_RULE,
        ),
        # L3 — the bouquet: one lit gathering in the corner, glass-edged frames.
        glass(
            "bellagio-l3",
            glass_field("bouquet-l3", PETALS_JEWEL_NIGHT, True, 70, 250, 900, 640, corner=True,
                        lucent=0.25, kinds="phbt", gloss=True),
            glass_field("bouquet-l3", PETALS_JEWEL_DAY, False, 70, 250, 900, 640, corner=True,
                        blend="multiply", lucent=0.25, kinds="phbt", gloss=True),
            glass_strip("strip-l3", PETALS_JEWEL_NIGHT, "pb", 6),
            glass_strip("strip-l3", PETALS_JEWEL_DAY, "pb", 6),
            GLASS_RIM,
            {"rim": rim(PETALS_JEWEL_NIGHT), "stage-place": "right bottom / 60rem auto no-repeat"},
            {"rim": rim(PETALS_JEWEL_DAY), "stage-place": "right bottom / 60rem auto no-repeat"},
        ),
        # L4 — the night garden: the lit glass glowing hard on black, glass-edged frames.
        glass(
            "bellagio-l4",
            glass_field("canopy-l4", PETALS_JEWEL_NIGHT, True, 100, 210, lucent=0.15,
                        kinds="phbt", gloss=True),
            glass_field("canopy-l4", PETALS_JEWEL_DAY, True, 100, 210, blend="multiply",
                        lucent=0.3, kinds="phbt", gloss=True),
            glass_strip("strip-l4", PETALS_JEWEL_NIGHT, "h", 6),
            glass_strip("strip-l4", PETALS_JEWEL_DAY, "h", 6),
            GLASS_RIM,
            {"rim": rim(PETALS_JEWEL_NIGHT)}, {"rim": rim(PETALS_JEWEL_DAY)},
        ),
    ]
    return "\n\n".join(blocks) + "\n"


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
