# Проверка evaluator (miniexcav v1 → v1.1)

Дата: 2026-09-27. Новый inference **не** выполнялся. Пересчёт P/R/AP — только из сохранённых raw после исключения near-dup test.

## Подтверждено

| Проверка | Результат |
|---|---|
| Exact sha256 across splits | 0 пересечений (дедуп на сборке) |
| YOLO→xyxy и area_ratio | spot-check: боксы в пределах кадра, area_ratio совпадает |
| Масштаб предсказаний | YOLOE oob=0; DINO oob=1 (единичный, на метрики не влияет существенно) |
| Порог только на tune | YOLOE conf∈{0.05…0.5} → **0.1**; DINO score∈{0.15…0.4} → **0.4**; YOLOE-26L conf→**0.1** |
| AP vs P/R | AP считается по полному диапазону score (YOLOE raw conf≥0.01: 305 score&lt;0.1 и 171≥0.1; DINO infer box_thr=0.15 затем filter). P/R — после locked порога |
| Пересчёт TP/FP/FN из raw | совпал с v1 отчётом до near-dup cleanup |
| Env | YOLOE: `LCT2026/.venv` + ultralytics **8.4.146**; DINO: **myenv** + transformers **5.8.1** (experimental) |

## Промпты / классы

| Модель | Промпт / класс | Checkpoint |
|---|---|---|
| YOLOE-11L | `set_classes(["excavator"])` text | `artifacts/model_selection/weights/yoloe-11l-seg.pt` sha `a993fb0f…` |
| YOLOE-26L | `set_classes(["excavator"])` text | `…/yoloe-26l-seg.pt` sha `a612d2d5…` |
| Grounding DINO | text list `["excavator"]`, box_thr infer 0.15, text_thr 0.20 | HF `IDEA-Research/grounding-dino-base` rev `12bdfa31…` |

Evaluator: `validation/model_selection/external_equipment/scripts/run_compare_miniexcav.py` (IoU match 0.5, VOC-style 101-point AP).

## Near-duplicates

aHash Hamming≤5 дал **7** пар-кандидатов. **Визуальный просмотр выполнен** (`NEAR_DUP_VISUAL_REVIEW.md`): все пары — **не** дубли одной сцены (разные бренды/локации/студии).  

Исключения **сняты**; id `102,133,139,144,173,198` снова в scored test.  
v1.1 пересчитан из raw на **n_test=171** (`metrics_version`: `v1.1-visual-near-dup-restored`).  
Промежуточный exclude-файл сохранён: `metrics_miniexcav_v1.1_neardup_excluded_pre_visual.json`.

## Колонки размера

Правильные имена: `relative_area_small|medium|large` по `area_ratio` (`size_bins_locked.json`). Не COCO.  
В by_size — AP50 и F1 рабочей точки. `relative_area_small`: **n_gt=1**.

## Нужен ли был полный пересчёт?

Да, из raw после визуального вердикта (восстановление test). Новый inference не нужен. Этап miniexcav **закрыт**.
