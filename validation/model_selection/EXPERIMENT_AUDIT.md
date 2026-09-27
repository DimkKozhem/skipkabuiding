# Аудит эксперимента выбора моделей

Дата аудита: 2026-09-27 (локально ~18:26 MSK).  
Рабочий каталог: `/home/dimk/my_project/LCT2026`.  
Владелец общих файлов после аудита: роль **experiment-owner** (этот аудит / следующий исполнитель `AGENT_TASKS.md` §A).

Победитель модели **не** выбран: human GT с `counts_toward_accuracy=true` = 0, verification split отсутствует, OpenRouter full matrix не гонялась.

---

## 1. Что подтверждено файлами

### Документы и конфиги

| Артефакт | Статус |
|---|---|
| `EXPERIMENT_PROTOCOL.v1.md` / `EXPERIMENT_PROTOCOL.md` (v2) | v1 сохранена; v2 = статусы, smoke-пригодность, ledger |
| `manifest.v1.json` / `manifest.json` (v2) | 11 кадров, hashes OK; v2 добавил индикаторы, состав кадров не менялся |
| `validation/vlm_compare/manifest.yaml` | источник кадров; 11 samples + 3 pairs |
| `validation/vlm_compare/labels.yaml` | 8 items, все `agent_preliminary`, accuracy=false |
| `config/vlm_compare_openrouter_pinned.yaml` | существует; pin deepinfra/fp8 и baidu/fp4 |
| `config/vlm_compare_openrouter_reasoning_off.yaml` | существует; reasoning off для 397B/Kimi |
| `openrouter_endpoints_2026-09-27.json` + index + reasoning + provider_pin | существуют; каталог без image calls |
| `openrouter_attempt_ledger.json` | 6 HTTP attempts, overrun +1, known cost ≠ 0 |
| `source_evidence.json` / `source_evidence_extra.json` | источники карточек/README; не inference |
| `model_registry.yaml` | 22 кандидата; часть статусов устарела до правок аудита |

### Локальные прогоны (настоящий inference)

| Run | Доказательство | Итог |
|---|---|---|
| Qwen3-VL-8B local | `artifacts/vlm_compare/runs/vc-local-qwen8b-20260927/` | 36 text completed; 36 structured unsupported; cost 0 |
| SAM 3.1 | `artifacts/model_selection/runs/sam31_baseline/` | 11/11 success, overlays |
| Grounding DINO base | `artifacts/model_selection/runs/dino_base_baseline/` | 11/11 success via **myenv** (не `.venv`) |
| YOLOE-11L smoke | `runs/yoloe11l_smoke/` на `s-check-office-a` | checkpoint verified; 0 boxes @ conf 0.25 |
| YOLOE adapter control | `runs/yoloe11l_adapter/` bus.jpg | 6 boxes person/bus — адаптер жив |
| YOLOE prefilter | `runs/yoloe11l_text_prefilter_v1/` | 47 boxes, max score 0.0415 |
| YOLOE dev | `runs/yoloe11l_text_v1/` | 5/5 frames, 0 accepted boxes |

### OpenRouter smoke (платные, не повторять)

Все на **одном** кадре `s-dev-earth-1`, задача `floors`, structured:

| Модель | Исход | cost |
|---|---|---|
| qwen3-vl-235b @ deepinfra/fp8 | completed, parse count=5 | $0.00044024 |
| qwen3.5-397b @ deepinfra/fp8 | truncated (length@400) | $0.0020388 |
| kimi-k2.6 @ baidu/fp4 | 404 Filter by Parameters (seed) | unknown |
| kimi retry | truncated (length@400) | $0.001242614 |
| qwen3.5-397b reasoning off | completed, parse count=5 | $0.0010767 |
| kimi reasoning off | ConnectTimeout / http_error | unknown |

Оба завершённых ответа count=5 смотрят на **фоновый фасад**, не на целевой котлован — визуально это ложное подтверждение этажности цели (labels для `s-dev-earth-1` floors **нет**; по протоколу кадр not applicable / refusal).

### Загрузки в фоне (не убивать)

