# MOCS diagnostic v2 — ignore по размеру (без нового inference)

Дата: 2026-09-27.  
Метрики: `reports/metrics_mocs_diagnostic_v2.json` (+ SAM: `metrics_mocs_diagnostic_sam_v2.json`).  
Evaluator: `scripts/mocs_eval_v2.py`.  
Пороги из lock: DINO/YOLOE **0.2**, YW **0.4**, SAM **0.5**.

**Legacy** (политика `legacy_size_fp_inflation`, preds вне бина = FP):  
`RESULTS_MOCS_DIAGNOSTIC*.md`, `metrics_mocs_diagnostic_v1*.json`, `metrics_mocs_diagnostic_sam_v1.json`.

## Правило ignore

GT вне целевого `relative_area_*` — ignore (не FN). Pred с IoU≥0.5 к ignore-GT — не FP. Pred без матча к target и ignore — FP. Несматченный target GT — FN. Class-agnostic AP50 = **обнаружение техники** (тип не требуется); preds Worker/Other vehicle/Hanging head исключены. Per-class — class-aware (неверный тип ≠ TP). Macro AP — **равные веса** классов с `n_gt>0` (остальные показаны как nan).

Тест: `test_mocs_size_ignore_eval.py` — **2 passed**.

## diag_test 120 (n_gt size: 396 / 86 / 48)

503/112/60 — подпись **всех 160** кадров, не scored test.

| Модель | class-agnostic AP50 | P / R / F1 | macro AP50 / AP50–95 | small AP50 (n=396) | med (86) | large (48) |
|---|---:|---|---:|---:|---:|---:|
| DINO | 0.382 | 0.601 / 0.466 / 0.525 | 0.024 / 0.018 | 0.251 | 0.574 | 0.636 |
| YOLOE-26L | 0.363 | 0.657 / 0.445 / 0.531 | 0.068 / 0.048 | **0.256** | 0.376 | 0.372 |
| YOLO-World | 0.223 | 0.388 / 0.391 / 0.390 | 0.082 / 0.062 | 0.156 | 0.218 | 0.200 |
| SAM 3.1 | 0.404 | **0.275 / 0.728 / 0.400** | 0.251 / 0.186 | 0.355 | 0.549 | 0.664 |

На small после ignore YOLOE ≈ DINO (0.256 vs 0.251); legacy «YOLOE сильно лучше на малых» было завышено FP-инфляцией. Medium/large по-прежнему лучше у DINO.
