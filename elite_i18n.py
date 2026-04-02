"""
Internationalization (i18n) framework for SENIA Elite.

Simple message catalog system supporting Chinese (zh) and English (en).
Messages are keyed by dot-separated identifiers.

Usage:
    from elite_i18n import t, set_locale

    set_locale("en")
    print(t("decision.auto_release"))  # "Auto Release - Quality meets standards"
    set_locale("zh")
    print(t("decision.auto_release"))  # "自动放行 — 质量达标"
"""

from __future__ import annotations

from threading import local
from typing import Any

_thread_local = local()
_DEFAULT_LOCALE = "zh"

# ─── Message Catalog ───────────────────────────────────────

MESSAGES: dict[str, dict[str, str]] = {
    # Decision outcomes
    "decision.auto_release": {
        "zh": "自动放行 — 质量达标",
        "en": "Auto Release — Quality meets standards",
    },
    "decision.manual_review": {
        "zh": "需人工复核 — 请操作员确认",
        "en": "Manual Review Required — Operator confirmation needed",
    },
    "decision.recapture": {
        "zh": "需重新拍摄 — 图像质量不足",
        "en": "Recapture Needed — Insufficient image quality",
    },
    "decision.hold_and_escalate": {
        "zh": "暂停并上报 — 发现严重偏差",
        "en": "Hold & Escalate — Critical deviation detected",
    },

    # Decision details
    "decision.customer_ok": {
        "zh": "颜色一致性稳定，可按客户标准交付。",
        "en": "Color consistency stable, ready for delivery per customer standards.",
    },
    "decision.customer_review": {
        "zh": "颜色偏差接近上限，建议人工比对确认。",
        "en": "Color deviation near upper limit, manual comparison recommended.",
    },
    "decision.boss_throughput_ok": {
        "zh": "产线效率正常，质量放行无阻碍。",
        "en": "Production line efficiency normal, quality release unimpeded.",
    },
    "decision.boss_throughput_warn": {
        "zh": "质量问题可能影响产量，建议关注。",
        "en": "Quality issues may affect throughput, attention recommended.",
    },

    # Risk levels
    "risk.low": {"zh": "低风险", "en": "Low Risk"},
    "risk.medium": {"zh": "中风险", "en": "Medium Risk"},
    "risk.high": {"zh": "高风险", "en": "High Risk"},
    "risk.critical": {"zh": "严重风险", "en": "Critical Risk"},

    # Process advice
    "advice.step_adjust": {
        "zh": "建议先小步调参并复测，再批量放行。",
        "en": "Recommend small parameter adjustments with re-testing before batch release.",
    },
    "advice.normal_range": {
        "zh": "偏差在正常范围，无明确调色方向。",
        "en": "Deviation within normal range, no clear color adjustment direction.",
    },

    # Calibration
    "calibration.overdue": {
        "zh": "校准已过期，请立即重新校准。",
        "en": "Calibration overdue, please recalibrate immediately.",
    },
    "calibration.ok": {
        "zh": "校准状态正常。",
        "en": "Calibration status normal.",
    },

    # Report labels
    "report.title": {
        "zh": "色膜质量检测报告",
        "en": "Color Film Quality Inspection Report",
    },
    "report.lot_id": {"zh": "批次号", "en": "Lot ID"},
    "report.product": {"zh": "产品", "en": "Product"},
    "report.profile": {"zh": "材质类型", "en": "Material Profile"},
    "report.decision": {"zh": "判定结果", "en": "Decision"},
    "report.color_metrics": {"zh": "颜色指标", "en": "Color Metrics"},
    "report.confidence": {"zh": "置信度", "en": "Confidence"},
    "report.process_advice": {"zh": "工艺建议", "en": "Process Recommendations"},
    "report.timestamp": {"zh": "检测时间", "en": "Inspection Time"},

    # Quality flags
    "flag.low_confidence": {
        "zh": "置信度偏低，结果仅供参考。",
        "en": "Low confidence, results for reference only.",
    },
    "flag.low_sharpness": {
        "zh": "图像清晰度不足，建议重新拍摄。",
        "en": "Image sharpness insufficient, recapture recommended.",
    },
    "flag.uneven_lighting": {
        "zh": "光照不均匀，可能影响色差计算。",
        "en": "Uneven lighting detected, may affect color measurement.",
    },

    # Tier labels
    "tier.vip": {"zh": "VIP 客户", "en": "VIP Customer"},
    "tier.standard": {"zh": "标准客户", "en": "Standard Customer"},
    "tier.growth": {"zh": "成长客户", "en": "Growth Customer"},
    "tier.economy": {"zh": "经济客户", "en": "Economy Customer"},

    # System messages
    "system.startup": {"zh": "SENIA Elite 系统启动", "en": "SENIA Elite System Starting"},
    "system.ready": {"zh": "系统就绪", "en": "System Ready"},
    "system.shutdown": {"zh": "系统关闭中", "en": "System Shutting Down"},
}


# ─── Public API ────────────────────────────────────────────

def set_locale(locale: str) -> None:
    """Set the current thread's locale (e.g. 'zh' or 'en')."""
    _thread_local.locale = locale


def get_locale() -> str:
    """Get the current thread's locale."""
    return getattr(_thread_local, "locale", _DEFAULT_LOCALE)


def t(key: str, locale: str | None = None, **kwargs: Any) -> str:
    """
    Translate a message key to the current (or specified) locale.

    Supports {placeholder} formatting via kwargs:
        t("report.lot_id")             -> "批次号"
        t("report.lot_id", locale="en") -> "Lot ID"
    """
    loc = locale or get_locale()
    entry = MESSAGES.get(key)
    if entry is None:
        return key
    text = entry.get(loc) or entry.get(_DEFAULT_LOCALE) or key
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError):
            pass
    return text


def available_locales() -> list[str]:
    """Return list of supported locale codes."""
    locales: set[str] = set()
    for entry in MESSAGES.values():
        locales.update(entry.keys())
    return sorted(locales)


def add_messages(messages: dict[str, dict[str, str]]) -> None:
    """Register additional messages (e.g., from plugins or custom configs)."""
    MESSAGES.update(messages)


def all_keys() -> list[str]:
    """Return all registered message keys."""
    return sorted(MESSAGES.keys())
