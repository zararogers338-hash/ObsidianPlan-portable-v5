#!/usr/bin/env bash
# Run every example through the real CLI and report pass/fail.
set -euo pipefail

SKILL="$(cd "$(dirname "$0")/.." && pwd)"
CLI="$SKILL/tools/mbs_auditor.py"
PASS=0
FAIL=0

run_one() {
  local file="$1" expected="$2" label="$3"
  local out status
  out=$(python "$CLI" < "$file") || { echo "  [$label] CRASH"; FAIL=$((FAIL+1)); return; }
  status=$(printf '%s' "$out" | python -c "import json,sys; print(json.load(sys.stdin)['status'])")
  if [ "$status" = "$expected" ]; then
    echo "  [$label] PASS ($status)"
    PASS=$((PASS+1))
  else
    echo "  [$label] FAIL expected=$expected got=$status"
    FAIL=$((FAIL+1))
  fi
}

echo "micp-biosafety-environment-auditor examples"
run_one "examples/01-lab-sand-column-audit.json"   "SUCCESS"                "01-lab"
run_one "examples/02-field-injection-audit.json"   "HUMAN_APPROVAL_REQUIRED" "02-field"
run_one "examples/03-strain-verify.json"           "SUCCESS"                "03-strain"

echo "passed=$PASS failed=$FAIL"
[ "$FAIL" -eq 0 ]
