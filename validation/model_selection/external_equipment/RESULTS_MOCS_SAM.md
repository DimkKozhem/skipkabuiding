# SAM 3.1 multiplex — diagnostic после фикса адаптера

Дата: 2026-09-27.  
Run-dir: `artifacts/model_selection/runs/external_equipment/mocs_diagnostic_sam/` (не затирает `mocs_diagnostic/`).  
Метрики: `reports/metrics_mocs_diagnostic_sam_v1.json`.  
Production `config/perception.yaml` **не** менялся.

## Причина KeyError: language_features

`forward_grounding` читает `backbone_out["language_features"]` из `self.text_embeddings` (заполняется `set_classes` → `backbone.forward_text`).

Диагностический раннер вызывал `ultralytics.SAM(...).predict(..., texts=)` **без** `setup_model` / `set_image` / корректного text-path → `text_embeddings` пуст → KeyError.  
Веса совместимы: в ckpt есть `detector.backbone.language_backbone` (295 ключей).

## Исправление (experiment adapter)

`scripts/run_mocs_sam_diagnostic.py`:

1. `SAM3SemanticPredictor.setup_model(model=None)`
2. `set_image`
3. box-only decode через `_inference_features(..., text=chunk)` + NMS (без upsample масок — иначе CPU RAM OOM)

Smoke: ненулевые боксы excavator/truck (cuda:1, conf высокие ~0.8–0.9).

## Метрики на том же diagnostic (tune 40 / diag_test 120)

| | |
|---|---|
| locked thr (tune F1) | **0.5** |
| AP50 overall | **0.404** |
| P / R / F1 | 0.275 / 0.728 / 0.400 |
| AP50 s/m/l | 0.163 / 0.389 / 0.616 |
| mean ms | 1097 |
| peak MiB | 12734 |
| device | cuda:1 |

Сильные классы (AP50): excavator 0.675, truck 0.614, pump_truck 0.731, bulldozer 0.537, loader 0.546, concrete_mixer 0.505, static_crane 0.429.  
Слабо: roller 0, pile_driver 0.021, crane 0.132. Много FP при высоком recall.

Не объявлять победителем только по diagnostic; расширенный eval для SAM в этом задании не требовался.
