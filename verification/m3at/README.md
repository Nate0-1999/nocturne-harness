# M3AT attunement verification

This evidence came from the production owner app served by `create_dev_app` at
`http://127.0.0.1:8797/` with a disposable local home. No scenario fixture or seeded
browser state was used. The Palace endpoint was deliberately unavailable because this
charge concerns local Stage layout and transcript journaling, not provider or Palace
behavior.

In the real Chrome UI, two Chat instances were pinned to distinct durable threads and
two Context Bars instances were arranged beside them. Their chrome badges named the
two different threads simultaneously. A pointer drag moved one Context Bars frame to
the other source and its badge changed without opening settings. Placing it at the
exact midpoint produced a random, sticky choice and the daemon appended
`rack.attunement.pick` event `01M1CDHZT7SHG2JXG60688PZHK`. Reload retained the choice.

Memory Graph was then moved on the Graph layer and switched to Nearest source. Its
badge resolved a Chat source on the Work layer, demonstrating cross-layer attunement.
The browser console remained free of warnings and errors. A screenshot of the
side-by-side distinct-thread state was captured during the verification run; the
structured observations are retained in `trace-summary.json`.
