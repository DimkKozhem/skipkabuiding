# MOCS extended eval v1 — DINO vs YOLOE-26L

Дата: 2026-09-27.  
**Не** официальный test MOCS (упаковка `AmiyaChan/mocs_yolo`, split `val`).  
Manifest (зафиксирован до inference): `manifests/mocs_extended_v1.json` + `mocs_extended_v1_COMPOSITION_LOCK.json`.  
Метрики: `reports/metrics_mocs_extended_v1.json`.  
Raw: `artifacts/model_selection/runs/external_equipment/mocs_extended/` (diagnostic не затёрт).

## Состав

| | |
|---|---|
| Источник | val HF; эпизоды `stem//20` **без** пересечения с diagnostic (38 eps) |
| Pool доступно | 62 eps / 850 кадров с equipment |
| extended_tune | **43** (только для resolution-эксперимента) |
| extended_eval | **197** |
| Equipment boxes (tune+eval) | small 683 / med 185 / large 99 |
| Пороги | **locked diagnostic**: DINO 0.2, YOLOE 0.2 (не перебирались на eval) |
| Resize | lock: YOLOE 640, DINO long-edge 800 |

## Результаты на extended_eval (197)

| Модель | Env | thr | AP50 | P | R | F1 | AP50 s/m/l | mean ms | peak MiB |
|---|---|---:|---:|---:|---:|---:|---|---:|---:|
| Grounding DINO | myenv cuda:1 | 0.2 | **0.477** | 0.602 | 0.549 | 0.574 | 0.124 / 0.509 / 0.538 | 323 | 2289 |
| YOLOE-26L | `.venv` cuda:1 | 0.2 | 0.460 | 0.685 | 0.531 | **0.598** | **0.195** / 0.351 / 0.248 | **28.5** | **311** |

Преимущество DINO по overall AP50 сохранилось узко (+0.017). По F1 и small AP50 впереди YOLOE. Универсального победителя **нет** — финальный выбор не объявляется.

### Per-class (strict, extended_eval)

См. JSON `by_class_strict`. Кратко (n_gt крупные):

| Класс | n_gt | DINO AP50 | YOLOE AP50 |
|---|---:|---:|---:|
| excavator | 229 | 0.099 | **0.248** |
| truck | 186 | 0.071 | **0.463** |
| static_crane | 182 | 0.000 | 0.000 |
| crane | 46 | **0.129** | 0.030 |

## Resolution tune (отдельный эксперимент, только extended_tune 43)

Файл: `reports/metrics_mocs_resolution_tune_v1.json`. Tiling не использовался. Победитель по tune **не** объявляется.

| Модель | config | AP50 | AP50_small (n=133) | peak MiB |
|---|---|---:|---:|---:|
| YOLOE-26L | lock 640 | 0.395 | 0.232 | 283 |
| YOLOE-26L | **hi 1280** | 0.378 | **0.294** | 757 |
| DINO | lock LE 800 | 0.341 | 0.118 | 2291 |
| DINO | **hi LE 1280** | 0.344 | **0.137** | 2291 |

На tune: увеличение разрешения **подняло AP на малых** у обеих (YOLOE сильнее: +0.062; DINO +0.019). Overall AP на tune не вырос однозначно (YOLOE даже чуть упал).

## Production / CMP

`config/perception.yaml`, DB, alerts, inspector — **не менялись**. CMP (окна/двери) этой задачей не закрыта.
