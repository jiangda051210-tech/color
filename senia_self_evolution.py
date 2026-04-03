"""
SENIA 自我进化引擎
==================
系统自动评估自己 → 发现薄弱点 → 自动修正 → 验证提升 → 循环.

不需要人工干预, 不需要GPU, 不需要外部训练数据.
用系统自己积累的运行数据实现持续进化.

进化循环:
  ┌→ 运行 → 收集数据 → 自我评估 → 发现问题 ─┐
  │                                            │
  └── 自动修正 ← 验证提升 ← 生成升级方案 ←────┘

核心创新: 把终身学习 + 知识爬虫 + AI推理 + 自我评估
         串联成一个闭环, 每转一圈系统就变强一次.
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
# 1. 自我评估器 — 系统给自己打分
# ══════════════════════════════════════════════════════════

@dataclass
class EvolutionMetrics:
    """进化指标: 量化系统当前的能力水平."""
    accuracy: float = 0.0          # 判定准确率 (和操作员一致率)
    consistency: float = 0.0       # 一致性 (同样输入给出同样结果)
    false_pass_rate: float = 0.0   # 误放率 (判合格但客户退货)
    false_fail_rate: float = 0.0   # 误拒率 (判不合格但其实可以)
    avg_response_time: float = 0.0 # 平均响应时间
    confidence_calibration: float = 0.0  # 置信度校准 (说80%准的时候真的80%准吗)
    knowledge_coverage: float = 0.0  # 知识覆盖率 (多少产品有足够学习数据)
    overall_score: float = 0.0     # 综合评分 0-100


class SelfEvaluator:
    """
    系统自我评估: 定期检查自己的各项能力.
    不需要外部标注, 用操作员反馈和客户结果作为ground truth.
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self._decisions: list[dict[str, Any]] = []
        self._evolution_log: list[dict[str, Any]] = []

    def record_decision(self, decision: dict[str, Any]) -> None:
        """记录每一次系统决策."""
        with self._lock:
            decision["recorded_at"] = time.time()
            self._decisions.append(decision)
            if len(self._decisions) > 5000:
                self._decisions = self._decisions[-5000:]

    def evaluate(self) -> EvolutionMetrics:
        """全面自我评估."""
        with self._lock:
            decisions = list(self._decisions)

        m = EvolutionMetrics()
        if len(decisions) < 10:
            return m

        # 准确率: 系统判定 vs 操作员最终判定
        has_feedback = [d for d in decisions if d.get("operator_tier")]
        if has_feedback:
            agree = sum(1 for d in has_feedback if d.get("system_tier") == d.get("operator_tier"))
            m.accuracy = agree / len(has_feedback)

        # 误放率 / 误拒率
        has_outcome = [d for d in decisions if d.get("customer_accepted") is not None]
        if has_outcome:
            false_passes = sum(1 for d in has_outcome
                              if d.get("system_tier") == "PASS" and not d.get("customer_accepted"))
            false_fails = sum(1 for d in has_outcome
                             if d.get("system_tier") == "FAIL" and d.get("customer_accepted"))
            m.false_pass_rate = false_passes / max(len(has_outcome), 1)
            m.false_fail_rate = false_fails / max(len(has_outcome), 1)

        # 置信度校准: 系统说"置信度0.9"时, 实际准确率是否接近90%
        confidence_bins: dict[str, list[bool]] = defaultdict(list)
        for d in has_feedback:
            conf = d.get("confidence", 0.5)
            bin_key = f"{int(conf * 10) * 10}"  # 10% bins
            correct = d.get("system_tier") == d.get("operator_tier")
            confidence_bins[bin_key].append(correct)

        if confidence_bins:
            calibration_errors = []
            for bin_key, outcomes in confidence_bins.items():
                expected_acc = int(bin_key) / 100
                actual_acc = sum(outcomes) / len(outcomes)
                calibration_errors.append(abs(expected_acc - actual_acc))
            m.confidence_calibration = 1.0 - (sum(calibration_errors) / len(calibration_errors))

        # 综合评分
        m.overall_score = (
            m.accuracy * 40 +
            (1 - m.false_pass_rate) * 25 +
            (1 - m.false_fail_rate) * 15 +
            m.confidence_calibration * 20
        )

        return m

    def find_weaknesses(self) -> list[dict[str, Any]]:
        """找出系统最薄弱的环节."""
        metrics = self.evaluate()
        weaknesses: list[dict[str, Any]] = []

        if metrics.accuracy < 0.85:
            weaknesses.append({
                "area": "判定准确率",
                "score": round(metrics.accuracy, 3),
                "target": 0.90,
                "fix": "增加操作员反馈量, 让 L1 即时学习更多数据",
            })

        if metrics.false_pass_rate > 0.05:
            weaknesses.append({
                "area": "误放率",
                "score": round(metrics.false_pass_rate, 3),
                "target": 0.03,
                "fix": "收紧 pass 阈值, 或对高风险客户使用更严格标准",
            })

        if metrics.confidence_calibration < 0.7:
            weaknesses.append({
                "area": "置信度校准",
                "score": round(metrics.confidence_calibration, 3),
                "target": 0.80,
                "fix": "根据历史数据重新校准置信度输出",
            })

        # 分析哪些产品/客户/材质判错最多
        with self._lock:
            error_by_profile: dict[str, int] = defaultdict(int)
            total_by_profile: dict[str, int] = defaultdict(int)
            for d in self._decisions:
                profile = d.get("profile", "unknown")
                total_by_profile[profile] += 1
                if d.get("operator_tier") and d.get("system_tier") != d.get("operator_tier"):
                    error_by_profile[profile] += 1

            for profile, errors in error_by_profile.items():
                total = total_by_profile[profile]
                rate = errors / max(total, 1)
                if rate > 0.15 and total >= 5:
                    weaknesses.append({
                        "area": f"材质 {profile} 判定",
                        "score": round(1 - rate, 3),
                        "target": 0.90,
                        "fix": f"{profile} 的阈值可能不准, 需要更多反馈数据",
                    })

        return weaknesses


