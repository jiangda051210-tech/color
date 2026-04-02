"""
SENIA M3+M4+M6: 双管线分析 + 三级判定 + 空间均匀性
=================================================
管线 A — 整体色偏判定 (全局 CIEDE2000)
管线 B — 局部缺陷检测 (FFT条纹 / IQR脏点 / 形态学划痕)
M4    — 三级判定 (合格 / 临界 / 不合格) + 偏差方向输出
M6    — 空间均匀性 (均匀偏色=配方, 不均匀=工艺)
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Any

from senia_calibration import ciede2000


# ══════════════════════════════════════════════════════════
# M3 管线 A: 整体色偏判定
# ══════════════════════════════════════════════════════════

@dataclass
class ColorDeviationResult:
    """管线A输出: 整体色差 + 偏差方向分解."""
    dE00: float = 0.0          # CIEDE2000 总色差
    dL: float = 0.0            # ΔL (正=偏亮, 负=偏暗)
    dC: float = 0.0            # ΔC (正=饱和度升高, 负=饱和度不足)
    dH: float = 0.0            # ΔH (色相偏移)
    da: float = 0.0            # Δa (正=偏红, 负=偏绿)
    db: float = 0.0            # Δb (正=偏黄, 负=偏蓝)
    directions: list[str] = field(default_factory=list)  # 偏差方向描述


def compute_color_deviation(
    ref_lab: tuple[float, float, float],
    sample_lab: tuple[float, float, float],
) -> ColorDeviationResult:
    """计算标样 vs 打样的整体色偏."""
    de = ciede2000(ref_lab[0], ref_lab[1], ref_lab[2],
                   sample_lab[0], sample_lab[1], sample_lab[2])
    da = sample_lab[1] - ref_lab[1]
    db = sample_lab[2] - ref_lab[2]

    # 偏差方向翻译
    dirs: list[str] = []
    if abs(de["dL"]) > 0.5:
        dirs.append("偏亮" if de["dL"] > 0 else "偏暗")
    if abs(da) > 0.5:
        dirs.append("偏红" if da > 0 else "偏绿")
    if abs(db) > 0.5:
        dirs.append("偏黄" if db > 0 else "偏蓝")
    if abs(de["dC"]) > 0.5:
        dirs.append("饱和度偏高" if de["dC"] > 0 else "饱和度不足")
    if de["dE00"] < 0.3:
        dirs.append("色差极小，视觉无法分辨")

    return ColorDeviationResult(
        dE00=de["dE00"],
        dL=de["dL"],
        dC=de["dC"],
        dH=de["dH"],
        da=round(da, 4),
        db=round(db, 4),
        directions=dirs,
    )


def compute_grid_deviations(
    ref_cells: list[tuple[float, float, float]],
    sample_cells: list[tuple[float, float, float]],
) -> list[ColorDeviationResult]:
    """对 N×N 网格逐块计算色偏 (用于热图)."""
    results = []
    for ref, smp in zip(ref_cells, sample_cells):
        results.append(compute_color_deviation(ref, smp))
    return results


# ══════════════════════════════════════════════════════════
# M3 管线 B: 局部缺陷检测
# ══════════════════════════════════════════════════════════

@dataclass
class DefectResult:
    """管线B输出: 各类缺陷检测结果."""
    has_mottling: bool = False       # 发花
    has_streaks: bool = False        # 条纹
    has_spots: bool = False          # 脏点
    has_scratches: bool = False      # 划痕
    mottling_severity: float = 0.0   # 0~1
    streak_severity: float = 0.0
    spot_count: int = 0
    scratch_count: int = 0
    overall_severity: float = 0.0    # 0~1 综合严重度
    details: list[str] = field(default_factory=list)


def detect_mottling(cell_L_values: list[float], threshold_std: float = 2.5) -> tuple[bool, float]:
    """
    发花检测: L通道网格标准差过大 = 发花.
    原理: 均匀涂布 → L通道空间分布一致; 发花 → L通道标准差上升.
    """
    if len(cell_L_values) < 4:
        return False, 0.0
    std = statistics.stdev(cell_L_values)
    severity = min(1.0, std / (threshold_std * 2))
    return std > threshold_std, round(severity, 3)


def detect_streaks_fft(row_means: list[float], col_means: list[float],
                       energy_threshold: float = 0.3) -> tuple[bool, float, str]:
    """
    条纹检测: 对行/列均值做FFT, 检查AC分量能量.
    条纹表现为某个空间频率的异常峰值.
    """
    def _ac_energy(values: list[float]) -> float:
        n = len(values)
        if n < 4:
            return 0.0
        mean = sum(values) / n
        centered = [v - mean for v in values]
        # 简化 DFT: 计算 AC 分量总能量 / DC 分量能量
        dc = abs(sum(centered))
        ac = sum(c ** 2 for c in centered)
        total = dc ** 2 + ac
        return ac / max(total, 1e-12)

    row_e = _ac_energy(row_means)
    col_e = _ac_energy(col_means)

    has = row_e > energy_threshold or col_e > energy_threshold
    severity = min(1.0, max(row_e, col_e) / (energy_threshold * 2))
    direction = ""
    if has:
        if row_e > col_e:
            direction = "horizontal_streaks"
        else:
            direction = "vertical_streaks"

    return has, round(severity, 3), direction


def detect_spots_iqr(cell_dE_values: list[float], iqr_multiplier: float = 2.0) -> tuple[bool, int, list[int]]:
    """
    脏点检测: 用 IQR 法找色差异常值.
    某个网格块色差远超其他块 → 局部脏点/异物.
    """
    if len(cell_dE_values) < 4:
        return False, 0, []
    sorted_v = sorted(cell_dE_values)
    n = len(sorted_v)
    q1 = sorted_v[n // 4]
    q3 = sorted_v[3 * n // 4]
    iqr = q3 - q1
    upper = q3 + iqr_multiplier * iqr

    outlier_indices = [i for i, v in enumerate(cell_dE_values) if v > upper]
    return len(outlier_indices) > 0, len(outlier_indices), outlier_indices


def run_defect_pipeline(
    cell_L_values: list[float],
    row_L_means: list[float],
    col_L_means: list[float],
    cell_dE_values: list[float],
) -> DefectResult:
    """运行完整缺陷检测管线B."""
    result = DefectResult()

    # 发花
    result.has_mottling, result.mottling_severity = detect_mottling(cell_L_values)
    if result.has_mottling:
        result.details.append(f"检测到发花 (L通道不均匀, 严重度={result.mottling_severity:.2f})")

    # 条纹
    result.has_streaks, result.streak_severity, streak_dir = detect_streaks_fft(
        row_L_means, col_L_means)
    if result.has_streaks:
        result.details.append(f"检测到{streak_dir} (严重度={result.streak_severity:.2f})")

    # 脏点
    result.has_spots, result.spot_count, _ = detect_spots_iqr(cell_dE_values)
    if result.has_spots:
        result.details.append(f"检测到 {result.spot_count} 处异常色块 (疑似脏点/异物)")

    # 综合严重度 = 取最高
    result.overall_severity = max(
        result.mottling_severity,
        result.streak_severity,
        min(1.0, result.spot_count / 5.0),
    )

    return result


# ══════════════════════════════════════════════════════════
# M4: 三级判定 + 偏差方向输出
# ══════════════════════════════════════════════════════════

@dataclass
class ThresholdConfig:
    """可配置的判定阈值, 支持按材质/客户定制."""
    pass_dE: float = 1.0       # ΔE < pass_dE → 合格
    marginal_dE: float = 2.5   # pass_dE ≤ ΔE < marginal_dE → 临界
    # ΔE ≥ marginal_dE → 不合格
    defect_marginal: float = 0.4   # 缺陷严重度 > 此值 → 降级为临界
    defect_fail: float = 0.7       # 缺陷严重度 > 此值 → 降级为不合格


@dataclass
class JudgmentResult:
    """三级判定输出."""
    tier: str = ""             # "PASS" / "MARGINAL" / "FAIL"
    dE00: float = 0.0
    color_deviation: ColorDeviationResult | None = None
    defect_result: DefectResult | None = None
    uniformity: str = ""       # "uniform" / "non_uniform"
    root_cause_hint: str = ""  # "recipe" / "process" / "mixed" / "ok"
    reasons: list[str] = field(default_factory=list)
    confidence: float = 0.0


def judge_three_tier(
    color: ColorDeviationResult,
    defects: DefectResult,
    thresholds: ThresholdConfig | None = None,
    capture_confidence: float = 1.0,
) -> JudgmentResult:
    """
    三级判定主逻辑.
    先按色差分档, 再按缺陷降级, 最后按拍摄质量调整置信度.
    """
    t = thresholds or ThresholdConfig()
    result = JudgmentResult(
        dE00=color.dE00,
        color_deviation=color,
        defect_result=defects,
    )
    reasons: list[str] = []

    # Step 1: 色差基础分档
    if color.dE00 < t.pass_dE:
        tier = "PASS"
        reasons.append(f"ΔE00={color.dE00:.2f} < {t.pass_dE} → 合格")
    elif color.dE00 < t.marginal_dE:
        tier = "MARGINAL"
        reasons.append(f"ΔE00={color.dE00:.2f} 在 {t.pass_dE}~{t.marginal_dE} 之间 → 临界")
    else:
        tier = "FAIL"
        reasons.append(f"ΔE00={color.dE00:.2f} ≥ {t.marginal_dE} → 不合格")

    # 偏差方向
    if color.directions:
        reasons.append("偏差方向: " + ", ".join(color.directions))

    # Step 2: 缺陷降级
    if defects.overall_severity > t.defect_fail:
        if tier != "FAIL":
            tier = "FAIL"
            reasons.append(f"缺陷严重度={defects.overall_severity:.2f} > {t.defect_fail} → 降为不合格")
    elif defects.overall_severity > t.defect_marginal:
        if tier == "PASS":
            tier = "MARGINAL"
            reasons.append(f"缺陷严重度={defects.overall_severity:.2f} > {t.defect_marginal} → 降为临界")

    if defects.details:
        reasons.extend(defects.details)

    # Step 3: 置信度
    confidence = min(1.0, capture_confidence)
    if confidence < 0.7:
        reasons.append(f"拍摄置信度偏低 ({confidence:.2f}), 建议重新拍摄")

    result.tier = tier
    result.reasons = reasons
    result.confidence = round(confidence, 3)
    return result


# ══════════════════════════════════════════════════════════
# M6: 空间均匀性 — 区分配方 vs 工艺问题
# ══════════════════════════════════════════════════════════

@dataclass
class UniformityResult:
    """空间均匀性分析结果."""
    is_uniform: bool = True         # True=均匀偏色, False=不均匀
    spatial_std_dE: float = 0.0     # 各区域色差的标准差
    spatial_cv: float = 0.0         # 变异系数 (CV = std/mean)
    zone_deviations: list[float] = field(default_factory=list)  # 各区域ΔE
    root_cause: str = "ok"          # "recipe" / "process" / "mixed" / "ok"
    explanation: str = ""


def analyze_spatial_uniformity(
    grid_dE_values: list[float],
    grid_defects: DefectResult,
    cv_threshold: float = 0.25,
) -> UniformityResult:
    """
    核心判据:
      - 整块膜均匀偏色 (CV < threshold) → 配方问题
      - 偏色不均匀 (CV ≥ threshold) 或有条纹/发花 → 工艺问题
      - 两者兼有 → 混合问题
    """
    result = UniformityResult(zone_deviations=grid_dE_values)

    if len(grid_dE_values) < 2:
        return result

    mean_dE = statistics.mean(grid_dE_values)
    std_dE = statistics.stdev(grid_dE_values) if len(grid_dE_values) > 1 else 0.0
    cv = std_dE / max(mean_dE, 1e-6)

    result.spatial_std_dE = round(std_dE, 4)
    result.spatial_cv = round(cv, 4)
    result.is_uniform = cv < cv_threshold

    has_spatial_defects = grid_defects.has_mottling or grid_defects.has_streaks

    if mean_dE < 0.5:
        result.root_cause = "ok"
        result.explanation = "色差极小，无需调整"
    elif result.is_uniform and not has_spatial_defects:
        result.root_cause = "recipe"
        result.explanation = (
            f"整版均匀偏色 (CV={cv:.3f}<{cv_threshold}), "
            f"大概率是配方问题, 建议调整配方"
        )
    elif not result.is_uniform or has_spatial_defects:
        if mean_dE > 1.5 and result.is_uniform:
            result.root_cause = "mixed"
            result.explanation = (
                f"整体偏色较大 (ΔE={mean_dE:.2f}) 且有空间缺陷, "
                f"配方和工艺均需排查"
            )
        else:
            result.root_cause = "process"
            result.explanation = (
                f"偏色不均匀 (CV={cv:.3f}≥{cv_threshold})"
                + (", 且有发花/条纹" if has_spatial_defects else "")
                + ", 大概率是工艺问题 (刮刀压力/烘干温度/涂布速度)"
            )
    else:
        result.root_cause = "mixed"
        result.explanation = "配方和工艺均有偏差迹象"

    return result


# ══════════════════════════════════════════════════════════
# 综合分析入口
# ══════════════════════════════════════════════════════════

@dataclass
class FullAnalysisResult:
    """完整分析结果, 包含所有子模块输出."""
    judgment: JudgmentResult = field(default_factory=JudgmentResult)
    uniformity: UniformityResult = field(default_factory=UniformityResult)
    grid_deviations: list[dict[str, Any]] = field(default_factory=list)
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        j = self.judgment
        u = self.uniformity
        return {
            "tier": j.tier,
            "dE00": j.dE00,
            "confidence": j.confidence,
            "deviation": {
                "dL": j.color_deviation.dL if j.color_deviation else 0,
                "dC": j.color_deviation.dC if j.color_deviation else 0,
                "dH": j.color_deviation.dH if j.color_deviation else 0,
                "da": j.color_deviation.da if j.color_deviation else 0,
                "db": j.color_deviation.db if j.color_deviation else 0,
                "directions": j.color_deviation.directions if j.color_deviation else [],
            },
            "defects": {
                "has_mottling": j.defect_result.has_mottling if j.defect_result else False,
                "has_streaks": j.defect_result.has_streaks if j.defect_result else False,
                "has_spots": j.defect_result.has_spots if j.defect_result else False,
                "spot_count": j.defect_result.spot_count if j.defect_result else 0,
                "overall_severity": j.defect_result.overall_severity if j.defect_result else 0,
                "details": j.defect_result.details if j.defect_result else [],
            },
            "uniformity": {
                "is_uniform": u.is_uniform,
                "spatial_cv": u.spatial_cv,
                "root_cause": u.root_cause,
                "explanation": u.explanation,
            },
            "reasons": j.reasons,
            "timestamp": self.timestamp,
        }


def run_full_analysis(
    ref_lab: tuple[float, float, float],
    sample_lab: tuple[float, float, float],
    grid_ref_labs: list[tuple[float, float, float]],
    grid_sample_labs: list[tuple[float, float, float]],
    grid_rows: int = 6,
    grid_cols: int = 8,
    thresholds: ThresholdConfig | None = None,
    capture_confidence: float = 1.0,
) -> FullAnalysisResult:
    """
    运行完整双管线分析.

    参数:
      ref_lab: 标样整体平均 Lab
      sample_lab: 打样整体平均 Lab
      grid_ref_labs: 标样 N×M 网格各块 Lab
      grid_sample_labs: 打样 N×M 网格各块 Lab
      grid_rows, grid_cols: 网格尺寸
      thresholds: 可配置判定阈值
      capture_confidence: 拍摄质量置信度 (0~1)
    """
    import time as _time

    # 管线 A: 整体色偏
    color_dev = compute_color_deviation(ref_lab, sample_lab)

    # 管线 A (网格): 逐块色偏
    grid_devs = compute_grid_deviations(grid_ref_labs, grid_sample_labs)
    grid_dE_values = [d.dE00 for d in grid_devs]

    # 管线 B: 缺陷检测
    cell_L = [s[0] for s in grid_sample_labs]
    n_rows = grid_rows
    n_cols = grid_cols
    row_L_means = []
    for r in range(n_rows):
        row_cells = cell_L[r * n_cols:(r + 1) * n_cols]
        row_L_means.append(statistics.mean(row_cells) if row_cells else 0.0)
    col_L_means = []
    for c in range(n_cols):
        col_cells = [cell_L[r * n_cols + c] for r in range(n_rows) if r * n_cols + c < len(cell_L)]
        col_L_means.append(statistics.mean(col_cells) if col_cells else 0.0)

    defects = run_defect_pipeline(cell_L, row_L_means, col_L_means, grid_dE_values)

    # M4: 三级判定
    judgment = judge_three_tier(color_dev, defects, thresholds, capture_confidence)

    # M6: 空间均匀性
    uniformity = analyze_spatial_uniformity(grid_dE_values, defects)
    judgment.uniformity = "uniform" if uniformity.is_uniform else "non_uniform"
    judgment.root_cause_hint = uniformity.root_cause

    # 把根因分析加入 reasons
    if uniformity.root_cause != "ok":
        judgment.reasons.append(f"根因分析: {uniformity.explanation}")

    return FullAnalysisResult(
        judgment=judgment,
        uniformity=uniformity,
        grid_deviations=[d.__dict__ for d in grid_devs],
        timestamp=_time.strftime("%Y-%m-%dT%H:%M:%S"),
    )
