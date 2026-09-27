# Журнал захваток

## 2026-09-26 — Интеграция тестовая КСГ

- Цель: закрыть блокер «evaluate пропущен: нет строки КСГ» для цепочки Observation → ActualState → Plan/Fact → Alert → решение инспектора → повторный evaluate с evidence.
- TEST KSG only (не график объекта): `validation/perception_regression/test_ksg_building_01_jan2026.csv` — `building_01`, этапы `superstructure` 2026-01-02 (floors=4) и 2026-01-06 (floors=5), `stage_label` явно «TEST KSG only — интеграция».
- БД: `SITEWATCH_DB_PATH=/tmp/sw_integ_ksg.db`. Каталог: `site_001` / `building_01` / `cam_building`. Perception: `real` (Qwen `:8001`, SAM `cuda:1`).
- Команда: `SITEWATCH_DB_PATH=/tmp/sw_integ_ksg.db .venv/bin/python validation/perception_regression/run_integration_ksg.py`
- Исход: observe `2026-01-02.jpg` → evaluate → `schedule_delay` `f13d4b6f…` (floors plan 4 / fact 0) + `insufficient_evidence`. Решение `rejected` / `false_detection`. Второй кадр (тот же календарный день, `2026-01-06.jpg` @ 18:00) → re-evaluate: evidence 1→2, событие `evidence_added`, статус/причина сохранены, fingerprint без дубля. Затем observe+evaluate `2026-01-06` (прогресс TEST КСГ 4→5).
- Отчёт: `validation/perception_regression/integration_ksg_report.json`. Blockers: нет. Это интеграция пайплайна, не precision/recall.

## 2026-09-26 — логика факта, времени и очереди

- Цель: закрыть ошибки, из-за которых неизвестность становилась нулём, а редкие кадры — сигналом об отсутствии динамики.
- Проблема: fusion записывал `0` на все классы онтологии; VLM без бокса мог пройти порог подтверждения; temporal затирал технику плохим кадром и не отличал порядок, камеру и ракурс; `no_dynamics` смотрел только на крайние даты; повторный evaluate не добавлял evidence; очередь не ограничивала зависшие GPU-задачи.
- Гипотеза: явные статусы согласия, подтверждение только по локализованному детектору и ограничение разрыва между пригодными кадрами убирают ложное «улучшение» через подавление.
- Файлы: `perception/fusion/service.py`, `perception/project.py`, `perception/dedup.py`, `perception/providers/qwen_vl.py`, `temporal/state_engine.py`, `temporal/engine.py`, `deviation/engine.py`, `inspector/workflow.py`, `pipeline/jobs.py`, `pipeline/benchmark.py`, `storage/db.py`, `config/perception.yaml`, `config/thresholds.yaml`.
- Проверка: `pytest` 101 passed. Соседние машины с малым IoU не сливаются. Кластер кадров + пауза 14 дней не даёт `no_dynamics`.
- Результат: поведение в рабочем пути. `pytest` 102 passed.
- Real, камера house6, без разметки этого прогона: `2026-01-02` SAM3 `cuda:1` 11.8 с, пик 5423 МБ из 15958; Qwen 10.3 с. Экскаватор — конфликт (детектор 2, VLM 1), в план/факт не попал. Грузовик согласован, count=1. `2026-01-06` подтвердил экскаватор 1 и mobile_crane 1; бульдозер остался неподтверждённым. Наблюдение `2026-01-02` записано в отдельную SQLite; evaluate на эту дату пропущен: нет строки КСГ. Это не precision/recall.

## 2026-09-26 — эксперимент house6_earthworks + интеграция TEST KSG

### A. Эксперимент с промптами (не интеграция)

- GT: `validation/perception_regression/gt/house6_earthworks.json` — 8 confirmed (excavator×5, truck×2, mobile_crane×1). **human_inspector_confirmed=false** (блокер для производственного эталона).
- Matching: IoU≥0.3; ambiguous/exclude не штрафуют FN/FP.
- Baseline freeze: `experiments/prompt_ab_2026-01/baseline_freeze.json` — текущие `mvp_prompts()`, `primary_prompt_only=true`, SAM `cuda:1`, imgsz 720, Qwen/fusion/temporal без изменений.
- Гипотеза: equipment-only один канонический промпт на класс (`narrow_prompts_v1.yaml`) снижает FP без потери TP.
- Критерий принятия: FP↓ при TP≥baseline по классам; конфликты SAM/Qwen — вторичная метрика; при равенстве оставить baseline.
- Результат детектора (оба варианта одинаковы после исправления неканонических paraphrases): **TP=6 FP=2 FN=2**, P=R=0.75. По классам: excavator 3/0/2, truck 2/0/0, mobile_crane 1/0/0, bulldozer 0/2/0.
- Fusion-confirmed counts не равны боксам: на `2026-01-02` excavator в конфликте → в факт не вошёл (count error 2). Overlays: `experiments/prompt_ab_2026-01/*/2026-01-0{2,6}_errors.jpg`.
- Вердикт: **keep_baseline_equal** — кандидата в прод не принимать. Holdout не открывался. Обучение не запускалось.

### B. Интеграция с тестовой КСГ (не реальный график)

- Скрипт: `validation/perception_regression/run_integration_ksg.py`, CSV `test_ksg_building_01_jan2026.csv`, отчёт `integration_ksg_report.json`, БД `/tmp/sw_integ_ksg.db`.
- Цепочка: real observe `2026-01-02` → evaluate → `schedule_delay` (TEST floors=4 vs факт 0) → решение `rejected/false_detection` → повторный observe/evaluate того же эпизода → **решение сохранено**, evidence 1→2.
- Дополнительно проверено: `persist_candidate` с тем же fingerprint дописывает evidence и не создаёт новую карточку.
- Явная метка: «TEST KSG only — не график объекта».

## Не повторять


- Synthetic scale на house6 не улучшил recall. Доменный эксперимент: 13 train / 28 объектов, февральский val 6 кадров / 9 объектов, осенний holdout 8 кадров / 3 объекта. Recall ~0.42 и 0. Это та же камера, не другая площадка. Holdout уже просмотрен — не использовать как закрытую оценку.
