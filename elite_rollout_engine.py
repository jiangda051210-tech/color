from __future__ import annotations

import math
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


def _estimate_targets(runs: list[dict[str, Any]]) -> tuple[float, float]:
    avg = np.array([_to_float(r.get("avg_de"), np.nan) for r in runs], dtype=np.float64)
    p95 = np.array([_to_float(r.get("p95_de"), np.nan) for r in runs], dtype=np.float64)
    passed = np.array([1.0 if bool(r.get("pass")) else 0.0 for r in runs], dtype=np.float64) > 0.5
    valid_avg = avg[~np.isnan(avg)]
    valid_p95 = p95[~np.isnan(p95)]
    if valid_avg.size == 0 or valid_p95.size == 0:
        return 1.0, 1.8

    pass_avg = avg[passed & ~np.isnan(avg)] if passed.size == avg.size else np.array([], dtype=np.float64)
    pass_p95 = p95[passed & ~np.isnan(p95)] if passed.size == p95.size else np.array([], dtype=np.float64)
    if pass_avg.size >= 4:
        t_avg = float(np.nanmean(pass_avg) * 1.05)
    else:
        t_avg = float(np.nanpercentile(valid_avg, 35))
    if pass_p95.size >= 4:
        t_p95 = float(np.nanmean(pass_p95) * 1.08)
    else:
        t_p95 = float(np.nanpercentile(valid_p95, 35))
    return max(0.2, t_avg), max(0.4, t_p95)


def _build_rows(runs: list[dict[str, Any]], target_avg: float, target_p95: float) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for r in runs:
        avg_de = _to_float(r.get("avg_de"), np.nan)
        p95_de = _to_float(r.get("p95_de"), np.nan)
        conf = _to_float(r.get("confidence"), np.nan)
        if np.isnan(avg_de) or np.isnan(p95_de):
            continue
        if np.isnan(conf):
            conf = 0.5
        avg_ratio = avg_de / max(1e-6, target_avg)
        p95_ratio = p95_de / max(1e-6, target_p95)
        risk = _to_float(r.get("decision_risk"), np.nan)
        if np.isnan(risk):
            risk = _clamp(
                0.55 * max(0.0, avg_ratio - 1.0)
                + 0.30 * max(0.0, p95_ratio - 1.0)
                + 0.15 * max(0.0, 1.0 - conf),
                0.0,
                1.0,
            )
        rows.append(
            {
                "id": int(r.get("id")),
                "pass": bool(r.get("pass", False)),
                "confidence": conf,
                "avg_ratio": avg_ratio,
                "p95_ratio": p95_ratio,
                "risk": risk,
                "decision_code_hist": str(r.get("decision_code") or ""),
            }
        )
    return rows


