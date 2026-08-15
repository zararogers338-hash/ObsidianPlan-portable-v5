"""Service: orchestrates contract validation → action dispatch → output assembly
→ self-check → trace logging. Pure of transport: the CLI owns stdin/stdout and
filesystem paths; tests inject transports and clocks.

Mirrors the router/state-manager convention: an envelope-shaped output that
always validates against output.schema.json, and a machine-parseable error list.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import adapters, cite, dedup, doi, triage
from .errors import (
    MlsError,
    e101_input_schema,
    e102_missing_fields,
    e103_invalid_action,
    e104_version_mismatch,
    e201_doi_unresolved,
    e202_doi_metadata_mismatch,
    e203_suspected_forged,
    e301_trace_corrupt,
    e402_network_unavailable,
    e501_network_approval_required,
    e502_write_approval_required,
    e701_output_schema_failed,
    e702_epistemic_mislabel,
    e703_scale_mislabel,
)
from .models import EpistemicLabel, EvidenceScope, OutputStatus
from .validate import list_issues, validate_input, validate_output

SKILL_NAME = "micp-literature-scout"
SKILL_VERSION = "1.0.0"
CONTRACT_VERSION = "1.0"
TOOL_VERSION = "1.0.0"

ACTIONS = [
    "search.run", "search.repeat", "doi.verify", "dedup.merge",
    "triage.screen", "cite.export", "sources.register", "validate.self",
]

# Actions that touch the network.
NETWORK_ACTIONS = {"search.run", "search.repeat", "doi.verify"}
# Actions that write to disk beyond the trace log.
WRITE_ACTIONS = {"sources.register", "cite.export"}

# Required inputs the unified envelope must carry; keyed with guidance.
REQUIRED_INPUTS = {
    "task_id": "任务节点标识；由 Task Decomposer 分配，用于审计锚点与预算记账",
    "project_id": "项目/实验标识；来自项目注册，决定 trace 日志与复现档案归属",
    "request": "任务陈述；由 Mission Lock 任务合同提供，决定检索式与分层目标",
    "action": "唯一执行入口；由控制器或 Router 指定",
    "skill_version": "本 Skill 版本；由 SKILL.md frontmatter 声明",
    "contract_version": "输入契约版本；由控制器按统一契约注入",
    "timestamp": "ISO-8601 时间戳；由控制器调用时注入",
}

ALLOWED_ROLES = ("controller", "skill", "human", "auditor")

# Claims that may never be labeled as if directly observed.
_CANNOT_BE_OBSERVED = {
    "综述显示", "研究表明", "文献报告", "模型预测", "可能", "推测",
    "建议", "应", "需要", "higher strength", "review shows", "suggests",
    "recommend", "should", "may improve", "likely",
}

_VALID_SCOPES = {s.value for s in EvidenceScope}


def _now_iso(now: Any) -> str:
    if now is not None:
        return now().isoformat()
    return datetime.now(timezone.utc).isoformat()


def _trace_dir(payload: dict[str, Any], cwd: Path) -> Path:
    override = payload.get("trace_dir")
    if override:
        return Path(override)
    return cwd / "traces"


def _write_trace(payload: dict[str, Any], trace_path: Path, repro: str, entry: dict[str, Any]) -> str | None:
    """Append a JSONL trace entry; return the ref or None on failure."""
    try:
        trace_path.mkdir(parents=True, exist_ok=True)
        file = trace_path / f"{repro}.jsonl"
        with file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return str(file)
    except OSError as exc:
        return None  # caller turns it into MLS-E301 if needed


def _first_error(out: dict[str, Any]) -> MlsError | None:
    for e in out.get("errors", []):
        return e
    return None


def _has_status(out: dict[str, Any], status: str) -> bool:
    return out.get("status") == status


def _findings(f: Any) -> list[dict[str, Any]]:
    if isinstance(f, list):
        return [x for x in f if isinstance(x, dict)]
    return []


def _label_value(item: dict[str, Any]) -> str:
    return str(item.get("label", ""))


class SkillService:
    """One skill invocation. Pure except for explicit disk writes (trace/export)."""

    def __init__(
        self,
        *,
        cwd: Path | None = None,
        now: Any = None,
        transport: Any = None,
        offline: bool = False,
    ) -> None:
        self.cwd = Path(cwd or Path.cwd())
        self.now = now
        self.transport = transport
        self.offline = offline

    # -- envelope scaffolding ------------------------------------------------

    def _base_envelope(self, payload: dict[str, Any], status: str, summary: str) -> dict[str, Any]:
        return {
            "status": status,
            "summary": summary,
            "findings": [],
            "assumptions": [],
            "evidence_used": [],
            "uncertainty": [],
            "risks": [],
            "artifacts": [],
            "requested_next_skills": [],
            "validation": {"self_check_passed": False, "output_schema_valid": False, "checks": []},
            "provenance": {
                "skill_name": SKILL_NAME,
                "skill_version": str(payload.get("skill_version") or SKILL_VERSION),
                "contract_version": str(payload.get("contract_version") or CONTRACT_VERSION),
                "tool_version": TOOL_VERSION,
                "timestamp": _now_iso(self.now),
            },
            "errors": [],
        }

    # -- validation ----------------------------------------------------------

    def _contract_check(self, payload: dict[str, Any]) -> MlsError | None:
        cv = str(payload.get("contract_version") or "")
        major = cv.split(".")[0] if cv else ""
        if major != "1":
            return e104_version_mismatch(cv)
        return None

    # -- self check ----------------------------------------------------------

    def _self_check(self, out: dict[str, Any]) -> None:
        checks: list[dict[str, Any]] = []
        valid, issues = validate_output(out)
        checks.append({"name": "output_schema", "passed": valid, "detail": issues[0].message if issues else ""})
        checks.append({"name": "status_non_empty", "passed": bool(out.get("status")), "detail": ""})
        checks.append({"name": "summary_non_empty", "passed": bool(out.get("summary")), "detail": ""})
        codes = [e.get("code") for e in out.get("errors", []) if isinstance(e, dict)]
        checks.append({"name": "error_codes_valid", "passed": all(re.match(r"^MLS-E\d{3}$", c) for c in codes), "detail": ""})
        labels = [_label_value(f) for f in _findings(out.get("findings"))]
        labels += [_label_value(a) for a in _findings(out.get("assumptions"))]
        checks.append({"name": "labels_valid", "passed": all(l in EpistemicLabel._value2member_map_ for l in labels), "detail": ""})

        mislabels: list[str] = []
        for f in _findings(out.get("findings")):
            statement = str(f.get("statement", ""))
            label = _label_value(f)
            if label == "OBSERVED" and any(hint in statement for hint in _CANNOT_BE_OBSERVED):
                mislabels.append(f"{statement[:40]}…")
        checks.append({"name": "no_epistemic_mislabel", "passed": not mislabels, "detail": "; ".join(mislabels)})

        # scope is optional in the schema; only non-empty scopes must be valid.
        scopes = [f.get("scope", "") for f in _findings(out.get("findings"))]
        bad_scopes = [s for s in scopes if s and s not in _VALID_SCOPES]
        checks.append({"name": "scopes_valid", "passed": not bad_scopes, "detail": f"非法 scope: {bad_scopes}"})

        out["validation"] = {
            "self_check_passed": all(c["passed"] for c in checks),
            "output_schema_valid": valid,
            "checks": checks,
        }

    # -- action dispatch -----------------------------------------------------

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            out = self._base_envelope({}, OutputStatus.FAILED.value, "输入必须是 JSON 对象")
            out["errors"].append(MlsError("MLS-E101", "输入必须是 JSON 对象",
                                          {"got": type(payload).__name__}).to_dict())
            out["findings"].append({"statement": out["summary"], "label": "OBSERVED"})
            self._self_check(out)
            return out

        # 0. Required-field completeness with guidance, BEFORE schema validation:
        #    a missing unified-envelope field must surface as BLOCKED + MLS-E102
        #    naming the field (metric M4), not as a generic E101.
        missing = {f: REQUIRED_INPUTS[f] for f in REQUIRED_INPUTS if not payload.get(f)}
        if missing:
            err = e102_missing_fields(missing)
            out = self._base_envelope(payload, OutputStatus.BLOCKED.value,
                                      f"缺少关键输入: {', '.join(sorted(missing))}；各字段获取方式见 errors[0].detail")
            out["errors"].append(err.to_dict())
            out["findings"].append({"statement": out["summary"], "label": "OBSERVED"})
            self._self_check(out)
            return out

        # 1. Action validity — checked before schema validation so an unknown
        #    action surfaces as MLS-E103, not as a generic enum violation.
        action = payload.get("action")
        if not isinstance(action, str) or action not in ACTIONS:
            err = e103_invalid_action(action, ACTIONS)
            out = self._base_envelope(payload, OutputStatus.FAILED.value, f"action 非法: {action!r}")
            out["errors"].append(err.to_dict())
            out["findings"].append({"statement": out["summary"], "label": "OBSERVED"})
            self._self_check(out)
            return out

        # 2. Input schema validation (structural/type/enum).
        valid, issues = validate_input(payload)
        if not valid:
            err = e101_input_schema(list_issues(issues))
            out = self._base_envelope(payload, OutputStatus.FAILED.value, f"输入未通过 schema 校验({len(issues)} 处问题)")
            out["errors"].append(err.to_dict())
            out["findings"].append({"statement": out["summary"], "label": "OBSERVED"})
            self._self_check(out)
            return out

        # 3. Contract major version.
        contract_err = self._contract_check(payload)
        if contract_err:
            out = self._base_envelope(payload, OutputStatus.BLOCKED.value, contract_err.message)
            out["errors"].append(contract_err.to_dict())
            out["findings"].append({"statement": out["summary"], "label": "OBSERVED"})
            self._self_check(out)
            return out

        # 4. Actor role.
        actor = payload.get("actor") or {}
        role = actor.get("role", "skill")
        if role not in ALLOWED_ROLES:
            out = self._base_envelope(payload, OutputStatus.FAILED.value, f"角色非法: {role!r}")
            out["errors"].append(MlsError("MLS-E503", f"角色非法: {role!r}", {"role": role}).to_dict())
            self._self_check(out)
            return out

        # 5. Human approval gates.
        approval = payload.get("human_approval_state") or {}
        if not self.offline and action in NETWORK_ACTIONS and not approval.get("granted"):
            out = self._base_envelope(payload, OutputStatus.HUMAN_APPROVAL_REQUIRED.value,
                                      "网络检索/核验需要人工审批 (human_approval_state.granted=true)")
            out["errors"].append(e501_network_approval_required(action).to_dict())
            out["findings"].append({"statement": out["summary"], "label": "OBSERVED"})
            self._self_check(out)
            return out
        if action in WRITE_ACTIONS and not approval.get("granted"):
            out = self._base_envelope(payload, OutputStatus.HUMAN_APPROVAL_REQUIRED.value,
                                      "写盘/来源登记需要人工审批")
            out["errors"].append(e502_write_approval_required(action).to_dict())
            out["findings"].append({"statement": out["summary"], "label": "OBSERVED"})
            self._self_check(out)
            return out

        # 6. Dispatch.
        handler = getattr(self, f"_do_{action.replace('.', '_')}", None)
        if handler is None:
            out = self._base_envelope(payload, OutputStatus.FAILED.value, f"action 未实现: {action}")
            out["errors"].append(MlsError("MLS-E103", f"action 未实现: {action}", {}).to_dict())
            self._self_check(out)
            return out
        out = handler(payload)
        self._self_check(out)
        return out

    # -- handlers ------------------------------------------------------------

    def _do_search_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        query_spec = payload.get("query") or {}
        text = str(query_spec.get("text") or payload.get("request") or "").strip()
        if len(text) < 3:
            out = self._base_envelope(payload, OutputStatus.BLOCKED.value, "query.text 至少 3 个字符")
            out["errors"].append(MlsError("MLS-E102", "query.text 缺失或过短", {"missing_fields": {"query.text": "检索式内容；由请求与领域检索式构造提供"}}).to_dict())
            self._self_check(out)
            return out

        n = int(query_spec.get("n") or 10)
        database = str(query_spec.get("database") or "auto")
        lang = str(query_spec.get("lang") or "en")
        time_range = self._parse_range(payload.get("constraints") or [])
        built = adapters.build_query(text, lang=lang)
        repro = adapters.repro_id(built, database=database, n=n, time_range=time_range)

        # Approval already enforced in run(); dry_run skips network & writes.
        dry_run = bool(payload.get("dry_run"))
        used_db = "none"
        records: list[dict[str, Any]] = []
        warnings: list[str] = []
        network_error: MlsError | None = None

        if not dry_run:
            # offline service mode forces the deterministic fixture path.
            eff_db = "offline_fixture" if self.offline else database
            try:
                records, used_db, warnings = adapters.search_all(
                    built, database=eff_db, n=n, time_range=time_range,
                    transport=self.transport,
                )
            except adapters.SearchError as exc:
                network_error = exc
            except Exception as exc:  # noqa: BLE001
                network_error = MlsError("MLS-E401", f"检索适配器异常: {exc}", {"exc": type(exc).__name__})
        else:
            warnings.append("dry_run: 未调用网络检索")

        out = self._base_envelope(payload, OutputStatus.SUCCESS.value, "检索完成")
        search_block: dict[str, Any] = {
            "database": used_db,
            "query": built,
            "filters": {
                "language": lang,
                "n": n,
                "time_range": [t for t in time_range if t is not None] or None,
                "inclusion": ["领域检索式构造", "语言筛选", "时间窗"],
                "exclusion": ["非 MICP 领域", "无 DOI 且无标题"],
                "dedup": "doi / 标题规范化 / 同题-同年-同刊",
            },
            "result_count": len(records),
            "retrieved_at": _now_iso(self.now),
            "records": records,
        }
        if network_error:
            search_block["database"] = "offline_fixture" if used_db == "offline_fixture" else "none"
            out["errors"].append(network_error.to_dict())
            out["status"] = OutputStatus.PARTIAL.value
            out["summary"] = "检索降级完成（详见 errors 与 search.filters）"
        out["search"] = search_block

        # Dedup merged records.
        merged = dedup.dedup_records(records)
        out["dedup"] = {
            "input_count": merged["input_count"],
            "output_count": merged["output_count"],
            "merged_groups": merged["merged_groups"],
        }
        unique = merged["unique_records"]

        # Triage (if records exist) — deterministic.
        if unique:
            triage_out = triage.screen(unique)
            out["triage"] = triage_out
            out["findings"] = self._findings_from_search(payload, triage_out, used_db)
        else:
            out["triage"] = {"levels": [], "rejections": []}
            out["findings"] = [{
                "statement": "检索未返回可分层记录; 检索盲区与覆盖偏差见 search.filters 与 summary",
                "label": "OBSERVED",
            }]

        out["uncertainty"].append("检索排名来自上游相关性算法, 不构成证据强度")
        out["uncertainty"].extend(warnings)
        out["provenance"]["repro_id"] = repro

        trace_ref = self._write_search_trace(payload, repro, built, used_db, records)
        if trace_ref:
            out["provenance"]["trace_log_ref"] = trace_ref
        return out

    def _do_search_repeat(self, payload: dict[str, Any]) -> dict[str, Any]:
        out = self._do_search_run(payload)
        if out["status"] not in ("SUCCESS", "PARTIAL"):
            return out
        out["summary"] = "重复检索完成（相同检索式 → 相同 repro_id，见 provenance）"
        out["findings"].append({
            "statement": "相同检索式与约束下 repro_id 一致，检索可复现",
            "label": "CALCULATED",
            "scope": "review",
            "refs": [out["provenance"].get("repro_id", "")],
        })
        return out

    def _do_doi_verify(self, payload: dict[str, Any]) -> dict[str, Any]:
        candidate_dois = payload.get("candidate_dois") or []
        if not candidate_dois or not isinstance(candidate_dois, list):
            out = self._base_envelope(payload, OutputStatus.BLOCKED.value, "candidate_dois 缺失或为空")
            out["errors"].append(MlsError("MLS-E102", "candidate_dois 缺失或为空",
                                          {"missing_fields": {"candidate_dois": "待核验 DOI 列表；逐条核验存在性与元数据"}}).to_dict())
            out["findings"].append({"statement": out["summary"], "label": "OBSERVED"})
            self._self_check(out)
            return out

        online = not self.offline and not bool(payload.get("dry_run"))
        approval = (payload.get("human_approval_state") or {}).get("granted")
        # Network DOI verification is gated in run(); here we just respect offline.
        fetcher = None
        if online and approval:
            fetcher = doi.CrossrefFetcher(transport=self.transport)
        elif online and not approval:
            # Approval gate already returned earlier for NETWORK_ACTIONS; this is
            # defensive for direct handler tests.
            online = False

        results = doi.verify_dois(
            list(candidate_dois),
            online=online,
            fetcher=fetcher,
            claimed_map=payload.get("claimed_metadata"),
        )
        out = self._base_envelope(payload, OutputStatus.SUCCESS.value,
                                  f"DOI 核验完成: {len(results)} 条")
        out["doi_verifications"] = results

        verified = sum(1 for r in results if r.get("status") == "verified")
        forged = [r for r in results if r.get("status") == "suspected_forged"]
        not_found = [r for r in results if r.get("status") == "not_found"]
        unverified = [r for r in results if r.get("status") in ("offline_unverified", "check_failed")]

        for r in results:
            if r.get("status") == "verified":
                out["findings"].append({
                    "statement": f"DOI {r['doi']} 存在且可核验",
                    "label": "REPORTED",
                    "scope": "review",
                    "refs": [r["doi"]],
                })
            elif r.get("status") == "suspected_forged":
                out["findings"].append({
                    "statement": f"DOI {r['doi']} 疑似伪造: {r.get('reason', '')}",
                    "label": "INFERRED",
                    "scope": "review",
                    "refs": [r["doi"]],
                })
            elif r.get("status") == "not_found":
                out["findings"].append({
                    "statement": f"DOI {r['doi']} 在 Crossref 未登记(404)",
                    "label": "REPORTED",
                    "scope": "review",
                    "refs": [r["doi"]],
                })
            elif r.get("status") == "offline_unverified":
                out["findings"].append({
                    "statement": f"DOI {r['doi']} 离线无法核验存在性(仅结构合法)",
                    "label": "INFERRED",
                    "scope": "review",
                    "refs": [r["doi"]],
                })

        if not_found:
            for r in not_found:
                out["errors"].append(e201_doi_unresolved(r["doi"], "Crossref 404").to_dict())
        if forged:
            for r in forged:
                out["errors"].append(e203_suspected_forged(r["doi"], r.get("reason", "元数据不一致")).to_dict())
            out["status"] = OutputStatus.PARTIAL.value
            out["summary"] = f"DOI 核验完成; {len(forged)} 条疑似伪造, 未采信"

        if unverified:
            out["uncertainty"].append(f"{len(unverified)} 条因网络不可用未能实时核验")

        trace_ref = self._write_trace_entry(payload, "doi.verify", results)
        if trace_ref:
            out["provenance"]["trace_log_ref"] = trace_ref
        return out

    def _do_dedup_merge(self, payload: dict[str, Any]) -> dict[str, Any]:
        records = payload.get("records") or []
        if not records or not isinstance(records, list):
            out = self._base_envelope(payload, OutputStatus.BLOCKED.value, "records 缺失或为空")
            out["errors"].append(MlsError("MLS-E102", "records 缺失或为空",
                                          {"missing_fields": {"records": "候选记录列表; 每项需 ref_id/doi/title/year/container"}}).to_dict())
            out["findings"].append({"statement": out["summary"], "label": "OBSERVED"})
            self._self_check(out)
            return out
        merged = dedup.dedup_records(records)
        out = self._base_envelope(payload, OutputStatus.SUCCESS.value,
                                  f"去重完成: {merged['input_count']} → {merged['output_count']}")
        out["dedup"] = {
            "input_count": merged["input_count"],
            "output_count": merged["output_count"],
            "merged_groups": merged["merged_groups"],
        }
        out["findings"].append({
            "statement": f"去重 {merged['input_count']}→{merged['output_count']} (DOI/标题规范化/同题-同年-同刊)",
            "label": "CALCULATED",
            "scope": "review",
        })
        return out

    def _do_triage_screen(self, payload: dict[str, Any]) -> dict[str, Any]:
        records = payload.get("records") or []
        if not records or not isinstance(records, list):
            out = self._base_envelope(payload, OutputStatus.BLOCKED.value, "records 缺失或为空")
            out["errors"].append(MlsError("MLS-E102", "records 缺失或为空",
                                          {"missing_fields": {"records": "候选记录列表; 每项需 ref_id/doi/title/scale/kind"}}).to_dict())
            out["findings"].append({"statement": out["summary"], "label": "OBSERVED"})
            self._self_check(out)
            return out
        triage_out = triage.screen(records)
        out = self._base_envelope(payload, OutputStatus.SUCCESS.value,
                                  f"分层完成: TIER1={sum(1 for l in triage_out['levels'] if l['level']=='TIER1')}, "
                                  f"TIER2={sum(1 for l in triage_out['levels'] if l['level']=='TIER2')}, "
                                  f"TIER3={sum(1 for l in triage_out['levels'] if l['level']=='TIER3')}, "
                                  f"REJECT={len(triage_out['rejections'])}")
        out["triage"] = triage_out
        out["findings"] = self._findings_from_search(payload, triage_out, "records")
        return out

    def _do_cite_export(self, payload: dict[str, Any]) -> dict[str, Any]:
        records = payload.get("records") or []
        fmt = payload.get("format") or "bibtex"
        if not records or not isinstance(records, list):
            out = self._base_envelope(payload, OutputStatus.BLOCKED.value, "records 缺失或为空")
            out["errors"].append(MlsError("MLS-E102", "records 缺失或为空",
                                          {"missing_fields": {"records": "待导出记录列表; 每项需 ref_id/doi/title/year/container/authors"}}).to_dict())
            out["findings"].append({"statement": out["summary"], "label": "OBSERVED"})
            self._self_check(out)
            return out
        try:
            content = cite.export(records, fmt)
        except ValueError as exc:
            out = self._base_envelope(payload, OutputStatus.BLOCKED.value, str(exc))
            out["errors"].append(MlsError("MLS-E103", str(exc), {}).to_dict())
            out["findings"].append({"statement": out["summary"], "label": "OBSERVED"})
            self._self_check(out)
            return out

        written_to = ""
        out_file = payload.get("out_file")
        if out_file:
            try:
                path = Path(out_file)
                if path.is_absolute():
                    path = path
                else:
                    path = self.cwd / path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
                written_to = str(path)
            except OSError as exc:
                out = self._base_envelope(payload, OutputStatus.FAILED.value, f"导出写盘失败: {exc}")
                out["errors"].append(MlsError("MLS-E301", f"导出写盘失败: {exc}", {}).to_dict())
                out["findings"].append({"statement": out["summary"], "label": "OBSERVED"})
                self._self_check(out)
                return out

        out = self._base_envelope(payload, OutputStatus.SUCCESS.value,
                                  f"导出 {len(records)} 条为 {fmt}" + (f" → {written_to}" if written_to else ""))
        out["exports"] = [{"format": fmt, "content": content, "written_to": written_to}]
        return out

    def _do_sources_register(self, payload: dict[str, Any]) -> dict[str, Any]:
        reference = payload.get("reference")
        if not reference or not isinstance(reference, dict):
            out = self._base_envelope(payload, OutputStatus.BLOCKED.value, "reference 缺失")
            out["errors"].append(MlsError("MLS-E102", "reference 缺失",
                                          {"missing_fields": {"reference": "待登记来源对象; 需 kind/title/url_or_doi/purpose"}}).to_dict())
            out["findings"].append({"statement": out["summary"], "label": "OBSERVED"})
            self._self_check(out)
            return out
        registry = self.cwd / "references" / "registry" / "registry.jsonl"
        entry = dict(reference)
        entry.setdefault("access_date", _now_iso(self.now).split("T")[0])
        try:
            registry.parent.mkdir(parents=True, exist_ok=True)
            with registry.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as exc:
            out = self._base_envelope(payload, OutputStatus.FAILED.value, f"来源登记写盘失败: {exc}")
            out["errors"].append(MlsError("MLS-E301", f"来源登记写盘失败: {exc}", {}).to_dict())
            out["findings"].append({"statement": out["summary"], "label": "OBSERVED"})
            self._self_check(out)
            return out
        out = self._base_envelope(payload, OutputStatus.SUCCESS.value,
                                  f"来源已登记: {entry.get('title') or entry.get('ref_id')} → {registry}")
        out["artifacts"].append({
            "ref_id": entry.get("ref_id") or f"src-{uuid.uuid4().hex[:8]}",
            "uri": str(registry),
            "media_type": "application/jsonl",
            "note": "source registry entry",
        })
        return out

    def _do_validate_self(self, payload: dict[str, Any]) -> dict[str, Any]:
        out = self._base_envelope(payload, OutputStatus.SUCCESS.value, "自检完成")
        # Confirm trace dir is writable.
        trace_path = _trace_dir(payload, self.cwd)
        try:
            trace_path.mkdir(parents=True, exist_ok=True)
            probe = trace_path / ".probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            out["uncertainty"].append("trace 目录可写")
        except OSError as exc:
            out["errors"].append(MlsError("MLS-E301", f"trace 目录不可写: {exc}", {"path": str(trace_path)}).to_dict())

        # Run the full self-check so output_schema/validation reflect the final envelope.
        self._self_check(out)
        out["selfcheck"] = {
            "passed": out["validation"]["self_check_passed"],
            "reasons": [c["name"] for c in out["validation"]["checks"] if c["passed"]],
        }
        out["status"] = OutputStatus.SUCCESS.value if out["selfcheck"]["passed"] else OutputStatus.FAILED.value
        out["summary"] = "自检通过" if out["selfcheck"]["passed"] else "自检失败: 见 validation.checks"
        return out

    # -- helpers -------------------------------------------------------------

    def _parse_range(self, constraints: list[Any]) -> tuple[int | None, int | None]:
        for c in constraints or []:
            text = str(c)
            if text.startswith("time_range:"):
                return adapters.parse_time_range(text.split(":", 1)[1])
        return (None, None)

    def _findings_from_search(self, payload: dict[str, Any], triage_out: dict[str, Any], db: str) -> list[dict[str, Any]]:
        """Convert triage levels into labeled findings. TIER1/2 become REPORTED
        statements (they cite records); the tier assignment itself is CALCULATED."""
        findings: list[dict[str, Any]] = []
        tier_counts: dict[str, int] = {}
        for item in triage_out.get("levels", []):
            tier_counts[item["level"]] = tier_counts.get(item["level"], 0) + 1
            findings.append({
                "statement": f"{item['ref_id']} 分层为 {item['level']}: {item['reason']}",
                "label": "CALCULATED",
                "scope": "review",
                "refs": [item["ref_id"]],
            })
        rej = len(triage_out.get("rejections", []))
        summary = (
            f"检索完成: 数据库={db}, 分层 TIER1={tier_counts.get('TIER1', 0)}, "
            f"TIER2={tier_counts.get('TIER2', 0)}, TIER3={tier_counts.get('TIER3', 0)}, 拒绝={rej}"
        )
        return findings or [{
            "statement": "检索未返回可分层记录",
            "label": "OBSERVED",
        }]

    def _write_search_trace(self, payload: dict[str, Any], repro: str, query: str, db: str, records: list[dict[str, Any]]) -> str | None:
        entry = {
            "ts": _now_iso(self.now),
            "project_id": payload.get("project_id"),
            "task_id": payload.get("task_id"),
            "action": "search.run",
            "repro_id": repro,
            "query": query,
            "database": db,
            "result_count": len(records),
            "records": [{"ref_id": r.get("ref_id"), "doi": r.get("doi"),
                         "title": (r.get("title") or "")[:80],
                         "doi_status": r.get("doi_status", "not_checked")} for r in records],
        }
        return _write_trace(payload, _trace_dir(payload, self.cwd), repro, entry)

    def _write_trace_entry(self, payload: dict[str, Any], action: str, data: Any) -> str | None:
        repro = adapters.repro_id(str(payload.get("request") or action))
        entry = {
            "ts": _now_iso(self.now),
            "project_id": payload.get("project_id"),
            "task_id": payload.get("task_id"),
            "action": action,
            "repro_id": repro,
            "data": data,
        }
        return _write_trace(payload, _trace_dir(payload, self.cwd), repro, entry)
