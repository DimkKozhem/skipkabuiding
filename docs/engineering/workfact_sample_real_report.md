# WorkFact real sample report

Generated: `2026-09-26T18:38:05.044079Z`
Qwen:8001 ok=True; SAM `cuda:1`; mode=`real`

| Sample | job_ok | floors | floors_status | WF certainty | notes |
|---|---|---:|---|---|---|
| house6_early | True | None | proposed | None/None |  |
| house6_mid | True | 2 | proposed | unknown/2 | floors not proven (expected until bands justify) |
| house6_final | True | 3 | proven | confirmed/3 |  |
| office_early | True | None | proposed | None/None |  |
| office_mid | True | 4 | proven | confirmed/4 | office floors count=4 expected~2 — band merge issue? |
| office_final | True | 3 | proven | confirmed/3 | office floors count=3 expected~2 — band merge issue? |
| road_early | True | None | None | None/None | dividing_line_m correctly unimplemented |
| road_final | True | None | None | None/None | dividing_line_m correctly unimplemented |

## Chain detail

### house6_early
```json
{
  "scene": {
    "visible_floor_levels": null,
    "floors_status": "proposed",
    "floors_derivation": "floor_bands_proposed",
    "structural_levels": null,
    "floor_bands_count": 0,
    "floor_bands_overlay": "/home/dimk/my_project/LCT2026-workfact/artifacts/workfact_sample/house6_early/floors/2026-01-02_8e40079e_levels.jpg",
    "floors_prove_reasons": [
      "building_focus_false",
      "no_bands"
    ],
    "observation_summary": "На кадре видно: 1 грузовик, 2 автокрана. По видимым признакам: признаки подъёмных работ. Соседние дома и дорога в расчёт не входят."
  },
  "work_facts": [
    {
      "indicator_id": "equipment:mobile_crane",
      "certainty": "contradiction",
      "value": null,
      "unit": "count",
      "method": "equipment_count",
      "limitations": [
        "конфликт моделей по технике"
      ]
    },
    {
      "indicator_id": "equipment:truck",
      "certainty": "confirmed",
      "value": 1,
      "unit": "count",
      "method": "equipment_count",
      "limitations": [
        "ресурсный факт; не объём выполненных работ"
      ]
    },
    {
      "indicator_id": "excavation_visible",
      "certainty": "confirmed",
      "value": true,
      "unit": null,
      "method": "excavation_visible",
      "limitations": [
        "признак земляных работ по технике в зоне; не объём выемки"
      ]
    }
  ],
  "checks": [
    {
      "indicator_id": "excavation_visible",
      "outcome": "match",
      "title": "Соответствие по признаку",
      "rationale": "Признак «excavation_visible»: план=True, факт=True.",
      "rule_id": "work.match_presence"
    }
  ],
  "stages": [
    {
      "name": "quality",
      "status": "success",
      "error": null,
      "latency_ms": 0.0
    },
    {
      "name": "sam3",
      "status": "success",
      "error": null,
      "latency_ms": 13060.08
    },
    {
      "name": "grounding_dino",
      "status": "skipped",
      "error": null,
      "latency_ms": 0.0
    },
    {
      "name": "qwen_vl",
      "status": "success",
      "error": null,
      "latency_ms": 11365.17
    },
    {
      "name": "floors_localize",
      "status": "success",
      "error": null,
      "latency_ms": 3180.42
    },
    {
      "name": "fusion",
      "status": "success",
      "error": null,
      "latency_ms": 0.0
    }
  ],
  "notes": [],
  "error": null
}
```

