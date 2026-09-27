# Протокол отбора (v2)

Версия: `model-selection-protocol-2026-09-27-v2`.  
Предыдущая версия сохранена: `EXPERIMENT_PROTOCOL.v1.md` (sha256 в `AUDIT_BASELINE_HASHES.txt`).

Критерии matching и gate ниже зафиксированы **до** новых сравнительных прогонов после аудита.  
Часть чисел из уже просмотренных smoke (локальный Qwen, SAM, DINO, YOLOE, OpenRouter на `s-dev-earth-1`) **не** используется как независимый тест. Если порог опирается на уже виденный кадр — это diagnostic, не verification.

## Задачи

Отдельные решения, без универсального победителя:

1. Этажность видимых надземных уровней целевого корпуса.
2. Окна и проёмы. Окно не равно проёму. Сравнение с этажами не смешивается.
3. Видимые признаки работ: фасад, кровля, котлован, фундамент, разделитель. Признак не означает завершение. Метры без калибровки не измеряются.
4. Техника как ресурс, не как выполнение работы.
5. Динамика: появление, изменение, отсутствие видимых изменений, несопоставимость кадров. Разрыв в днях не является непрерывным видео.
6. Режим: локальный или удалённый.

Perception не получает плановые количества и сроки. `unknown` не становится 0. Пустая видимая зона может подтверждать отсутствие объекта. Пустой ответ модели — нет. Ранний котлован не обязан давать число этажей. Повтор одной ошибки не подтверждение. Согласие моделей не эталон.

Индикаторы и запрещённые выводы: `manifest.json` → `indicator_meanings`.

## Статусы кандидата (техника ≠ качество)

| статус | смысл |
|---|---|
| `sources_verified` | Код/веса/статья/лицензия проверены по URL; inference не обязателен |
| `download_incomplete` | Загрузка весов идёт или оборвалась; checkpoint не готов |
| `weights_verified` | Локальный файл/ревизия сверены; inference ещё нет |
| `smoke_passed` | Настоящий inference на разрешённом кадре прошёл (или честно дал 0 боксов / отказ) |
| `truncated` / `unsupported` / `http_error` | Эксплуатационный исход smoke, не оценка качества |
| `run_complete_no_gt` | Полный прогон по манифесту есть, human GT нет → accuracy не считается |
| `evaluated` | Есть human GT с `counts_toward_accuracy=true` и посчитанные метрики |
| `blocked` / `rejected` | Кандидат остановлен или исключён |

Запрещено писать `evaluated`, если нет human GT. Прогон Qwen/SAM/DINO 2026-09-27 = `run_complete_no_gt`, не `evaluated`.

## Выборка

Манифест: `validation/model_selection/manifest.json` (v2 audit; состав кадров = v1).  
Источник кадров: `validation/vlm_compare/manifest.yaml`. Копия до аудита: `manifest.v1.json`.

| split | смысл в этом цикле |
|---|---|
| diagnostic dev | `split=dev`, 5 кадров и 1 пара. Промпт на них в этом цикле не подбирался. |
| selection | `split=check`, 6 кадров и 2 пары. Кадры уже знакомы. Это не независимая проверка. |
| verification | нет. Закрытый holdout не открывался. |

Не входят: `control_benchmark_days_excluded` и `holdout_days` из `validation/equipment_v1/domain_split.json`; неоткрытые кадры `artifacts/model_compare/protocol.json` со `split=holdout`.

Офисные имена файлов — слоты линейной интерполяции видео, не дата камеры. Для календарного отставания они запрещены.

### Пригодность smoke-кадров

- `s-dev-earth-1` / `s-dev-earth-2` / `s-check-pit` / `s-check-val`: земляные работы. Smoke этажности целевого корпуса **не** строить на них. Допустимы: котлован, техника, отказ по этажам цели.
- `s-check-office-a` / `s-check-office-b`: допустимы smoke этажности и окон, но **не** независимый тест (кадры уже многократно смотрелись).
- Один офисный кадр и одна задача этажности не закрывают матрицу отбора.

## Эталон

`validation/vlm_compare/labels.yaml`: `author_kind=agent_preliminary`, `counts_toward_accuracy=false`.

