# MOCS diagnostic v1.1 — уточнение метрик (без нового inference)

Дата: 2026-09-27.  
Исходный отчёт (сохранён): `RESULTS_MOCS_DIAGNOSTIC_v1.md` (= прежний `RESULTS_MOCS_DIAGNOSTIC.md`).  
Метрики: `reports/metrics_mocs_diagnostic_v1.1.json` (оригинал API-дампа: `metrics_mocs_diagnostic_v1.original.json`).  
Manifest **не** переписывался: `manifests/mocs_diagnostic_v1.json` (tune 40 / diag_test 120).

## Агрегация AP (evaluator)

Код: `scripts/run_mocs_diagnostic.py` → `evaluate_multiclass` + `run_compare_miniexcav.match_tp_fp_fn` / `ap_at_iou`.

| Срез | GT | Preds | Матч |
|---|---|---|---|
| **Overall AP50** | все equipment GT на diag_test (530 боксов) | все preds ≥ locked thr | **class-agnostic** IoU≥0.5; одна PR-кривая по score (micro) |
| **by_class AP50** | GT класса C | preds с `class==C` (если есть; иначе fallback all-preds) | class-agnostic IoU на отфильтрованных боксах |
| **by_relative_area AP50** | GT только бина | **все** preds кадра, где есть GT этого бина | class-agnostic; pred, попавший в GT другого бина на том же кадре, → **FP** |

Ignore: `Worker`, `Other vehicle` (`skip_ids`); `Hanging head` вне `equipment_eval_ids` — не входят в equipment GT.

### Почему overall AP50 может быть выше всех трёх size-AP50

Overall — единая задача на **всех** 530 GT. Size-AP — **три отдельные** задачи с другими знаменателями и завышенным FP (все preds кадра против GT одного бина). Это не среднее size-AP и не противоречие цифр.

На diag_test (DINO): overall **0.382** при small/med/large **0.131 / 0.407 / 0.454** — medium/large близки к overall, small тянет вниз; YOLOE: overall **0.363** при **0.167 / 0.274 / 0.302** (все size-AP ≤ overall из‑за FP-инфляции).

## Знаменатель 503 / 112 / 60

| Набор | small | medium | large |
|---|---:|---:|---:|
| **все 160** (tune+diag_test) | **503** | **112** | **60** |
| **только diag_test 120** (метрики в JSON) | **396** | **86** | **48** |

В v1 отчёте подпись «на поднаборе 503/112/60» смешивала все 160 с метриками по 120. **Исправлено:** 503/112/60 = все 160; AP by_size считался по diag_test (396/86/48).

## Таблица equipment (diag_test 120, class-agnostic overall)

| Модель | locked thr | AP50 | P | R | F1 | AP50 s/m/l (n_gt 396/86/48) |
|---|---:|---:|---:|---:|---:|---|
| Grounding DINO | 0.2 | 0.382 | 0.601 | 0.466 | 0.525 | 0.131 / 0.407 / 0.454 |
| YOLOE-26L | 0.2 | 0.363 | 0.657 | 0.445 | 0.531 | 0.167 / 0.274 / 0.302 |
| YOLO-World V2.1 L | 0.4 | 0.223 | 0.388 | 0.391 | 0.390 | 0.111 / 0.181 / 0.141 |
| SAM 3.1 | — | — | — | — | — | blocked (см. lock / SAM fix) |

Пороги на этих 120 **не** перебирались повторно.

## Per-class (diag_test, strict class filter + P/R при locked thr)

Полная таблица — `metrics_mocs_diagnostic_v1.1.json` → `by_class_strict`. Кратко:

| Класс | n_gt | DINO AP50 / P / R | YOLOE AP50 / P / R | YW AP50 / P / R |
|---|---:|---|---|---|
| excavator | 149 | 0.113 / 0.68 / 0.11 | **0.311 / 0.75 / 0.36** | 0.224 / 0.69 / 0.26 |
| truck | 95 | 0.053 / 0.32 / 0.06 | **0.392 / 0.45 / 0.43** | 0.248 / 0.58 / 0.26 |
| static_crane | 109 | 0.020 / 0.67 / 0.02 | 0.000 / 0 / 0 | **0.263 / 0.33 / 0.43** |
| crane | 54 | 0.140 / 0.10 / 0.32 | 0.047 / 0.10 / 0.15 | **0.162 / 0.12 / 0.30** |
| bulldozer | 18 | 0.084 / 0.07 / 0.17 | 0.000 / 0 / 0 | **0.198 / 0.14 / 0.22** |
| pile_driver | 34 | 0 / 0 / 0 | **0.119 / 0.10 / 0.24** | 0 / 0 / 0 |
| loader | 16 | 0 / 0 / 0 | 0.081 / 0.08 / 0.19 | 0.093 / 0.06 / 0.13 |
| pump_truck | 21 | 0.046 / 0.04 / 0.19 | 0 / 0 / 0 | 0.008 / 0.02 / 0.05 |
| concrete_mixer | 14 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 |
| roller | 20 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 |

Универсального победителя нет. Слабость на `relative_area_small` — главный практический итог диагностики.

Lock кандидатов: `MOCS_CANDIDATE_LOCK.json`.
