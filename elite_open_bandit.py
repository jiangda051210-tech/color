from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from elite_decision_center import apply_policy_patch, load_decision_policy
from elite_quality_history import list_outcomes, list_recent_runs


ARM_SPECS: dict[str, dict[str, Any]] = {
    "quality_guard": {
        "description": "Stricter quality guard for risk-sensitive or VIP-heavy windows.",
        "policy_patch": {
            "decision_policy": {
                "auto_release_min_confidence_delta": 0.02,
                "manual_review_min_confidence_delta": 0.01,
                "max_avg_ratio_for_auto_release_delta": -0.02,
                "max_p95_ratio_for_auto_release_delta": -0.02,
            }
        },
    },
    "balanced": {
        "description": "Balanced quality and throughput baseline.",
        "policy_patch": {"decision_policy": {}},
    },
    "throughput_boost": {
        "description": "Throughput-oriented policy under controlled risk.",
        "policy_patch": {
            "decision_policy": {
                "auto_release_min_confidence_delta": -0.01,
                "max_avg_ratio_for_auto_release_delta": 0.01,
                "max_p95_ratio_for_auto_release_delta": 0.01,
            }
        },
    },
}


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
    avg = avg[~np.isnan(avg)]
    p95 = p95[~np.isnan(p95)]
    if avg.size == 0 or p95.size == 0:
        return 1.0, 1.8
    return max(0.25, float(np.nanpercentile(avg, 38))), max(0.45, float(np.nanpercentile(p95, 38)))


def _risk_from_row(avg_ratio: float, p95_ratio: float, confidence: float) -> float:
    return _clamp(
        0.58 * max(0.0, avg_ratio - 1.0)
        + 0.29 * max(0.0, p95_ratio - 1.0)
        + 0.13 * max(0.0, 1.0 - confidence),
        0.0,
        1.0,
    )


def _vector_from_row(
    row: dict[str, Any],
    target_avg: float,
    target_p95: float,
) -> tuple[np.ndarray, dict[str, float]] | None:
    avg_de = _to_float(row.get("avg_de"), np.nan)
    p95_de = _to_float(row.get("p95_de"), np.nan)
    if np.isnan(avg_de) or np.isnan(p95_de):
        return None
    confidence = _clamp(_to_float(row.get("confidence"), 0.5), 0.0, 1.0)
    avg_ratio = avg_de / max(1e-6, target_avg)
    p95_ratio = p95_de / max(1e-6, target_p95)
    risk = _to_float(row.get("decision_risk"), np.nan)
    if np.isnan(risk):
        risk = _risk_from_row(avg_ratio, p95_ratio, confidence)
    is_pass = 1.0 if bool(row.get("pass", False)) else 0.0
    x = np.array(
        [
            1.0,
            _clamp(avg_ratio, 0.2, 3.5),
            _clamp(p95_ratio, 0.2, 3.8),
            _clamp(1.0 - confidence, 0.0, 1.0),
            _clamp(risk, 0.0, 1.0),
            is_pass,
        ],
        dtype=np.float64,
    )
    snap = {
        "avg_ratio": float(x[1]),
        "p95_ratio": float(x[2]),
        "confidence": float(1.0 - x[3]),
        "decision_risk": float(x[4]),
        "pass_indicator": float(x[5]),
    }
    return x, snap


def _code_to_arm(decision_code: str, confidence: float, risk: float, passed: bool) -> str:
    code = decision_code.strip().upper()
    if code == "AUTO_RELEASE":
        return "throughput_boost"
    if code == "MANUAL_REVIEW":
        return "balanced"
    if code in ("RECAPTURE_REQUIRED", "HOLD_AND_ESCALATE"):
        return "quality_guard"
    if risk > 0.72:
        return "quality_guard"
    if confidence > 0.82 and passed:
        return "throughput_boost"
    return "balanced"


