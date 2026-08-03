# M2J verification

`browser_check.mjs` drives the visibly isolated MODEL DEVICE at desktop and
390×844, writes `rendered.json`, and captures live plus historical states. The
manual in-app Browser walkthrough found and repaired two issues before this
script passed: sliders initially required an unreliable hidden pointer-up
commit, and selector changes initially left Chat's active-model header stale.

The fixture trace must show accepted `model.temperature`, `model.effort`, and
`model.slug` changes; the slug change's `model.change`; the named resolution;
and the hostile module's `parameter.refused`. Python tests prove validation,
historical replay, override preservation across selector changes, and exact
broker-settings forwarding.
