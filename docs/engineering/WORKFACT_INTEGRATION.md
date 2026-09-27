# WorkFact — интеграция (три слоя)

Дата: 2026-09-26. Копия: `/home/dimk/my_project/LCT2026-workfact` → основная `/home/dimk/my_project/LCT2026`.

## 1. Реализовано и проверено в копии

### Архитектура
- `WorkFact` + `PlannedIndicator` + `IndicatorCheckResult` в `domain/contracts.py`
- Правила: `config/work_rules.yaml` (YAML ≠ реализация)
- Методы: `src/sitewatch/works/methods.py` + `floors_localize` как метод этажности
- Derive → `ActualState.work_facts`; план → `PlannedIndicator`; compare → `CheckOutcome`
- Deviation: `_work_checks` (не legacy `progress_keys`)
- Temporal: proven ratchet + revision down; proposed не даёт UI-max
- UI: `work_facts_summary`; миграция старых нулей/max в `_demote_legacy_floors`

### Проверки
- pytest: capture API + workfact + e2e demo green
- real sample 8/8 job_ok: `docs/engineering/workfact_sample_real_report.md`
- Открыто CV: house6 floors не proven до IoU с open-frame; office oversegment 3–4 vs 2

## 2. Перенос

Скрипт: `scripts/integrate_workfact_into_main.sh`  
Backup: `artifacts/backup-workfact-integrate/<stamp>/`

## 3. Фактически интегрировано в общую папку

**Сделано 2026-09-26** (без коммита):

| Путь | Статус |
|------|--------|
| `config/work_rules.yaml`, `config/perception.yaml` (+floors_localize) | в main |
| `src/sitewatch/works/` | в main |
| `domain/contracts.py`, `domain/enums.py` | в main |
| `ksg/expected.py`, `deviation/engine.py`, `pipeline/evaluate.py` | в main |
| `perception/{project,pipeline,floors_localize}.py` | в main |
| `cv/aggregator.py`, `temporal/state_engine.py`, `services/queries.py` | в main |
| `frontend/src/labels.ts`, `tests/test_workfact.py` | в main |
| docs/scripts sample + integration | в main |

Штатный путь в main:

```text
КСГ → PlannedIndicator
кадр → ObservedState (+ floors_localize evidence) → WorkFact → TemporalStateEngine
PlannedIndicator + WorkFact → CheckOutcome → Alert → API/UI
```

**Не заявлено:** holdout; перенос на другие площадки; proven этажность house6=6 / office=2 без open-frame match.
