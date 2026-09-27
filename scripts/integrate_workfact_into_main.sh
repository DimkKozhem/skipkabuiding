#!/usr/bin/env bash
# Address-copy WorkFact slice from LCT2026-workfact → LCT2026.
# Does NOT commit. Backs up targets under artifacts/backup-workfact-integrate/.
set -euo pipefail
WF=/home/dimk/my_project/LCT2026-workfact
MAIN=/home/dimk/my_project/LCT2026
STAMP=$(date +%Y%m%d%H%M%S)
BACKUP="$MAIN/artifacts/backup-workfact-integrate/$STAMP"
mkdir -p "$BACKUP"

backup_one() {
  local rel="$1"
  if [ -e "$MAIN/$rel" ]; then
    mkdir -p "$BACKUP/$(dirname "$rel")"
    cp -a "$MAIN/$rel" "$BACKUP/$rel"
  fi
}

PATHS=(
  config/work_rules.yaml
  config/perception.yaml
  src/sitewatch/works
  src/sitewatch/domain/contracts.py
  src/sitewatch/domain/enums.py
  src/sitewatch/ksg/expected.py
  src/sitewatch/perception/project.py
  src/sitewatch/perception/floors_localize.py
  src/sitewatch/perception/pipeline.py
  src/sitewatch/cv/aggregator.py
  src/sitewatch/temporal/state_engine.py
  src/sitewatch/deviation/engine.py
  src/sitewatch/pipeline/evaluate.py
  src/sitewatch/services/queries.py
  frontend/src/labels.ts
  tests/test_workfact.py
  docs/engineering/WORKFACT_INTEGRATION.md
  docs/engineering/workfact_sample_expectations.md
  docs/engineering/workfact_sample_real_report.md
  docs/engineering/workfact_sample_real.json
  scripts/workfact_sample_real.py
  scripts/workfact_sample_dryrun.py
)

echo "Backup → $BACKUP"
for rel in "${PATHS[@]}"; do
  backup_one "$rel"
done
# DB backup if present
if [ -f "$MAIN/data/observations/sitewatch.db" ]; then
  mkdir -p "$BACKUP/data/observations"
  cp -a "$MAIN/data/observations/sitewatch.db" "$BACKUP/data/observations/sitewatch.db"
fi

echo "Copy workfact → main"
for rel in "${PATHS[@]}"; do
  if [ ! -e "$WF/$rel" ]; then
    echo "SKIP missing in workfact: $rel"
    continue
  fi
  mkdir -p "$MAIN/$(dirname "$rel")"
  if [ -d "$WF/$rel" ]; then
    rm -rf "$MAIN/$rel"
    cp -a "$WF/$rel" "$MAIN/$rel"
  else
    cp -a "$WF/$rel" "$MAIN/$rel"
  fi
  echo "OK $rel"
done

echo "DONE backup=$BACKUP"
