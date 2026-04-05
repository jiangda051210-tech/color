"""
SENIA M5: 配方联动 — 偏差→原因→调色建议 规则引擎
================================================
V1: 规则映射 (老师傅经验结构化)
V2: 历史数据反演 (需积累数据后实现)

规则表输入: ΔL / Δa / Δb / ΔC 组合
规则表输出: 排序后的调整建议列表

关键区分:
  - 均匀偏色 → 配方问题 → 给调色建议
  - 不均匀偏色/缺陷 → 工艺问题 → 给工艺建议
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RecipeAdvice:
    """单条调色建议."""
    action: str                   # 调整动作描述
    priority: int = 0             # 优先级 (越小越高)
    confidence: float = 0.8       # 建议置信度
    category: str = "recipe"      # "recipe" / "process" / "capture"
    component: str = ""           # 涉及的配方组分 (如 "黄色色精", "白色基料")
    direction: str = ""           # "increase" / "decrease" / "check"


@dataclass
class RecipeAdviceResult:
    """M5 输出: 调色建议集合."""
    advices: list[RecipeAdvice] = field(default_factory=list)
    root_cause: str = ""          # "recipe" / "process" / "mixed" / "ok"
    summary: str = ""
    is_process_issue: bool = False


# ── 规则表: 偏差方向 → 可能原因 → 调整建议 ─────────────────

RECIPE_RULES: list[dict[str, Any]] = [
    # ── 明度偏差 ──
    {
        "condition": lambda dL, da, db, dC: dL > 1.0,
        "advices": [
            RecipeAdvice(action="减少白色基料用量", priority=1, component="白色基料", direction="decrease"),
            RecipeAdvice(action="检查钛白粉添加量是否偏高", priority=2, component="钛白粉", direction="check"),
        ],
        "meaning": "偏亮: 白色基料/钛白粉可能过量",
    },
    {
        "condition": lambda dL, da, db, dC: dL < -1.0,
        "advices": [
            RecipeAdvice(action="增加白色基料用量或减少黑色色精", priority=1, component="白色基料", direction="increase"),
            RecipeAdvice(action="检查黑色色精是否多加", priority=2, component="黑色色精", direction="check"),
        ],
        "meaning": "偏暗: 黑色组分过多或白色基料不足",
    },

    # ── 红绿轴偏差 (Δa) ──
    {
        "condition": lambda dL, da, db, dC: da > 0.8,
        "advices": [
            RecipeAdvice(action="减少红色色精用量", priority=1, component="红色色精", direction="decrease"),
            RecipeAdvice(action="适当增加绿色补色", priority=3, component="绿色色精", direction="increase"),
        ],
        "meaning": "偏红: 红色色精过多",
    },
    {
        "condition": lambda dL, da, db, dC: da < -0.8,
        "advices": [
            RecipeAdvice(action="减少绿色色精或增加红色色精", priority=1, component="绿色色精", direction="decrease"),
        ],
        "meaning": "偏绿: 绿色色精过多或红色不足",
    },

    # ── 黄蓝轴偏差 (Δb) ──
    {
        "condition": lambda dL, da, db, dC: db > 0.8,
        "advices": [
            RecipeAdvice(action="减少黄色色精用量", priority=1, component="黄色色精", direction="decrease"),
            RecipeAdvice(action="如同时偏亮, 优先减白再校黄", priority=2, component="白色基料/黄色色精", direction="check"),
        ],
        "meaning": "偏黄: 黄色色精过多",
    },
    {
        "condition": lambda dL, da, db, dC: db < -0.8,
        "advices": [
            RecipeAdvice(action="减少蓝色色精或增加黄色色精", priority=1, component="蓝色色精", direction="decrease"),
        ],
        "meaning": "偏蓝: 蓝色色精过多",
    },

    # ── 饱和度偏差 ──
    {
        "condition": lambda dL, da, db, dC: dC < -1.0,
        "advices": [
            RecipeAdvice(action="增加主色色精浓度 (整体色精偏少)", priority=1, component="主色色精", direction="increase"),
            RecipeAdvice(action="检查溶剂比例是否过高导致稀释", priority=2, component="溶剂", direction="check"),
        ],
        "meaning": "饱和度不足: 色精浓度可能偏低",
    },
    {
        "condition": lambda dL, da, db, dC: dC > 1.0,
        "advices": [
            RecipeAdvice(action="适当减少主色色精浓度", priority=1, component="主色色精", direction="decrease"),
        ],
        "meaning": "饱和度过高: 色精浓度偏高",
    },

    # ── 复合偏差 (特殊组合) ──
    {
        "condition": lambda dL, da, db, dC: dL > 0.8 and db > 0.8,
        "advices": [
            RecipeAdvice(action="优先减白色基料, 再微调黄色", priority=0, component="白色基料", direction="decrease"),
        ],
        "meaning": "偏亮+偏黄: 白色基料过量是主因, 减白后黄可能自然回正",
    },
    {
        "condition": lambda dL, da, db, dC: abs(dL) < 0.5 and abs(da) < 0.5 and abs(db) < 0.5,
        "advices": [
            RecipeAdvice(action="色差在正常范围, 无需调整配方", priority=10, category="ok", direction=""),
        ],
        "meaning": "偏差极小, 配方合格",
    },
]

# ── 工艺问题建议 ────────────────────────────────────────────

PROCESS_RULES: list[dict[str, Any]] = [
    {
        "defect": "mottling",
        "advices": [
            RecipeAdvice(action="检查涂布辊压力均匀性", priority=1, category="process", component="涂布辊"),
            RecipeAdvice(action="检查浆料粘度是否在标准范围", priority=2, category="process", component="浆料粘度"),
            RecipeAdvice(action="检查烘箱温度均匀性", priority=3, category="process", component="烘箱"),
        ],
    },
    {
        "defect": "streaks",
        "advices": [
            RecipeAdvice(action="检查刮刀是否有缺口或磨损", priority=1, category="process", component="刮刀"),
            RecipeAdvice(action="检查涂布速度是否偏快", priority=2, category="process", component="涂布速度"),
            RecipeAdvice(action="清洁涂布辊表面", priority=3, category="process", component="涂布辊"),
        ],
    },
    {
        "defect": "spots",
        "advices": [
            RecipeAdvice(action="检查浆料中是否有异物/气泡", priority=1, category="process", component="浆料"),
            RecipeAdvice(action="检查生产环境洁净度", priority=2, category="process", component="环境"),
        ],
    },
]


# ── 规则引擎主入口 ──────────────────────────────────────────

def generate_recipe_advice(
    dL: float,
    da: float,
    db: float,
    dC: float,
    root_cause: str = "recipe",
    defect_types: list[str] | None = None,
    material_type: str = "generic",
) -> RecipeAdviceResult:
    """
    根据偏差方向和根因分析, 生成调色/工艺建议.

    参数:
      dL, da, db, dC: 色差分量
      root_cause: "recipe" / "process" / "mixed" / "ok" (来自 M6 均匀性分析)
      defect_types: 检测到的缺陷类型列表 ["mottling", "streaks", "spots"]
      material_type: material category; textured materials ("wood", "stone")
                     get relaxed dL thresholds (+30%)
    """
    # For textured materials, relax the dL threshold by 30%
    dL_threshold = 1.0 * (1.3 if material_type in ("wood", "stone") else 1.0)

    result = RecipeAdviceResult(root_cause=root_cause)
    defects = defect_types or []

    if root_cause == "ok":
        result.summary = "色差在正常范围, 无需调整"
        return result

    # 工艺问题 → 优先给工艺建议
    if root_cause in ("process", "mixed"):
        result.is_process_issue = True
        for rule in PROCESS_RULES:
            if rule["defect"] in defects:
                result.advices.extend(rule["advices"])
        if root_cause == "process":
            result.summary = "检测到工艺问题, 建议优先排查工艺参数, 暂不调配方"
            if not result.advices:
                result.advices.append(
                    RecipeAdvice(
                        action="偏色不均匀, 建议检查涂布/烘干工艺参数",
                        priority=0, category="process",
                    )
                )
            return result

    # 配方问题 / 混合问题 → 匹配规则表
    # Apply material-aware dL threshold: use dL_threshold instead of
    # the hardcoded 1.0 in rule lambdas by scaling dL for evaluation.
    dL_for_rules = dL / dL_threshold * 1.0 if dL_threshold > 0 else dL
    matched_meanings: list[str] = []
    for rule in RECIPE_RULES:
        try:
            if rule["condition"](dL_for_rules, da, db, dC):
                result.advices.extend(rule["advices"])
                matched_meanings.append(rule["meaning"])
        except Exception:
            continue

    # 排序: priority 小的在前
    result.advices.sort(key=lambda a: a.priority)

    # 去重
    seen: set[str] = set()
    unique: list[RecipeAdvice] = []
    for a in result.advices:
        if a.action not in seen:
            seen.add(a.action)
            unique.append(a)
    result.advices = unique

    if matched_meanings:
        result.summary = "调色分析: " + "; ".join(matched_meanings)
    elif root_cause == "mixed":
        result.summary = "存在工艺+配方混合问题, 建议先解决工艺问题后再微调配方"
    else:
        result.summary = "未匹配到明确规则, 建议人工判断"

    return result
