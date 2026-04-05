"""
SENIA AI 推理引擎 — 像经验丰富的调色师傅一样思考
================================================

规则系统 vs 推理引擎:
  规则: if dE > 2.5: return "FAIL"
  推理: "这批货色差2.3, 正常应该判临界, 但考虑到:
         1) 这是VIP客户的急单
         2) 客户上次因为偏红退过货, 这次又偏红0.6
         3) 这批货要出口到欧洲, 客户用暖灯看会更红
         所以建议判不合格, 返工后再出"

核心: 不是更复杂的规则, 而是模拟人类专家的推理链路.
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
# 1. 经验记忆系统 — 记住每一次决策和结果
# ══════════════════════════════════════════════════════════

@dataclass
class CaseMemory:
    """一个决策案例的完整记忆."""
    case_id: str = ""
    timestamp: str = ""
    # 输入
    dE: float = 0
    dL: float = 0
    da: float = 0
    db: float = 0
    profile: str = ""
    product_code: str = ""
    lot_id: str = ""
    customer_id: str = ""
    # 系统判断
    system_tier: str = ""
    # 实际结果
    operator_override: str = ""   # 操作员覆盖了什么
    customer_accepted: bool | None = None  # 客户最终接受了吗
    # 上下文
    context_tags: list[str] = field(default_factory=list)  # ["VIP","急单","出口欧洲"]
    notes: str = ""


class ExperienceMemory:
    """
    经验记忆库: 记住每一个案例, 从中学习.

    像老师傅一样: "上次这个颜色的产品, 给这个客户,
    我们判了合格但客户退货了, 因为他对偏红特别敏感."
    """

    def __init__(self, store_path: Path | None = None) -> None:
        self._lock = RLock()
        self._cases: list[CaseMemory] = []
        self._store_path = store_path
        if store_path and store_path.exists():
            self._load()

    def remember(self, case: CaseMemory) -> None:
        with self._lock:
            case.case_id = f"C{len(self._cases):05d}"
            case.timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")
            self._cases.append(case)
            self._save()

    def recall_similar(self, dE: float, profile: str, customer_id: str = "",
                       product_code: str = "", top_k: int = 5) -> list[dict[str, Any]]:
        """回忆类似的历史案例."""
        # Weights for each distance component
        W_DE = 1.0
        W_CUSTOMER = 2.0
        W_PRODUCT = 1.5
        W_PROFILE = 0.8

        with self._lock:
            scored = []
            for c in self._cases:
                # Weighted distance: continuous dE distance + binary match penalties
                dE_dist = abs(c.dE - dE)
                customer_dist = 0.0 if (c.customer_id == customer_id and customer_id) else 1.0
                product_dist = 0.0 if (c.product_code == product_code and product_code) else 1.0
                profile_dist = 0.0 if c.profile == profile else 1.0

                weighted_distance = (
                    W_DE * dE_dist
                    + W_CUSTOMER * customer_dist
                    + W_PRODUCT * product_dist
                    + W_PROFILE * profile_dist
                )
                # Normalized similarity in [0, 1] via inverse distance
                similarity = 1.0 / (1.0 + weighted_distance)
                scored.append((similarity, c))
            scored.sort(key=lambda x: x[0], reverse=True)
            return [
                {
                    "case_id": c.case_id,
                    "similarity": round(s, 4),
                    "dE": c.dE,
                    "system_said": c.system_tier,
                    "operator_said": c.operator_override or c.system_tier,
                    "customer_accepted": c.customer_accepted,
                    "notes": c.notes,
                    "context": c.context_tags,
                }
                for s, c in scored[:top_k]
            ]

    def learn_from_outcome(self, case_id: str, customer_accepted: bool, notes: str = "") -> None:
        """案例闭环: 记录客户最终是否接受."""
        with self._lock:
            for c in self._cases:
                if c.case_id == case_id:
                    c.customer_accepted = customer_accepted
                    if notes:
                        c.notes = notes
                    break
            self._save()

    def get_error_patterns(self) -> dict[str, Any]:
        """分析系统判错的模式: 什么情况下判错最多?"""
        with self._lock:
            errors = [c for c in self._cases if c.customer_accepted is not None
                      and ((c.system_tier == "PASS" and not c.customer_accepted)
                           or (c.system_tier == "FAIL" and c.customer_accepted))]
            total_closed = sum(1 for c in self._cases if c.customer_accepted is not None)

        if not errors:
            return {"error_count": 0, "accuracy": 1.0 if total_closed > 0 else None}

        # 分析错误模式
        false_pass = [e for e in errors if e.system_tier == "PASS"]
        false_fail = [e for e in errors if e.system_tier == "FAIL"]

        patterns: list[str] = []
        if false_pass:
            avg_dE = statistics.mean([e.dE for e in false_pass])
            patterns.append(f"误判合格 {len(false_pass)} 次, 平均 ΔE={avg_dE:.2f}")
            # 找出哪个维度是主要原因
            avg_dL = statistics.mean([abs(e.dL) for e in false_pass])
            avg_da = statistics.mean([abs(e.da) for e in false_pass])
            avg_db = statistics.mean([abs(e.db) for e in false_pass])
            worst = max(("dL", avg_dL), ("da", avg_da), ("db", avg_db), key=lambda x: x[1])
            patterns.append(f"误判合格时 {worst[0]} 偏差最大 (avg={worst[1]:.2f})")

        return {
            "total_closed_cases": total_closed,
            "error_count": len(errors),
            "accuracy": round(1 - len(errors) / max(total_closed, 1), 4),
            "false_pass": len(false_pass),
            "false_fail": len(false_fail),
            "patterns": patterns,
        }

    def _save(self) -> None:
        if not self._store_path:
            return
        try:
            self._store_path.parent.mkdir(parents=True, exist_ok=True)
            data = [
                {"id": c.case_id, "ts": c.timestamp, "dE": c.dE, "dL": c.dL,
                 "da": c.da, "db": c.db, "profile": c.profile,
                 "product": c.product_code, "lot": c.lot_id, "customer": c.customer_id,
                 "system": c.system_tier, "override": c.operator_override,
                 "accepted": c.customer_accepted, "tags": c.context_tags, "notes": c.notes}
                for c in self._cases[-1000:]
            ]
            tmp = self._store_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self._store_path)
        except OSError:
            pass

    def _load(self) -> None:
        try:
            data = json.loads(self._store_path.read_text(encoding="utf-8"))
            for d in data:
                self._cases.append(CaseMemory(
                    case_id=d.get("id", ""), timestamp=d.get("ts", ""),
                    dE=d.get("dE", 0), dL=d.get("dL", 0), da=d.get("da", 0), db=d.get("db", 0),
                    profile=d.get("profile", ""), product_code=d.get("product", ""),
                    lot_id=d.get("lot", ""), customer_id=d.get("customer", ""),
                    system_tier=d.get("system", ""), operator_override=d.get("override", ""),
                    customer_accepted=d.get("accepted"), context_tags=d.get("tags", []),
                    notes=d.get("notes", ""),
                ))
        except (json.JSONDecodeError, OSError):
            pass


# ══════════════════════════════════════════════════════════
# 2. 推理链 — 像专家一样一步步思考
# ══════════════════════════════════════════════════════════

def expert_reasoning_chain(
    dE: float,
    dL: float,
    da: float,
    db: float,
    profile: str = "wood",
    customer_id: str = "",
    lot_id: str = "",
    product_code: str = "",
    context_tags: list[str] | None = None,
    memory: ExperienceMemory | None = None,
    batch_history: list[float] | None = None,
) -> dict[str, Any]:
    """
    专家推理链: 模拟老师傅的思考过程.

    不是简单的 if-else, 而是:
      Step 1: 观察 — 色差多少? 偏什么方向?
      Step 2: 回忆 — 以前类似的情况怎么处理的?
      Step 3: 分析 — 为什么会偏? 配方还是工艺?
      Step 4: 考虑上下文 — 客户是谁? 急不急? 出口还是内销?
      Step 5: 权衡 — 放行的风险 vs 返工的成本
      Step 6: 决策 — 最终建议
    """
    tags = context_tags or []
    chain: list[dict[str, Any]] = []

    # Material profile configuration for dynamic thresholds
    profile_config: dict[str, dict[str, Any]] = {
        "wood":  {"pass": 1.2, "marginal": 2.8, "direction_threshold": 0.5, "sensitivity": {"dL": 1.0, "da": 1.0, "db": 1.0}},
        "solid": {"pass": 0.8, "marginal": 2.0, "direction_threshold": 0.3, "sensitivity": {"dL": 1.2, "da": 1.3, "db": 1.1}},
        "stone": {"pass": 1.5, "marginal": 3.2, "direction_threshold": 0.6, "sensitivity": {"dL": 0.9, "da": 1.0, "db": 0.9}},
    }
    pconf = profile_config.get(profile, {"pass": 1.0, "marginal": 2.5, "direction_threshold": 0.5, "sensitivity": {"dL": 1.0, "da": 1.0, "db": 1.0}})
    dir_threshold = pconf["direction_threshold"]
    sensitivity = pconf["sensitivity"]

    # ── Step 1: 观察 ──
    step1_confidence = min(1.0, 1.0 / (1.0 + 0.1 * abs(dE - (pconf["pass"] + pconf["marginal"]) / 2)))
    chain.append({
        "step": "观察",
        "thinking": f"色差 ΔE={dE:.2f}, 偏差: dL={dL:+.2f} da={da:+.2f} db={db:+.2f}",
        "confidence": round(step1_confidence, 3),
    })

    dirs = []
    if abs(dL) > dir_threshold: dirs.append("偏亮" if dL > 0 else "偏暗")
    if abs(da) > dir_threshold: dirs.append("偏红" if da > 0 else "偏绿")
    if abs(db) > dir_threshold: dirs.append("偏黄" if db > 0 else "偏蓝")

    if dirs:
        chain.append({"step": "观察", "thinking": f"主要偏差方向: {'、'.join(dirs)}", "confidence": round(step1_confidence, 3)})

    # ── Step 2: 回忆类似案例 ──
    similar_cases = []
    recall_confidence = 0.5  # default when no memory
    if memory:
        similar_cases = memory.recall_similar(dE, profile, customer_id, product_code)
        if similar_cases:
            best = similar_cases[0]
            recall_confidence = min(1.0, best["similarity"] * (1.0 + 0.1 * len(similar_cases)))
            chain.append({
                "step": "回忆",
                "thinking": f"找到 {len(similar_cases)} 个类似案例. 最相似的: "
                            f"ΔE={best['dE']:.2f}, 系统判{best['system_said']}, "
                            f"{'客户接受' if best.get('customer_accepted') else '客户退货' if best.get('customer_accepted') is False else '结果未知'}",
                "confidence": round(recall_confidence, 3),
            })
            # 从历史案例中学习
            rejected_similar = [c for c in similar_cases if c.get("customer_accepted") is False]
            if rejected_similar:
                chain.append({
                    "step": "回忆",
                    "thinking": f"⚠️ 类似情况 {len(rejected_similar)} 次被客户退货, 需要更谨慎",
                    "confidence": round(recall_confidence, 3),
                })

    # ── Step 3: 分析原因 ──
    # Apply sensitivity weights for analysis
    weighted_dL = abs(dL) * sensitivity["dL"]
    weighted_da = abs(da) * sensitivity["da"]
    weighted_db = abs(db) * sensitivity["db"]
    analysis_confidence = min(1.0, max(weighted_dL, weighted_da, weighted_db) / 2.0)

    if weighted_dL > weighted_da and weighted_dL > weighted_db:
        main_issue = "明度" + ("偏亮" if dL > 0 else "偏暗")
        chain.append({"step": "分析", "thinking": f"主要问题是{main_issue}, 可能原因: 墨量{'不足' if dL > 0 else '过多'}或涂布厚度变化", "confidence": round(analysis_confidence, 3)})
    elif weighted_da > weighted_db:
        chain.append({"step": "分析", "thinking": f"红绿轴偏差最大 (da={da:+.2f}), 可能原因: 红色色精{'过量' if da > 0 else '不足'}", "confidence": round(analysis_confidence, 3)})
    elif abs(db) > dir_threshold:
        chain.append({"step": "分析", "thinking": f"黄蓝轴偏差最大 (db={db:+.2f}), 可能原因: 黄色色精{'过量' if db > 0 else '不足'}", "confidence": round(analysis_confidence, 3)})

    # 批次趋势
    if batch_history and len(batch_history) >= 5:
        recent = batch_history[-5:]
        trend = recent[-1] - recent[0]
        if trend > 0.3:
            chain.append({"step": "分析", "thinking": f"⚠️ 色差在最近 5 次中上升了 {trend:.2f}, 趋势不好", "confidence": round(analysis_confidence, 3)})
        elif trend < -0.3:
            chain.append({"step": "分析", "thinking": f"✓ 色差在最近 5 次中下降了 {abs(trend):.2f}, 趋势在改善", "confidence": round(analysis_confidence, 3)})

    # ── Step 4: 考虑上下文 ──
    risk_multiplier = 1.0
    context_confidence = 0.9  # context is generally reliable when present
    if "VIP" in tags or "vip" in tags:
        risk_multiplier *= 1.5
        chain.append({"step": "上下文", "thinking": "VIP客户, 需要更严格的标准", "confidence": round(context_confidence, 3)})
    if "急单" in tags:
        chain.append({"step": "上下文", "thinking": "急单, 返工时间成本高", "confidence": round(context_confidence, 3)})
    if "出口" in tags or "export" in tags:
        chain.append({"step": "上下文", "thinking": "出口订单, 运输+退货成本高, 需要更谨慎", "confidence": round(context_confidence, 3)})
    if "内销" in tags:
        chain.append({"step": "上下文", "thinking": "内销订单, 沟通成本低, 可以适当放宽", "confidence": round(context_confidence, 3)})

    # ── Step 5: 权衡 ──
    # Use dynamic thresholds from material profile config
    pass_th = pconf["pass"] / risk_multiplier  # VIP 客户阈值更严
    marginal_th = pconf["marginal"] / risk_multiplier

    if dE <= pass_th:
        base_tier = "PASS"
    elif dE < marginal_th:
        base_tier = "MARGINAL"
    else:
        base_tier = "FAIL"

    # Confidence for the weighing step: higher when dE is far from thresholds
    dist_to_boundary = min(abs(dE - pass_th), abs(dE - marginal_th))
    weigh_confidence = min(1.0, 0.5 + dist_to_boundary / 2.0)
    chain.append({"step": "权衡", "thinking": f"基础判定: {base_tier} (阈值: pass<{pass_th:.1f}, fail≥{marginal_th:.1f})", "confidence": round(weigh_confidence, 3)})

    # 历史退货经验调整
    if similar_cases:
        reject_count = sum(1 for c in similar_cases[:3] if c.get("customer_accepted") is False)
        if reject_count >= 2 and base_tier == "PASS":
            base_tier = "MARGINAL"
            chain.append({"step": "权衡", "thinking": "类似案例多次退货, 从合格提升为临界", "confidence": round(recall_confidence, 3)})
        elif reject_count >= 2 and base_tier == "MARGINAL":
            base_tier = "FAIL"
            chain.append({"step": "权衡", "thinking": "类似案例多次退货, 从临界提升为不合格", "confidence": round(recall_confidence, 3)})

    # ── Step 6: 最终决策 ──
    tier_cn = {"PASS": "合格", "MARGINAL": "临界", "FAIL": "不合格"}[base_tier]
    # Overall decision confidence: weighted combination of step confidences
    step_confidences = [s.get("confidence", 0.5) for s in chain if "confidence" in s]
    overall_confidence = round(statistics.mean(step_confidences), 3) if step_confidences else 0.5
    chain.append({"step": "决策", "thinking": f"最终判定: {tier_cn}", "confidence": round(overall_confidence, 3)})

    # 生成行动建议
    actions: list[str] = []
    if base_tier == "PASS":
        actions.append("放行")
    elif base_tier == "MARGINAL":
        actions.append("人工复核")
        if "急单" in tags:
            actions.append("如果复核通过可以先发货, 但记录在案")
    else:
        if "急单" in tags:
            actions.append("尝试和客户沟通是否可接受, 如不可接受则返工")
        else:
            actions.append("返工调色")
        if dirs:
            from senia_recipe import generate_recipe_advice
            recipe = generate_recipe_advice(dL, da, db, 0, "recipe")
            if recipe.advices:
                actions.append(f"调色方向: {recipe.advices[0].action}")

    chain.append({"step": "决策", "thinking": "行动: " + "; ".join(actions), "confidence": round(overall_confidence, 3)})

    return {
        "tier": base_tier,
        "reasoning_chain": chain,
        "actions": actions,
        "similar_cases": similar_cases[:3],
        "risk_multiplier": round(risk_multiplier, 2),
        "context_tags": tags,
        "overall_confidence": overall_confidence,
        "profile_config": pconf,
    }


# ══════════════════════════════════════════════════════════
# 3. 自然语言理解 — 理解操作员的话
# ══════════════════════════════════════════════════════════

def parse_operator_input(text: str) -> dict[str, Any]:
    """
    理解操作员的自然语言输入.

    "这个偏了一点红" → {"direction": "da", "magnitude": "slight", "da": 0.5}
    "颜色太暗了" → {"direction": "dL", "magnitude": "significant", "dL": -1.5}
    "和标样差不多" → {"assessment": "pass", "confidence": "medium"}
    "客户会退货的" → {"assessment": "fail", "confidence": "high"}
    """
    text = text.strip().lower()
    result: dict[str, Any] = {"raw": text, "understood": False}

    # Negation prefixes: "不偏红" → NOT red
    negation_prefixes = ["不", "没有", "没", "非", "无"]

    # 颜色方向关键词
    direction_map = {
        "红": ("da", 1), "偏红": ("da", 1), "发红": ("da", 1),
        "绿": ("da", -1), "偏绿": ("da", -1),
        "黄": ("db", 1), "偏黄": ("db", 1), "发黄": ("db", 1),
        "蓝": ("db", -1), "偏蓝": ("db", -1),
        "亮": ("dL", 1), "偏亮": ("dL", 1), "浅": ("dL", 1),
        "暗": ("dL", -1), "偏暗": ("dL", -1), "深": ("dL", -1), "黑": ("dL", -1),
        "灰": ("dC", -1), "偏灰": ("dC", -1), "不鲜艳": ("dC", -1),
        "艳": ("dC", 1), "鲜艳": ("dC", 1),
    }

    # Intensity parsing: per-keyword intensity detection
    # "很偏红" → significant, "略偏红" → slight, "偏红" → medium
    intensity_prefixes_significant = ["太", "很", "非常", "严重", "明显", "特别"]
    intensity_prefixes_slight = ["一点", "稍微", "略", "轻微", "有点", "微"]

    # Global magnitude (fallback)
    magnitude = "medium"
    if any(w in text for w in intensity_prefixes_significant):
        magnitude = "significant"
    elif any(w in text for w in intensity_prefixes_slight):
        magnitude = "slight"

    magnitude_values = {"slight": 0.5, "medium": 1.0, "significant": 2.0}

    detected_directions: list[dict[str, Any]] = []
    for keyword, (axis, sign) in direction_map.items():
        if keyword in text:
            # Check for negation: look for negation prefix right before the keyword
            keyword_idx = text.index(keyword)
            negated = False
            for neg in negation_prefixes:
                neg_start = keyword_idx - len(neg)
                if neg_start >= 0 and text[neg_start:keyword_idx] == neg:
                    negated = True
                    break

            # Check for per-keyword intensity prefix
            local_magnitude = magnitude  # default to global
            for prefix in intensity_prefixes_significant:
                pstart = keyword_idx - len(prefix)
                if pstart >= 0 and text[pstart:keyword_idx] == prefix:
                    local_magnitude = "significant"
                    break
            for prefix in intensity_prefixes_slight:
                pstart = keyword_idx - len(prefix)
                if pstart >= 0 and text[pstart:keyword_idx] == prefix:
                    local_magnitude = "slight"
                    break

            if negated:
                detected_directions.append({
                    "keyword": keyword, "axis": axis, "value": 0.0,
                    "negated": True, "intensity": local_magnitude,
                })
            else:
                value = sign * magnitude_values[local_magnitude]
                detected_directions.append({
                    "keyword": keyword, "axis": axis, "value": value,
                    "negated": False, "intensity": local_magnitude,
                })

    if detected_directions:
        result["understood"] = True
        result["directions"] = detected_directions
        result["magnitude"] = magnitude

    # 判断关键词
    if any(w in text for w in ["合格", "可以", "没问题", "差不多", "ok", "行"]):
        result["assessment"] = "pass"
        result["understood"] = True
    elif any(w in text for w in ["不合格", "退货", "不行", "差太多", "重做"]):
        result["assessment"] = "fail"
        result["understood"] = True
    elif any(w in text for w in ["临界", "勉强", "凑合", "马马虎虎"]):
        result["assessment"] = "marginal"
        result["understood"] = True

    # 上下文关键词
    context: list[str] = []
    if any(w in text for w in ["急", "赶", "催"]): context.append("急单")
    if any(w in text for w in ["vip", "大客户", "重要"]): context.append("VIP")
    if any(w in text for w in ["出口", "国外", "欧洲", "美国"]): context.append("出口")
    if context:
        result["context_tags"] = context
        result["understood"] = True

    return result


# ══════════════════════════════════════════════════════════
# 4. 主动建议引擎 — 不等人问, 主动提醒
# ══════════════════════════════════════════════════════════

def proactive_suggestions(
    dE: float,
    dL: float,
    da: float,
    db: float,
    profile: str = "wood",
    batch_history: list[float] | None = None,
    memory: ExperienceMemory | None = None,
    hour_of_day: int | None = None,
) -> list[dict[str, str]]:
    """
    主动建议: 不等操作员问, 系统主动提醒.

    基于: 当前数据 + 历史经验 + 时间规律.
    """
    import time as _time
    suggestions: list[dict[str, str]] = []
    hour = hour_of_day if hour_of_day is not None else int(_time.strftime("%H"))

    # Configurable shift schedule: read from config or use default
    # Default: 3 shifts with transition windows
    _default_shift_hours = {7, 8, 15, 16, 23, 0}
    shift_change_hours = _default_shift_hours
    try:
        config_path = Path(__file__).parent / "config" / "shift_schedule.json"
        if config_path.exists():
            import json as _json
            _cfg = _json.loads(config_path.read_text(encoding="utf-8"))
            shift_change_hours = set(_cfg.get("shift_change_hours", _default_shift_hours))
    except (OSError, json.JSONDecodeError, ValueError):
        pass

    # 换班时间提醒
    if hour in shift_change_hours:
        suggestions.append({
            "type": "换班提醒",
            "message": "换班后第一批建议多测几块, 确认新班次的设备状态",
            "priority": "medium",
        })

    # 色差趋势提醒 — Mann-Kendall style trend test
    if batch_history and len(batch_history) >= 5:
        recent = batch_history[-5:]
        # Mann-Kendall sign test: count concordant vs discordant pairs
        n = len(recent)
        s_stat = 0
        for i in range(n - 1):
            for j in range(i + 1, n):
                diff = recent[j] - recent[i]
                if diff > 0:
                    s_stat += 1
                elif diff < 0:
                    s_stat -= 1
        # Maximum possible S for n items
        max_s = n * (n - 1) // 2
        # Normalized trend score in [-1, 1] (Kendall's tau)
        tau = s_stat / max_s if max_s > 0 else 0.0
        if tau > 0.6:
            suggestions.append({
                "type": "趋势警告",
                "message": f"色差呈显著上升趋势 (tau={tau:.2f}, {recent[0]:.2f}→{recent[-1]:.2f}), 建议检查设备",
                "priority": "high",
            })
        elif tau > 0.3:
            suggestions.append({
                "type": "趋势提醒",
                "message": f"色差有上升趋势 (tau={tau:.2f}), 建议关注",
                "priority": "medium",
            })

    # 基于历史错误的提醒
    if memory:
        patterns = memory.get_error_patterns()
        if patterns.get("false_pass", 0) >= 2:
            suggestions.append({
                "type": "历史教训",
                "message": f"系统曾 {patterns['false_pass']} 次误判合格, 建议当前结果偏保守",
                "priority": "medium",
            })

    # 环境提醒
    if hour >= 12 and hour <= 15:
        suggestions.append({
            "type": "环境提醒",
            "message": "午后温度最高, 注意墨水粘度变化对颜色的影响",
            "priority": "low",
        })

    return suggestions
