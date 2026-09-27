# Perception real-image validation

Put construction JPEGs here for manual / CLI benchmark.

## Layout

```text
validation/perception/
  manifest.json
  cases/<case_id>/
    image.jpg
    expected.json   # optional if listed only in manifest
  predictions/      # created by sitewatch perception-benchmark
```

## expected.json example

```json
{
  "id": "site_a_cam1_001",
  "image": "cases/site_a_cam1_001/image.jpg",
  "expected_visible_classes": ["column", "floor_slab", "excavator"],
  "expected_counts": {"column": 10, "excavator": 1},
  "expected_visibility_limitations": ["foundation occluded"],
  "notes": "pilot frame"
}
```

## Run

```bash
SITEWATCH_PERCEPTION_MODE=real \
sitewatch perception-benchmark validation/perception/
```

Do **not** commit heavy private site media. Keep only tiny fixtures or placeholders in git.
