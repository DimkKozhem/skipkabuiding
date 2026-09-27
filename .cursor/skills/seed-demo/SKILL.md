---
name: seed-demo
description: Пересобрать demo Скрипки и поднять UI/API. Use when resetting demo data or starting the prototype.
disable-model-invocation: true
---

# seed-demo

```bash
cd /home/dimk/my_project/LCT2026
source .venv/bin/activate
sitewatch seed-demo
sitewatch ui           # http://127.0.0.1:8000
```

`seed-demo` пересоздаёт SQLite demo. Не запускать против не-demo базы.

Проверка: `zone_a` без missing_equipment; `zone_b` missing_equipment; `building_01` `no_dynamics` + `schedule_delay`.

Формулировка no-dynamics: «Выявлены признаки отсутствия строительной динамики. Требуется проверка.»

UI после seed (живые маршруты):

- `/` — `zone_a`, норма без ложного сигнала
- `/signals` — `zone_b` `missing_equipment`; `building_01` `no_dynamics` + `schedule_delay`
- `/objects/:zoneCode` — карточка объекта

Aliases `/queue` `/dashboard` `/timeline` `/alerts` — redirects, не главные страницы QA.
