# M2C — Palace Vitals + spend strip

Status: **builder verification complete**. This directory is packet evidence,
not an independent milestone judgment.

M2C adds one compiled first-party Vitals resident to the M2 rack. Its iframe is
sealed by the same `rack.localhost` sandbox and CSP as every other factory
resident. It receives no Spine URL, bearer, WebSocket, or private adapter: the
frame asks ADR-023's public `query` surface for `resource=vitals`, and the host
performs the credentialed read. Lane focus and the scrub minute cross the same
public selection surface.

The strip renders the A-028 snapshot without re-accounting in JavaScript:
Spine groups exact decimals from `v_spend_rate` into total, purpose, and model
lanes. A known subtotal accompanied by unpriced receipt lines is visibly
partial; an all-unpriced point remains unpriced, never `$0` or free. Lifecycle
and Palace signals without a canonical timestamp or table are visibly not
recorded. M2C does not parse revision prose or infer a transition from a head's
current `updated_at`.

## Acceptance map

| Criterion | Rendered proof | Trace/adversarial proof |
|---|---|---|
| first-party rack resident | desktop/mobile screenshots; five isolated frames | CSP includes `connect-src 'none'`; forged/private fetch is absent |
| dollar-true lanes | exact hover/touch values, partial-price wording | `source_view=v_spend_rate`; total/purpose/model conservation |
| hover/touch scrub | visible minute/value marker | selection bus carries lane id + `as_of` |
| lane focus | selected lane remains full-emphasis; siblings stay visible | serialized `spend_lane` selection |
| collapse | panel rows reallocate; data/focus survive reopen | `aria-expanded` and geometry before/after |
| Palace Vitals | measured created/active/pinned; honest unavailable copy | A-028 source/status/value triples |
| failure isolation | strip says it could not refresh; Chat remains usable | fixture forces only the Vitals reader to fail |
| responsive law | exact 390×844 screenshots; composer remains reachable | `clientWidth == scrollWidth == 390` |

## Repeat the scripted rendered pass

From the Harness repository, the browser driver builds on the committed web
bundle, starts its own fixture on a non-owner port, uses a fresh browser
context, and terminates the fixture in `finally`:

```bash
npm run lint --prefix web
npm run build --prefix web
npm run verify:m2c:browser --prefix web
```

The rule-7 fixture is intentionally unmistakable: every screenshot carries the
full-surface `M2C REGRESSION FIXTURE` banner. It is deterministic evidence only,
never SOP or owner-app evidence.

## Live walkthrough

[`SOP.md`](SOP.md) records the independently executed rule-8 walkthrough
against the real product, a current local Spine/Postgres, real OpenRouter chat
and embedding calls, and an isolated browser profile. It is not performed
against H5 or any deterministic model.
