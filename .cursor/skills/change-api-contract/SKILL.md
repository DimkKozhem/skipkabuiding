---
name: change-api-contract
description: Change Скрипка /api DTO safely across FastAPI, queries, frontend types/client, and pytest. Use when adding, renaming, or removing API fields or routes.
disable-model-invocation: true
---

# change-api-contract

`/api` — контракт UI и тестов. Не менять «заодно». Нет поля на backend — frontend его не выдумывает.

## Consumers (все)

| Слой | Файлы |
|------|--------|
| Routes / In-модели | `src/sitewatch/api/main.py` |
| DTO | `src/sitewatch/services/queries.py`, при решении — `inspector/workflow.py` |
| Catalog layer | `src/sitewatch/services/catalog.py` и связанные queries |
| Домен (если торчит в JSON) | `src/sitewatch/domain/contracts.py` |
| Frontend client | `frontend/src/api.ts` |
| Frontend types | `frontend/src/types.ts` |
| Рендер | `frontend/src/pages/*`, `frontend/src/components/*`, `labels.ts` |
| Тесты | `tests/test_api.py`, при пайплайне — `tests/test_e2e.py` |

Медиа URL только через `public_media_url` → `/media/...`.

## Каталог видов / работ

**Изменение источника каталога требует сквозной проверки: producer → DTO → API → client types → UI consumer.**

| Факт | Статус |
|------|--------|
| `GET /api/catalog/stages` ← `config/equipment_rules.yaml` | **CURRENT** (MVP) |
| DGP xlsx (`ТЗ /Датасет /7.ДГП_датасеты/Сводный перечень строительных работ_ЛТЦ.xlsx`) | будущий справочник видов/наименований работ; API **не читает**; **not implemented yet** |
| Import графика через `parse_ksg` | отдельный контракт графика объекта; **xlsx ≠ КСГ** / ≠ подключение справочника |
| `ExpectedState` | только от графика объекта; сроки **не** генерировать из справочника |
| CV | смена каталога **не** даёт CV права окончательного вердикта |

Если позже появится API вокруг xlsx-справочника работ — контракт ещё не определён: сначала зафиксировать DTO и потребителей. **Не** писать endpoint / JSON-схему / пример ответа несуществующего API как спецификацию к реализации.

Сквозная проверка consumers при смене каталога:

1. `src/sitewatch/api/main.py`
2. `sitewatch/services/catalog.py` и связанные queries
3. backend DTO
4. `frontend/src/types.ts`
5. `frontend/src/api.ts`
6. frontend consumers (фактические импортёры: KsgEditor, Setup, ObjectPage и др.)
7. pytest / API contract tests

## Порядок

1. Зафиксировать: add / rename / remove поля или маршрута; какие страницы читают.
2. Изменить backend (queries + router). Не размазывать ту же форму по React.
3. Обновить `types.ts` и вызовы в `api.ts` / pages.
4. Обновить pytest. Для demo-полей — сценарии zone_a / zone_b / building_01.
5. `.venv/bin/python -m pytest tests/test_api.py -q` затем полный pytest.
6. `cd frontend && npm run build`.
7. Если поле видит инспектор — открыть UI и проверить, что старый экран не сломан.

## Не делать

- Параллельный «удобный» JSON только для UI, дублирующий deviation payload.
- Ломать `POST /alerts/{id}/decision` (нужна причина из `config/inspector.yaml`).
- Отдавать sidecar/predictions как будто это другой продукт; UI может показать `model_name` как metadata.
- Описывать DGP xlsx как уже подключённый каталог API.
- Генерировать сроки объекта из справочника работ.
