#!/usr/bin/env bash
# Run the three example flows end-to-end through the real CLI.
# Usage: bash examples/run-examples.sh
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CLI="$SKILL_DIR/tools/knowledge_graph_steward.py"
STORE="$(mktemp -d)"
trap 'rm -rf "$STORE"' EXIT

say() { printf '\n=== %s ===\n' "$*"; }

sum() { python -c "import sys,json; d=json.load(sys.stdin); print(d['status'], '|', d['summary'])"; }

say "01 初始化知识库"
python "$CLI" --store "$STORE" < "$SKILL_DIR/examples/01-init.json" | sum

say "02 矛盾晶体相共存（calcite vs vaterite → OPEN 冲突，不静默覆盖）"
python "$CLI" --store "$STORE" <<'JSON' | sum
{"contract_version":"1.0","task_id":"ex2","project_id":"demo-kg-02","request":"登记样品","action":"kb.init","title":"矛盾相演示","skill_version":"1.0.0","timestamp":"2026-08-06T00:00:00Z"}
JSON
python "$CLI" --store "$STORE" <<'JSON' | sum
{"contract_version":"1.0","task_id":"ex2","project_id":"demo-kg-02","request":"登记样品实体","action":"graph.upsert_entity","entity":{"id":"e-samp","entity_type":"ARTIFACT","canonical_name":"sample A"},"skill_version":"1.0.0","timestamp":"2026-08-06T00:00:00Z"}
JSON
python "$CLI" --store "$STORE" <<'JSON' | sum
{"contract_version":"1.0","task_id":"ex2","project_id":"demo-kg-02","request":"录入 calcite 结论","action":"graph.add_claim","claim":{"id":"p1","claim_kind":"TYPE","subject":"e-samp","predicate":"mineral_phase","object":"calcite","evidence_tier":"INTERNAL_OBSERVED","epistemic_label":"OBSERVED"},"skill_version":"1.0.0","timestamp":"2026-08-06T00:00:00Z"}
JSON
python "$CLI" --store "$STORE" <<'JSON' | sum
{"contract_version":"1.0","task_id":"ex2","project_id":"demo-kg-02","request":"录入矛盾 vaterite 结论","action":"graph.add_claim","claim":{"id":"p2","claim_kind":"TYPE","subject":"e-samp","predicate":"mineral_phase","object":"vaterite","evidence_tier":"EXTERNAL_REPORTED","epistemic_label":"REPORTED"},"skill_version":"1.0.0","timestamp":"2026-08-06T00:00:00Z"}
JSON
python "$CLI" --store "$STORE" <<'JSON' | python -c "import sys,json; d=json.load(sys.stdin); opens=[f['statement'] for f in d['findings'] if 'OPEN' in f['statement']]; print('conflict_scan:', d['status'], '|', d['summary'], '| 冲突:', len(opens))"
{"contract_version":"1.0","task_id":"ex2","project_id":"demo-kg-02","request":"扫描冲突","action":"graph.conflict_scan","skill_version":"1.0.0","timestamp":"2026-08-06T00:00:00Z"}
JSON

say "03 证据链审计 + 完整性 + 备份"
python "$CLI" --store "$STORE" <<'JSON' | sum
{"contract_version":"1.0","task_id":"ex3","project_id":"demo-kg-03","request":"初始化审计库","action":"kb.init","title":"审计演示","skill_version":"1.0.0","timestamp":"2026-08-06T00:00:00Z"}
JSON
python "$CLI" --store "$STORE" <<'JSON' | sum
{"contract_version":"1.0","task_id":"ex3","project_id":"demo-kg-03","request":"登记证据","action":"graph.evidence_register","evidence":{"ref":"doi:10.1000/urease","sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","tier":"EXTERNAL_REPORTED","source":"literature"},"skill_version":"1.0.0","timestamp":"2026-08-06T00:00:00Z"}
JSON
python "$CLI" --store "$STORE" <<'JSON' | sum
{"contract_version":"1.0","task_id":"ex3","project_id":"demo-kg-03","request":"录入带证据的声明","action":"graph.add_claim","claim":{"id":"c1","claim_kind":"TYPE","subject":"e-urease","subject_is_alias":true,"predicate":"catalyzes","object":"urea hydrolysis","evidence_tier":"EXTERNAL_REPORTED","epistemic_label":"REPORTED","evidence_refs":["doi:10.1000/urease"]},"skill_version":"1.0.0","timestamp":"2026-08-06T00:00:00Z"}
JSON
python "$CLI" --store "$STORE" <<'JSON' | python -c "import sys,json; d=json.load(sys.stdin); n=[a for a in d['artifacts'] if a['kind']=='evidence_chain'][0]['note']; print('evidence_chain:', d['status'], '|', d['summary'], '| 解析证据数:', len(n['evidence_chain']))"
{"contract_version":"1.0","task_id":"ex3","project_id":"demo-kg-03","request":"审计证据链","action":"graph.evidence_chain","claim_id":"c1","skill_version":"1.0.0","timestamp":"2026-08-06T00:00:00Z"}
JSON
python "$CLI" --store "$STORE" <<'JSON' | sum
{"contract_version":"1.0","task_id":"ex3","project_id":"demo-kg-03","request":"完整性校验","action":"kb.integrity","skill_version":"1.0.0","timestamp":"2026-08-06T00:00:00Z"}
JSON
python "$CLI" --store "$STORE" <<'JSON' | python -c "import sys,json; d=json.load(sys.stdin); print('kb.backup:', d['status'], '|', d['summary'])"
{"contract_version":"1.0","task_id":"ex3","project_id":"demo-kg-03","request":"备份","action":"kb.backup","label":"weekly","skill_version":"1.0.0","timestamp":"2026-08-06T00:00:00Z"}
JSON

say "全部示例执行完成 ✓"
