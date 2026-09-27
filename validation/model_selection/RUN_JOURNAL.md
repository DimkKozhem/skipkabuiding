# Журнал запусков 2026-09-27

Production DB, WorkFact, сигналы и UI не изменялись. Holdout не открывался.

Аудит 2026-09-27: см. `EXPERIMENT_AUDIT.md`. Ниже сохранены и локальные, и платные факты (ошибки/overrun не затирать).

## Qwen3-VL-8B

```bash
cd /home/dimk/my_project/LCT2026
.venv/bin/sitewatch vlm-compare run --execute --models local-qwen3-vl-8b \
  --out artifacts/vlm_compare/runs/vc-local-qwen8b-20260927
```

Сервер уже был на `127.0.0.1:8001`, cuda:0. 36 text `completed`, 36 structured `unsupported`. Cost 0. `scores.json`: exact=null (human GT нет). Статус: `run_complete_no_gt`.

## SAM 3.1

```bash
.venv/bin/python validation/model_selection/run_sam_baseline.py
```

11/11 success, cuda:1, overlays `artifacts/model_selection/runs/sam31_baseline/`. Статус: `run_complete_no_gt`.

## Grounding DINO base

`.venv` без `transformers` → прогон через `/home/dimk/my_project/myenv/bin/python`. 11/11 success. Статус: `run_complete_no_gt` (env = myenv).

## YOLOE-11L

Checkpoint: `artifacts/model_selection/weights/yoloe-11l-seg.pt`, 70982416 B, SHA-256 `a993fb0fc7c8830939ae14e6434a925dd1179428158c2761482eb8a8d8a3699f`, rev `b584da188a198a2e6aa0e013d3fef6d55b212603`.

- Smoke `s-check-office-a` conf 0.25 → 0 boxes (`yoloe11l_smoke`).
- Adapter bus.jpg → 6 boxes (`yoloe11l_adapter`).
- Prefilter conf 0.001 → 47 boxes, max 0.0415.
- Dev split 5/5 → 0 accepted boxes.
- Статус: `smoke_passed`, качество не оценено. Дальнейшая настройка порога остановлена.

## YOLOE-26L

`yoloe-26l-seg.pt`, 79417413 байт, SHA-256 `a612d2d505f24e14d87ec82d688b823b6cb600646664f16125ce6c84ce360da9` совпал с digest релиза `v8.4.0`. Энкодер `mobileclip2_b.ts`, не энкодер YOLOE-11. Пакеты в `.venv` не ставились: ultralytics 8.4.146 уже содержал модель.

- bus.jpg: 5 person + 1 bus, text_model `mobileclip2:b`.
- Dev, conf 0.25: 0/5. Dev, conf 0.001: максимум 0.029. Пик 1043 МиБ.
- Победитель не объявлен. Human box GT нет.

## YOLO-World V2.1

Отдельное окружение `.venv-yoloworld` (Python 3.11). Основная `.venv` не менялась: torch там `2.14.0+cu126`.

Связка, которая запустилась: torch `2.1.2+cu121`, torchvision `0.16.2`, mmcv `2.1.0` (колесо `cu121/torch2.1.0`, cp311), mmdet `3.3.0`, mmengine `0.10.3`, mmyolo `0.6.0`. README-пин torch 1.11 не использовался: для него нет колеса mmcv под эту видеокарту, а `docs/installation.md` прямо даёт mmcv 2.1.0 для torch 2.1/cu121.

Несовместимость, которую импорт показал дословно: `mmdet==3.0.0` → `AssertionError: MMCV==2.1.0 is used but incompatible. Please install mmcv>=2.0.0rc4, <2.1.0.`

`yolov8l-worldv2.pt` не подставлялся.

В `yolo_world.py` строка `self.text_feats, None = ...` — SyntaxError. Неиспользуемая маска заменена на `_`. Веса и config не менялись. `init_detector(..., palette="random")`: значение по умолчанию `none` пытается собрать LVIS только ради палитры, разметки LVIS на машине нет.

