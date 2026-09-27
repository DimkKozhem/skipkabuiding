# Perception Production MVP

## Аудит (до перестройки)

| Слой | Было | Стало |
|------|------|-------|
| Perception | `Detection[]` → сразу `ActualState` | `ObservedState` через quality → SAM3 → DINO? → Qwen → fusion |
| ActualState | снимок кадра | накопительный (TemporalStateEngine) |
| Plan/fact | `DeviationEngine` | `PlanFactEngine` facade (тот же engine) |
| Demo | annotation sidecar | `SITEWATCH_PERCEPTION_MODE=annotation` (default) |
| Async | только capture loop | `FrameAnalysisJob` + thread pool для `real` |

Граница: perception **никогда** не получает КСГ / `ExpectedState`.

## Цепочка

```text
Frame → ImageQuality → SAM3 → [Grounding DINO] → Qwen-VL → Fusion
  → ObservedState → TemporalStateEngine → ActualState → PlanFactEngine → API
```

## Режимы

- `annotation` — demo / pytest; annotation provider → ObservedState → temporal → ActualState.
- `real` (алиас `full`) — OpenCV quality → SAM3 → optional DINO → Qwen/vLLM → fusion.

```bash
export SITEWATCH_PERCEPTION_MODE=real
```

## Модели и кеш

| Компонент | Как | Где веса |
|-----------|-----|----------|
| SAM3 | ultralytics `SAM3SemanticPredictor` в backend worker | `models/sam3.1_multiplex.pt` или HF `~/.cache/huggingface/hub/models--facebook--sam3.1/...` |
| Qwen3-VL-8B | отдельный vLLM OpenAI API | HF cache / `QWEN_VL_MODEL` |
| Grounding DINO | optional, default off | — |

Не коммитить `.pt` в git (см. `.gitignore`).

SAM3 на 24GB: `imgsz: 720`, `prompt_batch_size: 4` в `config/perception.yaml` (1008 + все промпты сразу → OOM). Нужен пакет `timm` в `.venv`.

Рекомендуемый split GPU: Qwen на RTX 3090 (`CUDA_VISIBLE_DEVICES=0`), SAM3 на 4060 Ti (`SITEWATCH_SAM3_DEVICE=cuda:1`). Qwen3-VL-8B bf16 ≈20GB VRAM — на 16GB не влезает без квантизации.

### Поднять vLLM (отдельный процесс)

```bash
# пример на GPU1 (16GB) с Qwen3-VL-8B
CUDA_VISIBLE_DEVICES=1 CUDA_DEVICE_ORDER=PCI_BUS_ID \
/home/dimk/my_project/myenv/bin/python -m vllm.entrypoints.openai.api_server \
  --model Qwen/Qwen3-VL-8B-Instruct \
  --host 127.0.0.1 --port 8001 \
  --max-model-len 4096
```

Если vLLM падает на конфликте `transformers`/`mistral_common`, используйте shim:

```bash
CUDA_VISIBLE_DEVICES=1 CUDA_DEVICE_ORDER=PCI_BUS_ID \
/home/dimk/my_project/myenv/bin/python scripts/qwen_vl_openai_server.py \
  --host 127.0.0.1 --port 8001 --device cuda:0
```

Backend:

```bash
export SITEWATCH_PERCEPTION_MODE=real
export SITEWATCH_QWEN_VL_BASE_URL=http://127.0.0.1:8001/v1
export SITEWATCH_QWEN_VL_MODEL=Qwen/Qwen3-VL-8B-Instruct
export SITEWATCH_SAM3_DEVICE=cuda:0
```

Prompt: `config/prompts/qwen_construction_observer_v1.txt`  
Schema: `config/prompts/qwen_construction_observer_v1.schema.json`

## Запуск inference smoke

```bash
sitewatch analyze path/to/frame.jpg \
  --project site_001 --zone zone_a --camera cam_a --mode real
```

Artifacts: `data/observations/artifacts/<run_id>/`  
(`original.jpg`, `sam_overlay.jpg`, `detections.json`, `qwen_result.json`, `observed_state.json`, `pipeline_run.json`)

Benchmark:

```bash
sitewatch perception-benchmark validation/perception/
```

## Финальный аудит readiness

### Product
Можно подключить камеру (`interval_minutes≈30`) и копить ObservedState / ActualState / evidence в SQLite + artifacts. UI object_page совместим.

### ML
Сохраняются source / model / version, raw evidence, pipeline stages / errors.

### Infrastructure
Per-stage latency в `PipelineRun`; GPU/VRAM telemetry для локального SAM3 (если torch.cuda доступен).

### Architecture
Providers за Protocol. HumanCorrection — extension point (не реализован).

## Поведение 1.1

- Класс без локализованного бокса не получает количество `0`. Текст Qwen без бокса остаётся `uncertain` и не подтверждает факт.
- Конфликт детектора и VLM явно помечается `agreement:conflict`. Пространственный счёт детектора сохраняется, но не становится свежим подтверждением.
- Плохой кадр, другая камера, другой ракурс и повтор того же кадра не затирают подтверждённый факт. Кадр старше уже учтённого не откатывает состояние.
- Ошибочно завышенный persistent-счёт пересматривается только повторным уверенным чтением или новой версией perception.
- `no_dynamics` требует пригодные кадры и разрыв между ними не больше `max_observation_gap_days` (7). Три близких кадра и пауза в 14 дней сигнал не создают.
- Повторный `evaluate` того же эпизода не плодит карточку и не снимает решение инспектора; новое evidence дописывается. Новый эпизод начинается с другой первой даты.
- Очередь анализа: не больше `analysis_max_queued`, один worker, зависший `processing` становится `failed/stale_running`. Сравнение с графиком, которое не удалось, не отменяет сохранённое наблюдение.
- SAM3 по умолчанию на `cuda:1` (RTX 4060 Ti). Qwen остаётся на `cuda:0` (RTX 3090).

Воспроизводимый прогон:

```bash
.venv/bin/sitewatch perception-benchmark validation/perception_regression --mode annotation
.venv/bin/sitewatch perception-benchmark validation/perception_regression --mode real
```

`annotation` проверяет манифест и логику. Качество SAM/Qwen измеряет только `real`. Октябрьско-ноябрьский holdout из `validation/equipment_v1/domain_split.json` в этот набор не входит.
