# Матрица работ: таймлапсы site_001 (аудит 2026-09-26)

Числа пользователя/КСГ — только для проверки. План в perception не передаётся.

## Объекты и источники

| Объект | Кадры | Режим прогона | КСГ | Комментарий |
|--------|-------|---------------|-----|-------------|
| `house6` Жилой дом, 6 этажей | 358 | `real`, **Qwen выключен** (`SITEWATCH_QWEN_VL_ENABLED=false`) | `data/sources/house6_2026/ksg_2026.csv` | SAM без VLM → ложные этажи из боксов, затем сброс в 0 |
| `office_01` Офис, 2 этажа | 243 | `annotation` **без sidecar** | `data/sources/office_domodedovo/ksg.csv` | Пустые детекции = «успех» |
| `road_alley` Разделитель | 7–11 | `annotation` без sidecar | `data/sources/road_divider/ksg.csv` | Метры из плана; факт не измерялся; stale от wall-clock |

## Матрица: объект → работа → план → факт

| Объект | Работа / этап | Единица плана | Какой факт нужен | Что видно на кадрах (ручная оценка) | Способ | Реализовано? | В UI сейчас |
|--------|---------------|---------------|------------------|-------------------------------------|--------|--------------|-------------|
| house6 | excavation / site_setup | наличие/presence | земляные работы, техника | early: котлован, экскаваторы; соседний дом ≠ объект | SAM equipment + work_zone | частично (техника) | техника точечно; соседние дома мешают |
| house6 | foundation | presence | фундамент/подиум | mid: бетонный подиум | SAM foundation/wall | слабо | часто facade/roof без foundation |
| house6 | superstructure N этажей | floors count | видимые уровни каркаса | mid ~3 уровня дерева; final ~6 этажей фасада | **VLM visible_floor_levels** (не SAM count) | **нет в прогоне** (Qwen off) | 0 / «не определено» |
| house6 | facade / roof / finishing | presence | фасад, кровля | final: готовый фасад, окна, кровля | SAM facade/roof + VLM | частично SAM | facade/roof на финале есть |
| office_01 | foundation | presence | фундамент | early: площадка | real CV | **не запускался** | пусто |
| office_01 | superstructure | floors=1→2 | этажность каркаса | mid: **2 этажа** блоков, кровля | VLM floors | **не запускался** | 0 этажей |
| office_01 | facade / windows / roof | presence | фасад, окна, кровля | mid→final: панели, окна, мембрана | SAM+VLM | **не запускался** | пусто |
| road_alley | divider stages | dividing_line_m | длина м | нет калибровки/homography | метры с кадра | **нет оснований** | план 18 м, факт — |
| road_alley | divider progress | stage signs | отсыпка, техника, люди | final: экскаватор, грунт, рабочие | equipment + VLM scene | **не запускался** (annotation empty) | stale «качество» |

## Классификация текущего результата

| Случай | Статус |
|--------|--------|
| office/road annotation без sidecar | определение **не запускалось** (пустой успех) |
| house6 Qwen skipped | компонент **намеренно выключен** |
| house6 SAM floors→23 | метод **не справился** (боксы≠этажи) |
| house6 floors→0 после фикса | последствие отказа от ложного метода, **не** подтверждённый факт |
| road stale | ошибка **временной логики** (wall-clock), не качества кадра |
| road meters | **нет реализации** измерения |

## Цепочка дефектов

```
ingest (annotation|Qwen=off)
  → «успех» без наблюдений / без этажности
  → ActualState zeros
  → Temporal «стабильный ноль» / schedule gaps
  → ложные no_dynamics / schedule_delay
  → API/UI карточки с 0 и ложными сигналами
```
