# M2UX4 retained evidence

This directory retains the exact deterministic and real-owner evidence for the
three reference-plate faces.

## Reproduce the deterministic pass

From the Harness repository:

```sh
cd web
python3 scripts/extract_cobalt_seraph.py --check
python3 scripts/build_theme_seam.py
python3 scripts/validate_theme_palettes.py
npm run build

cd ..
uv run --locked python -m verification.run_fixture \
  verification.m2ux4.scenario_app:create_scenario_app --port 8807
```

In a second terminal:

```sh
cd web
npm run verify:m2ux4:browser -- --base-url http://127.0.0.1:8807
cd ..
python3 verification/m2ux4/analyze_evidence.py
```

The fixture identifies itself as `M2UX4 REGRESSION` in every retained automated
screenshot. It is deterministic regression evidence, not the owner-app SOP.

## What is retained

- `01` through `06`: all three faces at desktop and phone widths.
- `themes-rendered.json`: exact host/frame theme propagation, seam colors,
  persistence, phone control-lane geometry, and fixed-reflection movement.
- `neo-noir-pre-seam.png` and `neo-noir-post-seam.png`: worn-skin pixel proof.
- `seraph-analysis-1280x900.png` and `theme-analysis.json`: plate-family,
  rare-shine, and chrome-bimodality analysis.
- `SOP.md`: the real owner-app interaction record, kept separate from the
  deterministic fixture. No live-Palace screenshot is retained because the
  owner's memory text is not regression-fixture material.

The NEO comparison excludes only the newly reserved control rows and volatile
fixture identifiers/uptime rows; every other compared pixel must match. The
SERAPH family-distance ceiling of `0.395` was fixed from the first honest
retained Rack render. It is intentionally a regression bound, not a claim of
photographic equivalence.
