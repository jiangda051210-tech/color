from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from elite_decision_center import apply_policy_patch, load_decision_policy
from elite_quality_history import list_outcomes, list_recent_runs


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:  # noqa: BLE001
        return default


def _clamp(value: float, lo: float, hi: float) -> float:
    return float(max(lo, min(hi, value)))


def _estimate_targets_from_runs(runs: list[dict[str, Any]]) -> tuple[float, float]:
    avg_vals = np.array([_to_float(r.get("avg_de"), np.nan) for r in runs], dtype=np.float64)
    p95_vals = np.array([_to_float(r.get("p95_de"), np.nan) for r in runs], dtype=np.float64)
    pass_mask = np.array([1.0 if bool(r.get("pass")) else 0.0 for r in runs], dtype=np.float64) > 0.5

    valid_avg = avg_vals[~np.isnan(avg_vals)]
    valid_p95 = p95_vals[~np.isnan(p95_vals)]
    if valid_avg.size == 0 or valid_p95.size == 0:
        return 1.0, 1.8

    pass_avg = valid_avg[:0]
    pass_p95 = valid_p95[:0]
    if pass_mask.size == avg_vals.size:
        pass_avg = avg_vals[pass_mask & ~np.isnan(avg_vals)]
    if pass_mask.size == p95_vals.size:
        pass_p95 = p95_vals[pass_mask & ~np.isnan(p95_vals)]

    if pass_avg.size >= 4:
        t_avg = float(np.nanmean(pass_avg) * 1.05)
    else:
        t_avg = float(np.nanpercentile(valid_avg, 35))
    if pass_p95.size >= 4:
        t_p95 = float(np.nanmean(pass_p95) * 1.08)
    else:
        t_p95 = float(np.nanpercentile(valid_p95, 35))

    return max(0.2, t_avg), max(0.4, t_p95)


def _make_feature_rows(runs: list[dict[str, Any]], target_avg: float, target_p95: float) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in runs:
        run_id = r.get("id")
        if run_id is None:
            continue
        avg_de = _to_float(r.get("avg_de"), np.nan)
        p95_de = _to_float(r.get("p95_de"), np.nan)
        conf = _to_float(r.get("confidence"), np.nan)
        if np.isnan(avg_de) or np.isnan(p95_de):
            continue
        if np.isnan(conf):
            conf = 0.5
        avg_ratio = avg_de / max(1e-6, target_avg)
        p95_ratio = p95_de / max(1e-6, target_p95)
        base_risk = r.get("decision_risk")
        if base_risk is None:
            base_risk = _clamp(
                0.52 * max(0.0, avg_ratio - 1.0)
                + 0.28 * max(0.0, p95_ratio - 1.0)
                + 0.20 * max(0.0, 1.0 - conf),
                0.0,
                1.0,
            )
        row = {
            "id": int(run_id),
            "pass": bool(r.get("pass", False)),
            "confidence": float(conf),
            "avg_ratio": float(avg_ratio),
            "p95_ratio": float(p95_ratio),
            "risk": _clamp(_to_float(base_risk, 0.5), 0.0, 1.0),
            "decision_code": str(r.get("decision_code") or ""),
        }
        out.append(row)
    return out


def _simulate_decision(row: dict[str, Any], policy: dict[str, Any]) -> str:
    p = policy.get("decision_policy", {})
    auto_conf = _to_float(p.get("auto_release_min_confidence"), 0.82)
    manual_conf = _to_float(p.get("manual_review_min_confidence"), 0.68)
    recapture_conf = _to_float(p.get("recapture_max_confidence"), 0.62)
    max_avg_ratio = _to_float(p.get("max_avg_ratio_for_auto_release"), 1.0)
    max_p95_ratio = _to_float(p.get("max_p95_ratio_for_auto_release"), 1.0)

    confidence = _to_float(row.get("confidence"), 0.0)
    risk = _to_float(row.get("risk"), 1.0)
    avg_ratio = _to_float(row.get("avg_ratio"), 99.0)
    p95_ratio = _to_float(row.get("p95_ratio"), 99.0)
    passed = bool(row.get("pass", False))

    if risk >= 0.90:
        return "HOLD_AND_ESCALATE"
    if confidence <= recapture_conf:
        return "RECAPTURE_REQUIRED"
    if risk >= 0.75 and not passed:
        return "HOLD_AND_ESCALATE"
    if passed and confidence >= auto_conf and avg_ratio <= max_avg_ratio and p95_ratio <= max_p95_ratio and risk <= 0.70:
        return "AUTO_RELEASE"
    if confidence >= manual_conf:
        return "MANUAL_REVIEW"
    return "RECAPTURE_REQUIRED"


