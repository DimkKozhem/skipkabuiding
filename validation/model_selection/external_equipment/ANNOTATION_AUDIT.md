# Проверка аннотаций (external equipment v1)

## miniexcav_excavator_v1

| Проверка | Результат |
|---|---|
| Изображения | 223 jpg |
| Label-файлы | 223 txt, по одному на изображение |
| Пустые labels | 0 |
| Боксы | 223 (ровно 1 на кадр) |
| Классы в labels | только id `0` |
| sha256-дубликаты | 5 групп (10 файлов); в benchmark оставлен 1 на группу → 218 |
| Официальный split | нет → tune 47 / test 171 по sha1(stem) |
| Тип | YOLO bbox (cx,cy,w,h normalized) |
| Полнота | подтверждена только для excavator |
| Характер размера | area_ratio: 217 large, 1 small, 0 medium (пороги зафиксированы до метрик) |

Вывод: набор пригоден для **количественной** детекции excavator на крупном плане. Не пригоден как стресс-тест мелкой/дальней техники.

## Остальные из пяти ссылок

См. `DATASET_REGISTRY.md`: Kaggle без ключа; Roboflow 403 / 0 published versions.

## construction_equipment_v1 (не в пятёрке)

Commons-боксы = SAM proposals ≠ human GT. Safety COCO = human, но уже в train локального YOLO. Не использован как независимый test этого цикла.
