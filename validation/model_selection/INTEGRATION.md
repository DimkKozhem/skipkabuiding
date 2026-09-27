# Интеграция в ObservedState / WorkFact

Это проект подключения, не внедрение. Продуктовые факты, сигналы, решения инспектора и UI этим циклом не менялись.

## Что уже есть в runtime

- Qwen3-VL-8B на `127.0.0.1:8001` пишет предложение `visible_floor_levels`. `structural_levels` ставится только при `floors_status=proven`.
- SAM 3.1 на `cuda:1` даёт боксы по промптам онтологии. Наличие бокса не завершает работу.
- Grounding DINO в `config/perception.yaml` выключен, а провайдер при наличии пакета возвращает `grounding_dino_no_weights` и не читает скачанный `model.safetensors`.
- Harness `sitewatch vlm-compare` не пишет SQLite, WorkFact и алерты.

## Что понадобится, если shortlist подтвердится

1. Контракт ответа: `count | unknown | not_applicable`, видимость, основания, отдельные признаки работ и техники. Плановые числа в промпт не попадают.
2. Для точек MolmoPoint — вызов `extract_image_points`, затем перевод координат в исходный кадр. Свободный текст координатами не считается.
3. Для YOLOE — отдельный экспериментальный адаптер. AGPL не смешивать с текущим Apache-контуром без решения.
4. Экспорт в WorkFact только сухим прогоном маппинга, после human verification. Пока маппинг не запускался.
5. Смена `/api` не требуется, пока ObservedState не меняется.

## Прогоны 2026-09-27

Baseline Qwen, SAM 3.1 и Grounding DINO посчитаны в каталогах экспериментов. Их ответы не записаны в ObservedState и WorkFact. OpenRouter smoke (ledger) тоже не писал продукт. Победитель не выбран — новый адаптер не подключать.

Сырой текст Qwen содержит `completion=complete`. В факт это поле переносить нельзя: наличие признака и завершение работы остаются разными статусами.

DINO experimental baseline шёл из `myenv` (в `.venv` не было transformers). Product path от этого не менялся.

## Что изменено аудитом (конфиг эксперимента, не продукт)

- `EXPERIMENT_PROTOCOL.md` v2, `manifest.json` v2, `EXPERIMENT_AUDIT.md`, `AGENT_TASKS.md`, `LABELING_PACKET.md`.
- Pin OpenRouter: `config/vlm_compare_openrouter_pinned.yaml` (+ reasoning_off).
- Production `config/perception.yaml`, БД и UI не менялись.
