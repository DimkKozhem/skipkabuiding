# SAM diagnostic v2 (пересчёт из raw)

Метрики: `reports/metrics_mocs_diagnostic_sam_v2.json`.  
Legacy: `RESULTS_MOCS_SAM.md`, `metrics_mocs_diagnostic_sam_v1.json`.  
thr lock **0.5**. Записка product owner: `SAM_ADAPTER_REVIEW_REQUEST.md`.

| | значение |
|---|---|
| class-agnostic AP50 | 0.404 |
| P / R / F1 | **0.275 / 0.728 / 0.400** |
| small / med / large AP50 (ignore) | 0.355 / 0.549 / 0.664 |
| n_gt size | 396 / 86 / 48 |

Высокий recall при низкой precision = много ложных срабатываний.  
**Не основание** включать SAM в автоматические факты / WorkFact. Экспериментальный адаптер работает; production не менялся.
