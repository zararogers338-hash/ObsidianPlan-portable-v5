"""Analysis report generator (spec §七 "图表与分析报告生成器").

Deterministic, offline, pure-stdlib. Produces a structured report object that
summarizes an interpret.phases result into human- and machine-readable
sections, plus a compact ASCII bar chart for XRD peak profiles (so a report
can be rendered in a terminal without any plotting dependency).

This is *not* a fancy charting library — the skill deliberately avoids
fabricating figures. Every number in the report comes from the envelope's own
``results``; the generator only reshapes and annotates it, so the report can
never claim data the analysis did not produce.
"""

from __future__ import annotations

from typing import Any

from .errors import make_error


def _bar(value: float, max_value: float, width: int = 40) -> str:
    """A deterministic ASCII bar for one value (0..max_value)."""
    if max_value <= 0:
        return "·" * width
    filled = int(round(width * max(0.0, min(1.0, value / max_value))))
    return "#" * filled + "-" * (width - filled)


def xrd_ascii_chart(matches: list[dict[str, Any]], *, width: int = 48) -> str:
    """Render the matched XRD peaks as a compact ASCII chart.

    `matches` is the list of per-phase dicts from an xrd_match result
    (each has ``peaks`` with obs_2theta / rel_intensity_pct). One chart per
    phase; phases with no matched peaks produce a one-line note.
    """
    lines: list[str] = ["XRD 峰匹配图(CALCULATED;纵轴为相对强度 %)"]
    if not matches:
        return "\n".join(lines + ["  (无匹配结果)"])
    for m in matches:
        peaks = m.get("peaks") or []
        lines.append(f"  [{m.get('phase')}] verdict={m.get('verdict')} score={m.get('score')}")
        if not peaks:
            lines.append("    (无匹配峰)")
            continue
        max_rel = max(float(p.get("rel_intensity_pct", 0.0) or 0.0) for p in peaks)
        for p in peaks:
            rel = float(p.get("rel_intensity_pct", 0.0) or 0.0)
            lines.append(
                f"    {p.get('obs_2theta', 0):6.2f}°  d={p.get('obs_d_A', 0):.3f}Å  {_bar(rel, max_rel, width)} {rel:5.1f}%"
            )
    return "\n".join(lines)


def _evidence_summary(results: dict[str, Any]) -> list[str]:
    out: list[str] = []
    xrd = results.get("xrd") or []
    if xrd:
        top = xrd[0]
        out.append(f"XRD: 主导候选 {top.get('phase')}({top.get('verdict')}, score {top.get('score')})")
    eds = results.get("eds_ca_present")
    if eds is not None:
        out.append(f"EDS: 检出 Ca = {eds} (只证明含钙相,不证明 CaCO3 或晶型)")
    tga = results.get("tga_co2_likely")
    if tga is not None:
        out.append(f"TGA: CO2 质量损失与碳酸盐化学计量一致 = {tga}")
    spectra = results.get("spectra") or {}
    for phase, ev in spectra.items():
        for modality, bands in ev.items():
            if bands:
                out.append(f"{modality.upper()}: {phase} 匹配波段 {len(bands)} 个")
    return out


def build_report(
    envelope: dict[str, Any],
    *,
    title: str | None = None,
    include_chart: bool = True,
) -> dict[str, Any]:
    """Assemble a structured analysis report from a completed envelope.

    Works on any envelope that carries ``results`` (interpret.phases,
    tools.xrd_match, tools.sem_stats...). Pure function — no I/O, no mutation
    of the envelope. Every section is derived from envelope data.
    """
    if not isinstance(envelope, dict):
        raise make_error("OMM-E104", "build_report 需要输出封套对象", {})
    results = envelope.get("results") or {}
    if not isinstance(results, dict):
        raise make_error("OMM-E104", "results 必须是对象", {})

    winner = results.get("fusion", {}).get("winner") if isinstance(results.get("fusion"), dict) else None
    report = {
        "title": title or "MICP 矿物相解释报告",
        "generated_from": {
            "skill": envelope.get("skill"),
            "skill_version": envelope.get("skill_version"),
            "task_id": envelope.get("task_id"),
            "project_id": envelope.get("project_id"),
            "status": envelope.get("status"),
        },
        "conclusion": {
            "winner_phase": winner.get("phase") if winner else None,
            "winner_confidence": winner.get("confidence") if winner else None,
            "winner_score": winner.get("score") if winner else None,
            "summary": envelope.get("summary"),
        },
        "evidence_summary": _evidence_summary(results),
        "uncertainty": list(envelope.get("uncertainty") or []),
        "risks": [r.get("statement") for r in (envelope.get("risks") or [])],
        "requested_next_skills": [
            s.get("skill") if isinstance(s, dict) else s
            for s in (envelope.get("requested_next_skills") or [])
        ],
        "artifacts": list(envelope.get("artifacts") or []),
    }
    if include_chart:
        xrd = results.get("xrd")
        if isinstance(xrd, list):
            report["xrd_chart_ascii"] = xrd_ascii_chart(xrd)
    return report


def render_text(report: dict[str, Any]) -> str:
    """Render a report object as deterministic plain text (stdout-friendly)."""
    lines: list[str] = []
    lines.append(f"= {report.get('title')} =")
    gen = report.get("generated_from") or {}
    lines.append(f"skill={gen.get('skill')} v{gen.get('skill_version')} task={gen.get('task_id')} project={gen.get('project_id')} status={gen.get('status')}")
    conc = report.get("conclusion") or {}
    if conc.get("winner_phase"):
        lines.append(f"主导相: {conc.get('winner_phase')} ({conc.get('winner_confidence')}, score {conc.get('winner_score')})")
    else:
        lines.append("主导相: 未确定(PARTIAL)")
    lines.append(f"summary: {conc.get('summary')}")
    if report.get("evidence_summary"):
        lines.append("证据摘要:")
        for e in report["evidence_summary"]:
            lines.append(f"  - {e}")
    chart = report.get("xrd_chart_ascii")
    if chart:
        lines.append("")
        lines.append(chart)
    if report.get("uncertainty"):
        lines.append("不确定性:")
        for u in report["uncertainty"]:
            lines.append(f"  - {u}")
    if report.get("risks"):
        lines.append("风险:")
        for r in report["risks"]:
            lines.append(f"  - {r}")
    if report.get("requested_next_skills"):
        lines.append(f"建议下一步技能: {', '.join(report['requested_next_skills'])}")
    return "\n".join(lines)
