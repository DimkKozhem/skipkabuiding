---
name: improve-sitewatch-ui
description: Improve Скрипка React inspector UX against live demo API. Use when editing frontend pages, layout, evidence, queue, or plan/fact UI.
disable-model-invocation: true
---

# improve-sitewatch-ui

Инспекторский интерфейс, не generic dashboard. Карта факта: [FRONTEND.md](../../FRONTEND.md).

Не менять domain / FastAPI / CV в этом цикле, если задача только про UI. Не подключать новый UI framework. Не подменять API mock-данными.

**Живые маршруты** (правки только здесь): `/`, `/signals`, `/objects`, `/objects/:zoneCode`, `/observe`, `/setup`.  
`/housing` — experimental, не раздувать.  
Aliases `/alerts` `/inspect` `/queue` `/dashboard` `/object` `/timeline` — redirects, не главные экраны и не место для новой вёрстки.

## Три уровня работы

На каждом уровне явно разделяй **CURRENT** (что править сейчас) и **TARGET** (куда двигать UX). Не редактируй несуществующие страницы и не выдумывай URL.

### 1. Overview / projects

| | |
|--|--|
| **CURRENT** | Sidebar в `Layout.tsx`: Обзор `/`, Сигналы `/signals`, Объекты `/objects`, Корпус 16 `/housing` (experimental), Кадр `/observe`, Площадка `/setup`. Project select, если проектов > 1. localStorage: `sitewatch.project`, `sitewatch.inspector`. |
| **TARGET** | Sidebar = операционный реестр площадок/проектов: список, вертикальный scroll, поиск, переключение, выбранный проект виден, действие создания объекта. Не admin-console, не список API, не стена камер, не дерево сущностей. |

Запрос «переделай sidebar» → менять текущий `Layout` в сторону реестра, не добавлять туда все сущности системы. `/housing` не становится каноном TARGET.

### 2. Object creation

| | |
|--|--|
| **CURRENT** | `/setup` — площадка и CRUD объектов (zone), ссылки на график/источники объекта. Это не целевой мастер. |
| **TARGET** | Доменный сценарий (URL wizard не фиксировать): описание объекта → вид строительства → поля по виду → источники → загрузить существующий график **или** создать график на базе работ выбранного вида → открыть workspace объекта. |

Вид строительства определяет доступные работы. API справочника видов ещё нет. Не хардкодить отраслевые поля в React. Не считать xlsx ДГП уже подключённым к API.

### 3. Object workspace

| | |
|--|--|
| **CURRENT** | `/objects/:zoneCode`, вкладки `?tab=`: `state` (default, «Состояние»), `schedule` (KsgEditor), `sources` (SourcePanel), `history`, `evidence`. |
| **TARGET** | Единое рабочее окно: график, источники, фото, заметки, история, evidence, исполнение пунктов плана. Заметки и tracker исполнения — ещё не отдельные сущности. Не выдумывать их страницы. |

Запрос «переделай ObjectPage» → фактический `ObjectPage` и вкладки выше, не `/queue` `/dashboard` `/timeline`.

## Plan / fact / решение

- Plan (график → `ExpectedState`) и fact (наблюдение/CV → `ActualState`) — визуально и семантически разные. Frontend не считает доменный verdict.
- CV даёт признак/сигнал. Решение инспектора: `confirmed` / `rejected` / `needs_more_data` на `/signals` (`api.alerts` / decision, не `/api/queue`).
- Одна страница — один сценарий.
- Язык: «признаки», «возможное отклонение», «требуется проверка». Не «строительство остановлено».
- Demo не подменять: `zone_a` / `zone_b` / `building_01`. Annotation sidecar не выдавать за prod ML.

## Цикл

```text
1. поднять demo;
2. открыть UI;
3. пройти живые маршруты;
4. найти UX-проблемы;
5. посмотреть API/data contracts;
6. внести изменения (CURRENT → TARGET уровня задачи);
7. снова открыть UI;
8. проверить demo scenarios;
9. проверить responsive layout;
10. build/test.
```

## Как выполнять шаги

1. `cd /home/dimk/my_project/LCT2026 && source .venv/bin/activate && sitewatch seed-demo`
2. `sitewatch ui` → `http://127.0.0.1:8000` (dev: `sitewatch api` + `cd frontend && npm run dev` на `:5173`).
3. Страницы: `/` (обзор), `/signals` (очередь и разбор), `/objects`, `/objects/:zoneCode` (вкладки), `/observe`, `/setup`. Aliases не открывать как целевые экраны.
4. Смотреть, объясняется ли plan vs fact vs evidence vs «что проверить». JSON и технические id не должны быть главным.
5. Контракт: `frontend/src/api.ts`, `types.ts`, `src/sitewatch/api/main.py`, `services/queries.py`. Поля только с backend.
6. Правки в существующих pages/components/`styles.css` / `Layout.tsx`. Один главный сценарий на страницу.
7. Снова открыть те же экраны (браузер MCP `cursor-ide-browser` или Playwright, если доступны). Скриншот ≠ проверка потока.
8. Demo: `zone_a` NORMAL; `zone_b` `missing_equipment`; `building_01` `no_dynamics` + `schedule_delay`. Формулировка no-dynamics: «Выявлены признаки отсутствия строительной динамики. Требуется проверка.»
9. Desktop и узкая ширина (`styles.css`: 1100px / 800px). Ориентир: 1440×900 и 1280×800.
10. `cd frontend && npm run build`. Presentation: `npm test` (если трогали presentation/helpers). Если трогали контракт — `.venv/bin/python -m pytest -q`.
