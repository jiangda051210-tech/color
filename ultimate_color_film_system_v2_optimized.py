"""
Production-grade lifecycle system for decorative film quality.
Covers environment -> substrate -> run monitoring -> traceability -> CAPA closure.
No third-party dependencies.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import statistics
import time
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from threading import RLock
from typing import Any

from color_film_mvp_v3_optimized import de2000


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(float(x))


def _safe_mean(values: Sequence[float], default: float = 0.0) -> float:
    return statistics.mean(values) if values else default


def _ensure_lab(lab: Any) -> dict[str, float] | None:
    if not isinstance(lab, dict):
        return None
    out = {}
    for key in ("L", "a", "b"):
        val = lab.get(key)
        if not _is_number(val):
            return None
        out[key] = float(val)
    return out


class EnvironmentCompensatorV2:
    TEMP_COEFF = {"dL_per_deg": -0.015, "da_per_deg": 0.002, "db_per_deg": 0.008}
    HUMID_COEFF = {"dL_per_pct": -0.008, "da_per_pct": 0.001, "db_per_pct": 0.003}
    LED_DRIFT = {"hours_to_warning": 2000, "hours_to_recal": 5000, "cct_drift_per_1000h": 50}

    def __init__(self) -> None:
        self._ref_temp = 25.0
        self._ref_humid = 50.0
        self._led_hours = 0.0
        self._history: list[dict[str, Any]] = []

    def record_conditions(
        self,
        temp: float,
        humidity: float,
        led_hours: float | None = None,
        machine_id: str = "LINE-01",
        shift: str | None = None,
        ts: float | None = None,
    ) -> dict[str, Any]:
        if led_hours is not None and _is_number(led_hours):
            self._led_hours = float(led_hours)
        record = {
            "ts": float(ts if ts is not None else time.time()),
            "iso": _now_iso(),
            "temp": float(temp),
            "humidity": float(humidity),
            "led_hours": float(self._led_hours),
            "machine_id": machine_id,
            "shift": shift or ("night" if time.localtime().tm_hour < 8 or time.localtime().tm_hour >= 20 else "day"),
        }
        self._history.append(record)
        if len(self._history) > 5000:
            self._history = self._history[-5000:]
        return {"recorded": True, "count": len(self._history)}

    def compensate_lab(self, lab: dict[str, float], temp: float, humidity: float) -> dict[str, float]:
        dt = float(temp) - self._ref_temp
        dh = float(humidity) - self._ref_humid
        return {
            "L": lab["L"] - self.TEMP_COEFF["dL_per_deg"] * dt - self.HUMID_COEFF["dL_per_pct"] * dh,
            "a": lab["a"] - self.TEMP_COEFF["da_per_deg"] * dt - self.HUMID_COEFF["da_per_pct"] * dh,
            "b": lab["b"] - self.TEMP_COEFF["db_per_deg"] * dt - self.HUMID_COEFF["db_per_pct"] * dh,
        }

    def check_environment(self, temp: float, humidity: float, machine_id: str = "LINE-01") -> dict[str, Any]:
        issues: list[str] = []
        severity = 0.0
        temp = float(temp)
        humidity = float(humidity)

        if temp < 18 or temp > 30:
            issues.append(f"temperature_out_of_range:{temp}")
            severity = max(severity, 0.6 if abs(temp - 25) > 8 else 0.3)
        if humidity < 30 or humidity > 70:
            issues.append(f"humidity_out_of_range:{humidity}")
            severity = max(severity, 0.5 if abs(humidity - 50) > 25 else 0.2)

        if self._led_hours > self.LED_DRIFT["hours_to_recal"]:
            issues.append("lightbox_recalibration_overdue")
            severity = max(severity, 0.8)
        elif self._led_hours > self.LED_DRIFT["hours_to_warning"]:
            issues.append("lightbox_recalibration_due")
            severity = max(severity, 0.4)

        recent = [x for x in self._history[-20:] if x.get("machine_id") == machine_id]
        if len(recent) >= 5:
            t_span = max(x["temp"] for x in recent) - min(x["temp"] for x in recent)
            h_span = max(x["humidity"] for x in recent) - min(x["humidity"] for x in recent)
            if t_span > 3:
                issues.append(f"temperature_unstable_span:{round(t_span,2)}")
                severity = max(severity, 0.4)
            if h_span > 12:
                issues.append(f"humidity_unstable_span:{round(h_span,2)}")
                severity = max(severity, 0.35)

        # Day/night shift drift risk.
        day = [x for x in self._history[-200:] if x.get("shift") == "day"]
        night = [x for x in self._history[-200:] if x.get("shift") == "night"]
        shift_drift = 0.0
        if len(day) >= 3 and len(night) >= 3:
            day_t = _safe_mean([x["temp"] for x in day])
            night_t = _safe_mean([x["temp"] for x in night])
            day_h = _safe_mean([x["humidity"] for x in day])
            night_h = _safe_mean([x["humidity"] for x in night])
            shift_drift = abs(day_t - night_t) * 0.08 + abs(day_h - night_h) * 0.02
            if shift_drift > 0.35:
                issues.append(f"day_night_drift_risk:{round(shift_drift,3)}")
                severity = max(severity, 0.35)

        return {
            "suitable": severity < 0.5,
            "severity": round(severity, 3),
            "issues": issues,
            "compensation_applied": abs(temp - 25) > 2 or abs(humidity - 50) > 10,
            "led_status": "ok" if self._led_hours < self.LED_DRIFT["hours_to_warning"] else "warning" if self._led_hours < self.LED_DRIFT["hours_to_recal"] else "recal_needed",
            "estimated_cct_drift": round(self._led_hours / 1000.0 * self.LED_DRIFT["cct_drift_per_1000h"], 2),
            "day_night_drift_risk": round(shift_drift, 3),
        }


class SubstrateAnalyzerV2:
    def __init__(self) -> None:
        self._lots: dict[str, dict[str, Any]] = {}

    def register_lot(
        self,
        lot_id: str,
        lab: dict[str, float],
        supplier: str = "",
        material: str = "pvc",
        opacity: float = 1.0,
        gloss: float = 0.0,
        thickness_um: float | None = None,
    ) -> dict[str, Any]:
        lab_ok = _ensure_lab(lab)
        if lab_ok is None:
            return {"error": "invalid_lab"}
        duplicate = lot_id in self._lots
        self._lots[lot_id] = {
            "lab": lab_ok,
            "supplier": supplier,
            "material": material,
            "opacity": float(opacity),
            "gloss": float(gloss),
            "thickness_um": float(thickness_um) if _is_number(thickness_um) else None,
            "ts": _now_iso(),
            "version": (self._lots[lot_id]["version"] + 1) if duplicate else 1,
        }
        return {"registered": True, "lot": lot_id, "duplicate_overwrite": duplicate, "total_lots": len(self._lots)}

    def compare_to_reference(self, lot_id: str, ref_lot_id: str | None = None) -> dict[str, Any]:
        if lot_id not in self._lots:
            return {"error": f"lot_not_found:{lot_id}"}
        if ref_lot_id is None:
            keys = [k for k in self._lots if k != lot_id]
            if not keys:
                return {"status": "first_lot", "message": "no_reference_lot"}
            ref_lot_id = keys[-1]
        if ref_lot_id not in self._lots:
            return {"error": f"ref_lot_not_found:{ref_lot_id}"}

        cur = self._lots[lot_id]
        ref = self._lots[ref_lot_id]
        d = de2000(ref["lab"], cur["lab"])

        transmission = 0.7
        transmission *= 0.85 + 0.15 * max(0.0, min(cur.get("opacity", 1.0), 1.2))
        transmission *= 1.0 + min(0.2, abs(cur.get("gloss", 0.0) - ref.get("gloss", 0.0)) / 100.0)
        impact = d["total"] * transmission

        return {
            "current_lot": lot_id,
            "reference_lot": ref_lot_id,
            "substrate_de": round(d["total"], 4),
            "dL": d["raw_dL"],
            "da": d["raw_da"],
            "db": d["raw_db"],
            "estimated_print_impact": round(impact, 4),
            "needs_recipe_adjust": impact > 1.0,
            "warning": "substrate_shift_high" if impact > 1.2 else "substrate_shift_medium" if impact > 0.6 else None,
            "compensation_suggestion": self._suggest(d),
        }

    @staticmethod
    def _suggest(d: dict[str, float]) -> str:
        parts: list[str] = []
        if d["raw_dL"] > 0.3:
            parts.append("substrate_whiter:increase_ink_density")
        elif d["raw_dL"] < -0.3:
            parts.append("substrate_darker:decrease_ink_density")
        if d["raw_db"] > 0.3:
            parts.append("substrate_yellower:add_cool_compensation")
        elif d["raw_db"] < -0.3:
            parts.append("substrate_bluer:add_warm_compensation")
        return ";".join(parts) if parts else "no_strong_compensation_needed"


class WetToDryPredictorV2:
    PROFILES = {
        "solvent_gravure": {"dL": -1.2, "dC": +0.8, "dh": +1.5, "dry_hours": 4.0},
        "water_based": {"dL": -0.8, "dC": +0.5, "dh": +0.8, "dry_hours": 6.0},
        "uv_curing": {"dL": -0.3, "dC": +0.2, "dh": +0.3, "dry_hours": 0.1},
        "digital_inkjet": {"dL": -0.5, "dC": +0.3, "dh": +0.5, "dry_hours": 2.0},
    }

    def __init__(self) -> None:
        self._history: list[dict[str, Any]] = []

    def _profile(self, ink_type: str) -> dict[str, float]:
        p = dict(self.PROFILES.get(ink_type, self.PROFILES["solvent_gravure"]))
        samples = [x for x in self._history if x["type"] == ink_type]
        if len(samples) >= 5:
            p["dL"] = _safe_mean([x["actual_dL"] for x in samples], p["dL"])
            p["dC"] = _safe_mean([x["actual_dC"] for x in samples], p["dC"])
        return p

    def predict_dry_lab(
        self,
        wet_lab: dict[str, float],
        ink_type: str = "solvent_gravure",
        elapsed_hours: float = 0.0,
        post_process: list[str] | None = None,
        storage_days: float = 0.0,
    ) -> dict[str, Any]:
        wet = _ensure_lab(wet_lab)
        if wet is None:
            return {"error": "invalid_wet_lab"}
        profile = self._profile(ink_type)
        dry_h = max(0.01, float(profile["dry_hours"]))
        progress = 1.0 - math.exp(-2.5 * max(0.0, float(elapsed_hours)) / dry_h)
        progress = min(1.0, progress)

        c_wet = math.hypot(wet["a"], wet["b"])
        h_wet = math.atan2(wet["b"], wet["a"])
        c_current = c_wet + profile["dC"] * progress
        h_current = h_wet + math.radians(profile["dh"] * progress)

        current = {
            "L": round(wet["L"] + profile["dL"] * progress, 3),
            "a": round(c_current * math.cos(h_current), 3),
            "b": round(c_current * math.sin(h_current), 3),
        }
        final = {
            "L": round(wet["L"] + profile["dL"], 3),
            "a": round((c_wet + profile["dC"]) * math.cos(h_wet + math.radians(profile["dh"])), 3),
            "b": round((c_wet + profile["dC"]) * math.sin(h_wet + math.radians(profile["dh"])), 3),
        }

        post_shift = {"L": 0.0, "a": 0.0, "b": 0.0}
        for step in (post_process or []):
            tag = str(step).lower()
            if tag == "lamination":
                post_shift["L"] -= 0.15
                post_shift["b"] += 0.08
            elif tag == "embossing":
                post_shift["L"] += 0.05
                post_shift["a"] += 0.03
            elif tag == "adhesive":
                post_shift["b"] += 0.12
        if storage_days > 0:
            post_shift["L"] -= min(0.6, storage_days * 0.01)
            post_shift["b"] += min(0.5, storage_days * 0.012)
        final_post = {k: round(final[k] + post_shift[k], 3) for k in ("L", "a", "b")}

        d = de2000(wet, final_post)
        return {
            "wet_lab": wet,
            "predicted_current": current,
            "predicted_final_dry": final,
            "predicted_final_after_postprocess": final_post,
            "dry_progress_pct": round(progress * 100.0, 2),
            "remaining_hours": round(max(0.0, dry_h - elapsed_hours), 2),
            "wet_to_dry_de": d["total"],
            "ink_type": ink_type,
            "warning": "wet_dry_shift_high" if d["total"] > 1.2 else "wet_dry_shift_medium" if d["total"] > 0.6 else None,
        }

    def learn(self, wet_lab: dict[str, float], dry_lab: dict[str, float], ink_type: str, dry_hours: float) -> dict[str, Any]:
        wet = _ensure_lab(wet_lab)
        dry = _ensure_lab(dry_lab)
        if wet is None or dry is None:
            return {"error": "invalid_lab_for_learning"}
        c_wet = math.hypot(wet["a"], wet["b"])
        c_dry = math.hypot(dry["a"], dry["b"])
        self._history.append({
            "wet": wet,
            "dry": dry,
            "type": ink_type,
            "actual_dL": dry["L"] - wet["L"],
            "actual_dC": c_dry - c_wet,
            "dry_hours": float(dry_hours),
            "ts": _now_iso(),
        })
        if len(self._history) > 3000:
            self._history = self._history[-3000:]
        return {"recorded": True, "samples": len(self._history)}


class PrintRunMonitorV2:
    def __init__(self, target_lab: dict[str, float] | None = None, tolerance: float = 2.5) -> None:
        self._target = _ensure_lab(target_lab) if target_lab else None
        self._tol = float(tolerance)
        self._samples: list[dict[str, Any]] = []
        self._alerts: list[dict[str, Any]] = []
        self._run_id = ""
        self._changeovers: list[dict[str, Any]] = []
        self._startup_samples = 8

    def set_target(self, lab: dict[str, float], tolerance: float | None = None, run_id: str | None = None) -> dict[str, Any]:
        self._target = _ensure_lab(lab)
        if self._target is None:
            return {"error": "invalid_target_lab"}
        if tolerance is not None and _is_number(tolerance):
            self._tol = float(tolerance)
        self._samples = []
        self._alerts = []
        self._changeovers = []
        self._run_id = run_id or f"RUN-{int(time.time())}"
        return {"ok": True, "run_id": self._run_id, "tolerance": self._tol}

    def mark_changeover(self, change_type: str, at_seq: int | None = None, stabilization_samples: int = 10) -> dict[str, Any]:
        seq = int(at_seq if at_seq is not None else len(self._samples) + 1)
        self._changeovers.append({"type": change_type, "seq": seq, "stabilization_samples": max(1, int(stabilization_samples)), "ts": _now_iso()})
        return {"recorded": True, "changeovers": len(self._changeovers)}

    def _phase(self, seq: int) -> str:
        if seq <= self._startup_samples:
            return "startup"
        for c in self._changeovers:
            if c["seq"] <= seq < c["seq"] + c["stabilization_samples"]:
                return f"transition:{c['type']}"
        return "steady"

    def add_sample(
        self,
        lab: dict[str, float],
        seq: int | None = None,
        timestamp: float | None = None,
        meter_position: float | None = None,
        roll_id: str = "",
    ) -> dict[str, Any]:
        if self._target is None:
            return {"error": "target_not_set"}
        lab_ok = _ensure_lab(lab)
        if lab_ok is None:
            return {"error": "invalid_lab"}

        seq_num = int(seq if seq is not None else len(self._samples) + 1)
        ts = float(timestamp if timestamp is not None else time.time())
        if self._samples:
            if seq_num <= self._samples[-1]["seq"]:
                return {"error": "non_monotonic_seq"}
            if ts < self._samples[-1]["ts"]:
                return {"error": "non_monotonic_timestamp"}

        d = de2000(self._target, lab_ok)
        phase = self._phase(seq_num)
        sample = {
            "seq": seq_num,
            "ts": ts,
            "iso": _now_iso(),
            "phase": phase,
            "meter_position": float(meter_position) if _is_number(meter_position) else None,
            "roll_id": roll_id,
            "lab": lab_ok,
            "de": d["total"],
            "components": d,
        }
        self._samples.append(sample)

        alert: dict[str, Any] | None = None
        extra_alerts: list[dict[str, Any]] = []
        if d["total"] > self._tol:
            alert = {"type": "OUT_OF_TOLERANCE", "seq": seq_num, "de": d["total"], "phase": phase}

        if len(self._samples) >= 5 and alert is None:
            last5 = [s["de"] for s in self._samples[-5:]]
            if all(last5[i] < last5[i + 1] for i in range(4)):
                alert = {"type": "TRENDING_UP", "seq": seq_num, "start": last5[0], "end": last5[-1]}
            elif all(last5[i] > last5[i + 1] for i in range(4)):
                alert = {"type": "TRENDING_DOWN", "seq": seq_num, "start": last5[0], "end": last5[-1]}

        if len(self._samples) >= 2 and alert is None:
            prev_de = self._samples[-2]["de"]
            if abs(d["total"] - prev_de) > max(0.5, self._tol * 0.35):
                alert = {"type": "SUDDEN_SHIFT", "seq": seq_num, "from": prev_de, "to": d["total"]}

        if phase.startswith("startup") and d["total"] > self._tol * 0.8:
            extra_alerts.append({"type": "STARTUP_SCRAP_RISK", "seq": seq_num, "de": d["total"]})

        if phase.startswith("transition") and d["total"] > self._tol * 0.75:
            extra_alerts.append({"type": "CHANGEOVER_TRANSITION_RISK", "seq": seq_num, "de": d["total"], "phase": phase})

        if alert:
            self._alerts.append(alert)
        if extra_alerts:
            self._alerts.extend(extra_alerts)

        # Tail sustained drift detection by meter/sequence.
        tail_drift_alert = self._detect_tail_drift()
        if tail_drift_alert:
            self._alerts.append(tail_drift_alert)

        return {
            "seq": seq_num,
            "phase": phase,
            "meter_position": sample["meter_position"],
            "de": d["total"],
            "in_tolerance": d["total"] <= self._tol,
            "components": {"dL": d["dL"], "dC": d["dC"], "dH": d["dH"]},
            "alert": alert,
            "extra_alerts": extra_alerts,
            "run_stats": self._run_stats(),
        }

    def _run_stats(self) -> dict[str, Any]:
        if not self._samples:
            return {}
        des = [s["de"] for s in self._samples]
        return {
            "count": len(des),
            "avg_de": round(_safe_mean(des), 4),
            "max_de": round(max(des), 4),
            "std_de": round(statistics.stdev(des), 4) if len(des) > 1 else 0.0,
            "in_tolerance_pct": round(sum(1 for d in des if d <= self._tol) / len(des) * 100.0, 2),
            "alerts": len(self._alerts),
        }

    def get_report(self) -> dict[str, Any]:
        stats = self._run_stats()
        trend = self._trend_analysis()
        segment = self._head_mid_tail()
        startup_risk = any(a.get("type") == "STARTUP_SCRAP_RISK" for a in self._alerts)
        transition_risk = any(a.get("type") == "CHANGEOVER_TRANSITION_RISK" for a in self._alerts)
        tail_drift = self._tail_drift_summary()
        meters = [x.get("meter_position") for x in self._samples if _is_number(x.get("meter_position"))]
        return {
            "run_id": self._run_id,
            "status": "unstable" if self._alerts else "stable" if stats.get("std_de", 0.0) < 0.3 else "acceptable",
            "stats": stats,
            "alerts": self._alerts[-20:],
            "trend": trend,
            "segment_profile": segment,
            "startup_scrap_risk": startup_risk,
            "changeover_transition_risk": transition_risk,
            "changeover_count": len(self._changeovers),
            "tail_drift": tail_drift,
            "meter_range": {
                "min": round(min(meters), 3) if meters else None,
                "max": round(max(meters), 3) if meters else None,
                "covered": bool(meters),
            },
        }

    def _trend_analysis(self) -> dict[str, Any]:
        if len(self._samples) < 6:
            return {"direction": "insufficient_data"}
        first = [x["de"] for x in self._samples[: len(self._samples) // 2]]
        second = [x["de"] for x in self._samples[len(self._samples) // 2 :]]
        a = _safe_mean(first)
        b = _safe_mean(second)
        if b > a * 1.12:
            return {"direction": "degrading", "change": round(b - a, 4)}
        if b < a * 0.9:
            return {"direction": "improving", "change": round(b - a, 4)}
        return {"direction": "stable", "change": round(b - a, 4)}

    def _head_mid_tail(self) -> dict[str, float]:
        if len(self._samples) < 3:
            return {}
        n = len(self._samples)
        head = [x["de"] for x in self._samples[: max(1, n // 3)]]
        tail = [x["de"] for x in self._samples[-max(1, n // 3) :]]
        mid = [x["de"] for x in self._samples[n // 3 : 2 * n // 3]]
        return {"head": round(_safe_mean(head), 4), "middle": round(_safe_mean(mid), 4), "tail": round(_safe_mean(tail), 4)}

    def _tail_drift_summary(self) -> dict[str, Any]:
        if len(self._samples) < 12:
            return {"detected": False, "reason": "insufficient_samples"}
        n = len(self._samples)
        seg = max(3, n // 5)
        head = [x["de"] for x in self._samples[:seg]]
        tail = [x["de"] for x in self._samples[-seg:]]
        head_avg = _safe_mean(head)
        tail_avg = _safe_mean(tail)
        delta = tail_avg - head_avg
        sustained = all(x["de"] > self._tol * 0.8 for x in self._samples[-min(6, n) :])
        detected = delta > 0.35 and (tail_avg > head_avg * 1.1 or sustained)
        return {
            "detected": detected,
            "head_avg_de": round(head_avg, 4),
            "tail_avg_de": round(tail_avg, 4),
            "delta": round(delta, 4),
            "sustained_risk": sustained,
        }

    def _detect_tail_drift(self) -> dict[str, Any] | None:
        summary = self._tail_drift_summary()
        if summary.get("detected"):
            return {
                "type": "TAIL_SUSTAINED_DRIFT",
                "seq": self._samples[-1]["seq"] if self._samples else None,
                "delta": summary["delta"],
                "head_avg_de": summary["head_avg_de"],
                "tail_avg_de": summary["tail_avg_de"],
            }
        return None


class RollLifecycleTrackerV2:
    """
    Roll/length-direction tracker for mother roll, child roll and transition zones.
    """

    def __init__(self) -> None:
        self._rolls: dict[str, dict[str, Any]] = {}
        self._lot_rolls: dict[str, list[str]] = defaultdict(list)
        self._zones: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._samples: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def register_roll(
        self,
        lot_id: str,
        roll_id: str,
        length_m: float,
        parent_roll_id: str | None = None,
        rework_of: str | None = None,
        machine_id: str = "",
        shift: str = "",
    ) -> dict[str, Any]:
        rid = str(roll_id)
        if not rid or not lot_id:
            return {"registered": False, "error": "missing_roll_or_lot"}
        if rid in self._rolls:
            return {"registered": False, "error": "duplicate_roll_id", "roll_id": rid}
        length = max(1.0, float(length_m))
        row = {
            "lot_id": lot_id,
            "roll_id": rid,
            "length_m": round(length, 3),
            "parent_roll_id": str(parent_roll_id or ""),
            "rework_of": str(rework_of or ""),
            "machine_id": str(machine_id),
            "shift": str(shift),
            "created_at": _now_iso(),
        }
        self._rolls[rid] = row
        self._lot_rolls[lot_id].append(rid)
        return {"registered": True, "roll_id": rid, "lot_id": lot_id}

    def mark_zone(
        self,
        roll_id: str,
        zone_type: str,
        meter_start: float,
        meter_end: float,
        reason: str = "",
    ) -> dict[str, Any]:
        rid = str(roll_id)
        if rid not in self._rolls:
            return {"recorded": False, "error": "roll_not_found"}
        ms = float(meter_start)
        me = float(meter_end)
        if me <= ms:
            return {"recorded": False, "error": "invalid_meter_range"}
        ztype = str(zone_type).strip().lower().replace("-", "_").replace(" ", "_") or "transition_zone"
        zid = f"{rid}-ZONE-{len(self._zones[rid])+1:04d}"
        row = {
            "zone_id": zid,
            "type": ztype,
            "meter_start": round(ms, 3),
            "meter_end": round(me, 3),
            "reason": reason,
            "ts": _now_iso(),
        }
        self._zones[rid].append(row)
        return {"recorded": True, "zone_id": zid}

    def add_measurement(
        self,
        roll_id: str,
        meter_pos: float,
        de: float,
        lab: dict[str, float] | None = None,
        source: str = "",
        ts: float | None = None,
    ) -> dict[str, Any]:
        rid = str(roll_id)
        if rid not in self._rolls:
            return {"recorded": False, "error": "roll_not_found"}
        if not _is_number(meter_pos) or not _is_number(de):
            return {"recorded": False, "error": "meter_or_de_invalid"}
        meter = float(meter_pos)
        val = float(de)
        prev = self._samples[rid][-1] if self._samples[rid] else None
        if prev and meter < float(prev["meter_pos"]):
            return {"recorded": False, "error": "non_monotonic_meter"}
        row = {
            "seq": len(self._samples[rid]) + 1,
            "meter_pos": round(meter, 4),
            "de": round(val, 4),
            "lab": _ensure_lab(lab) if lab else None,
            "source": str(source),
            "ts_epoch": float(ts if ts is not None else time.time()),
            "ts": _now_iso(),
        }
        self._samples[rid].append(row)
        return {"recorded": True, "count": len(self._samples[rid])}

    @staticmethod
    def _zone_de_stats(samples: list[dict[str, Any]], zone: dict[str, Any]) -> dict[str, Any]:
        ms = float(zone["meter_start"])
        me = float(zone["meter_end"])
        inside = [x for x in samples if ms <= float(x["meter_pos"]) <= me]
        if not inside:
            return {
                "zone_id": zone["zone_id"],
                "type": zone["type"],
                "sample_count": 0,
                "avg_de": None,
                "max_de": None,
                "risk_score": 0.0,
            }
        des = [float(x["de"]) for x in inside]
        avg_de = _safe_mean(des)
        max_de = max(des)
        type_factor = 1.25 if zone["type"] in {"restart_zone", "transition_zone", "rework_zone"} else 1.0
        risk = min(1.0, (avg_de / 2.5) * 0.65 * type_factor + (max_de / 4.0) * 0.35)
        return {
            "zone_id": zone["zone_id"],
            "type": zone["type"],
            "sample_count": len(inside),
            "avg_de": round(avg_de, 4),
            "max_de": round(max_de, 4),
            "risk_score": round(risk, 4),
        }

    def summary(self, roll_id: str) -> dict[str, Any]:
        rid = str(roll_id)
        if rid not in self._rolls:
            return {"status": "roll_not_found", "roll_id": rid}
        profile = self._rolls[rid]
        samples = list(self._samples.get(rid, []))
        zones = list(self._zones.get(rid, []))
        if not samples:
            return {
                "status": "no_measurement",
                "roll_profile": profile,
                "zones": zones,
                "transition_risk_score": 0.0,
                "tail_risk_score": 0.0,
                "overall_risk_score": 0.0,
            }
        des = [float(x["de"]) for x in samples]
        n = len(samples)
        seg = max(1, n // 3)
        head = des[:seg]
        middle = des[seg : n - seg] if n > 2 * seg else des[seg:]
        tail = des[-seg:]
        head_avg = _safe_mean(head)
        mid_avg = _safe_mean(middle)
        tail_avg = _safe_mean(tail)
        tail_delta = tail_avg - mid_avg
        sustained_tail = sum(1 for x in des[-min(6, n) :] if x >= max(2.2, _safe_mean(des) * 1.15)) >= min(4, n)
        tail_drift = tail_delta > 0.28 and (tail_avg > max(mid_avg * 1.1, mid_avg + 0.2) or sustained_tail)
        tail_risk = min(1.0, max(0.0, tail_delta) * 1.35 + (0.25 if tail_drift else 0.0))

        zone_stats = [self._zone_de_stats(samples, z) for z in zones]
        transition_related = [z["risk_score"] for z in zone_stats if z["type"] in {"restart_zone", "transition_zone", "rework_zone"}]
        transition_risk = max(transition_related) if transition_related else 0.0
        overall_risk = max(float(transition_risk), float(tail_risk))
        return {
            "status": "ok",
            "roll_profile": profile,
            "sample_count": n,
            "avg_de": round(_safe_mean(des), 4),
            "max_de": round(max(des), 4),
            "head_mid_tail": {
                "head_avg_de": round(head_avg, 4),
                "middle_avg_de": round(mid_avg, 4),
                "tail_avg_de": round(tail_avg, 4),
                "tail_delta_vs_middle": round(tail_delta, 4),
            },
            "tail_sustained_drift": bool(tail_drift),
            "tail_risk_score": round(tail_risk, 4),
            "zone_stats": zone_stats,
            "transition_risk_score": round(float(transition_risk), 4),
            "overall_risk_score": round(float(overall_risk), 4),
            "zones": zones,
            "latest_meter": samples[-1]["meter_pos"],
        }

    def lot_summary(self, lot_id: str) -> dict[str, Any]:
        roll_ids = list(self._lot_rolls.get(lot_id, []))
        rows = [self.summary(rid) for rid in roll_ids]
        valid = [x for x in rows if x.get("status") == "ok"]
        if not valid:
            return {"lot_id": lot_id, "roll_count": len(roll_ids), "status": "no_valid_roll_data", "rows": rows}
        return {
            "lot_id": lot_id,
            "roll_count": len(roll_ids),
            "max_roll_risk": round(max(float(x.get("overall_risk_score", 0.0)) for x in valid), 4),
            "tail_drift_rolls": [x["roll_profile"]["roll_id"] for x in valid if x.get("tail_sustained_drift")],
            "rows": rows,
        }


class CrossBatchMatcherV2:
    def __init__(self) -> None:
        self._batches: dict[str, dict[str, Any]] = {}

    def register_batch(self, batch_id: str, data: dict[str, Any]) -> dict[str, Any]:
        duplicate = batch_id in self._batches
        payload = dict(data)
        payload["ts"] = _now_iso()
        self._batches[batch_id] = payload
        return {"registered": True, "batch_id": batch_id, "duplicate_overwrite": duplicate, "total": len(self._batches)}

    def find_match_recipe(self, target_batch_id: str, current_conditions: dict[str, Any] | None = None) -> dict[str, Any]:
        if target_batch_id not in self._batches:
            return {"error": "target_batch_not_found"}
        target = self._batches[target_batch_id]
        cur = dict(current_conditions or {})
        factors: list[dict[str, Any]] = []

        if isinstance(cur.get("substrate_lab"), dict) and isinstance(target.get("substrate_lab"), dict):
            d = de2000(target["substrate_lab"], cur["substrate_lab"])["total"]
            if d > 0.5:
                factors.append({"factor": "substrate", "impact": round(d * 0.7, 3), "desc": f"substrate_deltae={round(d,3)}"})

        if _is_number(cur.get("temp")) and _is_number(target.get("temp")):
            dt = abs(float(cur["temp"]) - float(target["temp"]))
            if dt > 2.0:
                factors.append({"factor": "temperature", "impact": round(dt * 0.05, 3), "desc": f"temperature_delta={round(dt,2)}C"})

        if cur.get("ink_lot") and target.get("ink_lot") and cur["ink_lot"] != target["ink_lot"]:
            factors.append({"factor": "ink_lot", "impact": 0.3, "desc": "ink_lot_changed"})

        if cur.get("machine_id") and target.get("machine_id") and cur["machine_id"] != target["machine_id"]:
            factors.append({"factor": "machine_transfer", "impact": 0.25, "desc": "production_machine_changed"})

        if cur.get("shift") and target.get("shift") and cur["shift"] != target["shift"]:
            factors.append({"factor": "shift_change", "impact": 0.12, "desc": "day_night_shift_changed"})

        if bool(cur.get("rework")):
            factors.append({"factor": "rework", "impact": 0.18, "desc": "rework_batch_extra_risk"})

        total_impact = round(sum(x["impact"] for x in factors), 3)
        rec = "reuse_recipe" if total_impact < 0.35 else "pilot_trial_then_release" if total_impact < 1.0 else "reformulate_and_requalify"
        return {
            "target_batch": target_batch_id,
            "target_lab": target.get("lab"),
            "target_recipe": target.get("recipe"),
            "change_factors": factors,
            "estimated_total_drift": total_impact,
            "recommendation": rec,
            "suggested_recipe": target.get("recipe"),
        }


class InkLotTrackerV2:
    def __init__(self) -> None:
        self._lots = defaultdict(list)
        self._index = set()

    def register(self, ink_model: str, lot_id: str, lab: dict[str, float], supplier: str = "") -> dict[str, Any]:
        lab_ok = _ensure_lab(lab)
        if lab_ok is None:
            return {"error": "invalid_lab"}
        key = (ink_model, lot_id)
        if key in self._index:
            return {"registered": False, "duplicate": True, "lot_id": lot_id}
        self._index.add(key)
        self._lots[ink_model].append({"lot": lot_id, "lab": lab_ok, "supplier": supplier, "ts": _now_iso()})
        return {"registered": True, "lot_id": lot_id, "total": len(self._lots[ink_model])}

    def lot_variation(self, ink_model: str) -> dict[str, Any]:
        lots = self._lots.get(ink_model, [])
        if len(lots) < 2:
            return {"status": "insufficient", "count": len(lots)}
        des = [de2000(lots[i - 1]["lab"], lots[i]["lab"])["total"] for i in range(1, len(lots))]
        return {
            "ink_model": ink_model,
            "lot_count": len(lots),
            "avg_lot_variation": round(_safe_mean(des), 4),
            "max_lot_variation": round(max(des), 4),
            "stable": max(des) < 1.0,
            "warning": "ink_lot_variation_high" if max(des) > 1.0 else None,
        }


class AutoCalibrationGuardV2:
    def __init__(self) -> None:
        self._calibrations: dict[str, dict[str, Any]] = {}

    def register_source(self, source: str, interval_hours: float) -> dict[str, Any]:
        self._calibrations[source] = {
            "interval": float(interval_hours),
            "last_cal": time.time(),
            "history": [],
        }
        return {"registered": True, "source": source}

    def check_status(self) -> dict[str, Any]:
        now = time.time()
        results: dict[str, dict[str, Any]] = {}
        overdue = 0
        for source, data in self._calibrations.items():
            elapsed = (now - data["last_cal"]) / 3600.0
            pct = elapsed / max(1e-6, data["interval"]) * 100.0
            status = "overdue" if pct > 100 else "warning" if pct > 80 else "ok"
            if status == "overdue":
                overdue += 1
            results[source] = {
                "elapsed_hours": round(elapsed, 3),
                "interval_hours": data["interval"],
                "progress_pct": round(min(250.0, pct), 3),
                "status": status,
            }
        return {
            "all_ok": overdue == 0,
            "sources": results,
            "overdue_count": overdue,
            "action": "recalibrate_now" if overdue else "ok",
        }

    def record_calibration(self, source: str, by: str = "", notes: str = "") -> dict[str, Any]:
        if source not in self._calibrations:
            return {"error": "source_not_found"}
        now = time.time()
        self._calibrations[source]["last_cal"] = now
        self._calibrations[source]["history"].append({"ts": _now_iso(), "by": by, "notes": notes})
        return {"recorded": True, "source": source}


class EdgeEffectAnalyzerV2:
    def analyze(self, de_grid: list[float], grid_shape: tuple[int, int] = (6, 8)) -> dict[str, Any]:
        rows, cols = grid_shape
        if len(de_grid) != rows * cols:
            return {"error": "grid_mismatch"}

        center: list[float] = []
        edges: list[float] = []
        by_edge = {"left": [], "right": [], "top": [], "bottom": []}

        for i, val in enumerate(de_grid):
            r = i // cols
            c = i % cols
            is_edge = r in {0, rows - 1} or c in {0, cols - 1}
            if is_edge:
                edges.append(float(val))
                if c == 0:
                    by_edge["left"].append(float(val))
                if c == cols - 1:
                    by_edge["right"].append(float(val))
                if r == 0:
                    by_edge["top"].append(float(val))
                if r == rows - 1:
                    by_edge["bottom"].append(float(val))
            else:
                center.append(float(val))

        if not center or not edges:
            return {"status": "grid_too_small"}

        center_avg = _safe_mean(center)
        edge_avg = _safe_mean(edges)
        diff = edge_avg - center_avg
        edge_details = {k: round(_safe_mean(v), 4) for k, v in by_edge.items() if v}
        worst_edge = max(edge_details, key=edge_details.get) if edge_details else None

        return {
            "center_avg_de": round(center_avg, 4),
            "edge_avg_de": round(edge_avg, 4),
            "center_edge_diff": round(diff, 4),
            "has_edge_effect": abs(diff) > 0.5,
            "edge_worse": diff > 0,
            "worst_edge": worst_edge,
            "edge_details": edge_details,
            "diagnosis": "edge_risk" if diff > 0.5 else "center_risk" if diff < -0.5 else "balanced",
            "possible_cause": "ink_supply_or_pressure_distribution" if abs(diff) > 0.5 else None,
        }

class RollerLifeTrackerV2:
    def __init__(self) -> None:
        self._rollers: dict[str, dict[str, Any]] = {}

    def register(self, roller_id: str, roller_type: str, max_meters: int = 500000) -> dict[str, Any]:
        self._rollers[roller_id] = {
            "type": roller_type,
            "installed": _now_iso(),
            "meters": 0,
            "max_meters": int(max_meters),
            "quality": [],
            "replacements": [],
        }
        return {"registered": True, "roller_id": roller_id}

    def update_meters(self, roller_id: str, meters: int, avg_de: float | None = None) -> dict[str, Any]:
        if roller_id not in self._rollers:
            return {"error": "roller_not_found"}
        r = self._rollers[roller_id]
        r["meters"] = int(meters)
        if _is_number(avg_de):
            r["quality"].append({"meters": int(meters), "de": float(avg_de), "ts": _now_iso()})
        return {"updated": True}

    def status(self, roller_id: str) -> dict[str, Any]:
        if roller_id not in self._rollers:
            return {"error": "roller_not_found"}
        r = self._rollers[roller_id]
        life_pct = r["meters"] / max(1, r["max_meters"]) * 100.0
        trend = None
        if len(r["quality"]) >= 5:
            first = _safe_mean([x["de"] for x in r["quality"][:3]])
            last = _safe_mean([x["de"] for x in r["quality"][-3:]])
            trend = "degrading" if last > first * 1.15 else "improving" if last < first * 0.9 else "stable"
        recommendation = "ok"
        if life_pct >= 95:
            recommendation = "replace_now"
        elif life_pct >= 75 or trend == "degrading":
            recommendation = "plan_replacement"
        return {
            "roller_id": roller_id,
            "type": r["type"],
            "meters": r["meters"],
            "max_meters": r["max_meters"],
            "life_pct": round(life_pct, 3),
            "life_status": "new" if life_pct < 30 else "mid" if life_pct < 70 else "aging" if life_pct < 100 else "overdue",
            "quality_trend": trend,
            "recommendation": recommendation,
        }


class GoldenSampleManagerV2:
    def __init__(self) -> None:
        self._samples: dict[str, dict[str, Any]] = {}

    def register(self, code: str, lab: dict[str, float], max_age_days: int = 90) -> dict[str, Any]:
        lab_ok = _ensure_lab(lab)
        if lab_ok is None:
            return {"error": "invalid_lab"}
        self._samples[code] = {"original": lab_ok, "current": lab_ok, "created": time.time(), "max_age": int(max_age_days), "checks": []}
        return {"registered": True, "code": code}

    def check(self, code: str, measured_lab: dict[str, float]) -> dict[str, Any]:
        if code not in self._samples:
            return {"error": "sample_not_found"}
        measured = _ensure_lab(measured_lab)
        if measured is None:
            return {"error": "invalid_measured_lab"}
        s = self._samples[code]
        d = de2000(s["original"], measured)
        age_days = (time.time() - s["created"]) / 86400.0
        s["current"] = measured
        s["checks"].append({"lab": measured, "de": d["total"], "ts": _now_iso()})
        drift_degrading = False
        if len(s["checks"]) >= 4:
            last4 = [x["de"] for x in s["checks"][-4:]]
            drift_degrading = all(last4[i] <= last4[i + 1] for i in range(3))

        degraded = d["total"] > 1.5
        expired = age_days > s["max_age"]
        status = "replace_now" if degraded or expired else "warning" if d["total"] > 1.0 or age_days > 0.8 * s["max_age"] else "ok"
        return {
            "code": code,
            "drift_from_original": round(d["total"], 4),
            "age_days": round(age_days, 3),
            "max_age_days": s["max_age"],
            "degraded": degraded,
            "expired": expired,
            "drift_trending_worse": drift_degrading,
            "status": status,
            "recommendation": "replace_now" if status == "replace_now" else "plan_replacement" if status == "warning" else "ok",
        }


class OperatorSkillTrackerV2:
    def __init__(self) -> None:
        self._operators = defaultdict(lambda: {"sessions": [], "total": 0, "first_pass": 0, "invalid_entries": 0})

    def record_session(self, operator: str, attempts: int, final_de: float, target_de: float = 2.5, operator_inputs: dict[str, Any] | None = None) -> dict[str, Any]:
        d = self._operators[operator]
        if not _is_number(attempts) or int(attempts) <= 0 or not _is_number(final_de):
            d["invalid_entries"] += 1
            return {"recorded": False, "error": "invalid_operator_input"}
        attempts = int(attempts)
        final_de = float(final_de)
        target_de = float(target_de)
        d["total"] += 1
        success = final_de <= target_de
        if attempts == 1 and success:
            d["first_pass"] += 1
        d["sessions"].append({"attempts": attempts, "final_de": final_de, "target_de": target_de, "success": success, "ts": _now_iso(), "inputs": operator_inputs or {}})
        if len(d["sessions"]) > 500:
            d["sessions"] = d["sessions"][-500:]
        return {"recorded": True, "total": d["total"]}

    def profile(self, operator: str) -> dict[str, Any]:
        d = self._operators.get(operator)
        if not d or d["total"] == 0:
            return {"operator": operator, "status": "no_data"}
        sessions = d["sessions"]
        fpr = d["first_pass"] / d["total"] * 100.0
        avg_attempts = _safe_mean([x["attempts"] for x in sessions])
        success_rate = sum(1 for x in sessions if x["success"]) / len(sessions) * 100.0
        avg_de = _safe_mean([x["final_de"] for x in sessions])

        if fpr > 70 and avg_de < 1.5:
            grade = "A_expert"
        elif fpr > 50 and avg_de < 2.0:
            grade = "B_skilled"
        elif success_rate > 70:
            grade = "C_adequate"
        else:
            grade = "D_training_needed"

        return {
            "operator": operator,
            "total_sessions": d["total"],
            "first_pass_rate": round(fpr, 3),
            "avg_attempts": round(avg_attempts, 3),
            "success_rate": round(success_rate, 3),
            "avg_final_de": round(avg_de, 4),
            "invalid_entries": d["invalid_entries"],
            "grade": grade,
        }

    def leaderboard(self) -> dict[str, Any]:
        rows = []
        for op, d in self._operators.items():
            if d["total"] <= 0:
                continue
            rows.append({"operator": op, "sessions": d["total"], "first_pass_rate": round(d["first_pass"] / d["total"] * 100.0, 3)})
        rows.sort(key=lambda x: x["first_pass_rate"], reverse=True)
        return {"leaderboard": rows}


class TraceabilityLedgerV2:
    REQUIRED_STAGES = [
        "ink_receipt",
        "substrate_receipt",
        "recipe_set",
        "printing",
        "inspection",
        "shipping",
    ]

    def __init__(self) -> None:
        self._chains: dict[str, dict[str, Any]] = {}

    def _hash_event(self, prev_hash: str, payload: dict[str, Any], nonce: str) -> str:
        txt = json.dumps({"prev_hash": prev_hash, "payload": payload, "nonce": nonce}, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(txt.encode("utf-8")).hexdigest()[:24]

    def add_event(
        self,
        lot_id: str,
        stage: str,
        data: dict[str, Any],
        event_id: str | None = None,
        actor: str = "",
        links: list[dict[str, str]] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        if lot_id not in self._chains:
            self._chains[lot_id] = {
                "events": [],
                "created": _now_iso(),
                "event_ids": set(),
                "event_idempotency": {},
                "anchors": [],
                "relations": [],
                "revisions": [],
                "overrides": [],
            }
        chain = self._chains[lot_id]
        idem_key = str(idempotency_key).strip() if idempotency_key else ""
        if idem_key:
            existed = chain["event_idempotency"].get(idem_key)
            if existed:
                return {"recorded": True, "event_id": existed, "deduplicated": True}
        event_id = event_id or f"{lot_id}-{len(chain['events'])+1:05d}"
        if event_id in chain["event_ids"]:
            return {"error": "duplicate_event_id", "event_id": event_id}

        prev_hash = chain["events"][-1]["hash"] if chain["events"] else "GENESIS"
        payload = {
            "stage": stage,
            "ts": _now_iso(),
            "data": data,
            "actor": actor,
            "event_id": event_id,
            "seq": len(chain["events"]) + 1,
        }
        nonce = hashlib.md5(f"{time.time_ns()}-{event_id}".encode("utf-8")).hexdigest()[:8]
        h = self._hash_event(prev_hash, payload, nonce)
        event = {**payload, "prev_hash": prev_hash, "nonce": nonce, "hash": h}
        chain["events"].append(event)
        chain["event_ids"].add(event_id)
        if idem_key:
            chain["event_idempotency"][idem_key] = event_id
        if links:
            chain["relations"].extend(links)
        return {"recorded": True, "event_id": event_id, "hash": h, "deduplicated": False}

    def add_revision(
        self,
        lot_id: str,
        target_event_id: str,
        patch: dict[str, Any],
        actor: str,
        reason: str,
    ) -> dict[str, Any]:
        if lot_id not in self._chains:
            return {"error": "lot_not_found"}
        chain = self._chains[lot_id]
        target = [x for x in chain["events"] if x.get("event_id") == target_event_id]
        if not target:
            return {"error": "target_event_not_found"}
        rev_id = f"{lot_id}-REV-{len(chain['revisions'])+1:05d}"
        rec = {
            "revision_id": rev_id,
            "target_event_id": target_event_id,
            "patch": dict(patch),
            "actor": actor,
            "reason": reason,
            "ts": _now_iso(),
        }
        chain["revisions"].append(rec)
        self.add_event(
            lot_id=lot_id,
            stage="event_revision",
            data={"revision_id": rev_id, "target_event_id": target_event_id, "reason": reason, "patch": patch},
            actor=actor,
            event_id=f"{lot_id}-EVR-{len(chain['events'])+1:05d}",
        )
        return {"recorded": True, "revision_id": rev_id}

    def add_override(
        self,
        lot_id: str,
        decision_ref: str,
        actor: str,
        approved_by: str,
        reason: str,
    ) -> dict[str, Any]:
        if lot_id not in self._chains:
            return {"error": "lot_not_found"}
        chain = self._chains[lot_id]
        override_id = f"{lot_id}-OVR-{len(chain['overrides'])+1:05d}"
        rec = {
            "override_id": override_id,
            "decision_ref": decision_ref,
            "actor": actor,
            "approved_by": approved_by,
            "reason": reason,
            "ts": _now_iso(),
        }
        chain["overrides"].append(rec)
        self.add_event(
            lot_id=lot_id,
            stage="manual_override",
            data={"override_id": override_id, "decision_ref": decision_ref, "approved_by": approved_by, "reason": reason},
            actor=actor,
            event_id=f"{lot_id}-OVE-{len(chain['events'])+1:05d}",
        )
        return {"recorded": True, "override_id": override_id}

    def anchor_chain(self, lot_id: str, note: str = "") -> dict[str, Any]:
        chain = self._chains.get(lot_id)
        if not chain:
            return {"error": "lot_not_found"}
        tip = chain["events"][-1]["hash"] if chain["events"] else "EMPTY"
        anchor = {"ts": _now_iso(), "tip_hash": tip, "note": note}
        chain["anchors"].append(anchor)
        return {"anchored": True, "tip_hash": tip, "anchor_count": len(chain["anchors"])}

    def validate_chain(self, lot_id: str) -> dict[str, Any]:
        chain = self._chains.get(lot_id)
        if not chain:
            return {"valid": False, "error": "lot_not_found"}
        prev = "GENESIS"
        valid = True
        broken_at = None
        for i, e in enumerate(chain["events"]):
            payload = {
                "stage": e["stage"],
                "ts": e["ts"],
                "data": e["data"],
                "actor": e["actor"],
                "event_id": e["event_id"],
                "seq": e.get("seq"),
            }
            expect = self._hash_event(prev, payload, e["nonce"])
            if e.get("prev_hash") != prev or e.get("hash") != expect:
                valid = False
                broken_at = i
                break
            prev = e["hash"]
        return {"valid": valid, "broken_at": broken_at}

    def get_chain(self, lot_id: str) -> dict[str, Any]:
        if lot_id not in self._chains:
            return {"error": "lot_not_found"}
        chain = self._chains[lot_id]
        valid = self.validate_chain(lot_id)
        stages = [e["stage"] for e in chain["events"]]
        missing = [s for s in self.REQUIRED_STAGES if s not in stages]
        stage_counts = defaultdict(int)
        for s in stages:
            stage_counts[s] += 1
        duplicate_stage = {k: v for k, v in stage_counts.items() if v > 1 and k in self.REQUIRED_STAGES}
        missing_diag = [{"stage": s, "severity": "high"} for s in missing]
        return {
            "lot_id": lot_id,
            "created": chain["created"],
            "event_count": len(chain["events"]),
            "stages_completed": stages,
            "events": chain["events"],
            "integrity": valid["valid"],
            "integrity_broken_at": valid.get("broken_at"),
            "missing_required_stages": missing,
            "missing_event_diagnostics": missing_diag,
            "duplicate_required_stage_counts": duplicate_stage,
            "anchors": chain["anchors"],
            "relations": chain["relations"],
            "revisions": chain.get("revisions", []),
            "overrides": chain.get("overrides", []),
        }

    def find_root_cause(self, lot_id: str, symptom: str) -> dict[str, Any]:
        chain = self._chains.get(lot_id, {}).get("events", [])
        if not chain:
            return {"error": "no_trace_data"}
        symptom = str(symptom)
        symptom_l = symptom.lower()
        is_yellow = ("偏黄" in symptom) or ("黄变" in symptom) or ("yellow" in symptom_l) or ("yell" in symptom_l)
        is_nonuniform = ("不均" in symptom) or ("发花" in symptom) or ("uneven" in symptom_l) or ("mottle" in symptom_l) or ("band" in symptom_l)
        suspects: list[dict[str, Any]] = []
        for e in chain:
            st = e.get("stage")
            data = e.get("data", {})
            if is_yellow and st == "printing":
                if _is_number(data.get("dry_temp")) and float(data.get("dry_temp")) > 70:
                    suspects.append({"stage": st, "factor": f"dry_temp_high:{data['dry_temp']}", "likelihood": "high"})
            if is_yellow and st == "substrate_receipt":
                if _is_number(data.get("substrate_db")) and float(data.get("substrate_db")) > 0.5:
                    suspects.append({"stage": st, "factor": "substrate_yellow_bias", "likelihood": "medium"})
            if is_nonuniform and st == "printing":
                if _is_number(data.get("roller_life_pct")) and float(data.get("roller_life_pct")) > 80:
                    suspects.append({"stage": st, "factor": f"roller_life_high:{data['roller_life_pct']}", "likelihood": "high"})

        conclusion = suspects[0]["factor"] if suspects else "no_confident_root_cause"
        return {"lot_id": lot_id, "symptom": symptom, "suspects": suspects, "conclusion": conclusion}


class RecipeVersionRegistryV2:
    def __init__(self) -> None:
        self._recipes: dict[str, dict[str, Any]] = {}

    def create_version(self, recipe_code: str, formula: dict[str, float], author: str, reason: str, approve: bool = False) -> dict[str, Any]:
        bucket = self._recipes.setdefault(recipe_code, {"versions": [], "active": None})
        ver = len(bucket["versions"]) + 1
        row = {
            "version": ver,
            "formula": dict(formula),
            "author": author,
            "reason": reason,
            "approved": bool(approve),
            "created": _now_iso(),
        }
        bucket["versions"].append(row)
        if approve:
            bucket["active"] = ver
        return {"recipe_code": recipe_code, "version": ver, "approved": row["approved"]}

    def approve_version(self, recipe_code: str, version: int, approver: str) -> dict[str, Any]:
        bucket = self._recipes.get(recipe_code)
        if not bucket:
            return {"error": "recipe_not_found"}
        rows = [x for x in bucket["versions"] if x["version"] == int(version)]
        if not rows:
            return {"error": "version_not_found"}
        rows[0]["approved"] = True
        rows[0]["approved_by"] = approver
        rows[0]["approved_at"] = _now_iso()
        bucket["active"] = int(version)
        return {"approved": True, "active": bucket["active"]}

    def rollback_to(self, recipe_code: str, version: int, operator: str) -> dict[str, Any]:
        bucket = self._recipes.get(recipe_code)
        if not bucket:
            return {"error": "recipe_not_found"}
        if not any(x["version"] == int(version) for x in bucket["versions"]):
            return {"error": "version_not_found"}
        bucket["active"] = int(version)
        return {"rolled_back": True, "active": bucket["active"], "operator": operator}


class CAPAEngineV2:
    def __init__(self) -> None:
        self._cases: dict[str, dict[str, Any]] = {}

    def auto_generate(self, lot_id: str, issue: str, root_cause: str, severity: str = "medium") -> dict[str, Any]:
        case_id = f"CAPA-{int(time.time())}-{len(self._cases)+1:04d}"
        actions = []
        if "data" in root_cause:
            actions = ["retrain_data_entry", "add_mandatory_field_validation", "enable_duplicate_id_block"]
        elif "process" in root_cause:
            actions = ["check_line_parameters", "tighten_changeover_quarantine", "verify_edge_pressure_balance"]
        elif "recipe" in root_cause:
            actions = ["recipe_review", "pilot_trial", "approve_new_recipe_version"]
        else:
            actions = ["cross_functional_review", "additional_sampling_plan"]
        self._cases[case_id] = {
            "case_id": case_id,
            "lot_id": lot_id,
            "issue": issue,
            "root_cause": root_cause,
            "severity": severity,
            "actions": actions,
            "status": "open",
            "created": _now_iso(),
            "closed": None,
            "outcome": None,
        }
        return self._cases[case_id]

    def close(self, case_id: str, outcome: str, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
        if case_id not in self._cases:
            return {"error": "capa_not_found"}
        row = self._cases[case_id]
        row["status"] = "closed"
        row["closed"] = _now_iso()
        row["outcome"] = outcome
        row["evidence"] = evidence or {}
        return {"closed": True, "case_id": case_id}

    def list_open(self) -> dict[str, Any]:
        return {"open": [x for x in self._cases.values() if x["status"] == "open"]}


class TimeStabilityManager:
    """
    Tracks 1h/4h/24h inspections and distinguishes current vs stable verdict.
    """

    def __init__(self) -> None:
        self._records: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def record(
        self,
        lot_id: str,
        elapsed_hours: float,
        lab: dict[str, float],
        stage: str = "recheck",
        verdict: str | None = None,
    ) -> dict[str, Any]:
        lab_ok = _ensure_lab(lab)
        if lab_ok is None:
            return {"error": "invalid_lab"}
        row = {
            "elapsed_hours": float(elapsed_hours),
            "lab": lab_ok,
            "stage": stage,
            "verdict": verdict,
            "ts": _now_iso(),
        }
        self._records[lot_id].append(row)
        self._records[lot_id].sort(key=lambda x: x["elapsed_hours"])
        return {"recorded": True, "count": len(self._records[lot_id])}

    def report(self, lot_id: str) -> dict[str, Any]:
        rows = self._records.get(lot_id, [])
        if not rows:
            return {"status": "no_data", "lot_id": lot_id}
        first = rows[0]
        latest = rows[-1]
        drift = de2000(first["lab"], latest["lab"])["total"]
        verdict_series = [x.get("verdict") for x in rows if x.get("verdict")]
        initial_pass_final_fail = len(verdict_series) >= 2 and verdict_series[0] in {"PASS", "pass"} and verdict_series[-1] in {"FAIL", "fail"}
        required_hold = latest["elapsed_hours"] < 4.0
        return {
            "lot_id": lot_id,
            "points": rows,
            "time_drift_de": round(drift, 4),
            "initial_pass_final_fail": initial_pass_final_fail,
            "current_state_verdict": verdict_series[-1] if verdict_series else None,
            "stable_state_verdict": verdict_series[-1] if latest["elapsed_hours"] >= 4.0 else None,
            "settling_time_insufficient": required_hold,
            "recommendation": "wait_for_stabilization" if required_hold else "stable_judgement_available",
        }


class ProcessCouplingRiskEngine:
    """
    Coupling-aware risk rules for gravure/digital/water/UV routes.
    """

    ROUTE_RANGES = {
        "gravure": {"viscosity": (15, 30), "line_speed": (40, 120), "dry_temp": (45, 80), "tension": (8, 30), "pressure": (1.0, 4.0)},
        "digital": {"viscosity": (2, 10), "line_speed": (5, 60), "dry_temp": (20, 60), "tension": (5, 20), "pressure": (0.5, 2.0)},
        "water": {"viscosity": (12, 28), "line_speed": (30, 100), "dry_temp": (40, 75), "tension": (8, 28), "pressure": (1.0, 3.5)},
        "uv": {"viscosity": (8, 20), "line_speed": (40, 150), "dry_temp": (20, 45), "tension": (8, 30), "pressure": (1.0, 3.5)},
    }

    def evaluate(self, params: dict[str, Any], route: str = "gravure") -> dict[str, Any]:
        route_key = route if route in self.ROUTE_RANGES else "gravure"
        ranges = self.ROUTE_RANGES[route_key]
        out_of_range: list[str] = []
        edge_risk: list[str] = []

        normalized: dict[str, float] = {}
        for key, (lo, hi) in ranges.items():
            val = params.get(key)
            if not _is_number(val):
                continue
            v = float(val)
            normalized[key] = v
            if v < lo or v > hi:
                out_of_range.append(f"{key}:{v}")
            elif (v - lo) / max(1e-6, hi - lo) < 0.1 or (hi - v) / max(1e-6, hi - lo) < 0.1:
                edge_risk.append(f"{key}_near_limit:{v}")

        coupling_alerts: list[str] = []
        visc = normalized.get("viscosity")
        speed = normalized.get("line_speed")
        temp = normalized.get("dry_temp")
        tension = normalized.get("tension")
        pressure = normalized.get("pressure")
        if visc is not None and speed is not None and visc > ranges["viscosity"][1] * 0.9 and speed > ranges["line_speed"][1] * 0.9:
            coupling_alerts.append("high_viscosity_high_speed_combo")
        if temp is not None and speed is not None and temp > ranges["dry_temp"][1] * 0.9 and speed > ranges["line_speed"][1] * 0.85:
            coupling_alerts.append("high_temp_high_speed_combo")
        if tension is not None and pressure is not None and tension > ranges["tension"][1] * 0.9 and pressure > ranges["pressure"][1] * 0.9:
            coupling_alerts.append("high_tension_high_pressure_combo")

        risk_score = 0.0
        risk_score += len(out_of_range) * 0.35
        risk_score += len(edge_risk) * 0.10
        risk_score += len(coupling_alerts) * 0.25
        risk_score = min(1.0, risk_score)

        return {
            "route": route_key,
            "risk_score": round(risk_score, 4),
            "out_of_range": out_of_range,
            "edge_risk": edge_risk,
            "coupling_alerts": coupling_alerts,
            "is_accident_edge": risk_score >= 0.7 or len(coupling_alerts) >= 2,
            "recommendation": "manual_review" if risk_score >= 0.45 else "monitor",
        }

    def reverse_infer(self, color_symptom: dict[str, Any], params: dict[str, Any], route: str = "gravure") -> dict[str, Any]:
        eval_out = self.evaluate(params, route=route)
        suspects = []
        dL = float(color_symptom.get("dL", 0.0) or 0.0)
        db = float(color_symptom.get("db", 0.0) or 0.0)
        if dL < -0.6 and "high_temp_high_speed_combo" in eval_out["coupling_alerts"]:
            suspects.append("over_drying_with_high_speed")
        if db > 0.6 and "high_temp_high_speed_combo" in eval_out["coupling_alerts"]:
            suspects.append("yellowing_due_to_thermal_stress")
        if "high_tension_high_pressure_combo" in eval_out["coupling_alerts"]:
            suspects.append("nonuniform_transfer_due_to_tension_pressure")
        return {"suspects": suspects, "coupling_evaluation": eval_out}


class FilmAppearanceRiskEngine:
    def evaluate(
        self,
        lab: dict[str, float],
        film_props: dict[str, Any],
        substrate_bases: list[dict[str, Any]] | None = None,
        observer_angles: list[float] | None = None,
    ) -> dict[str, Any]:
        lab_ok = _ensure_lab(lab)
        if lab_ok is None:
            return {"error": "invalid_lab"}
        opacity = float(film_props.get("opacity", 1.0) if _is_number(film_props.get("opacity")) else 1.0)
        haze = float(film_props.get("haze", 0.0) if _is_number(film_props.get("haze")) else 0.0)
        gloss = float(film_props.get("gloss", 0.0) if _is_number(film_props.get("gloss")) else 0.0)
        thickness = float(film_props.get("thickness_um", 60.0) if _is_number(film_props.get("thickness_um")) else 60.0)
        texture_dir = str(film_props.get("emboss_direction", "none")).lower()

        bases = substrate_bases or [
            {"name": "white", "lab": {"L": 96.0, "a": 0.0, "b": 1.0}},
            {"name": "gray", "lab": {"L": 70.0, "a": 0.0, "b": 0.0}},
            {"name": "wood", "lab": {"L": 62.0, "a": 5.0, "b": 18.0}},
            {"name": "metal", "lab": {"L": 76.0, "a": 0.2, "b": 2.5}},
        ]
        blended = []
        blend_alpha = max(0.05, min(1.0, opacity * (1.0 - min(0.6, haze / 100.0))))
        for b in bases:
            base_lab = _ensure_lab(b.get("lab"))
            if base_lab is None:
                continue
            mix = {
                "L": lab_ok["L"] * blend_alpha + base_lab["L"] * (1.0 - blend_alpha),
                "a": lab_ok["a"] * blend_alpha + base_lab["a"] * (1.0 - blend_alpha),
                "b": lab_ok["b"] * blend_alpha + base_lab["b"] * (1.0 - blend_alpha),
            }
            d = de2000(lab_ok, mix)["total"]
            blended.append({"base": b.get("name", "base"), "apparent_lab": {k: round(v, 3) for k, v in mix.items()}, "delta_from_free_film": round(d, 4)})

        angles = observer_angles or [0, 30, 60]
        angle_variation = []
        for ang in angles:
            factor = 1.0 + (gloss / 100.0) * abs(float(ang)) / 80.0
            factor *= 1.0 + min(0.15, abs(thickness - 60.0) / 400.0)
            if texture_dir in {"md", "td"}:
                factor *= 1.05
            angle_variation.append({"angle_deg": float(ang), "view_shift_factor": round(factor, 4)})

        max_base_shift = max((x["delta_from_free_film"] for x in blended), default=0.0)
        max_angle_factor = max((x["view_shift_factor"] for x in angle_variation), default=1.0)
        risk = min(1.0, max_base_shift / 3.0 + (max_angle_factor - 1.0))
        return {
            "blend_alpha": round(blend_alpha, 4),
            "base_appearance": blended,
            "angle_variation": angle_variation,
            "instrument_vs_installation_risk": round(risk, 4),
            "needs_visual_confirmation": risk >= 0.35,
        }


class CustomerScenarioEngine:
    def __init__(self) -> None:
        self._profiles: dict[str, dict[str, Any]] = {}

    def register_profile(self, customer_id: str, profile: dict[str, Any]) -> dict[str, Any]:
        self._profiles[customer_id] = {
            "profile": dict(profile),
            "updated_at": _now_iso(),
        }
        return {"registered": True, "customer_id": customer_id}

    def evaluate(self, customer_id: str, sku: str, scenario: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
        prof = self._profiles.get(customer_id, {}).get("profile", {})
        tolerance = float(prof.get("default_tolerance", 2.5))
        sku_tol_map = prof.get("sku_tolerance", {}) if isinstance(prof.get("sku_tolerance"), dict) else {}
        if sku in sku_tol_map and _is_number(sku_tol_map[sku]):
            tolerance = float(sku_tol_map[sku])
        light = str(scenario.get("light_source", "D65")).lower()
        if light in {"warm", "home", "2700k"}:
            tolerance *= 0.95
        if light in {"outdoor", "sunlight"}:
            tolerance *= 0.9
        sensitivity = prof.get("sensitivity", {}) if isinstance(prof.get("sensitivity"), dict) else {}
        yellow_sensitive = float(sensitivity.get("yellow", 1.0))
        uniform_sensitive = float(sensitivity.get("uniformity", 1.0))
        risk_score = 0.0
        risk_score += max(0.0, float(metrics.get("avg_de", 0.0)) - tolerance) * 0.5
        risk_score += max(0.0, float(metrics.get("max_de", 0.0)) - tolerance * 1.6) * 0.3
        risk_score += abs(float(metrics.get("db", 0.0))) * 0.03 * yellow_sensitive
        risk_score += max(0.0, float(metrics.get("uniformity_std", 0.0)) - 0.4) * 0.5 * uniform_sensitive
        return {
            "customer_id": customer_id,
            "sku": sku,
            "effective_tolerance": round(tolerance, 4),
            "risk_score": round(min(1.0, risk_score), 4),
            "risk_level": "high" if risk_score >= 0.7 else "medium" if risk_score >= 0.35 else "low",
            "light_source": light,
        }


class RetestDisputeManager:
    def __init__(self) -> None:
        self._records: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._status: dict[str, str] = defaultdict(lambda: "created")

    @staticmethod
    def _hash_record(prev_hash: str, payload: dict[str, Any]) -> str:
        txt = json.dumps({"prev_hash": prev_hash, "payload": payload}, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(txt.encode("utf-8")).hexdigest()[:24]

    def record(
        self,
        lot_id: str,
        test_type: str,
        device_id: str,
        operator: str,
        raw_result: dict[str, Any],
        compensated_result: dict[str, Any] | None,
        judgment_result: dict[str, Any],
        review_result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        prev_hash = self._records[lot_id][-1]["hash"] if self._records[lot_id] else "GENESIS"
        session_type = str(test_type).strip().lower().replace("-", "_").replace(" ", "_") or "retest"
        row = {
            "record_id": f"{lot_id}-INS-{len(self._records[lot_id]) + 1:05d}",
            "test_type": test_type,
            "session_type": session_type,
            "device_id": device_id,
            "operator": operator,
            "raw_result": dict(raw_result),
            "compensated_result": dict(compensated_result or {}),
            "judgment_result": dict(judgment_result),
            "review_result": dict(review_result or {}),
            "ts": _now_iso(),
            "seq": len(self._records[lot_id]) + 1,
            "prev_hash": prev_hash,
        }
        row["hash"] = self._hash_record(prev_hash, row)
        self._records[lot_id].append(row)
        self._status[lot_id] = "arbitration" if session_type == "arbitration" else "retesting"
        return {"recorded": True, "seq": row["seq"], "count": len(self._records[lot_id]), "record_id": row["record_id"]}

    def _validate_chain(self, lot_id: str) -> dict[str, Any]:
        rows = self._records.get(lot_id, [])
        prev = "GENESIS"
        for idx, row in enumerate(rows):
            payload = dict(row)
            got = payload.pop("hash", "")
            expect = self._hash_record(prev, payload)
            if expect != got or payload.get("prev_hash") != prev:
                return {"valid": False, "broken_at": idx}
            prev = got
        return {"valid": True, "broken_at": None}

    def dispute_report(self, lot_id: str) -> dict[str, Any]:
        rows = self._records.get(lot_id, [])
        if not rows:
            return {"status": "no_data", "lot_id": lot_id}
        chain = self._validate_chain(lot_id)
        tiers = [str(x.get("judgment_result", {}).get("tier", "")) for x in rows]
        conflict = len(set(tiers)) > 1
        device_set = sorted({x["device_id"] for x in rows})
        op_set = sorted({x["operator"] for x in rows})
        explanation = []
        if conflict:
            explanation.append("multiple_tiers_detected")
        if len(device_set) > 1:
            explanation.append("cross_device_variation")
        if len(op_set) > 1:
            explanation.append("cross_operator_variation")
        if not chain["valid"]:
            explanation.append("inspection_chain_broken")
        decision = "manual_arbitration_required" if (conflict or not chain["valid"]) else "latest_verdict_adopted"
        first = rows[0]
        latest = rows[-1]
        delta_avg_de = None
        if _is_number(first.get("raw_result", {}).get("avg_de")) and _is_number(latest.get("raw_result", {}).get("avg_de")):
            delta_avg_de = round(float(latest["raw_result"]["avg_de"]) - float(first["raw_result"]["avg_de"]), 4)
        return {
            "lot_id": lot_id,
            "records": rows,
            "conflict": conflict,
            "device_set": device_set,
            "operator_set": op_set,
            "decision": decision,
            "explanation": explanation,
            "inspection_chain_integrity": bool(chain["valid"]),
            "broken_at": chain["broken_at"],
            "session_state": self._status.get(lot_id, "created"),
            "dispute_explanation_report": {
                "first_tier": tiers[0] if tiers else None,
                "latest_tier": tiers[-1] if tiers else None,
                "delta_avg_de_first_to_latest": delta_avg_de,
                "why_different": explanation,
            },
        }


class MultiMachineConsistencyEngine:
    def __init__(self) -> None:
        self._records: list[dict[str, Any]] = []

    def record(self, machine_id: str, plant_id: str, sku: str, dL: float, da: float, db: float) -> dict[str, Any]:
        self._records.append(
            {
                "machine_id": machine_id,
                "plant_id": plant_id,
                "sku": sku,
                "dL": float(dL),
                "da": float(da),
                "db": float(db),
                "ts": _now_iso(),
            }
        )
        if len(self._records) > 20000:
            self._records = self._records[-20000:]
        return {"recorded": True, "count": len(self._records)}

    def fingerprint(self, machine_id: str, sku: str | None = None) -> dict[str, Any]:
        rows = [x for x in self._records if x["machine_id"] == machine_id and (sku is None or x["sku"] == sku)]
        if not rows:
            return {"status": "no_data", "machine_id": machine_id}
        return {
            "machine_id": machine_id,
            "sku": sku,
            "samples": len(rows),
            "avg_dL": round(_safe_mean([x["dL"] for x in rows]), 4),
            "avg_da": round(_safe_mean([x["da"] for x in rows]), 4),
            "avg_db": round(_safe_mean([x["db"] for x in rows]), 4),
        }

    def chronic_bias_report(self) -> dict[str, Any]:
        machines = sorted({x["machine_id"] for x in self._records})
        out = []
        for m in machines:
            fp = self.fingerprint(m)
            if fp.get("status") == "no_data":
                continue
            bias = "yellow" if fp["avg_db"] > 0.4 else "dark" if fp["avg_dL"] < -0.4 else "none"
            out.append({"machine_id": m, "bias": bias, "avg_dL": fp["avg_dL"], "avg_db": fp["avg_db"], "samples": fp["samples"]})
        return {"machines": out}


class LearningLoopEngine:
    def __init__(self) -> None:
        self._events: list[dict[str, Any]] = []
        self._cause_stats: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    def record(
        self,
        context_key: str,
        predicted_cause: str,
        actual_cause: str,
        success: bool,
        rule_source: str = "heuristic",
    ) -> dict[str, Any]:
        row = {
            "context_key": context_key,
            "predicted_cause": predicted_cause,
            "actual_cause": actual_cause,
            "success": bool(success),
            "rule_source": rule_source,
            "ts": _now_iso(),
        }
        self._events.append(row)
        self._cause_stats[context_key][actual_cause] += 1
        if len(self._events) > 100000:
            self._events = self._events[-100000:]
        return {"recorded": True, "count": len(self._events)}

    def cause_priority(self, context_key: str) -> dict[str, Any]:
        stats = self._cause_stats.get(context_key, {})
        total = sum(stats.values())
        if total <= 0:
            return {"context_key": context_key, "priorities": [], "source": "none"}
        rows = [{"cause": k, "weight": round(v / total, 4)} for k, v in sorted(stats.items(), key=lambda x: x[1], reverse=True)]
        return {"context_key": context_key, "priorities": rows, "source": "learned"}


class DecisionEnvelopeV2:
    @staticmethod
    def _risk_level(score: float) -> str:
        s = float(score)
        if s >= 0.85:
            return "critical"
        if s >= 0.65:
            return "high"
        if s >= 0.35:
            return "medium"
        return "low"

    @classmethod
    def build(
        cls,
        status: str,
        risk_score: float,
        confidence: float,
        blocking: bool,
        warnings: list[str] | None = None,
        explanations: list[str] | None = None,
        recommendations: list[str] | None = None,
        evidence: list[dict[str, Any]] | None = None,
        next_actions: list[dict[str, Any]] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "status": status,
            "risk_level": cls._risk_level(risk_score),
            "risk_score": round(float(max(0.0, min(1.0, risk_score))), 4),
            "confidence": round(float(max(0.0, min(1.0, confidence))), 4),
            "blocking": bool(blocking),
            "warnings": list(warnings or []),
            "explanations": list(explanations or []),
            "recommendations": list(recommendations or []),
            "evidence": list(evidence or []),
            "next_actions": list(next_actions or []),
            "payload": dict(payload or {}),
        }


class DataIntegrityGuardV2:
    """
    Lifecycle-level validation and idempotency guard.
    """

    def __init__(self) -> None:
        self._idempotency: dict[str, str] = {}
        self._submission_cache: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _hash_payload(payload: dict[str, Any]) -> str:
        body = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(body.encode("utf-8")).hexdigest()[:24]

    def check_idempotency(self, idempotency_key: str | None, payload: dict[str, Any]) -> dict[str, Any]:
        if not idempotency_key:
            return {"ok": True, "duplicate": False}
        key = str(idempotency_key)
        digest = self._hash_payload(payload)
        if key in self._idempotency:
            same = self._idempotency[key] == digest
            return {
                "ok": same,
                "duplicate": True,
                "same_payload": same,
                "error": None if same else "idempotency_key_payload_mismatch",
            }
        self._idempotency[key] = digest
        return {"ok": True, "duplicate": False}

    def cache_submission(self, idempotency_key: str | None, result: dict[str, Any]) -> None:
        if idempotency_key:
            self._submission_cache[str(idempotency_key)] = dict(result)

    def get_cached_submission(self, idempotency_key: str | None) -> dict[str, Any] | None:
        if not idempotency_key:
            return None
        row = self._submission_cache.get(str(idempotency_key))
        return dict(row) if isinstance(row, dict) else None

    def validate_assessment_inputs(
        self,
        lot_id: str,
        base_decision: dict[str, Any],
        color_metrics: dict[str, Any],
        meta: dict[str, Any],
    ) -> dict[str, Any]:
        errors: list[str] = []
        warnings: list[str] = []
        evidence: list[dict[str, Any]] = []
        required_color = ["avg_de", "max_de"]
        for k in required_color:
            if k not in color_metrics or not _is_number(color_metrics.get(k)):
                errors.append(f"missing_or_invalid_color_metric:{k}")
        if not lot_id:
            errors.append("lot_id_empty")
        quality_gate = base_decision.get("quality_gate")
        if quality_gate is not None and not isinstance(quality_gate, dict):
            errors.append("quality_gate_invalid_type")
        if _is_number(meta.get("decision_ts")) and float(meta["decision_ts"]) > time.time() + 3600:
            warnings.append("decision_ts_in_future")
        if _is_number(meta.get("suspicious_ratio")) and float(meta["suspicious_ratio"]) > 0.2:
            warnings.append("high_suspicious_ratio_in_meta")

        completeness_score = 1.0
        completeness_score -= min(0.8, len(errors) * 0.2)
        completeness_score -= min(0.3, len(warnings) * 0.05)
        completeness_score = max(0.0, completeness_score)

        evidence.append(
            {
                "source": "data_integrity_guard",
                "strength": "high" if not errors else "medium",
                "details": {
                    "errors": len(errors),
                    "warnings": len(warnings),
                    "completeness_score": round(completeness_score, 4),
                },
            }
        )
        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "completeness_score": round(completeness_score, 4),
            "data_trust_score": round(completeness_score * (0.95 if not warnings else 0.85), 4),
            "evidence": evidence,
        }

    def validate_event_payload(self, stage: str, data: dict[str, Any], ts: float | None = None) -> dict[str, Any]:
        if not isinstance(data, dict):
            return {"valid": False, "errors": ["event_data_not_dict"], "warnings": []}
        req_map = {
            "ink_receipt": ["lot"],
            "substrate_receipt": ["lot"],
            "recipe_set": ["recipe_code"],
            "printing": ["line_speed"],
            "inspection": ["avg_de"],
            "shipping": ["shipment_id"],
        }
        errors: list[str] = []
        warnings: list[str] = []
        for key in req_map.get(stage, []):
            if key not in data:
                errors.append(f"missing_field:{key}")
        if _is_number(ts) and float(ts) > time.time() + 3600:
            warnings.append("event_ts_future")
        return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}


class MeasurementSystemGuardV2:
    """
    MSA/Gauge capability approximation for runtime blocking decisions.
    """

    def __init__(self) -> None:
        self._records: list[dict[str, Any]] = []

    def record(
        self,
        lot_id: str,
        sample_id: str,
        device_id: str,
        operator_id: str,
        lab: dict[str, float],
        ts: float | None = None,
    ) -> dict[str, Any]:
        lab_ok = _ensure_lab(lab)
        if lab_ok is None:
            return {"recorded": False, "error": "invalid_lab"}
        row = {
            "lot_id": lot_id,
            "sample_id": sample_id,
            "device_id": device_id,
            "operator_id": operator_id,
            "lab": lab_ok,
            "ts": float(ts if ts is not None else time.time()),
            "iso": _now_iso(),
        }
        self._records.append(row)
        if len(self._records) > 50000:
            self._records = self._records[-50000:]
        return {"recorded": True, "count": len(self._records)}

    @staticmethod
    def _std(values: list[float]) -> float:
        return statistics.stdev(values) if len(values) > 1 else 0.0

    def report(self, lot_id: str | None = None, window: int = 500) -> dict[str, Any]:
        rows = self._records[-max(1, int(window)) :]
        if lot_id:
            rows = [x for x in rows if x["lot_id"] == lot_id]
        if len(rows) < 6:
            return {
                "status": "insufficient_data",
                "sample_count": len(rows),
                "repeatability_std": None,
                "reproducibility_std": None,
                "gage_risk_score": 0.5,
                "measurement_confidence": 0.4,
                "blocking": False,
                "warnings": ["msa_insufficient_data"],
            }

        by_sample_device_op: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
        for r in rows:
            by_sample_device_op[(r["sample_id"], r["device_id"], r["operator_id"])].append(r)

        repeatability_de: list[float] = []
        for group in by_sample_device_op.values():
            if len(group) < 2:
                continue
            labs = [x["lab"] for x in group]
            ref = labs[0]
            repeatability_de.extend([de2000(ref, l)["total"] for l in labs[1:]])
        repeatability_std = self._std(repeatability_de) if repeatability_de else 0.0

        # Reproducibility: compare operator/device means on same sample_id.
        by_sample: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in rows:
            by_sample[r["sample_id"]].append(r)
        reproducibility_de: list[float] = []
        for sample_rows in by_sample.values():
            if len(sample_rows) < 2:
                continue
            labs = [x["lab"] for x in sample_rows]
            base = labs[0]
            reproducibility_de.extend([de2000(base, l)["total"] for l in labs[1:]])
        reproducibility_std = self._std(reproducibility_de) if reproducibility_de else 0.0

        risk = min(1.0, repeatability_std * 1.8 + reproducibility_std * 1.2)
        conf = max(0.05, 1.0 - risk)
        gage_status = "capable" if risk < 0.3 else "marginal" if risk < 0.6 else "incapable"
        blocking = risk >= 0.75
        warnings: list[str] = []
        if risk >= 0.6:
            warnings.append("msa_risk_high")
        if repeatability_std > 0.35:
            warnings.append("repeatability_poor")
        if reproducibility_std > 0.4:
            warnings.append("reproducibility_poor")
        return {
            "status": "ok",
            "sample_count": len(rows),
            "repeatability_std": round(repeatability_std, 4),
            "reproducibility_std": round(reproducibility_std, 4),
            "gage_risk_score": round(risk, 4),
            "measurement_confidence": round(conf, 4),
            "gage_status": gage_status,
            "blocking": blocking,
            "warnings": warnings,
        }


class SPCMonitorV2:
    """
    Control-chart style monitoring for center and spread stability.
    """

    def __init__(self) -> None:
        self._streams: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def add_point(self, stream_id: str, value: float, ts: float | None = None, meta: dict[str, Any] | None = None) -> dict[str, Any]:
        if not _is_number(value):
            return {"recorded": False, "error": "value_not_numeric"}
        row = {
            "value": float(value),
            "ts": float(ts if ts is not None else time.time()),
            "iso": _now_iso(),
            "meta": dict(meta or {}),
        }
        self._streams[stream_id].append(row)
        if len(self._streams[stream_id]) > 20000:
            self._streams[stream_id] = self._streams[stream_id][-20000:]
        return {"recorded": True, "count": len(self._streams[stream_id])}

    def report(self, stream_id: str, window: int = 100) -> dict[str, Any]:
        rows = self._streams.get(stream_id, [])[-max(5, int(window)) :]
        if len(rows) < 8:
            return {"status": "insufficient_data", "stream_id": stream_id, "stable": True, "warnings": ["spc_insufficient_data"]}
        vals = [x["value"] for x in rows]
        center = _safe_mean(vals)
        sigma = statistics.stdev(vals) if len(vals) > 1 else 0.0
        ucl = center + 3 * sigma
        lcl = center - 3 * sigma
        out_of_control = [i for i, v in enumerate(vals) if v > ucl or v < lcl]

        trend_up = len(vals) >= 7 and all(vals[-7 + i] < vals[-6 + i] for i in range(6))
        trend_down = len(vals) >= 7 and all(vals[-7 + i] > vals[-6 + i] for i in range(6))
        one_side = False
        if len(vals) >= 8:
            last8 = vals[-8:]
            one_side = all(v > center for v in last8) or all(v < center for v in last8)

        half = len(vals) // 2
        first = vals[:half]
        second = vals[half:]
        mean_shift = _safe_mean(second) - _safe_mean(first)
        std_shift = (statistics.stdev(second) if len(second) > 1 else 0.0) - (statistics.stdev(first) if len(first) > 1 else 0.0)
        spread_growth = std_shift > max(0.15, (statistics.stdev(first) if len(first) > 1 else 0.0) * 0.3)

        warnings: list[str] = []
        if out_of_control:
            warnings.append("spc_out_of_control")
        if trend_up:
            warnings.append("spc_trend_up")
        if trend_down:
            warnings.append("spc_trend_down")
        if one_side:
            warnings.append("spc_run_one_side")
        if spread_growth:
            warnings.append("spc_spread_growth")

        special_cause = any(x in warnings for x in ["spc_out_of_control", "spc_trend_up", "spc_trend_down", "spc_run_one_side"])
        risk = min(1.0, len(warnings) * 0.18 + (0.25 if spread_growth else 0.0))
        return {
            "status": "ok",
            "stream_id": stream_id,
            "count": len(vals),
            "center": round(center, 4),
            "sigma": round(sigma, 4),
            "ucl": round(ucl, 4),
            "lcl": round(lcl, 4),
            "mean_shift": round(mean_shift, 4),
            "spread_shift": round(std_shift, 4),
            "special_cause": special_cause,
            "stable": len(warnings) == 0,
            "risk_score": round(risk, 4),
            "warnings": warnings,
        }


class MetamerismRiskEngineV2:
    """
    Proxy metamerism risk using multi-light deltas and film properties.
    """

    def evaluate(
        self,
        lab_d65: dict[str, float],
        alt_lights: dict[str, dict[str, float]] | None = None,
        film_props: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        base = _ensure_lab(lab_d65)
        if base is None:
            return {"error": "invalid_lab_d65"}
        fp = dict(film_props or {})
        alt = alt_lights or {}
        if not alt:
            # Conservative synthetic offsets when no alternate illuminants provided.
            alt = {
                "A_2856K": {"L": base["L"] - 0.45, "a": base["a"] + 0.15, "b": base["b"] + 0.75},
                "F11_store": {"L": base["L"] - 0.25, "a": base["a"] + 0.1, "b": base["b"] + 0.45},
            }
        rows: list[dict[str, Any]] = []
        for name, lv in alt.items():
            lab = _ensure_lab(lv)
            if lab is None:
                continue
            d = de2000(base, lab)["total"]
            rows.append({"light": name, "delta_from_d65": round(d, 4)})
        max_delta = max((x["delta_from_d65"] for x in rows), default=0.0)
        opacity = float(fp.get("opacity", 1.0) if _is_number(fp.get("opacity")) else 1.0)
        gloss = float(fp.get("gloss", 0.0) if _is_number(fp.get("gloss")) else 0.0)
        risk = min(1.0, max_delta / 3.5 + (0.12 if opacity < 0.55 else 0.0) + (0.08 if gloss > 60 else 0.0))
        return {
            "metamerism_risk_score": round(risk, 4),
            "max_light_delta": round(max_delta, 4),
            "lights": rows,
            "needs_visual_confirmation": risk >= 0.35,
            "blocking_recommendation": risk >= 0.75,
        }


class PostProcessImpactPredictorV2:
    def predict(self, lab: dict[str, float], steps: list[str] | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
        src = _ensure_lab(lab)
        if src is None:
            return {"error": "invalid_lab"}
        ctx = dict(context or {})
        out = dict(src)
        shifts = {"L": 0.0, "a": 0.0, "b": 0.0}
        for step in (steps or []):
            tag = str(step).lower()
            if tag == "lamination":
                shifts["L"] -= 0.2
                shifts["b"] += 0.08
            elif tag == "adhesive":
                shifts["L"] -= 0.05
                shifts["b"] += 0.12
            elif tag == "embossing":
                shifts["L"] += 0.06
                shifts["a"] += 0.04
            elif tag == "hot_press":
                shifts["L"] -= 0.1
                shifts["b"] += 0.06
            elif tag == "composite":
                shifts["L"] -= 0.12
                shifts["a"] += 0.03
        if _is_number(ctx.get("press_temp")) and float(ctx["press_temp"]) > 75:
            shifts["b"] += 0.08
        if _is_number(ctx.get("storage_days")) and float(ctx["storage_days"]) > 10:
            shifts["L"] -= min(0.5, float(ctx["storage_days"]) * 0.01)
            shifts["b"] += min(0.4, float(ctx["storage_days"]) * 0.008)
        for k in ("L", "a", "b"):
            out[k] = round(out[k] + shifts[k], 4)
        d = de2000(src, out)["total"]
        risk = min(1.0, d / 3.0)
        return {
            "predicted_lab_after_post_process": out,
            "post_process_shift_de": round(d, 4),
            "risk_score": round(risk, 4),
            "blocking_recommendation": risk >= 0.75,
            "steps": list(steps or []),
        }


class StorageTransportStabilityPredictorV2:
    def predict(
        self,
        lab: dict[str, float],
        storage_days: float,
        temp_c: float,
        humidity_pct: float,
        uv_hours: float = 0.0,
        vibration_index: float = 0.0,
    ) -> dict[str, Any]:
        src = _ensure_lab(lab)
        if src is None:
            return {"error": "invalid_lab"}
        days = max(0.0, float(storage_days))
        t = float(temp_c)
        h = float(humidity_pct)
        uv = max(0.0, float(uv_hours))
        vib = max(0.0, float(vibration_index))

        shifts = {
            "L": -min(0.8, days * 0.008 + max(0.0, t - 30) * 0.01),
            "a": 0.0 + max(0.0, t - 35) * 0.003,
            "b": min(1.0, days * 0.01 + max(0.0, h - 70) * 0.01 + uv * 0.002),
        }
        if vib > 0.5:
            shifts["L"] -= min(0.2, vib * 0.12)
        out = {k: round(src[k] + shifts[k], 4) for k in ("L", "a", "b")}
        d = de2000(src, out)["total"]
        risk = min(1.0, d / 3.2)
        return {
            "predicted_lab_after_storage_transport": out,
            "delayed_drift_de": round(d, 4),
            "risk_score": round(risk, 4),
            "shelf_life_warning": days > 90 or risk >= 0.55,
            "blocking_recommendation": risk >= 0.8,
        }


class LifecycleStateMachineV2:
    STATES = [
        "created",
        "material_received",
        "ink_received",
        "recipe_prepared",
        "trial_started",
        "in_run_monitoring",
        "hold_for_review",
        "rework",
        "retest",
        "arbitration",
        "released",
        "shipped",
        "complaint_opened",
        "capa_open",
        "capa_closed",
    ]

    TRANSITIONS = {
        "created": {"material_received", "ink_received"},
        "material_received": {"ink_received", "recipe_prepared"},
        "ink_received": {"material_received", "recipe_prepared"},
        "recipe_prepared": {"trial_started", "hold_for_review"},
        "trial_started": {"in_run_monitoring", "hold_for_review"},
        "in_run_monitoring": {"hold_for_review", "released", "rework", "retest"},
        "hold_for_review": {"retest", "arbitration", "rework", "released"},
        "retest": {"arbitration", "released", "rework", "hold_for_review"},
        "arbitration": {"released", "rework", "hold_for_review"},
        "rework": {"trial_started", "retest", "hold_for_review"},
        "released": {"shipped", "complaint_opened"},
        "shipped": {"complaint_opened"},
        "complaint_opened": {"capa_open"},
        "capa_open": {"capa_closed"},
        "capa_closed": set(),
    }

    def __init__(self) -> None:
        self._state: dict[str, str] = {}
        self._history: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def transition(
        self,
        lot_id: str,
        to_state: str,
        actor: str,
        reason: str = "",
        evidence: dict[str, Any] | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        target = str(to_state)
        if target not in self.STATES:
            return {"ok": False, "error": "invalid_state"}
        cur = self._state.get(lot_id, "created")
        allowed = target in self.TRANSITIONS.get(cur, set())
        if cur == target:
            allowed = True
        if not allowed and not force:
            return {"ok": False, "error": "illegal_transition", "from": cur, "to": target}
        row = {
            "lot_id": lot_id,
            "from": cur,
            "to": target,
            "actor": actor,
            "reason": reason,
            "evidence": dict(evidence or {}),
            "forced": bool(force and not allowed),
            "ts": _now_iso(),
        }
        self._history[lot_id].append(row)
        self._state[lot_id] = target
        return {"ok": True, "state": target, "history_count": len(self._history[lot_id]), "forced": row["forced"]}

    def snapshot(self, lot_id: str) -> dict[str, Any]:
        state = self._state.get(lot_id, "created")
        hist = self._history.get(lot_id, [])
        return {"lot_id": lot_id, "current_state": state, "history": list(hist), "history_count": len(hist)}


class FailureModeRegistryV2:
    def __init__(self) -> None:
        self._modes: dict[str, dict[str, Any]] = {}
        self._init_defaults()

    def _init_defaults(self) -> None:
        for row in [
            {"mode_id": "FM-CAL-OVERDUE", "desc": "calibration overdue", "severity": 9, "occurrence": 4, "detectability": 3, "category": "measurement"},
            {"mode_id": "FM-TRACE-MISSING", "desc": "traceability required stage missing", "severity": 8, "occurrence": 5, "detectability": 4, "category": "traceability"},
            {"mode_id": "FM-GOLDEN-DRIFT", "desc": "golden sample drift", "severity": 8, "occurrence": 4, "detectability": 5, "category": "reference"},
            {"mode_id": "FM-MSA-POOR", "desc": "measurement repeatability/reproducibility poor", "severity": 9, "occurrence": 3, "detectability": 6, "category": "measurement"},
            {"mode_id": "FM-SPC-UNSTABLE", "desc": "process unstable in spc", "severity": 7, "occurrence": 6, "detectability": 4, "category": "process"},
        ]:
            self.register(**row)

    def register(self, mode_id: str, desc: str, severity: int, occurrence: int, detectability: int, category: str = "general") -> dict[str, Any]:
        sev = max(1, min(10, int(severity)))
        occ = max(1, min(10, int(occurrence)))
        det = max(1, min(10, int(detectability)))
        rpn = sev * occ * det
        self._modes[mode_id] = {
            "mode_id": mode_id,
            "desc": desc,
            "severity": sev,
            "occurrence": occ,
            "detectability": det,
            "rpn": rpn,
            "category": category,
            "updated_at": _now_iso(),
        }
        return {"registered": True, "mode_id": mode_id, "rpn": rpn}

    def list_modes(self) -> dict[str, Any]:
        rows = sorted(self._modes.values(), key=lambda x: x["rpn"], reverse=True)
        return {"count": len(rows), "rows": rows}

    def capa_candidates(self, triggers: list[str]) -> dict[str, Any]:
        mapping = {
            "calibration_overdue": ["立即停机校准", "校准周期缩短并纳入班前检查"],
            "trace_missing_required_events": ["补录缺失事件并标记补录原因", "关键节点设置强制录入门禁"],
            "golden_sample_invalid": ["更换金样并复验", "提高金样巡检频率"],
            "repeatability_too_poor": ["执行MSA复核", "锁定设备与操作员组合做仲裁测量"],
            "spc_out_of_control": ["暂停自动放行", "排查特殊原因并隔离风险段"],
        }
        actions: list[str] = []
        for t in triggers:
            actions.extend(mapping.get(t, []))
        dedup = []
        seen = set()
        for a in actions:
            if a not in seen:
                dedup.append(a)
                seen.add(a)
        return {"triggers": triggers, "actions": dedup[:10]}


class AlertCenterV2:
    def __init__(self, dedup_seconds: int = 600) -> None:
        self._dedup_seconds = max(30, int(dedup_seconds))
        self._alerts: list[dict[str, Any]] = []
        self._last_seen: dict[str, dict[str, Any]] = {}

    def push(
        self,
        alert_type: str,
        severity: str,
        message: str,
        source: str,
        evidence: dict[str, Any] | None = None,
        dedup_key: str | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        key = dedup_key or f"{alert_type}|{source}|{message}"
        prev = self._last_seen.get(key)
        if prev and now - prev["ts"] <= self._dedup_seconds:
            prev["count"] += 1
            prev["last_ts"] = _now_iso()
            return {"recorded": False, "deduped": True, "count": prev["count"], "alert_id": prev["alert_id"]}
        row = {
            "alert_id": f"ALT-{int(now)}-{len(self._alerts)+1:05d}",
            "type": alert_type,
            "severity": severity,
            "message": message,
            "source": source,
            "evidence": dict(evidence or {}),
            "ts": now,
            "iso": _now_iso(),
            "count": 1,
        }
        self._alerts.append(row)
        self._last_seen[key] = {"alert_id": row["alert_id"], "ts": now, "count": 1, "last_ts": row["iso"]}
        if len(self._alerts) > 10000:
            self._alerts = self._alerts[-10000:]
        return {"recorded": True, "deduped": False, "alert_id": row["alert_id"]}

    def summary(self, last_n: int = 50) -> dict[str, Any]:
        rows = self._alerts[-max(1, int(last_n)) :]
        grouped: dict[str, int] = defaultdict(int)
        for r in rows:
            grouped[r["type"]] += 1
        return {"count": len(rows), "alerts": rows, "grouped": dict(grouped)}


class QualityCaseCenterV2:
    """
    Lightweight quality case workflow:
    nonconformance -> actions -> verification -> closure.
    """

    STATES = ["open", "investigating", "action_planned", "action_in_progress", "verification", "closed", "cancelled"]
    TRANSITIONS = {
        "open": {"investigating", "cancelled"},
        "investigating": {"action_planned", "cancelled"},
        "action_planned": {"action_in_progress", "cancelled"},
        "action_in_progress": {"verification", "cancelled"},
        "verification": {"closed", "action_in_progress", "cancelled"},
        "closed": set(),
        "cancelled": set(),
    }

    def __init__(self, store_path: str | None = None, db_path: str | None = None) -> None:
        self._lock = RLock()
        self._cases: dict[str, dict[str, Any]] = {}
        self._events: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._dedup: dict[str, str] = {}
        self._actions: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._role_rank = {
            "operator": 1,
            "supervisor": 2,
            "engineer": 2,
            "qa_manager": 3,
            "quality_manager": 3,
            "plant_manager": 4,
            "director": 5,
        }
        self._waiver_policy = {
            "low": {"standard": "supervisor", "vip": "qa_manager"},
            "medium": {"standard": "qa_manager", "vip": "quality_manager"},
            "high": {"standard": "quality_manager", "vip": "plant_manager"},
            "critical": {"standard": "plant_manager", "vip": "director"},
        }
        path = str(store_path or "").strip()
        db = str(db_path or "").strip()
        self._store_path = path if path else None
        self._db_path = db if db else None
        backend = "memory"
        if self._db_path:
            backend = "sqlite"
        elif self._store_path:
            backend = "json_file"
        self._store_meta: dict[str, Any] = {
            "enabled": bool(self._store_path or self._db_path),
            "backend": backend,
            "loaded": False,
            "persist_count": 0,
            "last_load_iso": "",
            "last_persist_iso": "",
            "last_error": "",
        }
        self._load_store()

    @staticmethod
    def _norm_role(role: str) -> str:
        return str(role).strip().lower().replace("-", "_").replace(" ", "_")

    def _rank(self, role: str) -> int:
        return int(self._role_rank.get(self._norm_role(role), 0))

    def _required_approver(
        self,
        severity: str,
        customer_tier: str = "standard",
    ) -> str:
        sev = str(severity).strip().lower()
        if sev not in self._waiver_policy:
            sev = "high"
        tier = str(customer_tier).strip().lower()
        if tier not in {"standard", "vip"}:
            tier = "standard"
        return str(self._waiver_policy.get(sev, {}).get(tier, "quality_manager"))

    def _normalize_open_action_count(self) -> None:
        for cid, case in self._cases.items():
            open_cnt = sum(1 for x in self._actions.get(cid, []) if x.get("status") != "completed")
            case["open_action_count"] = int(open_cnt)

    def _dump_store(self) -> dict[str, Any]:
        self._normalize_open_action_count()
        return {
            "version": 1,
            "saved_at": _now_iso(),
            "cases": self._cases,
            "events": {k: list(v) for k, v in self._events.items()},
            "actions": {k: list(v) for k, v in self._actions.items()},
            "dedup": self._dedup,
        }

    def _open_case_db(self) -> sqlite3.Connection:
        if not self._db_path:
            raise ValueError("sqlite case db path not configured")
        parent = os.path.dirname(self._db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        conn = sqlite3.connect(self._db_path, timeout=20.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    @staticmethod
    def _json_dump(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)

    @staticmethod
    def _json_load(text: str, fallback: Any) -> Any:
        try:
            out = json.loads(text)
            return out
        except (json.JSONDecodeError, ValueError):
            return fallback

    _SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

    @classmethod
    def _validate_identifier(cls, name: str) -> str:
        """Validate that *name* is a safe SQL identifier (alphanumeric + underscore)."""
        if not cls._SAFE_IDENTIFIER_RE.match(name):
            raise ValueError(f"Unsafe SQL identifier rejected: {name!r}")
        return name

    @classmethod
    def _ensure_db_column(cls, conn: sqlite3.Connection, table: str, col: str, ddl_type: str) -> None:
        table = cls._validate_identifier(table)
        col = cls._validate_identifier(col)
        ddl_type = cls._validate_identifier(ddl_type)
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        existing = {str(x[1]) for x in rows}
        if col not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl_type}")

    def _init_db_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS qcc_cases (
                case_id TEXT PRIMARY KEY,
                lot_id TEXT,
                state TEXT,
                severity TEXT,
                updated_at TEXT NOT NULL,
                payload TEXT NOT NULL
            )
            """
        )
        self._ensure_db_column(conn, "qcc_cases", "lot_id", "TEXT")
        self._ensure_db_column(conn, "qcc_cases", "state", "TEXT")
        self._ensure_db_column(conn, "qcc_cases", "severity", "TEXT")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS qcc_actions (
                action_id TEXT PRIMARY KEY,
                case_id TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                payload TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_qcc_actions_case_id ON qcc_actions(case_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_qcc_cases_lot ON qcc_cases(lot_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_qcc_cases_state ON qcc_cases(state)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_qcc_cases_severity ON qcc_cases(severity)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_qcc_cases_updated_at ON qcc_cases(updated_at)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS qcc_events (
                case_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                payload TEXT NOT NULL,
                PRIMARY KEY (case_id, seq)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_qcc_events_case_id ON qcc_events(case_id)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS qcc_dedup (
                dedup_key TEXT PRIMARY KEY,
                case_id TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS qcc_meta (
                k TEXT PRIMARY KEY,
                v TEXT NOT NULL
            )
            """
        )

    def _load_from_sqlite(self) -> None:
        try:
            with self._open_case_db() as conn:
                self._init_db_schema(conn)
                case_rows = conn.execute("SELECT case_id, payload FROM qcc_cases").fetchall()
                action_rows = conn.execute("SELECT case_id, payload FROM qcc_actions").fetchall()
                event_rows = conn.execute("SELECT case_id, payload FROM qcc_events ORDER BY case_id, seq").fetchall()
                dedup_rows = conn.execute("SELECT dedup_key, case_id FROM qcc_dedup").fetchall()
            self._cases = {}
            self._actions = defaultdict(list)
            self._events = defaultdict(list)
            self._dedup = {}
            for cid, payload_txt in case_rows:
                payload = self._json_load(str(payload_txt), {})
                if isinstance(payload, dict):
                    self._cases[str(cid)] = payload
            for cid, payload_txt in action_rows:
                payload = self._json_load(str(payload_txt), {})
                if isinstance(payload, dict):
                    self._actions[str(cid)].append(payload)
            for cid, payload_txt in event_rows:
                payload = self._json_load(str(payload_txt), {})
                if isinstance(payload, dict):
                    self._events[str(cid)].append(payload)
            for dkey, cid in dedup_rows:
                self._dedup[str(dkey)] = str(cid)
            self._normalize_open_action_count()
            self._store_meta["loaded"] = True
            self._store_meta["last_load_iso"] = _now_iso()
            self._store_meta["last_error"] = ""
        except Exception as exc:  # noqa: BLE001
            self._store_meta["loaded"] = False
            self._store_meta["last_error"] = f"sqlite_load_failed:{exc}"
            self._store_meta["last_load_iso"] = _now_iso()

    def _persist_to_sqlite(self) -> None:
        try:
            payload = self._dump_store()
            cases = payload.get("cases", {})
            actions = payload.get("actions", {})
            events = payload.get("events", {})
            dedup = payload.get("dedup", {})
            with self._open_case_db() as conn:
                self._init_db_schema(conn)
                conn.execute("BEGIN")
                conn.execute("DELETE FROM qcc_cases")
                conn.execute("DELETE FROM qcc_actions")
                conn.execute("DELETE FROM qcc_events")
                conn.execute("DELETE FROM qcc_dedup")
                for cid, row in dict(cases if isinstance(cases, dict) else {}).items():
                    if not isinstance(row, dict):
                        continue
                    conn.execute(
                        "INSERT INTO qcc_cases(case_id, lot_id, state, severity, updated_at, payload) VALUES(?, ?, ?, ?, ?, ?)",
                        (
                            str(cid),
                            str(row.get("lot_id", "")),
                            str(row.get("state", "")),
                            str(row.get("severity", "")),
                            str(row.get("updated_at", "")),
                            self._json_dump(row),
                        ),
                    )
                for cid, rows in dict(actions if isinstance(actions, dict) else {}).items():
                    if not isinstance(rows, list):
                        continue
                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        aid = str(row.get("action_id", ""))
                        if not aid:
                            continue
                        conn.execute(
                            "INSERT INTO qcc_actions(action_id, case_id, updated_at, payload) VALUES(?, ?, ?, ?)",
                            (aid, str(cid), str(row.get("completed_at") or row.get("created_at") or ""), self._json_dump(row)),
                        )
                for cid, rows in dict(events if isinstance(events, dict) else {}).items():
                    if not isinstance(rows, list):
                        continue
                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        seq = int(row.get("seq", 0) or 0)
                        if seq <= 0:
                            continue
                        conn.execute(
                            "INSERT INTO qcc_events(case_id, seq, payload) VALUES(?, ?, ?)",
                            (str(cid), seq, self._json_dump(row)),
                        )
                for dkey, cid in dict(dedup if isinstance(dedup, dict) else {}).items():
                    conn.execute(
                        "INSERT INTO qcc_dedup(dedup_key, case_id) VALUES(?, ?)",
                        (str(dkey), str(cid)),
                    )
                conn.execute(
                    "INSERT OR REPLACE INTO qcc_meta(k, v) VALUES(?, ?)",
                    ("last_saved_at", str(payload.get("saved_at", ""))),
                )
                conn.commit()
            self._store_meta["persist_count"] = int(self._store_meta.get("persist_count", 0)) + 1
            self._store_meta["last_persist_iso"] = _now_iso()
            self._store_meta["last_error"] = ""
        except Exception as exc:  # noqa: BLE001
            self._store_meta["last_error"] = f"sqlite_persist_failed:{exc}"

    def _load_store(self) -> None:
        if self._db_path:
            self._load_from_sqlite()
            return
        if not self._store_path:
            self._store_meta["loaded"] = True
            self._store_meta["last_load_iso"] = _now_iso()
            return
        if not os.path.exists(self._store_path):
            self._store_meta["loaded"] = True
            self._store_meta["last_load_iso"] = _now_iso()
            return
        try:
            with open(self._store_path, "r", encoding="utf-8") as fp:
                payload = json.load(fp)
            if not isinstance(payload, dict):
                raise ValueError("case store payload must be object")
            self._cases = {str(k): dict(v) for k, v in dict(payload.get("cases", {})).items() if isinstance(v, dict)}
            ev = payload.get("events", {})
            ac = payload.get("actions", {})
            self._events = defaultdict(list)
            self._actions = defaultdict(list)
            for k, v in dict(ev if isinstance(ev, dict) else {}).items():
                if isinstance(v, list):
                    self._events[str(k)] = [dict(x) for x in v if isinstance(x, dict)]
            for k, v in dict(ac if isinstance(ac, dict) else {}).items():
                if isinstance(v, list):
                    self._actions[str(k)] = [dict(x) for x in v if isinstance(x, dict)]
            dd = payload.get("dedup", {})
            self._dedup = {str(k): str(v) for k, v in dict(dd if isinstance(dd, dict) else {}).items()}
            self._normalize_open_action_count()
            self._store_meta["loaded"] = True
            self._store_meta["last_load_iso"] = _now_iso()
            self._store_meta["last_error"] = ""
        except Exception as exc:  # noqa: BLE001
            self._store_meta["loaded"] = False
            self._store_meta["last_error"] = f"load_failed:{exc}"
            self._store_meta["last_load_iso"] = _now_iso()

    def _persist_store(self) -> None:
        if self._db_path:
            self._persist_to_sqlite()
            return
        if not self._store_path:
            return
        try:
            parent = os.path.dirname(self._store_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            payload = self._dump_store()
            tmp = f"{self._store_path}.tmp"
            with open(tmp, "w", encoding="utf-8") as fp:
                json.dump(payload, fp, ensure_ascii=False, sort_keys=True, indent=2, default=str)
            os.replace(tmp, self._store_path)
            self._store_meta["persist_count"] = int(self._store_meta.get("persist_count", 0)) + 1
            self._store_meta["last_persist_iso"] = _now_iso()
            self._store_meta["last_error"] = ""
        except Exception as exc:  # noqa: BLE001
            self._store_meta["last_error"] = f"persist_failed:{exc}"

    def store_status(self) -> dict[str, Any]:
        meta = dict(self._store_meta)
        if self._db_path:
            meta["db_path"] = self._db_path
            meta["db_exists"] = os.path.exists(self._db_path)
        if self._store_path:
            meta["path"] = self._store_path
            meta["exists"] = os.path.exists(self._store_path)
        meta["case_count"] = len(self._cases)
        meta["open_case_count"] = sum(1 for x in self._cases.values() if x.get("state") not in {"closed", "cancelled"})
        return meta

    def consistency_check(self) -> dict[str, Any]:
        errors: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        with self._lock:
            case_ids = set(self._cases.keys())
            action_ids: dict[str, str] = {}
            event_count = 0
            for cid, case in self._cases.items():
                if str(case.get("case_id", "")) != str(cid):
                    errors.append({"code": "case_id_mismatch", "case_id": cid})
                state = str(case.get("state", ""))
                if state not in self.STATES:
                    errors.append({"code": "invalid_case_state", "case_id": cid, "state": state})
                open_count = sum(1 for x in self._actions.get(cid, []) if x.get("status") != "completed")
                if state not in {"closed", "cancelled"} and int(case.get("open_action_count", open_count)) != int(open_count):
                    warnings.append(
                        {
                            "code": "open_action_count_mismatch",
                            "case_id": cid,
                            "case_value": case.get("open_action_count"),
                            "actual": open_count,
                        }
                    )
            for cid, rows in self._actions.items():
                if cid not in case_ids:
                    errors.append({"code": "orphan_action_case", "case_id": cid, "count": len(rows)})
                for row in rows:
                    aid = str(row.get("action_id", ""))
                    if not aid:
                        errors.append({"code": "action_missing_id", "case_id": cid})
                        continue
                    owner_cid = action_ids.get(aid)
                    if owner_cid and owner_cid != cid:
                        errors.append({"code": "duplicate_action_id", "action_id": aid, "case_id": cid, "owner_case_id": owner_cid})
                    else:
                        action_ids[aid] = cid
                    status = str(row.get("status", ""))
                    if status not in {"open", "completed"}:
                        warnings.append({"code": "unknown_action_status", "action_id": aid, "status": status})
            for cid, rows in self._events.items():
                if cid not in case_ids:
                    warnings.append({"code": "orphan_event_case", "case_id": cid, "count": len(rows)})
                prev = "GENESIS"
                expected_seq = 1
                for row in rows:
                    event_count += 1
                    seq = int(row.get("seq", 0) or 0)
                    if seq != expected_seq:
                        errors.append({"code": "event_seq_gap", "case_id": cid, "expected_seq": expected_seq, "actual_seq": seq})
                    if str(row.get("prev_hash", "")) != prev:
                        errors.append({"code": "event_prev_hash_mismatch", "case_id": cid, "seq": seq})
                    payload = {
                        "case_id": str(row.get("case_id", cid)),
                        "seq": seq,
                        "event_type": str(row.get("event_type", "")),
                        "actor": str(row.get("actor", "")),
                        "details": dict(row.get("details", {}) if isinstance(row.get("details"), dict) else {}),
                        "ts": str(row.get("ts", "")),
                    }
                    calc = self._hash_event(prev, payload)
                    if str(row.get("hash", "")) != calc:
                        errors.append({"code": "event_hash_mismatch", "case_id": cid, "seq": seq})
                    prev = str(row.get("hash", ""))
                    expected_seq += 1
            for dkey, cid in self._dedup.items():
                if cid not in case_ids:
                    errors.append({"code": "dedup_orphan_case", "dedup_key": dkey, "case_id": cid})
            summary = {
                "case_count": len(self._cases),
                "action_count": sum(len(x) for x in self._actions.values()),
                "event_count": event_count,
                "dedup_count": len(self._dedup),
            }
        return {
            "ok": len(errors) == 0,
            "error_count": len(errors),
            "warning_count": len(warnings),
            "errors": errors[:200],
            "warnings": warnings[:200],
            "summary": summary,
            "checked_at": _now_iso(),
        }

    @staticmethod
    def _hash_event(prev_hash: str, payload: dict[str, Any]) -> str:
        txt = json.dumps({"prev_hash": prev_hash, "payload": payload}, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(txt.encode("utf-8")).hexdigest()[:24]

    def _append_event(self, case_id: str, event_type: str, actor: str, details: dict[str, Any]) -> dict[str, Any]:
        rows = self._events[case_id]
        prev = rows[-1]["hash"] if rows else "GENESIS"
        payload = {
            "case_id": case_id,
            "seq": len(rows) + 1,
            "event_type": event_type,
            "actor": actor,
            "details": dict(details),
            "ts": _now_iso(),
        }
        h = self._hash_event(prev, payload)
        row = {**payload, "prev_hash": prev, "hash": h}
        rows.append(row)
        return row

    def open_case(
        self,
        lot_id: str,
        case_type: str,
        issue: str,
        severity: str,
        source: str,
        created_by: str,
        linked_snapshot_id: str | None = None,
        linked_decision_code: str | None = None,
        dedup_key: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        dkey = str(dedup_key).strip() if dedup_key else ""
        if dkey and dkey in self._dedup:
            cid = self._dedup[dkey]
            old = self._cases.get(cid)
            if old and old.get("state") not in {"closed", "cancelled"}:
                return {"opened": True, "deduplicated": True, "case_id": cid, "state": old.get("state")}
        cid = f"CASE-{int(time.time())}-{len(self._cases)+1:06d}"
        row = {
            "case_id": cid,
            "lot_id": lot_id,
            "case_type": case_type,
            "issue": issue,
            "severity": str(severity).strip().lower(),
            "source": source,
            "state": "open",
            "created_by": created_by,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "linked_snapshot_id": linked_snapshot_id,
            "linked_decision_code": linked_decision_code,
            "waivers": [],
            "open_action_count": 0,
            "metadata": dict(metadata or {}),
        }
        self._cases[cid] = row
        if dkey:
            self._dedup[dkey] = cid
        self._append_event(case_id=cid, event_type="case_opened", actor=created_by, details={"issue": issue, "severity": severity})
        self._persist_store()
        return {"opened": True, "deduplicated": False, "case_id": cid, "state": "open"}

    def transition(self, case_id: str, to_state: str, actor: str, reason: str = "") -> dict[str, Any]:
        case = self._cases.get(case_id)
        if not case:
            return {"ok": False, "error": "case_not_found"}
        target = str(to_state)
        if target not in self.STATES:
            return {"ok": False, "error": "invalid_state"}
        cur = str(case.get("state", "open"))
        if target != cur and target not in self.TRANSITIONS.get(cur, set()):
            return {"ok": False, "error": "illegal_transition", "from": cur, "to": target}
        case["state"] = target
        case["updated_at"] = _now_iso()
        self._append_event(case_id=case_id, event_type="state_transition", actor=actor, details={"from": cur, "to": target, "reason": reason})
        self._persist_store()
        return {"ok": True, "case_id": case_id, "state": target}

    def add_action(
        self,
        case_id: str,
        action_type: str,
        owner: str,
        description: str,
        actor: str,
        due_ts: float | None = None,
        priority: int = 2,
        mandatory: bool = True,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        case = self._cases.get(case_id)
        if not case:
            return {"ok": False, "error": "case_not_found"}
        action_id = f"{case_id}-ACT-{len(self._actions[case_id])+1:04d}"
        due_val = float(due_ts) if _is_number(due_ts) else None
        action = {
            "action_id": action_id,
            "action_type": action_type,
            "owner": owner,
            "description": description,
            "priority": max(1, min(5, int(priority))),
            "mandatory": bool(mandatory),
            "due_ts": due_val,
            "status": "open",
            "completed_by": "",
            "completed_at": "",
            "result": {},
            "payload": dict(payload or {}),
            "created_at": _now_iso(),
        }
        self._actions[case_id].append(action)
        info = {
            "action_id": action_id,
            "action_type": action_type,
            "owner": owner,
            "description": description,
            "due_ts": due_val,
            "priority": action["priority"],
            "mandatory": action["mandatory"],
        }
        case["open_action_count"] = sum(1 for x in self._actions[case_id] if x.get("status") != "completed")
        case["updated_at"] = _now_iso()
        self._append_event(case_id=case_id, event_type="action_added", actor=actor, details=info)
        self._persist_store()
        return {"ok": True, "case_id": case_id, "state": case.get("state"), "action_id": action_id}

    def complete_action(
        self,
        case_id: str,
        action_id: str,
        actor: str,
        result: dict[str, Any] | None = None,
        effectiveness: float | None = None,
    ) -> dict[str, Any]:
        case = self._cases.get(case_id)
        if not case:
            return {"ok": False, "error": "case_not_found"}
        rows = self._actions.get(case_id, [])
        target = [x for x in rows if x.get("action_id") == action_id]
        if not target:
            return {"ok": False, "error": "action_not_found"}
        act = target[0]
        if act.get("status") == "completed":
            return {"ok": True, "case_id": case_id, "action_id": action_id, "deduplicated": True}
        act["status"] = "completed"
        act["completed_by"] = actor
        act["completed_at"] = _now_iso()
        act["result"] = dict(result or {})
        eff = float(effectiveness) if _is_number(effectiveness) else None
        if eff is not None:
            act["effectiveness"] = max(0.0, min(1.0, eff))
        case["open_action_count"] = sum(1 for x in rows if x.get("status") != "completed")
        case["updated_at"] = _now_iso()
        self._append_event(
            case_id=case_id,
            event_type="action_completed",
            actor=actor,
            details={
                "action_id": action_id,
                "effectiveness": act.get("effectiveness"),
            },
        )
        self._persist_store()
        return {"ok": True, "case_id": case_id, "action_id": action_id, "open_action_count": case["open_action_count"]}

    def get_sla_report(
        self,
        lot_id: str | None = None,
        case_id: str | None = None,
        now_ts: float | None = None,
    ) -> dict[str, Any]:
        now = float(now_ts if now_ts is not None else time.time())
        rows: list[dict[str, Any]] = []
        case_ids: list[str]
        if case_id:
            case_ids = [case_id]
        elif lot_id:
            case_ids = [c["case_id"] for c in self._cases.values() if c.get("lot_id") == lot_id]
        else:
            case_ids = list(self._cases.keys())
        for cid in case_ids:
            case = self._cases.get(cid)
            if not case:
                continue
            if case.get("state") in {"closed", "cancelled"}:
                continue
            for act in self._actions.get(cid, []):
                if act.get("status") == "completed":
                    continue
                due = act.get("due_ts")
                overdue = bool(_is_number(due) and float(due) < now)
                rows.append(
                    {
                        "case_id": cid,
                        "lot_id": case.get("lot_id"),
                        "severity": case.get("severity"),
                        "action_id": act.get("action_id"),
                        "owner": act.get("owner"),
                        "priority": act.get("priority"),
                        "mandatory": bool(act.get("mandatory", True)),
                        "due_ts": due,
                        "overdue": overdue,
                    }
                )
        overdue_rows = [x for x in rows if x.get("overdue")]
        critical_overdue = [x for x in overdue_rows if x.get("severity") in {"critical", "high"} and x.get("mandatory")]
        return {
            "count": len(rows),
            "overdue_count": len(overdue_rows),
            "critical_overdue_count": len(critical_overdue),
            "rows": rows,
            "overdue_rows": overdue_rows,
        }

    def add_waiver(
        self,
        case_id: str,
        actor: str,
        approved_by: str,
        reason: str,
        approver_role: str = "quality_manager",
        risk_level: str | None = None,
        customer_tier: str = "standard",
        waiver_type: str = "release_with_risk",
        expiry_ts: float | None = None,
    ) -> dict[str, Any]:
        case = self._cases.get(case_id)
        if not case:
            return {"ok": False, "error": "case_not_found"}
        sev = str(risk_level or case.get("severity", "high")).strip().lower()
        req = self._required_approver(severity=sev, customer_tier=customer_tier)
        actual_role = self._norm_role(approver_role)
        if self._rank(actual_role) < self._rank(req):
            return {
                "ok": False,
                "error": "approval_insufficient",
                "required_role": req,
                "actual_role": actual_role,
                "case_id": case_id,
            }
        rec = {
            "waiver_id": f"{case_id}-WVR-{len(case.get('waivers', []))+1:04d}",
            "actor": actor,
            "approved_by": approved_by,
            "approver_role": actual_role,
            "required_role": req,
            "waiver_type": waiver_type,
            "reason": reason,
            "expiry_ts": float(expiry_ts) if _is_number(expiry_ts) else None,
            "created_at": _now_iso(),
        }
        case["waivers"].append(rec)
        case["updated_at"] = _now_iso()
        self._append_event(case_id=case_id, event_type="waiver_added", actor=actor, details=rec)
        self._persist_store()
        return {"ok": True, "case_id": case_id, "waiver_id": rec["waiver_id"]}

    def close_case(self, case_id: str, actor: str, verification: dict[str, Any] | None = None) -> dict[str, Any]:
        case = self._cases.get(case_id)
        if not case:
            return {"ok": False, "error": "case_not_found"}
        cur = str(case.get("state", "open"))
        if cur not in {"verification", "action_in_progress"}:
            return {"ok": False, "error": "invalid_close_state", "state": cur}
        pending_mandatory = [
            x["action_id"]
            for x in self._actions.get(case_id, [])
            if x.get("status") != "completed" and bool(x.get("mandatory", True))
        ]
        if pending_mandatory:
            return {
                "ok": False,
                "error": "mandatory_actions_pending",
                "pending_actions": pending_mandatory,
            }
        case["state"] = "closed"
        case["updated_at"] = _now_iso()
        case["open_action_count"] = 0
        self._append_event(
            case_id=case_id,
            event_type="case_closed",
            actor=actor,
            details={"verification": dict(verification or {}), "closed_from": cur},
        )
        self._persist_store()
        return {"ok": True, "case_id": case_id, "state": "closed"}

    def get_case(self, case_id: str) -> dict[str, Any]:
        case = self._cases.get(case_id)
        if not case:
            return {"error": "case_not_found", "case_id": case_id}
        actions = list(self._actions.get(case_id, []))
        open_actions = [x for x in actions if x.get("status") != "completed"]
        return {
            "case": dict(case),
            "actions": actions,
            "open_action_count": len(open_actions),
            "events": list(self._events.get(case_id, [])),
            "event_count": len(self._events.get(case_id, [])),
        }

    def list_cases(self, lot_id: str | None = None, state: str | None = None, last_n: int = 100) -> dict[str, Any]:
        rows = list(self._cases.values())
        if lot_id:
            rows = [x for x in rows if x.get("lot_id") == lot_id]
        if state:
            rows = [x for x in rows if x.get("state") == state]
        rows.sort(key=lambda x: str(x.get("updated_at", "")))
        rows = rows[-max(1, int(last_n)) :]
        out = []
        for row in rows:
            rid = str(row.get("case_id"))
            open_cnt = sum(1 for x in self._actions.get(rid, []) if x.get("status") != "completed")
            out.append({**row, "open_action_count": open_cnt})
        return {"count": len(out), "rows": out}


class RoleViewBuilderV2:
    """
    Multi-role output adaptation to reduce cognitive load for each user role.
    """

    @staticmethod
    def _role_key(role: str) -> str:
        return str(role).strip().lower().replace("-", "_").replace(" ", "_")

    def build(self, role: str, assessment: dict[str, Any]) -> dict[str, Any]:
        r = self._role_key(role)
        fd = assessment.get("final_decision", {})
        boundary = assessment.get("boundary", {})
        actions = list(assessment.get("prioritized_actions", []))
        module_outputs = assessment.get("module_outputs", {})
        base = {
            "role": r,
            "lot_id": assessment.get("lot_id"),
            "status": assessment.get("status"),
            "risk_level": assessment.get("risk_level"),
            "risk_score": assessment.get("risk_score"),
            "tier": fd.get("tier"),
            "mode": fd.get("mode"),
            "decision_code": fd.get("decision_code"),
        }
        if r in {"operator", "line_operator"}:
            return {
                **base,
                "what_to_do_now": actions[0] if actions else None,
                "must_not_do": "先不要直接调配方，优先排查工艺和测量条件",
                "checklist": boundary.get("hard_blocks", []) + boundary.get("review_triggers", [])[:3],
            }
        if r in {"process_engineer", "engineer"}:
            return {
                **base,
                "process_focus": {
                    "process_coupling": module_outputs.get("process_coupling"),
                    "spc": module_outputs.get("spc"),
                    "roll_tracker": module_outputs.get("roll_tracker"),
                },
                "recommended_sequence": actions[:4],
            }
        if r in {"quality_manager", "qa", "qc"}:
            return {
                **base,
                "gates": {
                    "hard_blocks": boundary.get("hard_blocks", []),
                    "arbitration_triggers": boundary.get("arbitration_triggers", []),
                    "review_triggers": boundary.get("review_triggers", []),
                },
                "case_governance": module_outputs.get("case_governance"),
                "capa_candidates": assessment.get("business_suggestion_layer", {}).get("capa_candidates", {}),
                "case_ref": assessment.get("case_ref"),
            }
        if r in {"customer_service", "cs"}:
            return {
                **base,
                "customer_safe_summary": {
                    "conclusion": fd.get("tier"),
                    "decision_mode": fd.get("mode"),
                    "next_step": actions[0]["action"] if actions else "follow_internal_guidance",
                },
                "do_not_disclose_internal": True,
            }
        if r in {"executive", "boss", "management"}:
            return {
                **base,
                "business_disposition": assessment.get("disposition_plan"),
                "top_risks": (boundary.get("hard_blocks", []) + boundary.get("arbitration_triggers", []))[:5],
                "case_ref": assessment.get("case_ref"),
            }
        return {
            **base,
            "prioritized_actions": actions[:5],
            "boundary": boundary,
            "case_ref": assessment.get("case_ref"),
        }


class LifecycleRuleCenter:
    """
    Versioned and scoped rule packs for advanced lifecycle arbitration.
    """

    def __init__(self) -> None:
        self._packs: list[dict[str, Any]] = []
        self.register_pack(
            version="LIFE-RULE-2026.04-R1",
            active_from_ts=0.0,
            scope={},
            params={
                "process_risk_review": 0.45,
                "process_risk_arbitration": 0.75,
                "appearance_risk_review": 0.35,
                "customer_risk_review": 0.35,
                "customer_risk_arbitration": 0.75,
                "min_confidence_arbitration": 0.55,
                "repeatability_review_std": 0.35,
                "repeatability_hard_std": 0.45,
                "msa_risk_review": 0.45,
                "msa_risk_hard": 0.75,
                "spc_risk_review": 0.4,
                "spc_risk_hard": 0.75,
                "metamerism_risk_review": 0.35,
                "metamerism_risk_hard": 0.75,
                "post_process_risk_review": 0.4,
                "post_process_risk_hard": 0.78,
                "storage_risk_review": 0.45,
                "storage_risk_hard": 0.8,
                "roll_transition_risk_review": 0.45,
                "roll_tail_risk_review": 0.4,
                "roll_tail_risk_hard": 0.8,
                "case_overdue_review": 1,
                "case_overdue_hard": 2,
                "release_allowed_states": ["released", "in_run_monitoring", "hold_for_review", "retest", "arbitration"],
            },
            notes="default production lifecycle rules",
        )

    @staticmethod
    def _scope_match(scope: dict[str, Any], meta: dict[str, Any]) -> bool:
        if not scope:
            return True
        sku = str(meta.get("product_code", meta.get("sku", "")))
        customer_id = str(meta.get("customer_id", ""))
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

    def register_pack(
        self,
        version: str,
        active_from_ts: float,
        scope: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        notes: str = "",
    ) -> dict[str, Any]:
        row = {
            "version": str(version),
            "active_from_ts": float(active_from_ts),
            "scope": dict(scope or {}),
            "params": dict(params or {}),
            "notes": str(notes),
            "registered_at": _now_iso(),
        }
        self._packs.append(row)
        self._packs.sort(key=lambda x: x["active_from_ts"])
        return {"registered": True, "version": row["version"], "count": len(self._packs)}

    def resolve(self, meta: dict[str, Any] | None = None, at_ts: float | None = None, force_version: str | None = None) -> dict[str, Any]:
        m = dict(meta or {})
        ts = float(at_ts if at_ts is not None else time.time())
        if force_version:
            forced = [x for x in self._packs if x["version"] == force_version]
            if forced:
                return {"rule_pack": forced[-1], "resolved_by": "force_version"}
        candidates = [x for x in self._packs if x["active_from_ts"] <= ts and self._scope_match(x["scope"], m)]
        if not candidates:
            return {"rule_pack": self._packs[0], "resolved_by": "fallback_first"}
        return {"rule_pack": candidates[-1], "resolved_by": "time_scope"}

    def list_packs(self) -> list[dict[str, Any]]:
        return list(self._packs)


class ReportFactory:
    def release_report(self, lot_id: str, decision: dict[str, Any], metrics: dict[str, Any], audience: str = "internal") -> dict[str, Any]:
        base = {
            "lot_id": lot_id,
            "generated_at": _now_iso(),
            "tier": decision.get("tier"),
            "decision_code": decision.get("decision_code"),
            "avg_de": metrics.get("avg_de"),
            "max_de": metrics.get("max_de"),
        }
        if audience == "customer":
            return {
                **base,
                "summary": "batch_quality_assessed",
                "details": {
                    "conclusion": decision.get("tier"),
                    "note": "further technical details available upon request",
                },
            }
        return {
            **base,
            "summary": "internal_release_report",
            "details": {
                "reasons": decision.get("reasons", []),
                "hard_gate": decision.get("hard_gate", {}),
                "action_plan": decision.get("action_plan", {}),
            },
        }

    def complaint_summary(self, lot_id: str, symptom: str, root_cause: dict[str, Any], capa: dict[str, Any]) -> dict[str, Any]:
        return {
            "lot_id": lot_id,
            "symptom": symptom,
            "root_cause": root_cause,
            "capa": capa,
            "generated_at": _now_iso(),
        }

    def root_cause_report(self, lot_id: str, symptom: str, suspects: list[dict[str, Any]], conclusion: str) -> dict[str, Any]:
        return {
            "lot_id": lot_id,
            "symptom": symptom,
            "suspects": suspects,
            "conclusion": conclusion,
            "generated_at": _now_iso(),
        }

class UltimateColorFilmSystemV2Optimized:
    def __init__(self, case_store_path: str | None = None, case_db_path: str | None = None) -> None:
        self.env = EnvironmentCompensatorV2()
        self.substrate = SubstrateAnalyzerV2()
        self.wet_dry = WetToDryPredictorV2()
        self.run_monitor = PrintRunMonitorV2()
        self.roll_tracker = RollLifecycleTrackerV2()
        self.cross_batch = CrossBatchMatcherV2()
        self.ink_lot = InkLotTrackerV2()
        self.cal_guard = AutoCalibrationGuardV2()
        self.edge = EdgeEffectAnalyzerV2()
        self.roller = RollerLifeTrackerV2()
        self.golden = GoldenSampleManagerV2()
        self.operator = OperatorSkillTrackerV2()
        self.lifecycle = TraceabilityLedgerV2()
        self.recipe_registry = RecipeVersionRegistryV2()
        self.capa = CAPAEngineV2()
        self.time_stability = TimeStabilityManager()
        self.process_coupling = ProcessCouplingRiskEngine()
        self.appearance = FilmAppearanceRiskEngine()
        self.customer = CustomerScenarioEngine()
        self.retest = RetestDisputeManager()
        self.machine = MultiMachineConsistencyEngine()
        self.learning = LearningLoopEngine()
        self.data_guard = DataIntegrityGuardV2()
        self.measurement_guard = MeasurementSystemGuardV2()
        self.spc = SPCMonitorV2()
        self.metamerism = MetamerismRiskEngineV2()
        self.post_process = PostProcessImpactPredictorV2()
        self.storage_predictor = StorageTransportStabilityPredictorV2()
        self.state_machine = LifecycleStateMachineV2()
        self.failure_modes = FailureModeRegistryV2()
        self.alerts = AlertCenterV2()
        case_store_env = os.getenv("ELITE_CASE_CENTER_STORE_PATH", "").strip()
        case_db_env = os.getenv("ELITE_CASE_CENTER_DB_PATH", "").strip()
        resolved_case_store = str(case_store_path).strip() if case_store_path is not None else case_store_env
        resolved_case_db = str(case_db_path).strip() if case_db_path is not None else case_db_env
        self.case_center = QualityCaseCenterV2(store_path=(resolved_case_store or None), db_path=(resolved_case_db or None))
        self.role_views = RoleViewBuilderV2()
        self.lifecycle_rules = LifecycleRuleCenter()
        self.report_factory = ReportFactory()
        self._version_links: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._assessment_snapshots: dict[str, dict[str, Any]] = {}
        self._assessment_idempotency: dict[str, str] = {}

        self.cal_guard.register_source("lightbox", interval_hours=168)
        self.cal_guard.register_source("color_checker", interval_hours=720)
        self.cal_guard.register_source("camera_profile", interval_hours=2160)

    def pre_flight_check(self, temp: float, humidity: float, operator: str | None = None) -> dict[str, Any]:
        env = self.env.check_environment(temp, humidity)
        cal = self.cal_guard.check_status()
        issues = []
        if not env["suitable"]:
            issues.extend(env["issues"])
        if not cal["all_ok"]:
            issues.append(f"calibration_overdue_count:{cal['overdue_count']}")

        op = self.operator.profile(operator) if operator else None
        if op and op.get("grade") == "D_training_needed":
            issues.append("operator_training_needed")

        return {
            "ready": len(issues) == 0,
            "issues": issues,
            "environment": env,
            "calibration": cal,
            "operator": op,
            "recommendation": "go" if not issues else "resolve_issues_before_run",
        }

    def register_lifecycle_rule_pack(
        self,
        version: str,
        active_from_ts: float,
        scope: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        notes: str = "",
    ) -> dict[str, Any]:
        return self.lifecycle_rules.register_pack(
            version=version,
            active_from_ts=active_from_ts,
            scope=scope,
            params=params,
            notes=notes,
        )

    def list_lifecycle_rule_packs(self) -> list[dict[str, Any]]:
        return self.lifecycle_rules.list_packs()

    def record_version_link(
        self,
        lot_id: str,
        recipe_code: str,
        recipe_version: int,
        rule_version: str,
        model_version: str,
        pipeline_policy_version: str = "",
        notes: str = "",
    ) -> dict[str, Any]:
        row = {
            "recipe_code": recipe_code,
            "recipe_version": int(recipe_version),
            "rule_version": str(rule_version),
            "model_version": str(model_version),
            "pipeline_policy_version": str(pipeline_policy_version),
            "notes": str(notes),
            "ts": _now_iso(),
        }
        self._version_links[lot_id].append(row)
        return {"recorded": True, "lot_id": lot_id, "count": len(self._version_links[lot_id])}

    def get_version_links(self, lot_id: str) -> dict[str, Any]:
        return {"lot_id": lot_id, "links": list(self._version_links.get(lot_id, []))}

    def add_trace_event(
        self,
        lot_id: str,
        stage: str,
        data: dict[str, Any],
        event_id: str | None = None,
        actor: str = "",
        links: list[dict[str, str]] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        check = self.data_guard.validate_event_payload(stage=stage, data=data)
        if not check["valid"]:
            return {"recorded": False, "error": "invalid_event_payload", "details": check}
        return self.lifecycle.add_event(
            lot_id=lot_id,
            stage=stage,
            data=data,
            event_id=event_id,
            actor=actor,
            links=links,
            idempotency_key=idempotency_key,
        )

    def add_trace_revision(
        self,
        lot_id: str,
        target_event_id: str,
        patch: dict[str, Any],
        actor: str,
        reason: str,
    ) -> dict[str, Any]:
        return self.lifecycle.add_revision(
            lot_id=lot_id,
            target_event_id=target_event_id,
            patch=patch,
            actor=actor,
            reason=reason,
        )

    def add_manual_override_audit(
        self,
        lot_id: str,
        decision_ref: str,
        actor: str,
        approved_by: str,
        reason: str,
    ) -> dict[str, Any]:
        return self.lifecycle.add_override(
            lot_id=lot_id,
            decision_ref=decision_ref,
            actor=actor,
            approved_by=approved_by,
            reason=reason,
        )

    def record_time_stability(
        self,
        lot_id: str,
        elapsed_hours: float,
        lab: dict[str, float],
        stage: str = "recheck",
        verdict: str | None = None,
    ) -> dict[str, Any]:
        return self.time_stability.record(lot_id=lot_id, elapsed_hours=elapsed_hours, lab=lab, stage=stage, verdict=verdict)

    def get_time_stability_report(self, lot_id: str) -> dict[str, Any]:
        return self.time_stability.report(lot_id=lot_id)

    def evaluate_process_coupling(self, params: dict[str, Any], route: str = "gravure") -> dict[str, Any]:
        return self.process_coupling.evaluate(params=params, route=route)

    def reverse_infer_process(self, color_symptom: dict[str, Any], params: dict[str, Any], route: str = "gravure") -> dict[str, Any]:
        return self.process_coupling.reverse_infer(color_symptom=color_symptom, params=params, route=route)

    def evaluate_film_appearance(
        self,
        lab: dict[str, float],
        film_props: dict[str, Any],
        substrate_bases: list[dict[str, Any]] | None = None,
        observer_angles: list[float] | None = None,
    ) -> dict[str, Any]:
        return self.appearance.evaluate(
            lab=lab,
            film_props=film_props,
            substrate_bases=substrate_bases,
            observer_angles=observer_angles,
        )

    def register_customer_profile(self, customer_id: str, profile: dict[str, Any]) -> dict[str, Any]:
        return self.customer.register_profile(customer_id=customer_id, profile=profile)

    def evaluate_customer_acceptance(
        self,
        customer_id: str,
        sku: str,
        scenario: dict[str, Any],
        metrics: dict[str, Any],
    ) -> dict[str, Any]:
        return self.customer.evaluate(customer_id=customer_id, sku=sku, scenario=scenario, metrics=metrics)

    def record_retest(
        self,
        lot_id: str,
        test_type: str,
        device_id: str,
        operator: str,
        raw_result: dict[str, Any],
        compensated_result: dict[str, Any] | None,
        judgment_result: dict[str, Any],
        review_result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.retest.record(
            lot_id=lot_id,
            test_type=test_type,
            device_id=device_id,
            operator=operator,
            raw_result=raw_result,
            compensated_result=compensated_result,
            judgment_result=judgment_result,
            review_result=review_result,
        )

    def get_dispute_report(self, lot_id: str) -> dict[str, Any]:
        return self.retest.dispute_report(lot_id=lot_id)

    def record_machine_bias(self, machine_id: str, plant_id: str, sku: str, dL: float, da: float, db: float) -> dict[str, Any]:
        return self.machine.record(machine_id=machine_id, plant_id=plant_id, sku=sku, dL=dL, da=da, db=db)

    def get_machine_fingerprint(self, machine_id: str, sku: str | None = None) -> dict[str, Any]:
        return self.machine.fingerprint(machine_id=machine_id, sku=sku)

    def get_chronic_machine_bias_report(self) -> dict[str, Any]:
        return self.machine.chronic_bias_report()

    def record_learning_event(
        self,
        context_key: str,
        predicted_cause: str,
        actual_cause: str,
        success: bool,
        rule_source: str = "heuristic",
    ) -> dict[str, Any]:
        return self.learning.record(
            context_key=context_key,
            predicted_cause=predicted_cause,
            actual_cause=actual_cause,
            success=success,
            rule_source=rule_source,
        )

    def get_learning_priorities(self, context_key: str) -> dict[str, Any]:
        return self.learning.cause_priority(context_key=context_key)

    def record_measurement_msa(
        self,
        lot_id: str,
        sample_id: str,
        device_id: str,
        operator_id: str,
        lab: dict[str, float],
        ts: float | None = None,
    ) -> dict[str, Any]:
        return self.measurement_guard.record(
            lot_id=lot_id,
            sample_id=sample_id,
            device_id=device_id,
            operator_id=operator_id,
            lab=lab,
            ts=ts,
        )

    def get_msa_report(self, lot_id: str | None = None, window: int = 500) -> dict[str, Any]:
        return self.measurement_guard.report(lot_id=lot_id, window=window)

    def record_spc_point(self, stream_id: str, value: float, ts: float | None = None, meta: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.spc.add_point(stream_id=stream_id, value=value, ts=ts, meta=meta)

    def get_spc_report(self, stream_id: str, window: int = 100) -> dict[str, Any]:
        return self.spc.report(stream_id=stream_id, window=window)

    def register_roll(
        self,
        lot_id: str,
        roll_id: str,
        length_m: float,
        parent_roll_id: str | None = None,
        rework_of: str | None = None,
        machine_id: str = "",
        shift: str = "",
    ) -> dict[str, Any]:
        return self.roll_tracker.register_roll(
            lot_id=lot_id,
            roll_id=roll_id,
            length_m=length_m,
            parent_roll_id=parent_roll_id,
            rework_of=rework_of,
            machine_id=machine_id,
            shift=shift,
        )

    def mark_roll_zone(
        self,
        roll_id: str,
        zone_type: str,
        meter_start: float,
        meter_end: float,
        reason: str = "",
    ) -> dict[str, Any]:
        return self.roll_tracker.mark_zone(
            roll_id=roll_id,
            zone_type=zone_type,
            meter_start=meter_start,
            meter_end=meter_end,
            reason=reason,
        )

    def add_roll_measurement(
        self,
        roll_id: str,
        meter_pos: float,
        de: float,
        lab: dict[str, float] | None = None,
        source: str = "",
        ts: float | None = None,
    ) -> dict[str, Any]:
        return self.roll_tracker.add_measurement(
            roll_id=roll_id,
            meter_pos=meter_pos,
            de=de,
            lab=lab,
            source=source,
            ts=ts,
        )

    def get_roll_summary(self, roll_id: str) -> dict[str, Any]:
        return self.roll_tracker.summary(roll_id=roll_id)

    def get_lot_roll_summary(self, lot_id: str) -> dict[str, Any]:
        return self.roll_tracker.lot_summary(lot_id=lot_id)

    def evaluate_metamerism(
        self,
        lab_d65: dict[str, float],
        alt_lights: dict[str, dict[str, float]] | None = None,
        film_props: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.metamerism.evaluate(lab_d65=lab_d65, alt_lights=alt_lights, film_props=film_props)

    def evaluate_post_process_risk(
        self,
        lab: dict[str, float],
        steps: list[str] | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.post_process.predict(lab=lab, steps=steps, context=context)

    def evaluate_storage_transport_risk(
        self,
        lab: dict[str, float],
        storage_days: float,
        temp_c: float,
        humidity_pct: float,
        uv_hours: float = 0.0,
        vibration_index: float = 0.0,
    ) -> dict[str, Any]:
        return self.storage_predictor.predict(
            lab=lab,
            storage_days=storage_days,
            temp_c=temp_c,
            humidity_pct=humidity_pct,
            uv_hours=uv_hours,
            vibration_index=vibration_index,
        )

    def transition_state(
        self,
        lot_id: str,
        to_state: str,
        actor: str,
        reason: str = "",
        evidence: dict[str, Any] | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        return self.state_machine.transition(
            lot_id=lot_id,
            to_state=to_state,
            actor=actor,
            reason=reason,
            evidence=evidence,
            force=force,
        )

    def get_state_snapshot(self, lot_id: str) -> dict[str, Any]:
        return self.state_machine.snapshot(lot_id=lot_id)

    def register_failure_mode(
        self,
        mode_id: str,
        desc: str,
        severity: int,
        occurrence: int,
        detectability: int,
        category: str = "general",
    ) -> dict[str, Any]:
        return self.failure_modes.register(
            mode_id=mode_id,
            desc=desc,
            severity=severity,
            occurrence=occurrence,
            detectability=detectability,
            category=category,
        )

    def list_failure_modes(self) -> dict[str, Any]:
        return self.failure_modes.list_modes()

    def suggest_capa_candidates(self, triggers: list[str]) -> dict[str, Any]:
        return self.failure_modes.capa_candidates(triggers=triggers)

    def push_alert(
        self,
        alert_type: str,
        severity: str,
        message: str,
        source: str,
        evidence: dict[str, Any] | None = None,
        dedup_key: str | None = None,
    ) -> dict[str, Any]:
        return self.alerts.push(
            alert_type=alert_type,
            severity=severity,
            message=message,
            source=source,
            evidence=evidence,
            dedup_key=dedup_key,
        )

    def get_alert_summary(self, last_n: int = 50) -> dict[str, Any]:
        return self.alerts.summary(last_n=last_n)

    def open_quality_case(
        self,
        lot_id: str,
        case_type: str,
        issue: str,
        severity: str,
        source: str,
        created_by: str,
        linked_snapshot_id: str | None = None,
        linked_decision_code: str | None = None,
        dedup_key: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.case_center.open_case(
            lot_id=lot_id,
            case_type=case_type,
            issue=issue,
            severity=severity,
            source=source,
            created_by=created_by,
            linked_snapshot_id=linked_snapshot_id,
            linked_decision_code=linked_decision_code,
            dedup_key=dedup_key,
            metadata=metadata,
        )

    def add_case_action(
        self,
        case_id: str,
        action_type: str,
        owner: str,
        description: str,
        actor: str,
        due_ts: float | None = None,
        priority: int = 2,
        mandatory: bool = True,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.case_center.add_action(
            case_id=case_id,
            action_type=action_type,
            owner=owner,
            description=description,
            actor=actor,
            due_ts=due_ts,
            priority=priority,
            mandatory=mandatory,
            payload=payload,
        )

    def complete_case_action(
        self,
        case_id: str,
        action_id: str,
        actor: str,
        result: dict[str, Any] | None = None,
        effectiveness: float | None = None,
    ) -> dict[str, Any]:
        return self.case_center.complete_action(
            case_id=case_id,
            action_id=action_id,
            actor=actor,
            result=result,
            effectiveness=effectiveness,
        )

    def transition_case(self, case_id: str, to_state: str, actor: str, reason: str = "") -> dict[str, Any]:
        return self.case_center.transition(case_id=case_id, to_state=to_state, actor=actor, reason=reason)

    def add_case_waiver(
        self,
        case_id: str,
        actor: str,
        approved_by: str,
        reason: str,
        approver_role: str = "quality_manager",
        risk_level: str | None = None,
        customer_tier: str = "standard",
        waiver_type: str = "release_with_risk",
        expiry_ts: float | None = None,
    ) -> dict[str, Any]:
        return self.case_center.add_waiver(
            case_id=case_id,
            actor=actor,
            approved_by=approved_by,
            reason=reason,
            approver_role=approver_role,
            risk_level=risk_level,
            customer_tier=customer_tier,
            waiver_type=waiver_type,
            expiry_ts=expiry_ts,
        )

    def close_quality_case(self, case_id: str, actor: str, verification: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.case_center.close_case(case_id=case_id, actor=actor, verification=verification)

    def get_quality_case(self, case_id: str) -> dict[str, Any]:
        return self.case_center.get_case(case_id=case_id)

    def list_quality_cases(self, lot_id: str | None = None, state: str | None = None, last_n: int = 100) -> dict[str, Any]:
        return self.case_center.list_cases(lot_id=lot_id, state=state, last_n=last_n)

    def get_case_store_status(self) -> dict[str, Any]:
        return self.case_center.store_status()

    def get_case_store_consistency(self) -> dict[str, Any]:
        return self.case_center.consistency_check()

    def get_case_sla_report(
        self,
        lot_id: str | None = None,
        case_id: str | None = None,
        now_ts: float | None = None,
    ) -> dict[str, Any]:
        return self.case_center.get_sla_report(lot_id=lot_id, case_id=case_id, now_ts=now_ts)

    def build_role_view(self, role: str, assessment: dict[str, Any]) -> dict[str, Any]:
        return self.role_views.build(role=role, assessment=assessment)

    def validate_assessment_payload(
        self,
        lot_id: str,
        base_decision: dict[str, Any],
        color_metrics: dict[str, Any],
        meta: dict[str, Any],
    ) -> dict[str, Any]:
        return self.data_guard.validate_assessment_inputs(
            lot_id=lot_id,
            base_decision=base_decision,
            color_metrics=color_metrics,
            meta=meta,
        )

    def evaluate_auto_boundary(self, context: dict[str, Any], meta: dict[str, Any] | None = None) -> dict[str, Any]:
        m = dict(meta or {})
        ts = m.get("decision_ts")
        force_rule = m.get("force_lifecycle_rule_version")
        rr = self.lifecycle_rules.resolve(meta=m, at_ts=ts, force_version=force_rule)
        pack = rr["rule_pack"]
        p = pack.get("params", {})

        process_review = float(p.get("process_risk_review", 0.45))
        process_arb = float(p.get("process_risk_arbitration", 0.75))
        appearance_review = float(p.get("appearance_risk_review", 0.35))
        customer_review = float(p.get("customer_risk_review", 0.35))
        customer_arb = float(p.get("customer_risk_arbitration", 0.75))
        conf_arb = float(p.get("min_confidence_arbitration", 0.55))
        repeatability_review = float(p.get("repeatability_review_std", 0.35))
        repeatability_hard = float(p.get("repeatability_hard_std", 0.45))
        msa_review = float(p.get("msa_risk_review", 0.45))
        msa_hard = float(p.get("msa_risk_hard", 0.75))
        spc_review = float(p.get("spc_risk_review", 0.4))
        spc_hard = float(p.get("spc_risk_hard", 0.75))
        metamerism_review = float(p.get("metamerism_risk_review", 0.35))
        metamerism_hard = float(p.get("metamerism_risk_hard", 0.75))
        post_process_review = float(p.get("post_process_risk_review", 0.4))
        post_process_hard = float(p.get("post_process_risk_hard", 0.78))
        storage_review = float(p.get("storage_risk_review", 0.45))
        storage_hard = float(p.get("storage_risk_hard", 0.8))
        roll_transition_review = float(p.get("roll_transition_risk_review", 0.45))
        roll_tail_review = float(p.get("roll_tail_risk_review", 0.4))
        roll_tail_hard = float(p.get("roll_tail_risk_hard", 0.8))
        case_overdue_review = int(p.get("case_overdue_review", 1))
        case_overdue_hard = int(p.get("case_overdue_hard", 2))
        release_allowed_states = set(p.get("release_allowed_states", ["released", "in_run_monitoring", "hold_for_review", "retest", "arbitration"]))

        hard_blocks: list[str] = []
        review_triggers: list[str] = []
        arbitration_triggers: list[str] = []

        if str(context.get("sensor_health", "ok")).lower() in {"failed", "offline"}:
            hard_blocks.append("sensor_failure_detected")
        if int(context.get("calibration_overdue_count", 0) or 0) > 0:
            hard_blocks.append("calibration_overdue")
        if not context.get("trace_integrity", True):
            hard_blocks.append("trace_integrity_broken")
        if int(context.get("trace_missing_required", 0) or 0) > 0:
            hard_blocks.append("trace_missing_required_events")
        if not context.get("data_valid", True):
            hard_blocks.append("invalid_measurement_data")
        if not context.get("inspection_chain_integrity", True):
            hard_blocks.append("inspection_chain_broken")
        if float(context.get("suspicious_ratio", 0.0) or 0.0) > 0.25:
            hard_blocks.append("suspicious_data_ratio_high")
        if str(context.get("golden_status", "ok")).lower() in {"replace_now", "expired"}:
            hard_blocks.append("golden_sample_invalid")
        if bool(context.get("missing_critical_data", False)):
            hard_blocks.append("critical_data_missing")
        if bool(context.get("open_critical_case", False)):
            hard_blocks.append("open_critical_quality_case")
        if bool(context.get("rule_conflict", False)):
            arbitration_triggers.append("rule_conflict_detected")
        lifecycle_state = str(context.get("lifecycle_state", "created"))
        if lifecycle_state not in release_allowed_states:
            review_triggers.append(f"lifecycle_state_not_release_ready:{lifecycle_state}")

        repeatability_std = float(context.get("repeatability_std", 0.0) or 0.0)
        if repeatability_std >= repeatability_hard:
            hard_blocks.append("repeatability_too_poor")
        elif repeatability_std >= repeatability_review:
            review_triggers.append("repeatability_poor")
        msa_risk = float(context.get("msa_risk", 0.0) or 0.0)
        if msa_risk >= msa_hard:
            hard_blocks.append("msa_gage_risk_high")
        elif msa_risk >= msa_review:
            review_triggers.append("msa_gage_risk_review")

        if float(context.get("environment_severity", 0.0) or 0.0) >= 0.5:
            review_triggers.append("environment_instability")
        process_risk = float(context.get("process_risk", 0.0) or 0.0)
        if process_risk >= process_arb:
            arbitration_triggers.append("process_coupling_accident_edge")
        elif process_risk >= process_review:
            review_triggers.append("process_coupling_risk")
        appearance_risk = float(context.get("appearance_risk", 0.0) or 0.0)
        if appearance_risk >= appearance_review:
            review_triggers.append("appearance_installation_risk")
        customer_risk = float(context.get("customer_risk", 0.0) or 0.0)
        if customer_risk >= customer_arb:
            arbitration_triggers.append("customer_acceptance_risk_high")
        elif customer_risk >= customer_review:
            review_triggers.append("customer_acceptance_risk")
        if bool(context.get("settling_insufficient", False)):
            review_triggers.append("settling_time_insufficient")
        if bool(context.get("retest_conflict", False)):
            arbitration_triggers.append("retest_conflict")
        if bool(context.get("tail_drift_detected", False)):
            review_triggers.append("tail_sustained_drift")
        spc_risk = float(context.get("spc_risk", 0.0) or 0.0)
        if spc_risk >= spc_hard:
            arbitration_triggers.append("spc_instability_high")
        elif spc_risk >= spc_review:
            review_triggers.append("spc_instability_review")
        metamerism_risk = float(context.get("metamerism_risk", 0.0) or 0.0)
        if metamerism_risk >= metamerism_hard:
            arbitration_triggers.append("metamerism_risk_high")
        elif metamerism_risk >= metamerism_review:
            review_triggers.append("metamerism_risk_review")
        post_process_risk = float(context.get("post_process_risk", 0.0) or 0.0)
        if post_process_risk >= post_process_hard:
            arbitration_triggers.append("post_process_risk_high")
        elif post_process_risk >= post_process_review:
            review_triggers.append("post_process_risk_review")
        storage_risk = float(context.get("storage_risk", 0.0) or 0.0)
        if storage_risk >= storage_hard:
            arbitration_triggers.append("storage_transport_risk_high")
        elif storage_risk >= storage_review:
            review_triggers.append("storage_transport_risk_review")
        roll_transition_risk = float(context.get("roll_transition_risk", 0.0) or 0.0)
        if roll_transition_risk >= roll_transition_review:
            review_triggers.append("roll_transition_zone_risk")
        roll_tail_risk = float(context.get("roll_tail_risk", 0.0) or 0.0)
        if roll_tail_risk >= roll_tail_hard:
            arbitration_triggers.append("roll_tail_drift_high")
        elif roll_tail_risk >= roll_tail_review:
            review_triggers.append("roll_tail_drift_review")
        case_overdue_actions = int(context.get("case_overdue_actions", 0) or 0)
        if case_overdue_actions >= case_overdue_hard:
            hard_blocks.append("quality_case_sla_overdue")
        elif case_overdue_actions >= case_overdue_review:
            review_triggers.append("quality_case_sla_risk")
        open_high_case_count = int(context.get("open_high_case_count", 0) or 0)
        if open_high_case_count > 0:
            review_triggers.append("open_high_quality_case")

        conf = float(context.get("confidence", 1.0) or 1.0)
        if conf < conf_arb:
            arbitration_triggers.append("confidence_too_low")

        manual_arbitration_required = len(hard_blocks) > 0 or len(arbitration_triggers) > 0
        manual_review_required = not manual_arbitration_required and len(review_triggers) > 0
        auto_release_allowed = not manual_arbitration_required and not manual_review_required
        mode = "manual_arbitration" if manual_arbitration_required else "manual_review" if manual_review_required else "auto_release"
        return {
            "mode": mode,
            "auto_release_allowed": auto_release_allowed,
            "manual_review_required": manual_review_required,
            "manual_arbitration_required": manual_arbitration_required,
            "hard_blocks": sorted(set(hard_blocks)),
            "review_triggers": sorted(set(review_triggers)),
            "arbitration_triggers": sorted(set(arbitration_triggers)),
            "rule_trace": {
                "lifecycle_rule_version": pack.get("version"),
                "resolved_by": rr.get("resolved_by"),
                "notes": pack.get("notes"),
            },
        }

    def _business_disposition(self, tier: str, mode: str, risk_score: float, meta: dict[str, Any] | None = None) -> dict[str, Any]:
        m = dict(meta or {})
        urgency = str(m.get("order_urgency", "normal")).lower()
        customer_tier = str(m.get("customer_tier", "standard")).lower()
        inventory = str(m.get("inventory_status", "normal")).lower()

        urgency_factor = 1.25 if urgency in {"urgent", "critical"} else 1.0
        vip_factor = 1.2 if customer_tier == "vip" else 1.0
        shortage_factor = 0.9 if inventory in {"short", "critical_low"} else 1.0

        costs = {
            "remeasure": 600.0,
            "rework": 5000.0 * shortage_factor,
            "customer_confirm": 1200.0 * urgency_factor,
            "scrap": 14000.0,
            "release_with_risk": 22000.0 * vip_factor * urgency_factor,
        }
        options: list[dict[str, Any]] = []
        if mode == "auto_release" and tier == "PASS":
            options.append({"action": "release", "cost": 0.0})
        else:
            options.extend(
                [
                    {"action": "remeasure", "cost": costs["remeasure"]},
                    {"action": "rework", "cost": costs["rework"]},
                    {"action": "customer_confirm", "cost": costs["customer_confirm"]},
                    {"action": "scrap", "cost": costs["scrap"]},
                ]
            )
            if mode != "manual_arbitration":
                options.append({"action": "release_with_risk", "cost": costs["release_with_risk"]})
        if mode == "manual_arbitration":
            options = [x for x in options if x["action"] in {"remeasure", "rework", "customer_confirm", "scrap"}]

        best = min(options, key=lambda x: x["cost"]) if options else {"action": "manual_arbitration", "cost": 999999.0}
        must_block = mode == "manual_arbitration" or tier in {"FAIL", "HOLD"}
        can_customer_confirm = mode != "auto_release" and risk_score < 0.75
        return {
            "recommended_action": best["action"],
            "estimated_min_cost": round(float(best["cost"]), 2),
            "must_block": must_block,
            "can_customer_confirm": can_customer_confirm,
            "options": [{"action": x["action"], "cost": round(float(x["cost"]), 2)} for x in sorted(options, key=lambda z: z["cost"])],
            "business_context": {
                "order_urgency": urgency,
                "customer_tier": customer_tier,
                "inventory_status": inventory,
            },
        }

    def integrated_assessment(
        self,
        lot_id: str,
        base_decision: dict[str, Any] | None = None,
        color_metrics: dict[str, Any] | None = None,
        process_params: dict[str, Any] | None = None,
        process_route: str = "gravure",
        film_props: dict[str, Any] | None = None,
        scenario: dict[str, Any] | None = None,
        customer_id: str | None = None,
        sku: str = "",
        current_lab: dict[str, float] | None = None,
        repeatability_std: float | None = None,
        confidence: float | None = None,
        meta: dict[str, Any] | None = None,
        spc_stream_id: str | None = None,
        alt_light_labs: dict[str, dict[str, float]] | None = None,
        post_process_steps: list[str] | None = None,
        storage_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        m = dict(meta or {})
        cm = dict(color_metrics or {})
        bd = dict(base_decision or {})
        sc = dict(scenario or {})
        idem_key = str(m.get("idempotency_key", "")).strip() or None
        idem_payload = {
            "lot_id": lot_id,
            "base_decision": bd,
            "color_metrics": cm,
            "process_route": process_route,
            "sku": sku,
            "customer_id": customer_id,
            "meta": m,
        }
        idem = self.data_guard.check_idempotency(idem_key, idem_payload)
        if idem.get("duplicate"):
            cached = self.data_guard.get_cached_submission(idem_key)
            if cached:
                cached["deduplicated"] = True
                return cached
        if not idem.get("ok", True):
            env = DecisionEnvelopeV2.build(
                status="invalid_input",
                risk_score=0.95,
                confidence=0.98,
                blocking=True,
                warnings=[],
                explanations=["idempotency_key_payload_mismatch"],
                recommendations=["use_new_idempotency_key_for_changed_payload"],
                evidence=[{"source": "data_integrity_guard", "strength": "high", "details": idem}],
                next_actions=[{"priority": 1, "owner": "api_caller", "action": "retry_with_new_idempotency_key"}],
            )
            return {"lot_id": lot_id, **env}

        input_quality = self.validate_assessment_payload(lot_id=lot_id, base_decision=bd, color_metrics=cm, meta=m)
        if not input_quality["valid"]:
            env = DecisionEnvelopeV2.build(
                status="insufficient_data",
                risk_score=0.9,
                confidence=0.92,
                blocking=True,
                warnings=input_quality["warnings"],
                explanations=input_quality["errors"],
                recommendations=["complete required fields before judgement"],
                evidence=input_quality["evidence"],
                next_actions=[{"priority": 1, "owner": "operator", "action": "补全缺失数据后重新判定"}],
            )
            out = {"lot_id": lot_id, **env, "final_decision": {"tier": "HOLD", "mode": "manual_arbitration", "decision_code": "INSUFFICIENT_DATA"}}
            self.data_guard.cache_submission(idem_key, out)
            return out

        process_eval = self.process_coupling.evaluate(process_params or {}, route=process_route) if process_params else {"risk_score": 0.0, "route": process_route}
        app_eval = self.appearance.evaluate(lab=current_lab, film_props=film_props or {}, substrate_bases=None, observer_angles=None) if current_lab and film_props else {"instrument_vs_installation_risk": 0.0}
        customer_eval = self.customer.evaluate(customer_id=customer_id, sku=sku, scenario=sc, metrics=cm) if customer_id else {"risk_score": 0.0, "risk_level": "low"}
        time_report = self.time_stability.report(lot_id=lot_id)
        retest_report = self.retest.dispute_report(lot_id=lot_id)
        run_report = self.run_monitor.get_report()
        cal_status = self.cal_guard.check_status()
        trace = self.lifecycle.get_chain(lot_id=lot_id)
        roll_id = str(m.get("roll_id", "") or "")
        roll_report = self.roll_tracker.summary(roll_id=roll_id) if roll_id else {"status": "no_roll_context"}
        msa_report = self.measurement_guard.report(lot_id=lot_id, window=500)
        spc_id = str(spc_stream_id or m.get("spc_stream_id", lot_id))
        spc_report = self.spc.report(stream_id=spc_id, window=int(m.get("spc_window", 100)))
        metamerism_report = self.metamerism.evaluate(lab_d65=current_lab, alt_lights=alt_light_labs, film_props=film_props) if current_lab else {"metamerism_risk_score": 0.0}
        pp_steps = list(post_process_steps or m.get("post_process_steps", []) or [])
        post_report = self.post_process.predict(lab=current_lab, steps=pp_steps, context=m) if current_lab else {"risk_score": 0.0}
        storage_ctx = dict(storage_context or {})
        if current_lab:
            storage_report = self.storage_predictor.predict(
                lab=current_lab,
                storage_days=float(storage_ctx.get("storage_days", m.get("storage_days", 0.0)) or 0.0),
                temp_c=float(storage_ctx.get("temp_c", m.get("storage_temp_c", 25.0)) or 25.0),
                humidity_pct=float(storage_ctx.get("humidity_pct", m.get("storage_humidity_pct", 50.0)) or 50.0),
                uv_hours=float(storage_ctx.get("uv_hours", m.get("uv_hours", 0.0)) or 0.0),
                vibration_index=float(storage_ctx.get("vibration_index", m.get("vibration_index", 0.0)) or 0.0),
            )
        else:
            storage_report = {"risk_score": 0.0}
        state_snapshot = self.state_machine.snapshot(lot_id=lot_id)
        case_listing = self.list_quality_cases(lot_id=lot_id, last_n=200)
        case_rows = list(case_listing.get("rows", []))
        active_cases = [x for x in case_rows if str(x.get("state", "open")) not in {"closed", "cancelled"}]
        open_critical_case = any(str(x.get("severity", "")).lower() == "critical" for x in active_cases)
        open_high_case_count = sum(1 for x in active_cases if str(x.get("severity", "")).lower() in {"high", "critical"})
        case_sla = self.get_case_sla_report(lot_id=lot_id)
        case_governance = {
            "active_case_count": len(active_cases),
            "open_critical_case": open_critical_case,
            "open_high_case_count": open_high_case_count,
            "sla": case_sla,
        }

        boundary_context = {
            "sensor_health": m.get("sensor_health", "ok"),
            "calibration_overdue_count": cal_status.get("overdue_count", 0),
            "trace_integrity": bool(trace.get("integrity", False)) if "error" not in trace else False,
            "trace_missing_required": len(trace.get("missing_required_stages", [])) if "error" not in trace else len(self.lifecycle.REQUIRED_STAGES),
            "data_valid": bool(bd.get("quality_gate", {}).get("valid", True) and input_quality["valid"]),
            "inspection_chain_integrity": bool(retest_report.get("inspection_chain_integrity", True)),
            "suspicious_ratio": float(bd.get("quality_gate", {}).get("suspicious_ratio", 0.0) or 0.0),
            "golden_status": m.get("golden_status", "ok"),
            "repeatability_std": float(repeatability_std if _is_number(repeatability_std) else msa_report.get("repeatability_std", 0.0) or 0.0),
            "msa_risk": float(msa_report.get("gage_risk_score", 0.0) or 0.0),
            "spc_risk": float(spc_report.get("risk_score", 0.0) or 0.0),
            "metamerism_risk": float(metamerism_report.get("metamerism_risk_score", 0.0) or 0.0),
            "post_process_risk": float(post_report.get("risk_score", 0.0) or 0.0),
            "storage_risk": float(storage_report.get("risk_score", 0.0) or 0.0),
            "rule_conflict": bool(m.get("rule_conflict", False)),
            "missing_critical_data": bool(m.get("missing_critical_data", False)),
            "environment_severity": float(m.get("environment_severity", 0.0) or 0.0),
            "process_risk": float(process_eval.get("risk_score", 0.0) or 0.0),
            "appearance_risk": float(app_eval.get("instrument_vs_installation_risk", 0.0) or 0.0),
            "customer_risk": float(customer_eval.get("risk_score", 0.0) or 0.0),
            "settling_insufficient": bool(time_report.get("settling_time_insufficient", False)),
            "retest_conflict": bool(retest_report.get("conflict", False)),
            "tail_drift_detected": bool(run_report.get("tail_drift", {}).get("detected", False)),
            "roll_transition_risk": float(roll_report.get("transition_risk_score", 0.0) or 0.0),
            "roll_tail_risk": float(roll_report.get("tail_risk_score", 0.0) or 0.0),
            "open_critical_case": bool(open_critical_case),
            "open_high_case_count": int(open_high_case_count),
            "case_overdue_actions": int(case_sla.get("overdue_count", 0) or 0),
            "lifecycle_state": state_snapshot.get("current_state", "created"),
            "confidence": float(confidence if _is_number(confidence) else bd.get("confidence", 1.0) or 1.0),
        }
        boundary = self.evaluate_auto_boundary(context=boundary_context, meta=m)

        base_tier = str(bd.get("tier", "UNKNOWN"))
        final_tier = base_tier
        if final_tier not in {"PASS", "MARGINAL", "FAIL", "HOLD"}:
            avg_de = float(cm.get("avg_de", 0.0) or 0.0)
            final_tier = "PASS" if avg_de <= 1.0 else "MARGINAL" if avg_de <= 2.5 else "FAIL"
        if boundary["manual_arbitration_required"]:
            final_tier = "HOLD"
        elif boundary["manual_review_required"] and final_tier == "PASS":
            final_tier = "MARGINAL"

        weights = {
            "process": 0.16,
            "appearance": 0.11,
            "customer": 0.11,
            "tail_drift": 0.09,
            "settling": 0.08,
            "data": 0.08,
            "msa": 0.1,
            "spc": 0.1,
            "metamerism": 0.05,
            "post_process": 0.04,
            "storage": 0.03,
            "roll": 0.05,
        }
        risk_score = 0.0
        risk_score += float(process_eval.get("risk_score", 0.0) or 0.0) * weights["process"]
        risk_score += float(app_eval.get("instrument_vs_installation_risk", 0.0) or 0.0) * weights["appearance"]
        risk_score += float(customer_eval.get("risk_score", 0.0) or 0.0) * weights["customer"]
        risk_score += (1.0 if bool(run_report.get("tail_drift", {}).get("detected", False)) else 0.0) * weights["tail_drift"]
        risk_score += (1.0 if bool(time_report.get("settling_time_insufficient", False)) else 0.0) * weights["settling"]
        risk_score += min(1.0, float(boundary_context.get("suspicious_ratio", 0.0)) * 3.0) * weights["data"]
        risk_score += float(msa_report.get("gage_risk_score", 0.0) or 0.0) * weights["msa"]
        risk_score += float(spc_report.get("risk_score", 0.0) or 0.0) * weights["spc"]
        risk_score += float(metamerism_report.get("metamerism_risk_score", 0.0) or 0.0) * weights["metamerism"]
        risk_score += float(post_report.get("risk_score", 0.0) or 0.0) * weights["post_process"]
        risk_score += float(storage_report.get("risk_score", 0.0) or 0.0) * weights["storage"]
        roll_risk = max(float(roll_report.get("transition_risk_score", 0.0) or 0.0), float(roll_report.get("tail_risk_score", 0.0) or 0.0))
        risk_score += roll_risk * weights["roll"]
        if boundary["manual_arbitration_required"]:
            risk_score = max(risk_score, 0.95)
        elif boundary["manual_review_required"]:
            risk_score = max(risk_score, 0.55)
        risk_score = round(min(1.0, risk_score), 4)

        mode = boundary["mode"]
        decision_code = (
            "LIFECYCLE_AUTO_BLOCK"
            if boundary["hard_blocks"]
            else "LIFECYCLE_ARBITRATION"
            if mode == "manual_arbitration"
            else "LIFECYCLE_REVIEW"
            if mode == "manual_review"
            else "LIFECYCLE_AUTO_RELEASE"
        )
        reasons: list[str] = []
        reasons.extend(boundary["hard_blocks"])
        reasons.extend(boundary["arbitration_triggers"])
        reasons.extend(boundary["review_triggers"])
        reasons = sorted(set(reasons))

        process_reverse = self.process_coupling.reverse_infer(
            color_symptom={"dL": cm.get("dL", cm.get("avg_dL", 0.0)), "db": cm.get("db", cm.get("avg_db", 0.0))},
            params=process_params or {},
            route=process_route,
        )
        symptom = str(m.get("symptom", "偏黄"))
        trace_root = self.lifecycle.find_root_cause(lot_id=lot_id, symptom=symptom)
        cause_candidates: list[dict[str, Any]] = []
        for s in process_reverse.get("suspects", []):
            cause_candidates.append({"cause": s, "evidence_strength": "medium", "source": "process_coupling"})
        for s in trace_root.get("suspects", []):
            cause_candidates.append({"cause": s.get("factor"), "evidence_strength": s.get("likelihood", "medium"), "source": "traceability"})
        if not cause_candidates:
            cause_candidates.append({"cause": "unknown", "evidence_strength": "low", "source": "insufficient_data"})

        disposition = self._business_disposition(tier=final_tier, mode=mode, risk_score=risk_score, meta=m)
        capa_candidates = self.suggest_capa_candidates(triggers=reasons)

        prioritized_actions: list[dict[str, Any]] = []
        if boundary["hard_blocks"]:
            prioritized_actions.append({"priority": 1, "owner": "quality_manager", "action": "clear_hard_blocks_before_any_release"})
        if "process_coupling_risk" in boundary["review_triggers"] or "process_coupling_accident_edge" in boundary["arbitration_triggers"]:
            prioritized_actions.append({"priority": 1, "owner": "process_engineer", "action": "check_process_first_do_not_adjust_recipe_first"})
        if time_report.get("settling_time_insufficient"):
            prioritized_actions.append({"priority": 1, "owner": "operator", "action": "hold_until_minimum_settling_time_reached"})
        if run_report.get("tail_drift", {}).get("detected"):
            prioritized_actions.append({"priority": 2, "owner": "operator", "action": "quarantine_tail_segment_and_remeasure"})
        if retest_report.get("conflict"):
            prioritized_actions.append({"priority": 1, "owner": "quality_manager", "action": "start_arbitration_test_with_locked_device_and_operator"})
        if msa_report.get("blocking"):
            prioritized_actions.append({"priority": 1, "owner": "quality_manager", "action": "measurement_system_requalification_before_release"})
        if roll_report.get("tail_sustained_drift"):
            prioritized_actions.append({"priority": 1, "owner": "operator", "action": "quarantine_tail_roll_segment_and_issue_rework_ticket"})
        if float(roll_report.get("transition_risk_score", 0.0) or 0.0) >= 0.45:
            prioritized_actions.append({"priority": 1, "owner": "process_engineer", "action": "lock_transition_zone_until_stable_recheck_passes"})
        if int(case_sla.get("overdue_count", 0) or 0) > 0:
            prioritized_actions.append({"priority": 1, "owner": "quality_manager", "action": "clear_overdue_quality_case_actions_before_release"})
        if not prioritized_actions:
            prioritized_actions.append({"priority": 2, "owner": "quality_manager", "action": "routine_monitoring"})
        prioritized_actions = sorted(prioritized_actions, key=lambda x: int(x["priority"]))
        case_ref: dict[str, Any] | None = None

        confidence_parts = [
            float(confidence if _is_number(confidence) else bd.get("confidence", 0.75) or 0.75),
            float(input_quality.get("data_trust_score", 0.7) or 0.7),
            float(msa_report.get("measurement_confidence", 0.7) or 0.7),
        ]
        combined_conf = round(max(0.05, min(0.99, _safe_mean(confidence_parts))), 4)

        evidence: list[dict[str, Any]] = []
        evidence.extend(input_quality.get("evidence", []))
        evidence.extend(
            [
                {"source": "process_coupling", "strength": "high" if process_eval.get("risk_score", 0) >= 0.7 else "medium", "details": process_eval},
                {"source": "appearance", "strength": "medium", "details": app_eval},
                {"source": "customer_acceptance", "strength": "medium", "details": customer_eval},
                {"source": "msa", "strength": "high" if msa_report.get("blocking") else "medium", "details": msa_report},
                {"source": "spc", "strength": "high" if not spc_report.get("stable", True) else "medium", "details": spc_report},
                {"source": "metamerism", "strength": "medium", "details": metamerism_report},
                {"source": "post_process", "strength": "medium", "details": post_report},
                {"source": "storage_transport", "strength": "medium", "details": storage_report},
                {"source": "roll_tracker", "strength": "high" if roll_report.get("tail_sustained_drift") else "medium", "details": roll_report},
                {"source": "case_governance", "strength": "high" if case_sla.get("critical_overdue_count", 0) else "medium", "details": case_governance},
                {"source": "traceability", "strength": "high" if trace.get("integrity") else "medium", "details": {"integrity": trace.get("integrity"), "missing": trace.get("missing_required_stages", [])}},
            ]
        )

        status = "auto_release" if mode == "auto_release" and final_tier == "PASS" else "manual_review_required" if mode == "manual_review" else "manual_arbitration_required"
        if boundary["hard_blocks"]:
            status = "auto_blocked"
        envelope = DecisionEnvelopeV2.build(
            status=status,
            risk_score=risk_score,
            confidence=combined_conf,
            blocking=bool(boundary["hard_blocks"]),
            warnings=boundary["review_triggers"],
            explanations=reasons,
            recommendations=capa_candidates.get("actions", []),
            evidence=evidence,
            next_actions=prioritized_actions,
        )

        quality_fact_layer = {
            "tier": final_tier,
            "mode": mode,
            "decision_code": decision_code,
            "boundary": boundary,
            "rule_trace": boundary.get("rule_trace", {}),
            "causal_candidates": cause_candidates,
            "state_snapshot": state_snapshot,
            "traceability_integrity": trace.get("integrity", False),
            "roll_context": {"roll_id": roll_id, "status": roll_report.get("status")},
            "case_governance": case_governance,
        }
        business_suggestion_layer = {
            "disposition_plan": disposition,
            "capa_candidates": capa_candidates,
            "customer_confirmation_allowed": disposition.get("can_customer_confirm", False),
        }
        result = {
            "lot_id": lot_id,
            "final_decision": {
                "tier": final_tier,
                "mode": mode,
                "decision_code": decision_code,
                "auto_release_allowed": boundary["auto_release_allowed"],
                "reasons": reasons,
            },
            "risk_score": risk_score,
            "boundary": boundary,
            "disposition_plan": disposition,
            "quality_fact_layer": quality_fact_layer,
            "business_suggestion_layer": business_suggestion_layer,
            "module_outputs": {
                "process_coupling": process_eval,
                "appearance": app_eval,
                "customer_acceptance": customer_eval,
                "time_stability": time_report,
                "retest_dispute": retest_report,
                "run_monitor": run_report,
                "calibration": cal_status,
                "traceability": trace,
                "msa": msa_report,
                "spc": spc_report,
                "metamerism": metamerism_report,
                "post_process": post_report,
                "storage_transport": storage_report,
                "roll_tracker": roll_report,
                "case_governance": case_governance,
            },
            "version_links": self.get_version_links(lot_id),
            "prioritized_actions": prioritized_actions,
            "explainability": {
                "problem_to_root_to_action_closed_loop": True,
                "human_takeover_required": mode != "auto_release",
                "can_auto_release": boundary["auto_release_allowed"],
                "uncertainty_sources": [x for x in ["low_confidence" if combined_conf < 0.6 else "", "insufficient_trace" if not trace.get("integrity", True) else ""] if x],
            },
            **envelope,
        }

        auto_case_open = bool(m.get("auto_case_open", True))
        if auto_case_open and (result["status"] in {"auto_blocked", "manual_arbitration_required"} or risk_score >= 0.75):
            reason_key = "|".join(sorted(reasons)[:6])
            case_key = f"{lot_id}|{decision_code}|{mode}|{reason_key}"
            case_out = self.open_quality_case(
                lot_id=lot_id,
                case_type="nonconformance",
                issue=";".join(reasons[:4]) if reasons else decision_code,
                severity="critical" if result["status"] == "auto_blocked" else "high",
                source="integrated_assessment",
                created_by=str(m.get("actor", "system")),
                linked_snapshot_id=None,
                linked_decision_code=decision_code,
                dedup_key=case_key,
                metadata={"risk_score": risk_score, "status": result["status"]},
            )
            if case_out.get("opened"):
                case_ref = {
                    "case_id": case_out.get("case_id"),
                    "state": case_out.get("state"),
                    "deduplicated": bool(case_out.get("deduplicated", False)),
                }
                result["case_ref"] = case_ref
                result["quality_fact_layer"]["case_ref"] = case_ref
                result["business_suggestion_layer"]["case_ref"] = case_ref
                if not any(str(x.get("action", "")).startswith("open_or_follow_quality_case") for x in prioritized_actions):
                    prioritized_actions.insert(0, {"priority": 1, "owner": "quality_manager", "action": "open_or_follow_quality_case"})
                    prioritized_actions = sorted(prioritized_actions, key=lambda x: int(x["priority"]))
                    result["next_actions"] = prioritized_actions
                    result["prioritized_actions"] = prioritized_actions

        preview_roles = m.get("roles_preview", ["operator", "process_engineer", "quality_manager"])
        role_rows: dict[str, Any] = {}
        if isinstance(preview_roles, list):
            for role in preview_roles[:8]:
                r = str(role).strip()
                if r:
                    role_rows[r] = self.build_role_view(r, result)
        result["role_views"] = role_rows

        alert_severity = "critical" if result["status"] == "auto_blocked" else "high" if risk_score >= 0.7 else "medium"
        self.push_alert(
            alert_type="LIFECYCLE_DECISION",
            severity=alert_severity,
            message=f"{lot_id}:{result['status']}:{decision_code}",
            source="integrated_assessment",
            evidence={"risk_score": risk_score, "mode": mode},
            dedup_key=f"{lot_id}|{decision_code}|{mode}",
        )

        snapshot_id = f"AS-{int(time.time())}-{len(self._assessment_snapshots)+1:06d}"
        self._assessment_snapshots[snapshot_id] = {
            "snapshot_id": snapshot_id,
            "lot_id": lot_id,
            "created_at": _now_iso(),
            "input": {
                "base_decision": bd,
                "color_metrics": cm,
                "process_params": process_params or {},
                "process_route": process_route,
                "film_props": film_props or {},
                "scenario": sc,
                "customer_id": customer_id,
                "sku": sku,
                "current_lab": current_lab,
                "repeatability_std": repeatability_std,
                "confidence": confidence,
                "meta": m,
            },
            "output": result,
        }
        result["snapshot_id"] = snapshot_id
        result["deduplicated"] = False
        if case_ref and case_ref.get("case_id"):
            self.add_case_action(
                case_id=str(case_ref.get("case_id")),
                action_type="link_snapshot",
                owner="quality_manager",
                description=f"link integrated assessment snapshot {snapshot_id}",
                actor=str(m.get("actor", "system")),
                mandatory=False,
                priority=4,
                payload={"snapshot_id": snapshot_id, "decision_code": decision_code},
            )
        self.data_guard.cache_submission(idem_key, result)
        return result

    def generate_release_report(
        self,
        lot_id: str,
        assessment: dict[str, Any],
        metrics: dict[str, Any],
        audience: str = "internal",
    ) -> dict[str, Any]:
        fd = assessment.get("final_decision", {})
        decision_doc = {
            "tier": fd.get("tier"),
            "decision_code": fd.get("decision_code"),
            "reasons": fd.get("reasons", []),
            "hard_gate": assessment.get("boundary", {}),
            "action_plan": assessment.get("disposition_plan", {}),
        }
        report = self.report_factory.release_report(lot_id=lot_id, decision=decision_doc, metrics=metrics, audience=audience)
        return {
            "lot_id": lot_id,
            "audience": audience,
            "report": report,
            "snapshot": {
                "mode": fd.get("mode"),
                "risk_score": assessment.get("risk_score"),
            },
        }

    def list_assessment_snapshots(self, lot_id: str | None = None, last_n: int = 20) -> dict[str, Any]:
        rows = list(self._assessment_snapshots.values())
        if lot_id:
            rows = [x for x in rows if x.get("lot_id") == lot_id]
        rows = rows[-max(1, int(last_n)) :]
        return {"count": len(rows), "rows": rows}

    def replay_assessment(
        self,
        snapshot_id: str,
        force_lifecycle_rule_version: str | None = None,
        meta_patch: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        snap = self._assessment_snapshots.get(snapshot_id)
        if not snap:
            return {"error": "snapshot_not_found", "snapshot_id": snapshot_id}
        inp = dict(snap.get("input", {}))
        meta = dict(inp.get("meta", {}))
        if force_lifecycle_rule_version:
            meta["force_lifecycle_rule_version"] = force_lifecycle_rule_version
        if isinstance(meta_patch, dict):
            meta.update(meta_patch)
        # Replaying should not deduplicate with original request.
        if "idempotency_key" in meta:
            meta["idempotency_key"] = f"replay-{snapshot_id}-{int(time.time())}"
        out = self.integrated_assessment(
            lot_id=snap.get("lot_id", ""),
            base_decision=inp.get("base_decision"),
            color_metrics=inp.get("color_metrics"),
            process_params=inp.get("process_params"),
            process_route=str(inp.get("process_route", "gravure")),
            film_props=inp.get("film_props"),
            scenario=inp.get("scenario"),
            customer_id=inp.get("customer_id"),
            sku=str(inp.get("sku", "")),
            current_lab=inp.get("current_lab"),
            repeatability_std=inp.get("repeatability_std"),
            confidence=inp.get("confidence"),
            meta=meta,
        )
        return {
            "replayed_from": snapshot_id,
            "new_snapshot_id": out.get("snapshot_id"),
            "result": out,
        }

    def simulate_rule_impact(
        self,
        snapshot_id: str,
        rule_versions: list[str],
        meta_patch: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        snap = self._assessment_snapshots.get(snapshot_id)
        if not snap:
            return {"error": "snapshot_not_found", "snapshot_id": snapshot_id}
        versions = [str(v) for v in rule_versions if str(v).strip()]
        if not versions:
            return {"error": "rule_versions_empty"}
        base_out = snap.get("output", {})
        base_dec = base_out.get("final_decision", {})
        rows: list[dict[str, Any]] = []
        for ver in versions:
            replay = self.replay_assessment(
                snapshot_id=snapshot_id,
                force_lifecycle_rule_version=ver,
                meta_patch=meta_patch,
            )
            result = replay.get("result", {})
            fd = result.get("final_decision", {})
            rows.append(
                {
                    "rule_version": ver,
                    "tier": fd.get("tier"),
                    "mode": fd.get("mode"),
                    "decision_code": fd.get("decision_code"),
                    "status": result.get("status"),
                    "risk_score": result.get("risk_score"),
                    "snapshot_id": result.get("snapshot_id"),
                    "changed_vs_baseline": fd.get("tier") != base_dec.get("tier") or fd.get("mode") != base_dec.get("mode"),
                }
            )
        changed = sum(1 for x in rows if x["changed_vs_baseline"])
        return {
            "snapshot_id": snapshot_id,
            "baseline": {
                "tier": base_dec.get("tier"),
                "mode": base_dec.get("mode"),
                "decision_code": base_dec.get("decision_code"),
                "status": base_out.get("status"),
                "risk_score": base_out.get("risk_score"),
            },
            "simulations": rows,
            "changed_count": changed,
            "total": len(rows),
        }

    def simulate_rule_impact_batch(
        self,
        snapshot_ids: list[str],
        rule_versions: list[str],
        meta_patch: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        sids = [str(x) for x in snapshot_ids if str(x).strip()]
        if not sids:
            return {"error": "snapshot_ids_empty"}
        rows: list[dict[str, Any]] = []
        for sid in sids:
            one = self.simulate_rule_impact(snapshot_id=sid, rule_versions=rule_versions, meta_patch=meta_patch)
            rows.append({"snapshot_id": sid, "result": one})
        changed = 0
        total = 0
        for x in rows:
            r = x.get("result", {})
            changed += int(r.get("changed_count", 0) or 0)
            total += int(r.get("total", 0) or 0)
        return {
            "batch_count": len(rows),
            "changed_count": changed,
            "total_simulations": total,
            "change_ratio": round(changed / total, 4) if total > 0 else 0.0,
            "rows": rows,
        }

    def open_complaint_case(self, lot_id: str, symptom: str, severity: str = "medium") -> dict[str, Any]:
        rc = self.lifecycle.find_root_cause(lot_id, symptom)
        root = rc.get("conclusion", "unknown")
        ranked = []
        for s in rc.get("suspects", []):
            score = 0.8 if s.get("likelihood") == "high" else 0.6 if s.get("likelihood") == "medium" else 0.4
            ranked.append({"factor": s.get("factor"), "stage": s.get("stage"), "score": score})
        ranked.sort(key=lambda x: x["score"], reverse=True)
        cause_chain = [{"from": "symptom", "to": x.get("factor"), "weight": x.get("score")} for x in ranked[:6]]
        capa = self.capa.auto_generate(lot_id=lot_id, issue=symptom, root_cause=root, severity=severity)
        summary = self.report_factory.complaint_summary(lot_id=lot_id, symptom=symptom, root_cause=rc, capa=capa)
        return {
            "root_cause": rc,
            "ranked_candidates": ranked,
            "cause_chain": cause_chain,
            "capa": capa,
            "summary": summary,
            "state_snapshot": self.state_machine.snapshot(lot_id),
        }

    def generate_complaint_summary(self, lot_id: str, symptom: str, severity: str = "medium") -> dict[str, Any]:
        out = self.open_complaint_case(lot_id=lot_id, symptom=symptom, severity=severity)
        rc = out["root_cause"]
        return self.report_factory.root_cause_report(
            lot_id=lot_id,
            symptom=symptom,
            suspects=rc.get("suspects", []),
            conclusion=rc.get("conclusion", "unknown"),
        )

    def known_boundaries(self) -> dict[str, Any]:
        """
        Explicitly documents current system boundaries for rollout governance.
        """
        return {
            "boundaries": [
                "spectral_mismatch_still_modeled_by_proxy_rules_not_full_spectral_curve",
                "advanced_modules_currently_in_memory_without_persistent_database_tables",
                "machine_fingerprint_is_statistical_bias_not_physical_device_calibration_transfer_matrix",
                "learning_loop_is_frequency_based_priority_not_full_causal_model",
                "integrated_assessment_is_rule_first_not_end_to_end_supervised_model",
                "spc_and_msa_are_runtime_estimators_not_formal_certified_qms_records",
                "post_process_and_storage_models_are_proxy_estimators_requiring_field_calibration",
                "roll_length_risk_requires_dense_meter_sampling_for_high_confidence",
                "quality_case_workflow_supports_local_file_and_single-node_sqlite_persistence_but_needs_multi-node_workflow_backend_for_enterprise_scale",
                "manual_override_policy_requires_external_approval_workflow_integration",
            ],
            "explicit_unknown_states": [
                "unknown",
                "insufficient_data",
                "low_confidence",
                "conflict_detected",
                "manual_review_required",
            ],
            "last_reviewed": _now_iso(),
        }


UltimateColorFilmSystem = UltimateColorFilmSystemV2Optimized


if __name__ == "__main__":
    import random

    random.seed(7)
    sys = UltimateColorFilmSystemV2Optimized()

    print("[self-test] preflight")
    pre = sys.pre_flight_check(28, 65, operator="op_a")
    print(pre["ready"], pre["recommendation"])

    print("[self-test] run monitor startup + transition")
    sys.run_monitor.set_target({"L": 62, "a": 3.2, "b": 14.8}, tolerance=2.5, run_id="RUN-DEMO")
    for i in range(1, 6):
        lab = {"L": 62 + 0.7 + random.gauss(0, 0.1), "a": 3.2 + random.gauss(0, 0.06), "b": 14.8 + random.gauss(0, 0.08)}
        sys.run_monitor.add_sample(lab, seq=i)
    sys.run_monitor.mark_changeover("ink", at_seq=6, stabilization_samples=5)
    for i in range(6, 15):
        lab = {"L": 62 + random.gauss(0, 0.15), "a": 3.2 + random.gauss(0, 0.08), "b": 14.8 + random.gauss(0, 0.09)}
        sys.run_monitor.add_sample(lab, seq=i)
    rpt = sys.run_monitor.get_report()
    print(rpt["status"], rpt["startup_scrap_risk"], rpt["changeover_transition_risk"])

    print("[self-test] traceability + tamper check")
    sys.lifecycle.add_event("LOT-A", "ink_receipt", {"ink_model": "CYAN-PRO", "lot": "INK-1"})
    sys.lifecycle.add_event("LOT-A", "substrate_receipt", {"lot": "SUB-1", "substrate_db": 1.1})
    sys.lifecycle.add_event("LOT-A", "printing", {"dry_temp": 72, "roller_life_pct": 86})
    chain = sys.lifecycle.get_chain("LOT-A")
    assert chain["integrity"] is True
    rc = sys.lifecycle.find_root_cause("LOT-A", "偏黄")
    complaint = sys.open_complaint_case("LOT-A", "偏黄", "high")
    print(rc["conclusion"], complaint["capa"]["case_id"])

    print("[self-test] advanced modules")
    sys.register_customer_profile(
        "CUST-A",
        {
            "default_tolerance": 2.3,
            "sku_tolerance": {"SKU-A": 2.0},
            "sensitivity": {"yellow": 1.3, "uniformity": 1.2},
        },
    )
    sys.record_time_stability("LOT-A", 1.0, {"L": 62.0, "a": 3.2, "b": 14.8}, stage="first", verdict="PASS")
    sys.record_time_stability("LOT-A", 4.0, {"L": 61.3, "a": 3.4, "b": 15.7}, stage="recheck", verdict="FAIL")
    sys.record_retest(
        "LOT-A",
        "retest",
        "DEV-1",
        "OP-1",
        {"avg_de": 1.2},
        {"avg_de": 1.0},
        {"tier": "PASS"},
    )
    sys.record_retest(
        "LOT-A",
        "arbitration",
        "DEV-2",
        "OP-2",
        {"avg_de": 2.8},
        {"avg_de": 2.6},
        {"tier": "FAIL"},
    )
    assess = sys.integrated_assessment(
        lot_id="LOT-A",
        base_decision={"tier": "PASS", "confidence": 0.82, "quality_gate": {"valid": True, "suspicious_ratio": 0.03}},
        color_metrics={"avg_de": 1.35, "max_de": 2.7, "db": 0.8, "uniformity_std": 0.42},
        process_params={"viscosity": 28, "line_speed": 112, "dry_temp": 76, "tension": 27, "pressure": 3.3},
        process_route="gravure",
        film_props={"opacity": 0.45, "haze": 18, "gloss": 62, "thickness_um": 80, "emboss_direction": "md"},
        scenario={"light_source": "warm"},
        customer_id="CUST-A",
        sku="SKU-A",
        current_lab={"L": 62.0, "a": 3.2, "b": 14.8},
        meta={"environment_severity": 0.55, "golden_status": "ok"},
    )
    print(assess["final_decision"]["tier"], assess["final_decision"]["mode"], assess["risk_score"])
