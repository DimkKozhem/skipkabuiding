---
name: temporal
description: Скрипка temporal analysis and plan/fact deviation. Use for no_dynamics, evaluate, seed jobs, DeviationEngine.
model: inherit
---

You own `src/sitewatch/temporal/**`, `src/sitewatch/deviation/**`, `src/sitewatch/pipeline/evaluate.py`, `src/sitewatch/pipeline/seed.py`.

Rules:

- Hybrid: ΔS≈0 + KSG progress + N days → `no_dynamics`. No neural net for stop/no-stop.
- Alert text must not contain «остановлен».
- Do not import ultralytics/YOLO.
- `missing_element` is snapshot lag; keep it, do not replace `no_dynamics` with it.
- Visual change is supporting payload.

After edits run:
`LCT2026/.venv/bin/python -m pytest tests/test_temporal.py tests/test_deviation.py tests/test_e2e.py -q`
