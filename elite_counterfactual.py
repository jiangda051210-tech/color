from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

try:
    from sklearn.ensemble import GradientBoostingRegressor
    from sklearn.model_selection import train_test_split
    _SKLEARN_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover
    _SKLEARN_AVAILABLE = False
    GradientBoostingRegressor = None  # type: ignore[assignment,misc]
    train_test_split = None  # type: ignore[assignment]

from elite_decision_center import apply_policy_patch, load_decision_policy
from elite_quality_history import list_outcomes, list_recent_runs


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:  # noqa: BLE001
        return default


def _clamp(value: float, lo: float, hi: float) -> float:
    return float(max(lo, min(hi, value)))


def _decision_one(
    confidence: float,
    avg_ratio: float,
    p95_ratio: float,
    risk: float,
    passed: bool,
    decision_policy: dict[str, Any],
) -> str:
    auto_conf = _to_float(decision_policy.get("auto_release_min_confidence"), 0.82)
    manual_conf = _to_float(decision_policy.get("manual_review_min_confidence"), 0.68)
    recapture_conf = _to_float(decision_policy.get("recapture_max_confidence"), 0.62)
    max_avg_ratio = _to_float(decision_policy.get("max_avg_ratio_for_auto_release"), 1.0)
    max_p95_ratio = _to_float(decision_policy.get("max_p95_ratio_for_auto_release"), 1.0)

    if risk >= 0.90:
        return "HOLD_AND_ESCALATE"
    if confidence <= recapture_conf:
        return "RECAPTURE_REQUIRED"
    if risk >= 0.78 and not passed:
        return "HOLD_AND_ESCALATE"
    if (
        passed
        and confidence >= auto_conf
        and avg_ratio <= max_avg_ratio
        and p95_ratio <= max_p95_ratio
        and risk <= 0.72
    ):
        return "AUTO_RELEASE"
    if confidence >= manual_conf:
        return "MANUAL_REVIEW"
    return "RECAPTURE_REQUIRED"


def _estimate_targets(runs: list[dict[str, Any]]) -> tuple[float, float, float]:
    avg = np.array([_to_float(r.get("avg_de"), np.nan) for r in runs], dtype=np.float64)
    p95 = np.array([_to_float(r.get("p95_de"), np.nan) for r in runs], dtype=np.float64)
    maxv = np.array([_to_float(r.get("max_de"), np.nan) for r in runs], dtype=np.float64)
    passed = np.array([1.0 if bool(r.get("pass")) else 0.0 for r in runs], dtype=np.float64) > 0.5

    def pick(values: np.ndarray, pass_mask: np.ndarray, fallback_q: float, mult: float, lo: float) -> float:
        vals = values[~np.isnan(values)]
        if vals.size == 0:
            return lo
        if pass_mask.size == values.size:
            pass_vals = values[(pass_mask) & (~np.isnan(values))]
        else:
            pass_vals = np.array([], dtype=np.float64)
        if pass_vals.size >= 4:
            base = float(np.nanmean(pass_vals) * mult)
        else:
            base = float(np.nanpercentile(vals, fallback_q))
        return max(lo, base)

    t_avg = pick(avg, passed, 35, 1.05, 0.2)
    t_p95 = pick(p95, passed, 35, 1.08, 0.4)
    t_max = pick(maxv, passed, 40, 1.08, 0.6)
    return t_avg, t_p95, t_max


def _outcome_to_bad_score(outcome: str, severity: float | None) -> float:
    o = str(outcome or "").lower()
    s = _to_float(severity, 0.0)
    if o in ("complaint_major", "return"):
        return 1.0
    if o == "complaint_minor":
        return max(0.35, min(0.80, s if s > 0 else 0.45))
    if o == "rework":
        return max(0.30, min(0.75, s if s > 0 else 0.40))
    if o == "accepted":
        return 0.0
    return np.nan


