# Example 01 — Clean and infer: MICP-treated sand UCS

Pseudo-replicated data (two columns per treatment, three heights each). The
service must: detect pseudo-replication, aggregate to the specimen unit for the
group effect, report mean ± 95% CI per response, and pass self-check.

## Input

```json
{
  "task_id": "ex-01",
  "project_id": "panshi-demo",
  "request": "Analyze UCS strength across treatments, detect pseudo-replication, report statistics and uniformity.",
  "skill_version": "1.0.0",
  "controller_version": "obsidian-ctl-0.1.0",
  "timestamp": "2026-08-06T12:00:00Z",
  "risk_level": "medium",
  "human_approval_state": "not_required",
  "requested_output_format": "json",
  "data_columns": [
    {"name": "specimen", "role": "id", "data_type": "string", "sampling_unit": "column"},
    {"name": "treatment", "role": "treatment", "data_type": "string"},
    {"name": "position", "role": "position", "data_type": "string"},
    {"name": "ucs", "role": "response", "data_type": "number", "unit": "MPa"}
  ],
  "samples": [
    {"specimen": "A1", "treatment": "ctrl", "position": "top", "ucs": 1.0},
    {"specimen": "A1", "treatment": "ctrl", "position": "mid", "ucs": 1.1},
    {"specimen": "A1", "treatment": "ctrl", "position": "bot", "ucs": 1.2},
    {"specimen": "A2", "treatment": "ctrl", "position": "top", "ucs": 1.3},
    {"specimen": "A2", "treatment": "ctrl", "position": "mid", "ucs": 1.4},
    {"specimen": "A2", "treatment": "ctrl", "position": "bot", "ucs": 1.5},
    {"specimen": "B1", "treatment": "micp", "position": "top", "ucs": 3.0},
    {"specimen": "B1", "treatment": "micp", "position": "mid", "ucs": 3.4},
    {"specimen": "B1", "treatment": "micp", "position": "bot", "ucs": 3.8},
    {"specimen": "B2", "treatment": "micp", "position": "top", "ucs": 3.2},
    {"specimen": "B2", "treatment": "micp", "position": "mid", "ucs": 3.5},
    {"specimen": "B2", "treatment": "micp", "position": "bot", "ucs": 3.9}
  ]
}
```

## Run

```bash
cd skills/micp-data-analyst
python tools/micp/cli.py service < examples/01-clean-infer.json
```

## Expected highlights

- `status: SUCCESS`, `validation.self_audit_pass: true`
- `pseudo_replication.detected: true`, `effective_n: 4` (vs 12 rows)
- `statistics.group_comparison.unit_aggregated: true`, `sampling_unit: specimen`
- `statistics.variables.ucs.ci` carries a finite 95% CI with n=12 and unit MPa
- every `findings[]` item carries an epistemic tag