def _calibrate_mitigation_factors(feature_rows: list[dict[str, Any]], outcomes: list[dict[str, Any]]) -> dict[str, float]:
    default = {
        "AUTO_RELEASE": 1.00,
        "MANUAL_REVIEW": 0.35,
        "RECAPTURE_REQUIRED": 0.18,
        "HOLD_AND_ESCALATE": 0.08,
    }
    by_run_id: dict[int, dict[str, Any]] = {}
    for row in outcomes:
        run_id = row.get("run_id")
        if run_id is None:
            continue
        by_run_id[int(run_id)] = row

    buckets: dict[str, list[tuple[float, float]]] = {k: [] for k in default}
    for row in feature_rows:
        outcome = by_run_id.get(int(row["id"]))
        if not outcome:
            continue
        decision = str(row.get("decision_code") or "")
        if decision not in buckets:
            continue
        label = str(outcome.get("outcome") or "")
        severity = _to_float(outcome.get("severity"), 0.0)
        if label in ("complaint_major", "return"):
            bad = 1.0
        elif label in ("complaint_minor", "rework"):
            bad = max(0.35, min(0.7, severity if severity > 0 else 0.45))
        elif label == "accepted":
            bad = 0.0
        else:
            continue
        buckets[decision].append((_to_float(row.get("risk"), 0.5), bad))

    factors: dict[str, float] = {}
    for decision, values in buckets.items():
        if len(values) < 4:
            factors[decision] = default[decision]
            continue
        risk_arr = np.array([v[0] for v in values], dtype=np.float64)
        bad_arr = np.array([v[1] for v in values], dtype=np.float64)
        risk_mean = float(np.mean(risk_arr))
        bad_mean = float(np.mean(bad_arr))
        if risk_mean < 1e-6:
            factors[decision] = default[decision]
            continue
        factor = _clamp(bad_mean / risk_mean, 0.05, 1.50)
        factors[decision] = factor
    return factors


def _candidate_patches() -> list[dict[str, Any]]:
    return [
        {"name": "base", "patch": {}},
        {"name": "quality_guard_plus", "patch": {"decision_policy": {"auto_release_min_confidence_delta": 0.02, "max_avg_ratio_for_auto_release_delta": -0.03, "max_p95_ratio_for_auto_release_delta": -0.03}}},
        {"name": "quality_guard_max", "patch": {"decision_policy": {"auto_release_min_confidence_delta": 0.04, "max_avg_ratio_for_auto_release_delta": -0.05, "max_p95_ratio_for_auto_release_delta": -0.05}}},
        {"name": "throughput_plus", "patch": {"decision_policy": {"auto_release_min_confidence_delta": -0.015, "max_avg_ratio_for_auto_release_delta": 0.02, "max_p95_ratio_for_auto_release_delta": 0.02}}},
        {"name": "balanced_slight_relax", "patch": {"decision_policy": {"auto_release_min_confidence_delta": -0.008, "max_avg_ratio_for_auto_release_delta": 0.01, "max_p95_ratio_for_auto_release_delta": 0.01}}},
    ]


