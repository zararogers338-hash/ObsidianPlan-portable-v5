#!/usr/bin/env bash
# Run the three example flows end-to-end through the real CLI.
# Usage: bash examples/run-examples.sh
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CLI="$SKILL_DIR/tools/state_manager.py"
STORE="$(mktemp -d)"
trap 'rm -rf "$STORE"' EXIT

say() { printf '\n=== %s ===\n' "$*"; }

say "01 初始化研究流 (project.init)"
python "$CLI" --store "$STORE" < "$SKILL_DIR/examples/01-init.json" | python -c \
  "import sys,json; d=json.load(sys.stdin); print('status=',d['status'],'| state=',d['state'],'| head=',d['provenance']['head_revision'])"

say "02 推进到 HYPOTHESIS_BUILDING（含证据守卫演示）"
python "$CLI" --store "$STORE" < "$SKILL_DIR/examples/02-lifecycle.json" | python -c \
  "import sys,json; d=json.load(sys.stdin); print('init         ', d['status'], d['state'])"
python "$CLI" --store "$STORE" <<'JSON' | python -c "import sys,json; d=json.load(sys.stdin); print('-> SCOPED   ', d['status'], d['state'])"
{"contract_version":"1.0","task_id":"ex2","project_id":"demo-micp-02","request":"推进","action":"state.transition","to_state":"SCOPED","actor":{"role":"controller"},"skill_version":"1.0.0","timestamp":"2026-08-06T00:00:00Z"}
JSON
python "$CLI" --store "$STORE" <<'JSON' | python -c "import sys,json; d=json.load(sys.stdin); print('-> EVIDENCE_GATHERING', d['status'], d['state'])"
{"contract_version":"1.0","task_id":"ex2","project_id":"demo-micp-02","request":"推进","action":"state.transition","to_state":"EVIDENCE_GATHERING","actor":{"role":"controller"},"skill_version":"1.0.0","timestamp":"2026-08-06T00:00:00Z"}
JSON
echo "-- 故意在无证据时尝试推进到 HYPOTHESIS_BUILDING（应被守卫拦截）--"
python "$CLI" --store "$STORE" <<'JSON' | python -c "import sys,json; d=json.load(sys.stdin); print('  blocked code=', d['errors'][0]['code'] if d['errors'] else d['status'], '| 状态保持', d['state'])"
{"contract_version":"1.0","task_id":"ex2","project_id":"demo-micp-02","request":"推进","action":"state.transition","to_state":"HYPOTHESIS_BUILDING","actor":{"role":"skill"},"skill_version":"1.0.0","timestamp":"2026-08-06T00:00:00Z"}
JSON
python "$CLI" --store "$STORE" <<'JSON' | python -c "import sys,json; d=json.load(sys.stdin); print('attach 证据  ', d['status'])"
{"contract_version":"1.0","task_id":"ex2","project_id":"demo-micp-02","request":"推进","action":"evidence.attach","evidence":{"ref":"doi:10.1000/urease","sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","summary":"urease kinetics"},"skill_version":"1.0.0","timestamp":"2026-08-06T00:00:00Z"}
JSON
python "$CLI" --store "$STORE" <<'JSON' | python -c "import sys,json; d=json.load(sys.stdin); print('-> HYPOTHESIS_BUILDING', d['status'], d['state'])"
{"contract_version":"1.0","task_id":"ex2","project_id":"demo-micp-02","request":"推进","action":"state.transition","to_state":"HYPOTHESIS_BUILDING","actor":{"role":"skill"},"skill_version":"1.0.0","timestamp":"2026-08-06T00:00:00Z"}
JSON

say "03 中断恢复（检查点 + 恢复计划，重复工作应被跳过）"
python "$CLI" --store "$STORE" <<'JSON' | python -c "import sys,json; d=json.load(sys.stdin); print('checkpoint', d['status'])"
{"contract_version":"1.0","task_id":"ex3","project_id":"demo-micp-03","request":"恢复","action":"project.init","title":"中断恢复","skill_version":"1.0.0","timestamp":"2026-08-06T00:00:00Z"}
JSON
python "$CLI" --store "$STORE" <<'JSON' | python -c "import sys,json; d=json.load(sys.stdin); print('checkpoint', d['status'])"
{"contract_version":"1.0","task_id":"ex3","project_id":"demo-micp-03","request":"恢复","action":"task.checkpoint","completed_work":[{"step":"compile data","input":"a.csv"}],"pending_work":[{"step":"fit model"}],"skill_version":"1.0.0","timestamp":"2026-08-06T00:00:00Z"}
JSON
python "$CLI" --store "$STORE" <<'JSON' | python -c "import sys,json; d=json.load(sys.stdin); plan=[a for a in d['artifacts'] if a['kind']=='resume_plan'][0]['note']; print('恢复计划: 跳过(already_done)=',plan['skipped_count'],' 需执行(to_run)=',len(plan['to_run']))"
{"contract_version":"1.0","task_id":"ex3","project_id":"demo-micp-03","request":"恢复","action":"task.resume_plan","candidate_work":[{"step":"compile data","input":"a.csv"},{"step":"compile data","input":"b.csv"},{"step":"fit model"}],"skill_version":"1.0.0","timestamp":"2026-08-06T00:00:00Z"}
JSON

say "全部示例执行完成 ✓"
