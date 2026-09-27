# Протокол внешнего benchmark техники (v1)

Версия: `external-equipment-benchmark-2026-09-27-v1`.  
Отдельно от `validation/model_selection/EXPERIMENT_PROTOCOL.md` (Скрипка).  
Манифест Скрипки (`manifest.json` v2) **не** изменяется этим протоколом.

## Назначение

Измерить zero-shot / open-vocab детекцию строительной техники на **опубликованной** разметке внешних датасетов.  
Результат ≠ accuracy на камерах Скрипки.

## Источник v1

`miniexcav_excavator_v1` — GitHub `miniexcav/Construction-Machines-Images-Dataset`, каталог `excavator-dataset-223img-yolo`, commit зафиксирован в `manifest.json`.

- Разметка: YOLO bbox, класс `0` = excavator (единственный).
- Лицензия / назначение (дословно из README Disclaimer): данные scraped from Google Images; **educational and research purposes**; labels created by dataset authors; commercial use may require permissions from original image creators.
- Автор советует: *avoid images with small objects or those of far distance* — набор = крупноплановая техника, не дальний общий план.

Официального split нет. После sha256-дедупа: ~20% `tune`, остальное `test` (правило в manifest). Test не используется для подбора порога.

## Пороги размера (зафиксированы ДО метрик)

`area_ratio = box_area / image_area` (из YOLO bw×bh):

| bin | условие |
|---|---|
| small | area_ratio < 0.04 |
| medium | 0.04 ≤ area_ratio < 0.16 |
| large | area_ratio ≥ 0.16 |

Файл: `size_bins_locked.json`. На miniexcav v1 почти все боксы — `large`.

## Оценка

- IoU match = 0.5 для рабочей точки.
- AP50, AP50–95 (IoU 0.50:0.05:0.95, VOC 101-point).
- Precision / Recall / TP / FP / FN при пороге, выбранном на **tune** (max F1, tie-break precision).
- Разрез по size_bin.
- Учитывается только класс `excavator` (полнота разметки подтверждена только для него). Предсказания других классов в primary AP не входят; сырые dumps сохраняются.
- Пустые label-файлы на этом наборе отсутствуют; негативы «нет экскаватора» в наборе не заявлены.

## Mapping

`miniexcav class 0 excavator` → `excavator` (`config/construction_ontology.yaml` / этапы excavation,foundation в `equipment_rules.yaml`).  
Автоматически не делать: crane→mobile_crane, tractor→bulldozer, other→машина.

## Модели (локально)

Устройство по умолчанию: `cuda:1`. Qwen на `cuda:0` не выгружать.

| Модель | Env |
|---|---|
| YOLOE-11L | `LCT2026/.venv` |
| Grounding DINO base | **myenv** (experimental; в `.venv` нет transformers) — явно |
| SAM 3.1 | `.venv` при отдельном прогоне |

YOLOE-26L / YOLO-World — только если адаптер готов; иначе статус not_run.

## Две строки выводов

1. **Внешний benchmark** — цифры ниже.  
2. **Камеры Скрипки** — без claimed accuracy до human GT; прошлый YOLOE 0 boxes на офисе сюда не переносится.
