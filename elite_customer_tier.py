from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from threading import RLock
from typing import Any

from elite_decision_center import apply_policy_patch


DEFAULT_CUSTOMER_TIER: dict[str, Any] = {
    "default_tier": "standard",
    "tiers": {
        "vip": {
            "description": "Key account with strict quality preference.",
            "decision_policy_patch": {
                "auto_release_min_confidence_delta": 0.04,
                "manual_review_min_confidence_delta": 0.02,
                "max_avg_ratio_for_auto_release_delta": -0.04,
                "max_p95_ratio_for_auto_release_delta": -0.04,
            },
        },
        "standard": {
            "description": "Enterprise default balance policy.",
            "decision_policy_patch": {},
        },
        "growth": {
            "description": "Balanced throughput improvement with controlled risk.",
            "decision_policy_patch": {
                "auto_release_min_confidence_delta": -0.005,
                "max_avg_ratio_for_auto_release_delta": 0.005,
                "max_p95_ratio_for_auto_release_delta": 0.005,
            },
        },
        "economy": {
            "description": "Cost-sensitive segment under managed guardrails.",
            "decision_policy_patch": {
                "auto_release_min_confidence_delta": -0.015,
                "max_avg_ratio_for_auto_release_delta": 0.015,
                "max_p95_ratio_for_auto_release_delta": 0.015,
            },
        },
    },
    "customers": {},
}


_TIER_CACHE: dict[str, dict[str, Any]] = {}
_TIER_CACHE_MTIME: dict[str, float] = {}
_TIER_CACHE_LOCK = RLock()


def load_customer_tier_config(config_path: Path | None) -> tuple[dict[str, Any], str]:
    if config_path is None:
        return deepcopy(DEFAULT_CUSTOMER_TIER), "builtin_default"
    resolved = str(config_path.resolve())
    try:
        mtime = config_path.stat().st_mtime
    except OSError:
        mtime = -1.0
    with _TIER_CACHE_LOCK:
        if resolved in _TIER_CACHE and _TIER_CACHE_MTIME.get(resolved) == mtime:
            return deepcopy(_TIER_CACHE[resolved]), resolved
    raw = json.loads(config_path.read_text(encoding="utf-8-sig"))
    if not isinstance(raw, dict):
        raise ValueError("customer tier config must be a JSON object")
    cfg = deepcopy(DEFAULT_CUSTOMER_TIER)
    cfg.update(raw)
    if "tiers" in raw and isinstance(raw["tiers"], dict):
        cfg["tiers"] = raw["tiers"]
    if "customers" in raw and isinstance(raw["customers"], dict):
        cfg["customers"] = raw["customers"]
    with _TIER_CACHE_LOCK:
        _TIER_CACHE[resolved] = cfg
        _TIER_CACHE_MTIME[resolved] = mtime
    return deepcopy(cfg), resolved


def resolve_customer_tier(
    customer_tier_config: dict[str, Any],
    customer_tier: str | None = None,
    customer_id: str | None = None,
) -> tuple[str, dict[str, Any]]:
    tiers = customer_tier_config.get("tiers", {})
    customers = customer_tier_config.get("customers", {})
    default_tier = str(customer_tier_config.get("default_tier", "standard")).lower()

    tier = None
    if customer_tier:
        tier = str(customer_tier).strip().lower()
    elif customer_id:
        mapping = customers.get(str(customer_id), {})
        if isinstance(mapping, dict) and "tier" in mapping:
            tier = str(mapping["tier"]).strip().lower()
        elif isinstance(mapping, str):
            tier = mapping.strip().lower()
    if tier is None or tier not in tiers:
        tier = default_tier if default_tier in tiers else "standard"

    tier_obj = tiers.get(tier, {})
    if not isinstance(tier_obj, dict):
        tier_obj = {}
    return tier, tier_obj


def apply_customer_tier_to_policy(
    base_policy: dict[str, Any],
    customer_tier_config: dict[str, Any],
    customer_tier: str | None = None,
    customer_id: str | None = None,
) -> dict[str, Any]:
    tier, tier_obj = resolve_customer_tier(
        customer_tier_config=customer_tier_config,
        customer_tier=customer_tier,
        customer_id=customer_id,
    )
    patch_inner = tier_obj.get("decision_policy_patch", {})
    patch = {"decision_policy": patch_inner if isinstance(patch_inner, dict) else {}}
    policy = apply_policy_patch(base_policy, patch)
    return {
        "policy": policy,
        "tier": tier,
        "tier_description": tier_obj.get("description"),
        "patch": patch,
    }
