# Реестр проверенных источников (multi-class / distant) — 2026-09-27

Доказательство по файлам, не по карточке. miniexcav v1.1 закрыт как `selected_external_large_excavator`.

| ID | Источник | Аннотации | Классы / масштаб | Лицензия / доступ | Вердикт |
|---|---|---|---|---|---|
| miniexcav | GitHub Construction-Machines-Images-Dataset | YOLO bbox ✓ | 1 класс excavator; почти всё `relative_area_large` | публичный clone | **закрыт** (этап large excavator) |
| kaggle-xyzyxzzxy | kaggle.com/…/construction-equipment | не скачан | — | нет credentials | `blocked` (auth) |
| kaggle-arh-df | kaggle.com/…/arh-df | не скачан | — | нет credentials | `blocked` (auth) |
| kaggle-datacluster | kaggle.com/…/construction-vehicle-images | не скачан | image-level ожидается | нет credentials | `blocked` (auth); вероятно `images_only` |
| roboflow-jejung | universe …/construction-machinery-tbosw | 403 / 0 published | — | Cloudflare / API | `blocked` |
| construction_equipment_v1 | `data/external/…` локально | YOLO есть, но SAM proposals + train contamination | multi? | локальный | **не независимый тест** |
| incoming/ | `data/external/benchmark_sources/incoming/` | пусто | — | — | ждать zip |
| **mocs_yolo_hf** | HF `AmiyaChan/mocs_yolo` | **labels.rar скачан и разобран** (YOLO bbox, train/val/test) | 13 классов (Worker…Other vehicle); equipment: excavator/truck/crane/…; **~84% боксов relative_area_small** | card MIT; images.rar ~9.0 GiB public | **пригоден**; images в загрузке → diagnostic |
| ybli/yolo-construction-site-detection | HF | только README, нет images/labels в tree | — | — | `images_only` / empty |
| famerL/construction_defect_yolo | HF | defect detection | не техника площадки | — | не целевой (дефекты) |
| lonlonago/…UAV heavy machinery | GitHub | «sponsor for full data» | — | paywall | `blocked` (доступ ограничен) |
| SODA-D (VoltaLemon/zz94) | HF имена | не проверено по файлам в этом прогоне | SODA-D часто driving, не стройка | — | отложено |
| eTRIMS / ECP / CMP | facade ветка | см. `OTHER_TASKS_DATA_GAPS.md` | окна | — | не техника |

## Главный найденный набор

**MOCS YOLO (HF AmiyaChan/mocs_yolo)**  
- Labels: локально `data/external/benchmark_sources/hf_probe/mocs_labels_extracted/` + копия rar в `…/mocs_yolo_hf/`.  
- Images: `…/mocs_yolo_hf/images.rar` (download owner-side, без Kaggle).  
- Mapping: `class_mapping_mocs.json`.  
- Protocol: `DIAGNOSTIC_PROTOCOL.md`.  
- Loader: `scripts/build_mocs_diagnostic_manifest.py`.

## Почему нет diagnostic metrics прямо сейчас

Сравнение не имитировалось: **нет распакованных images** (архив ~9 GiB ещё качается / curl LFS завис, повтор через `huggingface_hub`). Labels доказаны. Как только `images.rar` на диске и распакован — owner соберёт `manifests/mocs_diagnostic_v1.json` и прогонит DINO + YOLOE-26L + SAM + YOLO-World по протоколу.

## Одно следующее действие (без токена в чат)

Действие пользователя **не требуется** для MOCS (публичный HF).  
Команда owner после докачки:

```bash
# проверить размер ~9675931636 байт
ls -la data/external/benchmark_sources/mocs_yolo_hf/images.rar
~/.local/bin/unrar x -o+ data/external/benchmark_sources/mocs_yolo_hf/images.rar \
  data/external/benchmark_sources/mocs_yolo_hf/
.venv/bin/python validation/model_selection/external_equipment/scripts/build_mocs_diagnostic_manifest.py
```

Опционально ускорить Kaggle-наборы: `~/.kaggle/kaggle.json` chmod 600 — см. `ACCESS_BLOCKERS.md` (не блокирует MOCS).