- checkpoint `l_stage1-7d280586.pth`, input 640. bus.jpg: 1 bus + 3 person, максимум 0.905. Dev conf 0.25: 1, 1, 1, 1, 0. Принятые боксы — полосы по краю; на `s-dev-empty` ложная door. Пик 563 МиБ.
- checkpoint `l_stage2-b3e3dc3f.pth`, 441517219 байт, SHA-256 `b3e3dc3f...a83f6` совпал с ETag. input 1280. Режим 800 того же файла не запускался. bus.jpg снова person и bus. Dev conf 0.25: 2, 2, 2, 0, 0. На `s-dev-frame` одна узкая column и полоса по краю. Пик 949 МиБ.

Прогоны: `artifacts/model_selection/runs/yoloworld_v21_l_stage1_res640/`, `.../yoloworld_v21_l_stage2_res1280/`.

## Решение ветки локальных детекторов

Статус на пяти dev-кадрах: `diagnostic_no_useful_localization`. Это не измеренный нулевой recall и не вывод обо всём семействе YOLO. DINO на внешнем наборе экскаваторов остаётся отдельным результатом.

Конфигурации и оверлеи: `artifacts/model_selection/runs/yoloe11l_text_v1`, `yoloe11l_text_natural_v1`, `yoloe26l_text_v1`, `yoloworld_v21_l_stage1_res640`, `yoloworld_v21_l_stage2_res1280`. Окружение `.venv-yoloworld` сохранено. Минимальная правка SyntaxError — `self.text_feats, _ =` в `artifacts/model_selection/third_party/YOLO-World/yolo_world/models/detectors/yolo_world.py`. К YOLO-World за ещё одним smoke не возвращаться.

## OpenRouter (платные smoke — не повторять успешные)

Ledger: `validation/vlm_compare/openrouter_attempt_ledger.json`.  
Pin: `config/vlm_compare_openrouter_pinned.yaml`. Reasoning-off: `config/vlm_compare_openrouter_reasoning_off.yaml`.

| run_dir | model | sample/task | status | cost |
|---|---|---|---|---|
| openrouter-smoke-2026-09-27 | 235B deepinfra/fp8 | s-dev-earth-1 floors | completed count=5 | $0.00044024 |
| same | 397B | same | truncated length@400 | $0.0020388 |
| same | Kimi baidu/fp4 | same | 404 unsupported (seed) | unknown |
| openrouter-smoke-kimi-2026-09-27 | Kimi | same | truncated | $0.001242614 |
| openrouter-smoke2-2026-09-27 | 397B reasoning-off | same | completed count=5 | $0.0010767 |
| same | Kimi reasoning-off | same | http_error/timeout | unknown |

Итого attempts: authorized 5, observed 6 (**overrun +1**). known cost ≈ $0.004798.  
Кадр earth-1 **не** floors-positive для целевого корпуса (см. protocol v2).

## floors_v2, диагностический пакет 2026-09-27

Run: `artifacts/vlm_compare/runs/openrouter-floors-v2-2026-09-27`.  
Конфиг: `config/vlm_compare_openrouter_qwen_floors_v2.yaml`. 12 HTTP, без retries.  
Известная стоимость $0.00646394. Четыре вызова без цены: три ConnectTimeout и HTTP 403 у 397B на `s-check-office-a`. В ноль не записывались.  
Accuracy не считалась: человеческих полей этажности нет, метки агента preliminary. Ответы floors_v1 в эту оценку не входили. Это отбор конфигурации, не оценка качества и не перенос в продукт.

Повторная валидация без нового inference, validator 2. Классификатор 2: фасад 235B — `task_spec_defect`, не ошибка модели. `accuracy = null`, `support = 0`. `floors_v3` заморожен. Предложение считать полосы снято. Два протокола: `validation/vlm_compare/protocols/cmp_windows_doors.yaml` и `validation/vlm_compare/protocols/floorlevel_boundaries.yaml`. Видимое целое число этажей — `blocked_no_ground_truth`. Обе лицензии — `license_unresolved`. 403 по-прежнему без причины.

## Загрузки в фоне (аудит, не kill)

- InternVL3.5-8B snapshot_download: PID из `artifacts/model_compare/internvl_download.pid` — `download_incomplete`.
- MolmoPoint-8B: загрузка завершена, 8/8, ревизия `188130f961c8e0888a34e11121a1423c461a01ba`, smoke_passed. Повторно не качать.

