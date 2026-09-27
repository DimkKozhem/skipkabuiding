# Реестр моделей (сводка после аудита)

Машиночитаемо: `model_registry.yaml`. Сырьё: `source_evidence.json`, `source_evidence_extra.json`.  
Таксономия статусов: `EXPERIMENT_PROTOCOL.md` v2. Полная таблица: `EXPERIMENT_AUDIT.md` §2.

Проверка источников 2026-09-26. Inference/smoke/download статусы сверены аудитом 2026-09-27.

## Счёт (после аудита)

| Состояние | Кто |
|---|---|
| `run_complete_no_gt` | Qwen3-VL-8B local, SAM 3.1, Grounding DINO base |
| `smoke_passed` | YOLOE-11L (0 boxes на office @0.25) |
| OpenRouter smoke (не matrix) | 235B completed; 397B truncated→completed; Kimi 404/trunc/timeout |
| `download_incomplete` | MolmoPoint-8B, InternVL3.5-8B |
| `sources_verified` без run | 397B/Kimi/235B как family (smoke отдельно), CountEx, CountGD++, Molmo2, ProgressLM, InternVL14B |
| `blocked` | InternVL241B, FloorLevel-Net, CountGD stack |
| `rejected` | GATA2Floor, GroundCount, AVA-VLM, ChatGPT-4V progress |

Страница HTTP и строка каталога OpenRouter ≠ ответ на кадр. `download_incomplete` ≠ `weights_verified` ≠ `smoke_passed` ≠ `evaluated`.

## Заметки

- Product DINO provider всё ещё может отдавать `grounding_dino_no_weights`; экспериментальный baseline шёл из myenv.
- YOLOE AGPL — продуктовый вопрос, не закрыт.
- ProgressLM ответ ≠ процент готовности строительства.
- Ключ API: `OPENROUTR_KEY`. Новые $ — только grant в ledger.
