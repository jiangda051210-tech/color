from __future__ import annotations

import json
import math
from copy import deepcopy
from pathlib import Path
from typing import Any


DEFAULT_POLICY: dict[str, Any] = {
    "decision_policy": {
        "auto_release_min_confidence": 0.82,
        "manual_review_min_confidence": 0.68,
        "recapture_max_confidence": 0.62,
        "max_avg_ratio_for_auto_release": 1.0,
        "max_p95_ratio_for_auto_release": 1.0,
        "hard_stop_flags": [
            "history_avg_outlier_high",
            "history_p95_outlier_high",
            "history_max_outlier_high",
        ],
        "recapture_flags": [
            "low_overall_confidence",
            "lighting_non_uniform",
            "board_low_sharpness",
            "sample_low_sharpness",
            "board_effective_pixels_low",
            "sample_effective_pixels_low",
        ],
        "critical_process_risk_levels": ["high", "critical"],
    },
    "stakeholder_weights": {
        "customer": {"quality": 0.58, "stability": 0.24, "confidence": 0.18},
        "boss": {"throughput": 0.42, "risk": 0.38, "cost": 0.20},
        "company": {"governance": 0.40, "customer_risk": 0.35, "operational_risk": 0.25},
    },
    "cost_model": {
        "manual_review_cost": 18.0,
        "recapture_cost": 10.0,
        "hold_delay_cost": 120.0,
        "escape_cost": 350.0,
    },
}


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:  # noqa: BLE001
        return default


def _clamp(value: float, lo: float, hi: float) -> float:
    return float(max(lo, min(hi, value)))