def _build_joined_rows(
    runs: list[dict[str, Any]],
    outcomes: list[dict[str, Any]],
    target_avg: float,
    target_p95: float,
    target_max: float,
) -> list[dict[str, Any]]:
    outcome_map: dict[int, dict[str, Any]] = {}
    for o in outcomes:
        run_id = o.get("run_id")
        if run_id is None:
            continue
        key = int(run_id)
        if key not in outcome_map:
            outcome_map[key] = o

    out: list[dict[str, Any]] = []
    for r in runs:
        run_id = r.get("id")
        if run_id is None:
            continue
        avg_de = _to_float(r.get("avg_de"), np.nan)
        p95_de = _to_float(r.get("p95_de"), np.nan)
        max_de = _to_float(r.get("max_de"), np.nan)
        d_l = _to_float(r.get("dL"), 0.0)
        d_c = _to_float(r.get("dC"), 0.0)
        d_h = _to_float(r.get("dH"), 0.0)
        confidence = _to_float(r.get("confidence"), np.nan)
        if np.isnan(avg_de) or np.isnan(p95_de) or np.isnan(max_de):
            continue
        if np.isnan(confidence):
            confidence = 0.5

        risk = _to_float(r.get("decision_risk"), np.nan)
        if np.isnan(risk):
            risk = _clamp(
                0.52 * max(0.0, avg_de / max(1e-6, target_avg) - 1.0)
                + 0.30 * max(0.0, p95_de / max(1e-6, target_p95) - 1.0)
                + 0.18 * max(0.0, 1.0 - confidence),
                0.0,
                1.0,
            )

        decision_code = str(r.get("decision_code") or "")
        is_auto = 1.0 if decision_code == "AUTO_RELEASE" else 0.0
        is_manual = 1.0 if decision_code == "MANUAL_REVIEW" else 0.0
        is_recap = 1.0 if decision_code == "RECAPTURE_REQUIRED" else 0.0
        is_hold = 1.0 if decision_code == "HOLD_AND_ESCALATE" else 0.0

        outcome_row = outcome_map.get(int(run_id))
        bad_score = np.nan
        realized_cost = np.nan
        customer_rating = np.nan
        if outcome_row is not None:
            bad_score = _outcome_to_bad_score(str(outcome_row.get("outcome") or ""), outcome_row.get("severity"))
            realized_cost = _to_float(outcome_row.get("realized_cost"), np.nan)
            customer_rating = _to_float(outcome_row.get("customer_rating"), np.nan)

        estimated_cost = _to_float(r.get("estimated_cost"), np.nan)
        if np.isnan(estimated_cost):
            estimated_cost = risk * 350.0 + (18.0 if is_manual else 0.0) + (10.0 if is_recap else 0.0) + (120.0 if is_hold else 0.0)
        if np.isnan(realized_cost):
            realized_cost = estimated_cost

        if np.isnan(bad_score):
            bad_score = _clamp(risk * (1.0 if is_auto else 0.45 if is_manual else 0.22 if is_recap else 0.10), 0.0, 1.0)
        if np.isnan(customer_rating):
            customer_rating = _clamp(100.0 - 72.0 * bad_score - 10.0 * is_hold - 5.0 * is_recap, 0.0, 100.0)

        out.append(
            {
                "id": int(run_id),
                "avg_de": avg_de,
                "p95_de": p95_de,
                "max_de": max_de,
                "dL": d_l,
                "dC": d_c,
                "dH": d_h,
                "confidence": confidence,
                "risk": risk,
                "pass": bool(r.get("pass", False)),
                "decision_code": decision_code,
                "is_auto": is_auto,
                "is_manual": is_manual,
                "is_recap": is_recap,
                "is_hold": is_hold,
                "avg_ratio": avg_de / max(1e-6, target_avg),
                "p95_ratio": p95_de / max(1e-6, target_p95),
                "max_ratio": max_de / max(1e-6, target_max),
                "y_bad": bad_score,
                "y_cost": realized_cost,
                "y_customer": customer_rating,
            }
        )
    return out


