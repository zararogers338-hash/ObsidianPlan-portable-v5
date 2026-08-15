"""MES orchestration service — the full synthesis pipeline behind the CLI.

Pipeline (SKILL.md §四):
  1. input schema validation       (schemas/input.schema.json)
  2. evidence card validation      (evidence_validate)
  3. PICO alignment                (pico presence gate)
  4. comparability check           (heterogeneity_compute.check_comparability)
  5. evidence + conflict matrix    (evidence_map)
  6. effects + pooling decision    (effect_compute → meta_analyze / narrative)
  7. heterogeneity classification  (heterogeneity_compute.classify_heterogeneity)
  8. sensitivity analysis          (sensitivity_run)
  9. GRADE certainty               (grade_assess)
 10. over-generalization self-check (result_check_overgeneralization)
 11. unified envelope              (models)

Never mutates global state; every call is deterministic given its inputs
(digest + completed_at are the only time-dependent fields).
"""

from __future__ import annotations

import json
from typing import Any, Optional

from . import effect_compute, evidence_map, evidence_validate
from .errors import MesError, MesErrorCode
from . import grade_assess, heterogeneity_compute, meta_analyze
from . import result_check_overgeneralization, sensitivity_run
from . import jsonschema as _js
from .models import (
    CONTRACT_VERSION, EVIDENCE_LEVELS, LABELS, OutputStatus, SKILL_NAME,
    SKILL_VERSION, finalize_envelope, new_envelope, stable_digest,
)

INPUT_SCHEMA_PATH = "schemas/input.schema.json"
OUTPUT_SCHEMA_PATH = "schemas/output.schema.json"


