#!/usr/bin/env bash
# End-to-end run for example 03 (BLOCKED on missing required input).
# The skill contract: never improvise a plan — return BLOCKED with missing_inputs.
set -euo pipefail

SKILL_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TOOLS="$SKILL_ROOT/tools"
DIR="$(cd "$(dirname "$0")" && pwd)"
PY="python"

echo "== validate: empty request must fail the input schema =="
"$PY" "$TOOLS/validate.py" <<< "{\"schema\": \"schemas/input.schema.json\", \"document\": $(cat "$DIR/input.json")}"

echo
echo "Expected agent behavior:"
echo "  status: BLOCKED"
echo "  missing_inputs: [ {field: 'request', why_critical: '...', how_to_obtain: '...'} ]"
echo "  errors[0].code: E_SCHEMA_INPUT"
echo "  No DAG is fabricated."