### house6_mid
```json
{
  "scene": {
    "visible_floor_levels": 2,
    "floors_status": "proposed",
    "floors_derivation": "floor_bands_proposed",
    "structural_levels": null,
    "floor_bands_count": 0,
    "floor_bands_overlay": "/home/dimk/my_project/LCT2026-workfact/artifacts/workfact_sample/house6_mid/floors/2026-05-01_38d5851b_levels.jpg",
    "floors_prove_reasons": [
      "building_focus_false",
      "no_bands"
    ],
    "observation_summary": "На кадре видно: 1 грузовик, 1 башенный кран. По видимым признакам: признаки монтажных работ башенным краном; видны элементы каркаса. Соседние дома и дорога в расчёт не входят."
  },
  "work_facts": [
    {
      "indicator_id": "equipment:tower_crane",
      "certainty": "confirmed",
      "value": 1,
      "unit": "count",
      "method": "equipment_count",
      "limitations": [
        "ресурсный факт; не объём выполненных работ"
      ]
    },
    {
      "indicator_id": "equipment:truck",
      "certainty": "confirmed",
      "value": 1,
      "unit": "count",
      "method": "equipment_count",
      "limitations": [
        "ресурсный факт; не объём выполненных работ"
      ]
    },
    {
      "indicator_id": "visible_floor_levels",
      "certainty": "unknown",
      "value": 2,
      "unit": "levels",
      "method": "floors_localize",
      "limitations": [
        "building_focus_false",
        "no_bands"
      ]
    }
  ],
  "checks": [
    {
      "indicator_id": "visible_floor_levels",
      "outcome": "insufficient_data",
      "title": "Недостаточно подтверждения факта",
      "rationale": "building_focus_false; no_bands",
      "rule_id": "work.insufficient_certainty"
    }
  ],
  "stages": [
    {
      "name": "quality",
      "status": "success",
      "error": null,
      "latency_ms": 0.0
    },
    {
      "name": "sam3",
      "status": "success",
      "error": null,
      "latency_ms": 13526.49
    },
    {
      "name": "grounding_dino",
      "status": "skipped",
      "error": null,
      "latency_ms": 0.0
    },
    {
      "name": "qwen_vl",
      "status": "success",
      "error": null,
      "latency_ms": 28183.31
    },
    {
      "name": "floors_localize",
      "status": "success",
      "error": null,
      "latency_ms": 4191.9
    },
    {
      "name": "fusion",
      "status": "success",
      "error": null,
      "latency_ms": 0.0
    }
  ],
  "notes": [
    "floors not proven (expected until bands justify)"
  ],
  "error": null
}
```

### house6_final
```json
{
  "scene": {
    "visible_floor_levels": 3,
    "floors_status": "proven",
    "floors_derivation": "floor_bands_proven",
    "structural_levels": 3,
    "floor_bands_count": 3,
    "floor_bands_overlay": "/home/dimk/my_project/LCT2026-workfact/artifacts/workfact_sample/house6_final/floors/2026-12-24_d0dd15b6_levels.jpg",
    "floors_prove_reasons": [],
    "observation_summary": "Строительной техники на кадре не отмечено. По видимым признакам: виден корпус с фасадом или кровлей, признаки отделочных работ. Соседние дома и дорога в расчёт не входят."
  },
  "work_facts": [
    {
      "indicator_id": "facade_visible",
      "certainty": "confirmed",
      "value": true,
      "unit": null,
      "method": "facade_visible",
      "limitations": [
        "подтверждает наличие признака, не завершение работы"
      ]
    },
    {
      "indicator_id": "roof_visible",
      "certainty": "confirmed",
      "value": false,
      "unit": null,
      "method": "roof_visible",
      "limitations": [
        "успешный пустой результат: признак не обнаружен в зоне"
      ]
    },
    {
      "indicator_id": "visible_floor_levels",
      "certainty": "confirmed",
      "value": 3,
      "unit": "levels",
      "method": "floors_localize",
      "limitations": []
    },
    {
      "indicator_id": "windows_visible",
      "certainty": "confirmed",
      "value": false,
      "unit": null,
      "method": "windows_visible",
      "limitations": [
        "успешный пустой результат: признак не обнаружен в зоне"
      ]
    }
  ],
  "checks": [
    {
      "indicator_id": "facade_visible",
      "outcome": "match",
      "title": "Соответствие по признаку",
      "rationale": "Признак «facade_visible»: план=True, факт=True.",
      "rule_id": "work.match_presence"
    },
    {
      "indicator_id": "roof_visible",
      "outcome": "deviation",
      "title": "Возможное отклонение: признак не наблюдается",
      "rationale": "План ожидает признак «видимый признак кровли (не завершение кровли)». Факт: не наблюдается. Это не вердикт о завершении работы.",
      "rule_id": "work.deviation_presence"
    },
    {
      "indicator_id": "windows_visible",
      "outcome": "deviation",
      "title": "Возможное отклонение: признак не наблюдается",
      "rationale": "План ожидает признак «видимые оконные проёмы (не завершение остекления)». Факт: не наблюдается. Это не вердикт о завершении работы.",
      "rule_id": "work.deviation_presence"
    },
    {
      "indicator_id": "visible_floor_levels",
      "outcome": "deviation",
      "title": "Возможное отклонение по показателю",
      "rationale": "План «число видимых этажей/уровней целевого корпуса в зоне наблюдения»: 6.0 levels. Факт: 3.0 levels. Подтверждает только этот индикатор, не завершение этапа.",
      "rule_id": "work.deviation_count"
    }
  ],
  "stages": [
    {
      "name": "quality",
      "status": "success",
      "error": null,
      "latency_ms": 0.0
    },
    {
      "name": "sam3",
      "status": "success",
      "error": null,
      "latency_ms": 1727.21
    },
    {
      "name": "grounding_dino",
      "status": "skipped",
      "error": null,
      "latency_ms": 0.0
    },
    {
      "name": "qwen_vl",
      "status": "success",
      "error": null,
      "latency_ms": 8691.53
    },
    {
      "name": "floors_localize",
      "status": "success",
      "error": null,
      "latency_ms": 15420.94
    },
    {
      "name": "fusion",
      "status": "success",
      "error": null,
      "latency_ms": 0.0
    }
  ],
  "notes": [],
  "error": null
}
```

