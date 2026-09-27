---
name: cv
description: Скрипка CV adapters, taxonomy, demo image generation. Use for detection classes, aggregator, YOLO/SAM/DINO slots, demo_assets.
model: inherit
---

You own `src/sitewatch/cv/**`, `config/classes.yaml`, `src/sitewatch/pipeline/demo_assets.py`.

Rules:

- Emit `Detection` only. Canonical names from `config/classes.yaml`.
- No `floor` detector class. `floors` / `structural_levels` from `scene.floors` or VLM `visible_floor_levels` — not raw `slab`/`floor_slab` box counts.
- Do not import KSG or DeviationEngine.
- Do not claim YOLO quality from sidecar labels.
- Video: 1–3 FPS sampling.

After edits run:
`LCT2026/.venv/bin/python -m pytest tests/test_actual_state.py tests/test_video.py -q`
