# Floors localize experiment

Generated: `2026-09-26T09:57:51.825578+00:00` (localize re-run after prompt tighten; numeric from first pass)

Goal: check whether localize→bands recovers real levels (not force answer 6).

| Case | GT | Numeric | Bands | Band recall | Band precision |
|---|---:|---:|---:|---:|---:|
| house6_final | 6 | 4 | 7 | 1.0 | 0.857 |
| house6_frame | 4 | 4 | 5 | 0.75 | 0.6 |
| office_final | 2 | 3 | 4 | 1.0 | 0.5 |

## Verdict

### house6_final (фасад, план 6)
- Numeric Qwen: **4** (как раньше — пропускает низ).
- Localize: **7** полос; recall к GT=1.0, +1 FP (часто кровля/парапет).
- Важно: L1 с cues storefront/canopy — **коммерческий низ локализован**, чего scalar 4 не давал.
- Overlay: `overlays/*_levels.jpg` рядом с `house6_final_gt.jpg`.

### house6_frame (открытый каркас)
- Numeric: **4** (совпало с GT count).
- Localize после правки промпта: **5** полос (раньше было 0 — модель молчала на каркасе).
- Полезно как evidence уровней, но координаты/слияние ещё шумят; не брать max числа в temporal.

### office_final (контроль 2 этажа)
- Numeric: **3**; Localize: **4**.
- Контроль **не пройден**: земля/парапет/кровля попадают в полосы. Метод пока пересегментирует.

## System implications

| Показатель | Смысл |
|---|---|
| Наблюдение финального кадра | Scalar=4; localize видит низ, но count не = GT |
| Историческое (каркас) | Scalar=4; localize даёт полосы, нужна сверка overlay |
| Подтверждённая этажность | Только proven levels + evidence, не max(proposed) |
| Сравнение с планом 6 | Пока нет надёжного confirmed факта отставания |

Temporal: `floors_status=proposed|proven`; structural_levels обновляется только из proven.

Conclusion: localize→overlay улучшает проверяемость и находит коммерческий низ на доме,
но одного VLM-ответа всё ещё недостаточно для доказанной этажности (office ломается,
кровля/земля дают FP). Нужен отдельный способ локализации конструктивных уровней
или human/inspector confirm полос.
