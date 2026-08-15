"""Shared canonical MICP node list used by the bootstrap scenarios.

Kept in its own module so scenario 1 (decompose) and scenario 4 (paper-study
review) audit the SAME artifact — the reviewer must not see a different DAG
than the one that was produced.
"""

# Canonical self-audit-passing DAG for "optimize sand-column MICP uniformity":
# literature -> mechanism -> experiment design -> {simulation, measurement}
# -> audit -> decision. Includes the mandatory ammonium mass-balance task.
MIC_P_NODES = [
    {
        "id": "lit_review", "title": "Survey MICP ureolysis literature",
        "kind": "evidence_retrieval", "primary_skill": "micp-literature-scout",
        "depends_on": [], "inputs": ["request", "evidence_refs:whiffin2007"],
        "outputs": ["evidence_shortlist"],
        "definition_of_done": {"artifact": "evidence_shortlist.json",
                               "acceptance_criteria": [{"metric": "sources_shortlisted", "comparator": ">=", "threshold": 10}]},
        "failure_modes": ["no sources"], "retry_policy": {"max_attempts": 2, "backoff": "linear", "on_exhaustion": "replan_local"},
        "risk_level": "low", "data_sensitivity": "public", "est_effort_hours": 2.0,
        "est_context_tokens": 20000, "max_cost_budget": {"amount": 10, "currency": "USD"},
        "human_approval_gate": False,
    },
    {
        "id": "ureolysis_chem", "title": "Ureolysis chemistry + ammonium balance",
        "kind": "mechanism_reasoning", "primary_skill": "micp-ureolysis-chemistry",
        "depends_on": ["lit_review"], "inputs": ["lit_review:evidence_shortlist"],
        "outputs": ["ammonium_mass_balance"],
        "definition_of_done": {"artifact": "ammonium_mass_balance.md",
                               "acceptance_criteria": [{"metric": "n_balance_closed", "comparator": ">=", "threshold": 0.95, "unit": "-"}]},
        "failure_modes": ["pathway not ureolytic"], "retry_policy": {"max_attempts": 2, "backoff": "none", "on_exhaustion": "escalate_human"},
        "risk_level": "medium", "data_sensitivity": "internal", "est_effort_hours": 6.0,
        "est_context_tokens": 30000, "max_cost_budget": {"amount": 20, "currency": "USD"},
        "human_approval_gate": False,
    },
    {
        "id": "exp_design", "title": "Design sand-column uniformity experiment",
        "kind": "experiment_design", "primary_skill": "micp-experiment-designer",
        "depends_on": ["ureolysis_chem"], "inputs": ["ureolysis_chem:ammonium_mass_balance"],
        "outputs": ["protocol"],
        "definition_of_done": {"artifact": "protocol.md",
                               "acceptance_criteria": [{"metric": "control_replicates", "comparator": ">=", "threshold": 3}]},
        "failure_modes": ["confounded design"], "retry_policy": {"max_attempts": 1, "backoff": "none", "on_exhaustion": "escalate_human"},
        "risk_level": "high", "data_sensitivity": "sensitive", "est_effort_hours": 8.0,
        "est_context_tokens": 40000, "max_cost_budget": {"amount": 50, "currency": "USD"},
        "human_approval_gate": True,
    },
    {
        "id": "simulation", "title": "Reactive-transport simulation of uniformity",
        "kind": "simulation", "primary_skill": "micp-modeling-optimizer",
        "depends_on": ["exp_design"], "inputs": ["exp_design:protocol"],
        "outputs": ["uniformity_sim"],
        "definition_of_done": {"artifact": "uniformity_sim.h5",
                               "acceptance_criteria": [{"metric": "mesh_converged", "comparator": "==", "threshold": True}]},
        "failure_modes": ["non-convergence"], "retry_policy": {"max_attempts": 3, "backoff": "exponential", "on_exhaustion": "replan_local"},
        "risk_level": "medium", "data_sensitivity": "internal", "est_effort_hours": 10.0,
        "est_context_tokens": 50000, "max_cost_budget": {"amount": 60, "currency": "USD"},
        "human_approval_gate": False,
    },
    {
        "id": "measurement", "title": "Run column measurements and QC",
        "kind": "measurement", "primary_skill": "micp-instrumentation-qc",
        "depends_on": ["exp_design"], "inputs": ["exp_design:protocol"],
        "outputs": ["measured_uniformity"],
        "definition_of_done": {"artifact": "uniformity_dataset.csv",
                               "acceptance_criteria": [{"metric": "uniformity_cv", "comparator": "<=", "threshold": 0.3, "unit": "-"}]},
        "failure_modes": ["sensor drift"], "retry_policy": {"max_attempts": 2, "backoff": "linear", "on_exhaustion": "replan_local"},
        "risk_level": "high", "data_sensitivity": "sensitive", "est_effort_hours": 6.0,
        "est_context_tokens": 30000, "max_cost_budget": {"amount": 40, "currency": "USD"},
        "human_approval_gate": True,
    },
    {
        "id": "audit", "title": "Audit uniformity against acceptance criteria",
        "kind": "audit", "primary_skill": "micp-reproducibility-versioning",
        "depends_on": ["measurement"], "inputs": ["measurement:measured_uniformity"],
        "outputs": ["audit_report"],
        "definition_of_done": {"artifact": "audit_report.json",
                               "acceptance_criteria": [{"metric": "audit_issues_resolved", "comparator": "==", "threshold": 0}]},
        "failure_modes": ["criteria unmet"], "retry_policy": {"max_attempts": 1, "backoff": "none", "on_exhaustion": "replan_local"},
        "risk_level": "low", "data_sensitivity": "internal", "est_effort_hours": 3.0,
        "est_context_tokens": 20000, "max_cost_budget": {"amount": 10, "currency": "USD"},
        "human_approval_gate": False,
    },
    {
        "id": "decision", "title": "Decide on uniformity optimization path",
        "kind": "decision", "primary_skill": "obsidian-decision-gate",
        "depends_on": ["audit"], "inputs": ["audit:audit_report"],
        "outputs": ["decision_record"],
        "definition_of_done": {"artifact": "decision_record.json",
                               "acceptance_criteria": [{"metric": "decision_recorded", "comparator": "==", "threshold": True}]},
        "failure_modes": ["insufficient evidence"], "retry_policy": {"max_attempts": 1, "backoff": "none", "on_exhaustion": "escalate_human"},
        "risk_level": "medium", "data_sensitivity": "internal", "est_effort_hours": 1.5,
        "est_context_tokens": 15000, "max_cost_budget": {"amount": 5, "currency": "USD"},
        "human_approval_gate": False,
    },
]