def _reward_from_outcome(outcome_row: dict[str, Any] | None, row: dict[str, Any], snap: dict[str, float]) -> tuple[float, float]:
    if outcome_row is None:
        fallback = (
            (0.60 if bool(row.get("pass", False)) else -0.35)
            + 0.25 * (snap["confidence"] - 0.70)
            - 0.25 * max(0.0, snap["avg_ratio"] - 1.0)
            - 0.22 * max(0.0, snap["p95_ratio"] - 1.0)
            - 0.25 * snap["decision_risk"]
        )
        return _clamp(fallback, -1.6, 1.6), 0.0

    label = str(outcome_row.get("outcome") or "").lower()
    base = {
        "accepted": 1.0,
        "pending": 0.20,
        "rework": -0.45,
        "complaint_minor": -0.70,
        "complaint_major": -1.10,
        "return": -1.25,
    }.get(label, 0.0)
    sev = _clamp(_to_float(outcome_row.get("severity"), 0.0), 0.0, 1.0)
    rating = _to_float(outcome_row.get("customer_rating"), np.nan)
    cost = max(0.0, _to_float(outcome_row.get("realized_cost"), 0.0))
    rating_term = 0.0 if np.isnan(rating) else (rating - 80.0) / 120.0
    cost_penalty = min(0.55, cost / 900.0)
    conf_term = 0.08 * (snap["confidence"] - 0.70)
    reward = base - 0.35 * sev - cost_penalty + rating_term + conf_term
    bad = 1.0 if label in ("complaint_major", "return") else 0.0
    return _clamp(reward, -1.8, 1.8), bad


def _build_query_context(
    latest: dict[str, float] | None,
    avg_ratio: float | None,
    p95_ratio: float | None,
    confidence: float | None,
    decision_risk: float | None,
) -> tuple[np.ndarray, dict[str, Any]]:
    base = latest or {
        "avg_ratio": 1.0,
        "p95_ratio": 1.0,
        "confidence": 0.78,
        "decision_risk": 0.24,
        "pass_indicator": 1.0,
    }
    ar = _clamp(float(avg_ratio) if avg_ratio is not None else _to_float(base.get("avg_ratio"), 1.0), 0.2, 3.5)
    pr = _clamp(float(p95_ratio) if p95_ratio is not None else _to_float(base.get("p95_ratio"), 1.0), 0.2, 3.8)
    cf = _clamp(float(confidence) if confidence is not None else _to_float(base.get("confidence"), 0.78), 0.0, 1.0)
    risk = _clamp(float(decision_risk) if decision_risk is not None else _to_float(base.get("decision_risk"), np.nan), 0.0, 1.0)
    if np.isnan(risk):
        risk = _risk_from_row(ar, pr, cf)
    pass_indicator = _clamp(_to_float(base.get("pass_indicator"), 1.0), 0.0, 1.0)
    vector = np.array([1.0, ar, pr, 1.0 - cf, risk, pass_indicator], dtype=np.float64)
    return vector, {
        "source": "override_or_latest",
        "avg_ratio": ar,
        "p95_ratio": pr,
        "confidence": cf,
        "decision_risk": risk,
        "pass_indicator": pass_indicator,
    }