@dataclass
class _ConformalRegressor:
    model: GradientBoostingRegressor
    q_abs_error: float

    def predict(self, x: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        pred = self.model.predict(x)
        lo = pred - self.q_abs_error
        hi = pred + self.q_abs_error
        return pred, lo, hi


def _fit_conformal_gbr(
    x: np.ndarray,
    y: np.ndarray,
    random_state: int = 42,
) -> _ConformalRegressor | None:
    if x.shape[0] < 18:
        return None
    try:
        x_train, x_cal, y_train, y_cal = train_test_split(x, y, test_size=0.30, random_state=random_state)
    except ValueError:
        return None
    if x_train.shape[0] < 10 or x_cal.shape[0] < 5:
        return None

    model = GradientBoostingRegressor(
        random_state=random_state,
        n_estimators=180,
        max_depth=3,
        learning_rate=0.05,
        subsample=0.9,
    )
    model.fit(x_train, y_train)
    cal_pred = model.predict(x_cal)
    abs_err = np.abs(y_cal - cal_pred)
    q = float(np.quantile(abs_err, 0.90)) if abs_err.size else 0.0
    return _ConformalRegressor(model=model, q_abs_error=q)


def _feature_matrix(rows: list[dict[str, Any]]) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    x = np.array(
        [
            [
                r["avg_de"],
                r["p95_de"],
                r["max_de"],
                abs(r["dL"]),
                abs(r["dC"]),
                abs(r["dH"]),
                r["confidence"],
                r["risk"],
                r["is_auto"],
                r["is_manual"],
                r["is_recap"],
                r["is_hold"],
            ]
            for r in rows
        ],
        dtype=np.float64,
    )
    y_bad = np.array([_to_float(r["y_bad"], 0.5) for r in rows], dtype=np.float64)
    y_cost = np.array([_to_float(r["y_cost"], 120.0) for r in rows], dtype=np.float64)
    y_customer = np.array([_to_float(r["y_customer"], 70.0) for r in rows], dtype=np.float64)
    return x, y_bad, y_cost, y_customer


def _scenario_grid() -> list[dict[str, float]]:
    conf_d = [-0.03, -0.015, 0.0, 0.015, 0.03]
    avg_d = [-0.04, 0.0, 0.04]
    p95_d = [-0.04, 0.0, 0.04]
    luma = [-0.35, 0.0, 0.35]
    chroma = [-0.35, 0.0, 0.35]
    hue = [-1.0, 0.0, 1.0]

    grid: list[dict[str, float]] = []
    for c in conf_d:
        for a in avg_d:
            for p in p95_d:
                for l in luma:
                    for ch in chroma:
                        for h in hue:
                            name = f"c{c:+.3f}_a{a:+.3f}_p{p:+.3f}_l{l:+.2f}_ch{ch:+.2f}_h{h:+.2f}"
                            grid.append(
                                {
                                    "name": name,
                                    "auto_release_min_confidence_delta": c,
                                    "max_avg_ratio_for_auto_release_delta": a,
                                    "max_p95_ratio_for_auto_release_delta": p,
                                    "luma_shift": l,
                                    "chroma_shift": ch,
                                    "hue_shift": h,
                                }
                            )
    return grid


def _counterfactual_transform_row(row: dict[str, Any], sc: dict[str, float]) -> dict[str, Any]:
    d_l = _to_float(row["dL"], 0.0)
    d_c = _to_float(row["dC"], 0.0)
    d_h = _to_float(row["dH"], 0.0)
    l_shift = _to_float(sc["luma_shift"], 0.0)
    c_shift = _to_float(sc["chroma_shift"], 0.0)
    h_shift = _to_float(sc["hue_shift"], 0.0)

    d_l_new = d_l - l_shift
    d_c_new = d_c - c_shift
    d_h_new = d_h - h_shift

    def gain(old: float, new: float) -> float:
        denom = max(1e-6, abs(old))
        return _clamp((abs(old) - abs(new)) / denom, -1.0, 1.0)

    g_l = gain(d_l, d_l_new)
    g_c = gain(d_c, d_c_new)
    g_h = gain(d_h, d_h_new)
    improve = max(-0.75, 0.50 * g_l + 0.34 * g_c + 0.16 * g_h)

    over = 0.0
    over += max(0.0, abs(l_shift) - abs(d_l))
    over += max(0.0, abs(c_shift) - abs(d_c))
    over += 0.35 * max(0.0, abs(h_shift) - abs(d_h))
    over_norm = _clamp(over / 2.5, 0.0, 1.0)

    avg_cf = max(0.01, _to_float(row["avg_de"]) * (1.0 - 0.34 * improve + 0.12 * over_norm))
    p95_cf = max(0.02, _to_float(row["p95_de"]) * (1.0 - 0.28 * improve + 0.14 * over_norm))
    max_cf = max(0.03, _to_float(row["max_de"]) * (1.0 - 0.22 * improve + 0.16 * over_norm))
    conf_cf = _clamp(_to_float(row["confidence"]) - 0.04 * over_norm + 0.015 * max(0.0, improve), 0.0, 1.0)
    risk_cf = _clamp(_to_float(row["risk"]) * (1.0 - 0.55 * max(0.0, improve) + 0.35 * over_norm), 0.0, 1.0)

    out = dict(row)
    out.update(
        {
            "avg_de_cf": avg_cf,
            "p95_de_cf": p95_cf,
            "max_de_cf": max_cf,
            "dL_cf": d_l_new,
            "dC_cf": d_c_new,
            "dH_cf": d_h_new,
            "confidence_cf": conf_cf,
            "risk_cf": risk_cf,
            "improve_score": improve,
            "overshoot_score": over_norm,
        }
    )
    return out


def _cf_feature_matrix(cf_rows: list[dict[str, Any]]) -> np.ndarray:
    return np.array(
        [
            [
                r["avg_de_cf"],
                r["p95_de_cf"],
                r["max_de_cf"],
                abs(r["dL_cf"]),
                abs(r["dC_cf"]),
                abs(r["dH_cf"]),
                r["confidence_cf"],
                r["risk_cf"],
                1.0 if r.get("decision_code_cf") == "AUTO_RELEASE" else 0.0,
                1.0 if r.get("decision_code_cf") == "MANUAL_REVIEW" else 0.0,
                1.0 if r.get("decision_code_cf") == "RECAPTURE_REQUIRED" else 0.0,
                1.0 if r.get("decision_code_cf") == "HOLD_AND_ESCALATE" else 0.0,
            ]
            for r in cf_rows
        ],
        dtype=np.float64,
    )


def _summarize_decisions(codes: list[str]) -> dict[str, float]:
    n = max(1, len(codes))
    auto = sum(1 for c in codes if c == "AUTO_RELEASE") / n
    manual = sum(1 for c in codes if c == "MANUAL_REVIEW") / n
    recap = sum(1 for c in codes if c == "RECAPTURE_REQUIRED") / n
    hold = sum(1 for c in codes if c == "HOLD_AND_ESCALATE") / n
    return {
        "auto_release_rate": auto,
        "manual_review_rate": manual,
        "recapture_rate": recap,
        "hold_rate": hold,
    }


def _pareto_front(items: list[dict[str, Any]]) -> list[str]:
    front: list[str] = []
    for i, a in enumerate(items):
        am = a["metrics"]
        dominated = False
        for j, b in enumerate(items):
            if i == j:
                continue
            bm = b["metrics"]
            better_or_equal = (
                _to_float(bm["customer_acceptance_index"]) >= _to_float(am["customer_acceptance_index"])
                and _to_float(bm["throughput_index"]) >= _to_float(am["throughput_index"])
                and _to_float(bm["governance_index"]) >= _to_float(am["governance_index"])
                and _to_float(bm["expected_cost_per_run"]) <= _to_float(am["expected_cost_per_run"])
                and _to_float(bm["expected_escape_rate"]) <= _to_float(am["expected_escape_rate"])
            )
            strictly = (
                _to_float(bm["customer_acceptance_index"]) > _to_float(am["customer_acceptance_index"])
                or _to_float(bm["throughput_index"]) > _to_float(am["throughput_index"])
                or _to_float(bm["governance_index"]) > _to_float(am["governance_index"])
                or _to_float(bm["expected_cost_per_run"]) < _to_float(am["expected_cost_per_run"])
                or _to_float(bm["expected_escape_rate"]) < _to_float(am["expected_escape_rate"])
            )
            if better_or_equal and strictly:
                dominated = True
                break
        if not dominated:
            front.append(str(a["name"]))
    return front


def run_counterfactual_twin(
    db_path: Path,
    line_id: str | None = None,
    product_code: str | None = None,
    lot_id: str | None = None,
    window: int = 260,
    policy_config: Path | None = None,
    max_scenarios: int = 260,
) -> dict[str, Any]:
    runs = list_recent_runs(
        db_path=db_path,
        line_id=line_id,
        product_code=product_code,
        lot_id=lot_id,
        limit=max(30, int(window)),
    )
    outcomes = list_outcomes(
        db_path=db_path,
        line_id=line_id,
        product_code=product_code,
        lot_id=lot_id,
        limit=max(40, int(window)),
    )
    if not runs:
        return {"enabled": False, "reason": "no_runs"}

    t_avg, t_p95, t_max = _estimate_targets(runs)
    rows = _build_joined_rows(runs, outcomes, target_avg=t_avg, target_p95=t_p95, target_max=t_max)
    if len(rows) < 12:
        return {
            "enabled": True,
            "insufficient_data": True,
            "reason": "not_enough_rows",
            "run_count": len(runs),
            "joined_row_count": len(rows),
        }

    x, y_bad, y_cost, y_customer = _feature_matrix(rows)
    bad_model = _fit_conformal_gbr(x, y_bad, random_state=11)
    cost_model = _fit_conformal_gbr(x, y_cost, random_state=13)
    customer_model = _fit_conformal_gbr(x, y_customer, random_state=17)

    base_policy, source = load_decision_policy(policy_config)
    dpol_base = base_policy.get("decision_policy", {})

    grid = _scenario_grid()
    if max_scenarios > 0 and len(grid) > max_scenarios:
        # Keep symmetric sampling with deterministic stride to balance coverage.
        stride = max(1, len(grid) // max_scenarios)
        grid = grid[::stride][:max_scenarios]

    candidates: list[dict[str, Any]] = []
    for sc in grid:
        patch = {
            "decision_policy": {
                "auto_release_min_confidence_delta": sc["auto_release_min_confidence_delta"],
                "max_avg_ratio_for_auto_release_delta": sc["max_avg_ratio_for_auto_release_delta"],
                "max_p95_ratio_for_auto_release_delta": sc["max_p95_ratio_for_auto_release_delta"],
            }
        }
        policy_cf = apply_policy_patch(base_policy, patch)
        dpol_cf = policy_cf.get("decision_policy", {})

        cf_rows: list[dict[str, Any]] = []
        decisions: list[str] = []
        for row in rows:
            cf = _counterfactual_transform_row(row, sc)
            avg_ratio = cf["avg_de_cf"] / max(1e-6, t_avg)
            p95_ratio = cf["p95_de_cf"] / max(1e-6, t_p95)
            max_ratio = cf["max_de_cf"] / max(1e-6, t_max)
            passed = bool(avg_ratio <= 1.0 and p95_ratio <= 1.0 and max_ratio <= 1.0)
            dc = _decision_one(
                confidence=cf["confidence_cf"],
                avg_ratio=avg_ratio,
                p95_ratio=p95_ratio,
                risk=cf["risk_cf"],
                passed=passed,
                decision_policy=dpol_cf,
            )
            cf["decision_code_cf"] = dc
            cf["passed_cf"] = passed
            cf["avg_ratio_cf"] = avg_ratio
            cf["p95_ratio_cf"] = p95_ratio
            cf["max_ratio_cf"] = max_ratio
            cf_rows.append(cf)
            decisions.append(dc)

        x_cf = _cf_feature_matrix(cf_rows)
        if bad_model is not None:
            bad_pred, bad_lo, bad_hi = bad_model.predict(x_cf)
            bad_pred = np.clip(bad_pred, 0.0, 1.0)
            bad_lo = np.clip(bad_lo, 0.0, 1.0)
            bad_hi = np.clip(bad_hi, 0.0, 1.0)
        else:
            base_bad = np.array([_clamp(_to_float(r["risk_cf"]) * (1.0 if r["decision_code_cf"] == "AUTO_RELEASE" else 0.4), 0.0, 1.0) for r in cf_rows], dtype=np.float64)
            bad_pred = base_bad
            bad_lo = np.clip(base_bad - 0.12, 0.0, 1.0)
            bad_hi = np.clip(base_bad + 0.12, 0.0, 1.0)

        if cost_model is not None:
            cost_pred, cost_lo, cost_hi = cost_model.predict(x_cf)
            cost_pred = np.maximum(cost_pred, 0.0)
            cost_lo = np.maximum(cost_lo, 0.0)
            cost_hi = np.maximum(cost_hi, 0.0)
        else:
            op = np.array(
                [
                    18.0 if r["decision_code_cf"] == "MANUAL_REVIEW" else 10.0 if r["decision_code_cf"] == "RECAPTURE_REQUIRED" else 138.0 if r["decision_code_cf"] == "HOLD_AND_ESCALATE" else 0.0
                    for r in cf_rows
                ],
                dtype=np.float64,
            )
            cost_pred = op + bad_pred * 350.0
            cost_lo = np.maximum(0.0, cost_pred - 45.0)
            cost_hi = cost_pred + 45.0

        if customer_model is not None:
            customer_pred, customer_lo, customer_hi = customer_model.predict(x_cf)
            customer_pred = np.clip(customer_pred, 0.0, 100.0)
            customer_lo = np.clip(customer_lo, 0.0, 100.0)
            customer_hi = np.clip(customer_hi, 0.0, 100.0)
        else:
            customer_pred = np.clip(100.0 - 72.0 * bad_pred, 0.0, 100.0)
            customer_lo = np.clip(customer_pred - 10.0, 0.0, 100.0)
            customer_hi = np.clip(customer_pred + 10.0, 0.0, 100.0)

        ds = _summarize_decisions(decisions)
        escape_rate = float(np.mean(bad_pred))
        escape_lo = float(np.mean(bad_lo))
        escape_hi = float(np.mean(bad_hi))
        cost_mean = float(np.mean(cost_pred))
        cost_lo_m = float(np.mean(cost_lo))
        cost_hi_m = float(np.mean(cost_hi))
        customer_mean = float(np.mean(customer_pred))
        customer_lo_m = float(np.mean(customer_lo))
        customer_hi_m = float(np.mean(customer_hi))
        throughput_idx = _clamp(100.0 * (ds["auto_release_rate"] + 0.74 * ds["manual_review_rate"] + 0.56 * ds["recapture_rate"] + 0.30 * (1.0 - ds["hold_rate"])), 0.0, 100.0)
        governance_idx = _clamp(100.0 - 130.0 * ds["hold_rate"] - 55.0 * escape_rate, 0.0, 100.0)
        boss_idx = _clamp(0.46 * throughput_idx + 0.34 * (100.0 - 100.0 * escape_rate) + 0.20 * _clamp(100.0 - cost_mean / 3.5, 0.0, 100.0), 0.0, 100.0)
        company_idx = _clamp(0.44 * customer_mean + 0.30 * governance_idx + 0.26 * (100.0 - 100.0 * escape_rate), 0.0, 100.0)

        objective = 0.48 * customer_mean + 0.28 * boss_idx + 0.24 * company_idx
        penalty = 0.0
        if escape_rate > 0.03:
            penalty += (escape_rate - 0.03) * 1400.0
        if customer_mean < 80:
            penalty += (80 - customer_mean) * 1.9
        if ds["hold_rate"] > 0.20:
            penalty += (ds["hold_rate"] - 0.20) * 380.0
        final_score = float(objective - penalty)

        metrics = {
            "auto_release_rate": ds["auto_release_rate"],
            "manual_review_rate": ds["manual_review_rate"],
            "recapture_rate": ds["recapture_rate"],
            "hold_rate": ds["hold_rate"],
            "expected_escape_rate": escape_rate,
            "expected_escape_rate_interval": [escape_lo, escape_hi],
            "expected_cost_per_run": cost_mean,
            "expected_cost_per_run_interval": [cost_lo_m, cost_hi_m],
            "customer_acceptance_index": customer_mean,
            "customer_acceptance_index_interval": [customer_lo_m, customer_hi_m],
            "throughput_index": throughput_idx,
            "boss_efficiency_index": boss_idx,
            "governance_index": governance_idx,
            "company_index": company_idx,
        }
        candidates.append(
            {
                "name": sc["name"],
                "final_score": final_score,
                "scenario_knobs": sc,
                "policy_patch": patch,
                "suggested_policy": policy_cf,
                "metrics": metrics,
                "constraints": {
                    "escape_rate_ok": bool(escape_rate <= 0.03),
                    "customer_index_ok": bool(customer_mean >= 80),
                    "hold_rate_ok": bool(ds["hold_rate"] <= 0.20),
                },
            }
        )

    candidates.sort(key=lambda x: _to_float(x["final_score"], -1e9), reverse=True)
    pareto = _pareto_front(candidates)

    def pick_customer_first(items: list[dict[str, Any]]) -> dict[str, Any] | None:
        valid = [x for x in items if x["constraints"]["escape_rate_ok"]]
        target = valid if valid else items
        return max(target, key=lambda x: _to_float(x["metrics"]["customer_acceptance_index"], 0.0), default=None)

    def pick_throughput_first(items: list[dict[str, Any]]) -> dict[str, Any] | None:
        valid = [x for x in items if _to_float(x["metrics"]["expected_escape_rate"], 1.0) <= 0.05]
        target = valid if valid else items
        return max(target, key=lambda x: _to_float(x["metrics"]["throughput_index"], 0.0), default=None)

    balanced = candidates[0] if candidates else None
    customer_first = pick_customer_first(candidates)
    throughput_first = pick_throughput_first(candidates)

    return {
        "enabled": True,
        "innovation": "counterfactual_color_twin_conformal",
        "base_policy_source": source,
        "run_count": len(runs),
        "outcome_count": len(outcomes),
        "joined_row_count": len(rows),
        "target_estimation": {
            "avg_target_est": t_avg,
            "p95_target_est": t_p95,
            "max_target_est": t_max,
        },
        "modeling": {
            "algorithm_stack": [
                "GradientBoostingRegressor",
                "Split Conformal Prediction",
                "Pareto Multi-objective Selection",
            ],
            "labels": {
                "bad_outcome_proxy": "complaint_major/return + severity mapping",
                "cost": "realized_cost or risk-derived fallback",
                "customer_index": "customer_rating or risk-derived fallback",
            },
            "scenario_count": len(candidates),
        },
        "pareto_front": pareto,
        "recommended": {
            "customer_first": customer_first,
            "balanced": balanced,
            "throughput_first": throughput_first,
        },
        "top_scenarios": candidates[:12],
        "notes": [
            "Use customer_first for key accounts and complaint-sensitive lines.",
            "Use balanced as default enterprise strategy.",
            "Use throughput_first only for low-risk SKUs with stable acceptance history.",
        ],
    }
