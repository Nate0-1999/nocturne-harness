#!/usr/bin/env python3
"""Build the M2UX6 grimoire motif layer from the frozen Sigil Forge.

The audition kit proves the visual vocabulary. This generator maps that
vocabulary onto the real Rack without importing its demo-only SPA shell or
letting decoration compete with owner data.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from urllib.parse import quote, unquote

from sigil_forge import elvish_strip, strip_svg

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "src" / "themes" / "grimoire.generated.css"

AMBER = "#d9a45c"
PARCHMENT = "#9a8768"
PHOSPHOR = "#4be08a"
ULTRAVIOLET = "#b46cf0"

# SD-080: two layers of eight falling columns each — the glyph count is capped by the columns.
RAIN_COLUMNS = (
    ((2, 0.0), (15, 0.55), (28, 0.2), (41, 0.75), (54, 0.4), (67, 0.9), (80, 0.15), (93, 0.6)),
    ((8, 0.3), (21, 0.85), (34, 0.1), (47, 0.65), (60, 0.45), (73, 0.05), (86, 0.7), (99, 0.35)),
)
RAIN_SPEEDS = (2.0, 1.4)  # rem per second, the near layer faster


def rain_tile(strip: str) -> tuple[str, float]:
    """One falling column: the strip brightens toward its head, then falls silent."""
    match = re.search(r'width="(\d+)" height="(\d+)"', unquote(strip))
    assert match is not None
    width, height = (int(value) for value in match.groups())
    tile = round(height * 1.5)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{tile}" '
        f'viewBox="0 0 {width} {tile}"><defs><linearGradient id="t" x2="0" y2="1">'
        '<stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset="1" stop-color="#fff"/>'
        f'</linearGradient><mask id="m"><rect width="{width}" height="{height}" fill="url(#t)"/>'
        f'</mask></defs><image href="{strip}" width="{width}" height="{height}" '
        'mask="url(#m)"/></svg>'
    )
    return "data:image/svg+xml," + quote(svg, safe=""), tile / width


def stage_rain(theme: str, tiles: tuple[tuple[str, float], tuple[str, float]]) -> str:
    """The scripts run down the Stage behind the modules, never over a data surface."""
    viewport = ".stage-viewport:not(.stage-viewport--sheet)"
    stage = f'html[data-theme="{theme}"] {viewport}'
    blocks = [
        f'html[data-theme="{theme}"] {{\n'
        + "".join(
            f'  --grimoire-stage-rain-{layer}: url("{uri}");\n'
            for layer, (uri, _) in zip(("one", "two"), tiles, strict=True)
        )
        + "}",
        f"{stage} {{\n  isolation: isolate;\n}}",
    ]
    for (_, ratio), columns, speed, pseudo, layer in zip(
        tiles, RAIN_COLUMNS, RAIN_SPEEDS, ("::before", "::after"), ("one", "two"), strict=True
    ):
        height = round(ratio * 1.2, 4)  # the tile drawn 1.2rem wide
        images = ", ".join(f"var(--grimoire-stage-rain-{layer})" for _ in columns)
        positions = ", ".join(f"{x}% {round(offset * height, 3)}rem" for x, offset in columns)
        name = f"grimoire-stage-rain-{theme}-{pseudo[2:]}"
        blocks.append(
            f"""{stage}{pseudo} {{
  position: absolute;
  z-index: -1;
  top: -{height}rem;
  right: 0;
  bottom: 0;
  left: 0;
  background-image: {images};
  background-position: {positions};
  background-repeat: repeat-y;
  background-size: 1.2rem {height}rem;
  content: "";
  opacity: 0.5;
  pointer-events: none;
  animation: {name} {round(height / speed, 2)}s linear infinite;
}}

html[data-page-hidden][data-theme="{theme}"] {viewport}{pseudo} {{
  animation-play-state: paused;
}}

