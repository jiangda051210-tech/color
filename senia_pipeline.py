"""
SENIA 彩膜视觉一致性与调色辅助系统 — 主编排器
=============================================
串联 M1~M7 完整流程:

  M1 校准 → M2 配准 → M3 双管线分析 → M4 三级判定
                                    → M5 调色建议
                                    → M6 根因分析
                                    → M7 会话记录

核心原则:
  - 规则系统 + 可解释分析 (非端到端黑盒)
  - 固定标准光源为主流程, 自然光为辅助复核
  - 所有比对在 CIELAB 空间完成
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from senia_calibration import (
    CalibrationResult,
    ciede2000,
    fit_ccm_least_squares,
    srgb_to_lab_d50,
)
from senia_analysis import (
    FullAnalysisResult,
    ThresholdConfig,
    run_full_analysis,
)
from senia_recipe import (
    RecipeAdviceResult,
    generate_recipe_advice,
)


# ══════════════════════════════════════════════════════════
# M7: 会话记录 + 防篡改签名
# ══════════════════════════════════════════════════════════

@dataclass
class SessionRecord:
    """一次完整检测会话."""
    session_id: str = ""
    lot_id: str = ""
    product_code: str = ""
    line_id: str = ""
    operator_id: str = ""
    profile: str = "auto"
    customer_id: str = ""

    # 校准信息
    calibration: dict[str, Any] = field(default_factory=dict)

    # 分析结果
    analysis: dict[str, Any] = field(default_factory=dict)

    # 调色建议
    recipe_advice: dict[str, Any] = field(default_factory=dict)

    # 元信息
    timestamp: str = ""
    elapsed_sec: float = 0.0
    sha256: str = ""


def _compute_signature(data: dict[str, Any]) -> str:
    """防篡改 SHA256 签名."""
    raw = json.dumps(data, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ══════════════════════════════════════════════════════════
# 主编排器
# ══════════════════════════════════════════════════════════

# 材质 profile → 判定阈值
PROFILE_THRESHOLDS: dict[str, ThresholdConfig] = {
    "solid": ThresholdConfig(pass_dE=0.8, marginal_dE=2.0),
    "wood": ThresholdConfig(pass_dE=1.2, marginal_dE=2.8),
    "stone": ThresholdConfig(pass_dE=1.5, marginal_dE=3.2),
    "metallic": ThresholdConfig(pass_dE=0.8, marginal_dE=2.2),
    "high_gloss": ThresholdConfig(pass_dE=0.6, marginal_dE=1.8),
    "default": ThresholdConfig(pass_dE=1.0, marginal_dE=2.5),
}


def run_pipeline(
    ref_rgb_cells: list[tuple[int, int, int]],
    sample_rgb_cells: list[tuple[int, int, int]],
    grid_rows: int = 6,
    grid_cols: int = 8,
    profile: str = "auto",
    lot_id: str = "",
    product_code: str = "",
    line_id: str = "",
    operator_id: str = "",
    customer_id: str = "",
    ccm: list[list[float]] | None = None,
    capture_confidence: float = 1.0,
) -> SessionRecord:
    """
    运行完整 SENIA 管线.

    参数:
      ref_rgb_cells: 标样 N 个色块的 sRGB 值 (校正前)
      sample_rgb_cells: 打样 N 个色块的 sRGB 值 (校正前)
      grid_rows, grid_cols: 网格尺寸 (ref/sample 各 rows×cols 个色块)
      profile: 材质类型 (solid/wood/stone/metallic/high_gloss/auto)
      ccm: 预标定的 3×3 CCM (如果已校准, 传入)
      capture_confidence: 拍摄质量置信度 (0~1)

    返回 SessionRecord 含完整结果.
    """
    # 输入验证
    if not ref_rgb_cells:
        raise ValueError("ref_rgb_cells is empty — need at least 1 reference color sample")
    if not sample_rgb_cells:
        raise ValueError("sample_rgb_cells is empty — need at least 1 sample color sample")

    start = time.perf_counter()
    session_id = f"{time.strftime('%Y%m%d%H%M%S')}_{hashlib.md5(f'{lot_id}{time.time()}'.encode()).hexdigest()[:8]}"

    # ── Step 1: 色彩校正 (M1) ──
    # 如果有 CCM, 应用; 否则直接用原始值 (假设已校准或无色卡)
    # 注意: CCM 只在此处应用一次, 不要在下游再次应用
    ccm_applied = ccm is not None
    def to_lab(r: int, g: int, b: int) -> tuple[float, float, float]:
        if ccm_applied and ccm:
            from senia_calibration import apply_ccm
            r, g, b = apply_ccm(ccm, r, g, b)
        return srgb_to_lab_d50(r, g, b)

    ref_labs = [to_lab(*c) for c in ref_rgb_cells]
    sample_labs = [to_lab(*c) for c in sample_rgb_cells]

    # 整体平均 Lab
    n_ref = max(len(ref_labs), 1)
    n_smp = max(len(sample_labs), 1)
    ref_avg = (
        sum(l[0] for l in ref_labs) / n_ref,
        sum(l[1] for l in ref_labs) / n_ref,
        sum(l[2] for l in ref_labs) / n_ref,
    )
    sample_avg = (
        sum(l[0] for l in sample_labs) / n_smp,
        sum(l[1] for l in sample_labs) / n_smp,
        sum(l[2] for l in sample_labs) / n_smp,
    )

    # ── Step 2: 配准 (M2) ──
    # 在此 pipeline 入口, 假设 ref_rgb_cells 和 sample_rgb_cells 已经配准裁切
    # 实际部署时, M2 在图像层面完成 (ORB+RANSAC → NCC → ROI crop)

    # ── Step 3-6: 双管线分析 + 三级判定 + 空间均匀性 ──
    thresholds = PROFILE_THRESHOLDS.get(profile, PROFILE_THRESHOLDS["default"])

    analysis = run_full_analysis(
        ref_lab=ref_avg,
        sample_lab=sample_avg,
        grid_ref_labs=ref_labs,
        grid_sample_labs=sample_labs,
        grid_rows=grid_rows,
        grid_cols=grid_cols,
        thresholds=thresholds,
        capture_confidence=capture_confidence,
    )

    # ── Step 5: 调色建议 (M5) ──
    j = analysis.judgment
    cd = j.color_deviation
    defect_types: list[str] = []
    if j.defect_result:
        if j.defect_result.has_mottling:
            defect_types.append("mottling")
        if j.defect_result.has_streaks:
            defect_types.append("streaks")
        if j.defect_result.has_spots:
            defect_types.append("spots")

    recipe = generate_recipe_advice(
        dL=cd.dL if cd else 0,
        da=cd.da if cd else 0,
        db=cd.db if cd else 0,
        dC=cd.dC if cd else 0,
        root_cause=analysis.uniformity.root_cause,
        defect_types=defect_types,
    )

    # ── Step 7: 组装会话记录 (M7) ──
    elapsed = time.perf_counter() - start

    record = SessionRecord(
        session_id=session_id,
        lot_id=lot_id,
        product_code=product_code,
        line_id=line_id,
        operator_id=operator_id,
        profile=profile,
        customer_id=customer_id,
        calibration={"ccm_applied": ccm is not None},
        analysis=analysis.to_dict(),
        recipe_advice={
            "root_cause": recipe.root_cause,
            "is_process_issue": recipe.is_process_issue,
            "summary": recipe.summary,
            "advices": [
                {
                    "action": a.action,
                    "priority": a.priority,
                    "category": a.category,
                    "component": a.component,
                    "direction": a.direction,
                    "confidence": a.confidence,
                }
                for a in recipe.advices
            ],
        },
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
        elapsed_sec=round(elapsed, 4),
    )

    # 防篡改签名
    sig_data = {
        "session_id": record.session_id,
        "analysis": record.analysis,
        "recipe_advice": record.recipe_advice,
        "timestamp": record.timestamp,
    }
    record.sha256 = _compute_signature(sig_data)

    return record


def save_session(record: SessionRecord, output_dir: Path) -> Path:
    """保存会话记录到 JSON 文件."""
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"session_{record.session_id}.json"
    path = output_dir / filename
    data = asdict(record)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return path
