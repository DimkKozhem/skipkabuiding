# Timelapse recompute WorkFact — summary

Updated: `2026-09-27T04:25:07.098132Z`
pipeline_version=`workfact-1` method=`floors_localize` v`Qwen/Qwen3-VL-8B-Instruct|qwen_floor_levels_v2.txt|c1a9b3a7c1eb`

| Series | frames on disk | journal total | ok | skipped | error |
|---|---:|---:|---:|---:|---:|
| house6 | 358 | 362 | 360 | 2 | 0 |
| office | 243 | 333 | 331 | 0 | 0 |
| road | 10 | 20 | 10 | 0 | 10 |

Totals: ok=701 skipped=2 error=10 wf_confirmed=0 wf_unknown=700

23 key-frames from prior report are a control sample only — not full recompute.
Open: house6 floors proven without open-frame IoU; office oversegment vs visual 2.
