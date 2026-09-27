# Задания агентам после аудита 2026-09-27

Общий владелец: **experiment-owner**.  
Чужие общие файлы не править. Платные вызовы — только после новой записи `grants[]` в `openrouter_attempt_ledger.json`. Чужие PID загрузок/GPU не убивать.

Канон: `EXPERIMENT_PROTOCOL.md` (v2), `manifest.json` (v2), `EXPERIMENT_AUDIT.md`.

### Внешний equipment benchmark — аудит закрыт (2026-09-27)

Рейтинг не пересчитывать. Канон ролей: `external_equipment/MOCS_PILOT_ROLES.md`, статус: `SELECTION_STATUS.md`. Следующая работа — ограниченный пилот и просмотр кандидатов на трёх объектах, не новая таблица метрик. Qwen3.5 — отдельно.

### Внешний equipment benchmark (2026-09-27)

- Каталог: `validation/model_selection/external_equipment/` (+ raw в `artifacts/model_selection/runs/external_equipment/`).
- Статус: **`selected_external_large_excavator`** (DINO; этап **закрыт**, v1.1). Production не менять.
- Near-dup: визуально ложные срабатывания — см. `NEAR_DUP_VISUAL_REVIEW.md`.
- Следующий этап multi-class/distant: **MOCS YOLO** — images.rar скачан; diagnostic v1 в `RESULTS_MOCS_DIAGNOSTIC.md` / `reports/metrics_mocs_diagnostic_v1.json`. Provenance: `MOCS_PROVENANCE.md`.
- Kaggle по-прежнему optional (`ACCESS_BLOCKERS.md`) — **не** блокирует MOCS.

#### Роли моделей (equipment)

| Модель | miniexcav | следующий diagnostic |
|---|---|---|
| Grounding DINO | primary `selected_external_large_excavator` | участвует |
| YOLOE-26L | альтернатива | участвует |
| YOLOE-11L | baseline-frozen | **не** включать |
| YOLO-World V2.1 | `not_run` | участвует, если runtime ок (`.venv-yoloworld` есть) |
| SAM 3.1 | `not_run` | участвует, если runtime ок (`models/sam3.1_multiplex.pt` есть) |

---

## Владельцы общих файлов

| Файл | Владелец | Кто НЕ пишет |
|---|---|---|
| `validation/model_selection/manifest.json` (+ `.vN`) | experiment-owner | local-models, openrouter-agent |
| `validation/model_selection/EXPERIMENT_PROTOCOL.md` (+ `.vN`) | experiment-owner | остальные |
| `validation/model_selection/external_equipment/**` | experiment-owner | openrouter-agent; local-models пишут только `artifacts/.../external_equipment/` raw по заданию |
| `validation/vlm_compare/labels.yaml` | experiment-owner (принимает human GT) | модели-агенты не ставят GT |
| `validation/vlm_compare/openrouter_attempt_ledger.json` | openrouter-agent пишет events; **grant** утверждает experiment-owner | local-models |
| `config/vlm_compare_openrouter_*.yaml` | openrouter-agent | local-models (без смены общего pin без согласования) |
| `validation/model_selection/model_registry.yaml` | experiment-owner (статусы); агенты шлют patch-proposal | — |
| `artifacts/vlm_compare/runs/*` | openrouter-agent / local VLM runner | не смешивать каталоги |
| `artifacts/model_selection/runs/*` | local-models | openrouter не пишет сюда |
| Production DB / alerts / inspector decisions | **никто** из model-selection | — |

---

## A. experiment-owner

### A1. Принять human GT
- **Входы:** `LABELING_PACKET.md`, кадры манифеста, текущий `labels.yaml`.
- **Результат:** `labels.yaml` с `author_kind=human`, `review_status=accepted`, `counts_toward_accuracy=true` только где человек подтвердил; спорные этажи → range/unknown, не точное число.
- **Критерий завершения:** ≥1 кадр floors с accuracy=true **или** явный отказ разметчика с причиной; отдельно presence для pit/equipment/facade/roof; box GT хотя бы на office-a для window vs opening.
- **Ограничения:** не открывать holdout; не копировать agent_preliminary в human; не подставлять 6 из имени house6.
- **Переход:** после GT → A2 score существующих raw runs (пересчёт, без нового inference где raw есть).

### A2. Пересчёт метрик на существующих raw
- **Входы:** `vc-local-qwen8b-20260927`, `sam31_baseline`, `dino_base_baseline`, YOLOE runs; OR smokes только как diagnostic.
- **Результат:** `score`/`report` с разделёнными quality vs availability; OR earth-1 floors помечен `incomparable_for_floors_selection`.
- **Критерий:** scores не null там, где есть human GT; иначе явно `support=0`.
- **Inference:** только пересчёт, если raw полные.

### A3. Verification plan (без открытия sealed holdout)
- **Результат:** черновик verification episode из ещё неоткрытых разрешённых дней **или** явное «недоступно → winner запрещён».
- **Ограничения:** не использовать `holdout_days` / sealed list из manifest.

