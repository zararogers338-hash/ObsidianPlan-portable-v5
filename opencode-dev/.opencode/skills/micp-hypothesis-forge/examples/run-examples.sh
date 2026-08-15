#!/usr/bin/env bash
# Run the three micp-hypothesis-forge examples through the tool pipeline.
# Demonstrates dag -> scoring -> card-validate -> competing-matrix ->
# experiment-priority, then self-audit on a hand-built envelope.
#
# Usage: bash examples/run-examples.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "=== Example 1: ureolysis strength loss (mechanism DAG) ==="
# A skill-invocation document is NOT a dag payload -> the tool must reject it
# (MHX-E102: missing mechanism_chain). Then run dag on the embedded statement
# chain to show the causal DAG.
if python tools/dag.py < examples/01-ureolysis-strength.json 2>/dev/null; then
  echo "(expected: invocation doc is rejected by dag.py)"
else
  echo "correctly rejected invocation document (MHX-E102 missing mechanism_chain)"
fi
echo '{"mechanism_chain": ["high urease activity", "accelerated hydrolysis", "NH4+ accumulation", "reduced cementation strength"]}' \
  | python tools/dag.py | python -c "
import json,sys
d=json.load(sys.stdin)
r=d['result']
print('DAG:', ' -> '.join(r['topological_order']))
print('acyclic:', r['acyclic'], '| edges:', r['edge_count'])
"
echo

echo "=== Example 2: inlet clogging (competing matrix) ==="
cat > /tmp/ex2_cm.json <<'EOF'
{"hypotheses":[
 {"id":"H1","statement":"Inlet clogs by chemical precipitation of calcite","refutation":"If inlet calcite mass increases while inlet cell mass stays low, chemical precipitation drives the clog","observables":["inlet calcite (g)","inlet cell mass (g)","pressure rise (kPa)"],"observable_predictions":{"inlet calcite (g)":"increase","inlet cell mass (g)":"no_change","pressure rise (kPa)":"increase"},"epistemic_label":"HYPOTHESIS"},
 {"id":"H2","statement":"Inlet clogs by cell entrapment / biofilm accumulation","refutation":"If inlet cell mass increases while inlet calcite stays low, cell entrapment drives the clog","observables":["inlet cell mass (g)","inlet calcite (g)","pressure rise (kPa)"],"observable_predictions":{"inlet cell mass (g)":"increase","inlet calcite (g)":"no_change","pressure rise (kPa)":"increase"},"epistemic_label":"HYPOTHESIS"},
 {"id":"H3","statement":"Inlet clogs by flow-field redistribution concentrating precipitation downstream","refutation":"If downstream calcite increases while inlet pressure stays flat, flow-field redistribution drives the clog","observables":["downstream calcite (g)","inlet pressure (kPa)"],"observable_predictions":{"downstream calcite (g)":"increase","inlet pressure (kPa)":"no_change"},"epistemic_label":"HYPOTHESIS"}]}
EOF
python tools/competing-matrix.py < /tmp/ex2_cm.json | python -c "
import json,sys
d=json.load(sys.stdin)
r=d.get('result',{})
print('predicted_directions:', json.dumps(r.get('predicted_directions',{}), ensure_ascii=False))
for p in r.get('pair_discrimination',[]):
    print('pair', p['pair'], 'discriminates via', p.get('discriminating_experiments'), 'gain', p.get('best_information_gain_bits'))
"
echo

echo "=== Example 3: non-uniform calcite (scoring + experiment priority) ==="
cat > /tmp/ex3_score.json <<'EOF'
{"statements":[
 {"id":"H1","statement":"Precipitation is substrate-limited downstream","refutation":"If downstream residual urea exceeds 10 mM, H1 is weakened","observables":["residual urea (mM)"],"time_scale":"14 days","scope":"30cm column, 0.5M urea"},
 {"id":"H2","statement":"Precipitation is nucleation-limited downstream","refutation":"If seeding with calcite nuclei downstream restores precipitation, H2 is confirmed","observables":["seeded vs unseeded calcite (g)"],"time_scale":"14 days","scope":"30cm column, 0.5M urea"},
 {"id":"H3","statement":"Precipitation is transport-limited by mixing","refutation":"If raising interstitial velocity does not change the profile, H3 is weakened","observables":["velocity (m/s)","profile uniformity"],"time_scale":"7 days","scope":"30cm column"}]}
EOF
python tools/scoring.py < /tmp/ex3_score.json | python -c "
import json,sys
d=json.load(sys.stdin)
for r in d['result']['results']:
    print(r['id'], 'fals', r['falsifiability']['score'], 'meas', r['measurability']['score'], 'overall', r['overall'])
"

cat > /tmp/ex3_prio.json <<'EOF'
{"experiments":[
 {"id":"E1","information_gain_bits":0.7,"cost_rank":2,"risk_level":"low","time_scale_days":7,"feasibility":0.9,"name":"measure downstream residual urea"},
 {"id":"E2","information_gain_bits":0.5,"cost_rank":3,"risk_level":"medium","time_scale_days":14,"feasibility":0.7,"name":"seeded vs unseeded downstream columns"},
 {"id":"E3","information_gain_bits":0.3,"cost_rank":1,"risk_level":"low","time_scale_days":3,"feasibility":0.95,"name":"interstitial velocity sweep"}]}
EOF
python tools/experiment-priority.py < /tmp/ex3_prio.json | python -c "
import json,sys
d=json.load(sys.stdin)
for r in d['result']['ranked_experiments']:
    print('rank', r['rank'], r['id'], 'score', r['score'], r['name'])
"
echo

echo "=== Self-audit on a complete envelope ==="
cat > /tmp/ex_audit.json <<'EOF'
{"contract_version":"1.0","skill":"micp-hypothesis-forge","skill_version":"1.0.0","status":"SUCCESS","summary":"3 hypotheses forged","findings":[{"id":"F1","epistemic_label":"HYPOTHESIS","summary":"NH4+ accumulation drives strength loss"}],"assumptions":[],"evidence_used":[{"ref_id":"EV1","role":"support"}],"evidence_refs":[{"ref_id":"EV1"}],"uncertainty":{},"risks":[{"id":"R1","epistemic_label":"HYPOTHESIS","risk":"direction could flip"}],"artifacts":[{"kind":"hypothesis_card_set","cards":[{"id":"H1","refutation":"if NH4+>120mM then UCS declines"},{"id":"H2","refutation":"if calcite stays high then H2 weakened"},{"id":"H3","refutation":"if permeability uniform then H3 weakened"}]}],"requested_next_skills":[],"validation":{},"provenance":{"skill":"micp-hypothesis-forge","skill_version":"1.0.0","timestamp":"2026-08-06T00:00:00Z","contract_version":"1.0","controller_version":"0.1.0"},"errors":[]}
EOF
python tools/self-audit.py < /tmp/ex_audit.json | python -c "
import json,sys
d=json.load(sys.stdin)
print('pass:', d['result']['pass'], '| summary:', d['result']['summary'])
"

echo "ALL EXAMPLES DONE"