def _evaluate_candidate(
    name: str,
    patch: dict[str, Any],
    base_policy: dict[str, Any],
    rows: list[dict[str, Any]],
    factors: dict[str, float],
) -> dict[str, Any]:
    policy = apply_policy_patch(base_policy, patch)
    p = policy.get("decision_policy", {})
    cost_model = policy.get("cost_model", {})
    manual_cost = _to_float(cost_model.get("manual_review_cost"), 18.0)
    recapture_cost = _to_float(cost_model.get("recapture_cost"), 10.0)
    hold_cost = _to_float(cost_model.get("hold_delay_cost"), 120.0)
    escape_cost = _to_float(cost_model.get("escape_cost"), 350.0)

    counts = {"AUTO_RELEASE": 0, "MANUAL_REVIEW": 0, "RECAPTURE_REQUIRED": 0, "HOLD_AND_ESCALATE": 0}
    total_bad_prob = 0.0
    total_complaint_prob = 0.0
    total_cost = 0.0
    auto_bad_probs: list[float] = []

    for row in rows:
        decision = _simulate_decision(row, p)
        counts[decision] += 1
        risk = _to_float(row.get("risk"), 0.5)
        factor = _to_float(factors.get(decision), 1.0)
        bad_prob = _clamp(risk * factor, 0.0, 1.0)
        complaint_prob = _clamp(bad_prob * 1.45, 0.0, 1.0)
        total_bad_prob += bad_prob
        total_complaint_prob += complaint_prob
        if decision == "AUTO_RELEASE":
            auto_bad_probs.append(bad_prob)

        op_cost = 0.0
        if decision == "MANUAL_REVIEW":
            op_cost += manual_cost
        elif decision == "RECAPTURE_REQUIRED":
            op_cost += recapture_cost
        elif decision == "HOLD_AND_ESCALATE":
            op_cost += hold_cost + manual_cost
        total_cost += op_cost + bad_prob * escape_cost

    n = max(1, len(rows))
    auto_rate = counts["AUTO_RELEASE"] / n
    manual_rate = counts["MANUAL_REVIEW"] / n
    recapture_rate = counts["RECAPTURE_REQUIRED"] / n
    hold_rate = counts["HOLD_AND_ESCALATE"] / n
    escape_rate = total_bad_prob / n
    complaint_rate = total_complaint_prob / n
    auto_escape_rate = float(np.mean(auto_bad_probs)) if auto_bad_probs else 0.0
    cost_per_run = total_cost / n

    throughput_score = _clamp(100.0 * (auto_rate + 0.72 * manual_rate + 0.55 * recapture_rate + 0.28 * (1.0 - hold_rate)), 0.0, 100.0)
    customer_index = _clamp(100.0 - 130.0 * escape_rate - 60.0 * complaint_rate - 12.0 * hold_rate, 0.0, 100.0)
    boss_index = _clamp(0.45 * throughput_score + 0.35 * (100.0 - escape_rate * 100.0) + 0.20 * _clamp(100.0 - (cost_per_run / max(1.0, escape_cost)) * 100.0, 0.0, 100.0), 0.0, 100.0)
    company_index = _clamp(0.44 * customer_index + 0.32 * (100.0 - escape_rate * 100.0) + 0.24 * (100.0 - hold_rate * 100.0), 0.0, 100.0)

    objective = 0.45 * customer_index + 0.30 * boss_index + 0.25 * company_index
    penalty = 0.0
    if escape_rate > 0.03:
        penalty += (escape_rate - 0.03) * 1200.0
    if customer_index < 80:
        penalty += (80 - customer_index) * 1.8
    if hold_rate > 0.20:
        penalty += (hold_rate - 0.20) * 320.0
    final_score = objective - penalty

    return {
        "name": name,
        "policy_patch": patch,
        "suggested_policy": policy,
        "final_score": float(final_score),
        "metrics": {
            "auto_release_rate": auto_rate,
            "manual_review_rate": manual_rate,
            "recapture_rate": recapture_rate,
            "hold_rate": hold_rate,
            "expected_escape_rate": escape_rate,
            "expected_complaint_rate": complaint_rate,
            "expected_auto_release_escape_rate": auto_escape_rate,
            "expected_cost_per_run": cost_per_run,
            "customer_acceptance_index": customer_index,
            "boss_efficiency_index": boss_index,
            "company_governance_index": company_index,
        },
        "constraints": {
            "escape_rate_ok": bool(escape_rate <= 0.03),
            "customer_index_ok": bool(customer_index >= 80),
            "hold_rate_ok": bool(hold_rate <= 0.20),
        },
    }


