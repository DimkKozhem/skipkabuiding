# Аудит class-aware: mapping / ID / типы (extended 197)

Дата: 2026-09-27. Без нового inference.  
Метрики: `reports/metrics_mocs_extended_v2.1.json` (+ `metrics_mocs_diagnostic_v2.1.json`).  
v2 **не** затёрт. Тесты: `test_mocs_size_ignore_eval.py` — **6 passed**.

## 1. Баг mapping / class ID?

| Проверка | Результат |
|---|---|
| Перестановка YOLO class id ↔ имя | **Нет.** YOLOE: `class = prompts[cls_i]` после `set_classes(sorted EQUIPMENT_CLASSES)`; все имена в raw — канон (`excavator`, `truck`, …). Source id MOCS (1=Static crane…) в preds не используется. |
| Порядок промптов | Один список lock: `bulldozer…truck` (sorted). Совпадает с GT `mapped_class`. |
| Worker / Other / Hanging | В equipment GT не входят; preds этих имён отбрасываются (`normalize`→None), не становятся TP техники. |
| DINO label debris | **Да, дефект записи имени в raw:** `##zer`, `##dozer`, `##vat`, `pile driver` (с пробелом). Не перестановка ID. В **v2.1** нормализуются к канону; macro DINO 0.029→**0.032** (почти без эффекта). |

Пример: raw DINO `##dozer` / `##zer` при IoU к GT excavator/bulldozer; YOLOE `cls_i→prompts[i]` без обломков.

**Вывод:** разрыв macro AP (DINO≪YOLOE) — **не** артефакт перестановки ID. После нормализации остаётся слабая классификация типов (особенно DINO).

## 2. Матрица типов (геометрический матч IoU≥0.5, класс не для матча)

Пропуски GT и orphan preds — вне матрицы.

| | DINO | YOLOE-26L |
|---|---:|---:|
| Геом. матчи | 437 | 423 |
| Верный тип | 16.5% | **40.9%** |
| Неверный тип | 83.5% | 59.1% |
| GT miss / pred orphan | 359 / 289 | 373 / 195 |

Главные путаницы (gt→pred):

- **обе:** `static_crane→crane` (DINO 121, YOLOE 86)
- DINO: `truck→pump_truck` (69), `excavator→bulldozer` (64)
- YOLOE: `excavator→loader` (26), `static_crane→pile_driver` (25), `concrete_mixer→truck` (16)

Диагностика кратко: YW type-ok ≈37.7%; SAM ≈52.6% (лучше тип, но legacy/v2 P≈0.275 — не в автофакты).

## 3. AP по классам (extended 197, v2.1, class-aware)

Macro = равные веса, **n_classes_in_macro = 10**; classes_without_gt = [].

| Класс | n_gt | DINO AP50 / AP50–95 | YOLOE AP50 / AP50–95 |
|---|---:|---|---|
| excavator | 229 | 0.114 / 0.084 | **0.232 / 0.162** |
| truck | 186 | 0.061 / 0.038 | **0.410 / 0.295** |
| static_crane | 182 | 0.000 / 0.000 | 0.000 / 0.000 |
| crane | 46 | 0.066 / 0.044 | 0.011 / 0.006 |
| concrete_mixer | 33 | 0.000 / 0.000 | 0.000 / 0.000 |
| pump_truck | 29 | 0.001 / 0.001 | 0.000 / 0.000 |
| roller | 27 | 0.000 / 0.000 | 0.000 / 0.000 |
| pile_driver | 23 | 0.000 / 0.000 | 0.032 / 0.012 |
| loader | 21 | 0.000 / 0.000 | 0.089 / 0.083 |
| bulldozer | 20 | 0.080 / 0.070 | 0.059 / 0.042 |
| **macro** | — | **0.032 / 0.022** | **0.083 / 0.060** |

Class-agnostic AP50 (детекция техники): DINO **0.477**, YOLOE **0.460**.

## 4. Парный bootstrap (DINO − YOLOE), 41 эпизод, 1000 boot

| Метрика | point Δ | 95% CI Δ | P(Δ>0) |
|---|---:|---|---:|
| class-agnostic AP50 | +0.017 | **[−0.013, +0.058]** | 0.882 |
| macro AP50 | −0.051 | **[−0.082, −0.022]** | 0.000 |

Agnostic: CI включает 0 — уверенного превосходства DINO нет.  
Macro: CI целиком ниже 0 — YOLOE устойчиво лучше по типам (при всё ещё низком абсолютном macro).

## 5. Ограничение и роли

- Детекция техники (class-agnostic) — пригодна для проверки в пилоте.
- Классификация по типам — **слабая** (подтверждено аудитом; не баг ID).
- Автоподтверждение типа / `missing_equipment` по этим детекторам — **не включать**.
- Тип в факт — только после инспектора.

См. `MOCS_PILOT_ROLES.md`. Production не менялся.
