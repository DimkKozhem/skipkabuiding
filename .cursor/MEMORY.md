# Скрипка — memory

Продукт: **Скрипка**, контроль строительства. Пакет кода — `sitewatch`.

## Назначение

Скрипка показывает инспектору план (график объекта → `ExpectedState`), факт по фото/видео (`ActualState`), отклонение, evidence и что проверить. Не видеонаблюдение и не юридический вердикт. CV меняет наблюдаемый факт/сигнал; решение — инспектор.

## Perception MVP (2026-09-23)

- Цепочка: Image → `ObservedState` → TemporalStateEngine → `ActualState` → PlanFactEngine.
- Пакет `src/sitewatch/perception/`; онтология `config/construction_ontology.yaml`; режим `SITEWATCH_PERCEPTION_MODE=annotation|real|full`.
- Docs: `docs/perception_mvp.md`. `not_visible ≠ absent`; persistent не затирается плохим кадром.
- Real E2E (проверено): SAM3 ultralytics + Qwen3-VL-8B (OpenAI shim `scripts/qwen_vl_openai_server.py` при конфликте vLLM/transformers). GPU split: Qwen→3090, SAM→4060 Ti. `timm` обязателен. SAM `imgsz=720`, `prompt_batch_size=4`.
- Smoke: `sitewatch analyze … --mode real` на `building_01`; benchmark `validation/perception` precision/recall=1.0 на demo-кейсе. pytest annotation: 75 passed.

## Границы

- CV → `Detection` / `ObservedState` / `ActualState`. КСГ/график объекта → `ExpectedState`. Слои не ходят в обход контракта.
- DeviationEngine не импортирует YOLO. Frontend не считает правила.
- `/api` — контракт UI↔backend. Медиа — `/media`. SQLite MVP.
- `no_dynamics`: ΔS≈0 + КСГ движется + N дней. Текст: «Выявлены признаки отсутствия строительной динамики. Требуется проверка.»
- Этажность — из `scene.floors` / VLM `visible_floor_levels`, не из count `slab`/`floor_slab` боксов (SAM фрагментирует фасад). Annotation без sidecar → ошибка, не пустой успех. Таймлапсы с выключенной камерой: `playback_mode=historical` (не stale от wall-clock).
- Этажи: `visible_floor_levels` = proposed наблюдение кадра; `structural_levels` только при `floors_status=proven` (не max неподтверждённых чисел). Эксперимент localize→bands: `validation/perception_regression/experiments/floors_localize_run/` + `docs/engineering/floors_localize_experiment.md`. На доме commercial L1 находится; office-контроль пока пересегментирует — одного VLM недостаточно для confirmed этажности.
- Key-frame recompute: `validation/perception_regression/recompute_timelapse_facts.py` + отчёт `timelapse_recompute_report.json` / `docs/engineering/timelapse_facts_report.md`.
- Demo не подменять новой архитектурой: `zone_a` NORMAL; `zone_b` `missing_equipment`; `building_01` `no_dynamics` + `schedule_delay`.

## Где что лежит

- Backend: `src/sitewatch/` (FastAPI `api/main.py`, CLI `cli.py`).
- Frontend: `frontend/src/` (React + Vite, CSS variables, без UI-kit). UI только `:8000`.
- Конфиг: `config/*.yaml`. Demo: `data/demo/`. БД: `data/observations/sitewatch.db`.
- Python: `LCT2026/.venv/bin/python`.
- Канон продукта/UI: `.cursor/PRODUCT.md`, `.cursor/FRONTEND.md`.

## Команды

```bash
cd /home/dimk/my_project/LCT2026
source .venv/bin/activate
sitewatch seed-demo
sitewatch ui                 # :8000
# cd frontend && npm run dev  # :5173, proxy /api и /media
.venv/bin/python -m pytest -q
cd frontend && npm run build
```

Детектор по умолчанию — `annotation`. YOLO: `SITEWATCH_DETECTOR=yolo` + веса в `models/` или `SITEWATCH_YOLO_WEIGHTS`. Без весов — `FileNotFoundError`.

Интеграция TEST КСГ (не график объекта): `SITEWATCH_DB_PATH=/tmp/sw_integ_ksg.db .venv/bin/python validation/perception_regression/run_integration_ksg.py` — observe→plan/fact→alert→decision→re-evaluate; отчёт `validation/perception_regression/integration_ksg_report.json`.

