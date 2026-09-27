# Resolution tune v2 — ignore по размеру

Метрики: `reports/metrics_mocs_resolution_tune_v2.json`.  
Raw был: `artifacts/.../mocs_resolution_tune/*_raw.json` (пересчёт без inference).  
Legacy: `metrics_mocs_resolution_tune_v1.json`.  
Split: **extended_tune 43** only. Победитель по tune не объявляется.

| Модель | config | class-agnostic AP50 | small AP50 ignore (n_gt=133) |
|---|---|---:|---:|
| YOLOE-26L | lock 640 | 0.395 | 0.309 |
| YOLOE-26L | hi 1280 | 0.378 | **0.337** |
| DINO | lock LE 800 | 0.341 | 0.214 |
| DINO | hi LE 1280 | 0.344 | **0.227** |

Вывод по малым **не изменился по знаку**: увеличение разрешения поднимает small AP у обеих (YOLOE +0.028, DINO +0.013). YOLOE по-прежнему выше на small на этой tune-части.
