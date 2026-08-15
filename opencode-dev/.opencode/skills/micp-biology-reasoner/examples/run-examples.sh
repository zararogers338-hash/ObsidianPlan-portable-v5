#!/usr/bin/env bash
# Run all examples through the real CLI and show each output envelope.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PYTHON:-python}
CLI="tools/micp_bio_reasoner.py"

for f in examples/0*.json; do
  echo "============================================================"
  echo "== $f"
  echo "============================================================"
  "$PY" "$CLI" < "$f" | "$PY" -c "
import json, sys
o = json.load(sys.stdin)
print('status:', o['status'])
print('summary:', o['summary'])
for f in o['findings']:
    print(f\"  [{f['label']}] {f['statement']}\")
print('artifacts:', len(o['artifacts']))
print('next_skills:', [r['skill'] for r in o['requested_next_skills']])
print('validation:', o['validation'])
if o['errors']:
    print('errors:', [e['code'] for e in o['errors']])
"
done
