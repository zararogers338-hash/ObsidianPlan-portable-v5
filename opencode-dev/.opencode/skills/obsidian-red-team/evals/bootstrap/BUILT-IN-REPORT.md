# Bootstrap log — obsidian-red-team

> 2026-08-07 · Self-hosting: the Red Team reviews a real repository artifact,
> then reviews its own review, then is re-run after fixes. All CLI runs are
> real tool invocations (no faked results).

## Step 1 — Review of a real artifact (`micp-evidence-synthesizer`)

Target: the evidence-synthesizer's quantitative-pooling methodology claims
(`SKILL.md §5.6`): `can_pool` allows pooling when `I² ≤ 75%` and `≥2` studies
(2-study → fixed-effect; ≥3 → random-effect), plus GRADE-style certainty with
an imprecision domain that does not require sample-size/power evidence.

Input: `evals/bootstrap/step1-review-evidence-synthesizer.json`
Run: `python tools/ort/cli.py review < …`
Output: `evals/bootstrap/step1-output.json`

Result: `status=BLOCKED`, `state_recommendation=REVIEW_FAIL`, 8 findings,
2 BLOCKING.

Key findings produced by the deterministic scanner:

| finding | severity | dimension | substance |
|---|---|---|---|
| F02-001 | BLOCKING (BLOCK-10) | epistemic_escalation | target labels `RECOMMENDATION` but claims `VALIDATED` support |
| F02-002 | BLOCKING (BLOCK-10) | epistemic_escalation | same for the GRADE claim |
| F05-003 | CRITICAL | statistical_analysis | **I² treated as absolute heterogeneity**: I² is precision-confounded (varies with k and sample size); a single 75% threshold misjudges poolability |
| F05-004 | CRITICAL | statistical_analysis | **2-study fixed-effect pooling**: k=2 cannot estimate τ²; fixed effect assumes zero heterogeneity and one study can dominate the pooled estimate |
| F05-007 | MAJOR | statistical_analysis | **GRADE imprecision without sample-size/power evidence**: CI-width-only imprecision can misrate small underpowered studies |
| F07-008 | CRITICAL | model_boundary | missing declared boundary conditions (I² threshold, min studies) |

The two CRITICAL methodology findings are the **strongest counterexamples**
the review must not miss (they were absent before the bootstrap loop exposed
the gap — see Step 3).

## Step 2 — Red Team reviews its own review

Input: `evals/bootstrap/step2-self-review.json`
Run: `python tools/ort/cli.py review < …`
Output: `evals/bootstrap/step2-output.json`

Result: `status=SUCCESS`, `state_recommendation=NO_OBJECTION`, 5 findings
(2× I²-precision CRITICAL, 2× 2-study fixed-effect CRITICAL, 1× GRADE-imprecision
MAJOR).

Conclusion of the self-review: the review **does not miss the strongest
counterexamples** (I² precision-confounding and 2-study fixed-effect
unreliability are both surfaced), findings carry concrete evidence + location +
counterexample + executable fix + verification method, and the BLOCKING
(epistemic escalation) is justified by the declared label/support mismatch.

## Step 3 — Gap found and fixed

The first self-review run returned `findings: 0` — the Red Team had reviewed
the evidence-synthesizer but **missed the strongest methodological
counterexamples** (I²-as-absolute-heterogeneity, 2-study fixed-effect pooling).
This is precisely the failure mode the bootstrap is designed to catch
("是否遗漏最强反例").

Fix applied:
- Added `_scan_stat_methodology` to the service (`tools/ort/service.py`):
  text-based, deterministic patterns for I² precision-confounding,
  k<3 fixed-effect pooling, and GRADE imprecision-without-power. These fire
  even when no structured `analysis` object is supplied, so a methodology
  claim in a SKILL/README/report is attacked on its substance.
- Re-ran both steps; step 1 now surfaces the strongest counterexamples and
  step 2 confirms they are present.

## Step 4 — Regression check

`python -m pytest tests/ -q` → 65 passed.
`python evals/run_evals.py` → all 15 adversarial cases intercepted, M1–M7 all
PASS (M5 adversarial_interception_rate = 1.0).

## Open risks (未关闭风险)

1. **Citation verification is offline and structural.** A DOI that is
   well-formed but belongs to a different paper is marked UNVERIFIED (not
   REJECTED) unless its locator is malformed or its title is placeholder-like.
   Full-text/DOI-registry verification is a recommended human/networked
   follow-up (`verification_required` flags are emitted). This is a design
   limit, not a false negative in the 15 cases.
2. **Ammonia/regulatory limits are a bundled default table** (GB/T 14848-2017
   Class III 0.5 mg/L, GBZ 2.1-2019, etc.). A deployment under a stricter
   jurisdiction requires `constraints.ammonia_limit_source`; otherwise the
   BLOCK-2/BLOCK-6 judgment uses the default. Explicitly documenting the
   applicable limit source is the required fix for BLOCK-6.
3. **Methodology patterns are a curated set.** The `_scan_stat_methodology`
   list covers the I²/k<3/GRADE patterns that this bootstrap exposed. New
   methodological traps must be appended to `STAT_METHOD_PATTERNS` (with a
   test) as they are discovered — the list is not exhaustive.
4. **The escalation checker models gates from the brief**
   (SUPPORTED→VALIDATED→PILOT_READY→DEPLOYABLE) plus the project's review/
   approval gates. If the Controller later uses different gate names, the
   `escalation.py` gate table must be synchronized.
5. **Red Team is read-only but its verdict is advisory to the human.** The
   machine refuses `→ VALIDATED`/`→ DEPLOYABLE` when the latest review verdict
   is `fail` (OSM `requires_review_pass` guard, verified by
   `obsidian-state-manager/tests/test_red_team_gate.py`), but a human can still
   choose to proceed by recording a fresh `review.complete` pass after closing
   findings. That is the intended human-override path; it is not a bypass.

## Deliverables locked

- `evals/bootstrap/step1-output.json` — real review of a real artifact.
- `evals/bootstrap/step2-output.json` — self-review of that review.
- `tests/test_bootstrap.py` — regression test asserting the bootstrap loop
  surfaces the strongest methodological counterexamples.
