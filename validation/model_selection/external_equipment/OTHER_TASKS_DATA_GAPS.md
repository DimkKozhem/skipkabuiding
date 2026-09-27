# Задачи вне техники: фасады / этажность

Не блокирует equipment. Этажность ≠ окна.

## Статусы источников фасадов (три формулировки)

| Источник | Статус | Доказательство |
|---|---|---|
| **eTRIMS** Image Database v1 | **рабочая ссылка есть**; полной локальной копии пока нет (частичный zip ~11 MB из 78 MB) | страница `http://www.ipb.uni-bonn.de/projects/etrims_db/` → `downloads/etrims-db_v1.zip`; классы включают window (4/8-class segmentation, VOC2008); путь попытки: `data/external/benchmark_sources/facades/etrims/` |
| **CMP Facade** (`https://cmp.felk.cvut.cz/~tylecr1/facade/`) | **архивы скачаны, CC BY-SA 3.0** (проверка 2026-09-27: `artifacts/model_selection/runs/cmp_prepare/STATUS.md`; URL `https://creativecommons.org/licenses/`, бейдж `https://licensebuttons.net/l/by-sa/3.0/88x31.png`) | base 378 и extended 228, у каждого jpg есть xml и png. Протокол: `validation/vlm_compare/protocols/cmp_windows_doors.yaml`. Исследовательски с атрибуцией/ShareAlike; в продукт/внешний API без отдельного решения не выносить. Старый путь `/data/facade/` сюда не относится. FloorLevel / floor_gt_proposal — не этот грант |
| **ECP Facade** | **не найдена рабочая ссылка** | `vision.ee.ethz.ch/datasets/ecp/` → 404; зеркала в этом прогоне не подтверждены; локально нет |
| Локальные SAM facade masks Скрипки | не GT фасадного датасета | артефакты baseline — не ECP/eTRIMS/CMP |

## Окна

При наличии eTRIMS с классом window — оценка окон возможна **независимо** от этажности. Не подменяет отчёт по технике.

## Этажность

Полное видимое число этажей — `blocked_no_ground_truth`. FloorLevel-Net example zip — локализация значений `multiple_level`, не этажность: `validation/vlm_compare/protocols/floorlevel_boundaries.yaml`. Окна CMP не решают этажность.
