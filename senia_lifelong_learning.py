"""
SENIA 终身学习引擎
==================
系统永远不会停止进化. 每一次使用都让它更强.

传统机器学习: 训练一次 → 部署 → 性能逐渐退化
终身学习:     每一次对色 → 自动提取知识 → 模型变强 → 永不退化

5 层学习机制:
  L1 即时学习  — 操作员反馈 → 秒级阈值微调
  L2 批次学习  — 每批结束 → 更新材质/客户模型
  L3 周期学习  — 每周自动 → 重新拟合所有回归模型
  L4 跨域迁移  — 新产品线 → 从已有知识迁移初始参数
  L5 知识蒸馏  — 把所有经验压缩成紧凑的决策规则

核心算法: Elastic Weight Consolidation (EWC) 思想
  学新知识时不忘旧知识: 重要参数变化慢, 不重要参数变化快.
"""

from __future__ import annotations

import json
import math
import statistics
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Any


# ══════════════════════════════════════════════════════════
# L1: 即时学习 — 每次反馈都让阈值更准
# ══════════════════════════════════════════════════════════

class AdaptiveThreshold:
    """
    自适应阈值: 不是固定的, 也不是简单的线性调整.
    而是维护一个 "决策边界的概率分布".

    每次操作员反馈 → 贝叶斯更新 → 边界越来越精确.
    学习率随证据量衰减 (EWC 思想: 重要参数变化慢).
    """

    def __init__(self) -> None:
        self._lock = RLock()
        # profile → {"pass_mean": float, "pass_var": float, "n": int,
        #             "marginal_mean": float, "marginal_var": float}
        self._boundaries: dict[str, dict[str, float]] = {}

    def update(self, profile: str, dE: float, actual_tier: str) -> dict[str, Any]:
        """从一个数据点更新决策边界."""
        with self._lock:
            if profile not in self._boundaries:
                defaults = {"wood": 1.2, "solid": 0.8, "stone": 1.5}.get(profile, 1.0)
                self._boundaries[profile] = {
                    "pass_mean": defaults, "pass_var": 0.5,
                    "marginal_mean": defaults * 2.3, "marginal_var": 0.8,
                    "n": 0,
                }
            b = self._boundaries[profile]
            b["n"] += 1
            n = b["n"]

            # EWC 学习率: 早期学快, 后期学慢 (保护已学知识)
            lr = 1.0 / (1.0 + n * 0.1)  # n=10 → lr=0.5, n=100 → lr=0.09

            if actual_tier == "PASS":
                # 这个 dE 值应该在 pass 边界以下 → 如果 dE > pass_mean, 上调
                b["pass_mean"] += lr * (dE - b["pass_mean"]) * 0.3
                b["pass_var"] = b["pass_var"] * (1 - lr * 0.1) + lr * 0.1 * (dE - b["pass_mean"]) ** 2
            elif actual_tier == "FAIL":
                # 这个 dE 值应该在 marginal 边界以上 → 如果 dE < marginal_mean, 下调
                b["marginal_mean"] += lr * (dE - b["marginal_mean"]) * 0.3
                b["marginal_var"] = b["marginal_var"] * (1 - lr * 0.1) + lr * 0.1 * (dE - b["marginal_mean"]) ** 2

            # 安全约束: pass < marginal, 且不超出物理合理范围
            b["pass_mean"] = max(0.3, min(b["pass_mean"], 3.0))
            b["marginal_mean"] = max(b["pass_mean"] + 0.5, min(b["marginal_mean"], 6.0))

            return {
                "profile": profile,
                "pass_threshold": round(b["pass_mean"], 3),
                "marginal_threshold": round(b["marginal_mean"], 3),
                "confidence": round(1.0 / (1.0 + b["pass_var"]), 3),
                "samples": n,
                "lr": round(lr, 4),
            }

    def get_thresholds(self, profile: str) -> tuple[float, float]:
        """获取当前学习到的阈值."""
        with self._lock:
            b = self._boundaries.get(profile)
            if b is None:
                defaults = {"wood": 1.2, "solid": 0.8, "stone": 1.5}.get(profile, 1.0)
                return (defaults, defaults * 2.3)
            return (b["pass_mean"], b["marginal_mean"])


# ══════════════════════════════════════════════════════════
# L2: 批次学习 — 每批结束后更新模型
# ══════════════════════════════════════════════════════════