### office_early
```json
{
  "scene": {
    "visible_floor_levels": null,
    "floors_status": "proposed",
    "floors_derivation": "floor_bands_proposed",
    "structural_levels": null,
    "floor_bands_count": 0,
    "floor_bands_overlay": "/home/dimk/my_project/LCT2026-workfact/artifacts/workfact_sample/office_early/floors/2022-06-01_7362f08b_levels.jpg",
    "floors_prove_reasons": [
      "building_focus_false",
      "no_bands"
    ],
    "observation_summary": "На кадре видно: 1 грузовик."
  },
  "work_facts": [
    {
      "indicator_id": "equipment:mobile_crane",
      "certainty": "unknown",
      "value": null,
      "unit": "count",
      "method": "equipment_count",
      "limitations": []
    },
    {
      "indicator_id": "equipment:truck",
      "certainty": "confirmed",
      "value": 1,
      "unit": "count",
      "method": "equipment_count",
      "limitations": [
        "ресурсный факт; не объём выполненных работ"
      ]
    },
    {
      "indicator_id": "foundation_visible",
      "certainty": "confirmed",
      "value": false,
      "unit": null,
      "method": "foundation_visible",
      "limitations": [
        "успешный пустой результат: признак не обнаружен в зоне"
      ]
    }
  ],
  "checks": [
    {
      "indicator_id": "foundation_visible",
      "outcome": "deviation",
      "title": "Возможное отклонение: признак не наблюдается",
      "rationale": "План ожидает признак «видимый признак фундамента или подиума (не завершение фундамента)». Факт: не наблюдается. Это не вердикт о завершении работы.",
      "rule_id": "work.deviation_presence"
    }
  ],
  "stages": [
    {
      "name": "quality",
      "status": "success",
      "error": null,
      "latency_ms": 0.0
    },
    {
      "name": "sam3",
      "status": "success",
      "error": null,
      "latency_ms": 1690.65
    },
    {
      "name": "grounding_dino",
      "status": "skipped",
      "error": null,
      "latency_ms": 0.0
    },
    {
      "name": "qwen_vl",
      "status": "success",
      "error": null,
      "latency_ms": 10408.0
    },
    {
      "name": "floors_localize",
      "status": "success",
      "error": null,
      "latency_ms": 3646.19
    },
    {
      "name": "fusion",
      "status": "success",
      "error": null,
      "latency_ms": 0.0
    }
  ],
  "notes": [],
  "error": null
}
```

