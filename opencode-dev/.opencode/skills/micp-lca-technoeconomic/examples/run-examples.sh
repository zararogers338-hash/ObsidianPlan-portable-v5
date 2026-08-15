#!/usr/bin/env bash
# Runs every example through the real CLI and checks exit/envelope shape.
# Usage: bash examples/run-examples.sh
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PYTHON:-python}

"$PY" - <<'PY'
import json, subprocess, sys
CLI = "tools/micp_lca.py"

with open('examples/01-sandbody-lca-tea.json', encoding='utf-8') as fh:
    payload = json.load(fh)
proc = subprocess.run([sys.executable, CLI, "service"], input=json.dumps(payload),
                      capture_output=True, text=True)
envelope = json.loads(proc.stdout)
r = envelope.get('result', {})
assert envelope.get('ok') is True, envelope.get('error')
assert r.get('status') == 'SUCCESS', r.get('status')
assert r['validation']['output_schema'] == 'passed'
env = r['environmental_results']
for sid in ('micp-a-standard', 'micp-b-ammonia-recovery', 'cement-dsm'):
    assert sid in env, f'missing {sid}'
print('== 01-sandbody-lca-tea: SUCCESS, scenarios =', sorted(env))
for sid, er in env.items():
    print('  %-22s GWP=%7.2f kgCO2eq  energy=%6.1f MJ  N=%6.2f kgNH3-N  cost=%9.0f CNY' % (
        sid, er['gwp']['value'], er['energy']['value'], er['nitrogen_load']['value'],
        r['cost_results'][sid]['total_cost_cny']))
print('  comparison best:', [(m['metric'], m['best_scenario'])
                             for m in r['scenario_comparison']['metrics']])

with open('examples/02-blocked-missing-fu.json', encoding='utf-8') as fh:
    p2 = json.load(fh)
proc2 = subprocess.run([sys.executable, CLI, "service"], input=json.dumps(p2),
                       capture_output=True, text=True)
r2 = json.loads(proc2.stdout)['result']
assert r2.get('status') == 'BLOCKED', r2.get('status')
assert r2['errors'][0]['code'] == 'LCA-E103', r2['errors']
print('== 02-blocked-missing-fu: BLOCKED', r2['errors'][0]['code'])
print('ALL EXAMPLES PASS')
PY
