# Скрипка — контроль строительства

Скрипка сопоставляет **план** объекта (график → `ExpectedState`) с **наблюдаемым фактом** (фото, видео или CV → `ActualState`) и показывает инспектору объяснимый сигнал. Решение принимает человек: `confirmed`, `rejected` или `needs_more_data`.

Система не выносит юридические и управленческие вердикты. Корректный язык сигнала: «признаки», «возможное отклонение», «требуется проверка».

Пакет кода — `sitewatch`. Это пилот, не production-контур CV.

## Ограничения текущего пилота

- Рабочий путь наблюдения — детектор `annotation` (sidecar JSON). Режим `SITEWATCH_PERCEPTION_MODE=real` (SAM3, опциональный Grounding DINO, Qwen-VL) — эксперимент. Метрики на demo-кейсе не являются качеством production-модели.
- Веса YOLO, SAM, CLIP и чекпоинты в git не входят. Без локальных весов YOLO-адаптер завершается ошибкой, а не тихим успехом.
- Теневые кандидаты (`model_candidate`) по умолчанию выключены. Это не подтверждённый факт и не отклонение от графика.
- Сроки берутся только из графика конкретного объекта. Справочник работ ДГП графиком не является. Нет графика — сроки не выдумываются.
- База пилота — SQLite. Исходные фото, видео и архивы датасетов в репозиторий не входят.
- Синтетические кадры `data/demo` нужны, чтобы воспроизвести demo-сценарии. Это не съёмка реальной площадки и не обученная модель.

## Состояние пилота

После `sitewatch seed-demo` на площадке `site_001`:

| Зона | Наблюдение | Сигнал |
|------|------------|--------|
| `zone_a` | excavator=1, dump_truck=3 | отклонений по технике нет |
| `zone_b` | dump_truck=0 при ожидаемом минимуме 2 | `missing_equipment` |
| `building_01` | факт держится на 4 уровнях, график двигается 4→5→6 | `no_dynamics` и `schedule_delay` |

Формулировка отсутствия динамики: «Выявлены признаки отсутствия строительной динамики. Требуется проверка.»

Интерфейс инспектора: витрина `/objects`, карточка объекта, сигналы `/signals`. Экспериментальный срез корпуса 16 — `/housing`, он не заменяет основной контур.

## Установка

Нужны Python 3.10+ (проверено на 3.12) и Node.js 22.

```bash
cd /path/to/skipkabuiding
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cd frontend && npm ci && cd ..
```

Зависимости backend заданы минимальными версиями в `pyproject.toml` и `requirements.txt`. Это не полный `pip freeze` экспериментальных окружений (`.venv-yoloworld`, `.venv-countgd`). Frontend фиксируется `frontend/package-lock.json`.

Опционально, только если локально есть GPU и веса:

```bash
pip install -e ".[cv,perception-sam]"
```

## Запуск и тесты

```bash
cp .env.example .env
source .venv/bin/activate
sitewatch seed-demo
sitewatch ui
```

Приложение: `http://127.0.0.1:8000`.

Разработка UI отдельно:

```bash
sitewatch api
cd frontend && npm run dev
```

Проверки без GPU и без платных API:

```bash
.venv/bin/python -m pytest -q
cd frontend && npm test && npm run build
```

## Переменные окружения

Шаблон — `.env.example`. Секреты в `.env` не коммитятся.

| Переменная | Зачем |
|------------|--------|
| `SITEWATCH_DB_PATH` | путь к SQLite; пусто — `data/observations/sitewatch.db` |
| `SITEWATCH_DETECTOR` | `annotation` (по умолчанию) или `yolo` |
| `SITEWATCH_YOLO_WEIGHTS` | файл весов вне git |
| `SITEWATCH_PERCEPTION_MODE` | `annotation` или экспериментальный `real` |
| `SITEWATCH_SAM3_*`, `SITEWATCH_QWEN_VL_*`, `SITEWATCH_GROUNDING_DINO_*` | локальные модели и endpoint VLM |
| `SITEWATCH_SHADOW_CANDIDATES` | `0` выключает теневые кандидаты |
| `SITEWATCH_CONSTRUCTION_XLSX` | локальная копия справочника ДГП |
| `OPENROUTR_KEY` | ключ только для платных VLM-сравнений; имя как в `config/vlm_compare*.yaml` |

## Модели и внешние данные

В git нет весов, HF-кэша, архивов датасетов, полевых фото и видео, рабочей SQLite.

- YOLO: положить `yolo26m.pt` в `models/` или задать `SITEWATCH_YOLO_WEIGHTS`. См. `models/README.md`.
- SAM3: скачать чекпоинт отдельно и указать `SITEWATCH_SAM3_CHECKPOINT`. В репозитории остаётся только документация `docs/perception_mvp.md`.
- Qwen-VL: отдельный локальный OpenAI-совместимый сервер, не часть `pip install` этого проекта. Скрипт-шим: `scripts/qwen_vl_openai_server.py`.
- Справочник работ: файл ДГП хранить локально и передать через `SITEWATCH_CONSTRUCTION_XLSX`.
- Протоколы отбора моделей и скрипты прогонов лежат в `validation/`. Кадры, оверлеи и веса прогонов в снимок не входят.

## Подтверждённый факт и теневые кандидаты

**Подтверждённый факт** — `ActualState`, который observe записывает из annotation или из основного perception-контура. Plan/fact сравнивает его с `ExpectedState` и может открыть сигнал отклонения.

**Теневой кандидат** — боксы дополнительной модели (Grounding DINO, YOLOE). Они пишутся как сигнал `model_candidate` с формулировкой «обнаружены признаки объектов на кадре» и **не** меняют сохранённый факт и **не** считаются отклонением от графика. Инспектор закрывает карточку; решение кандидата в факт не переносит.

Пока `config/shadow_candidates.yaml` содержит `enabled: false`, кадр идёт прежним путём observe → факт.

## Документация

Продуктовая документация (обычным языком):

- [Оглавление docs](docs/README.md)
- [О продукте](docs/product/overview.md)
- [Как это работает](docs/product/how-it-works.md)
- [Экраны](docs/product/screens.md)
- [Сценарии](docs/product/scenarios.md)
- [Что готово и что дальше](docs/product/status.md)
- [Язык сигналов](docs/product/language.md)

Для разработки и агентов:

- Канон продукта: `.cursor/PRODUCT.md`, `AGENTS.md`
- Perception: `docs/perception_mvp.md`
- Инженерные протоколы: `docs/engineering/`
- Правила стройки: `config/*.yaml`
