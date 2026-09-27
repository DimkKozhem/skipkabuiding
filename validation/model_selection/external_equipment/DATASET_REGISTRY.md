# Реестр внешних датасетов техники

Проверка 2026-09-27. Карточки сайтов не заменяют архив на диске.

| id | URL | Локально | Аннотации | Лицензия / назначение | Статус |
|---|---|---|---|---|---|
| miniexcav_excavator_v1 | https://github.com/miniexcav/Construction-Machines-Images-Dataset | `data/external/benchmark_sources/Construction-Machines-Images-Dataset/` commit `fc3e24b…` | **bbox YOLO**, 223 jpg + 223 txt, класс 0=excavator, 223 бокса; после dedup 218 img | README Disclaimer: Google Images scrape; **educational and research**; labels by authors; commercial may need rights from creators. Author tip: avoid small/far objects | **включён в benchmark v1** |
| kaggle_xyzyxzzxy_construction_equipment | https://www.kaggle.com/datasets/xyzyxzzxy/construction-equipment | нет | не проверено архивом | неизвестна без скачивания | **blocked**: нет `~/.kaggle/kaggle.json`, пакет `kaggle` не в `.venv` |
| kaggle_kartaviychert_arh_df | https://www.kaggle.com/datasets/kartaviychert/arh-df | нет | заявлено OD crane/excavator/other/tractor/truck — **не подтверждено** | неизвестна | **blocked**: нет Kaggle credentials |
| kaggle_datacluster_construction_vehicle_images | https://www.kaggle.com/datasets/dataclusterlabs/construction-vehicle-images | нет | боксы на карточке не подтверждены | неизвестна | **blocked** / вероятно `images_only` без доступа |
| roboflow_jejung_construction_machinery_tbosw | https://universe.roboflow.com/jejung/construction-machinery-tbosw | нет | индекс заявлен 78 img / 24 class / OD / CC BY 4.0, **0 published versions** | CC BY 4.0 (карточка) | **unavailable**: HTTP 403 Cloudflare без API key; нет опубликованной версии для скачивания аннотаций |

## Связанный локальный корпус (НЕ один из пяти ссылок)

`data/external/construction_equipment_v1/` — Wikimedia Commons + `keremberke/construction-safety-object-detection` (HF).  
Часть боксов Commons = **SAM3 proposals** (`label_proposals.py`: «Output is not ground truth»). Safety = COCO human labels, но **все ушли в train** локального YOLO и использовались для настройки/обучения в `validation/equipment_v1/`.  

→ **Не независимый тест** для этого цикла; не смешивать молча с пятью источниками; не оценивать SAM на SAM-proposals.

## Mapping (miniexcav)

См. `class_mapping.json` и `EVAL_PROTOCOL.md`.  
`class_0 excavator` → ontology `excavator`. Не маппить crane/tractor/other автоматически.

## Отбор

`SELECTION_STATUS.md`: **`selected_external_large_excavator`** = Grounding DINO на miniexcav (relative_area large excavators). Production config не менялся.  
Следующий приоритет — multi-class + distant: см. `ACCESS_BLOCKERS.md` (Kaggle credentials или архив в `incoming/`).
