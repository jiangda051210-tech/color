"""
SENIA Pydantic 响应模型
======================
定义所有 SENIA API 端点的请求/响应 schema,
防止前后端 JSON 结构不一致.
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Any


# ── 色差偏差 ──

class DeviationResponse(BaseModel):
    directions: list[str] = Field(default_factory=list, description="偏差方向列表, 如 ['偏红', '偏黄']")
    summary: str = Field("", description="一句话偏差描述")
    dL: float = Field(0, description="ΔL (正=偏亮, 负=偏暗)")
    da: float = Field(0, description="Δa (正=偏红, 负=偏绿)")
    db: float = Field(0, description="Δb (正=偏黄, 负=偏蓝)")
    dC: float = Field(0, description="ΔC (正=饱和度升高, 负=饱和度不足)")
    dH_deg: float = Field(0, description="ΔH 色相角偏移")


# ── 调色建议 ──

class RecipeAdviceItem(BaseModel):
    action: str = Field("", description="调整动作描述")
    priority: int = Field(0, description="优先级 (越小越高)")
    category: str = Field("recipe", description="recipe / process")
    component: str = Field("", description="涉及的配方组分")
    direction: str = Field("", description="increase / decrease / check")


class RecipeAdviceResponse(BaseModel):
    root_cause: str = Field("", description="recipe / process / mixed / ok")
    is_process_issue: bool = Field(False)
    summary: str = Field("")
    advices: list[RecipeAdviceItem] = Field(default_factory=list)


# ── 空间均匀性 ──

class UniformityResponse(BaseModel):
    is_uniform: bool = Field(True)
    spatial_cv: float = Field(0)
    root_cause: str = Field("ok", description="recipe / process / mixed / ok")
    explanation: str = Field("")
    mean_dE: float = Field(0)


# ── 分析摘要 ──

class AnalysisSummary(BaseModel):
    global_delta_e00: float = 0
    avg_delta_e00: float = 0
    p50_delta_e00: float = 0
    p95_delta_e00: float = 0
    max_delta_e00: float = 0
    dL: float = 0
    dC: float = 0
    dH_deg: float = 0
    board_lab: list[float] = Field(default_factory=list)
    sample_lab: list[float] = Field(default_factory=list)


class ConfidenceResponse(BaseModel):
    overall: float = Field(0, description="综合置信度 0~1")
    geometry: float = 0
    lighting: float = 0
    coverage: float = 0


class ResultBlock(BaseModel):
    pass_legacy: bool = Field(False, description="原有二元判定 (向后兼容)")
    confidence: ConfidenceResponse = Field(default_factory=ConfidenceResponse)
    summary: AnalysisSummary = Field(default_factory=AnalysisSummary)
    recommendations: list[str] = Field(default_factory=list)
    quality_flags: list[str] = Field(default_factory=list)
    capture_guidance: list[str] = Field(default_factory=list)


# ── 产物路径 ──

class ArtifactPaths(BaseModel):
    heatmap: str | None = None
    detection_overlay: str | None = None
    board_corrected: str | None = None
    sample_corrected: str | None = None


# ── Profile ──

class ProfileInfo(BaseModel):
    requested: str = "auto"
    used: str = "auto"
    metrics: dict[str, Any] = Field(default_factory=dict)
    targets: dict[str, float] = Field(default_factory=dict)
    targets_used: dict[str, float] = Field(default_factory=dict)


# ── 历史对比 ──

class HistoryComparison(BaseModel):
    has_baseline: bool = False
    vs_baseline: str = Field("", description="better / same / worse")
    baseline_avg: float = 0
    percentile: float = 0
    trend: str = Field("", description="improving / stable / degrading")
    drift_detected: bool = False


# ══════════════════════════════════════════════════════════
# 完整响应
# ══════════════════════════════════════════════════════════

class SeniaAnalyzeResponse(BaseModel):
    """POST /v1/senia/analyze 的完整响应."""
    mode: str = "auto_match"
    image: str = ""
    lot_id: str = ""
    product_code: str = ""
    elapsed_sec: float = 0

    # ★ 核心输出
    tier: str = Field("", description="PASS / MARGINAL / FAIL")
    tier_reasons: list[str] = Field(default_factory=list)
    deviation: DeviationResponse = Field(default_factory=DeviationResponse)
    recipe_advice: RecipeAdviceResponse = Field(default_factory=RecipeAdviceResponse)
    uniformity: UniformityResponse = Field(default_factory=UniformityResponse)

    # 历史对比
    history: HistoryComparison = Field(default_factory=HistoryComparison)

    # 详细数据
    profile: ProfileInfo = Field(default_factory=ProfileInfo)
    detection: dict[str, Any] = Field(default_factory=dict)
    result: ResultBlock = Field(default_factory=ResultBlock)
    artifacts: ArtifactPaths = Field(default_factory=ArtifactPaths)


class SeniaCalibrationResponse(BaseModel):
    """POST /v1/senia/calibrate 的响应."""
    found: bool = False
    ccm: list[list[float]] | None = None
    ccm_rmse: float | None = None
    ccm_quality: str | None = None
    reason: str = ""
    patches_rgb: list[list[int]] | None = None


class SeniaThresholdResponse(BaseModel):
    """阈值配置响应."""
    pass_dE: float = 1.0
    marginal_dE: float = 2.5
    defect_marginal: float = 0.4
    defect_fail: float = 0.7
    source: str = Field("default", description="default / product_override / customer_override")


class SeniaLotTrendResponse(BaseModel):
    """批次趋势响应."""
    has_history: bool = False
    record_count: int = 0
    avg_dE: float = 0
    latest_dE: float = 0
    pass_rate: float = 0
    trend_direction: str = ""
    drift_detected: bool = False
    drift_magnitude: float = 0
    reason: str = ""
