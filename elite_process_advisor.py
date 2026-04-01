from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:  # noqa: BLE001
        return default


def load_action_rules(config_path: Path) -> dict[str, Any]:
    raw = json.loads(config_path.read_text(encoding="utf-8-sig"))
    if not isinstance(raw, dict):
        raise ValueError("action rules config must be a JSON object")
    rules = raw.get("action_rules", [])
    if not isinstance(rules, list):
        raise ValueError("action_rules must be a list")
    return raw


def _safe_eval(expr: str, variables: dict[str, float]) -> bool:
    allowed_nodes = (
        ast.Expression,
        ast.BoolOp,
        ast.BinOp,
        ast.UnaryOp,
        ast.Compare,
        ast.Name,
        ast.Load,
        ast.Constant,
        ast.Call,
        ast.And,
        ast.Or,
        ast.Not,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.Mod,
        ast.Pow,
        ast.USub,
        ast.UAdd,
        ast.Lt,
        ast.LtE,
        ast.Gt,
        ast.GtE,
        ast.Eq,
        ast.NotEq,
    )
    allowed_funcs = {
        "abs": abs,
        "min": min,
        "max": max,
    }
    tree = ast.parse(expr, mode="eval")
    for node in ast.walk(tree):
        if not isinstance(node, allowed_nodes):
            raise ValueError(f"Unsupported expression node: {type(node).__name__}")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in allowed_funcs:
                raise ValueError("Only abs/min/max calls are allowed in conditions")
        if isinstance(node, ast.Name):
            if node.id not in variables and node.id not in allowed_funcs:
                raise ValueError(f"Unknown variable in condition: {node.id}")
    value = eval(compile(tree, "<condition>", "eval"), {"__builtins__": {}}, {**allowed_funcs, **variables})  # noqa: S307
    return bool(value)


def _extract_metric_context(report: dict[str, Any]) -> dict[str, float]:
    result = report.get("result", {})
    summary = result.get("summary", {})
    confidence = result.get("confidence", {})
    profile = report.get("profile", {})
    targets = profile.get("targets_used", profile.get("targets", {}))

    avg_de = _to_float(summary.get("avg_delta_e00", summary.get("median_avg_delta_e00")), 0.0)
    p95_de = _to_float(summary.get("p95_delta_e00", summary.get("median_p95_delta_e00")), 0.0)
    max_de = _to_float(summary.get("max_delta_e00", summary.get("median_max_delta_e00")), 0.0)
    d_l = _to_float(summary.get("dL", summary.get("median_dL")), 0.0)
    d_c = _to_float(summary.get("dC", summary.get("median_dC")), 0.0)
    d_h = _to_float(summary.get("dH_deg", summary.get("median_dH_deg")), 0.0)
    conf = _to_float(confidence.get("overall", confidence.get("median")), 0.0)
    pass_rate = _to_float(summary.get("single_pass_rate"), 1.0)

    t_avg = _to_float(targets.get("avg_delta_e00"), 1.0)
    t_p95 = _to_float(targets.get("p95_delta_e00"), 1.0)
    t_max = _to_float(targets.get("max_delta_e00"), 1.0)

    return {
        "avg_delta_e00": avg_de,
        "p95_delta_e00": p95_de,
        "max_delta_e00": max_de,
        "dL": d_l,
        "dC": d_c,
        "dH_deg": d_h,
        "confidence": conf,
        "single_pass_rate": pass_rate,
        "target_avg_delta_e00": max(t_avg, 1e-6),
        "target_p95_delta_e00": max(t_p95, 1e-6),
        "target_max_delta_e00": max(t_max, 1e-6),
        "median_dL": d_l,
        "median_dC": d_c,
        "median_dH_deg": d_h,
    }


def _risk_from_context(ctx: dict[str, float]) -> tuple[float, str]:
    ratio_avg = ctx["avg_delta_e00"] / ctx["target_avg_delta_e00"]
    ratio_p95 = ctx["p95_delta_e00"] / ctx["target_p95_delta_e00"]
    ratio_max = ctx["max_delta_e00"] / ctx["target_max_delta_e00"]
    conf_penalty = max(0.0, 1.0 - ctx["confidence"])
    pass_rate_penalty = max(0.0, 1.0 - ctx["single_pass_rate"])
    risk_score = (
        0.34 * ratio_avg
        + 0.30 * ratio_p95
        + 0.20 * ratio_max
        + 0.10 * conf_penalty
        + 0.06 * pass_rate_penalty
    )
    if risk_score >= 1.60:
        level = "critical"
    elif risk_score >= 1.20:
        level = "high"
    elif risk_score >= 0.90:
        level = "medium"
    else:
        level = "low"
    return float(risk_score), level


def build_process_advice(report: dict[str, Any], config: dict[str, Any], config_path: Path) -> dict[str, Any]:
    ctx = _extract_metric_context(report)
    risk_score, risk_level = _risk_from_context(ctx)

    rules = config.get("action_rules", [])
    matched_rules: list[dict[str, Any]] = []
    meanings: list[str] = []
    actions: list[str] = []

    for idx, item in enumerate(rules):
        if not isinstance(item, dict):
            continue
        cond = str(item.get("condition", "")).strip()
        if not cond:
            continue
        try:
            hit = _safe_eval(cond, ctx)
        except Exception as exc:  # noqa: BLE001
            matched_rules.append(
                {
                    "index": idx,
                    "condition": cond,
                    "matched": False,
                    "error": str(exc),
                }
            )
            continue

        if not hit:
            continue

        meaning = str(item.get("meaning", "")).strip()
        severity = str(item.get("severity", "")).strip().lower() or None
        act = item.get("actions", [])
        if not isinstance(act, list):
            act = []

        matched_rules.append(
            {
                "index": idx,
                "condition": cond,
                "matched": True,
                "meaning": meaning,
                "severity": severity,
                "actions": [str(x) for x in act],
            }
        )
        if meaning and meaning not in meanings:
            meanings.append(meaning)
        for a in act:
            s = str(a).strip()
            if s and s not in actions:
                actions.append(s)

    if risk_level in ("high", "critical") and "建议先小步调参并复测，再批量放行。" not in actions:
        actions.append("建议先小步调参并复测，再批量放行。")

    return {
        "enabled": True,
        "config_path": str(config_path),
        "risk_score": risk_score,
        "risk_level": risk_level,
        "matched_rule_count": len([r for r in matched_rules if r.get("matched")]),
        "metric_context": ctx,
        "matched_rules": matched_rules,
        "suggested_meanings": meanings,
        "suggested_actions": actions,
    }


def attach_process_advice(report: dict[str, Any], config_path: Path | None) -> dict[str, Any]:
    if config_path is None:
        advice = {"enabled": False, "reason": "config_not_provided"}
        report["process_advice"] = advice
        return advice
    if not config_path.exists():
        advice = {"enabled": False, "reason": f"config_not_found: {config_path}"}
        report["process_advice"] = advice
        return advice
    try:
        config = load_action_rules(config_path)
        advice = build_process_advice(report, config, config_path)
    except Exception as exc:  # noqa: BLE001
        advice = {"enabled": False, "reason": f"config_error: {exc}"}
    report["process_advice"] = advice
    return advice