## Demo (site_001 / «ЖК Северный»)

| Зона | Факт | Сигнал |
|------|------|--------|
| `zone_a` | excavator=1, dump_truck=3 | NORMAL |
| `zone_b` | dump_truck=0, expected min=2 | `missing_equipment` |
| `building_01` | факт 4 этажа; КСГ 4→5→6 (01/08/15/22.09) | `no_dynamics`, `schedule_delay` |

CV demo: annotation sidecar. YOLO adapter есть, production-весов нет. SAM2/DINOv2/OCR — слоты. Demo media синтетическое.

## Приоритет

frontend/UX → real ingest → real CV → real КСГ.

Не трогать без задачи: микросервисы, k8s, PostgreSQL, BIM, VLM-вердикт, новый CV stack.

---

## Canon — 2026-09-23 (object workspace tabs)

- Стартовый sidebar везде: логотип, Объекты, + Добавить объект, Информация о проекте. Без второго sidebar объекта.
- В объекте вкладки в шапке: Обзор, Камеры (`sources`), План-факт (`progress` + график по кнопке), Хронология (`history`), Сигналы (`signals`). Заметки/настройки — ссылки в шапке.
- Витрина: фото-карточки с планом/фактом из API (этажи/техника), без выдуманных %.
- Удалены `JsonBlock` / `TechnicalDetails`. Enum в UI через `labels.ts`.

## Canon — 2026-09-22 (inspector workspace)

- Шапка: знак «Скрипка», строка «Контроль строительства», «Объекты», «Добавить объект», «О проекте».
- Создание объекта: `/objects/new` — имя, описание, вид из `GET /api/catalog/construction-types`.
- Навигация: старт `/objects` (фото-витрина); глобальный sidebar — Объекты `[+]` и Информация о проекте; внутри объекта — OBJECT_NAV (`routes.ts`). Обложка карточки = `preview_url` с API.
- DGP: `src/sitewatch/catalog/construction.py` → construction-types / works. `GET /api/catalog/stages` без изменений.
- Zone: `description`, `construction_type_id`. Заметки: `zone_notes`.
- Object workspace: plan-item, ObserveForm в объекте, KsgEditor (import + справочник с датами), SourcePanel с русским 409.
- Витрина: tier 3 = прочие open; `ksg[].current` с backend.
- xlsx ≠ КСГ. Demo zone_a / zone_b / building_01 сохранены.
- localStorage: `sitewatch.project`, `sitewatch.inspector`. Aliases `/queue` и др. — redirects.

## UI и исходные данные — 21.09.2026

- Рабочее место инспектора: ingest `/observe`, контекст площадки/инспектора, сигналы на `/signals` (не alias `/queue`), календарь КСГ, честный demo-баннер. Карта — `.cursor/FRONTEND.md`.
- Additive API: `cameras`, `last_source`, `actor_default`, `/alerts?project=`, `POST /observations/upload`. Frontend `WorkspaceProvider`, без Redux.
- Frontend: `typecheck` + presentation tests (Node 22). Решения инспектора в browser QA не писать в рабочую SQLite.
- `ТЗ /Датасет /7.ДГП_датасеты/Сводный перечень строительных работ_ЛТЦ.xlsx` — справочник видов работ; API читает через `catalog/construction.py`.

## Техника и изменения — 21.09.2026

- Observe считает технику: фото — боксы или уникальные треки; видео — `class_counts` окна, не сумма кадров.
- Evaluate пишет переход. Timeline отдаёт `change`: дельты техники и конструктива. Сдвиг техники не отменяет стабильность конструктива для `no_dynamics`.
- Карточка объекта: «Техника и изменения».

## Операционный контур — 21.09.2026

- Площадка/объект/источник/график заводятся через `/setup` и вкладки объекта «График» / «Источники» (CURRENT; не TARGET-wizard).
- Камера: `uri`, `enabled`, `interval_minutes` (5–1440, default 30), `last_captured_at`, `last_error`. Пустой `uri` не снимается.
- Цикл съёмки в `sitewatch ui` (`SITEWATCH_CAPTURE_LOOP=1`): тик ~20 с, кадр если прошёл интервал. Pytest: цикл выключен.
- Нет КСГ на дату — observe всё равно пишется, evaluate пропускается, ошибка в `last_error`.
- Удаление камеры с наблюдениями → 409, только отключение.