def _calibrate_factors(rows: list[dict[str, Any]], outcomes: list[dict[str, Any]]) -> dict[str, float]:
    default = {"AUTO_RELEASE": 1.0, "MANUAL_REVIEW": 0.35, "RECAPTURE_REQUIRED": 0.20, "HOLD_AND_ESCALATE": 0.08}
    by_run: dict[int, dict[str, Any]] = {}
    for o in outcomes:
        run_id = o.get("run_id")
        if run_id is None:
            continue
        by_run[int(run_id)] = o

    buckets: dict[str, list[tuple[float, float]]] = {k: [] for k in default}
    for row in rows:
        hist = row.get("decision_code_hist")
        if hist not in buckets:
            continue
        o = by_run.get(int(row["id"]))
        if not o:
            continue
        label = str(o.get("outcome") or "")
        sev = _to_float(o.get("severity"), 0.0)
        if label in ("complaint_major", "return"):
            bad = 1.0
        elif label in ("complaint_minor", "rework"):
            bad = max(0.35, min(0.75, sev if sev > 0 else 0.45))
        elif label == "accepted":
            bad = 0.0
        else:
            continue
        buckets[hist].append((float(row["risk"]), bad))

    out: dict[str, float] = {}
    out_uncertainty: dict[str, dict[str, float]] = {}
    LAPLACE_ALPHA = 1.0  # Laplace smoothing constant
    for k, vals in buckets.items():
        if len(vals) < 4:
            out[k] = default[k]
            out_uncertainty[k] = {"low": default[k], "high": default[k], "n": len(vals)}
            continue
        r = np.array([v[0] for v in vals], dtype=np.float64)
        b = np.array([v[1] for v in vals], dtype=np.float64)
        r_mean = float(np.mean(r))
        # Laplace smoothing: add LAPLACE_ALPHA to numerator and denominator
        # to avoid division by zero and stabilize small-sample estimates
        n = len(vals)
        smoothed_factor = _clamp(float((np.sum(b) + LAPLACE_ALPHA) / (np.sum(r) + LAPLACE_ALPHA)), 0.05, 1.50)
        out[k] = smoothed_factor
        # Uncertainty interval via bootstrap-like standard error estimate
        if r_mean > 1e-6 and n >= 4:
            b_std = float(np.std(b, ddof=1))
            se = b_std / (math.sqrt(n) * max(r_mean, 1e-6))
            out_uncertainty[k] = {
                "low": round(_clamp(smoothed_factor - 1.96 * se, 0.05, 1.50), 4),
                "high": round(_clamp(smoothed_factor + 1.96 * se, 0.05, 1.50), 4),
                "n": n,
            }
        else:
            out_uncertainty[k] = {"low": smoothed_factor, "high": smoothed_factor, "n": n}
    # Attach uncertainty as an attribute-like dict entry; callers access via _calibrate_factors
    # We return just the factors dict for backward compat; store uncertainty in module-level cache
    _calibrate_factors._last_uncertainty = out_uncertainty  # type: ignore[attr-defined]
    return out


def _simulate_decision(row: dict[str, Any], policy: dict[str, Any]) -> str:
    p = policy.get("decision_policy", {})
    auto_conf = _to_float(p.get("auto_release_min_confidence"), 0.82)
    manual_conf = _to_float(p.get("manual_review_min_confidence"), 0.68)
    recapture_conf = _to_float(p.get("recapture_max_confidence"), 0.62)
    max_avg = _to_float(p.get("max_avg_ratio_for_auto_release"), 1.0)
    max_p95 = _to_float(p.get("max_p95_ratio_for_auto_release"), 1.0)
    confidence = _to_float(row.get("confidence"), 0.0)
    avg_ratio = _to_float(row.get("avg_ratio"), 99.0)
    p95_ratio = _to_float(row.get("p95_ratio"), 99.0)
    risk = _to_float(row.get("risk"), 1.0)
    passed = bool(row.get("pass", False))

    if risk >= 0.90:
        return "HOLD_AND_ESCALATE"
    if confidence <= recapture_conf:
        return "RECAPTURE_REQUIRED"
    if risk >= 0.75 and not passed:
        return "HOLD_AND_ESCALATE"
    if passed and confidence >= auto_conf and avg_ratio <= max_avg and p95_ratio <= max_p95 and risk <= 0.70:
        return "AUTO_RELEASE"
    if confidence >= manual_conf:
        return "MANUAL_REVIEW"
    return "RECAPTURE_REQUIRED"