## Не готовы к inference

FloorLevel-Net (нет имени `.pth`), CountGD++, CountEx, Molmo2, ProgressLM, InternVL14B/241B. CountGD text-only уже выполняет inference; статус `inference_ran`, не `blocked`.

## Внешний equipment benchmark 2026-09-27

Каталог: `validation/model_selection/external_equipment/` (отдельно от Skripka manifest).  
Источник с боксами: miniexcav 218 dedup / tune47 test171.  
Сравнение на `cuda:1`: Grounding DINO (myenv), YOLOE-11L, YOLOE-26L. Raw: `artifacts/model_selection/runs/external_equipment/`. Метрики: `external_equipment/RESULTS.md`.  
Kaggle/Roboflow из пятёрки ссылок — без ключа / 403. `construction_equipment_v1` не использован как независимый test (SAM-proposals + уже в train локального YOLO).

## Окна и проёмы, CountGD и MolmoPoint, 2026-09-27

Ветка YOLO на пяти dev-кадрах закрыта со статусом `diagnostic_no_useful_localization`. Это не измеренный нулевой recall и не вывод о всём семействе. DINO на внешнем наборе экскаваторов остаётся отдельным.

MolmoPoint-8B, ревизия `188130f961c8`, родной `extract_image_points`. Полный bf16 не входит в 4060. Прогон: реальные веса, 12 блоков на CPU, остальное на `CUDA_VISIBLE_DEVICES=1`. Пять кадров × три замороженных запроса: `artifacts/model_selection/runs/molmopoint_windows_dev/`. Прежние 23 точки — это `s-check-office-b`, не эти пять кадров: `artifacts/model_compare/molmo/points_23_meaning.json`.

CountGD `checkpoint_fsc147_best.pth` (1250122522 байт), text-only, порог 0.23. CUDA op не собран: в системе нет nvcc, attention — чистый PyTorch на CPU, torch 2.1.2 из `.venv-yoloworld`. Прогон: `artifacts/model_selection/runs/countgd_text_windows_dev/`. Visual exemplar на пяти кадрах не запускался: пример на объекте не отмечен, окно соседнего дома не использовалось (`validation/model_selection/countgd_visual_exemplars.json`).

На пяти кадрах полезной локализации объекта нет. Исключение частичное: `s-dev-early`, проёмы кладки. На остальных точках и рамках — соседний дом, стекло машины или пустой ответ. Лист: `artifacts/model_selection/runs/window_localization_sheet.html`.

Два CMP-эксперимента разведены в `validation/model_selection/cmp_protocol_reconciliation.json`. Owner tech package — восемь development-кадров base/extended и `cmp_point_eval.py`. Первые восемь base — отдельный эксперимент. `cmp_b0003` принадлежит test и уже просмотрен, в нетронутую проверку не входит. Общий протокол не менялся.

CountGD на этих восьми, окна, IoU ≥ 0.3: n_pred 293, TP 29, FP 264, FN 246, n_gt 275. Precision 9.9%, recall 10.5%. Критерий «центр GT внутри рамки» метрикой не является. Checkpoint sha256 `c1bab864…aa126`. CPU attention — штатная функция `multi_scale_deformable_attn_pytorch`, оба файла в дереве CountGD совпадают.

Сохранённые точки MolmoPoint пересчитаны тем же matcher без нового inference. На `cmp_b0001` window это один запуск: n_pred 12, TP 3, FP 9, FN 71. Хвост текста содержит диапазон `30–39` без координат. `cmp_b0002` window обрезан лимитом 512: n_pred 9, TP 4, FP 5, FN 20. Пакет остановился по OOM после двери `cmp_b0002` и с тем же лимитом не продолжался.

Полный кадр Скрипки с текстом «каждое видимое окно» не задавал целевой корпус. Фиксированный кроп из уже записанного `crop_xyxy` подготовлен и не запускался: `validation/model_selection/localization_target_region_frozen.json`.

