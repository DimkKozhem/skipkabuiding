# Распределение классов и размеров

Файл порогов: `size_bins_locked.json` (`locked_before_metrics: true`).

**Имена бинов — relative area, не COCO:**

| Имя | Условие (`area_ratio = box_area / image_area`) |
|---|---|
| `relative_area_small` | &lt; 0.04 |
| `relative_area_medium` | [0.04, 0.16) |
| `relative_area_large` | ≥ 0.16 |

Ранее в текстах встречались ярлыки `small/medium/large` — это те же relative_area пороги, **не** стандартные COCO pixel bins (32² / 96²).

## miniexcav_excavator_v1 (после sha256-dedup, 218 images / 218 boxes)

| класс (mapped) | n_boxes |
|---|---:|
| excavator | 218 |

| relative_area bin | n_boxes |
|---|---:|
| relative_area_small | 1 |
| relative_area_medium | 0 |
| relative_area_large | 217 |

Единственный `relative_area_small` объект показывается отдельно в метриках; по нему нельзя судить о мелкой технике.

Характер набора: **крупноплановые** экскаваторы (автор советует избегать small/far).

Splits: tune 47 / test 171; v1.1 после визуального разбора: scored test **171** (aHash-исключения сняты; см. NEAR_DUP_VISUAL_REVIEW.md).