### office_mid
```json
{
  "scene": {
    "visible_floor_levels": 4,
    "floors_status": "proven",
    "floors_derivation": "floor_bands_proven",
    "structural_levels": 4,
    "floor_bands_count": 4,
    "floor_bands_overlay": "/home/dimk/my_project/LCT2026-workfact/artifacts/workfact_sample/office_mid/floors/2022-09-28_5a0c1c22_levels.jpg",
    "floors_prove_reasons": [],
    "observation_summary": "На кадре видно: 1 бульдозер. По видимым признакам: признаки земляных работ и перемещения грунта. Соседние дома и дорога в расчёт не входят."
  },
  "work_facts": [
    {
      "indicator_id": "equipment:bulldozer",
      "certainty": "confirmed",
      "value": 1,
      "unit": "count",
      "method": "equipment_count",
      "limitations": [
        "ресурсный факт; не объём выполненных работ"
      ]
    },
    {
      "indicator_id": "visible_floor_levels",
      "certainty": "confirmed",
      "value": 4,
      "unit": "levels",
      "method": "floors_localize",
      "limitations": []
    }
  ],
  "checks": [
    {
      "indicator_id": "visible_floor_levels",
      "outcome": "match",
      "title": "Соответствие по показателю",
      "rationale": "План 2.0, факт 4.0 (visible_floor_levels).",
      "rule_id": "work.match_count"
    },
    {
      "indicator_id": "roof_visible",
      "outcome": "insufficient_data",
      "title": "Недостаточно данных по показателю",
      "rationale": "Нет WorkFact для индикатора «roof_visible».",
      "rule_id": "work.insufficient_data"
    }
  ],
  "stages": [
    {
      "name": "quality",
      "status": "success",
      "error": null,
      "latency_ms": 0.0
    },
    {
      "name": "sam3",
      "status": "success",
      "error": null,
      "latency_ms": 1951.93
    },
    {
      "name": "grounding_dino",
      "status": "skipped",
      "error": null,
      "latency_ms": 0.0
    },
    {
      "name": "qwen_vl",
      "status": "success",
      "error": null,
      "latency_ms": 24714.2
    },
    {
      "name": "floors_localize",
      "status": "success",
      "error": null,
      "latency_ms": 15936.69
    },
    {
      "name": "fusion",
      "status": "success",
      "error": null,
      "latency_ms": 0.0
    }
  ],
  "notes": [
    "office floors count=4 expected~2 — band merge issue?"
  ],
  "error": null
}
```

