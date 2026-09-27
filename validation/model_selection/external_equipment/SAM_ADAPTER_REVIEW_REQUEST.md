# Запрос на ревью: SAM-адаптер (experiment → product owner)

Дата: 2026-09-27. **Production пока не менять.**

## Что сломалось в эксперименте

В диагностическом раннере MOCS использовался путь:

`ultralytics.SAM(ckpt).predict(..., texts=prompts)`

без явного `SAM3SemanticPredictor.setup_model` / `set_image`.  
`forward_grounding` ожидает `language_features` из `self.text_embeddings` (заполняется через `set_classes` ← text). При пустых embeddings → `KeyError: language_features`.

Экспериментальный фикс только в  
`validation/model_selection/external_equipment/scripts/run_mocs_sam_diagnostic.py`  
(setup_model + set_image + box-only grounding). Строка `text_embeddings = {}` — инициализация атрибута до `set_classes`, не заглушка ради метрик.

## Product-адаптер (не патчен)

Файл: `src/sitewatch/perception/providers/sam3.py` (`Sam3Provider`).

Уже другой путь: `SAM3SemanticPredictor` → `set_image` → `predictor(text=chunk)`.  
Это **не** тот же `SAM.predict(texts=)`, на котором упал experiment harness.

Проверить владельцу (без обязательного патча сейчас):

1. В `_try_load` стоит `_ = predictor.model` — в ultralytics 8.4.146 атрибут может остаться `None`, пока не вызван `setup_model`. Убедиться, что `set_image` / первый `text=` гарантированно поднимают модель (baseline `sam31_baseline` ранее отрабатывал — но явная `setup_model` безопаснее).
2. Нет ли других experiment/скриптов с `SAM(...).predict(texts=)`.
3. Не переносить box-only decode в production без отдельной задачи (product сейчас идёт через полный postprocess с масками).

## Итог для product

Не утверждается, что в production есть тот же KeyError. Утверждается: баг экспериментального harness подтверждён; product API ближе к рабочему пути — нужна точечная проверка `setup_model`, без смены `config/perception.yaml` в рамках model-selection.
