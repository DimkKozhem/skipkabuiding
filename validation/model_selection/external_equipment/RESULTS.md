# Результаты внешнего benchmark техники

Дата: 2026-09-27.  
Датасет: `miniexcav_excavator_v1`.  
Метрики канон: **v1.2** (`reports/metrics_miniexcav_v1.2.json`) — закрытый этап `selected_external_large_excavator`, scored **n_test=171** после визуального снятия aHash-исключений (`NEAR_DUP_VISUAL_REVIEW.md`).  
История не затёрта: `v1.1` = aHash-exclude test=165 (`metrics_miniexcav_v1.1.json`); индекс — `reports/METRICS_INDEX.md`.  
Production не менялся.

Сырые предсказания: `artifacts/model_selection/runs/external_equipment/`.

## Сводная таблица (excavator, v1.1 visual-restored)

| Модель | Env | locked thr (только miniexcav) | AP50 | AP50–95 | P | R | F1 | TP/FP/FN |
|---|---|---|---:|---:|---:|---:|---:|---|
| Grounding DINO base | **myenv** | score≥0.4 | **0.9895** | **0.9654** | 0.9605 | 0.9942 | 0.977 | 170/7/1 |
| YOLOE-26L | `.venv` | conf≥0.1 | 0.8412 | 0.7650 | 0.8548 | 0.9298 | 0.8908 | 159/27/12 |
| YOLOE-11L | `.venv` | conf≥0.1 | 0.7414 | 0.6601 | 0.8187 | 0.8187 | 0.8187 | 140/31/31 |

Пороги **не** универсальны. AP — полный score; P/R — после tune-lock.

## relative_area (не COCO)

`relative_area_small` &lt;0.04 / `medium` &lt;0.16 / `large` ≥0.16.  
В by_size — AP50 и F1 рабочей точки. `relative_area_small`: n_gt=1 — не статистика.

## Следующий этап

Multi-class + distant: **MOCS YOLO** (HF) — labels готовы, images качаются.  
Протокол: `DIAGNOSTIC_PROTOCOL.md`. Реестр: `SOURCE_CANDIDATES.md`.  
Диагностический прогон (DINO, YOLOE-26L, SAM, YOLO-World) — после распаковки images; YOLOE-11L baseline-frozen.
