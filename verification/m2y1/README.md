# M2Y1 decision-provenance evidence

F023 exposed an authority inversion: the rack authored `machine_id` on queue
decisions. The owner API now accepts only the human choice fields and stamps the
configured daemon identity before forwarding the request to Spine. A browser
cannot supply or override that identity.

`scout-decision-annotations.json` preserves the two affected M2X observations
without rewriting append-only history. Both were made in the
`m2x-sop-verification` session and are explicitly classified as verification.

No learner migration or floor repair was required. The enacted A-031 learner
selects `InjectionEvent` rows and computes `eligible_dispositions` from the
filtered examples; queue `ApprovalDecision` rows are not an input. The two seed
rejections therefore never contributed to the 25-signal training floor. The
annotation makes that boundary and the intended classification durable if the
learner's inputs expand later.

Regression evidence:

- `01-rejected-queue-trusted-identity.png` shows the visible deterministic
  fixture immediately after the owner-style **Reject batch** tap returned the
  queue to its clear state.
- `tap-trace.json` records both resulting decisions with
  `machine_id=m2i-verification-machine` and zero pending cards.
- `tests/test_queue_provenance.py` proves an owner tap and an SOP tap arrive at
  the Spine boundary with their distinct configured daemon identities, rejects
  a browser-supplied identity, and checks the published owner API schema.
- `web/tests/approvalQueue.test.mjs` proves the rack emits choice-only item and
  batch payloads.
- `verification/m2i/scenario_app.py` records the daemon-stamped identity in the
  deterministic tap trace used for browser verification.
