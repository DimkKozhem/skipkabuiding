# MOCS diagnostic v1 — результаты

Дата: 2026-09-27.  
Manifest: `manifests/mocs_diagnostic_v1.json` (tune 40 / diag_test 120, episode blocks `stem//20`, без пересечения).  
Метрики: `reports/metrics_mocs_diagnostic_v1.json`.  
Raw: `artifacts/model_selection/runs/external_equipment/mocs_diagnostic/`.  
Пороги miniexcav **не** использовались. YOLOE-11L не участвовал.

## Источник изображений

| Поле | Значение |
|---|---|
| Файл | `data/external/benchmark_sources/mocs_yolo_hf/images.rar` |
| Размер | **9 675 931 636** байт (= `x-linked-size`) |
| Маршрут | HF resolve → CDN `us.aws.cdn.hf.co` через proxy `127.0.0.1:10808`; `curl -L -C -` (после зависания hf_hub на 0 байт и обнуления incomplete) |
| Labels | `hf_probe/mocs_labels_extracted/` — 2000 val paired 1:1 |
| Extract | только `images/val/` (2000 jpg) |

## Совпадение имён / боксов

- val: 2000 labels ↔ 2000 images, 0 missing.
- YOLO norm → xyxy проверен на поднаборе; боксы в пределах кадра.
- Equipment boxes на поднаборе: **503 small / 112 medium / 60 large** (relative_area).
- Нативные пиксели (median w×h): small ≈ 90×67; medium ≈ 288×255; large ≈ 610×481.
- После resize моделей (approx scale = imgsz/max(H,W), median image max≈1200):

| Модель | Resize | small box ≈ px после resize (median) |
|---|---|---|
| YOLOE-26L | letterbox **640** | ~48×36 |
| DINO | long-edge **800** (VRAM) → processor | ~60×45 |
| YOLO-World | **1280** | ~96×71 |
| SAM 3.1 | imgsz **720/728** | не запускался |

`<4%` площади ≠ одинаковая сложность: после 640 многие «small» всё ещё десятки пикселей.

## Таблица (equipment, class-agnostic match + by class в JSON)

| Модель | Env | locked thr (tune) | AP50 | P | R | F1 | AP50 small/med/large |
|---|---|---:|---:|---:|---:|---:|---|
| Grounding DINO | myenv, cuda:0 рядом с Qwen | **0.2** | **0.382** | 0.601 | 0.466 | 0.525 | 0.131 / 0.407 / 0.454 |
| YOLOE-26L | `.venv` cuda:1 | **0.2** | 0.363 | 0.657 | 0.445 | 0.531 | 0.167 / 0.274 / 0.302 |
| YOLO-World V2.1 L | `.venv-yoloworld` cuda:1 | **0.4** | 0.223 | 0.388 | 0.391 | 0.390 | 0.111 / 0.181 / 0.141 |
| SAM 3.1 | — | — | — | — | — | — | **blocked_runtime** |

### SAM блокер (не «проиграла»)

Веса `models/sam3.1_multiplex.pt` есть. `SAM3SemanticPredictor` + `texts=` → `KeyError: 'language_features'` в `sam3_image.py:forward_grounding`.

### Допуск в расширенный test (предварительно)

- **DINO** и **YOLOE-26L** — допущены (отработали; на small оба слабы, DINO лучше на medium/large).
- **YOLO-World** — допущен условно (отработал, AP ниже).
- **SAM** — не допущен, пока не снят runtime-блокер.

Production / CMP этим не закрыты.