def _merge_dict(base: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(base)
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge_dict(out[key], value)
        else:
            out[key] = value
    return out


def load_decision_policy(config_path: Path | None) -> tuple[dict[str, Any], str]:
    policy = deepcopy(DEFAULT_POLICY)
    if config_path is None:
        return policy, "builtin_default"
    raw = json.loads(config_path.read_text(encoding="utf-8-sig"))
    if not isinstance(raw, dict):
        raise ValueError("decision policy config must be a JSON object")
    return _merge_dict(policy, raw), str(config_path)


def apply_policy_patch(policy: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(policy)
    if not isinstance(patch, dict):
        return out
    dp = patch.get("decision_policy", {})
    if not isinstance(dp, dict):
        return out
    target = out.setdefault("decision_policy", {})
    if not isinstance(target, dict):
        return out

    for key, value in dp.items():
        if key.endswith("_delta"):
            base_key = key[: -len("_delta")]
            base = _to_float(target.get(base_key), 0.0)
            new_val = base + _to_float(value, 0.0)
            if "confidence" in base_key:
                new_val = _clamp(new_val, 0.3, 0.99)
            elif "ratio" in base_key:
                new_val = _clamp(new_val, 0.7, 1.3)
            target[base_key] = float(new_val)
        else:
            target[key] = value
    return out


def _extract_context(report: dict[str, Any]) -> dict[str, Any]:
    result = report.get("result", {})
    summary = result.get("summary", {})
    confidence_obj = result.get("confidence", {})
    profile = report.get("profile", {})
    targets = profile.get("targets_used", profile.get("targets", {}))
    quality_flags = [str(x) for x in result.get("quality_flags", [])]
    history_flags = [str(x) for x in report.get("history_assessment", {}).get("flags", [])]
    process_advice = report.get("process_advice", {})

    avg_de = _to_float(summary.get("avg_delta_e00", summary.get("median_avg_delta_e00")), 0.0)
    p95_de = _to_float(summary.get("p95_delta_e00", summary.get("median_p95_delta_e00")), 0.0)
    max_de = _to_float(summary.get("max_delta_e00", summary.get("median_max_delta_e00")), 0.0)
    confidence = _to_float(confidence_obj.get("overall", confidence_obj.get("median")), 0.0)

    t_avg = max(1e-6, _to_float(targets.get("avg_delta_e00"), 1.0))
    t_p95 = max(1e-6, _to_float(targets.get("p95_delta_e00"), 1.0))
    t_max = max(1e-6, _to_float(targets.get("max_delta_e00"), 1.0))

    avg_ratio = avg_de / t_avg
    p95_ratio = p95_de / t_p95
    max_ratio = max_de / t_max

    process_risk = str(process_advice.get("risk_level", "unknown")) if isinstance(process_advice, dict) else "unknown"
    process_actions = process_advice.get("suggested_actions", []) if isinstance(process_advice, dict) else []
    process_actions = [str(x) for x in process_actions]

    return {
        "mode": str(report.get("mode", "unknown")),
        "pass": bool(result.get("pass", False)),
        "avg_de": avg_de,
        "p95_de": p95_de,
        "max_de": max_de,
        "confidence": confidence,
        "target_avg": t_avg,
        "target_p95": t_p95,
        "target_max": t_max,
        "avg_ratio": avg_ratio,
        "p95_ratio": p95_ratio,
        "max_ratio": max_ratio,
        "quality_flags": quality_flags,
        "history_flags": history_flags,
        "all_flags": quality_flags + [f for f in history_flags if f not in quality_flags],
        "process_risk": process_risk,
        "process_actions": process_actions,
    }


def _risk_probability(ctx: dict[str, Any]) -> float:
    ratio_risk = (
        0.45 * max(0.0, ctx["avg_ratio"] - 1.0)
        + 0.35 * max(0.0, ctx["p95_ratio"] - 1.0)
        + 0.20 * max(0.0, ctx["max_ratio"] - 1.0)
    )
    confidence_risk = max(0.0, 1.0 - ctx["confidence"])
    flag_risk = min(1.0, len(ctx["all_flags"]) * 0.08)
    return _clamp(0.52 * ratio_risk + 0.33 * confidence_risk + 0.15 * flag_risk, 0.0, 1.0)


def _decide(ctx: dict[str, Any], policy: dict[str, Any]) -> tuple[str, list[str]]:
    p = policy["decision_policy"]
    reasons: list[str] = []
    flags = set(ctx["all_flags"])

    hard_stop_flags = set(str(x) for x in p.get("hard_stop_flags", []))
    recapture_flags = set(str(x) for x in p.get("recapture_flags", []))
    critical_levels = set(str(x) for x in p.get("critical_process_risk_levels", []))

    hit_hard = flags & hard_stop_flags
    if hit_hard:
        reasons.append("hard_stop_flags_hit")
        reasons.append(f"triggered flags: {', '.join(sorted(hit_hard))}")
        return "HOLD_AND_ESCALATE", reasons

    recap_conf = _to_float(p.get("recapture_max_confidence"), 0.62)
    if ctx["confidence"] <= recap_conf:
        reasons.append("confidence_too_low_for_judgement")
        reasons.append(f"confidence={ctx['confidence']:.3f} <= threshold={recap_conf:.3f}")
        return "RECAPTURE_REQUIRED", reasons

    hit_recap = flags & recapture_flags
    if hit_recap:
        reasons.append("capture_quality_insufficient")
        reasons.append(f"triggered flags: {', '.join(sorted(hit_recap))}")
        return "RECAPTURE_REQUIRED", reasons

    if ctx["process_risk"] in critical_levels and not ctx["pass"]:
        reasons.append("process_risk_critical_and_quality_fail")
        reasons.append(f"process_risk={ctx['process_risk']}, pass={ctx['pass']}")
        return "HOLD_AND_ESCALATE", reasons

    auto_conf = _to_float(p.get("auto_release_min_confidence"), 0.82)
    max_avg_ratio = _to_float(p.get("max_avg_ratio_for_auto_release"), 1.0)
    max_p95_ratio = _to_float(p.get("max_p95_ratio_for_auto_release"), 1.0)
    if (
        ctx["pass"]
        and ctx["confidence"] >= auto_conf
        and ctx["avg_ratio"] <= max_avg_ratio
        and ctx["p95_ratio"] <= max_p95_ratio
        and ctx["process_risk"] not in critical_levels
    ):
        reasons.append("all_auto_release_gates_passed")
        reasons.append(
            f"confidence={ctx['confidence']:.3f}>={auto_conf:.3f}, "
            f"avg_ratio={ctx['avg_ratio']:.3f}<={max_avg_ratio:.3f}, "
            f"p95_ratio={ctx['p95_ratio']:.3f}<={max_p95_ratio:.3f}"
        )
        return "AUTO_RELEASE", reasons

    manual_conf = _to_float(p.get("manual_review_min_confidence"), 0.68)
    if ctx["confidence"] >= manual_conf:
        reasons.append("requires_human_confirmation")
        gate_misses: list[str] = []
        if not ctx["pass"]:
            gate_misses.append("pass=False")
        if ctx["avg_ratio"] > max_avg_ratio:
            gate_misses.append(f"avg_ratio={ctx['avg_ratio']:.3f}>{max_avg_ratio:.3f}")
        if ctx["p95_ratio"] > max_p95_ratio:
            gate_misses.append(f"p95_ratio={ctx['p95_ratio']:.3f}>{max_p95_ratio:.3f}")
        if gate_misses:
            reasons.append(f"auto-release blocked by: {'; '.join(gate_misses)}")
        return "MANUAL_REVIEW", reasons

    reasons.append("confidence_borderline_retake_safer")
    reasons.append(f"confidence={ctx['confidence']:.3f} < manual_threshold={manual_conf:.3f}")
    return "RECAPTURE_REQUIRED", reasons


def _estimate_cost(
    decision_code: str,
    risk_probability: float,
    policy: dict[str, Any],
    ctx: dict[str, Any] | None = None,
) -> float:
    c = policy["cost_model"]
    # Per-product overrides: cost_model may contain product-specific costs keyed by
    # product_code (e.g. "per_product": {"ABC": {"escape_cost": 500}}).
    product_code = (ctx or {}).get("product_code")
    per_product = c.get("per_product", {})
    if isinstance(per_product, dict) and product_code and product_code in per_product:
        pc = per_product[product_code]
        manual = _to_float(pc.get("manual_review_cost", c.get("manual_review_cost")), 18.0)
        recapture = _to_float(pc.get("recapture_cost", c.get("recapture_cost")), 10.0)
        hold = _to_float(pc.get("hold_delay_cost", c.get("hold_delay_cost")), 120.0)
        escape = _to_float(pc.get("escape_cost", c.get("escape_cost")), 350.0)
    else:
        manual = _to_float(c.get("manual_review_cost"), 18.0)
        recapture = _to_float(c.get("recapture_cost"), 10.0)
        hold = _to_float(c.get("hold_delay_cost"), 120.0)
        escape = _to_float(c.get("escape_cost"), 350.0)

    if decision_code == "AUTO_RELEASE":
        return float(risk_probability * escape)
    if decision_code == "MANUAL_REVIEW":
        return float(manual + risk_probability * escape * 0.30)
    if decision_code == "RECAPTURE_REQUIRED":
        return float(recapture + risk_probability * escape * 0.15)
    return float(hold + manual + risk_probability * escape * 0.08)


def _stakeholder_scores(
    ctx: dict[str, Any],
    decision_code: str,
    risk_probability: float,
    estimated_cost: float,
    policy: dict[str, Any],
) -> dict[str, float]:
    w = policy["stakeholder_weights"]
    max_ref_cost = max(1.0, _to_float(policy["cost_model"].get("escape_cost"), 350.0))

    # --- sub-scores are all on 0-100 scale ---
    quality_score = _clamp(
        100.0
        - 45.0 * max(0.0, ctx["avg_ratio"] - 1.0)
        - 35.0 * max(0.0, ctx["p95_ratio"] - 1.0)
        - 20.0 * max(0.0, ctx["max_ratio"] - 1.0),
        0.0,
        100.0,
    )
    stability_score = _clamp(100.0 - len(ctx["all_flags"]) * 8.5, 0.0, 100.0)
    confidence_score = _clamp(ctx["confidence"] * 100.0, 0.0, 100.0)

    # Customer: weighted sum of 0-100 sub-scores (weights sum to 1) -> already 0-100
    customer_raw = (
        w["customer"]["quality"] * quality_score
        + w["customer"]["stability"] * stability_score
        + w["customer"]["confidence"] * confidence_score
    )
    cust_wsum = sum(w["customer"].values())
    customer_score = _clamp(customer_raw / max(cust_wsum, 1e-9) * 1.0, 0.0, 100.0) if cust_wsum != 1.0 else _clamp(customer_raw, 0.0, 100.0)

    throughput_map = {
        "AUTO_RELEASE": 98.0,
        "MANUAL_REVIEW": 72.0,
        "RECAPTURE_REQUIRED": 60.0,
        "HOLD_AND_ESCALATE": 35.0,
    }
    throughput_score = throughput_map.get(decision_code, 60.0)
    risk_score = _clamp(100.0 - risk_probability * 100.0, 0.0, 100.0)
    cost_score = _clamp(100.0 - (estimated_cost / max_ref_cost) * 100.0, 0.0, 100.0)

    # Boss: normalize by weight sum for comparable scale
    boss_raw = (
        w["boss"]["throughput"] * throughput_score
        + w["boss"]["risk"] * risk_score
        + w["boss"]["cost"] * cost_score
    )
    boss_wsum = sum(w["boss"].values())
    boss_score = _clamp(boss_raw / max(boss_wsum, 1e-9) * 1.0, 0.0, 100.0) if boss_wsum != 1.0 else _clamp(boss_raw, 0.0, 100.0)

    governance_score = 100.0
    if not ctx.get("mode"):
        governance_score -= 25.0
    if not ctx["process_actions"]:
        governance_score -= 8.0
    if len(ctx["all_flags"]) > 0:
        governance_score -= min(30.0, len(ctx["all_flags"]) * 5.0)
    governance_score = _clamp(governance_score, 0.0, 100.0)

    # Company: normalize by weight sum for comparable scale
    company_raw = (
        w["company"]["governance"] * governance_score
        + w["company"]["customer_risk"] * customer_score
        + w["company"]["operational_risk"] * risk_score
    )
    comp_wsum = sum(w["company"].values())
    company_score = _clamp(company_raw / max(comp_wsum, 1e-9) * 1.0, 0.0, 100.0) if comp_wsum != 1.0 else _clamp(company_raw, 0.0, 100.0)

    return {
        "customer_score": customer_score,
        "boss_score": boss_score,
        "company_score": company_score,
    }


def _messages(decision_code: str, scores: dict[str, float]) -> dict[str, str]:
    customer = (
        "颜色一致性稳定，可按客户标准交付。"
        if scores["customer_score"] >= 82
        else "颜色风险偏高，建议先复测或人工复核后再对客户承诺。"
    )
    boss = (
        "当前策略兼顾放行效率与风险，可控推进产出。"
        if decision_code == "AUTO_RELEASE"
        else "建议优先控风险，避免返工与客诉放大总成本。"
    )
    company = (
        "决策链路可追溯，适合纳入标准作业流程。"
        if scores["company_score"] >= 78
        else "治理分偏低，建议补齐复拍/复核动作并留痕。"
    )
    return {"customer": customer, "boss": boss, "company": company}


def _decision_confidence(scores: dict[str, float], decision_code: str) -> dict[str, Any]:
    """Compute decision confidence from agreement between stakeholder perspectives.

    If all three scores are on the same side of a threshold (all high or all low),
    confidence is high.  Disagreement lowers confidence.
    """
    vals = [scores["customer_score"], scores["boss_score"], scores["company_score"]]
    mean_s = sum(vals) / 3.0
    spread = max(vals) - min(vals)
    # Normalise spread: 0 spread -> 1.0 agreement, 100 spread -> 0.0
    agreement = _clamp(1.0 - spread / 100.0, 0.0, 1.0)

    # Severity-adjusted: riskier decisions need tighter agreement
    severity_weight = {
        "AUTO_RELEASE": 0.85,
        "MANUAL_REVIEW": 0.75,
        "RECAPTURE_REQUIRED": 0.65,
        "HOLD_AND_ESCALATE": 0.55,
    }.get(decision_code, 0.75)
    confidence = _clamp(agreement * 0.7 + (mean_s / 100.0) * 0.3 * severity_weight + (1 - severity_weight) * 0.3, 0.0, 1.0)

    if agreement >= 0.85:
        label = "high"
    elif agreement >= 0.60:
        label = "medium"
    else:
        label = "low"

    return {
        "value": round(confidence, 4),
        "label": label,
        "agreement": round(agreement, 4),
        "score_spread": round(spread, 2),
    }


# Priority ordering: lower number = more urgent.  HOLD(P0) > RECAPTURE(P1) > MANUAL(P2) > AUTO(P3)
_PRIORITY_MAP: dict[str, str] = {
    "HOLD_AND_ESCALATE": "P0",
    "RECAPTURE_REQUIRED": "P1",
    "MANUAL_REVIEW": "P2",
    "AUTO_RELEASE": "P3",
}
_PRIORITY_ORDER: dict[str, int] = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


def build_decision_center(report: dict[str, Any], policy: dict[str, Any], policy_source: str) -> dict[str, Any]:
    ctx = _extract_context(report)
    decision_code, reasons = _decide(ctx, policy)
    risk_probability = _risk_probability(ctx)
    estimated_cost = _estimate_cost(decision_code, risk_probability, policy, ctx)
    scores = _stakeholder_scores(ctx, decision_code, risk_probability, estimated_cost, policy)
    msgs = _messages(decision_code, scores)
    decision_conf = _decision_confidence(scores, decision_code)

    actions = ctx["process_actions"][:]
    if not actions:
        actions = ["建议先采集 2-3 张补充图像，再执行人工复核。"]

    priority = _PRIORITY_MAP.get(decision_code, "P2")

    # Validate priority consistency: if risk is very high but decision is lenient,
    # escalate the priority (never downgrade).
    if risk_probability > 0.6 and _PRIORITY_ORDER.get(priority, 2) > _PRIORITY_ORDER["P1"]:
        priority = "P1"
        reasons.append("priority_escalated_due_to_high_risk")

    return {
        "enabled": True,
        "policy_source": policy_source,
        "decision_code": decision_code,
        "priority": priority,
        "decision_reasons": reasons,
        "decision_confidence": decision_conf,
        "risk_probability": risk_probability,
        "estimated_cost": estimated_cost,
        "stakeholder_scores": scores,
        "recommended_actions_top3": actions[:3],
        "executive_messages": msgs,
        "context_snapshot": {
            "avg_ratio": ctx["avg_ratio"],
            "p95_ratio": ctx["p95_ratio"],
            "max_ratio": ctx["max_ratio"],
            "confidence": ctx["confidence"],
            "flags": ctx["all_flags"],
            "process_risk": ctx["process_risk"],
        },
    }


def attach_decision_center(
    report: dict[str, Any],
    policy_path: Path | None,
    enabled: bool = True,
    policy_override: dict[str, Any] | None = None,
    policy_source_override: str | None = None,
) -> dict[str, Any]:
    if not enabled:
        center = {"enabled": False, "reason": "disabled_by_flag"}
        report["decision_center"] = center
        return center
    try:
        if policy_override is not None:
            policy = policy_override
            source = policy_source_override or "policy_override"
        else:
            policy, source = load_decision_policy(policy_path)
        center = build_decision_center(report, policy, source)
    except Exception as exc:  # noqa: BLE001
        center = {"enabled": False, "reason": f"decision_center_error: {exc}"}
    report["decision_center"] = center
    return center
