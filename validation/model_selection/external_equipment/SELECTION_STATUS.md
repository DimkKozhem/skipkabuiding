# Статус отбора моделей (external equipment)

Production (`config/perception.yaml`, DB, alerts, inspector, `missing_equipment`) — **не изменён**.

## miniexcav (закрыт)

| Поле | Значение |
|---|---|
| status_id | `selected_external_large_excavator` |
| metrics | `reports/metrics_miniexcav_v1.2.json` |

## MOCS — после class-aware audit (v2.1)

Канон size: ignore_out_of_bin (`*_v2.json`).  
Канон типов/имён: `*_v2.1.json` + `RESULTS_MOCS_CLASS_AWARE_AUDIT.md`.  
Роли пилота: `MOCS_PILOT_ROLES.md`.

| Модель | Роль |
|---|---|
| **YOLOE-26L** | теневой пилот «предположительно техника» |
| **Grounding DINO** | сравнение (medium/large) |
| YOLO-World | отдельные классы (reserve) |
| SAM 3.1 | experiment; не автофакты |
| YOLOE-11L | baseline-frozen |

**Ограничение:** детекция техники (class-agnostic) пригодна для пилотной проверки; **классификация типов слабая** (аудит подтвердил; не баг class-id). Тип — только через инспектора.

## Аудит закрыт (2026-09-27)

Пересчёты рейтинга остановлены. Преимущество DINO по обнаружению не доказано (парный интервал разности включает ноль). YOLOE лучше по типу на этой выборке, абсолютное качество типа низкое. 40,9% — верный тип только среди геометрических совпадений.

Дальше: ограниченный пилот YOLOE-26L (рамка «предположительно техника») и просмотр кандидатов на трёх объектах. DINO — сравнение. Qwen3.5-пересчёт — отдельная ветка.
