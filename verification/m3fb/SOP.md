# M3FB real-browser phone recovery SOP

Date: 2026-08-21

Viewport: 390 x 844

Surface: ordinary local owner app at `http://127.0.0.1:8876/` (not a regression fixture)

Browser: Chrome through the in-app Browser control

## Recipe

1. I selected the Graph layer, opened Stage Library, and added Recipe through its ordinary owner control.
2. I closed Stage Library. Recipe was outside the phone viewport and the visible Off-screen rail offered `Recipe` as the recovery action.
3. I captured [01-recipe-before-390x844.jpg](01-recipe-before-390x844.jpg).
4. I clicked `Recipe` once in the Off-screen rail.
5. I captured [02-recipe-after-390x844.jpg](02-recipe-after-390x844.jpg).
6. I measured the settled browser geometry: Stage viewport `(0, 92) -> (390, 844)`; Recipe `(27, 108) -> (363, 828)`, `336 x 720`, persisted grid `7 x 20`, camera `100%`.
7. I confirmed Recipe disappeared from the Off-screen rail, the document and body remained 390 pixels wide, and the Stage's native scroll remained `(0, 0)`.
8. I opened and closed `Recipe settings` after recovery. The dialog appeared, proving the recovered module chrome remained operable.

## The Deck

1. I used App settings `Reset` to restore the factory Stage, then reloaded the built owner app.
2. The Deck was outside the initial Work camera and the visible Off-screen rail offered `The Deck`.
3. I captured [03-deck-before-390x844.jpg](03-deck-before-390x844.jpg).
4. I clicked `The Deck` once in the Off-screen rail.
5. I captured [04-deck-after-390x844.jpg](04-deck-after-390x844.jpg).
6. I measured the settled browser geometry: Stage viewport `(0, 92) -> (390, 844)`; The Deck `(27, 108) -> (363, 828)`, `336 x 720`, persisted grid `7 x 20`, camera `100%`.
7. I confirmed The Deck disappeared from the Off-screen rail, the document and body remained 390 pixels wide, and the Stage's native scroll remained `(0, 0)`.
8. I opened and closed `The Deck settings` after recovery. The dialog appeared, proving the recovered module chrome remained operable.

## Unscripted exploration

On the first Deck pass, the camera math reported the module as fitting but the rendered frame began at `x = -1`. I inspected the live Stage rather than accepting that screenshot. Browser focus had moved the `overflow: hidden` Stage viewport to native scroll `(28, 13)`, silently offsetting the explicit camera transform. I added a Stage invariant that returns native scroll to `(0, 0)`, rebuilt, reset through the owner settings, and repeated both flows. The final measurements and screenshots above are from those clean reruns. I also exercised each recovered module's settings control and observed no horizontal page overflow.

## Result

PASS. One visible recovery action returns both Recipe and The Deck fully inside the 390 x 844 Stage at readable native scale. Both remain usable, persist their recovered geometry, and do not create page overflow.