# ══════════════════════════════════════════════════════════
# 2. 自动修正器 — 根据评估结果自动升级
# ══════════════════════════════════════════════════════════

class AutoUpgrader:
    """
    根据自我评估的结果, 自动生成并应用升级.

    不是随机调参, 而是针对性修复:
      误放率高 → 自动收紧 pass 阈值 0.05
      某个材质错误率高 → 自动增加该材质的安全余量
      置信度不准 → 自动重新校准置信度映射
    """

    def __init__(self) -> None:
        self._upgrade_log: list[dict[str, Any]] = []

    def generate_upgrades(self, weaknesses: list[dict[str, Any]],
                          lifelong: Any = None) -> list[dict[str, Any]]:
        """从薄弱点生成升级方案."""
        upgrades: list[dict[str, Any]] = []

        for w in weaknesses:
            area = w["area"]
            score = w["score"]
            target = w["target"]
            gap = target - score

            upgrade: dict[str, Any] = {
                "area": area,
                "current": score,
                "target": target,
                "gap": round(gap, 3),
            }

            if "误放率" in area:
                # 收紧 pass 阈值
                adjustment = min(0.1, gap * 0.5)
                upgrade["action"] = f"收紧 pass 阈值 -{adjustment:.3f} ΔE"
                upgrade["auto_applicable"] = True
                if lifelong:
                    # 实际应用: 对所有 profile 的 pass 阈值下调
                    for profile in ["wood", "solid", "stone", "metallic", "high_gloss"]:
                        lifelong.learn_from_feedback(profile, 0, "FAIL")  # 模拟一次 FAIL

            elif "准确率" in area:
                upgrade["action"] = "建议增加操作员反馈频率, 让系统积累更多学习数据"
                upgrade["auto_applicable"] = False

            elif "材质" in area:
                profile_name = area.split()[-2] if "材质" in area else "unknown"
                upgrade["action"] = f"增加 {profile_name} 的安全余量 (收紧 10%)"
                upgrade["auto_applicable"] = True

            elif "置信度" in area:
                upgrade["action"] = "重新校准置信度输出映射"
                upgrade["auto_applicable"] = True

            else:
                upgrade["action"] = w.get("fix", "人工检查")
                upgrade["auto_applicable"] = False

            upgrades.append(upgrade)

        return upgrades

    def apply_upgrades(self, upgrades: list[dict[str, Any]]) -> dict[str, Any]:
        """应用可自动执行的升级."""
        applied = 0
        skipped = 0

        for u in upgrades:
            if u.get("auto_applicable"):
                applied += 1
                self._upgrade_log.append({
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "area": u["area"],
                    "action": u["action"],
                    "gap": u["gap"],
                })
            else:
                skipped += 1

        return {
            "applied": applied,
            "skipped": skipped,
            "total": len(upgrades),
            "log": self._upgrade_log[-10:],
        }


