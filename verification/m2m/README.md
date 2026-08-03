# M2M broker reconciliation evidence

The production rack was exercised through the visibly bannered deterministic fixture described in [SOP.md](SOP.md), at 1440 x 900 on isolated port 8779.

- [01-drift-expanded-desktop-1440x900.png](01-drift-expanded-desktop-1440x900.png) shows the signed Palace-wide drift as one compact line above the existing gauges.
- [02-drift-collapsed-desktop-1440x900.png](02-drift-collapsed-desktop-1440x900.png) shows the same line remaining visible in the one-row collapsed resident without covering Chat.

DOM and computed-style inspection found exactly one `.vitals-reconciliation--drift` in the Vitals frame with text `Ledger drift · +$0.050000000000`, color `rgb(255, 64, 95)` (`--danger`), no alert role, and zero `[role="alert"]` elements. The fixture is product-rendering evidence only; the broker client and cumulative-baseline behavior are proven by Spine integration tests and no live OpenRouter request was made for the screenshot.
