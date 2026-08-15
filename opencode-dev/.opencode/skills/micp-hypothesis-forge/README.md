# micp-hypothesis-forge

MICP Hypothesis Forge — 机制假设生成、竞争模型与可证伪预测。

A governed professional skill of **Obsidian Plan (Panshi)**. It turns an
observed/verified phenomenon into one **main + ≥2 competing falsifiable
mechanism hypotheses**, each as a machine-readable **Hypothesis Card**, plus a
**discriminating-experiment matrix** consumable by the Experiment Designer.

## Install / load

1. Place (or keep) this directory at `skills/micp-hypothesis-forge/` under the
   Obsidian OpenCode fork. OpenCode discovers skills via `**/SKILL.md`.
2. No dependencies: pure Python 3.10+ standard library, offline, deterministic.
3. The controller invokes it with an input document per
   `schemas/input.schema.json` and receives an output document per
   `schemas/output.schema.json`.

## Invocation (example)

```json
{
  "task_id": "T-1",
  "project_id": "P-UR",
  "request": "Explain why high urease activity lowers UCS — generate competing mechanisms",
  "risk_level": "low",
  "human_approval_state": "granted",
  "requested_output_format": "both",
  "skill_version": "1.0.0",
  "controller_version": "0.1.0",
  "timestamp": "2026-08-06T00:00:00Z",
  "statement_to_forge": "High urease activity reduces unconfined compressive strength",
  "evidence_refs": ["EV1", "EV2"]
}
```

## Tools

| Tool | Purpose |
|---|---|
| `tools/dag.py` | mechanism chain(s) → causal DAG; cycle / self-loop / unknown-ref rejection |
| `tools/scoring.py` | falsifiability / measurability / discriminability scores (0–1) |
| `tools/card-validate.py` | Hypothesis Card / Card Set schema validation + audit |
| `tools/competing-matrix.py` | discriminating experiments per hypothesis pair + info gain |
| `tools/experiment-priority.py` | rank experiments by gain × cost × risk |
| `tools/self-audit.py` | output envelope gates G1–G7 |

Every tool: **one JSON on stdin → one JSON on stdout**, exit `0/2/3/4`, no
network, no file writes. See `tools/README.md`.

## Tests & evals

```bash
cd skills/micp-hypothesis-forge
python -m pytest tests -q            # unit + failure + integration + regression
python evals/run_evals.py            # 8+ cases, 7 performance indicators
```

`evals/run_evals.py` asserts every indicator threshold from `skill.yaml`
(`evaluation.indicators`).

## Conventions

- Error codes: single source of truth in `tools/mhfx/errors.py` (`MHX-E1xx`…`E8xx`).
- Epistemic labels: `OBSERVED/REPORTED/CALCULATED/INFERRED/HYPOTHESIS/RECOMMENDATION`.
- Version policy: semantic, documented in `skill.yaml`.
- The `skill.yaml` is a **project-custom** manifest (OpenCode native loader
  reads only SKILL.md frontmatter `name` + `description`).

## Limits

- Deterministic text scoring of card features; scientific judgment lives in the
  system prompt + controller.
- Information gain assumes symmetric prior + default sensitivity/specificity.
- Offline by design: evidence must be supplied via `evidence_refs`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `MHX-E104` | send exactly one JSON document on stdin |
| `MHX-E106` | hypothesis lacks a falsifiable refutation condition |
| `MHX-E801` | `skill_version` / contract mismatch with installed 1.0.0 |
| schema path errors | run tools from the skill directory (paths resolve relative to it) |


---

> 原 `README-安装说明.md` 已归档至 [`audit/README-安装说明.md`](audit/README-安装说明.md)。
