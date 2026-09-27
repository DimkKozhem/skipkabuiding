# Отбор после прогонов и аудита 2026-09-27

Победитель не установлен ни по одной задаче. Human GT с правом на accuracy: **0**. Verification split: **нет**.

Детали: `EXPERIMENT_AUDIT.md`, задания: `AGENT_TASKS.md`, протокол: `EXPERIMENT_PROTOCOL.md` v2.

| Задача | Выбранный | Runner-up | Что измерено |
|---|---|---|---|
| Этажность | не установлен | local Qwen8B (11 кадров); OR smoke только earth-1 | exact match нет; OR count=5 на котловане = фон |
| Окна и проёмы | не установлен | DINO/SAM/YOLOE/YOLO-World | precision/recall нет; на dev локальные детекторы не локализуют |
| Остальные работы | не установлен | сырой Qwen/SAM | `completion=complete` не факт |
| Техника | не установлен | SAM raw | фильтр подтверждения не применялся |
| Динамика | не установлен | Qwen на 3 парах | матрицы 4 классов нет |
| Локальный режим | baseline исполним: Qwen8B+SAM; DINO experimental myenv | YOLOE и YOLO-World smoke_passed | ветка YOLO закрыта отрицательным результатом; дальше CountGD/MolmoPoint |
| Удалённый режим | не установлен | 235B/397B/Kimi — только smoke | ledger known ≈$0.0048; matrix нет |

## Blocker

| Кандидат | Причина |
|---|---|
| OR matrix | нет нового grant; предыдущий smoke2 исчерпан; overrun истории сохранён |
| InternVL 8B / MolmoPoint | `download_incomplete` (PID живы) |
| InternVL 14B/241B | VRAM / нет endpoint |
| FloorLevel-Net | имя `.pth` не извлечено |
| CountGD / ++ / CountEx | стек/файлы не собраны |
| YOLOE / YOLO-World | smoke_passed. На dev рамки не являются окнами и проёмами. Ветка закрыта. Дальше CountGD и MolmoPoint. Precision/recall нет |
| ProgressLM | не скачан; ≠ % готовности |

Нужна человеческая разметка: `LABELING_PACKET.md`.
