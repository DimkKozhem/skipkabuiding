# Пакет разметки (human GT)

Назначение: закрыть `counts_toward_accuracy=false`.  
Разметчик — человек. Агент **не** заполняет эталонные числа.

Манифест: `validation/model_selection/manifest.json` (v2).  
Текущие agent labels: `validation/vlm_compare/labels.yaml` — только подсказка, не копировать в human.

## Правила

1. Плановые этажи КСГ, имя `house6`, leak_canary и ответы моделей **не** подсказка к числу.
2. Спорная этажность → `unknown` или `allowed_range`, не точный int.
3. `0` — только подтверждённое отсутствие объекта в **целевой** области.
4. Окно ≠ проём. Признак работ ≠ `completion=complete`.
5. Офисные даты файлов не использовать как календарь.
6. Holdout / sealed paths не открывать.

## Бланк по кадрам

Для каждого `sample_id` заполнить JSON-элемент (можно в копии `labels_human_draft.yaml`):

```yaml
- sample_id: s-check-office-a
  task: floors
  author: <имя>
  author_kind: human
  review_status: draft   # → accepted после второй проверки
  counts_toward_accuracy: false  # true только после accepted
  visibility: full|partial|none
  ambiguity: low|high
  value: null            # int или null
  allowed_range: null    # [lo, hi] или null
  expected_outcome: count|refusal|range|not_applicable
  target_region_ok: true
  notes: ""
```

### Обязательный минимум для разблокировки score

| sample_id | floors | elements (window / opening / roof / facade) | works (pit / foundation / facade_sign) | equipment |
|---|---|---|---|---|
| s-dev-empty | refusal/NA | — | — | false-positive check |
| s-check-office-a | count или range | presence + опц. боксы | facade/roof presence | — |
| s-check-office-b | count или range | presence | — | — |
| s-check-pit | refusal for target | — | pit present | presence/count |
| s-check-openframe | unknown/range OK | openings presence | — | — |
| s-check-facade | range OK | windows/facade/roof | facade_sign | — |
| s-dev-earth-1 | NA/refusal target | — | pit/foundation | presence |
| s-dev-earth-2 | NA/refusal | — | pit/foundation | presence |

### Боксы (если есть время)

На `s-check-office-a` crop/original:

- полилинии или xyxy полос этажей (кровля отдельно);
- ≥5 box `window` и ≥5 `window_opening` **если** различимы; иначе presence-only.

IoU matching: protocol v2 (≥0.3).

### Пары change

| pair_id | класс | notes |
|---|---|---|
| p-dev-earth | appeared\|changed\|no_visible_change\|incomparable | interval 4d reliable as filename series |
| p-check-office | … | interval **unreliable** |
| p-check-house | … | 161d filename delta; not schedule delay |

## Сдача

1. Файл draft → experiment-owner.
2. Owner ставит `accepted` + `counts_toward_accuracy=true` выборочно.
3. Запуск `sitewatch vlm-compare score` на существующих raw dirs.