Следующий пакет MolmoPoint — не эти 8 id и не все 606. Splits: `validation/model_selection/cmp_facade_splits.json` (development 365, test 241). Технические 8 кадров development: `cmp_molmopoint_tech_package.json`. Сопоставление точек — максимальная мощность, пересечения остаются в знаменателе. FloorLevel-Net: `annotation_semantics_unresolved`, из количественного отбора выведен.

## 2026-09-27 — CMP Facade license + diagnostic eight vs cmp-tech

Лицензия **CMP Facade** (только этот набор; не FloorLevel, не floor_gt_proposal): **CC BY-SA 3.0**. Источник: `artifacts/model_selection/runs/cmp_prepare/STATUS.md`. URL со страницы авторов: `https://creativecommons.org/licenses/`, бейдж `https://licensebuttons.net/l/by-sa/3.0/88x31.png`. Страница набора: `https://cmp.felk.cvut.cz/~tylecr1/facade/`. Дата проверки: 2026-09-27. Область: исследовательское использование с указанием авторства и ShareAlike; в продукт и внешний API без отдельного решения не выносить. Обновлены только материалы CMP: `validation/vlm_compare/protocols/cmp_windows_doors.yaml`, строка CMP в `OTHER_TASKS_DATA_GAPS.md`, поле `license` в `cmp_molmopoint_tech_package.json`. Исторический абзац выше с `license_unresolved` не переписывался.

Диагностический run первых восьми base (`cmp_b0001`…`cmp_b0008`) зафиксирован отдельно: `artifacts/model_selection/runs/molmopoint_cmp_facade/RUN_RECORD.json`, команда `run_molmopoint_dev.py cmp`. Это **не** `cmp-tech` и не пакет `cmp_molmopoint_tech_package.json` (кадры cmp_b0146, cmp_b0045, cmp_b0344, cmp_b0091, cmp_x0155, cmp_x0038, cmp_x0045, cmp_x0027). Официального train/test у CMP нет — только base/extended; восемь помечены used_for_diagnostics. Независимая оценка дальше — вне этих восьми и вне списка cmp-tech; в общий owner manifest новые split не добавлялись. В `model_registry.yaml` у MolmoPoint `next_step` больше не зовёт cmp-tech как следующий шаг этого прогона; cmp-tech остаётся отдельной записью.

## CountGD: CPU выполнен, GPU не готов

Опубликованный прогон — `.venv-yoloworld`, torch `2.1.2+cu121`, CPU, `multi_scale_deformable_attn_pytorch`. Конфигурация: `artifacts/model_selection/runs/countgd_text_windows_dev/published_run_env.json`. Torch `2.2.1` в `.venv-countgd` к этим предсказаниям не относится. Статус: `cpu_inference_done`, `gpu_environment: not_ready`. Неполный cuDNN переименован в `/tmp/countgd-wheels/nvidia_cudnn_cu12-8.9.2.26.INCOMPLETE` (438362112 байт из 731725872), не установлен. Повторная загрузка остановлена: ближайшего GPU-задания нет. Сохранённые рамки оцениваются без этого файла.

## CountGD: технический вопрос закрыт

CPU-прогон воспроизводим, окружение — `published_run_env.json`. На первых восьми base, окна, text-only, IoU ≥ 0.3: precision 9.9%, recall 10.5%. Это слабый результат проверенной конфигурации; в продукт её не внедрять. GPU-загрузки и настройка CountGD не возобновляются. Новый inference не нужен.

Следующее действие у owner: пересчёт сохранённых результатов по согласованному протоколу и сопоставление с завершённым MolmoPoint на общих кадрах. Сравнение рамок и точек требует одной явно названной метрики. Текущий bbox-результат остаётся отдельной записью. Завершённый MolmoPoint на этих восьми есть у `cmp_b0001` (окно и дверь) и у двери `cmp_b0002`. Окно `cmp_b0002` обрезано и в завершённые не входит.

## CountGD закрыт, сравнение с MolmoPoint не завершено

bbox IoU ≥ 0.3 на восьми фасадах сохранён: precision 9.9%, recall 10.5%, 293 рамки на 275 окон, TP 29. Новый inference CountGD не запускался.

Отдельная метрика попадания: центр каждой сохранённой рамки сопоставлен тем же matcher, что точки MolmoPoint (`countgd_center_point_matching.json`). На восьми кадрах, окна: TP 47, FP 246, FN 228, precision 16.0%, recall 17.1%. Это не замена IoU и не сравнение с неполным MolmoPoint.

