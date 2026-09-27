# Индекс метрик external equipment

## miniexcav

| Файл | Эпоха / тег |
|---|---|
| `metrics_miniexcav_v1.original.json` | v1 полный test=171 (до rename size) |
| `metrics_miniexcav_v1.1.json` | v1.1 aHash-exclude test=165 (**история**) |
| `metrics_miniexcav_v1.1_neardup_excluded_pre_visual.json` | тот же снимок exclude |
| **`metrics_miniexcav_v1.2.json`** | **канон** visual-restored test=171 |
| `metrics_miniexcav_v1.json` | алиас → v1.2 |

## MOCS — legacy (`legacy_size_fp_inflation`)

Старая политика size-AP: preds вне бина считались FP. Не использовать для вывода «лучше на малых».

| Файл | Тег |
|---|---|
| `metrics_mocs_diagnostic_v1.original.json` | legacy_size_fp_inflation |
| `metrics_mocs_diagnostic_v1.json` | legacy_size_fp_inflation |
| `metrics_mocs_diagnostic_v1.1.json` | legacy_size_fp_inflation (+ уточнение знаменателей) |
| `metrics_mocs_diagnostic_sam_v1.json` | legacy_size_fp_inflation |
| `metrics_mocs_extended_v1.json` | legacy_size_fp_inflation |
| `metrics_mocs_resolution_tune_v1.json` | legacy_size_fp_inflation |

Отчёты legacy: `RESULTS_MOCS_DIAGNOSTIC.md` / `_v1.md` / `_v1.1.md`, `RESULTS_MOCS_EXTENDED.md`, `RESULTS_MOCS_SAM.md`.

## MOCS — v2 (ignore out-of-bin)

| Файл | Тег |
|---|---|
| **`metrics_mocs_diagnostic_v2.json`** | ignore_out_of_bin |
| **`metrics_mocs_diagnostic_sam_v2.json`** | ignore_out_of_bin |
| **`metrics_mocs_extended_v2.json`** | ignore_out_of_bin + episode bootstrap |
| **`metrics_mocs_resolution_tune_v2.json`** | ignore_out_of_bin |

Отчёты: `RESULTS_MOCS_*_v2.md`. Evaluator: `scripts/mocs_eval_v2.py`. Тест: `test_mocs_size_ignore_eval.py`.

## MOCS — v2.1 (normalize pred labels + class-aware audit)

| Файл | Тег |
|---|---|
| **`metrics_mocs_extended_v2.1.json`** | + normalize_pred_class; confusion; paired bootstrap |
| **`metrics_mocs_diagnostic_v2.1.json`** | то же на diag_test |
| Аудит | `../RESULTS_MOCS_CLASS_AWARE_AUDIT.md` |
| Роли | `../MOCS_PILOT_ROLES.md` |

v2 файлы **сохранены** (не overwrite).