| PID (на момент аудита) | Что | Состояние |
|---|---|---|
| `internvl_download.pid` → процесс snapshot_download InternVL3.5-8B | download_incomplete | 0 готовых model*.safetensors, 4 incomplete ~3.7 ГБ |
| `molmo_download.pid` → curl resume MolmoPoint-8B | download_incomplete | 7/8 шардов; 1 incomplete ~1.8 ГБ |
| GPU0 pid 3026602 | Qwen server ~21892 MiB | занят |
| GPU1 pid 2045 | carplatedetect ~362 MiB | 4060 почти свободна |

### Что документы врали до аудита

`MODEL_SELECTION.md` / `MODEL_COMPARISON.md` / `RUN_JOURNAL.md` / blockers в `model_registry.yaml` утверждали «0 USD / удалённые не вызывались / Molmo не скачивался». Это **опровергнуто** ledger и PID загрузок. Исправления — в журнале и реестре ниже.

---

## 2. Таблица готовности кандидатов

Легенда: **Tech** = техническая готовность; **Qual** = качество (только при human GT).

| Кандидат | Задача | Источники | Конфигурация | Доступность | Smoke | Результаты | Оценка | Блокировка | Следующее действие | Ответственный |
|---|---|---|---|---|---|---|---|---|---|---|
| Qwen3-VL-8B local | floors/elements/works/change | HF rev `0c351dd…`, Apache-2.0, код Qwen3-VL | `:8001` cuda:0, text only, max_tokens 400 | weights+server | да, 11+3 | `vc-local-qwen8b-20260927` | Qual нет | GT отсутствует; structured unsupported | ждать human GT → score; не объявлять winner | experiment-owner |
| Qwen3-VL-235B OR | remote floors+… | HF+OR catalog | pin `deepinfra/fp8`, structured | API pin OK | smoke: 1 frame completed | raw+parsed count=5 на earth-1 | Qual нет | нет grant на matrix; smoke-кадр неподходящий для floors | новый grant + multi-sample plan **без** earth-1 как floors-positive | openrouter-agent |
| Qwen3.5-397B OR | remote | blog+HF+OR | pin fp8; reasoning on/off | API | truncated → completed off | smoke2 parsed count=5 | Qual нет | truncation history; grant exhausted | с reasoning-off и достаточным max_tokens; не earth-1 floors | openrouter-agent |
| Kimi-K2.6 OR | remote | HF Modified MIT | pin `baidu/fp4`, omit seed | API | 404→trunc→timeout | нет parsed success | Qual нет | seed/param, truncation, timeout; unknown cost | fix omit_seed+reasoning-off; retry только с grant | openrouter-agent |
| InternVL3.5-8B | local alt VLM | HF `9bb6a56…` | TBD после download | download_incomplete | нет | нет | нет | загрузка идёт; 8B≈21ГБ vs 16ГБ 4060 | дождаться шардов; план VRAM (offload/квант) до load | local-models |
| InternVL3.5-14B | local | HF | — | sources_verified | нет | нет | нет | GPU/VRAM | после 8B decision | local-models |
| InternVL3.5-241B | — | HF | — | blocked | нет | нет | нет | нет endpoint; не скачивать | оставить blocked | experiment-owner |
| FloorLevel-Net | floor bounds | Drive folder visible | `.pth` name unknown | blocked | нет | нет | нет | имя весов не извлечено | извлечь filename из Drive listing без полного download | local-models |
| MolmoPoint-8B | pointing | HF `188130f…` | transformers pin planned | download_incomplete | нет | нет | нет | shard 8 качается; VRAM | дождаться 8/8; smoke на office crop | local-models |
| CountGD | count | recipe+Drive | multi-weight stack | blocked | нет | нет | нет | стек не собран | не начинать до GT boxes | local-models |
| CountGD++ | count | Drive 1.25GB | — | sources_verified | нет | нет | нет | не скачан | после CountGD decision | local-models |
| CountEx | count | HF collection | — | sources_verified | нет | нет | нет | не скачан | низкий приоритет | local-models |
| YOLOE-11L | open-vocab det | HF `b584da…`, AGPL | text classes window… conf0.25 imgsz640 cuda:1 | weights_verified | smoke_passed (0 boxes) | smoke+dev+prefilter+adapter | Qual нет | 0@0.25 на office; нет box GT; AGPL | не крутить conf ради победы; ждать box GT | local-models |
| SAM 3.1 | segment | local `sam3.1_multiplex.pt` | thr0.35 imgsz720 cuda:1 | weights_verified | run_complete_no_gt | 11 overlays | Qual нет | нет box GT | score после GT; не писать в WorkFact | local-models |
| Grounding DINO base | det | HF `12bdfa…` | box0.35 text0.25; **myenv** | weights local | run_complete_no_gt | 11 overlays | Qual нет | нет transformers в `.venv`; product provider `no_weights` | либо deps в `.venv`, либо зафиксировать myenv-only experimental | local-models |
| Molmo2-8B | multi-image | HF | — | sources_verified | нет | нет | нет | GPU; не скачан | после MolmoPoint | local-models |
| ProgressLM SFT/RL | progress text | HF | — | sources_verified | нет | нет | нет | протокол входа неясен; ≠ % готовности | не качать до постановки задачи | experiment-owner |
| GATA2Floor / GroundCount / AVA-VLM / ChatGPT4V | — | articles only | — | rejected | — | — | — | нет весов | не трогать | experiment-owner |