Общая метрика полных пар — попадание точки или центра в объект, максимальная мощность. Пары только три, победителя нет (`common_task_comparison.json`):

- `cmp_b0001` окно: CountGD 13/73 при 74 GT, MolmoPoint 3/12.
- `cmp_b0001` дверь: оба 0 попаданий.
- `cmp_b0002` дверь: оба 0 попаданий.

Окно `cmp_b0002` обрезано лимитом 512 и в эти пары не входит: MolmoPoint 4/9 при 24 GT. `cmp_b0003`–`cmp_b0008` у MolmoPoint не запускались из-за OOM. Это отсутствие результата, не визуальные FN.

OOM: склейка эмбеддингов `lm_head` запросила 1.16 ГиБ при 459 МиБ свободных. Свой процесс держал 12.36 ГиБ, чужой процесс 309489 — 2.37 ГиБ, процесс 2045 — 362 МиБ. Чужие процессы не останавливались. Фрагментация не причина: незанятый резерв PyTorch 95 МиБ.

`cmp_b0003` остаётся test в исходном `cmp_facade_splits.json`. Факт просмотра и проверочная выборка v2 (240 нетронутых test из 241): `cmp_facade_verification_v2.json`.

Генерация v2 записана отдельно: `molmopoint_generation_v2.json`, лимит 8192, тот же промпт и bf16, другой каталог. Лимит 512 больше не запускается.

На пяти кадрах Скрипки текущие задания не дали полезного результата для целевого объекта, потому что цель не была задана однозначно. Это не доказательство, что модели не могут найти его окна. В продукт из этой ветки переносить нечего.

## MolmoPoint: blocked_memory

Автоматические повторы остановлены. Новых ответов 0. Статус `blocked_memory`. Сохранённое сравнение трёх полных пар остаётся действительным.

Первый сбой — нехватка RAM при загрузке шарда 6, 48 МиБ, до размещения на GPU. Второй — нехватка VRAM на склейке `lm_head`, запрос 1.16 ГиБ. Размещение было динамическим: 12 блоков на CPU в первом прогоне и 16 во втором. Чужой процесс держал 2.37 ГиБ и 3.77 ГиБ в этих двух случаях. Его завершение освободило бы память, но вместимость всего inference этим не доказана. Чужие процессы не останавливались.

План одного запуска, не вооружён: `validation/model_selection/molmopoint_launch_plan.json`. Окно owner не согласовано: нужны GPU, доступная RAM, время освобождения и владелец запуска. Остановка других сервисов — только по согласованию. Число CPU-блоков этой конфигурации заморожено: 36. `cmp_b0045` — стресс-тест исполнения, не критерий качества. Успех исполнения: загрузка, ответ без OOM и без обрезки, декодированные координаты. Найдены ли 311 окон — отдельно. Resume пакета только после этого успеха. Если снова не помещается — конфигурация непригодна для текущего бюджета, без повторов на удачу. До окна приоритет готовой работы: исправленный пересчёт MOCS и проверка изоляции теневого пилота. Они MolmoPoint не требуют.

Уточнение окна: 36 decoder-блоков на CPU нагружают RAM и могут сильно замедлить генерацию. 8192 — лимит, не гарантия перечисления 311 окон; завершение без обрезки не доказывает полноту обнаружения. Приоритет: Qwen3.5-397B, затем MOCS и изоляция пилота, MolmoPoint последним.

Qwen3.5-397B, отдельная версия без нового вызова: `artifacts/vlm_compare/runs/qwen3.5-397b-three-objects-v1/scores.json`. Три завершённых объекта: `s-check-pit` (этажность не применима), `s-check-facade` (видимых уровней 5), `s-check-office-b` (видимых уровней 2). Три ответа с http_error в эту версию не входят. Accuracy нет: метки предварительные.

Изоляция пилота техники: `tests/test_shadow_isolation.py` прошёл. Кадр пилота не входит в plan/fact. Исправленные метрики MOCS остаются в `metrics_mocs_diagnostic_v1.1.json`.

