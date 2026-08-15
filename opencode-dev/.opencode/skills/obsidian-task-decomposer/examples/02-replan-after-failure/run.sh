#!/usr/bin/env bash
# End-to-end run for example 02 (local replan after a failed experiment).
set -euo pipefail

SKILL_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TOOLS="$SKILL_ROOT/tools"
DIR="$(cd "$(dirname "$0")" && pwd)"
PY="python"

echo "== replan_diff: failed experiment -> local diff that preserves completed work =="
"$PY" "$TOOLS/replan_diff.py" < "$DIR/replan-input.json"

echo
echo "Expected semantics:"
echo "  preserved  -> ['lit_review']            (confirmed facts kept)"
echo "  rework     -> ['ureolysis_kinetics']    (the failed node)"
echo "  invalidated-> ['mechanism_model', 'ammonium_balance']"
echo "  added      -> ['ureolysis_kinetics_v2', 'mechanism_model_v2']"
echo "  removed    -> ['ammonium_balance']"
echo "  merged graph must stay a DAG"
