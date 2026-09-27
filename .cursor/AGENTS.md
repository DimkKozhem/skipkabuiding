# Скрипка — индекс агента

Канон этого файла совпадает с корневым [`AGENTS.md`](../AGENTS.md).  
Память: [MEMORY.md](MEMORY.md). Продукт: [PRODUCT.md](PRODUCT.md). Карта UI: [FRONTEND.md](FRONTEND.md). MCP: [MCP.md](MCP.md).

Python только `LCT2026/.venv`. Не `myenv`. Не трогать CaseDetect / MVD / sam2 без явной задачи.

## Product

**Скрипка** — контроль строительства: сопоставить **план** (график объекта → `ExpectedState`) с **фактом** (наблюдение / CV → `ActualState`) и дать инспектору объяснимый сигнал.

Ценность не в «дашборде камер» / camera wall, а в цепочке:

> площадка → объект → источники → график → наблюдение → plan/fact → сигнал → решение инспектора

Детали сущностей и CURRENT/TARGET: [PRODUCT.md](PRODUCT.md). Карта экранов: [FRONTEND.md](FRONTEND.md).

Система **не** пишет юридические вердикты («строительство остановлено», «подрядчик нарушил сроки», «объект не соответствует проекту»).  
Корректно: «обнаружены признаки», «возможное отклонение», «требуется проверка», «нет наблюдаемой динамики за период».  
Решение принимает инспектор на `/signals` (`confirmed` / `rejected` / `needs_more_data` + причина из `config/inspector.yaml`).

## Продуктовый канон (CURRENT / TARGET)

**CURRENT (реализовано):**

- Sidebar: Обзор `/`, Сигналы `/signals`, Объекты `/objects`, Корпус 16 `/housing` (experimental), Кадр `/observe`, Площадка `/setup`.
- Объект: `/objects/:zoneCode` — вкладки `state` / `schedule` / `sources` / `history` / `evidence` (default `state`).
- Площадка и CRUD объектов: `/setup` (не TARGET-wizard).
- Каталог этапов MVP: `GET /api/catalog/stages` ← `config/equipment_rules.yaml`.
- График объекта → `ExpectedState`. Наблюдение/CV → `ActualState`. Plan/fact deviation → Alert. Инспектор: `/signals`.
- Aliases `/queue` `/dashboard` `/alerts` `/inspect` `/timeline` — redirects, **не** главные экраны.
- Отдельной сущности «исполнение пункта плана» **нет** (есть plan/fact + deviation).

**TARGET (ещё не реализовано):**

- Sidebar = реестр площадок/проектов (не меню технических экранов, не стена камер).
- Создание объекта начинается с **вида строительства**; `/setup` этим сценарием не подменять.
- Справочник работ = `ТЗ /Датасет /7.ДГП_датасеты/Сводный перечень строительных работ_ЛТЦ.xlsx` — API **не читает**.
- График объекта отдельно от справочника; сроки **только** из графика (нет графика — не выдумывать).
- Единое рабочее окно объекта; CV даёт **признак** исполнения, не окончательное «выполнено».

**Явно:** xlsx ДГП ≠ КСГ. `ExpectedState` = производная **конкретного графика объекта**. CURRENT = plan/fact deviation; TARGET = признак исполнения + решение инспектора.

## Core loop

```text
график объекта (КСГ) → ExpectedState
фото/видео → Detection → Observation → ActualState
Temporal (ΔS во времени)
Plan/Fact → Deviation → Alert → Evidence
/signals → решение инспектора
```

Контракт слоёв: CV эмитит `Detection` / `ActualState`. КСГ/график эмитит `ExpectedState`.  
Пакет: `src/sitewatch/`. Правила стройки — `config/*.yaml`, не хардкод.

## Architecture boundaries

- CV не знает КСГ и не импортирует deviation/inspector.
- DeviationEngine не зависит от YOLO / ultralytics; работает с `ActualState` + `ExpectedState`.
- Frontend не считает бизнес-правила и не выдумывает backend state.
- HTTP `/api` — контракт между UI и backend. Медиа — `/media`.
- Решение инспектора не заменяется automatic verdict / VLM.
- SQLite MVP. Не мигрировать на PostgreSQL «на будущее».

## Current product priorities

1. frontend / UX (операционный интерфейс инспектора);
2. ingest реальных фото/видео;
3. подключение реального CV;
4. реальная КСГ.

Не приоритет: microservices, Kubernetes, PostgreSQL, BIM/digital twin, новый CV framework, VLM-вердикт, глобальная перекладка архитектуры.

CV сейчас частично demo: рабочий backend — `annotation` (sidecar JSON). YOLO-адаптер есть, весов construction-модели в репо нет. SAM2 / DINOv2 / OCR — слоты. Синтетическое demo media и sidecar **нельзя** выдавать в UI как production ML; источник можно показать как metadata/debug, не превращая экран в developer console.

## Карта кода

| Путь | Роль |
|------|------|
| `src/sitewatch/domain/` | `ActualState`, `ExpectedState`, `Detection`, enums |
| `src/sitewatch/cv/` | адаптеры → `Detection`; агрегация → `ActualState` |
| `src/sitewatch/ksg/` | парсер КСГ → `ExpectedState` |
| `src/sitewatch/temporal/` | ΔS, `no_dynamics` (не нейросеть «остановка») |
| `src/sitewatch/deviation/` | plan/fact правила → `DeviationCandidate` |
| `src/sitewatch/evidence/` | привязка кадров к сигналу |
| `src/sitewatch/inspector/` | очередь, fingerprint/dedup, решение, brief |
| `src/sitewatch/pipeline/` | seed / observe / evaluate |
| `src/sitewatch/api/main.py` | FastAPI `/api` + SPA `frontend/dist` |
| `src/sitewatch/storage/` | SQLAlchemy + SQLite |
| `src/sitewatch/services/queries.py` | DTO для UI |
| `frontend/` | React + Vite, без UI-kit |
| `config/` | таксономия, пороги, техника, инспектор |
| `tests/` | pytest (изолированный SQLite) |

## Rules / skills / субагенты

Rules: `lct2026-core` + `sitewatch-architecture|backend|frontend|testing` + доменные `lct2026-cv|temporal|ksg|python`.

Skills — ручной `/skill` (`disable-model-invocation: true`):

| Skill | Когда |
|-------|--------|
| [improve-sitewatch-ui](skills/improve-sitewatch-ui/SKILL.md) | UX/UI React |
| [change-api-contract](skills/change-api-contract/SKILL.md) | смена `/api` DTO |
| [test-runner](skills/test-runner/SKILL.md) | pytest |
| [seed-demo](skills/seed-demo/SKILL.md) | пересобрать demo |
| [grill-me](skills/grill-me/SKILL.md) | неясные требования |

Субагенты: `verifier`, `debugger`, `cv`, `temporal`.

## Verification

Перед завершением задачи:

```bash
cd /home/dimk/my_project/LCT2026
.venv/bin/python -m pytest -q
```

Frontend (нет отдельного lint/test — есть build):

```bash
cd frontend && npm run build
```

Если менялся пайплайн или UI опирается на demo:

```bash
sitewatch seed-demo
sitewatch ui          # http://127.0.0.1:8000
```

Проверить сценарии: `zone_a` NORMAL; `zone_b` `missing_equipment`; `building_01` `no_dynamics` + `schedule_delay`.  
Формулировка no-dynamics: «Выявлены признаки отсутствия строительной динамики. Требуется проверка.»

Коммиты / push — только по просьбе.
