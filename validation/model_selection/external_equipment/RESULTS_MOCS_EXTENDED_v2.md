# MOCS extended v2 — ignore по размеру (без нового inference)

Метрики: `reports/metrics_mocs_extended_v2.json`.  
Legacy: `RESULTS_MOCS_EXTENDED.md`, `metrics_mocs_extended_v1.json` (`legacy_size_fp_inflation`).  
Eval: **197** кадров; пороги lock 0.2 / 0.2; resize не менялись.

## Таблица DINO vs YOLOE-26L (extended_eval)

| | DINO | YOLOE-26L |
|---|---:|---:|
| class-agnostic AP50 (обнаружение техники) | **0.477** | 0.460 |
| P / R / F1 (agnostic, thr lock) | 0.602 / 0.549 / 0.574 | 0.685 / 0.531 / **0.598** |
| macro AP50 / AP50–95 (equal weight, n_gt>0) | 0.029 / 0.022 | **0.083 / 0.060** |
| small AP50 (n_gt=**550**) | 0.300 | **0.328** |
| medium AP50 (n=165) | **0.775** | 0.559 |
| large AP50 (n=81) | **0.766** | 0.402 |
| mean ms / peak MiB (из raw runtime) | 323 / 2289 | **28.5 / 311** |

**Преимущество YOLOE на small после ignore сохранилось** (0.328 vs 0.300 на 550 GT).  
DINO остаётся сильнее на medium/large и чуть выше по class-agnostic AP50.

## Неопределённость ΔAP50 ≈ 0.017

Bootstrap по **эпизодам** (`stem//20`), n_episodes=**41**, n_boot=1000:

| | point AP50 | mean boot | 95% CI |
|---|---:|---:|---|
| DINO | 0.477 | 0.481 | [0.439, 0.525] |
| YOLOE | 0.460 | 0.459 | [0.418, 0.506] |

Интервалы **перекрываются**. Разницу 0.017 **не** считать уверенным преимуществом DINO.

## Роли (не production)

- **YOLOE-26L** — первый кандидат теневого пилота (дешевле по latency/VRAM, близкий agnostic результат; роль не из «победы на малых» alone).
- **DINO** — сравнительный кандидат (лучше medium/large).
- Выбор «победитель на малых» — по v2: YOLOE впереди на small, но общий выбор не объявляется одним числом.
