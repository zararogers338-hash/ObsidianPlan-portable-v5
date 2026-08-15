#!/usr/bin/env bash
# End-to-end run for example 01 (basic MICP decomposition).
# Requires: python >= 3.10. Run from anywhere: bash 01-basic-micp/run.sh
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_ROOT="$(cd "$DIR/../.." && pwd)"
TOOLS="$SKILL_ROOT/tools"
export TOOLS_DIR="$TOOLS"
PY="python"

echo "== 1. Validate the input contract =="
"$PY" - "$DIR/input.json" <<'PYEOF'
import json, os, subprocess, sys
tool = os.path.join(os.environ["TOOLS_DIR"], "validate.py")
doc = json.load(open(sys.argv[1], encoding="utf-8"))
proc = subprocess.run([sys.executable, tool],
                      input=json.dumps({"schema": "schemas/input.schema.json", "document": doc}),
                      capture_output=True, text=True)
print(proc.stdout)
sys.exit(proc.returncode)
PYEOF

echo "== 2. dag_check on the expected DAG =="
"$PY" - "$DIR/expected-dag.json" <<'PYEOF'
import json, os, subprocess, sys
tool = os.path.join(os.environ["TOOLS_DIR"], "dag_check.py")
dag = json.load(open(sys.argv[1], encoding="utf-8"))
proc = subprocess.run([sys.executable, tool],
                      input=json.dumps({"nodes": dag["dag"]["nodes"]}),
                      capture_output=True, text=True)
print(proc.stdout)
sys.exit(proc.returncode)
PYEOF

echo "== 3. granularity scoring =="
"$PY" - "$DIR/expected-dag.json" <<'PYEOF'
import json, os, subprocess, sys
tool = os.path.join(os.environ["TOOLS_DIR"], "granularity_scorer.py")
dag = json.load(open(sys.argv[1], encoding="utf-8"))
proc = subprocess.run([sys.executable, tool],
                      input=json.dumps({"nodes": dag["dag"]["nodes"]}),
                      capture_output=True, text=True)
print(proc.stdout)
sys.exit(proc.returncode)
PYEOF

echo "== 4. budget estimates =="
"$PY" - "$DIR/expected-dag.json" <<'PYEOF'
import json, os, subprocess, sys
tool = os.path.join(os.environ["TOOLS_DIR"], "budget_estimator.py")
dag = json.load(open(sys.argv[1], encoding="utf-8"))
tasks = [{"id": n["id"], "kind": n["kind"], "risk_level": n["risk_level"],
          "data_sensitivity": n["data_sensitivity"], "est_context_tokens": n["est_context_tokens"]}
         for n in dag["dag"]["nodes"]]
proc = subprocess.run([sys.executable, tool],
                      input=json.dumps({"tasks": tasks}),
                      capture_output=True, text=True)
print(proc.stdout)
sys.exit(proc.returncode)
PYEOF

echo "== 5. critical path =="
"$PY" - "$DIR/expected-dag.json" <<'PYEOF'
import json, os, subprocess, sys
tool = os.path.join(os.environ["TOOLS_DIR"], "critical_path.py")
dag = json.load(open(sys.argv[1], encoding="utf-8"))
proc = subprocess.run([sys.executable, tool],
                      input=json.dumps({"nodes": dag["dag"]["nodes"]}),
                      capture_output=True, text=True)
print(proc.stdout)
sys.exit(proc.returncode)
PYEOF

echo "== 6. self-audit gates G1-G6 =="
"$PY" - "$DIR/expected-dag.json" <<'PYEOF'
import json, os, subprocess, sys
tool = os.path.join(os.environ["TOOLS_DIR"], "self_audit.py")
out = json.load(open(sys.argv[1], encoding="utf-8"))
proc = subprocess.run([sys.executable, tool],
                      input=json.dumps({"output": out,
                                        "external_inputs": ["evidence_refs", "data_refs"]}),
                      capture_output=True, text=True)
print(proc.stdout)
sys.exit(proc.returncode)
PYEOF

echo "== 7. output schema validation =="
"$PY" - "$DIR/expected-dag.json" <<'PYEOF'
import json, os, subprocess, sys
tool = os.path.join(os.environ["TOOLS_DIR"], "validate.py")
out = json.load(open(sys.argv[1], encoding="utf-8"))
doc = {"status": "SUCCESS",
       "summary": "See expected-dag.json",
       "findings": [{"statement": "ureolysis yields 2 mol NH4+ per mol CaCO3",
                     "epistemic_tag": "CALCULATED", "source": "stoichiometry"}],
       "assumptions": [], "evidence_used": [{"ref_id": "whiffin2007"}],
       "uncertainty": [], "risks": [],
       "artifacts": [{"artifact_id": "dag-1", "kind": "task_dag",
                      "content_type": "application/json", "payload": out}],
       "requested_next_skills": [],
       "validation": {"self_audit_pass": True, "gates": {}},
       "provenance": {"skill": "obsidian-task-decomposer", "skill_version": "1.0.0",
                      "generated_at": "2026-08-06T00:00:00Z", "generator": "run.sh"},
       "errors": []}
proc = subprocess.run([sys.executable, tool],
                      input=json.dumps({"schema": "schemas/output.schema.json", "document": doc}),
                      capture_output=True, text=True)
print(proc.stdout)
sys.exit(proc.returncode)
PYEOF

echo "ALL PIPELINE STEPS OK"