def recommend_open_bandit_policy(
    db_path: Path,
    line_id: str | None = None,
    product_code: str | None = None,
    lot_id: str | None = None,
    window: int = 360,
    policy_config: Path | None = None,
    alpha: float = 0.35,
    avg_ratio: float | None = None,
    p95_ratio: float | None = None,
    confidence: float | None = None,
    decision_risk: float | None = None,
) -> dict[str, Any]:
    runs = list_recent_runs(
        db_path=db_path,
        line_id=line_id,
        product_code=product_code,
        lot_id=lot_id,
        limit=max(90, int(window)),
    )
    if not runs:
        return {"enabled": False, "reason": "no_runs"}

    outcomes = list_outcomes(
        db_path=db_path,
        line_id=line_id,
        product_code=product_code,
        lot_id=lot_id,
        limit=max(120, int(window)),
    )
    by_run: dict[int, dict[str, Any]] = {}
    for o in outcomes:
        rid = o.get("run_id")
        if rid is None:
            continue
        try:
            key = int(rid)
        except Exception:  # noqa: BLE001
            continue
        if key not in by_run:
            by_run[key] = o

    target_avg, target_p95 = _estimate_targets(runs)
    prepared: list[dict[str, Any]] = []
    for row in runs:
        vec_and_snap = _vector_from_row(row, target_avg, target_p95)
        if vec_and_snap is None:
            continue
        x, snap = vec_and_snap
        rid = int(row.get("id")) if row.get("id") is not None else -1
        decision_code = str(row.get("decision_code") or "")
        arm = _code_to_arm(
            decision_code=decision_code,
            confidence=snap["confidence"],
            risk=snap["decision_risk"],
            passed=bool(row.get("pass", False)),
        )
        reward, bad = _reward_from_outcome(by_run.get(rid), row, snap)
        prepared.append(
            {
                "run_id": rid,
                "x": x,
                "snap": snap,
                "arm": arm,
                "reward": reward,
                "bad": bad,
            }
        )

    if len(prepared) < 12:
        base_policy, source = load_decision_policy(policy_config)
        fallback_arm = "balanced"
        patch = ARM_SPECS[fallback_arm]["policy_patch"]
        return {
            "enabled": True,
            "innovation": "open_linucb_policy_orchestrator",
            "insufficient_data": True,
            "sample_count": len(prepared),
            "reason": "need_at_least_12_samples",
            "recommendation": {
                "arm": fallback_arm,
                "arm_description": ARM_SPECS[fallback_arm]["description"],
                "policy_patch": patch,
                "suggested_policy": apply_policy_patch(base_policy, patch),
                "base_policy_source": source,
                "reasoning": ["insufficient_samples_fallback_to_balanced"],
            },
        }

    dim = int(prepared[0]["x"].shape[0])
    arm_state: dict[str, dict[str, Any]] = {}
    for arm in ARM_SPECS:
        arm_state[arm] = {
            "A": np.eye(dim, dtype=np.float64),
            "b": np.zeros(dim, dtype=np.float64),
            "count": 0,
            "reward_sum": 0.0,
            "bad_sum": 0.0,
        }

    for row in prepared:
        state = arm_state[row["arm"]]
        x = row["x"]
        r = float(row["reward"])
        state["A"] += np.outer(x, x)
        state["b"] += r * x
        state["count"] += 1
        state["reward_sum"] += r
        state["bad_sum"] += float(row["bad"])

    latest_snap = prepared[0]["snap"] if prepared else None
    x_query, context_snapshot = _build_query_context(
        latest=latest_snap,
        avg_ratio=avg_ratio,
        p95_ratio=p95_ratio,
        confidence=confidence,
        decision_risk=decision_risk,
    )

    alpha_v = _clamp(float(alpha), 0.05, 1.20)
    arm_scores: dict[str, dict[str, Any]] = {}
    for arm, state in arm_state.items():
        A = state["A"]
        b = state["b"]
        A_inv = np.linalg.pinv(A)
        theta = A_inv @ b
        pred = float(theta @ x_query)
        unc = float(alpha_v * np.sqrt(max(0.0, float(x_query @ A_inv @ x_query))))
        ucb = pred + unc
        count = int(state["count"])
        mean_reward = float(state["reward_sum"] / count) if count > 0 else 0.0
        bad_rate = float(state["bad_sum"] / count) if count > 0 else 0.0
        arm_scores[arm] = {
            "count": count,
            "predicted_reward": pred,
            "exploration_bonus": unc,
            "ucb_score": ucb,
            "historical_mean_reward": mean_reward,
            "historical_bad_event_rate": bad_rate,
            "arm_description": ARM_SPECS[arm]["description"],
        }

    best_arm = max(arm_scores.items(), key=lambda kv: kv[1]["ucb_score"])[0]
    base_policy, source = load_decision_policy(policy_config)
    best_patch = ARM_SPECS[best_arm]["policy_patch"]
    suggested_policy = apply_policy_patch(base_policy, best_patch)

    reasons: list[str] = []
    best_detail = arm_scores[best_arm]
    if best_detail["historical_bad_event_rate"] <= 0.03:
        reasons.append("historical_bad_event_rate_is_low")
    if best_detail["predicted_reward"] > 0:
        reasons.append("predicted_reward_is_positive")
    if best_detail["exploration_bonus"] > 0.10:
        reasons.append("exploration_bonus_suggests_learning_value")
    if not reasons:
        reasons.append("highest_ucb_under_current_context")

    return {
        "enabled": True,
        "innovation": "open_linucb_policy_orchestrator",
        "sample_count": len(prepared),
        "bandit_dimension": dim,
        "alpha": alpha_v,
        "target_estimation": {"avg_target_est": target_avg, "p95_target_est": target_p95},
        "context_snapshot": context_snapshot,
        "arms": arm_scores,
        "recommendation": {
            "arm": best_arm,
            "arm_description": ARM_SPECS[best_arm]["description"],
            "policy_patch": best_patch,
            "suggested_policy": suggested_policy,
            "base_policy_source": source,
            "reasoning": reasons,
        },
    }
