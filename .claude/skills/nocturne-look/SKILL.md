---
name: nocturne-look
description: How Nocturne's surfaces must look and read. Load before changing any web module's presentation — buttons, labels, tips, spacing, themes. The owner's rules, distilled from the garden's design rulings (D.2 107-119). Not for behavior changes.
---

# The Nocturne look

You are polishing surfaces, not fixing features. Same handlers, same
meaning, same test ids. If something is broken, write one flag and move on.

## The owner's words (these are the law)

- "get rid of slop like phrases that don't need to be there"
- "buttons right sized and chamfered corners and have hovertips"
- "make the surfaces look better, more cohesive, display more information more cleanly"
- "chrome for the borders not buttons" (the rim law)
- "the chrome needs to be liquid and shiny and white" (the shine floor)
- neo-noir stays the default; every theme keeps working (the three-theme ruling)

## Procedure, module by module

1. Open the running app. Capture the module before you touch it.
2. WORDS. Delete the sub-header sentence that narrates the module, the
   instruction a tip can carry, the status line that repeats the header.
   A label is one or two words in mono caps. Numbers are human
   (1.2K, $0.004, 3 min ago). Nothing explains itself twice.
3. CONTROLS. One button style, three sizes (row, module, primary).
   Chamfered corners: `clip-path: polygon(...)` cutting 6px off two
   opposite corners, never `border-radius`. Dark body, one-pixel rim
   from the seam tokens, text in the theme's ink. Quiet buttons have the
   rim only; the primary has the accent rim and a brighter ink; danger
   uses the theme's one danger color. Selects and toggles wear the same
   rim and height as the row button. No third-party component kits.
4. TIPS. Every control gets a short descriptive `title` (or the existing
   ControlTooltip): what it does in five words, then the shortcut if one
   exists. Never restate the label.
5. COHESION. Every module: the same header height, the same padding
   scale (4 / 8 / 12 / 20), the same border, the same six type sizes.
   Reuse the tokens in `web/src/themes/materials.css` and the `--seam-*`
   colors; do not invent a color. If a module has its own stylesheet,
   remove what the shared rules now cover.
6. DENSITY. The room the deleted words free shows more real data: one
   more column, the count beside the label, the state as a chip.
7. THEMES. Switch through every theme and look. A rule that only works
   in one theme is wrong.
8. Capture the module after, same framing. Commit: one module per commit.

## Never

- Chrome as a fill (headers, chips, buttons). Chrome is an edge material.
- Decoration on a data surface (the pure-render law). Motion belongs to
  the grimoire themes' glyphs, off data.
- A new color, font, or icon set. Everything comes from the theme tokens.
- Rounded corners. Chamfers.
- A change inside the composer function or inside the 3D scenes; peers
  hold unmerged work there. Style around them.
- A behavior change of any kind.

## Done looks like

Every module's before/after pair in the evidence folder, one full-app
capture per theme, the suites and the rendered UI canon green.