### A4. Статусы реестра
- Держать `model_registry.yaml` в taxonomy protocol v2.
- Принимать patch от local/openrouter только как proposal.

---

## B. local-models

### B1. Мониторинг загрузок (без kill)
- **Входы:** `artifacts/model_compare/molmo_download.pid`, `internvl_download.pid`, HF blobs.
- **Результат:** запись в `RUN_JOURNAL.md` (секция local): incomplete bytes, n_shards, alive y/n. При `MOLMO_READY` / `INTERNVL_READY` — сменить статус на `weights_verified` **через experiment-owner**.
- **Критерий:** ежедневный снимок или по завершению; не запускать второй snapshot_download того же repo.
- **Ограничения:** не `kill` PID сервера Qwen и живые download PID, carplatedetect. PID из этого файла устаревают; узнавать процесс по командной строке.
- **Сессия:** обрыв MolmoPoint был временем жизни фоновой команды, не ошибкой модели. Правило: `DOWNLOAD_SESSIONS.md`. Не держать докачку только внутри shell-задачи инструмента.

### B2. MolmoPoint smoke (после 8/8 шардов)
- **Входы:** checkpoint revision `188130f…`, кадр `s-check-office-a` crop из манифеста, `extract_image_points`.
- **Результат:** `artifacts/model_selection/runs/molmopoint_smoke/` с raw points + overlay; config.json.
- **Критерий:** настоящий inference; пустой выход записан честно.
- **VRAM:** не выгружать Qwen без согласования; предпочесть cuda:1 / offload.
- **Переход к InternVL:** только если Molmo smoke записан или blocked с причиной VRAM.

### B3. YOLOE — не крутить порог
- **Запрет:** менять conf ради ненулевых боксов на office.
- **Разрешено:** после box GT — score prefilter+frozen conf раздельно; отчёт FP/FN.
- **Критерий завершения текущего шага:** уже выполнено (`smoke_passed`); ждать GT.

### B4. DINO deps policy
- **Результат:** либо `transformers` в `LCT2026/.venv` для воспроизводимости, либо документ «experimental myenv-only» в INTEGRATION + registry note.
- **Не** подключать в product `perception.yaml` без experiment-owner.

### B5. FloorLevel-Net filename
- **Входы:** Drive folder listing (без скачивания всего dataset).
- **Результат:** точное имя `.pth` или `blocked` с цитатой listing.
- **Не** скачивать веса до подтверждения имени.

### B6. SAM/DINO
- Новых полных 11-кадровых прогонов не делать без изменения конфига.
- Ждать GT → score.

---

## C. openrouter-agent

### C1. Зафиксировать историю (уже есть)
- Ledger overrun и truncation **не удалять**.
- Не повторять успешные completed calls (235B earth-1; 397B reasoning-off earth-1).

### C2. Следующий grant (только после утверждения experiment-owner)
Минимальный пакет для закрытия вопросов доступности (не качества):

| # | model | sample | task | config | зачем |
|---|---|---|---|---|---|
| 1 | or-qwen3-vl-235b | s-check-office-a | floors | pinned, max_tokens≥400 | floors smoke на пригодном кадре |
| 2 | or-qwen3-vl-235b | s-check-pit | floors | same | refusal / not target |
| 3 | or-qwen3.5-397b | s-check-office-a | floors | reasoning-off, max_tokens≥800 | законченный JSON |
| 4 | or-kimi-k2.6 | s-check-office-a | floors | reasoning-off, omit seed, max_tokens≥800 | первый parsed success |

- **Входы:** `config/vlm_compare_openrouter_pinned.yaml` + reasoning_off; ledger grant id.
- **Результат:** новый run-dir под `artifacts/vlm_compare/runs/openrouter-…`; events в ledger; raw+parsed.
- **Критерий завершения:** 4 attempts без overrun; каждый cost_status api|unknown (unknown ≠ 0); Kimi не 404 из-за seed.
- **Ограничения:** concurrency=1; allow_fallbacks=false; не слать earth-1 как floors-positive; не открывать holdout; не поднимать budget без grant.
- **Переход к matrix:** только если C2 parsed≥3/4 и experiment-owner выдал grant на elements/works/change.

### C3. Полная matrix
- Запрещена до: human GT **или** явного diagnostic-only флага с пометкой «не selection».
- При diagnostic-only: не писать в MODEL_SELECTION winner tables.

### C4. Кэш
- Переиспользовать raw по cache_key; не биллить повтор того же hash.

---

## Критерий перехода к отбору лучших моделей

Отбор (shortlist per task) разрешён только когда:

1. Human GT на индикаторе задачи с `counts_toward_accuracy=true` для ≥ N пригодных кадров (floors: ≥3 non-office-only если претендуем на перенос; иначе честно «office-only diagnostic»).
2. ≥2 кандидата с сопоставимым run (те же samples, task, view, score rules).
3. Опубликованы: coverage, false confirms, refusals, exec errors, cost/latency.
4. Verification ≠ пересмотр тех же office/earth кадров; либо winner помечен `provisional_familiar_check_only`.

Пока пункт 1 ложен — **победителей нет**.
