# Очередь следующих действий (после аудита)

1. **Human GT** по `LABELING_PACKET.md` → `labels.yaml` (`author_kind=human`, accuracy=true где accepted). Без этого отбор победителей запрещён.
2. **experiment-owner:** `sitewatch vlm-compare score` на `vc-local-qwen8b-20260927` (+ SAM/DINO raw) только после п.1; OR earth-1 пометить incomparable для floors selection.
3. **openrouter-agent:** новый grant (утверждает owner) → 4 smoke из `AGENT_TASKS.md` C2 (office-a + pit; не earth-1 floors-positive; Kimi omit seed + reasoning-off). Успешные completed не повторять.
4. **local-models:** дождаться Molmo 8/8 и InternVL ready → `weights_verified` через owner → MolmoPoint smoke на office crop; YOLOE conf не трогать.
5. **FloorLevel-Net:** извлечь имя `.pth` из Drive listing без полного скачивания.
6. **Verification episode** вне sealed holdout — иначе любой shortlist только `provisional_familiar_check_only`.

Закрывает вопросы:
- «кто лучше по этажам?» → п.1 + сопоставимый multi-sample run ≥2 моделей + score (не smoke earth-1).
- «окна vs проёмы?» → box/presence GT + score SAM/DINO/YOLOE без смены conf ради ненуля.
- «удалённый режим жив?» → п.3 parsed success на office-a.
- «локализаторы готовы?» → п.4 weights_verified + smoke.
