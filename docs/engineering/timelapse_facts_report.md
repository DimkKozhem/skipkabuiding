# Отчёт: определение факта на таймлапсах (2026-09-26)

Матрица аудита: `docs/engineering/timelapse_work_matrix.md`  
Прогон: `validation/perception_regression/timelapse_recompute_report.json`  
Команда: `SITEWATCH_PERCEPTION_MODE=real SITEWATCH_QWEN_VL_ENABLED=true .venv/bin/python validation/perception_regression/recompute_timelapse_facts.py`

## 1. Почему результаты были неверными

| Причина | Эффект |
|---------|--------|
| `office_01` / `road_alley` ingest в `annotation` **без sidecar** | «Успех» с пустыми детекциями → нули → ложные `no_dynamics` / `schedule_delay` |
| `house6` ingest с `SITEWATCH_QWEN_VL_ENABLED=false` | Этажность только из SAM-боксов (17–23), затем отказ → 0 |
| SAM count `floor_slab` = этажи | Ложная этажность |
| Temporal: меньший кадр затирал больший `structural_levels` | Потеря накопленного факта (5→3) |
| Freshness от wall-clock | Архив 2016 → «качество недостаточно» |
| Ноль без evidence как факт | Plan/fact «0 этажей», «плиты 0» |

## 2. Что исправлено в рабочем пути

- Annotation: нет sidecar → `MissingAnnotationSidecarError` / HTTP 400 (явный пустой sidecar ≠ missing).
- Capture: пишет **явный** empty sidecar для live; upload без файла — ошибка.
- Этажи: только VLM/annotation `visible_floor_levels`; не SAM-боксы.
- Temporal ratchet: кадр не понижает confirmed floors.
- Freshness: выключенные камеры → `playback_mode=historical`, tip серии не stale.
- Progress count: count=0 + confidence=0 → `None`, не ноль.
- Ingest: office/road/house6 → `real` + Qwen on.
- Key-frame recompute 23 кадра: SAM+Qwen, сводка в отчёте JSON.

## 3. До / после (ключевые кадры)

| Объект | Работа | До | После (факт) | Ручная оценка | План (КСГ) | Совместимо? |
|--------|--------|-----|--------------|---------------|------------|-------------|
| house6 | floors early | 0 / мусор | **0** (VLM) + техника | котлован, 0 на участке | 0 | да |
| house6 | floors mid Jun | — | **3** + кран | ~3 уровня каркаса | superstructure | да |
| house6 | floors Sep | — | **5** | рост каркаса | →6 | близко |
| house6 | floors final | **0** | **5** (ratchet; VLM raw 3–4) | визуально **~6** | finishing 6 | **недочёт VLM (−1)** |
| office_01 | floors mid/final | **0** (пусто) | **2** | 2 этажа ясно | facade 2 | **да** |
| office_01 | техника | — | excavator/bulldozer | частично | facade | сигнал unexpected_equipment (проверить FP) |
| road_alley | meters | план 18 / факт — | план 18 / факт — | нет калибровки | 18 м | метры **не измеряем** |
| road_alley | активность | пусто / stale | real observe, on_plan | экскаватор/грунт видны | stages | техника на части кадров слабая; **не метры** |
| road_alley | freshness | «качество» | historical, не stale | кадр годный | — | да |

Сводка прогона: **queued=23 ok=23 err=0**, with_floors=17, with_equipment=12. Нулевой прогон по объекту объяснён только если annotation без sidecar (исправлено).

## 4. Доказательства

- Артефакты: `data/observations/artifacts/<run_id>/` (qwen_result, pipeline_run, observed_state).
- API витрина после пересчёта: house6 floors=5, office_01 floors=2, road_alley der=unavailable, playback=historical.
- Ручные просмотры: `/tmp/skripka_audit/{h,o,r}_*.jpg` (early/mid/final).

## 5. Работает / не работает

**Работает**

- Реальный SAM+Qwen на ключевых кадрах трёх таймлапсов.
- Офис: этажность 2 на финале подтверждена.
- Дом: траектория 0→2→3→5; техника на ранних/средних кадрах.
- Разделитель: нет ложной этажности и нет stale от 2016; метры честно не измеряются.
- Annotation без sidecar больше не создаёт ложный успех.

**Пока не закрыто**

- Финал house6: пользователь/визуал **6**, система **5** (VLM недосчитывает ряды окон; ratchet держит max=5). Не подогнано под план.
- Плотный daily recompute всех 243/358 кадров не гонялся (только key-frame сетка) — полный ряд дорогой по GPU.
- `dividing_line_m`: нет калибровки/homography → метрический plan/fact невозможен; признаки работ (техника/отсыпка) ещё нестабильны на части кадров.
- `unexpected_equipment` на office facade — может быть FP SAM; отдельный разбор не в этом прогоне.
- Seed-demo зоны zone_a/b/building_01 не пересчитывались здесь.

**Критерий «ложные карточки убраны» — недостаточен.** Закрытие по качеству факта: офис 2/2 ок; дом 5/6 частично; дорога — ограничение измерения явно зафиксировано.