class MesService:
    """Stateless service; all state is passed in or returned in the envelope."""

    def __init__(self, skill_root: str | None = None, clock=None):
        self._skill_root = skill_root
        self._clock = clock or (lambda: None)  # None timestamps allowed in tests

    # ------------------------------------------------------------------ utils
    def _load_schema(self, name: str) -> dict:
        if self._skill_root is None:
            raise MesError(MesErrorCode.TOOL_UNAVAILABLE,
                           f"skill root not configured; cannot load {name}")
        import pathlib
        path = pathlib.Path(self._skill_root) / name
        if not path.exists():
            raise MesError(MesErrorCode.CORRUPTION, f"schema file missing: {path}")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise MesError(MesErrorCode.CORRUPTION,
                           f"schema file unreadable: {path}: {exc}") from exc

    # ------------------------------------------------------------------ handle
    def handle(self, payload: dict) -> dict:
        """Validate, dispatch on action, return a contract-shaped envelope.

        Status mapping (SKILL.md §六): input/schema/unit/capability/state errors
        -> BLOCKED (caller must fix inputs); internal/self-check errors -> FAILED.
        """
        try:
            return self._handle(payload)
        except MesError as exc:
            status = self._status_for_error(exc)
            return self._error_envelope(payload, exc, status=status)
        except Exception as exc:  # defensive last resort
            err = MesError(MesErrorCode.SELF_CHECK_FAILED,
                           f"unexpected internal error: {exc}")
            return self._error_envelope(payload, err, status=OutputStatus.FAILED)

    @staticmethod
    def _status_for_error(exc: MesError) -> OutputStatus:
        """BLOCKED for caller-fixable errors; FAILED for internal/protocol.

        OES-E101 is BLOCKED when it describes schema issues (fixable inputs)
        but FAILED when the payload is not an object at all (protocol fault).
        OES-E115 (unsupported action) is FAILED: not retryable as-is.
        """
        blocked_codes = {
            MesErrorCode.EVIDENCE_UNVERIFIABLE, MesErrorCode.UNIT_MISMATCH,
            MesErrorCode.PERMISSION_DENIED, MesErrorCode.CAPABILITY_MISSING,
            MesErrorCode.CORRUPTION, MesErrorCode.BUDGET_EXCEEDED,
            MesErrorCode.NUMERIC_INVALID, MesErrorCode.NOT_COMPARABLE,
            MesErrorCode.PICO_MISSING, MesErrorCode.INSUFFICIENT_POOLING,
            MesErrorCode.VERSION_UNSUPPORTED,
        }
        if exc.code == MesErrorCode.INPUT_SCHEMA:
            if exc.detail and exc.detail.get("fault") == "non_object_payload":
                return OutputStatus.FAILED
            return OutputStatus.BLOCKED
        if exc.code in blocked_codes:
            return OutputStatus.BLOCKED
        return OutputStatus.FAILED

    def _error_envelope(self, payload, exc: MesError, status: OutputStatus) -> dict:
        action = payload.get("action") if isinstance(payload, dict) else None
        task_id = payload.get("task_id") if isinstance(payload, dict) else None
        project_id = payload.get("project_id") if isinstance(payload, dict) else None
        env = new_envelope(action, task_id, project_id)
        env["status"] = status.value
        env["summary"] = f"{exc.code}: {exc.message}"
        env["errors"] = [exc.to_dict()]
        env["validation"]["input_schema"] = "failed"
        env["validation"]["self_check"] = "not_run"
        return env

    # ------------------------------------------------------------------ pipeline
    def _handle(self, payload: dict) -> dict:
        if not isinstance(payload, dict):
            # Protocol fault, not a fixable input gap: FAILED, not BLOCKED.
            raise MesError(MesErrorCode.INPUT_SCHEMA, "payload must be a JSON object",
                           detail={"fault": "non_object_payload"})

        action = payload.get("action")
        if action != "evidence.synthesize":
            raise MesError(MesErrorCode.ACTION_UNSUPPORTED,
                           f"action '{action}' is not supported by {SKILL_NAME}")

        # 1. input schema
        input_schema = self._load_schema(INPUT_SCHEMA_PATH)
        issues = _js.validate(payload, input_schema)
        if issues:
            details = [{"path": i.path, "message": i.message} for i in issues]
            raise MesError(MesErrorCode.INPUT_SCHEMA,
                           "input failed schema validation",
                           detail={"issues": details})

        started = (self._clock() if self._clock else None)
        env = new_envelope(action, payload.get("task_id"), payload.get("project_id"),
                           started_at=started)
        env["provenance"]["input_digest"] = stable_digest(payload)
        env["provenance"]["controller_version"] = payload.get("controller_version")

        cards = payload.get("evidence_cards", [])
        pico = payload.get("pico", {})
        constraints = payload.get("constraints") or {}
        requested = payload.get("requested_output_format", "synthesis_report")
        dry_run = bool(payload.get("dry_run"))

        # 2. card validation
        vres = evidence_validate.validate_cards(cards)
        env["evidence_used"] = sorted(vres["ref_ids"])
        if not vres["ok"]:
            raise MesError(MesErrorCode.EVIDENCE_UNVERIFIABLE,
                           "evidence cards failed validation",
                           detail={"problems": vres["problems"]})

        # 3. PICO presence gate
        missing_pico = [f for f in ("population", "intervention", "outcome")
                        if not pico.get(f)]
        if missing_pico:
            raise MesError(MesErrorCode.PICO_MISSING,
                           "PICO/PECO core fields missing",
                           detail={"missing": missing_pico,
                                   "acquisition": {
                                       "population": "define target soil/material + density (e.g. Ottawa sand, Dr=60%)",
                                       "intervention": "define treatment (e.g. MICP, 1M cementation solution, 5 injections)",
                                       "outcome": "define measured outcome + unit (e.g. UCS at 7d, MPa)"}})

        # 4. comparability
        comp = heterogeneity_compute.check_comparability(cards)

        # 5. evidence + conflict matrices
        pico_unit = pico.get("unit")
        matrix = evidence_map.build_evidence_matrix(cards, pico_unit)
        conflicts = evidence_map.build_conflict_matrix(cards)

        # 6. effects + pooling decision
        effects: list[dict] = []
        for card in cards:
            arms = (card.get("reported_effect") or {}).get("arms")
            eff = effect_compute.compute_effect(card.get("ref_id"), arms)
            if eff is not None:
                effects.append({
                    "ref_id": eff.ref_id, "effect_size": eff.effect_size,
                    "variance": eff.variance, "ci95_low": eff.ci95_low,
                    "ci95_high": eff.ci95_high, "weight_note": eff.weight_note,
                })

        min_studies = int(constraints.get("min_poolable_studies", 2))
        i2_ceiling = float(constraints.get("max_heterogeneity_allowable", 75.0))
        meta = None
        sensitivity = None
        poolable = True
        pool_reason = "narrative"
        admissible, reason = meta_analyze.can_pool(effects, min_studies=min_studies,
                                                   i2_ceiling=i2_ceiling)
        # Comparability gate (SKILL.md §能力要求-3/§验收门槛-3): data that is not
        # comparable MUST stay isolated. Never pool across an incomparable unit.
        if comp["status"] == "incomparable":
            admissible = False
            reason = "comparability is 'incomparable' — data must stay isolated"
        if admissible:
            model = "random_effects" if len(effects) >= 3 else "fixed_effect"
            meta = meta_analyze.meta_analyze(effects, model=model)
            poolable = True
            pool_reason = reason
            try:
                sensitivity = sensitivity_run.run_sensitivity(effects, model=model)
            except MesError:
                sensitivity = None
        else:
            poolable = False
            pool_reason = reason
            # Even when the full pool is inadmissible (high heterogeneity), run
            # leave-one-out sensitivity on the poolable studies so an outlier /
            # high-bias card can be shown to restore admissibility (bootstrap
            # scenario 3: removing a high-bias study changes the result).
            if len(effects) >= 2:
                try:
                    sensitivity = sensitivity_run.run_sensitivity(effects, model="random_effects")
                except MesError:
                    sensitivity = None

        # 7. heterogeneity
        het = heterogeneity_compute.classify_heterogeneity(cards, meta)

        # 8. GRADE
        grade = grade_assess.assess_grade(cards, meta)

        # 9. build conclusions
        conclusions = self._build_conclusions(payload, matrix, conflicts, meta,
                                              poolable, pool_reason, comp, het, grade,
                                              requested)

        # 10. over-generalization self-check
        check = result_check_overgeneralization.check_conclusions(
            conclusions, env["evidence_used"])
        env["validation"]["self_check"] = "passed" if check["passed"] else "failed"
        env["validation"]["checks"] = check["checks"]
        if not check["passed"]:
            raise MesError(MesErrorCode.SELF_CHECK_FAILED,
                           "conclusions failed the over-generalization self-check",
                           detail={"checks": check["checks"]})

        # synthesis body
        env["synthesis"] = {
            "pico_framework": pico,
            "comparability_check": comp,
            "evidence_matrix": matrix,
            "conflict_matrix": conflicts,
            "conclusions": conclusions,
            "synthesis_method": "quantitative_meta_analysis" if meta else "structured_narrative",
            "conditions": self._derive_conditions(comp, het),
            "gaps": self._derive_gaps(cards, matrix, comp),
        }
        env["synthesis"]["meta_analysis"] = (
            {
                "model": meta.model,
                "pooled_effect": meta.pooled_effect,
                "ci95": meta.ci95,
                "between_study_variance_tau2": meta.between_study_variance_tau2,
                "weights": meta.weights,
            }
            if meta is not None else None
        )
        env["synthesis"]["sensitivity"] = sensitivity
        env["synthesis"]["heterogeneity"] = het
        env["synthesis"]["grade"] = grade

        # summary
        env["summary"] = self._summarize(payload, meta, poolable, pool_reason,
                                         conclusions, comp, grade)

        env["findings"] = self._findings_from_conclusions(conclusions, meta, grade)

        # PARTIAL semantics (SKILL.md §边界案例): a synthesis is PARTIAL when it
        # cannot deliver a fully comparable cross-study conclusion — a single
        # card (no cross-study claim), non-poolable/incomparable data, or a
        # conflict set that could not be resolved to a stable reading.
        partial_reasons = []
        n_cards = len(cards)
        if n_cards < 2:
            partial_reasons.append("fewer than 2 evidence cards — no cross-study synthesis claimed")
        if comp["status"] == "incomparable":
            partial_reasons.append("data are not comparable across studies and must stay isolated")
        elif comp["status"] == "conditional":
            partial_reasons.append("comparability is conditional on reported dimensions")
        if not poolable and n_cards >= 2:
            partial_reasons.append("quantitative pooling not admissible — narrative synthesis only")
        if partial_reasons:
            env["status"] = OutputStatus.PARTIAL.value
            env["assumptions"].append("PARTIAL: " + "; ".join(partial_reasons))
        else:
            env["status"] = OutputStatus.SUCCESS.value

        # gates: risk/approval flags -> HUMAN_APPROVAL_REQUIRED
        risk = payload.get("risk_level", "medium")
        approval = payload.get("human_approval_state") or {}
        needs_approval = self._needs_approval(payload)
        if needs_approval and not approval.get("granted"):
            env["status"] = OutputStatus.HUMAN_APPROVAL_REQUIRED.value
            env["errors"] = [MesError(
                MesErrorCode.APPROVAL_PENDING,
                "field deployment / live bio-experiment / hazardous chemicals / "
                "long-term knowledge write requires human approval").to_dict()]
            env["summary"] = env["errors"][0]["message"]
            return finalize_envelope(env, self._now())

        if risk in ("high", "critical"):
            env["requested_next_skills"] = self._audit_skills(env["requested_next_skills"])

        if not dry_run:
            env["artifacts"] = [{"kind": "synthesis", "path": None,
                                 "note": "machine-readable synthesis in output"}]

        return finalize_envelope(env, self._now())

    # ------------------------------------------------------------- sub-helpers
    def _now(self):
        t = self._clock() if self._clock else None
        return t

    def _needs_approval(self, payload: dict) -> bool:
        flags = payload.get("constraints") or {}
        return bool(flags.get("field_deployment") or flags.get("live_bio_experiment")
                    or flags.get("hazardous_chemicals") or flags.get("long_term_knowledge_write"))

    def _audit_skills(self, base: list) -> list:
        """high/critical risk chains the mandatory red-team + decision-gate
        audit skills (star topology via Router)."""
        seen = {s.get("skill") if isinstance(s, dict) else s for s in base}
        for name in ("obsidian-red-team", "obsidian-decision-gate"):
            if name not in seen:
                base.append({"skill": name,
                             "reason": "mandatory audit for high/critical risk",
                             "inputs_needed": ["synthesis output envelope"]})
        return base

    def _build_conclusions(self, payload, matrix, conflicts, meta, poolable,
                           pool_reason, comp, het, grade, requested) -> list[dict]:
        conclusions: list[dict] = []
        cid = 0

        def _add(label, statement, evidence_level="insufficient", scope="",
                 counterexample="", open_questions=None, conditions=None):
            nonlocal cid
            cid += 1
            conclusions.append({
                "id": f"C{cid:02d}",
                "statement": statement,
                "label": label,
                "evidence_level": evidence_level,
                "scope": scope,
                "counterexample": counterexample,
                "open_questions": open_questions or [],
                "conditions": conditions or [],
            })

        # pooled effect conclusion
        if meta is not None:
            ci = meta.ci95
            ci_txt = f"[{ci[0]}, {ci[1]}]" if ci[0] is not None else "n/a"
            _add(
                "CALCULATED",
                f"Pooled standardized effect {meta.pooled_effect} (95% CI {ci_txt}), "
                f"{meta.model.replace('_', ' ')} across {len(meta.weights)} studies.",
                evidence_level=self._effect_evidence_level(meta, grade),
                scope=f"{payload['pico'].get('population')} under {payload['pico'].get('intervention')}; "
                      f"effects standardized (Hedges' g)",
                counterexample="Any single study outside the pooled heterogeneity band; "
                               "prediction interval if reported",
                open_questions=[f"I2={het['statistical'].get('i2')}% — sources of residual heterogeneity",
                                f"pooling model: {meta.model}"],
                conditions=[pool_reason],
            )
        elif not poolable:
            reason_txt = pool_reason or "studies not comparable"
            _add(
                "INFERRED",
                f"Quantitative pooling not admissible ({reason_txt}); synthesis is "
                "structured narrative with per-study effect reporting.",
                evidence_level="insufficient",
                scope="All studies individually reported; no pooled estimate",
                counterexample="A future dataset with comparable arms and low heterogeneity "
                               "would permit pooling",
                open_questions=["identify missing arms/sds to enable pooling",
                                "reduce methodological heterogeneity"],
                conditions=[f"min_poolable_studies={(payload.get('constraints') or {}).get('min_poolable_studies', 2)}",
                            f"I2 ceiling={(payload.get('constraints') or {}).get('max_heterogeneity_allowable', 75)}%"],
            )

        # comparability summary conclusion
        _add(
            "INFERRED",
            f"Cross-study comparability is {comp['status']} across "
            f"{len(comp['dimensions'])} checked dimensions.",
            evidence_level="moderate",
            scope="Dimensions checked: " + ", ".join(d["dimension"] for d in comp["dimensions"]),
            counterexample="A study reporting a dimension as 'not reported' may change status if filled",
            open_questions=[d["detail"] for d in comp["dimensions"] if d["status"] == "missing"],
            conditions=["comparability is conditional on the reported dimensions"],
        )

        # conflict conclusion
        if conflicts:
            types = sorted({c["type"] for c in conflicts})
            _add(
                "INFERRED",
                f"{len(conflicts)} conflicts detected across {types}; each is "
                "explained by source, not averaged.",
                evidence_level="high",
                scope="Conflict matrix rows",
                counterexample="None — conflicts are reported, not resolved by fiat",
                open_questions=["mechanistic explanation for each conflict",
                                "whether a common protocol study would resolve the conflict"],
                conditions=["conflicts require explanation, not averaging"],
            )

        # grade conclusion
        _add(
            "RECOMMENDATION",
            f"Overall certainty for the synthesized conclusion set: {grade['certainty']}.",
            evidence_level=self._grade_evidence_level(grade),
            scope="GRADE-style 5-domain rating",
            counterexample="New high-quality randomized data could raise certainty",
            open_questions=[d["reason"] for d in grade["domains"] if d["rating"] in ("serious", "moderate")],
            conditions=["rating applies to this evidence set and outcome only"],
        )

        return conclusions

    def _effect_evidence_level(self, meta, grade) -> str:
        return grade["certainty"].replace("very_low", "insufficient")

    def _grade_evidence_level(self, grade) -> str:
        return grade["certainty"]

    def _derive_conditions(self, comp, het) -> list[str]:
        conds = [f"comparability: {comp['status']}"]
        for d in comp["dimensions"]:
            if d["status"] in ("mixed", "incomparable"):
                conds.append(f"{d['dimension']}: {d['detail']}")
        for t in het["types"]:
            if t["present"]:
                conds.append(f"heterogeneity({t['type']}): {t['detail']}")
        return conds

    def _derive_gaps(self, cards, matrix, comp) -> list[dict]:
        gaps: list[dict] = []
        missing_dims = [d for d in comp["dimensions"] if d["status"] == "missing"]
        if missing_dims:
            gaps.append({
                "gap": "missing comparability dimensions: " + ", ".join(d["dimension"] for d in missing_dims),
                "impact": "cannot certify cross-study comparability",
                "how_to_fill": "upstream skills (literature-scout / evidence-extractor) re-extract "
                               "strain, material, grain size, concentration, scale, protocol, measurement, endpoint",
            })
        arms_missing = sum(
            1 for c in cards if not ((c.get("reported_effect") or {}).get("arms"))
        )
        if arms_missing:
            gaps.append({
                "gap": f"{arms_missing} card(s) lack two-arm data for effect computation",
                "impact": "excluded from quantitative pooling",
                "how_to_fill": "re-extract treatment/control arms (n, mean, sd, unit) from source",
            })
        # evidence level gaps
        low_levels = [c["ref_id"] for c in matrix if c["evidence_level"] in ("L3_weak_indirect", "L4_no_evidence", "expert_opinion")]
        if low_levels:
            gaps.append({
                "gap": f"cards at low/indirect evidence tiers: {low_levels}",
                "impact": "lower certainty; not pooled as direct measurements",
                "how_to_fill": "prioritize direct L1/L2 evidence or clearly label indirectness",
            })
        return gaps

    def _summarize(self, payload, meta, poolable, pool_reason, conclusions, comp, grade) -> str:
        n = len(payload.get("evidence_cards", []))
        parts = [
            f"Synthesized {n} evidence card(s); comparability={comp['status']}; "
            f"certainty={grade['certainty']}."
        ]
        if meta is not None:
            parts.append(f"Pooled effect {meta.pooled_effect} (95% CI {meta.ci95}, {meta.model}).")
        else:
            parts.append(f"No pooling ({pool_reason}); structured narrative synthesis.")
        parts.append(f"{len(conclusions)} conditioned conclusions.")
        return " ".join(parts)

    def _findings_from_conclusions(self, conclusions, meta, grade) -> list[dict]:
        findings = []
        for c in conclusions:
            findings.append({"label": c["label"], "statement": c["statement"],
                             "source": f"conclusion {c['id']}"})
        if meta is not None:
            findings.append({"label": "CALCULATED",
                             "statement": f"Between-study variance tau2={meta.between_study_variance_tau2}",
                             "source": "meta_analyze"})
        return findings
