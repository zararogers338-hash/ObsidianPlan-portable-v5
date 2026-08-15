"""Counterexample generator (对抗用例生成器).

Constructs the strongest attack scenario against a claim, plus alternative
explanations that fit the same evidence. Deterministic templates selected by
claim type and domain; the result is a structured counterexample that a human
or downstream reviewer can prosecute further.

Output is HYPOTHESIS-tagged by default: it is an attack scenario, not an
observation.
"""

from __future__ import annotations

from typing import Any

from common import ToolError, emit_progress
from errors import OrtErrorCode, OrtError

# claim type -> attack template. {C} is substituted with the claim summary.
_TEMPLATES: dict[str, str] = {
    "conclusion": (
        "攻击：{C}。在证据集未排除 {alt} 的情况下，结论直接成立？构造一个满足同一证据集、"
        "但得出相反结论的最小情景，并检查该情景是否被原始分析排除。"
    ),
    "claim": (
        "攻击：{C}。该主张最脆弱的环节是 {weak}。给出一个能同时解释观测证据的替代机制，"
        "使得原始主张不再被观测唯一支持。"
    ),
    "evidence": (
        "攻击：{C}。该证据的采样/测量过程是否存在系统偏差？若换一种测量方式（直接 vs 间接、"
        "不同仪器、不同取样位置），结论是否仍成立？"
    ),
    "model": (
        "攻击：{C}。该模型最可能的失效模式是参数不识别、边界条件缺失或尺度外推。"
        "在验证域之外构造一个输入，使模型预测与真实行为显著背离。"
    ),
    "experiment": (
        "攻击：{C}。实验设计中最可能的混淆是缺乏对照、伪重复或非随机化。"
        "构造一个能由非处理因素（批次、位置、时间漂移）产生的同样观测。"
    ),
    "analysis": (
        "攻击：{C}。该分析的统计结构最可能被选择性报告、p 值滥用或效应量被高估侵蚀。"
        "若用正确的独立样本量重算，结论是否仍显著？"
    ),
    "lca": (
        "攻击：{C}。LCA 最可能的攻击面是功能单元、系统边界或分配方法的选择性。"
        "换一种合理的系统边界，结论是否反转？"
    ),
    "decision": (
        "攻击：{C}。该决策的阻断项是否全部关闭？构造一个未关闭阻断项的现实场景，"
        "说明放行后的失败模式。"
    ),
    "code": (
        "攻击：{C}。代码最可能的缺陷是单位换算、边界条件硬编码、或输入校验缺失。"
        "构造一个能触发错误路径的输入。"
    ),
    "other": (
        "攻击：{C}。对这条主张，最强反例是：一个能使当前证据与结论不再自洽的最小变动。"
    ),
}

_ALTERNATIVES: dict[str, list[str]] = {
    "experiment": [
        "观测差异由批次效应而非处理引起（伪重复/非随机化）",
        "测量点间差异由位置/深度梯度而非处理引起",
        "观测由仪器漂移或校准错误产生",
    ],
    "evidence": [
        "间接测量与真实量存在系统偏差（如 OD600 vs 活菌数）",
        "采样位置选择引入空间偏差",
        "重复测量被当作独立样本放大样本量",
    ],
    "analysis": [
        "p 值显著但效应量可忽略（高 n 放大）",
        "选择性报告显著结果，null 结果被隐藏",
        "同一样本多次检验未做多重比较校正",
    ],
    "model": [
        "校准与验证使用同一数据（过拟合）",
        "缺失的边界条件在特定工况下主导行为",
        "尺度外推未验证（小柱→现场）",
    ],
    "default": [
        "存在未检查的混杂变量",
        "测量误差方向性偏差",
        "样本代表性不足",
    ],
}


def _generate(target: dict[str, Any]) -> dict[str, Any]:
    t_id = str(target.get("id", "?"))
    t_type = str(target.get("type", "other"))
    summary = str(target.get("summary", "该主张")).strip()
    claimed_label = target.get("epistemic_label")

    template = _TEMPLATES.get(t_type, _TEMPLATES["other"])
    weak = {
        "conclusion": "证据链末端链接的强度",
        "claim": "统计单位（伪重复）或量纲",
        "evidence": "测量与真值之间的映射",
        "model": "边界条件与参数可识别性",
        "experiment": "对照与随机化",
        "analysis": "效应量/置信区间/独立样本量",
        "lca": "功能单元与系统边界",
        "decision": "未关闭的阻断项",
        "code": "单位与边界条件",
        "other": "支持证据的完备性",
    }.get(t_type, "支持证据的完备性")

    attack = template.format(C=summary[:1200], alt=weak)

    alts = _ALTERNATIVES.get(t_type, _ALTERNATIVES["default"])
    alternative_explanations = [{
        "explanation": a,
        "fits_evidence": True,
        "epistemic_tag": "HYPOTHESIS",
    } for a in alts]

    escalation = None
    if claimed_label and claimed_label in ("INFERRED", "HYPOTHESIS", "RECOMMENDATION"):
        escalation = (
            f"该主张自标 {claimed_label}，若被用于支撑部署/升级决策，属于认识论越级"
            "（BLOCK-10）；反例优先指向其证据等级是否足以支撑所声称的用途。"
        )

    return {
        "target_id": t_id,
        "type": t_type,
        "attack": attack,
        "consequence": (
            f"若 {summary[:80]} 在真实场景中遭遇上述攻击情景，结论将被推翻或需降级；"
            "原分析未排除此情景时，不能放行升级/部署。"
        ),
        "alternative_explanations": alternative_explanations,
        "epistemic_tag": "HYPOTHESIS",
        "note": escalation,
    }


def main(payload: dict[str, Any]) -> dict[str, Any]:
    emit_progress("counterexamp: generating strongest counterexamples")
    targets = payload.get("targets")
    if not targets:
        raise OrtError(OrtErrorCode.INPUT_SCHEMA_VIOLATION,
                       "counterexamp: targets array is required",
                       detail={"how_to_fix": "attach the claims to attack"})
    generated = [_generate(t) for t in targets]
    return {
        "counterexamples": generated,
        "count": len(generated),
        "note": "all counterexamples are HYPOTHESIS-tagged attack scenarios, not observations",
    }


if __name__ == "__main__":
    from common import read_stdin_envelope, run_tool
    run_tool("counterexamp", lambda: main(read_stdin_envelope()))
