# Назначение owner, 2026-09-27

Handoff принят: `artifacts/model_selection/runs/molmopoint_excavator/OWNER_HANDOFF.md`.

Общий набор и общая оценка принадлежат experiment-owner. Два исполнителя не делят одну и ту же работу.

| Кто | Делает | Не делает |
|---|---|---|
| Агент MolmoPoint | Один измеримый результат MolmoPoint | CountGD, второй прогон экскаваторов, InternVL-загрузчик |
| Агент CountGD | Только CountGD | MolmoPoint inference, правку raw Molmo, второй загрузчик InternVL |

## Следующий прогон MolmoPoint — один

Приоритет окон и дверей на CMP сейчас **не выполняется**: CMP Facade по `external_equipment/OTHER_TASKS_DATA_GAPS.md` дал HTTP 404, локальной копии с разметкой окон и дверей нет. Пока набор и условия использования не проверены на диске, CMP не запускать.

Согласованный запасной прогон уже сделан и **не повторяется**: внешний экскаватор `miniexcav_excavator_v1`, те же изображения и splits, протокол `artifacts/model_selection/runs/molmopoint_excavator/POINT_PROTOCOL.json`. Метрики точек не сравнивать с bbox AP DINO. Сохранённые предсказания детекторов не пересчитывать.

## CountGD

Тот же протокол сопоставления точек, те же кадры экскаваторов, если веса и лицензия позволяют запуск. Если стек не собран — конкретный blocker, не нулевые метрики. Сырьё только в `artifacts/model_selection/runs/countgd_excavator/`. Общую таблицу пишет owner, не исполнитель.

## InternVL

Единственный загрузчик не трогать: pid из `artifacts/model_compare/internvl_download.pid`, скрипт `internvl_curl_resume.sh`. После `INTERNVL_READY` — проверка размеров одной revision и один smoke. Сервер Qwen не останавливать без отдельного окна GPU.

## Отчёт

Либо числа эксперимента, либо blocker. Строка про загрузку InternVL — дополнительно и не повод ждать.
