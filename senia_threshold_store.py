"""
SENIA 可配置阈值存储
====================
支持按产品/客户/材质定制判定阈值, 持久化到 JSON 文件.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from threading import RLock
from typing import Any

from senia_analysis import ThresholdConfig


# 默认阈值 (按材质)
DEFAULT_THRESHOLDS: dict[str, dict[str, float]] = {
    "solid":      {"pass_dE": 0.8, "marginal_dE": 2.0, "defect_marginal": 0.4, "defect_fail": 0.7},
    "wood":       {"pass_dE": 1.2, "marginal_dE": 2.8, "defect_marginal": 0.5, "defect_fail": 0.8},
    "stone":      {"pass_dE": 1.5, "marginal_dE": 3.2, "defect_marginal": 0.5, "defect_fail": 0.8},
    "metallic":   {"pass_dE": 0.8, "marginal_dE": 2.2, "defect_marginal": 0.4, "defect_fail": 0.7},
    "high_gloss": {"pass_dE": 0.6, "marginal_dE": 1.8, "defect_marginal": 0.3, "defect_fail": 0.6},
}


class ThresholdStore:
    """
    线程安全的阈值存储, 支持:
      - 按材质默认阈值
      - 按产品覆盖
      - 按客户覆盖
      - 持久化到 JSON 文件
    """

    def __init__(self, config_path: Path | None = None) -> None:
        self._lock = RLock()
        self._config_path = config_path
        self._overrides: dict[str, dict[str, float]] = {}
        if config_path and config_path.exists():
            self._load()

    def get(
        self,
        profile: str = "solid",
        product_code: str = "",
        customer_id: str = "",
    ) -> ThresholdConfig:
        """
        获取阈值, 优先级: customer > product > profile > default.
        """
        with self._lock:
            base = DEFAULT_THRESHOLDS.get(profile, DEFAULT_THRESHOLDS["solid"]).copy()

            # 产品覆盖
            if product_code:
                product_key = f"product:{product_code}"
                if product_key in self._overrides:
                    base.update(self._overrides[product_key])

            # 客户覆盖
            if customer_id:
                customer_key = f"customer:{customer_id}"
                if customer_key in self._overrides:
                    base.update(self._overrides[customer_key])

            return ThresholdConfig(
                pass_dE=base.get("pass_dE", 1.0),
                marginal_dE=base.get("marginal_dE", 2.5),
                defect_marginal=base.get("defect_marginal", 0.4),
                defect_fail=base.get("defect_fail", 0.7),
            )

    def set_product_override(
        self,
        product_code: str,
        pass_dE: float | None = None,
        marginal_dE: float | None = None,
        defect_marginal: float | None = None,
        defect_fail: float | None = None,
    ) -> dict[str, float]:
        """设置产品级阈值覆盖."""
        key = f"product:{product_code}"
        return self._set_override(key, pass_dE, marginal_dE, defect_marginal, defect_fail)

    def set_customer_override(
        self,
        customer_id: str,
        pass_dE: float | None = None,
        marginal_dE: float | None = None,
        defect_marginal: float | None = None,
        defect_fail: float | None = None,
    ) -> dict[str, float]:
        """设置客户级阈值覆盖."""
        key = f"customer:{customer_id}"
        return self._set_override(key, pass_dE, marginal_dE, defect_marginal, defect_fail)

    def remove_override(self, key: str) -> bool:
        """删除一个覆盖."""
        with self._lock:
            if key in self._overrides:
                del self._overrides[key]
                self._save()
                return True
            return False

    def list_overrides(self) -> dict[str, dict[str, float]]:
        """列出所有覆盖."""
        with self._lock:
            return dict(self._overrides)

    def status(self) -> dict[str, Any]:
        """返回存储状态."""
        with self._lock:
            return {
                "config_path": str(self._config_path) if self._config_path else None,
                "override_count": len(self._overrides),
                "defaults": DEFAULT_THRESHOLDS,
                "overrides": dict(self._overrides),
            }

    # ── internal ──

    def _set_override(
        self, key: str,
        pass_dE: float | None, marginal_dE: float | None,
        defect_marginal: float | None, defect_fail: float | None,
    ) -> dict[str, float]:
        with self._lock:
            existing = self._overrides.get(key, {})
            if pass_dE is not None:
                existing["pass_dE"] = max(0.1, min(pass_dE, 5.0))
            if marginal_dE is not None:
                existing["marginal_dE"] = max(0.5, min(marginal_dE, 8.0))
            if defect_marginal is not None:
                existing["defect_marginal"] = max(0.1, min(defect_marginal, 1.0))
            if defect_fail is not None:
                existing["defect_fail"] = max(0.2, min(defect_fail, 1.0))
            self._overrides[key] = existing
            self._save()
            return existing

    def _load(self) -> None:
        if not self._config_path or not self._config_path.exists():
            return
        try:
            data = json.loads(self._config_path.read_text(encoding="utf-8"))
            self._overrides = data.get("overrides", {})
        except (json.JSONDecodeError, OSError):
            pass

    def _save(self) -> None:
        if not self._config_path:
            return
        try:
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "overrides": self._overrides,
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            self._config_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            pass
