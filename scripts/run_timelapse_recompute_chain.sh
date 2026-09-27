#!/usr/bin/env bash
# Finish office (resume), then house6, then summary.
set -euo pipefail
cd /home/dimk/my_project/LCT2026
export SITEWATCH_PERCEPTION_MODE=real
export SITEWATCH_SAM3_DEVICE=cuda:1
export PYTHONPATH=src
LOG=artifacts/workfact_recompute_cache
mkdir -p "$LOG"
echo "WRAP_START $(date -Is)" >> "$LOG/chain.log"

# Wait if another office worker already running
while pgrep -f 'python -u scripts/timelapse_recompute_workfact.py --series office' >/dev/null \
   || pgrep -f 'python scripts/timelapse_recompute_workfact.py --series office' >/dev/null; do
  echo "wait_office $(date -Is)" >> "$LOG/chain.log"
  sleep 60
done

# Ensure office complete (idempotent resume)
.venv/bin/python -u scripts/timelapse_recompute_workfact.py --series office \
  >> "$LOG/office_run.log" 2>&1
echo "OFFICE_RC=$? $(date -Is)" >> "$LOG/chain.log"

.venv/bin/python -u scripts/timelapse_recompute_workfact.py --series house6 \
  > "$LOG/house6_run.log" 2>&1
echo "HOUSE6_RC=$? $(date -Is)" >> "$LOG/chain.log"

.venv/bin/python scripts/timelapse_recompute_workfact.py --summary-only
echo "ALL_DONE $(date -Is)" >> "$LOG/chain.log"
