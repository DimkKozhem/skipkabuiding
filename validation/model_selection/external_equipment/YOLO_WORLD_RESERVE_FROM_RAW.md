# YOLO-World — анализ резерва по raw (без нового inference)

Источник: `artifacts/.../mocs_diagnostic/yoloworld_raw_predictions.json` vs dino/yoloe26, diag_test 120, locked thr (YW 0.4, DINO/YOLOE 0.2).

## Есть ли класс/условие, где YW полезнее

| Класс | n_gt | YW AP50 | DINO AP50 | YOLOE AP50 | Вердикт |
|---|---:|---:|---:|---:|---|
| **static_crane** | 109 | **0.263** | 0.020 | 0.000 | **явное преимущество** (TP 47 vs 2 / 0) |
| **bulldozer** | 18 | **0.198** | 0.084 | 0.000 | преимущество на малом n |
| **crane** | 54 | **0.162** | 0.140 | 0.047 | слабое преимущество vs DINO; сильное vs YOLOE |
| excavator | 149 | 0.224 | 0.113 | **0.311** | хуже YOLOE |
| truck | 95 | 0.248 | 0.053 | **0.392** | хуже YOLOE |
| pile_driver | 34 | 0.000 | 0.000 | **0.119** | хуже YOLOE |
| loader | 16 | 0.093 | 0.000 | 0.081 | паритет с YOLOE, n мал |
| остальные | — | ≈0 | ≈0 | ≈0 | нет |

Overall AP50 YW (0.223) ниже DINO/YOLOE — как универсальный кандидат слабее. Как специалист по **static_crane** (и частично bulldozer/crane) — доказательство в raw есть.

## Статус

**reserve** — расширенный прогон **не** запускается; резерв owner не снимает автоматически в этом задании.  
Ансамбль DINO/YOLOE/YW по complementary TP **не проверен**.