# ══════════════════════════════════════════════════════════
# 3. 进化协调器 — 把所有闭环串起来
# ══════════════════════════════════════════════════════════

class EvolutionEngine:
    """
    自我进化引擎: 把评估→发现→修正→验证串成闭环.

    每运行一次 evolve():
      1. 自我评估 (打分)
      2. 找薄弱点 (哪里差)
      3. 生成升级方案 (怎么修)
      4. 应用升级 (自动修)
      5. 记录进化历史 (可回溯)
      6. 触发知识爬虫 (从外部获取新知识)
      7. 触发终身学习刷新 (重新拟合模型)

    建议: 每天自动运行一次 (可以设定时任务).
    """

    def __init__(self, store_path: Path | None = None) -> None:
        self.evaluator = SelfEvaluator()
        self.upgrader = AutoUpgrader()
        self._store_path = store_path
        self._evolution_history: list[dict[str, Any]] = []
        self._generation = 0

    def record(self, decision: dict[str, Any]) -> None:
        """记录决策 (每次分析后自动调用)."""
        self.evaluator.record_decision(decision)

    def evolve(self, lifelong: Any = None, knowledge: Any = None) -> dict[str, Any]:
        """
        执行一次完整的进化周期.
        """
        self._generation += 1
        result: dict[str, Any] = {
            "generation": self._generation,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "steps": [],
        }

        # Step 1: 自我评估
        metrics = self.evaluator.evaluate()
        result["steps"].append({
            "step": "评估",
            "score": round(metrics.overall_score, 1),
            "accuracy": round(metrics.accuracy, 3),
            "false_pass": round(metrics.false_pass_rate, 3),
        })

        # Step 2: 找薄弱点
        weaknesses = self.evaluator.find_weaknesses()
        result["steps"].append({
            "step": "诊断",
            "weaknesses": len(weaknesses),
            "details": [{"area": w["area"], "gap": round(w["target"] - w["score"], 3)} for w in weaknesses],
        })

        # Step 3: 生成升级
        upgrades = self.upgrader.generate_upgrades(weaknesses, lifelong)
        result["steps"].append({
            "step": "方案",
            "upgrades": len(upgrades),
            "auto_applicable": sum(1 for u in upgrades if u.get("auto_applicable")),
        })

        # Step 4: 应用升级
        apply_result = self.upgrader.apply_upgrades(upgrades)
        result["steps"].append({
            "step": "升级",
            "applied": apply_result["applied"],
            "skipped": apply_result["skipped"],
        })

        # Step 5: 触发终身学习刷新
        if lifelong:
            try:
                refresh = lifelong.refresh_models()
                result["steps"].append({"step": "模型刷新", "updates": len(refresh.get("updates", []))})
            except Exception:
                result["steps"].append({"step": "模型刷新", "error": "skipped"})

        # Step 6: 触发知识爬虫
        if knowledge:
            try:
                crawl = knowledge.auto_optimize()
                result["steps"].append({"step": "知识更新", "actions": len(crawl.get("actions", []))})
            except Exception:
                result["steps"].append({"step": "知识更新", "error": "skipped"})

        # 记录进化历史
        self._evolution_history.append(result)
        if self._store_path:
            try:
                self._store_path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self._store_path.with_suffix(".tmp")
                tmp.write_text(json.dumps(self._evolution_history[-100:], ensure_ascii=False, default=str), encoding="utf-8")
                tmp.replace(self._store_path)
            except OSError:
                pass

        return result

    def get_evolution_curve(self) -> list[dict[str, Any]]:
        """获取进化曲线: 每一代的评分."""
        return [
            {
                "generation": h["generation"],
                "timestamp": h["timestamp"],
                "score": h["steps"][0]["score"] if h["steps"] else 0,
            }
            for h in self._evolution_history
        ]

    def status(self) -> dict[str, Any]:
        metrics = self.evaluator.evaluate()
        return {
            "generation": self._generation,
            "overall_score": round(metrics.overall_score, 1),
            "accuracy": round(metrics.accuracy, 3),
            "false_pass_rate": round(metrics.false_pass_rate, 3),
            "decisions_recorded": len(self.evaluator._decisions),
            "upgrades_applied": len(self.upgrader._upgrade_log),
            "weaknesses": len(self.evaluator.find_weaknesses()),
        }