### office_final
```json
{
  "scene": {
    "visible_floor_levels": 3,
    "floors_status": "proven",
    "floors_derivation": "floor_bands_proven",
    "structural_levels": 3,
    "floor_bands_count": 3,
    "floor_bands_overlay": "/home/dimk/my_project/LCT2026-workfact/artifacts/workfact_sample/office_final/floors/2023-01-29_0ff7e204_levels.jpg",
    "floors_prove_reasons": [],
    "observation_summary": "На кадре видно: 1 экскаватор. По видимым признакам: признаки земляных работ и перемещения грунта."
  },
  "work_facts": [
    {
      "indicator_id": "equipment:excavator",
      "certainty": "confirmed",
      "value": 1,
      "unit": "count",
      "method": "equipment_count",
      "limitations": [
        "ресурсный факт; не объём выполненных работ"
      ]
    },
    {
      "indicator_id": "facade_visible",
      "certainty": "confirmed",
      "value": true,
      "unit": null,
      "method": "facade_visible",
      "limitations": [
        "подтверждает наличие признака, не завершение работы"
      ]
    },
    {
      "indicator_id": "roof_visible",
      "certainty": "confirmed",
      "value": false,
      "unit": null,
      "method": "roof_visible",
      "limitations": [
        "успешный пустой результат: признак не обнаружен в зоне"
      ]
    },
    {
      "indicator_id": "visible_floor_levels",
      "certainty": "confirmed",
      "value": 3,
      "unit": "levels",
      "method": "floors_localize",
      "limitations": []
    },
    {
      "indicator_id": "windows_visible",
      "certainty": "confirmed",
      "value": false,
      "unit": null,
      "method": "windows_visible",
      "limitations": [
        "успешный пустой результат: признак не обнаружен в зоне"
      ]
    }
  ],
  "checks": [
    {
      "indicator_id": "facade_visible",
      "outcome": "match",
      "title": "Соответствие по признаку",
      "rationale": "Признак «facade_visible»: план=True, факт=True.",
      "rule_id": "work.match_presence"
    },
    {
      "indicator_id": "roof_visible",
      "outcome": "deviation",
      "title": "Возможное отклонение: признак не наблюдается",
      "rationale": "План ожидает признак «видимый признак кровли (не завершение кровли)». Факт: не наблюдается. Это не вердикт о завершении работы.",
      "rule_id": "work.deviation_presence"
    },
    {
      "indicator_id": "windows_visible",
      "outcome": "deviation",
      "title": "Возможное отклонение: признак не наблюдается",
      "rationale": "План ожидает признак «видимые оконные проёмы (не завершение остекления)». Факт: не наблюдается. Это не вердикт о завершении работы.",
      "rule_id": "work.deviation_presence"
    },
    {
      "indicator_id": "visible_floor_levels",
      "outcome": "match",
      "title": "Соответствие по показателю",
      "rationale": "План 2.0, факт 3.0 (visible_floor_levels).",
      "rule_id": "work.match_count"
    }
  ],
  "stages": [
    {
      "name": "quality",
      "status": "success",
      "error": null,
      "latency_ms": 0.0
    },
    {
      "name": "sam3",
      "status": "success",
      "error": null,
      "latency_ms": 1832.66
    },
    {
      "name": "grounding_dino",
      "status": "skipped",
      "error": null,
      "latency_ms": 0.0
    },
    {
      "name": "qwen_vl",
      "status": "success",
      "error": null,
      "latency_ms": 26860.18
    },
    {
      "name": "floors_localize",
      "status": "success",
      "error": null,
      "latency_ms": 13165.47
    },
    {
      "name": "fusion",
      "status": "success",
      "error": null,
      "latency_ms": 0.0
    }
  ],
  "notes": [
    "office floors count=3 expected~2 — band merge issue?"
  ],
  "error": null
}
```

### road_early
```json
{
  "scene": {
    "visible_floor_levels": null,
    "floors_status": null,
    "floors_derivation": null,
    "structural_levels": null,
    "floor_bands_count": 0,
    "floor_bands_overlay": null,
    "floors_prove_reasons": null,
    "observation_summary": "Строительной техники на кадре не отмечено. Соседние дома и дорога в расчёт не входят."
  },
  "work_facts": [
    {
      "indicator_id": "divider_stage_sign",
      "certainty": "confirmed",
      "value": false,
      "unit": null,
      "method": "divider_stage_sign",
      "limitations": [
        "видимых признаков стадии разделителя нет"
      ]
    },
    {
      "indicator_id": "dividing_line_m",
      "certainty": "measurement_unimplemented",
      "value": null,
      "unit": "m",
      "method": "unimplemented",
      "limitations": [
        "метод измерения не реализован (запись YAML ≠ реализация)"
      ]
    }
  ],
  "checks": [
    {
      "indicator_id": "divider_stage_sign",
      "outcome": "deviation",
      "title": "Возможное отклонение: признак не наблюдается",
      "rationale": "План ожидает признак «визуальные признаки стадии разделителя (отсыпка/бордюр/техника)». Факт: не наблюдается. Это не вердикт о завершении работы.",
      "rule_id": "work.deviation_presence"
    },
    {
      "indicator_id": "dividing_line_m",
      "outcome": "measurement_unimplemented",
      "title": "Метод измерения отсутствует",
      "rationale": "План задаёт «dividing_line_m» (m), но метод измерения не реализован. Нужна калибровка/масштаб — не отставание графика.",
      "rule_id": "work.measurement_unimplemented"
    }
  ],
  "stages": [
    {
      "name": "quality",
      "status": "success",
      "error": null,
      "latency_ms": 0.0
    },
    {
      "name": "sam3",
      "status": "success",
      "error": null,
      "latency_ms": 1546.97
    },
    {
      "name": "grounding_dino",
      "status": "skipped",
      "error": null,
      "latency_ms": 0.0
    },
    {
      "name": "qwen_vl",
      "status": "success",
      "error": null,
      "latency_ms": 3910.47
    },
    {
      "name": "floors_localize",
      "status": "success",
      "error": null,
      "latency_ms": 1769.21
    },
    {
      "name": "fusion",
      "status": "success",
      "error": null,
      "latency_ms": 0.0
    }
  ],
  "notes": [
    "dividing_line_m correctly unimplemented"
  ],
  "error": null
}
```

