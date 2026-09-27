# Блокировки доступа (обновлено)

Kaggle **не** останавливает этап: найден публичный MOCS YOLO на Hugging Face.

## Kaggle (опционально)

По-прежнему нет `~/.kaggle/kaggle.json` / env. Для arh-df / xyzyxzzxy / datacluster:

```bash
mkdir -p ~/.kaggle
# положить kaggle.json
chmod 600 ~/.kaggle/kaggle.json
```

или zip → `data/external/benchmark_sources/incoming/`.

## MOCS images — разблокировано (2026-09-27)

| Артефакт | Состояние |
|---|---|
| Labels | готовы |
| **images.rar** | **9 675 931 636 B** в `data/external/benchmark_sources/mocs_yolo_hf/images.rar` |
| Маршрут | curl -L -C - + proxy 10808 (hf_hub завис на 0 B / обнулил incomplete) |
| Diagnostic | выполнен: `RESULTS_MOCS_DIAGNOSTIC.md` |

Kaggle по-прежнему optional (не блокер MOCS).