def _build_pareto_front(candidates: list[dict[str, Any]]) -> list[str]:
    if not candidates:
        return []
    front: list[str] = []
    for i, a in enumerate(candidates):
        am = a.get("metrics", {})
        dominated = False
        for j, b in enumerate(candidates):
            if i == j:
                continue
            bm = b.get("metrics", {})
            better_or_equal = (
                _to_float(bm.get("customer_acceptance_index"), 0.0) >= _to_float(am.get("customer_acceptance_index"), 0.0)
                and _to_float(bm.get("boss_efficiency_index"), 0.0) >= _to_float(am.get("boss_efficiency_index"), 0.0)
                and _to_float(bm.get("company_governance_index"), 0.0) >= _to_float(am.get("company_governance_index"), 0.0)
                and _to_float(bm.get("expected_cost_per_run"), 1e9) <= _to_float(am.get("expected_cost_per_run"), 1e9)
            )
            strictly_better = (
                _to_float(bm.get("customer_acceptance_index"), 0.0) > _to_float(am.get("customer_acceptance_index"), 0.0)
                or _to_float(bm.get("boss_efficiency_index"), 0.0) > _to_float(am.get("boss_efficiency_index"), 0.0)
                or _to_float(bm.get("company_governance_index"), 0.0) > _to_float(am.get("company_governance_index"), 0.0)
                or _to_float(bm.get("expected_cost_per_run"), 1e9) < _to_float(am.get("expected_cost_per_run"), 1e9)
            )
            if better_or_equal and strictly_better:
                dominated = True
                break
        if not dominated:
            front.append(str(a.get("name")))
    return front


def run_policy_lab(
    db_path: Path,
    line_id: str | None = None,
    product_code: str | None = None,
    lot_id: str | None = None,
    window: int = 250,
    policy_config: Path | None = None,
) -> dict[str, Any]:
    runs = list_recent_runs(
        db_path=db_path,
        line_id=line_id,
        product_code=product_code,
        lot_id=lot_id,
        limit=max(30, int(window)),
    )
    if not runs:
        return {"enabled": False, "reason": "no_runs"}

    outcomes = list_outcomes(
        db_path=db_path,
        line_id=line_id,
        product_code=product_code,
        lot_id=lot_id,
        limit=max(50, int(window)),
    )

    base_policy, base_source = load_decision_policy(policy_config)
    target_avg, target_p95 = _estimate_targets_from_runs(runs)
    feature_rows = _make_feature_rows(runs, target_avg, target_p95)
    if len(feature_rows) < 12:
        return {
            "enabled": True,
            "insufficient_data": True,
            "reason": "not_enough_feature_rows",
            "feature_row_count": len(feature_rows),
            "run_count": len(runs),
            "outcome_count": len(outcomes),
            "base_policy_source": base_source,
        }

    factors = _calibrate_mitigation_factors(feature_rows, outcomes)
    candidates = []
    for item in _candidate_patches():
        candidates.append(
            _evaluate_candidate(
                name=str(item["name"]),
                patch=item["patch"],
                base_policy=base_policy,
                rows=feature_rows,
                factors=factors,
            )
        )
    candidates.sort(key=lambda x: _to_float(x.get("final_score"), -1e9), reverse=True)
    pareto_front = _build_pareto_front(candidates)
    recommended = candidates[0] if candidates else None

    return {
        "enabled": True,
        "innovation": "policy_digital_twin_multi_objective",
        "base_policy_source": base_source,
        "run_count": len(runs),
        "outcome_count": len(outcomes),
        "feature_row_count": len(feature_rows),
        "target_estimation": {"avg_target_est": target_avg, "p95_target_est": target_p95},
        "mitigation_factors": factors,
        "pareto_front": pareto_front,
        "recommended": recommended,
        "candidates": candidates,
        "notes": [
            "Policy Lab simulates policy impact before rollout.",
            "It optimizes customer acceptance, business efficiency, and governance simultaneously.",
            "Use recommended policy first on one line as canary deployment.",
        ],
    }