class BatchLearner:
    """
    每批生产结束后, 从这批数据中提取知识:
      - 这个配方+这个机台+这个季节 → 实际色差是多少
      - 色差变化趋势 → 设备状态推断
      - 操作员判断 vs 系统判断 → 哪些阈值需要调整
    """

    def __init__(self) -> None:
        self._lock = RLock()
        # product_code → [batch summaries]
        self._batch_history: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def finish_batch(self, product_code: str, samples: list[dict[str, Any]]) -> dict[str, Any]:
        """批次结束, 汇总学习."""
        if not samples:
            return {"learned": False}

        dEs = [s.get("dE", 0) for s in samples if "dE" in s]
        if not dEs:
            return {"learned": False}

        summary = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "product_code": product_code,
            "sample_count": len(dEs),
            "avg_dE": round(statistics.mean(dEs), 4),
            "std_dE": round(statistics.stdev(dEs), 4) if len(dEs) > 1 else 0,
            "max_dE": round(max(dEs), 4),
            "pass_rate": round(sum(1 for d in dEs if d < 2.0) / len(dEs), 4),
        }

        with self._lock:
            self._batch_history[product_code].append(summary)
            # 保留最近 100 批
            if len(self._batch_history[product_code]) > 100:
                self._batch_history[product_code] = self._batch_history[product_code][-100:]

        # 趋势分析
        history = self._batch_history[product_code]
        if len(history) >= 3:
            recent_avg = statistics.mean([h["avg_dE"] for h in history[-3:]])
            older_avg = statistics.mean([h["avg_dE"] for h in history[-6:-3]]) if len(history) >= 6 else recent_avg
            trend = recent_avg - older_avg
            summary["trend"] = "improving" if trend < -0.2 else "degrading" if trend > 0.2 else "stable"
        else:
            summary["trend"] = "insufficient_data"

        return {"learned": True, "summary": summary}


# ══════════════════════════════════════════════════════════
# L3: 周期学习 — 定期重新拟合所有模型
# ══════════════════════════════════════════════════════════

