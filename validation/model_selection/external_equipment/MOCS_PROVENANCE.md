# Происхождение MOCS / упаковка AmiyaChan

Дата проверки: 2026-09-27.

## Первичный источник

| Поле | Значение |
|---|---|
| Название | Moving Objects in Construction Sites (**MOCS**) |
| Статья | An et al., *Dataset and benchmark for detecting moving objects in construction sites*, Automation in Construction, 2021 — https://doi.org/10.1016/S0926580520310621 |
| Официальная страница | http://www.anlab340.com/Archives/IndexArctype/index/t_id/17.html (Tsinghua An Lab) |
| Официальный объём | 41 668 изображений, 174 площадки, 13 категорий, ~222 861 instance; bbox + mask |
| Официальный split (статья/вторичные отчёты) | train≈19 404 / val≈4 000 / test≈18 264 (COCO-style JSON) |

**HF `AmiyaChan/mocs_yolo` — сторонняя YOLO-упаковка**, не официальный релиз An Lab. Card: license MIT, файлы `images.rar` (~9.0 GiB, sha `dd72cfc2…`) + `labels.rar`. README на HF пустой (только license). Эквивалентность официальному набору **не доказана автоматически**.

## Классы: официальные vs HF YOLO vs mapping

| id | Official (anlab340) | HF `classes.txt` | Наш mapped | vs `equipment_rules.yaml` |
|---:|---|---|---|---|
| 0 | Worker | Worker | skip | нет в ontology types |
| 1 | Tower crane | Static crane | `static_crane` | ontology: `mobile_crane` только — **расхождение имён** |
| 2 | Hanging hook | Hanging head | `hanging_head` | нет в ontology |
| 3 | Vehicle crane | Crane | `crane` (не auto→mobile_crane) | близко к `mobile_crane`, **не сливаем автоматически** |
| 4 | Roller | Roller | `roller` | встречается в rules как stage hint, не type-enum |
| 5 | Bulldozer | Bulldozer | `bulldozer` | в rules как hint, не type-enum |
| 6 | Excavator | Excavator | `excavator` | ✓ type |
| 7 | Truck | Truck | `truck` | ontology: `dump_truck` — **не ужесточаем** |
| 8 | Loader | Loader | `loader` | нет type-enum |
| 9 | Pump truck | Pump truck | `pump_truck` | нет type-enum |
| 10 | Concrete transport Mixer | Concrete mixer | `concrete_mixer` | ✓ type |
| 11 | Pile driver | Pile driving | `pile_driver` | нет type-enum |
| 12 | Other vehicle | Other vehicle | `other_vehicle` | **не** маппить в конкретную машину |

Ontology types в `config/equipment_rules.yaml`: только `excavator`, `dump_truck`, `concrete_mixer`, `mobile_crane`. Остальные MOCS-классы остаются внешними метками для benchmark.

## YOLO-преобразование

- Labels: YOLO normalized `class cx cy w h` per line; splits `train/val/test` в rar.
- HF counts (labels): train 19 404 / val **2 000** / test **2 000** — **не совпадает** с официальным val≈4000 / test≈18264.
- Вывод: использовать как **внешний YOLO-репак** с официальным происхождением классов MOCS; официальный COCO JSON / masks в этой упаковке нет.

## Политика для диагностики

- Официальный split An Lab недоступен локально → фиксируем diagnostic поднабор из HF `val` (+ при нехватке `test`), **до** inference.
- Эпизоды: имена `00xxxxx.jpg` последовательные; соседние id не режем tune/diag_test (группируем по префиксу диапазона / stride).
- Запрещённые auto-maps сохранены в `class_mapping_mocs.json`.
