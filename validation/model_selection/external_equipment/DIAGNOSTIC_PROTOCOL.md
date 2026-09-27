# Протокол диагностического этапа (multi-class / distant)

Версия: `diagnostic-multiclass-v1` · 2026-09-27  
Не затирает miniexcav v1 / v1.1. Отдельный manifest.

## Цель

Проверить кандидатов на **новом** источнике с несколькими классами техники и объектами `relative_area_small/medium`, не на close-up excavator miniexcav.

## Участники диагностики (обязательный список)

| Модель | Роль | Env |
|---|---|---|
| Grounding DINO base | основной кандидат прошлого этапа (не универсальный победитель) | experimental **myenv** |
| YOLOE-26L | альтернатива | `LCT2026/.venv` |
| SAM 3.1 multiplex | если веса+адаптер готовы | `.venv` + `models/sam3.1_multiplex.pt` + `Sam3Provider` |
| YOLO-World V2.1 L | если адаптер+venv готовы | `.venv-yoloworld` + `artifacts/model_selection/third_party/YOLO-World` + `l_stage2-*.pth` |

**Не участвует:** YOLOE-11L (**baseline-frozen**).

На этапе miniexcav у SAM и YOLO-World статус остаётся `not_run` (не проиграли). Допуск в **расширенный** test — только по итогам этой диагностики.

Если модель не стартует — в отчёте точный блокер (путь, traceback), статус `blocked_runtime`, не «проиграла».

## Пороги

- Пороги miniexcav (DINO **0.4**, YOLOE **0.1**) **не переносятся**.
- На диагностическом поднаборе: выделить **tune** (фиксированный список sample_id), подобрать порог только на tune, заморозить, оценить оставшиеся кадры поднабора.
- Расширенный test полного датасета **не** использовать для подбора порога.
- AP — по полному диапазону score; P/R — при locked пороге с tune.

## Поднабор

- Отдельный файл: `manifests/mocs_diagnostic_v1.json` (после появления images).
- Не смешивать с miniexcav и со Скрипкой.
- Критерии набора кадров (фиксируются до inference):
  - ≥3 mapped equipment-классов с боксами;
  - доля боксов `relative_area_small` (<0.04) ≥ 30% **или** явно задокументированный дефицит;
  - без SAM-proposals как GT;
  - near-dup: sha256 + визуальная проверка кандидатов aHash (Hamming≤5 не достаточна).

## Допуск в расширенный test

Модель допускается дальше, если на диагностике:

1. технически отработала на всём поднаборе;
2. AP50 / F1 не «ломаются» на `relative_area_small` сильнее остальных (сравнительно, не абсолютный порог из miniexcav);
3. нет критического class-collapse (одна метка на все классы) при честном mapping.

Иначе — `hold` или `blocked_runtime` с причиной.

## Mapping

См. `class_mapping_mocs.json`. Запрещено: crane→mobile_crane автоматом без обоснования; tractor→bulldozer; shovel→excavator; other→конкретная машина.  
`Worker` / `Other vehicle` / `Hanging head` — отдельные метки или `unmapped_skip` в equipment-метриках.

## Метрики

Отдельно: источник, класс, `relative_area_*`. Файлы: `reports/metrics_<source>_diagnostic_v1.json` + raw в `artifacts/model_selection/runs/external_equipment/<source>/`.