def _evaluate(rows: list[dict[str, Any]], policy: dict[str, Any], factors: dict[str, float]) -> dict[str, Any]:
    cm = policy.get("cost_model", {})
    manual_cost = _to_float(cm.get("manual_review_cost"), 18.0)
    recapture_cost = _to_float(cm.get("recapture_cost"), 10.0)
    hold_cost = _to_float(cm.get("hold_delay_cost"), 120.0)
    escape_cost = _to_float(cm.get("escape_cost"), 350.0)

    codes: list[str] = []
    bad_probs: list[float] = []
    costs: list[float] = []
    auto_bad: list[float] = []
    for row in rows:
        code = _simulate_decision(row, policy)
        codes.append(code)
        risk = _to_float(row.get("risk"), 0.5)
        factor = _to_float(factors.get(code), 1.0)
        bad = _clamp(risk * factor, 0.0, 1.0)
        bad_probs.append(bad)
        if code == "AUTO_RELEASE":
            auto_bad.append(bad)
        op = 0.0
        if code == "MANUAL_REVIEW":
            op += manual_cost
        elif code == "RECAPTURE_REQUIRED":
            op += recapture_cost
        elif code == "HOLD_AND_ESCALATE":
            op += hold_cost + manual_cost
        costs.append(op + bad * escape_cost)

    n = max(1, len(rows))
    auto_rate = float(np.mean([1.0 if c == "AUTO_RELEASE" else 0.0 for c in codes]))
    manual_rate = float(np.mean([1.0 if c == "MANUAL_REVIEW" else 0.0 for c in codes]))
    recapture_rate = float(np.mean([1.0 if c == "RECAPTURE_REQUIRED" else 0.0 for c in codes]))
    hold_rate = float(np.mean([1.0 if c == "HOLD_AND_ESCALATE" else 0.0 for c in codes]))
    escape_rate = float(np.mean(np.array(bad_probs, dtype=np.float64)))
    auto_escape_rate = float(np.mean(np.array(auto_bad, dtype=np.float64))) if auto_bad else 0.0
    cost_per_run = float(np.mean(np.array(costs, dtype=np.float64)))
    throughput = _clamp(100.0 * (auto_rate + 0.72 * manual_rate + 0.55 * recapture_rate + 0.28 * (1.0 - hold_rate)), 0.0, 100.0)
    customer_idx = _clamp(100.0 - 135.0 * escape_rate - 12.0 * hold_rate, 0.0, 100.0)
    boss_idx = _clamp(0.45 * throughput + 0.35 * (100.0 - escape_rate * 100.0) + 0.20 * _clamp(100.0 - cost_per_run / max(1.0, escape_cost) * 100.0, 0.0, 100.0), 0.0, 100.0)
    company_idx = _clamp(0.44 * customer_idx + 0.30 * (100.0 - escape_rate * 100.0) + 0.26 * (100.0 - hold_rate * 100.0), 0.0, 100.0)
    return {
        "sample_count": n,
        "auto_release_rate": auto_rate,
        "manual_review_rate": manual_rate,
        "recapture_rate": recapture_rate,
        "hold_rate": hold_rate,
        "expected_escape_rate": escape_rate,
        "expected_auto_release_escape_rate": auto_escape_rate,
        "expected_cost_per_run": cost_per_run,
        "customer_acceptance_index": customer_idx,
        "boss_efficiency_index": boss_idx,
        "company_governance_index": company_idx,
        "decision_counts": {
            "AUTO_RELEASE": sum(1 for c in codes if c == "AUTO_RELEASE"),
            "MANUAL_REVIEW": sum(1 for c in codes if c == "MANUAL_REVIEW"),
            "RECAPTURE_REQUIRED": sum(1 for c in codes if c == "RECAPTURE_REQUIRED"),
            "HOLD_AND_ESCALATE": sum(1 for c in codes if c == "HOLD_AND_ESCALATE"),
        },
    }


def _two_proportion_z_test(p1: float, n1: int, p2: float, n2: int) -> float:
    """Two-proportion z-test. Returns p-value (two-sided).

    Tests H0: p1 == p2 vs H1: p1 != p2.
    """
    if n1 <= 0 or n2 <= 0:
        return 1.0
    p_pool = (p1 * n1 + p2 * n2) / (n1 + n2)
    if p_pool <= 0 or p_pool >= 1:
        return 1.0
    se = math.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2))
    if se < 1e-12:
        return 1.0
    z = (p1 - p2) / se
    # Two-sided p-value using normal CDF approximation (erfc)
    p_value = math.erfc(abs(z) / math.sqrt(2))
    return p_value