`validation/perception_regression/gt/floors_localize_manual.json` не принят независимым human GT.

Точность числа на кадрах без human GT не считается. Пакет разметки: `LABELING_PACKET.md`. Агент GT не назначает.

| значение | смысл |
|---|---|
| 0 | только подтверждённое отсутствие конкретного объекта в видимой зоне |
| unknown | счёт или признак не установлен |
| not_applicable | задача к кадру не относится |

## Пороги (зафиксированы до новых сравнений)

- Этажи: exact match и MAE только на кадрах с human GT и `counts_toward_accuracy=true`. Сейчас таких кадров 0. Отказ на `visibility=none` и число на пригодном кадре считаются отдельно. Покрытие — доля пригодных кадров с ответом, не с отказом.
- Локализация: бокс совпадает при IoU ≥ 0.3. Точка — если после crop→original ближе 32 px к GT. Линия этажа — средняя |Δy| на кропе ≤ 8% высоты кропа и не в полосе кровли/проезда.
- Работы: TP/FP/FN по наблюдаемым признакам. Ложное «завершено» по одному признаку дисквалифицирует использование ответа как факта завершения.
- Динамика: четыре класса — появилось, изменилось, видимых изменений нет, кадры несопоставимы.
- Gate отбора (публиковать абсолютные числа при малом n):  
  1) ложные подтверждения меньше при покрытии ≥ 0.5 пригодных кадров;  
  2) больше верных фактов;  
  3) локализация;  
  4) цена и задержка.  
  Сплошной отказ не победа. Неопределённость — по эпизодам.
- Ошибки API, parse, truncation, пустой ответ — эксплуатационная доступность, отдельно от качества.
- Сравнение моделей требует одинаковых: изображений, crop/target, постановки задачи, правил оценки и набора cases. Различия resolution/tiling/exemplars/reasoning/quantization/route — отдельные конфигурации.

### Бюджет токенов

Не требовать одинакового `max_tokens` любой ценой. Модель должна иметь шанс закончить структурный ответ. Для reasoning-моделей: либо `reasoning.enabled=false`, либо отдельный бюджет completion достаточный для JSON после reasoning. Truncation при `finish_reason=length` — эксплуатационный провал конфигурации, не «модель отказалась».

## Бюджет и факты OpenRouter (не затирать)

Dry-run plan 2026-09-26T22:03:23Z (изображения не отправлялись): оценка ≤ $0.759096 на 216 billable из 288 calls — см. v1 и `call_matrix_plan.json` (там ещё пустой `provider_order`; актуальные пины — `config/vlm_compare_openrouter_pinned.yaml`).

Фактические smoke (ledger `validation/vlm_compare/openrouter_attempt_ledger.json`):

| grant | attempts | факт |
|---|---:|---|
| smoke-2026-09-27 | 3 | 235B completed; 397B truncated; Kimi 404 |
| повтор Kimi (отдельный процесс) | +1 | overrun лимита; Kimi truncated |
| smoke2-2026-09-27 | 2 | 397B completed (reasoning off); Kimi ConnectTimeout |

Итого: authorized 5, observed 6, overrun +1. known cost ≈ $0.004798; unknown cost calls = 2 (не подставлять 0).

Ключ: `.env` → `OPENROUTR_KEY`. Новые платные вызовы — только по новому grant в ledger.

## Команды

```bash
cd /home/dimk/my_project/LCT2026
.venv/bin/sitewatch vlm-compare plan
.venv/bin/sitewatch vlm-compare run --execute \
  --models local-qwen3-vl-8b --split dev \
  --budget-usd 0 --max-requests 40 --max-output-tokens 400
# Платные: только после записи grant в openrouter_attempt_ledger.json
.venv/bin/sitewatch vlm-compare score --run-dir artifacts/vlm_compare/runs/<id>
.venv/bin/sitewatch vlm-compare report --run-dir artifacts/vlm_compare/runs/<id>
.venv/bin/python validation/model_selection/check_sources.py
```

Повторная проверка источников не качает веса. Не останавливать чужие GPU/download PID.