@keyframes {name} {{
  to {{ transform: translateY({height}rem); }}
}}"""
        )
    return "\n\n".join(blocks)


def render() -> str:
    """Render the frozen kit's strips as Rack-safe decorative CSS."""
    rain = {
        "wizard-mode": (
            rain_tile(elvish_strip(9, AMBER, "wiz-rain1", vertical=True)),
            rain_tile(elvish_strip(7, PARCHMENT, "wiz-rain2", vertical=True)),
        ),
        "technomancer": (
            rain_tile(strip_svg(12, PHOSPHOR, "tec-rain1", vertical=True)),
            rain_tile(strip_svg(10, ULTRAVIOLET, "tec-rain2", vertical=True)),
        ),
    }
    strips = {
        "wizard_head": elvish_strip(16, AMBER, "wiz-head"),
        "wizard_margin": elvish_strip(6, PARCHMENT, "wiz-margin", vertical=True),
        "wizard_breathe": elvish_strip(20, AMBER, "wiz-breath"),
        "wizard_column": elvish_strip(8, PARCHMENT, "wiz-col", vertical=True),
        "wizard_one": elvish_strip(1, AMBER, "wiz-one"),
        "wizard_composer": elvish_strip(8, AMBER, "wiz-comp"),
        "wizard_topbar": elvish_strip(3, PARCHMENT, "wiz-top"),
        "tech_head": strip_svg(13, PHOSPHOR, "tec-head"),
        "tech_hexline": strip_svg(11, PHOSPHOR, "tec-hex"),
        "tech_rain_one": strip_svg(12, PHOSPHOR, "tec-rain1", vertical=True),
        "tech_rain_two": strip_svg(10, ULTRAVIOLET, "tec-rain2", vertical=True),
        "tech_composer": strip_svg(7, PHOSPHOR, "tec-comp"),
        "tech_topbar": strip_svg(3, ULTRAVIOLET, "tec-top"),
    }
    variables = "\n".join(
        f'  --grimoire-{name.replace("_", "-")}: url("{uri}");' for name, uri in strips.items()
    )
    return f"""/* Generated by web/scripts/build_grimoire_motifs.py; do not edit. */
/* M2UX6 / B.6 rule 7 / B.6 rule 12 / D.2 115-120. */

html[data-theme="wizard-mode"],
html[data-theme="technomancer"] {{
{variables}
}}

/* State-change conjurations are finite: mount, hover, focus, and message arrival. */
/* The head strip follows the module name and yields first: the name reads whole (SD-078). */
html[data-theme="wizard-mode"] .rack-module__drag::after,
html[data-theme="technomancer"] .rack-module__drag::after {{
  order: 1;
  flex: 0 1000000 auto;
  min-width: 0;
  width: 7.5rem;
  height: 1.15rem;
  content: "";
  pointer-events: none;
}}

html[data-theme="wizard-mode"] .rack-module__drag > .rack-module__attunement,
html[data-theme="technomancer"] .rack-module__drag > .rack-module__attunement {{
  order: 2;
}}

html[data-theme="wizard-mode"] .rack-module__drag::after {{
  background: var(--grimoire-wizard-head) left center / auto 100% repeat-x;
  animation: grimoire-rune-inscribe 1.35s ease-out both;
}}

html[data-theme="technomancer"] .rack-module__drag::after {{
  background: var(--grimoire-tech-head) left center / auto 100% repeat-x;
  filter: drop-shadow(0 0 4px {PHOSPHOR});
  animation: grimoire-glitch-in 950ms steps(12) both;
}}

html[data-theme="wizard-mode"] .rack-module__content::after {{
  position: absolute;
  z-index: 2;
  top: 0.4rem;
  right: 0.24rem;
  width: 0.78rem;
  height: 7.5rem;
  background: var(--grimoire-wizard-margin) top center / 100% auto repeat-y;
  content: "";
  opacity: 0;
  pointer-events: none;
}}

html[data-theme="wizard-mode"] .rack-module:hover .rack-module__content::after,
html[data-theme="wizard-mode"] .rack-module:focus-within .rack-module__content::after {{
  animation: grimoire-margin-reveal 900ms ease-out both;
}}

html[data-theme="technomancer"] .rack-module__content::before {{
  position: absolute;
  z-index: 2;
  right: 0.6rem;
  bottom: 0.12rem;
  left: 0.6rem;
  height: 0.55rem;
  background: var(--grimoire-tech-hexline) left center / auto 100% repeat-x;
  content: "";
  opacity: 0;
  pointer-events: none;
  animation: grimoire-hexline-arrive 1.1s ease-out 300ms both;
}}

html[data-theme="wizard-mode"] .message__label,
html[data-theme="technomancer"] .message__label {{
  position: relative;
}}

html[data-theme="wizard-mode"] .message__label::after {{
  width: 0.8rem;
  height: 1.15rem;
  margin-top: 0.2rem;
  background: var(--grimoire-wizard-one) center / contain no-repeat;
  content: "";
  opacity: 0;
  pointer-events: none;
  animation: grimoire-message-mark 800ms ease-out 250ms both;
}}

html[data-theme="wizard-mode"] .composer,
html[data-theme="technomancer"] .composer,
html[data-theme="wizard-mode"] .topbar,
html[data-theme="technomancer"] .topbar {{
  position: relative;
}}

html[data-theme="wizard-mode"] .composer::before,
html[data-theme="technomancer"] .composer::before {{
  position: absolute;
  top: -1.25rem;
  width: 7.5rem;
  height: 1rem;
  content: "";
  opacity: 0;
  pointer-events: none;
}}

html[data-theme="wizard-mode"] .composer::before {{
  left: 0.8rem;
  background: var(--grimoire-wizard-composer) left center / auto 100% repeat-x;
}}

html[data-theme="technomancer"] .composer::before {{
  right: 0.9rem;
  background: var(--grimoire-tech-composer) left center / auto 100% repeat-x;
  filter: drop-shadow(0 0 4px {PHOSPHOR});
}}

html[data-theme="wizard-mode"] .composer:focus-within::before {{
  animation: grimoire-rune-focus 850ms ease-out both;
}}

html[data-theme="technomancer"] .composer:focus-within::before {{
  animation: grimoire-glitch-focus 720ms steps(8) both;
}}

html[data-theme="wizard-mode"] .topbar::after,
html[data-theme="technomancer"] .topbar::after {{
  position: absolute;
  top: 50%;
  right: 12rem;
  width: 3.4rem;
  height: 1rem;
  background-position: center;
  background-repeat: no-repeat;
  background-size: contain;
  content: "";
  opacity: 0;
  pointer-events: none;
  transform: translateY(-50%);
}}

html[data-theme="wizard-mode"] .topbar::after {{
  background-image: var(--grimoire-wizard-topbar);
  animation: grimoire-topbar-arrive 1s ease-out 450ms both;
}}

html[data-theme="technomancer"] .topbar::after {{
  background-image: var(--grimoire-tech-topbar);
  filter: drop-shadow(0 0 5px {ULTRAVIOLET});
  animation: grimoire-topbar-arrive 1s steps(8) 450ms both;
}}

/* Ambient loops are restricted to the empty transcript or non-data Rack background. */
html[data-theme="wizard-mode"] .transcript__inner:has(.thread-empty),
html[data-theme="technomancer"] .transcript__inner:has(.thread-empty) {{
  position: relative;
  overflow: hidden;
}}

html[data-theme="wizard-mode"] .transcript__inner:has(.thread-empty)::after,
html[data-theme="wizard-mode"] .transcript__inner:has(.thread-empty)::before,
html[data-theme="technomancer"] .transcript__inner:has(.thread-empty)::after,
html[data-theme="technomancer"] .transcript__inner:has(.thread-empty)::before {{
  position: absolute;
  content: "";
  opacity: 0;
  pointer-events: none;
}}

html[data-theme="wizard-mode"] .transcript__inner:has(.thread-empty)::after {{
  right: 1.5rem;
  bottom: 0.6rem;
  left: 1.5rem;
  height: 1.5rem;
  background: var(--grimoire-wizard-breathe) left center / auto 100% repeat-x;
  animation: grimoire-breathe-x 11s ease-in-out infinite;
}}

html[data-theme="wizard-mode"] .transcript__inner:has(.thread-empty)::before {{
  top: 30%;
  right: 1.6rem;
  width: 0.95rem;
  height: 9rem;
  background: var(--grimoire-wizard-column) top center / 100% auto repeat-y;
  animation: grimoire-breathe-y 13s ease-in-out 4s infinite;
}}

html[data-theme="technomancer"] .transcript__inner:has(.thread-empty)::after {{
  top: -1rem;
  right: 2rem;
  width: 1rem;
  height: 14rem;
  background: var(--grimoire-tech-rain-one) top center / 100% auto repeat-y;
  filter: drop-shadow(0 0 5px {PHOSPHOR});
  animation: grimoire-glyph-rain 8s linear infinite;
}}

html[data-theme="technomancer"] .transcript__inner:has(.thread-empty)::before {{
  top: -1rem;
  left: 34%;
  width: 0.95rem;
  height: 12rem;
  background: var(--grimoire-tech-rain-two) top center / 100% auto repeat-y;
  filter: drop-shadow(0 0 5px {ULTRAVIOLET});
  animation: grimoire-glyph-rain 11s linear 3.5s infinite;
}}

html[data-theme="technomancer"] .rack-ambient::after {{
  position: absolute;
  inset: 0;
  background: repeating-linear-gradient(
    to bottom,
    rgba(140, 255, 190, 0.045) 0 1px,
    transparent 1px 4px
  );
  content: "";
  opacity: 0.45;
  pointer-events: none;
  animation: grimoire-scan 9s linear infinite;
}}

{stage_rain("wizard-mode", rain["wizard-mode"])}

{stage_rain("technomancer", rain["technomancer"])}

@keyframes grimoire-rune-inscribe {{
  from {{ width: 0; opacity: 0; }}
  35% {{ opacity: 0.95; }}
  to {{ width: 7.5rem; opacity: 0.55; }}
}}

@keyframes grimoire-glitch-in {{
  from {{ opacity: 0; clip-path: inset(0 100% 0 0); }}
  35% {{ opacity: 0.9; clip-path: inset(0 34% 0 0); }}
  48% {{ opacity: 0.25; }}
  to {{ opacity: 0.6; clip-path: inset(0); }}
}}

@keyframes grimoire-margin-reveal {{
  from {{ opacity: 0; transform: translateX(0.35rem); }}
  to {{ opacity: 0.65; transform: translateX(0); }}
}}

@keyframes grimoire-hexline-arrive {{
  from {{ opacity: 0; clip-path: inset(0 100% 0 0); }}
  to {{ opacity: 0.32; clip-path: inset(0); }}
}}

@keyframes grimoire-message-mark {{
  from {{ opacity: 0; transform: translateY(0.25rem); }}
  to {{ opacity: 0.52; transform: translateY(0); }}
}}

@keyframes grimoire-rune-focus {{
  from {{ opacity: 0; clip-path: inset(0 100% 0 0); }}
  to {{ opacity: 0.68; clip-path: inset(0); }}
}}

@keyframes grimoire-glitch-focus {{
  from {{ opacity: 0; clip-path: inset(0 100% 0 0); }}
  58% {{ opacity: 0.8; clip-path: inset(0 20% 0 0); }}
  to {{ opacity: 0.62; clip-path: inset(0); }}
}}

@keyframes grimoire-topbar-arrive {{
  from {{ opacity: 0; transform: translateY(-50%) translateX(0.5rem); }}
  to {{ opacity: 0.48; transform: translateY(-50%) translateX(0); }}
}}

@keyframes grimoire-breathe-x {{
  0%, 100% {{ opacity: 0; transform: translateY(4px); }}
  50% {{ opacity: 0.42; transform: translateY(0); }}
}}

@keyframes grimoire-breathe-y {{
  0%, 100% {{ opacity: 0; transform: translateX(3px); }}
  50% {{ opacity: 0.36; transform: translateX(0); }}
}}

@keyframes grimoire-glyph-rain {{
  0% {{ opacity: 0; transform: translateY(-12%); }}
  12%, 80% {{ opacity: 0.32; }}
  100% {{ opacity: 0; transform: translateY(55%); }}
}}

@keyframes grimoire-scan {{
  from {{ transform: translateY(0); }}
  to {{ transform: translateY(4px); }}
}}

@media (prefers-reduced-motion: reduce) {{
  html[data-theme="wizard-mode"] .rack-module__drag::after,
  html[data-theme="technomancer"] .rack-module__drag::after,
  html[data-theme="wizard-mode"] .rack-module__content::after,
  html[data-theme="technomancer"] .rack-module__content::before,
  html[data-theme="wizard-mode"] .message__label::after,
  html[data-theme="wizard-mode"] .composer::before,
  html[data-theme="technomancer"] .composer::before,
  html[data-theme="wizard-mode"] .topbar::after,
  html[data-theme="technomancer"] .topbar::after,
  html[data-theme="wizard-mode"] .transcript__inner:has(.thread-empty)::after,
  html[data-theme="wizard-mode"] .transcript__inner:has(.thread-empty)::before,
  html[data-theme="technomancer"] .transcript__inner:has(.thread-empty)::after,
  html[data-theme="technomancer"] .transcript__inner:has(.thread-empty)::before,
  html[data-theme="technomancer"] .rack-ambient::after,
  html[data-theme="wizard-mode"] .stage-viewport::before,
  html[data-theme="wizard-mode"] .stage-viewport::after,
  html[data-theme="technomancer"] .stage-viewport::before,
  html[data-theme="technomancer"] .stage-viewport::after {{
    animation: none !important;
  }}

  html[data-theme="wizard-mode"] .rack-module__drag::after,
  html[data-theme="technomancer"] .rack-module__drag::after {{
    width: 7.5rem;
    opacity: 0.42;
    clip-path: none;
  }}

  html[data-theme="wizard-mode"] .rack-module__content::after,
  html[data-theme="technomancer"] .rack-module__content::before,
  html[data-theme="wizard-mode"] .message__label::after,
  html[data-theme="wizard-mode"] .topbar::after,
  html[data-theme="technomancer"] .topbar::after {{
    opacity: 0.24;
    clip-path: none;
  }}

  html[data-theme="wizard-mode"] .transcript__inner:has(.thread-empty)::after,
  html[data-theme="wizard-mode"] .transcript__inner:has(.thread-empty)::before,
  html[data-theme="technomancer"] .transcript__inner:has(.thread-empty)::after,
  html[data-theme="technomancer"] .transcript__inner:has(.thread-empty)::before {{
    opacity: 0.14;
    transform: none;
  }}
}}
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = render()
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text() != expected:
            print(f"stale generated grimoire CSS: {OUTPUT}")
            return 1
        print(f"grimoire CSS is current: {OUTPUT}")
        return 0
    OUTPUT.write_text(expected)
    print(f"wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