MIN_SAMPLE_SIZE_PER_ARM = 20


def _rollout_decision(champ: dict[str, Any], chall: dict[str, Any]) -> tuple[str, list[str]]:
    reasons: list[str] = []

    n_champ = int(_to_float(champ.get("sample_count"), 0))
    n_chall = int(_to_float(chall.get("sample_count"), 0))

    # Minimum sample size requirement
    if n_champ < MIN_SAMPLE_SIZE_PER_ARM or n_chall < MIN_SAMPLE_SIZE_PER_ARM:
        return "CANARY", [
            f"insufficient_sample_size: champion={n_champ}, challenger={n_chall}, "
            f"minimum={MIN_SAMPLE_SIZE_PER_ARM}"
        ]

    escape_gain = _to_float(champ.get("expected_escape_rate"), 1.0) - _to_float(chall.get("expected_escape_rate"), 1.0)
    cost_gain = _to_float(champ.get("expected_cost_per_run"), 1e9) - _to_float(chall.get("expected_cost_per_run"), 1e9)
    customer_gain = _to_float(chall.get("customer_acceptance_index"), 0.0) - _to_float(champ.get("customer_acceptance_index"), 0.0)
    throughput_gain = _to_float(chall.get("auto_release_rate"), 0.0) - _to_float(champ.get("auto_release_rate"), 0.0)

    # Statistical significance test: two-proportion z-test on escape rates
    p_champ = _to_float(champ.get("expected_escape_rate"), 0.0)
    p_chall = _to_float(chall.get("expected_escape_rate"), 0.0)
    sig_p_value = _two_proportion_z_test(p_champ, n_champ, p_chall, n_chall)
    is_significant = sig_p_value < 0.05

    if escape_gain >= 0.006 and customer_gain >= 0.8:
        reasons.append("challenger_reduces_escape_and_improves_customer")
    if cost_gain >= 4.0:
        reasons.append("challenger_reduces_expected_cost")
    if throughput_gain >= 0.02:
        reasons.append("challenger_improves_auto_release_rate")
    if is_significant:
        reasons.append(f"statistically_significant (p={sig_p_value:.4f})")
    else:
        reasons.append(f"not_statistically_significant (p={sig_p_value:.4f})")

    # Require statistical significance (p < 0.05) for PROMOTE
    if (escape_gain >= 0.010 and customer_gain >= 1.5
            and _to_float(chall.get("expected_escape_rate"), 1.0) <= 0.03
            and is_significant):
        return "PROMOTE", reasons or ["strong_win_on_quality_and_risk"]
    if escape_gain >= -0.002 and customer_gain >= -0.5:
        return "CANARY", reasons or ["borderline_win_requires_canary"]
    return "REJECT", reasons or ["challenger_not_better_than_champion"]


def _rollout_plan(
    verdict: str,
    canary_ratio: float,
    phase_days: int,
) -> list[dict[str, Any]]:
    c = _clamp(canary_ratio, 0.05, 0.50)
    d = max(1, int(phase_days))
    if verdict == "REJECT":
        return [{"phase": "rollback", "traffic_ratio": 0.0, "duration_days": 0, "gate": "Keep champion policy only."}]
    if verdict == "PROMOTE":
        return [
            {"phase": "canary", "traffic_ratio": c, "duration_days": d, "gate": "Stop if escape_rate > champion * 1.10"},
            {"phase": "ramp_50", "traffic_ratio": 0.5, "duration_days": d, "gate": "Stop if complaint_rate rises > +0.5pp"},
            {"phase": "full", "traffic_ratio": 1.0, "duration_days": d, "gate": "Promote if no red alerts in 3 days"},
        ]
    return [
        {"phase": "canary", "traffic_ratio": c, "duration_days": d, "gate": "Continue if escape_rate <= champion * 1.05"},
        {"phase": "extended_canary", "traffic_ratio": min(0.35, c + 0.15), "duration_days": d + 1, "gate": "Continue if customer index not degraded"},
        {"phase": "decision", "traffic_ratio": 0.0, "duration_days": 0, "gate": "Promote or rollback based on KPI review"},
    ]