---

## 3. Матрица покрытия задач

| Задача / индикатор | Кадры в манифесте | Разметка | Кандидаты с raw | Метрики | Недостающее |
|---|---|---|---|---|---|
| Этажность (число) | все 11 applicable_tasks floors; пригодны office-a/b, frame?, facade range; earth/pit = refusal/NA | preliminary floors на 6 samples; **нет** earth-1/2/val/early | Qwen8B all; OR smoke только earth-1; | exact/MAE = null | human GT; OR multi-frame **не** на earth-1; не назначать 6 по имени house6 |
| Окна установленные | office-a/b, facade, openframe? | elements presence только office-b; **боксов нет** | SAM window opening=0 на office; DINO window≫opening; YOLOE 0@0.25 | нет | box GT window vs opening |
| Проёмы | office, early, openframe | нет координат | SAM 0 opening на office; DINO мало opening | нет | box GT openings |
| Фасад (признак) | facade, office, openframe | нет works labels | Qwen works сырой completion=complete | нет | presence labels без % |
| Кровля | office, facade | presence в elements office-b | SAM roof boxes | нет | human presence |
| Котлован | earth-1/2, pit, val | нет | Qwen/SAM/DINO raw | нет | presence GT; floors refusal check |
| Фундамент | earth/pit (primary) | нет отдельно | SAM foundation prompts | нет | presence GT |
| Техника | earth/pit/val/empty | нет | SAM equipment (FP на empty) | нет | count/presence GT; confirmation filter отдельно |
| Разделитель | office/facade optional | **выпал** | никто целево | нет | решить нужен ли индикатор; иначе вычеркнуть из gate |
| Изменение работы (пары) | p-dev-earth, p-check-office, p-check-house | только note на p-check-office | Qwen change text | нет 4-классной матрицы | human change class на 3 пары; office interval unreliable |

**Выпало из фактического отбора:** разделитель; фундамент как отдельный признак; техника как метрика; works presence; multi-frame OR; verification. Фактический удалённый smoke свелся к **этажности на одном земляном кадре**.

---

## 4. Аудит manifest / GT / утечки

### Кадры

Все 11 путей существуют; sha256 совпали с манифестом. Holdout и sealed_excluded не открывались аудитом.

### `s-dev-earth-1`

- Stage earthworks; primary: pit/equipment/foundation.
- OpenRouter smoke floors → **неподходящий** positive floors smoke.
- Qwen local вернул count=6 без отказа — диагностический ложный позитив фона.

### `s-check-office-a`

- Envelope; подходит floors/elements smoke; **не** independent test.
- YOLOE smoke здесь корректен как smoke детектора (ожидаемы окна), но 0 boxes ≠ precision score.
- Agent floors value=2 не counts_toward_accuracy.

### Утечки / загрязнение

