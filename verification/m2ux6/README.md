# M2UX6 verification

This directory separates repeatable fixture evidence from the live owner-app
walkthrough required by B.6 rule 8.

The eight PNGs are produced by the production Rack under the explicit
`M2UX6 REGRESSION` verification identity. They cover mount, module hover,
empty-state ambience, and reduced motion for WIZARD MODE and TECHNOMANCER.
`grimoire-rendered.json` records the computed animation, persistence, and
cross-frame theme observations behind those captures.

Run the deterministic pass from `web/` while the isolated scenario app is on
port `8809`:

```sh
npm run verify:m2ux6:browser
```

The separate [SOP.md](SOP.md) records the real packaged-Rack pass. Live Palace
content is intentionally not retained in this directory.