def champion_challenger_rollout(
    db_path: Path,
    line_id: str | None = None,
    product_code: str | None = None,
    lot_id: str | None = None,
    window: int = 260,
    champion_policy_config: Path | None = None,
    challenger_policy_config: Path | None = None,
    challenger_patch: dict[str, Any] | None = None,
    canary_ratio: float = 0.15,
    phase_days: int = 3,
) -> dict[str, Any]:
    runs = list_recent_runs(
        db_path=db_path,
        line_id=line_id,
        product_code=product_code,
        lot_id=lot_id,
        limit=max(40, int(window)),
    )
    outcomes = list_outcomes(
        db_path=db_path,
        line_id=line_id,
        product_code=product_code,
        lot_id=lot_id,
        limit=max(60, int(window)),
    )
    if not runs:
        return {"enabled": False, "reason": "no_runs"}

    target_avg, target_p95 = _estimate_targets(runs)
    rows = _build_rows(runs, target_avg, target_p95)
    if len(rows) < 15:
        return {
            "enabled": True,
            "insufficient_data": True,
            "reason": "not_enough_rows",
            "run_count": len(runs),
            "feature_row_count": len(rows),
        }

    champion_policy, champion_source = load_decision_policy(champion_policy_config)
    if challenger_policy_config is not None:
        challenger_policy, challenger_source = load_decision_policy(challenger_policy_config)
    else:
        challenger_policy = apply_policy_patch(champion_policy, challenger_patch or {})
        challenger_source = "champion_plus_patch"

    factors = _calibrate_factors(rows, outcomes)
    champion_metrics = _evaluate(rows, champion_policy, factors)
    challenger_metrics = _evaluate(rows, challenger_policy, factors)

    verdict, reasons = _rollout_decision(champion_metrics, challenger_metrics)
    plan = _rollout_plan(verdict, canary_ratio=canary_ratio, phase_days=phase_days)

    delta = {
        "auto_release_rate": _to_float(challenger_metrics.get("auto_release_rate"), 0.0) - _to_float(champion_metrics.get("auto_release_rate"), 0.0),
        "expected_escape_rate": _to_float(challenger_metrics.get("expected_escape_rate"), 1.0) - _to_float(champion_metrics.get("expected_escape_rate"), 1.0),
        "expected_cost_per_run": _to_float(challenger_metrics.get("expected_cost_per_run"), 1e9) - _to_float(champion_metrics.get("expected_cost_per_run"), 1e9),
        "customer_acceptance_index": _to_float(challenger_metrics.get("customer_acceptance_index"), 0.0) - _to_float(champion_metrics.get("customer_acceptance_index"), 0.0),
    }

    return {
        "enabled": True,
        "innovation": "champion_challenger_auto_rollout",
        "sample_count": len(rows),
        "target_estimation": {"avg_target_est": target_avg, "p95_target_est": target_p95},
        "champion": {"source": champion_source, "metrics": champion_metrics},
        "challenger": {
            "source": challenger_source,
            "metrics": challenger_metrics,
            "patch": challenger_patch or {},
            "policy": challenger_policy,
        },
        "delta": delta,
        "verdict": verdict,
        "reasons": reasons,
        "rollout_plan": plan,
        "guardrails": {
            "max_allowed_escape_rate": min(_to_float(champion_metrics.get("expected_escape_rate"), 0.03) * 1.10, 0.06),
            "min_customer_acceptance_index": _to_float(champion_metrics.get("customer_acceptance_index"), 80.0) - 1.0,
        },
    }