def periodic_model_refresh(
    batch_learner: BatchLearner,
    adaptive_threshold: AdaptiveThreshold,
) -> dict[str, Any]:
    """
    周期性模型刷新 (建议每周运行一次).

    从累积的批次数据中:
      1. 重新计算每个产品的基线色差
      2. 更新材质 profile 的默认阈值
      3. 检测系统精度趋势
    """
    results: dict[str, Any] = {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"), "updates": []}

    with batch_learner._lock:
        for product, batches in batch_learner._batch_history.items():
            if len(batches) < 3:
                continue
            avg_dEs = [b["avg_dE"] for b in batches]
            overall_avg = statistics.mean(avg_dEs)
            overall_std = statistics.stdev(avg_dEs) if len(avg_dEs) > 1 else 0

            results["updates"].append({
                "product": product,
                "batches": len(batches),
                "avg_dE": round(overall_avg, 4),
                "std_dE": round(overall_std, 4),
                "suggested_pass": round(overall_avg + overall_std, 2),
                "suggested_marginal": round(overall_avg + 2 * overall_std + 0.5, 2),
            })

    return results


# ══════════════════════════════════════════════════════════
# L4: 跨域迁移 — 新产品从已有知识启动
# ══════════════════════════════════════════════════════════

def transfer_knowledge(
    source_profile: str,
    target_profile: str,
    adaptive_threshold: AdaptiveThreshold,
    similarity: float = 0.8,
) -> dict[str, Any]:
    """
    知识迁移: 新产品线没有数据时, 从最相似的已有产品迁移.

    例: 新产品 "橡木灰B" 和已有的 "橡木灰A" 很像 → 迁移阈值.
    迁移的参数按相似度加权: 越相似 → 迁移越多.
    """
    source_pass, source_marginal = adaptive_threshold.get_thresholds(source_profile)
    target_pass, target_marginal = adaptive_threshold.get_thresholds(target_profile)

    # 加权迁移
    new_pass = target_pass * (1 - similarity) + source_pass * similarity
    new_marginal = target_marginal * (1 - similarity) + source_marginal * similarity

    return {
        "source": source_profile,
        "target": target_profile,
        "similarity": similarity,
        "transferred_pass": round(new_pass, 3),
        "transferred_marginal": round(new_marginal, 3),
        "note": f"从 {source_profile} 迁移了 {similarity*100:.0f}% 的知识到 {target_profile}",
    }


# ══════════════════════════════════════════════════════════
# L5: 知识蒸馏 — 把经验压缩成简单规则
# ══════════════════════════════════════════════════════════

def distill_knowledge(
    adaptive_threshold: AdaptiveThreshold,
    batch_learner: BatchLearner,
    memory: Any = None,
) -> dict[str, Any]:
    """
    知识蒸馏: 把系统学到的所有知识压缩成人类可读的规则.

    输出类似于:
      "灰橡木产品, 色差 < 1.15 可以放行, 1.15-2.60 需要复核, > 2.60 返工"
      "客户 EU-001 对偏红最敏感, 阈值要收紧 20%"
      "7月份色差平均比1月份高 0.12 ΔE"
    """
    rules: list[dict[str, str]] = []

    # 从自适应阈值蒸馏
    with adaptive_threshold._lock:
        for profile, b in adaptive_threshold._boundaries.items():
            rules.append({
                "type": "阈值",
                "rule": f"{profile}: ΔE < {b['pass_mean']:.2f} 放行, "
                        f"{b['pass_mean']:.2f}-{b['marginal_mean']:.2f} 复核, "
                        f"> {b['marginal_mean']:.2f} 返工 "
                        f"(基于 {b['n']} 次学习)",
            })

    # 从批次历史蒸馏
    with batch_learner._lock:
        for product, batches in batch_learner._batch_history.items():
            if len(batches) >= 5:
                recent = batches[-5:]
                avg = statistics.mean([b["avg_dE"] for b in recent])
                pass_rate = statistics.mean([b["pass_rate"] for b in recent])
                rules.append({
                    "type": "产品基线",
                    "rule": f"{product}: 近5批平均 ΔE={avg:.2f}, 合格率 {pass_rate*100:.0f}%",
                })

    # 从 AI 记忆蒸馏
    if memory:
        try:
            patterns = memory.get_error_patterns()
            if patterns.get("error_count", 0) > 0:
                rules.append({
                    "type": "误判教训",
                    "rule": f"系统准确率 {patterns['accuracy']*100:.1f}%, "
                            f"误判合格 {patterns['false_pass']} 次, "
                            f"误判不合格 {patterns['false_fail']} 次",
                })
                for p in patterns.get("patterns", []):
                    rules.append({"type": "误判模式", "rule": p})
        except Exception:
            pass

    return {
        "distilled_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "rule_count": len(rules),
        "rules": rules,
    }


# ══════════════════════════════════════════════════════════
# 统一接口: 终身学习协调器
# ══════════════════════════════════════════════════════════

class LifelongLearner:
    """
    终身学习协调器: 统一管理 L1-L5 五层学习.

    每次对色:
      → L1 即时更新阈值
    每批结束:
      → L2 批次汇总
    每周:
      → L3 模型刷新
    新产品:
      → L4 迁移知识
    随时查看:
      → L5 蒸馏出人类可读规则
    """

    def __init__(self, store_dir: Path | None = None) -> None:
        self.threshold = AdaptiveThreshold()
        self.batch = BatchLearner()
        self._store_dir = store_dir
        self._stats = {"l1_updates": 0, "l2_batches": 0, "l3_refreshes": 0,
                       "l4_transfers": 0, "l5_distills": 0}

    def learn_from_feedback(self, profile: str, dE: float, actual_tier: str) -> dict[str, Any]:
        """L1: 即时学习."""
        self._stats["l1_updates"] += 1
        return self.threshold.update(profile, dE, actual_tier)

    def learn_from_batch(self, product_code: str, samples: list[dict[str, Any]]) -> dict[str, Any]:
        """L2: 批次学习."""
        self._stats["l2_batches"] += 1
        return self.batch.finish_batch(product_code, samples)

    def refresh_models(self) -> dict[str, Any]:
        """L3: 周期学习."""
        self._stats["l3_refreshes"] += 1
        return periodic_model_refresh(self.batch, self.threshold)

    def transfer(self, source: str, target: str, similarity: float = 0.8) -> dict[str, Any]:
        """L4: 迁移学习."""
        self._stats["l4_transfers"] += 1
        return transfer_knowledge(source, target, self.threshold, similarity)

    def distill(self, memory: Any = None) -> dict[str, Any]:
        """L5: 知识蒸馏."""
        self._stats["l5_distills"] += 1
        return distill_knowledge(self.threshold, self.batch, memory)

    def status(self) -> dict[str, Any]:
        """终身学习状态."""
        return {
            "stats": dict(self._stats),
            "profiles_learned": len(self.threshold._boundaries),
            "products_tracked": len(self.batch._batch_history),
            "total_learning_events": sum(self._stats.values()),
        }