| Риск | Находка |
|---|---|
| Плановые числа в имени | `house6` / leak_canary в labels; в промпт perception/plan не должны попадать |
| Agent answers в model input | harness labels отдельно; не передавать value модели |
| Соседи эпизода в splits | office a/b оба check; earth 1/2 оба dev — OK для diagnostic, плохо как независимые |
| Check для настройки | protocol: prompt не подбирался на check в этом цикле; кадры всё равно «знакомы» |
| Holdout | не в манифесте |
| Повторный просмотр | office / earth уже в floor_method_check и perception experiments → не verification |

### GT пакет

См. `LABELING_PACKET.md`. Числа этажей дома **не** назначены аудитом.

---

## 5. Сопоставимость запусков

| Сравнение | Сопоставимо? | Почему |
|---|---|---|
| Qwen8B text vs OR structured smoke | **нет** для качества | разный response_mode; OR только 1 кадр |
| 235B vs 397B vs Kimi smoke | частично по кадру/задаче | один sample; разные finish (stop/length/404/timeout); 397B до/после reasoning-off — **разные конфигурации** |
| SAM vs DINO vs YOLOE | частично localization raw | разные class lists/thresholds; YOLOE underscore `window_opening`; SAM space `window opening`; нет GT matching |
| DINO `.venv` vs myenv | env разный | зафиксировать в отчёте; product path другой |
| Full local Qwen 11 frames | внутренне сопоставим | один манифест, один crop pipeline |

---

## 6. Ресурсы и ошибки (сохранить историю)

- Ledger overrun: 6 observed / 5 authorized.
- Truncation @400 на reasoning models — зафиксировано; reasoning-off помог 397B.
- Kimi: 404 seed → omit_seed; затем truncation; затем ConnectTimeout (cost unknown).
- YOLOE download: curl timeouts, resume via proxy — завершён, sha совпал.
- Molmo/InternVL: download_incomplete, чужие PID — не трогать.
- `call_matrix_plan.json`: устаревшие пустые `provider_order` и catalog prices — не источник pin.

---

## 7. Критерии выбора

Пороги matching/gate перенесены в protocol v2 **до** новых сравнений.  
Уже просмотренные smoke/office/earth **не** дают право объявить winner. После human GT — независимый verification episode обязателен.

Публиковать всегда: качество (если GT), покрытие, ложные подтверждения, отказы на пригодных, ошибки исполнения, cost/latency. Сырые предсказания и post-confirmation — раздельно.

---

## 8. Исправления этого аудита

| # | Проблема | Доказательство | Исправление | Затронутые результаты | Новый inference? |
|---|---|---|---|---|---|
| 1 | Docs: «0 remote calls / 0 USD» | ledger + run dirs | обновлены RUN_JOURNAL, MODEL_*, registry blockers | interpretive only | нет |
| 2 | status `evaluated` без GT | protocol + scores null | taxonomy v2; registry → `run_complete_no_gt` / smoke статусы | метки статуса | нет |
| 3 | Molmo/InternVL «не скачивались» | PID + incomplete blobs | registry `download_incomplete` | статус | нет (не убивать download) |
| 4 | Нет индикаторов задач в manifest | coverage gap | manifest v2 indicators; v1 сохранён | интерпретация пригодности | нет |
| 5 | Protocol не знал OR smoke/overrun | ledger | protocol v2 + история ошибок | критерии новых прогонов | нет |
| 6 | Нет заданий агентам | — | `AGENT_TASKS.md` | процесс | по grant/GPU |
| 7 | Нет бланка GT | labels accuracy=false | `LABELING_PACKET.md` | разметка | human only |

Метрики уже полученных прогонов **не пересчитывались как accuracy** (нельзя: GT нет). Пересчёт оценки возможен только после human labels.

---

## 9. Очередь следующих действий

1. Human labeling packet (`LABELING_PACKET.md`) — блокирует любой winner.
2. OpenRouter: новый grant только после явного бюджета; матрица ≥ office-a/b + pit refusal + openframe/facade; **не** earth-1 floors-positive; max_tokens/reasoning по protocol v2.
3. Local: дождаться Molmo/InternVL downloads; YOLOE/SAM/DINO score после box GT; DINO deps policy.
4. Experiment-owner: держать единый manifest/protocol/ledger; запрет правки общего manifest другими агентами.
5. Verification episode вне holdout — после GT на текущем check.

Конкретные задания — `AGENT_TASKS.md`.