### road_final
```json
{
  "scene": {
    "visible_floor_levels": null,
    "floors_status": null,
    "floors_derivation": null,
    "structural_levels": null,
    "floor_bands_count": 0,
    "floor_bands_overlay": null,
    "floors_prove_reasons": null,
    "observation_summary": "Строительной техники на кадре не отмечено. Соседние дома и дорога в расчёт не входят."
  },
  "work_facts": [
    {
      "indicator_id": "divider_stage_sign",
      "certainty": "confirmed",
      "value": false,
      "unit": null,
      "method": "divider_stage_sign",
      "limitations": [
        "видимых признаков стадии разделителя нет"
      ]
    },
    {
      "indicator_id": "dividing_line_m",
      "certainty": "measurement_unimplemented",
      "value": null,
      "unit": "m",
      "method": "unimplemented",
      "limitations": [
        "метод измерения не реализован (запись YAML ≠ реализация)"
      ]
    },
    {
      "indicator_id": "equipment:dump_truck",
      "certainty": "unknown",
      "value": null,
      "unit": "count",
      "method": "equipment_count",
      "limitations": []
    },
    {
      "indicator_id": "equipment:loader",
      "certainty": "unknown",
      "value": null,
      "unit": "count",
      "method": "equipment_count",
      "limitations": []
    }
  ],
  "checks": [
    {
      "indicator_id": "divider_stage_sign",
      "outcome": "deviation",
      "title": "Возможное отклонение: признак не наблюдается",
      "rationale": "План ожидает признак «визуальные признаки стадии разделителя (отсыпка/бордюр/техника)». Факт: не наблюдается. Это не вердикт о завершении работы.",
      "rule_id": "work.deviation_presence"
    },
    {
      "indicator_id": "dividing_line_m",
      "outcome": "measurement_unimplemented",
      "title": "Метод измерения отсутствует",
      "rationale": "План задаёт «dividing_line_m» (m), но метод измерения не реализован. Нужна калибровка/масштаб — не отставание графика.",
      "rule_id": "work.measurement_unimplemented"
    }
  ],
  "stages": [
    {
      "name": "quality",
      "status": "success",
      "error": null,
      "latency_ms": 0.0
    },
    {
      "name": "sam3",
      "status": "success",
      "error": null,
      "latency_ms": 1543.38
    },
    {
      "name": "grounding_dino",
      "status": "skipped",
      "error": null,
      "latency_ms": 0.0
    },
    {
      "name": "qwen_vl",
      "status": "success",
      "error": null,
      "latency_ms": 19527.14
    },
    {
      "name": "floors_localize",
      "status": "success",
      "error": null,
      "latency_ms": 3785.28
    },
    {
      "name": "fusion",
      "status": "success",
      "error": null,
      "latency_ms": 0.0
    }
  ],
  "notes": [
    "dividing_line_m correctly unimplemented"
  ],
  "error": null
}
```

## До / после и открытые CV-ошибки

| Объект/кадр | job | floors до (ожидание) | floors после | proven? | Вердикт факта |
|---|---|---:|---:|---|---|
| house6 early | ok | нет этажей | null proposed | no | ok: котлован |
| house6 mid | ok | partial | 2 proposed | no | ok: не proven |
| house6 final | ok | ~5–6 визуально | 3 | was proven→now needs open-frame | **открыто**: bands недосчитают; **не** подставлять 6 |
| office mid | ok | 2 | 4 | was wrongly proven | **открыто**: oversegment земля/парапет |
| office final | ok | 2 | 3 | was wrongly proven | **открыто**: oversegment |
| road | ok | meters N/A | unimplemented | n/a | ok: measurement_unimplemented |

После ужесточения `assess_floors_proven`: VLM-полосы без IoU с open-frame/GT → только `proposed` (не confirmed WorkFact). Office 3–4 и house6=3 не поднимают structural_levels.

