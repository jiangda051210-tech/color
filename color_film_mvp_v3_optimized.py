"""
Production-grade core color pipeline for decorative film quality control.
No third-party dependencies.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
import time
from dataclasses import dataclass, asdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _safe_mean(values: Sequence[float], default: float = 0.0) -> float:
    return statistics.mean(values) if values else default


def _percentile(values: Sequence[float], q: float) -> float:
    if not values:
        return 0.0
    v = sorted(values)
    if len(v) == 1:
        return float(v[0])
    p = _clamp(q, 0.0, 1.0) * (len(v) - 1)
    lo = int(math.floor(p))
    hi = int(math.ceil(p))
    if lo == hi:
        return float(v[lo])
    frac = p - lo
    return float(v[lo] * (1 - frac) + v[hi] * frac)


def _slug(text: str) -> str:
    out = []
    for ch in text.lower():
        if ch.isalnum() or ch in {"-", "_"}:
            out.append(ch)
        else:
            out.append("_")
    return "".join(out).strip("_")


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(float(x))


def _ensure_lab_dict(lab: Any) -> Optional[Dict[str, float]]:
    if not isinstance(lab, dict):
        return None
    out: Dict[str, float] = {}
    for key in ("L", "a", "b"):
        val = lab.get(key)
        if not _is_number(val):
            return None
        out[key] = float(val)
    return out


def _lab_physical_flags(lab: Dict[str, float]) -> List[str]:
    flags: List[str] = []
    if not (0.0 <= lab["L"] <= 100.0):
        flags.append("L_out_of_range")
    if not (-140.0 <= lab["a"] <= 140.0):
        flags.append("a_out_of_range")
    if not (-140.0 <= lab["b"] <= 140.0):
        flags.append("b_out_of_range")
    chroma = math.hypot(lab["a"], lab["b"])
    if chroma > 170.0:
        flags.append("chroma_out_of_range")
    return flags


def _srgb_to_linear(c: float) -> float:
    c = _clamp(c / 255.0, 0.0, 1.0)
    if c <= 0.04045:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(c: float) -> int:
    c = _clamp(c, 0.0, 1.0)
    if c <= 0.0031308:
        s = 12.92 * c
    else:
        s = 1.055 * (c ** (1.0 / 2.4)) - 0.055
    return int(round(_clamp(s * 255.0, 0.0, 255.0)))


def rgb_to_lab(r: float, g: float, b: float) -> Dict[str, float]:
    lr = _srgb_to_linear(r)
    lg = _srgb_to_linear(g)
    lb = _srgb_to_linear(b)
    x = lr * 0.4124564 + lg * 0.3575761 + lb * 0.1804375
    y = lr * 0.2126729 + lg * 0.7151522 + lb * 0.0721750
    z = lr * 0.0193339 + lg * 0.1191920 + lb * 0.9503041

    def f(t: float) -> float:
        if t > 0.008856:
            return t ** (1.0 / 3.0)
        return 7.787 * t + 16.0 / 116.0

    fx = f(x / 0.95047)
    fy = f(y)
    fz = f(z / 1.08883)
    return {"L": 116.0 * fy - 16.0, "a": 500.0 * (fx - fy), "b": 200.0 * (fy - fz)}


def de2000(lab1: Dict[str, float], lab2: Dict[str, float]) -> Dict[str, float]:
    l1, a1, b1 = lab1["L"], lab1["a"], lab1["b"]
    l2, a2, b2 = lab2["L"], lab2["a"], lab2["b"]

    c1 = math.hypot(a1, b1)
    c2 = math.hypot(a2, b2)
    c_bar = (c1 + c2) / 2.0
    g = 0.5 * (1.0 - math.sqrt((c_bar**7) / (c_bar**7 + 25.0**7)))
    a1p = (1.0 + g) * a1
    a2p = (1.0 + g) * a2
    c1p = math.hypot(a1p, b1)
    c2p = math.hypot(a2p, b2)

    h1p = math.degrees(math.atan2(b1, a1p)) % 360.0
    h2p = math.degrees(math.atan2(b2, a2p)) % 360.0

    dl = l2 - l1
    dc = c2p - c1p

    if c1p * c2p == 0:
        dhp = 0.0
    else:
        delta = h2p - h1p
        if abs(delta) <= 180.0:
            dhp = delta
        elif delta > 180.0:
            dhp = delta - 360.0
        else:
            dhp = delta + 360.0
    dh = 2.0 * math.sqrt(c1p * c2p) * math.sin(math.radians(dhp) / 2.0)

    l_bar = (l1 + l2) / 2.0
    c_bar_p = (c1p + c2p) / 2.0

    if c1p * c2p == 0:
        h_bar = h1p + h2p
    else:
        delta_h = abs(h1p - h2p)
        if delta_h <= 180.0:
            h_bar = (h1p + h2p) / 2.0
        elif h1p + h2p < 360.0:
            h_bar = (h1p + h2p + 360.0) / 2.0
        else:
            h_bar = (h1p + h2p - 360.0) / 2.0

    t = (
        1.0
        - 0.17 * math.cos(math.radians(h_bar - 30.0))
        + 0.24 * math.cos(math.radians(2.0 * h_bar))
        + 0.32 * math.cos(math.radians(3.0 * h_bar + 6.0))
        - 0.20 * math.cos(math.radians(4.0 * h_bar - 63.0))
    )
    sl = 1.0 + (0.015 * (l_bar - 50.0) ** 2) / math.sqrt(20.0 + (l_bar - 50.0) ** 2)
    sc = 1.0 + 0.045 * c_bar_p
    sh = 1.0 + 0.015 * c_bar_p * t
    rt = -2.0 * math.sqrt((c_bar_p**7) / (c_bar_p**7 + 25.0**7)) * math.sin(
        math.radians(60.0 * math.exp(-((h_bar - 275.0) / 25.0) ** 2))
    )
    vl = dl / sl
    vc = dc / sc
    vh = dh / sh
    total = math.sqrt(max(0.0, vl * vl + vc * vc + vh * vh + rt * vc * vh))

    return {
        "total": round(total, 4),
        "dL": round(vl, 4),
        "dC": round(vc, 4),
        "dH": round(vh, 4),
        "raw_dL": round(dl, 4),
        "raw_da": round(a2 - a1, 4),
        "raw_db": round(b2 - b1, 4),
    }


def _mat3_inv(m: List[List[float]]) -> Optional[List[List[float]]]:
    if len(m) != 3 or any(len(row) != 3 for row in m):
        return None
    aug = [
        [float(m[0][0]), float(m[0][1]), float(m[0][2]), 1.0, 0.0, 0.0],
        [float(m[1][0]), float(m[1][1]), float(m[1][2]), 0.0, 1.0, 0.0],
        [float(m[2][0]), float(m[2][1]), float(m[2][2]), 0.0, 0.0, 1.0],
    ]
    for col in range(3):
        pivot = max(range(col, 3), key=lambda r: abs(aug[r][col]))
        if abs(aug[pivot][col]) < 1e-12:
            return None
        if pivot != col:
            aug[col], aug[pivot] = aug[pivot], aug[col]
        div = aug[col][col]
        for c in range(6):
            aug[col][c] /= div
        for r in range(3):
            if r == col:
                continue
            factor = aug[r][col]
            for c in range(6):
                aug[r][c] -= factor * aug[col][c]
    return [[aug[r][3], aug[r][4], aug[r][5]] for r in range(3)]


def _mat3_vec_mul(m: List[List[float]], v: Sequence[float]) -> List[float]:
    return [
        m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
        m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
        m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2],
    ]


@dataclass(frozen=True)
class ThresholdProfile:
    pass_avg: float = 1.0
    pass_p95: float = 2.0
    pass_max: float = 2.4
    marginal_avg: float = 2.5
    marginal_p95: float = 3.6
    marginal_max: float = 4.5
    local_hotspot_limit: float = 4.0
    local_hotspot_ratio_limit: float = 0.08
    suspicious_data_limit: float = 0.10
    visual_pass_probability: float = 0.65
    visual_hold_probability: float = 0.45


class ThresholdPolicyEngine:
    def __init__(self) -> None:
        self._base = ThresholdProfile()
        self._tier_multipliers = {"vip": 0.85, "standard": 1.0, "growth": 1.08, "economy": 1.18}
        self._application_multipliers = {"exterior": 0.90, "interior": 1.0, "premium": 0.88, "industrial": 1.05}
        self._policy_version = "POLICY-2026.04-R2"

    def resolve(self, meta: Dict[str, Any], overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        tier = _slug(str(meta.get("customer_tier", "standard"))) or "standard"
        app = _slug(str(meta.get("application", "interior"))) or "interior"
        sku = _slug(str(meta.get("sku_class", "")))

        k_tier = self._tier_multipliers.get(tier, 1.0)
        k_app = self._application_multipliers.get(app, 1.0)
        k_sku = 0.92 if ("high_gloss" in sku or "transparent" in sku) else 1.05 if ("matte" in sku or "embossed" in sku) else 1.0
        k = k_tier * k_app * k_sku

        # Customer/SKU/application specific runtime tightening/loosening.
        for extra_key in (
            "tolerance_scale",
            "customer_tolerance_scale",
            "sku_tolerance_scale",
            "application_tolerance_scale",
        ):
            if _is_number(meta.get(extra_key)):
                k *= max(0.5, min(1.5, float(meta[extra_key])))
        if _is_number(meta.get("complaint_history_bias")):
            # Positive bias means frequent complaints -> tighten.
            bias = float(meta["complaint_history_bias"])
            k *= max(0.75, min(1.25, 1.0 - bias * 0.15))

        b = self._base
        profile = ThresholdProfile(
            pass_avg=round(b.pass_avg * k, 3),
            pass_p95=round(b.pass_p95 * k, 3),
            pass_max=round(b.pass_max * k, 3),
            marginal_avg=round(b.marginal_avg * k, 3),
            marginal_p95=round(b.marginal_p95 * k, 3),
            marginal_max=round(b.marginal_max * k, 3),
            local_hotspot_limit=round(b.local_hotspot_limit * k, 3),
            local_hotspot_ratio_limit=b.local_hotspot_ratio_limit,
            suspicious_data_limit=b.suspicious_data_limit,
            visual_pass_probability=b.visual_pass_probability,
            visual_hold_probability=b.visual_hold_probability,
        )
        if overrides and isinstance(overrides, dict):
            data = asdict(profile)
            for key, value in overrides.items():
                if key in data and _is_number(value):
                    data[key] = float(value)
            profile = ThresholdProfile(**data)
        return {
            "profile": profile,
            "tier": tier,
            "application": app,
            "sku_class": sku,
            "policy_factor": round(k, 4),
            "policy_version": self._policy_version,
            "policy_source": "heuristic+runtime",
        }


class RuleGovernanceCenter:
    """
    Centralized rule governance:
    - versioned packs
    - active time
    - scope matching (customer/sku/machine)
    - replay support
    """

    def __init__(self) -> None:
        self._packs: List[Dict[str, Any]] = []
        self.register_rule_pack(
            version="RULE-2026.04-R2",
            active_from_ts=0.0,
            scope={},
            threshold_overrides={},
            model_version="MODEL-COLOR-V3.2",
            notes="production baseline",
        )

    @staticmethod
    def _scope_match(scope: Dict[str, Any], meta: Dict[str, Any]) -> bool:
        if not scope:
            return True
        customer_id = str(meta.get("customer_id", ""))
        sku = str(meta.get("product_code", meta.get("sku", "")))
        machine_id = str(meta.get("machine_id", ""))
        if scope.get("customer_ids") and customer_id not in set(scope["customer_ids"]):
            return False
        if scope.get("machine_ids") and machine_id not in set(scope["machine_ids"]):
            return False
        if scope.get("sku_prefixes"):
            prefixes = [str(x) for x in scope["sku_prefixes"]]
            if not any(sku.startswith(p) for p in prefixes):
                return False
        return True

    def register_rule_pack(
        self,
        version: str,
        active_from_ts: float,
        scope: Optional[Dict[str, Any]] = None,
        threshold_overrides: Optional[Dict[str, Any]] = None,
        model_version: str = "MODEL-COLOR-V3",
        notes: str = "",
    ) -> Dict[str, Any]:
        row = {
            "version": str(version),
            "active_from_ts": float(active_from_ts),
            "scope": dict(scope or {}),
            "threshold_overrides": dict(threshold_overrides or {}),
            "model_version": str(model_version),
            "notes": str(notes),
            "registered_at": _now_iso(),
        }
        self._packs.append(row)
        self._packs.sort(key=lambda x: x["active_from_ts"])
        return {"registered": True, "version": row["version"], "count": len(self._packs)}

    def resolve(self, meta: Dict[str, Any], at_ts: Optional[float] = None, force_version: Optional[str] = None) -> Dict[str, Any]:
        ts = float(at_ts if at_ts is not None else time.time())
        if force_version:
            rows = [x for x in self._packs if x["version"] == force_version]
            if rows:
                pack = rows[-1]
                return {"rule_pack": pack, "resolved_by": "force_version"}
        candidates = [x for x in self._packs if x["active_from_ts"] <= ts and self._scope_match(x["scope"], meta)]
        if not candidates:
            pack = self._packs[0]
        else:
            pack = candidates[-1]
        return {"rule_pack": pack, "resolved_by": "time+scope"}

    def list_rule_packs(self) -> List[Dict[str, Any]]:
        return list(self._packs)


class InputQualityGuard:
    def validate_grid(
        self,
        ref_grid: Any,
        sample_grid: Any,
        grid_shape: Tuple[int, int],
        measurement_ids: Optional[Sequence[str]] = None,
        measurement_timestamps: Optional[Sequence[float]] = None,
    ) -> Dict[str, Any]:
        errors: List[str] = []
        warnings: List[str] = []

        rows, cols = grid_shape
        if rows <= 0 or cols <= 0:
            return {"valid": False, "errors": ["invalid_grid_shape"], "warnings": []}

        expected_n = rows * cols
        if not isinstance(ref_grid, list) or not isinstance(sample_grid, list):
            return {"valid": False, "errors": ["grid_not_list"], "warnings": []}
        if len(ref_grid) != len(sample_grid):
            errors.append("grid_count_mismatch")
        if len(ref_grid) != expected_n:
            errors.append("grid_shape_count_mismatch")
        if len(ref_grid) < 12:
            errors.append("insufficient_sampling_points")

        ref_ok: List[Dict[str, float]] = []
        sample_ok: List[Dict[str, float]] = []
        physical_flags = 0
        for idx, (r, s) in enumerate(zip(ref_grid, sample_grid)):
            r_lab = _ensure_lab_dict(r)
            s_lab = _ensure_lab_dict(s)
            if r_lab is None or s_lab is None:
                errors.append(f"non_numeric_lab_at_{idx}")
                continue
            flags = _lab_physical_flags(r_lab) + _lab_physical_flags(s_lab)
            if flags:
                physical_flags += 1
                warnings.append(f"physical_range_warning_at_{idx}")
            ref_ok.append(r_lab)
            sample_ok.append(s_lab)

        suspicious_count = 0
        for r_lab, s_lab in zip(ref_ok, sample_ok):
            if de2000(r_lab, s_lab)["total"] > 15.0:
                suspicious_count += 1
        suspicious_ratio = suspicious_count / len(ref_ok) if ref_ok else 1.0
        if suspicious_ratio > 0.2:
            warnings.append("suspicious_high_deltae_ratio")

        duplicate_ids = 0
        if measurement_ids:
            seen = set()
            for mid in measurement_ids:
                key = str(mid)
                if key in seen:
                    duplicate_ids += 1
                seen.add(key)
            if duplicate_ids:
                warnings.append(f"duplicate_measurement_ids:{duplicate_ids}")

        ts_issues = 0
        if measurement_timestamps and len(measurement_timestamps) > 1:
            prev = float(measurement_timestamps[0])
            for val in measurement_timestamps[1:]:
                cur = float(val)
                if cur < prev:
                    ts_issues += 1
                prev = cur
            if ts_issues:
                warnings.append(f"timestamp_disorder:{ts_issues}")

        return {
            "valid": not errors,
            "errors": errors,
            "warnings": sorted(set(warnings)),
            "physical_flag_points": physical_flags,
            "suspicious_ratio": round(suspicious_ratio, 4),
            "duplicate_measurement_ids": duplicate_ids,
            "timestamp_disorder_count": ts_issues,
            "clean_ref_grid": ref_ok,
            "clean_sample_grid": sample_ok,
        }

class ColorCorrectionEngineV3:
    COLORCHECKER_SRGB: List[Tuple[int, int, int]] = [
        (115, 82, 68), (194, 150, 130), (98, 122, 157), (87, 108, 67),
        (133, 128, 177), (103, 189, 170), (214, 126, 44), (80, 91, 166),
        (193, 90, 99), (94, 60, 108), (157, 188, 64), (224, 163, 46),
        (56, 61, 150), (70, 148, 73), (175, 54, 60), (231, 199, 31),
        (187, 86, 149), (8, 133, 161), (243, 243, 242), (200, 200, 200),
        (160, 160, 160), (122, 122, 121), (85, 85, 85), (52, 52, 52),
    ]

    def __init__(self) -> None:
        self._ccm: Optional[List[List[float]]] = None
        self._rmse: Optional[float] = None
        self._calibrated = False

    def calibrate(self, measured_rgb_24: Sequence[Sequence[float]]) -> Dict[str, Any]:
        if not isinstance(measured_rgb_24, (list, tuple)) or len(measured_rgb_24) != 24:
            return {"status": "error", "message": "measured_rgb_24 must have exactly 24 patches"}

        x: List[List[float]] = []
        y: List[List[float]] = []
        for i in range(24):
            m = measured_rgb_24[i]
            if not isinstance(m, (list, tuple)) or len(m) != 3:
                return {"status": "error", "message": f"invalid patch at index {i}"}
            if not all(_is_number(v) for v in m):
                return {"status": "error", "message": f"non-numeric patch at index {i}"}
            mr, mg, mb = [float(v) for v in m]
            if not (0.0 <= mr <= 255.0 and 0.0 <= mg <= 255.0 and 0.0 <= mb <= 255.0):
                return {"status": "error", "message": f"patch {i} out of 0..255 range"}
            tr, tg, tb = self.COLORCHECKER_SRGB[i]
            x.append([_srgb_to_linear(mr), _srgb_to_linear(mg), _srgb_to_linear(mb)])
            y.append([_srgb_to_linear(tr), _srgb_to_linear(tg), _srgb_to_linear(tb)])

        xtx = [[0.0, 0.0, 0.0] for _ in range(3)]
        for row in x:
            for i in range(3):
                for j in range(3):
                    xtx[i][j] += row[i] * row[j]
        inv = _mat3_inv(xtx)
        if inv is None:
            return {"status": "error", "message": "singular matrix in calibration"}

        ccm = [[0.0, 0.0, 0.0] for _ in range(3)]
        for out_ch in range(3):
            xty = [0.0, 0.0, 0.0]
            for row, yy in zip(x, y):
                for i in range(3):
                    xty[i] += row[i] * yy[out_ch]
            ccm[out_ch] = _mat3_vec_mul(inv, xty)

        self._ccm = ccm
        self._calibrated = True
        sqe: List[float] = []
        for row, target in zip(x, y):
            pred = self.apply_ccm_linear(row)
            for i in range(3):
                sqe.append((pred[i] - target[i]) ** 2)
        rmse = math.sqrt(_safe_mean(sqe))
        self._rmse = rmse
        return {
            "status": "ok",
            "ccm": [[round(v, 6) for v in row] for row in ccm],
            "rmse_linear": round(rmse, 6),
            "quality": "excellent" if rmse < 0.01 else "good" if rmse < 0.03 else "acceptable" if rmse < 0.05 else "poor",
            "patches_used": 24,
        }

    def apply_ccm_linear(self, linear_rgb: Sequence[float]) -> List[float]:
        if self._ccm is None:
            return [float(linear_rgb[0]), float(linear_rgb[1]), float(linear_rgb[2])]
        out = _mat3_vec_mul(self._ccm, linear_rgb)
        return [_clamp(v, 0.0, 1.0) for v in out]

    def correct_rgb(self, r: float, g: float, b: float) -> Tuple[int, int, int]:
        lin = [_srgb_to_linear(r), _srgb_to_linear(g), _srgb_to_linear(b)]
        corr = self.apply_ccm_linear(lin)
        return (_linear_to_srgb(corr[0]), _linear_to_srgb(corr[1]), _linear_to_srgb(corr[2]))

    def correct_to_lab(self, r: float, g: float, b: float) -> Dict[str, float]:
        cr, cg, cb = self.correct_rgb(r, g, b)
        return rgb_to_lab(cr, cg, cb)

    def validate(self) -> Dict[str, Any]:
        if not self._calibrated:
            return {"valid": False, "message": "ccm_not_calibrated"}
        rmse = float(self._rmse or 0.0)
        return {"valid": True, "rmse_linear": round(rmse, 6), "quality": "excellent" if rmse < 0.01 else "good" if rmse < 0.03 else "marginal"}


class ThreeStepMatcherV3:
    def evaluate_match(self, match_result: Dict[str, Any]) -> Dict[str, Any]:
        method = str(match_result.get("method", "unknown")).lower()
        inlier_ratio = float(match_result.get("inlier_ratio", 0.0) or 0.0)
        ncc = float(match_result.get("ncc_score", 0.0) or 0.0)
        reproj = float(match_result.get("reprojection_error", match_result.get("reproj_error", 999.0)) or 999.0)
        inlier_count = int(match_result.get("inlier_count", 0) or 0)

        score = 0.0
        reasons: List[str] = []
        if method == "aruco":
            score = 0.95
            reasons.append("aruco_direct_alignment")
        elif method == "orb_ransac":
            score += 0.4 if inlier_ratio > 0.5 else 0.25 if inlier_ratio > 0.3 else 0.05
            score += 0.3 if ncc > 0.9 else 0.2 if ncc > 0.8 else 0.05
            score += 0.2 if reproj < 2.0 else 0.1 if reproj < 4.0 else 0.0
            score += 0.1 if inlier_count >= 35 else 0.0
            reasons.append("orb_ransac_estimation")
        elif method == "manual":
            score = 0.58
            reasons.append("manual_roi")
        else:
            reasons.append("unknown_method")

        score = _clamp(score, 0.0, 1.0)
        confidence = "high" if score >= 0.75 else "medium" if score >= 0.45 else "low"
        warnings: List[str] = []
        scale = match_result.get("scale_factor")
        if _is_number(scale) and abs(float(scale) - 1.0) > 0.05:
            warnings.append("scale_deviation_gt_5pct")
        rot = match_result.get("rotation_deg")
        if _is_number(rot) and abs(float(rot)) > 2.0:
            warnings.append("rotation_deviation_gt_2deg")
        return {
            "score": round(score, 4),
            "confidence": confidence,
            "usable": score >= 0.35,
            "reasons": reasons,
            "warnings": warnings,
            "recommendation": "alignment_ok" if score >= 0.75 else "alignment_usable_manual_verify" if score >= 0.45 else "alignment_retry_or_aruco",
        }

    def suggest_strategy(self, scene: Dict[str, Any]) -> Dict[str, Any]:
        has_aruco = bool(scene.get("has_aruco"))
        pattern = _slug(str(scene.get("pattern_type", "random")))
        sku_count = int(scene.get("sku_count", 999) or 999)
        if has_aruco:
            return {"strategy": "ARUCO_DIRECT", "reliability": "high", "steps": ["detect_markers", "homography", "perspective_warp", "roi_crop"]}
        if pattern in {"repeating", "wood_grain", "texture_repeat"}:
            return {"strategy": "ORB_RANSAC_NCC", "reliability": "medium_high", "steps": ["feature_match", "ransac", "ncc_refine", "roi_crop"], "risk": "periodic_pattern_false_match"}
        if sku_count <= 80:
            return {"strategy": "TEMPLATE_LIBRARY", "reliability": "high", "steps": ["load_template", "coarse_match", "ncc_refine", "roi_crop"]}
        return {"strategy": "MANUAL_ROI_FALLBACK", "reliability": "operator_dependent", "steps": ["operator_select_roi", "double_check_overlay"]}


class GridAnalyzer:
    @staticmethod
    def _neighbors(idx: int, rows: int, cols: int) -> Iterable[int]:
        r = idx // cols
        c = idx % cols
        if r > 0:
            yield (r - 1) * cols + c
        if r < rows - 1:
            yield (r + 1) * cols + c
        if c > 0:
            yield r * cols + (c - 1)
        if c < cols - 1:
            yield r * cols + (c + 1)

    def analyze(self, ref_grid: List[Dict[str, float]], sample_grid: List[Dict[str, float]], grid_shape: Tuple[int, int], hotspot_threshold: float) -> Dict[str, Any]:
        rows, cols = grid_shape
        n = len(ref_grid)
        des: List[float] = []
        dls: List[float] = []
        das: List[float] = []
        dbs: List[float] = []
        point_components: List[Dict[str, float]] = []
        for r, s in zip(ref_grid, sample_grid):
            d = de2000(r, s)
            des.append(float(d["total"]))
            dls.append(float(d["raw_dL"]))
            das.append(float(d["raw_da"]))
            dbs.append(float(d["raw_db"]))
            point_components.append(d)

        avg_de = _safe_mean(des)
        p95 = _percentile(des, 0.95)
        p99 = _percentile(des, 0.99)
        mx = max(des) if des else 0.0
        std = statistics.stdev(des) if len(des) >= 2 else 0.0

        hotspot_indices = [i for i, de in enumerate(des) if de >= hotspot_threshold]
        hotspot_ratio = len(hotspot_indices) / n if n else 0.0
        hotspot_set = set(hotspot_indices)
        visited: set[int] = set()
        clusters: List[List[int]] = []
        for idx in hotspot_indices:
            if idx in visited:
                continue
            stack = [idx]
            visited.add(idx)
            cluster: List[int] = []
            while stack:
                cur = stack.pop()
                cluster.append(cur)
                for nb in self._neighbors(cur, rows, cols):
                    if nb in hotspot_set and nb not in visited:
                        visited.add(nb)
                        stack.append(nb)
            clusters.append(sorted(cluster))

        largest_cluster = max((len(c) for c in clusters), default=0)
        worst_idx = max(range(len(des)), key=lambda i: des[i]) if des else None
        worst_point = {
            "index": int(worst_idx),
            "de": round(des[worst_idx], 4),
            "dL": round(point_components[worst_idx]["raw_dL"], 4),
            "da": round(point_components[worst_idx]["raw_da"], 4),
            "db": round(point_components[worst_idx]["raw_db"], 4),
        } if worst_idx is not None else None

        center_vals: List[float] = []
        edge_vals: List[float] = []
        for i, de in enumerate(des):
            rr = i // cols
            cc = i % cols
            if rr in {0, rows - 1} or cc in {0, cols - 1}:
                edge_vals.append(de)
            else:
                center_vals.append(de)
        edge_avg = _safe_mean(edge_vals)
        center_avg = _safe_mean(center_vals)

        zone_data: Dict[str, List[float]] = {"head": [], "middle": [], "tail": []}
        for i, de in enumerate(des):
            rr = i // cols
            if rr < rows / 3.0:
                zone_data["head"].append(de)
            elif rr < rows * 2.0 / 3.0:
                zone_data["middle"].append(de)
            else:
                zone_data["tail"].append(de)

        return {
            "global": {
                "count": n,
                "avg_de": round(avg_de, 4),
                "p50_de": round(_percentile(des, 0.50), 4),
                "p90_de": round(_percentile(des, 0.90), 4),
                "p95_de": round(p95, 4),
                "p99_de": round(p99, 4),
                "max_de": round(mx, 4),
                "std_de": round(std, 4),
                "avg_dL": round(_safe_mean(dls), 4),
                "avg_da": round(_safe_mean(das), 4),
                "avg_db": round(_safe_mean(dbs), 4),
            },
            "local": {
                "hotspot_threshold": round(hotspot_threshold, 4),
                "hotspot_count": len(hotspot_indices),
                "hotspot_ratio": round(hotspot_ratio, 4),
                "largest_hotspot_cluster": largest_cluster,
                "hotspot_indices_preview": hotspot_indices[:20],
                "worst_point": worst_point,
            },
            "uniformity": {
                "edge_avg_de": round(edge_avg, 4),
                "center_avg_de": round(center_avg, 4),
                "edge_center_diff": round(edge_avg - center_avg, 4),
                "edge_effect_risk": abs(edge_avg - center_avg) > 0.5,
            },
            "roll_segments": {z: round(_safe_mean(v), 4) for z, v in zone_data.items()},
            "heatmap": [round(v, 4) for v in des],
            "components": point_components,
            "clusters": clusters[:50],
        }


class VisualAcceptabilityModel:
    def predict(self, metrics: Dict[str, Any], meta: Dict[str, Any]) -> Dict[str, Any]:
        g = metrics["global"]
        u = metrics["uniformity"]
        texture = _slug(str(meta.get("texture_type", "normal")))
        transparent = bool(meta.get("is_transparent_film", False))
        z = 3.1
        z -= 1.1 * g["avg_de"]
        z -= 0.55 * g["p95_de"]
        z -= 0.35 * g["max_de"]
        z -= 0.9 * abs(u["edge_center_diff"])
        if texture in {"wood", "stone", "embossed"}:
            z += 0.25
        if transparent:
            z -= 0.25
        p = 1.0 / (1.0 + math.exp(-z))
        return {
            "probability": round(_clamp(p, 0.0, 1.0), 4),
            "model": "logistic_v1",
            "factors": {
                "avg_de": g["avg_de"],
                "p95_de": g["p95_de"],
                "max_de": g["max_de"],
                "edge_center_diff": u["edge_center_diff"],
                "texture_type": texture,
                "transparent": transparent,
            },
        }


class RootCauseEngine:
    def classify(self, metrics: Dict[str, Any], data_quality: Dict[str, Any]) -> Dict[str, Any]:
        if not data_quality["valid"]:
            return {"type": "data_quality", "summary": "invalid_measurement_input", "evidence": data_quality["errors"], "confidence": "high"}
        if data_quality["suspicious_ratio"] > 0.2:
            return {"type": "data_quality", "summary": "high_suspicious_ratio", "evidence": [f"suspicious_ratio={data_quality['suspicious_ratio']}"], "confidence": "high"}

        g = metrics["global"]
        l = metrics["local"]
        u = metrics["uniformity"]
        bias_mag = math.hypot(g["avg_da"], g["avg_db"])

        if g["std_de"] < 0.35 and l["hotspot_ratio"] < 0.04 and abs(u["edge_center_diff"]) < 0.35:
            return {"type": "recipe", "summary": "uniform_global_bias_recipe_likely", "evidence": [f"std_de={g['std_de']}", f"avg_bias_mag={round(bias_mag,4)}"], "confidence": "high"}
        if l["hotspot_ratio"] > 0.08 or g["std_de"] > 0.75 or abs(u["edge_center_diff"]) > 0.6:
            return {
                "type": "process",
                "summary": "spatial_nonuniformity_process_likely",
                "evidence": [f"hotspot_ratio={l['hotspot_ratio']}", f"std_de={g['std_de']}", f"edge_center_diff={u['edge_center_diff']}"],
                "confidence": "high",
            }
        return {"type": "mixed", "summary": "mixed_recipe_and_process_risk", "evidence": [f"avg_de={g['avg_de']}", f"std_de={g['std_de']}"], "confidence": "medium"}


class HardGateEngine:
    """
    Defines hard boundaries where automatic release is not allowed.
    """

    def evaluate(
        self,
        data_quality: Dict[str, Any],
        visual: Dict[str, Any],
        root_cause: Dict[str, Any],
        gate_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        ctx = dict(gate_context or {})
        hard_blocks: List[str] = []
        review_triggers: List[str] = []
        arbitration_triggers: List[str] = []

        if not data_quality.get("valid", False):
            hard_blocks.append("invalid_input_data")
        if float(data_quality.get("suspicious_ratio", 0.0)) > 0.25:
            hard_blocks.append("suspicious_data_ratio_high")

        if int(ctx.get("calibration_overdue_count", 0) or 0) > 0:
            hard_blocks.append("calibration_overdue")
        if ctx.get("trace_integrity") is False:
            hard_blocks.append("trace_integrity_broken")
        if int(ctx.get("trace_missing_required", 0) or 0) > 0:
            hard_blocks.append("trace_missing_required_stage")
        if str(ctx.get("golden_status", "")).lower() in {"replace_now", "expired"}:
            hard_blocks.append("golden_sample_invalid")

        if float(ctx.get("environment_severity", 0.0) or 0.0) >= 0.65:
            review_triggers.append("environment_severity_high")
        if float(ctx.get("repeatability_std", 0.0) or 0.0) >= 0.35:
            review_triggers.append("repeatability_poor")
        if str(ctx.get("retest_conflict", "")).lower() in {"high", "critical"}:
            arbitration_triggers.append("retest_conflict_high")
        if root_cause.get("type") == "data_quality":
            arbitration_triggers.append("root_cause_data_quality")
        if float(visual.get("probability", 0.5)) < 0.25:
            review_triggers.append("visual_acceptance_low")

        auto_release_allowed = len(hard_blocks) == 0 and len(arbitration_triggers) == 0 and len(review_triggers) == 0
        manual_review_required = (len(review_triggers) > 0) and len(arbitration_triggers) == 0 and len(hard_blocks) == 0
        manual_arbitration_required = len(arbitration_triggers) > 0 or len(hard_blocks) > 0
        return {
            "auto_release_allowed": auto_release_allowed,
            "manual_review_required": manual_review_required,
            "manual_arbitration_required": manual_arbitration_required,
            "hard_blocks": sorted(set(hard_blocks)),
            "review_triggers": sorted(set(review_triggers)),
            "arbitration_triggers": sorted(set(arbitration_triggers)),
        }


class BusinessCostEngine:
    """
    Balances quality risk with business consequence, without hiding quality facts.
    """

    def plan(
        self,
        decision: Dict[str, Any],
        hard_gate: Dict[str, Any],
        meta: Dict[str, Any],
    ) -> Dict[str, Any]:
        costs = {
            "false_release_cost": float(meta.get("false_release_cost", 22000.0)),
            "false_reject_cost": float(meta.get("false_reject_cost", 7000.0)),
            "remeasure_cost": float(meta.get("remeasure_cost", 600.0)),
            "rework_cost": float(meta.get("rework_cost", 5000.0)),
            "scrap_cost": float(meta.get("scrap_cost", 14000.0)),
            "customer_confirm_cost": float(meta.get("customer_confirm_cost", 1200.0)),
        }
        urgency = _slug(str(meta.get("order_urgency", "normal")))
        inventory = _slug(str(meta.get("inventory_status", "normal")))
        customer_tier = _slug(str(meta.get("customer_tier", "standard")))

        urgency_factor = 1.25 if urgency in {"urgent", "critical"} else 1.0
        customer_factor = 1.25 if customer_tier == "vip" else 1.0
        inventory_factor = 0.9 if inventory in {"short", "critical_low"} else 1.0

        # Candidate dispositions.
        options: List[Dict[str, Any]] = []
        options.append({"action": "remeasure", "cost": costs["remeasure_cost"]})
        options.append({"action": "rework", "cost": costs["rework_cost"] * inventory_factor})
        options.append({"action": "customer_confirm", "cost": costs["customer_confirm_cost"] * urgency_factor})
        options.append({"action": "scrap", "cost": costs["scrap_cost"]})

        if decision.get("tier") == "PASS" and hard_gate.get("auto_release_allowed", False):
            options.append({"action": "release", "cost": 0.0})
        else:
            # Risk cost proxy if still release under uncertain conditions.
            risk_release = costs["false_release_cost"] * urgency_factor * customer_factor
            options.append({"action": "release_with_risk", "cost": risk_release})

        # Constrained by hard gate boundary.
        if not hard_gate.get("auto_release_allowed", False):
            options = [x for x in options if x["action"] not in {"release", "release_with_risk"}]
        if hard_gate.get("manual_arbitration_required", False):
            options = [x for x in options if x["action"] in {"remeasure", "rework", "scrap", "customer_confirm"}]

        best = min(options, key=lambda x: x["cost"]) if options else {"action": "manual_arbitration", "cost": 999999.0}
        consequence_level = (
            "critical"
            if decision.get("tier") == "FAIL" or hard_gate.get("manual_arbitration_required", False)
            else "high"
            if decision.get("tier") == "MARGINAL"
            else "medium"
            if hard_gate.get("manual_review_required", False)
            else "low"
        )
        return {
            "recommended_action": best["action"],
            "estimated_min_cost": round(float(best["cost"]), 2),
            "consequence_level": consequence_level,
            "options": [{"action": x["action"], "cost": round(float(x["cost"]), 2)} for x in sorted(options, key=lambda z: z["cost"])],
            "context": {
                "order_urgency": urgency,
                "customer_tier": customer_tier,
                "inventory_status": inventory,
            },
        }

class DecisionArbitrator:
    def arbitrate(
        self,
        metrics: Dict[str, Any],
        visual: Dict[str, Any],
        data_quality: Dict[str, Any],
        root_cause: Dict[str, Any],
        profile: ThresholdProfile,
        hard_gate: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        reasons: List[str] = []
        conflicts: List[str] = []
        hard_gate = dict(hard_gate or {})

        if not data_quality["valid"]:
            return {
                "tier": "HOLD",
                "tier_cn": "待复测",
                "decision_code": "DATA_INVALID",
                "confidence": 0.98,
                "reasons": data_quality["errors"],
                "conflict_resolution": [],
                "decision_mode": "manual_arbitration",
                "auto_release_allowed": False,
            }

        g = metrics["global"]
        l = metrics["local"]
        visual_prob = visual["probability"]

        if g["avg_de"] <= profile.pass_avg and g["p95_de"] <= profile.pass_p95 and g["max_de"] <= profile.pass_max:
            tier = "PASS"
            code = "NUMERIC_PASS"
        elif g["avg_de"] <= profile.marginal_avg and g["p95_de"] <= profile.marginal_p95 and g["max_de"] <= profile.marginal_max:
            tier = "MARGINAL"
            code = "NUMERIC_MARGINAL"
        else:
            tier = "FAIL"
            code = "NUMERIC_FAIL"

        reasons.append(f"avg/p95/max={g['avg_de']}/{g['p95_de']}/{g['max_de']}")

        if l["hotspot_count"] > 0 and (
            g["max_de"] > profile.local_hotspot_limit
            or l["hotspot_ratio"] > profile.local_hotspot_ratio_limit
            or l["largest_hotspot_cluster"] >= 3
        ):
            if tier == "PASS":
                tier = "MARGINAL"
                code = "LOCAL_HOTSPOT_OVERRIDE"
            elif tier == "MARGINAL":
                tier = "FAIL"
                code = "LOCAL_HOTSPOT_ESCALATION"
            reasons.append("local_hotspot_override")

        if data_quality["suspicious_ratio"] > profile.suspicious_data_limit:
            if tier == "PASS":
                tier = "MARGINAL"
                code = "SUSPICIOUS_DATA_HOLD"
            conflicts.append("data_suspicious_vs_numeric_ok")
            reasons.append(f"suspicious_ratio={data_quality['suspicious_ratio']}")

        if tier == "FAIL" and visual_prob >= profile.visual_pass_probability:
            fail_ratio = max(
                g["avg_de"] / max(profile.marginal_avg, 1e-6),
                g["p95_de"] / max(profile.marginal_p95, 1e-6),
                g["max_de"] / max(profile.marginal_max, 1e-6),
            )
            if fail_ratio < 1.08:
                tier = "MARGINAL"
                code = "VISUAL_NUMERIC_CONFLICT_REVIEW"
                conflicts.append("visual_ok_numeric_near_fail")
        elif tier == "PASS" and visual_prob < profile.visual_hold_probability:
            tier = "MARGINAL"
            code = "VISUAL_RISK_OVERRIDE"
            conflicts.append("numeric_ok_visual_risk")

        if root_cause["type"] == "process" and tier == "PASS":
            tier = "MARGINAL"
            code = "PROCESS_RISK_REVIEW"
            reasons.append("process_risk_requires_review")

        if hard_gate.get("manual_arbitration_required"):
            conflicts.append("hard_gate_manual_arbitration")
            tier = "HOLD"
            code = "HARD_GATE_ARBITRATION"
            reasons.extend(hard_gate.get("hard_blocks", []))
            reasons.extend(hard_gate.get("arbitration_triggers", []))
        elif hard_gate.get("manual_review_required") and tier == "PASS":
            conflicts.append("hard_gate_manual_review")
            tier = "MARGINAL"
            code = "HARD_GATE_REVIEW"
            reasons.extend(hard_gate.get("review_triggers", []))

        conf = 0.92
        conf *= 0.85 if tier == "MARGINAL" else 0.78 if tier == "HOLD" else 1.0
        conf *= 0.9 if conflicts else 1.0
        conf *= 0.85 if data_quality["warnings"] else 1.0

        tier_cn = {"PASS": "合格", "MARGINAL": "临界复核", "FAIL": "不合格", "HOLD": "待复测"}[tier]
        decision_mode = (
            "manual_arbitration"
            if tier == "HOLD" or hard_gate.get("manual_arbitration_required")
            else "manual_review"
            if tier == "MARGINAL" or hard_gate.get("manual_review_required")
            else "auto_release"
        )
        return {
            "tier": tier,
            "tier_cn": tier_cn,
            "decision_code": code,
            "confidence": round(_clamp(conf, 0.05, 0.99), 4),
            "reasons": reasons,
            "conflict_resolution": conflicts,
            "decision_mode": decision_mode,
            "auto_release_allowed": bool(hard_gate.get("auto_release_allowed", decision_mode == "auto_release")),
        }


class ActionRecommender:
    def recommend(
        self,
        decision: Dict[str, Any],
        metrics: Dict[str, Any],
        root_cause: Dict[str, Any],
        recipe: Optional[Dict[str, Any]] = None,
        process_params: Optional[Dict[str, Any]] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        meta = dict(meta or {})
        tier = decision["tier"]
        g = metrics["global"]
        advice: List[str] = []
        process_checks: List[str] = []
        recipe_ops: List[str] = []
        prioritized: List[Dict[str, Any]] = []

        if tier == "HOLD":
            advice.extend([
                "复测并锁定光源/曝光/白平衡",
                "核对测量点数量、时间戳、批次号是否完整",
                "复测前执行仪器快速校准",
            ])
        if root_cause["type"] in {"process", "mixed"}:
            process_checks.extend([
                "检查停机再开机首段，首段样品默认隔离",
                "检查换墨/换辊/换基材后的过渡段是否已稳定",
                "检查烘干温度、线速、刮刀压力波动",
                "检查边缘与中心压力平衡",
            ])
        if root_cause["type"] in {"recipe", "mixed"}:
            dL = g["avg_dL"]
            da = g["avg_da"]
            db = g["avg_db"]
            if dL > 0.5:
                recipe_ops.append("整体加深: 主色墨量 +1%~3%")
            elif dL < -0.5:
                recipe_ops.append("整体提亮: 主色墨量 -1%~3%")
            if da > 0.5:
                recipe_ops.append("偏红修正: M -0.5%~2% 或 C +0.5%~1.5%")
            elif da < -0.5:
                recipe_ops.append("偏绿修正: C -0.5%~2% 或 M +0.5%~1.5%")
            if db > 0.5:
                recipe_ops.append("偏黄修正: Y -0.5%~2%")
            elif db < -0.5:
                recipe_ops.append("偏蓝修正: Y +0.5%~2%")

        if tier == "PASS":
            action = "release"
            advice.insert(0, "可放行，建议留样并记录追溯指纹")
            prioritized.append({"priority": 1, "item": "放行并归档", "owner": "质量经理"})
        elif tier == "MARGINAL":
            action = "manual_review"
            advice.insert(0, "需复核后放行，建议补拍+复测至少1轮")
            prioritized.append({"priority": 1, "item": "复测并人工复核", "owner": "质量经理"})
        elif tier == "FAIL":
            action = "block_and_rework"
            advice.insert(0, "禁止放行，执行纠正动作后重测")
            prioritized.append({"priority": 1, "item": "禁止放行并启动纠正措施", "owner": "质量经理"})
        else:
            action = "hold_and_remeasure"
            prioritized.append({"priority": 1, "item": "人工仲裁", "owner": "质量经理"})

        if recipe and isinstance(recipe, dict):
            advice.append("当前配方基线: " + ", ".join(f"{k}={v}" for k, v in sorted(recipe.items())))
            prioritized.append({"priority": 3, "item": "记录配方版本并锁定试印批次", "owner": "工艺工程师"})
        if process_params and isinstance(process_params, dict):
            hints = []
            if _is_number(process_params.get("line_speed")) and float(process_params["line_speed"]) > 100:
                hints.append("线速偏高")
            if _is_number(process_params.get("dry_temp")) and float(process_params["dry_temp"]) > 70:
                hints.append("烘干温度偏高")
            if hints:
                advice.append("工艺风险提示: " + " / ".join(hints))
                prioritized.append({"priority": 2, "item": "先查工艺参数再决定是否改配方", "owner": "工艺工程师"})

        # Anti-oscillation guard for repeated opposite recipe trials.
        trial_guard: List[str] = []
        recent_adjustments = meta.get("recent_recipe_adjustments")
        if isinstance(recent_adjustments, list) and len(recent_adjustments) >= 4:
            norm = [str(x).lower() for x in recent_adjustments[-6:]]
            opposite_pairs = 0
            for i in range(1, len(norm)):
                if ("increase" in norm[i - 1] and "decrease" in norm[i]) or ("decrease" in norm[i - 1] and "increase" in norm[i]):
                    opposite_pairs += 1
            if opposite_pairs >= 2:
                trial_guard.append("检测到反复加减墨来回试错，建议冻结配方并转工艺排查")
                prioritized.append({"priority": 1, "item": "停止来回调墨，先做工艺稳定性排查", "owner": "班组长"})

        role_views = {
            "operator": [advice[0] if advice else "", "按优先级执行前两项动作"],
            "process_engineer": process_checks[:4] or ["工艺无显著异常，维持参数观察"],
            "quality_manager": [f"决策模式:{decision.get('decision_mode', 'unknown')}", f"自动放行:{decision.get('auto_release_allowed', False)}"],
            "customer_service": ["如需对外沟通，先提供复测计划和风险说明"],
        }
        return {
            "action": action,
            "summary": advice[0] if advice else "",
            "advice": advice,
            "recipe_actions": recipe_ops,
            "process_checks": process_checks,
            "prioritized_actions": sorted(prioritized, key=lambda x: int(x["priority"])),
            "trial_guard": trial_guard,
            "role_views": role_views,
        }


class SessionRecorderV3:
    def __init__(self) -> None:
        self._sessions: List[Dict[str, Any]] = []
        self._last_hash = "GENESIS"
        self._idempotency_map: Dict[str, Dict[str, Any]] = {}

    def record(self, payload: Dict[str, Any], idempotency_key: Optional[str] = None) -> Dict[str, Any]:
        if idempotency_key and idempotency_key in self._idempotency_map:
            return {"session_id": self._idempotency_map[idempotency_key]["session_id"], "deduplicated": True}
        session_id = f"S-{int(time.time())}-{len(self._sessions)+1:06d}"
        body = {"session_id": session_id, "ts": _now_iso(), "prev_hash": self._last_hash, "payload": payload}
        digest = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()
        body["hash"] = digest[:24]
        self._last_hash = body["hash"]
        self._sessions.append(body)
        if idempotency_key:
            self._idempotency_map[idempotency_key] = body
        return {"session_id": session_id, "hash": body["hash"], "deduplicated": False}

    def history(self, product: Optional[str] = None, last_n: int = 20) -> List[Dict[str, Any]]:
        if product:
            rows = [s for s in self._sessions if s.get("payload", {}).get("meta", {}).get("product_code") == product]
        else:
            rows = list(self._sessions)
        return rows[-max(1, int(last_n)) :]


class CaptureSOPGeneratorV3:
    def generate(self, product_type: str = "decorative_film") -> Dict[str, Any]:
        return {
            "title": f"Capture SOP - {product_type}",
            "version": "v3.0",
            "core": {
                "geometry": "45/0",
                "light_source": "D65 lightbox Ra>=95",
                "camera_mode": "fixed exposure + fixed white balance + fixed focus",
                "raw_format": "RAW preferred",
            },
            "critical_checks": [
                "lock_exposure_and_wb",
                "include_reference_chart_if_ccm_needed",
                "avoid_glare_shadow_fingerprint",
                "verify_roi_alignment_before_analysis",
                "for_restart_or_changeover: isolate first segment before release",
            ],
        }


class ColorFilmPipelineV3Optimized:
    def __init__(self) -> None:
        self.policy = ThresholdPolicyEngine()
        self.rules = RuleGovernanceCenter()
        self.guard = InputQualityGuard()
        self.ccm = ColorCorrectionEngineV3()
        self.matcher = ThreeStepMatcherV3()
        self.analyzer = GridAnalyzer()
        self.visual = VisualAcceptabilityModel()
        self.root = RootCauseEngine()
        self.hard_gate = HardGateEngine()
        self.arbitrator = DecisionArbitrator()
        self.recommender = ActionRecommender()
        self.cost_engine = BusinessCostEngine()
        self.recorder = SessionRecorderV3()
        self.sop = CaptureSOPGeneratorV3()

    def run(
        self,
        ref_grid: List[Dict[str, Any]],
        sample_grid: List[Dict[str, Any]],
        grid_shape: Tuple[int, int] = (6, 8),
        capture_quality: str = "GOOD",
        recipe: Optional[Dict[str, Any]] = None,
        process_params: Optional[Dict[str, Any]] = None,
        meta: Optional[Dict[str, Any]] = None,
        measurement_context: Optional[Dict[str, Any]] = None,
        policy_overrides: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        meta = dict(meta or {})
        measurement_context = dict(measurement_context or {})
        gate_context = measurement_context.get("gate_context") if isinstance(measurement_context.get("gate_context"), dict) else {}
        decision_ts = measurement_context.get("decision_ts")
        force_rule_version = measurement_context.get("force_rule_version")

        quality = self.guard.validate_grid(
            ref_grid=ref_grid,
            sample_grid=sample_grid,
            grid_shape=grid_shape,
            measurement_ids=measurement_context.get("measurement_ids"),
            measurement_timestamps=measurement_context.get("timestamps"),
        )
        if not quality["valid"]:
            session = self.recorder.record({
                "meta": meta,
                "tier": "HOLD",
                "decision_code": "DATA_INVALID",
                "quality": {"errors": quality["errors"], "warnings": quality["warnings"]},
            }, idempotency_key=str(meta.get("idempotency_key", "")) or None)
            return {
                "session_id": session["session_id"],
                "tier": "HOLD",
                "tier_cn": "待复测",
                "confidence": 0.99,
                "decision_code": "DATA_INVALID",
                "action": "hold_and_remeasure",
                "reasons": quality["errors"],
                "color": {},
                "defects": {},
                "root_cause": {"type": "data_quality", "summary": "invalid_measurement_input"},
                "advice": {"summary": "输入数据无效，禁止放行", "advice": ["检查Lab字段完整性与物理范围", "检查网格尺寸与点数匹配", "检查测量时间戳和批次号"]},
                "quality_gate": quality,
                "meta": meta,
            }

        rule_resolve = self.rules.resolve(meta=meta, at_ts=decision_ts, force_version=force_rule_version)
        rule_pack = rule_resolve["rule_pack"]
        merged_overrides = dict(rule_pack.get("threshold_overrides", {}))
        if isinstance(policy_overrides, dict):
            merged_overrides.update(policy_overrides)
        policy = self.policy.resolve(meta, merged_overrides)
        profile = policy["profile"]
        metrics = self.analyzer.analyze(quality["clean_ref_grid"], quality["clean_sample_grid"], grid_shape=grid_shape, hotspot_threshold=profile.local_hotspot_limit)
        visual = self.visual.predict(metrics, meta)
        root = self.root.classify(metrics, quality)
        hard_gate = self.hard_gate.evaluate(data_quality=quality, visual=visual, root_cause=root, gate_context=gate_context)
        decision = self.arbitrator.arbitrate(metrics, visual, quality, root, profile, hard_gate=hard_gate)
        advice = self.recommender.recommend(decision, metrics, root, recipe=recipe, process_params=process_params, meta=meta)
        business_plan = self.cost_engine.plan(decision=decision, hard_gate=hard_gate, meta=meta)

        capture_quality_slug = _slug(capture_quality)
        conf = float(decision["confidence"])
        if capture_quality_slug in {"acceptable"}:
            conf *= 0.9
        elif capture_quality_slug in {"recapture_needed", "poor"}:
            conf *= 0.75
        decision["confidence"] = round(_clamp(conf, 0.01, 0.99), 4)

        session = self.recorder.record({
            "meta": meta,
            "tier": decision["tier"],
            "decision_code": decision["decision_code"],
            "avg_de": metrics["global"]["avg_de"],
            "max_de": metrics["global"]["max_de"],
            "hotspot_ratio": metrics["local"]["hotspot_ratio"],
            "root_cause": root["type"],
            "rule_version": rule_pack.get("version"),
        }, idempotency_key=str(meta.get("idempotency_key", "")) or None)

        color_block = {
            "avg_de": metrics["global"]["avg_de"],
            "p95_de": metrics["global"]["p95_de"],
            "max_de": metrics["global"]["max_de"],
            "components": {
                "dL": metrics["global"]["avg_dL"],
                "da": metrics["global"]["avg_da"],
                "db": metrics["global"]["avg_db"],
            },
            "deviation": {"summary": self._deviation_summary(metrics["global"]["avg_dL"], metrics["global"]["avg_da"], metrics["global"]["avg_db"])},
        }
        defects_block = {
            "uniformity_std": metrics["global"]["std_de"],
            "uniformity_grade": "uniform" if metrics["global"]["std_de"] < 0.35 else "acceptable" if metrics["global"]["std_de"] < 0.75 else "uneven",
            "hotspot_count": metrics["local"]["hotspot_count"],
            "hotspot_ratio": metrics["local"]["hotspot_ratio"],
            "edge_effect_risk": metrics["uniformity"]["edge_effect_risk"],
            "tail_drift_risk": metrics["roll_segments"].get("tail", 0) > metrics["roll_segments"].get("middle", 0) * 1.1 if metrics.get("roll_segments") else False,
            "worst_point": metrics["local"]["worst_point"],
            "clusters": metrics["clusters"],
        }

        result_layers = {
            "raw_value_layer": {
                "global_metrics": metrics["global"],
                "point_components_preview": metrics["components"][:10],
            },
            "compensated_value_layer": measurement_context.get("compensated_layer", {}),
            "judgment_layer": {
                "tier": decision["tier"],
                "decision_code": decision["decision_code"],
                "decision_mode": decision.get("decision_mode"),
                "confidence": decision["confidence"],
            },
            "review_layer": {
                "hard_blocks": hard_gate["hard_blocks"],
                "review_triggers": hard_gate["review_triggers"],
                "arbitration_triggers": hard_gate["arbitration_triggers"],
            },
        }

        return {
            "ok": True,
            "session_id": session["session_id"],
            "session_hash": session.get("hash"),
            "tier": decision["tier"],
            "tier_cn": decision["tier_cn"],
            "decision_code": decision["decision_code"],
            "confidence": decision["confidence"],
            "action": advice["action"],
            "reasons": decision["reasons"],
            "conflict_resolution": decision["conflict_resolution"],
            "decision_mode": decision.get("decision_mode"),
            "auto_release_allowed": decision.get("auto_release_allowed"),
            "color": color_block,
            "defects": defects_block,
            "root_cause": root,
            "advice": advice,
            "business_plan": business_plan,
            "hard_gate": hard_gate,
            "result_layers": result_layers,
            "quality_gate": {
                "valid": quality["valid"],
                "warnings": quality["warnings"],
                "suspicious_ratio": quality["suspicious_ratio"],
                "duplicate_measurement_ids": quality["duplicate_measurement_ids"],
                "timestamp_disorder_count": quality["timestamp_disorder_count"],
            },
            "threshold_profile": {
                **asdict(profile),
                "policy_factor": policy["policy_factor"],
                "customer_tier": policy["tier"],
                "application": policy["application"],
                "sku_class": policy["sku_class"],
                "policy_version": policy["policy_version"],
            },
            "rule_trace": {
                "rule_version": rule_pack.get("version"),
                "model_version": rule_pack.get("model_version"),
                "resolved_by": rule_resolve.get("resolved_by"),
                "rule_notes": rule_pack.get("notes"),
            },
            "visual_acceptance": visual,
            "roll_segments": metrics["roll_segments"],
            "heatmap": metrics["heatmap"],
            "meta": meta,
        }

    def register_rule_pack(
        self,
        version: str,
        active_from_ts: float,
        scope: Optional[Dict[str, Any]] = None,
        threshold_overrides: Optional[Dict[str, Any]] = None,
        model_version: str = "MODEL-COLOR-V3",
        notes: str = "",
    ) -> Dict[str, Any]:
        return self.rules.register_rule_pack(
            version=version,
            active_from_ts=active_from_ts,
            scope=scope,
            threshold_overrides=threshold_overrides,
            model_version=model_version,
            notes=notes,
        )

    def list_rule_packs(self) -> List[Dict[str, Any]]:
        return self.rules.list_rule_packs()

    def simulate_rule_versions(
        self,
        ref_grid: List[Dict[str, Any]],
        sample_grid: List[Dict[str, Any]],
        versions: List[str],
        grid_shape: Tuple[int, int] = (6, 8),
        meta: Optional[Dict[str, Any]] = None,
        measurement_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        rows: List[Dict[str, Any]] = []
        for ver in versions:
            ctx = dict(measurement_context or {})
            ctx["force_rule_version"] = ver
            out = self.run(
                ref_grid=ref_grid,
                sample_grid=sample_grid,
                grid_shape=grid_shape,
                meta=meta,
                measurement_context=ctx,
            )
            rows.append(
                {
                    "rule_version": ver,
                    "tier": out.get("tier"),
                    "decision_code": out.get("decision_code"),
                    "decision_mode": out.get("decision_mode"),
                    "estimated_min_cost": out.get("business_plan", {}).get("estimated_min_cost"),
                }
            )
        return {"simulations": rows, "count": len(rows)}

    @staticmethod
    def _deviation_summary(dL: float, da: float, db: float) -> str:
        parts: List[str] = []
        if dL > 0.5:
            parts.append("偏亮")
        elif dL < -0.5:
            parts.append("偏暗")
        if da > 0.4:
            parts.append("偏红")
        elif da < -0.4:
            parts.append("偏绿")
        if db > 0.4:
            parts.append("偏黄")
        elif db < -0.4:
            parts.append("偏蓝")
        return "、".join(parts) if parts else "无明显偏差"


ColorFilmPipelineV2 = ColorFilmPipelineV3Optimized
ColorCorrectionEngine = ColorCorrectionEngineV3
ThreeStepMatcher = ThreeStepMatcherV3


if __name__ == "__main__":
    import random

    random.seed(42)
    pipe = ColorFilmPipelineV3Optimized()

    ref: List[Dict[str, float]] = []
    sample: List[Dict[str, float]] = []
    for i in range(48):
        base = {"L": 62.0 + random.gauss(0.0, 0.12), "a": 3.2 + random.gauss(0.0, 0.05), "b": 14.8 + random.gauss(0.0, 0.08)}
        ref.append(base)
        col = i % 8
        if col == 0 and i < 24:
            sample.append({"L": base["L"] + 1.8, "a": base["a"] + 1.1, "b": base["b"] + 0.8})
        else:
            sample.append({"L": base["L"] + 0.35, "a": base["a"] + 0.2, "b": base["b"] + 0.15})

    result = pipe.run(
        ref,
        sample,
        grid_shape=(6, 8),
        meta={"product_code": "SELFTEST-SKU", "customer_tier": "vip", "application": "exterior", "idempotency_key": "demo-001"},
        process_params={"line_speed": 98, "dry_temp": 72},
    )
    assert result["tier"] in {"MARGINAL", "FAIL"}
    assert result["quality_gate"]["valid"] is True
    print(json.dumps({
        "tier": result["tier"],
        "decision_code": result["decision_code"],
        "avg_de": result["color"]["avg_de"],
        "max_de": result["color"]["max_de"],
        "hotspot_ratio": result["defects"]["hotspot_ratio"],
        "root_cause": result["root_cause"]["type"],
    }, ensure_ascii=False, indent=2))
