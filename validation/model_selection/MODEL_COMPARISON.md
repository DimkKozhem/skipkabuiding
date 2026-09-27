# Сравнение после прогонов и аудита 2026-09-27

Знаменатель манифеста: 11 кадров + 3 пары. Human GT accuracy: 0. Exact/MAE не считались.

**Потрачено на API (известно):** ≈ $0.004798 по ledger; 2 вызова с `cost_status=unknown` (не нули).  
Локальные прогоны тарифа не имеют.

Сопоставимость: см. `EXPERIMENT_AUDIT.md` §5. OpenRouter smoke **не** сопоставим с full local Qwen как selection.

## Что реально запущено

| Модель | Кадры | Статус | Числа/боксы | Отказы/ошибки | Время/память |
|---|---:|---|---|---|---|
| Qwen3-VL-8B text | 11+3 | run_complete_no_gt | 8 floors counts / 3 unknown | structured 36 unsupported | ~3.5 с; 21892 MiB занято |
| SAM 3.1 | 11 | run_complete_no_gt | боксы | FP техника на empty | 31 с; ~5.5 ГиБ |
| DINO base (myenv) | 11 | run_complete_no_gt | боксы | 0 на empty | load 10.9 с |
| YOLOE-11L | 1 smoke + 5 dev | smoke_passed | 0@0.25; 47@0.001 | — | cuda:1 |
| OR 235B | 1 (earth-1) | smoke completed | count=5 (фон) | — | pin deepinfra/fp8 |
| OR 397B | 1 | truncated → completed off | count=5 | length@400 | deepinfra/fp8 |
| OR Kimi | 1×3 attempts | 404 / truncated / timeout | нет parsed OK | seed, length, network | baidu/fp4 |

## Этажность Qwen8B (сырое, без GT)

| Кадр | count | refusal |
|---|---|---|
| s-dev-empty | unknown | да |
| s-dev-early | unknown | да |
| s-dev-frame | unknown | да |
| s-dev-earth-1 | 6 | нет (фон) |
| s-dev-earth-2 | 5 | нет |
| s-check-val | 6 | нет |
| s-check-pit | 6 | нет |
| s-check-office-a | 3 | нет |
| s-check-office-b | 3 | нет |
| s-check-openframe | 5 | нет |
| s-check-facade | 5 | нет |

Попадание 3 на office при agent_preliminary 2 **не** accuracy.

## Кто не в таблице качества

InternVL, FloorLevel-Net, Count*, Molmo*, ProgressLM — нет сопоставимого evaluated run. Их отсутствие ≠ проигрыш.

## Локализация, dev, без human box GT

Победитель не объявлен. TP/FP/FN нет: координаты окон не размечены, агентские метки к точности не относятся. Число этажей из числа окон не выводилось. Одинаковый порог не ранжирует модели: шкалы confidence разные. Строки после NMS — это выход после NMS, не сырые оценки до фильтрации. conf 0.25 — контрольная точка, не единственный критерий; precision/recall по порогам не считались, человеческие боксы не заполнены.

Старый baseline YOLOE-11L использовал `window_opening`. Новая конфигурация `yoloe11l_text_natural_v1` повторяет фразы YOLOE-26L: `window`, `window opening`, `door`, `column`. Старый прогон не заменён.

| Модель | checkpoint | input | conf 0.25, принятые боксы на 5 dev | После NMS, максимум | Память | Характер |
|---|---|---|---|---|---|---|
| YOLOE-11L, старые идентификаторы | yoloe-11l-seg.pt | 640 | 0/5 | на dev не снимался; офисный check максимум 0.0415 | 1266 МиБ | bus.jpg распознан |
| YOLOE-11L, те же фразы, что у 26L | yoloe-11l-seg.pt | 640 | 0/5 | 0.121, 0.102, 0.136, 0.018, 0.003 | не пересчитан отдельно | самые уверенные боксы — полосы по краю кадра |
| YOLOE-26L, те же фразы | yoloe-26l-seg.pt | 640 | 0/5 | 0.019, 0.020, 0.029, 0.020, нет боксов | 1043 МиБ | bus.jpg распознан; на стройке оценки ниже |
| YOLO-World V2.1 | l_stage1-7d280586.pth | 640 | 1, 1, 1, 1, 0 | 0.382, 0.383, 0.386, 0.313, 0.007 | 563 МиБ | bus.jpg: person и bus. На стройке принятые боксы — полосы по краю или ложная дверь |
| YOLO-World V2.1 | l_stage2-b3e3dc3f.pth | 1280 | 2, 2, 2, 0, 0 | 0.269, 0.478, 0.349, 0.083, 0.189 | 949 МиБ | тот же контроль person/bus. На кадре каркаса одна узкая column и полоса по краю. Режим 800 этого файла не запускался |

## Решение по локальным детекторам

Ни YOLOE-11L, ни YOLOE-26L, ни YOLO-World V2.1 (`l_stage1` при 640 и `l_stage2` при 1280) не локализуют окна, проёмы, двери и колонны на разрешённых dev-кадрах. Контроль bus.jpg у всех сработал: человек и автобус находятся. На стройке принятые рамки — полосы вдоль края кадра. У stage2 на `s-dev-frame` есть одна узкая рамка `column`; этого мало для покрытия. У stage1 на кадре без здания при 0.25 есть ложная `door`.

Отрицательный диагностический результат на этих пяти кадрах: статус `diagnostic_no_useful_localization`. Это не измеренный нулевой recall и не вывод о качестве всего семейства YOLO. Результат DINO на внешнем наборе экскаваторов сюда не входит. Новые YOLO, разрешения и промпты не запускать. Следующая проверка локализации — CountGD и MolmoPoint.
