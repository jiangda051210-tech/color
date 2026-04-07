"""
SENIA 标准化取样 / 拍摄 / 提交流程中心
=====================================

目标:
1. 把“取样标准、拍摄标准、提交标准”从零散规则收敛成一个中心模块
2. 让前端、后端、SOP、培训资料都围绕同一套标准工作
3. 为后续把标准强接入 `elite_api.py` 和 `senia_web_ui.py` 做准备

设计原则:
- 双拍模式优先作为生产默认标准
- 单拍模式保留，但必须满足更严格的摆放和采样要求
- 标准既能输出给前端，也能给后端做校验
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


VALID_MODES = {"single", "dual"}
VALID_PROFILES = {"auto", "solid", "wood", "stone", "metallic", "high_gloss"}
VALID_LIGHTS = {"D65", "D50", "unknown"}
VALID_BACKGROUNDS = {"N7_gray", "neutral_gray", "unknown"}
VALID_SAMPLE_PLACEMENT = {
    "side_by_side",
    "top_right",
    "separate_full_frame",
    "manual_roi",
    "unknown",
}


@dataclass(slots=True)
class SamplingStandard:
    mode: str
    profile: str
    default_grid_rows: int = 6
    default_grid_cols: int = 8
    min_valid_cell_pixels: int = 80
    min_cell_coverage_ratio: float = 0.28
    border_ratio_single: float = 0.04
    border_ratio_dual: float = 0.05
    sample_overlap_forbidden: bool = True
    require_full_frame_in_dual: bool = True
    require_reference_present: bool = True
    colorchecker_required: bool = False
    aruco_recommended: bool = False
    confidence_target: float = 0.85
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CaptureWorkflow:
    mode: str
    title: str
    goal: str
    steps: list[str]
    required_fields: list[str]
    recommended_fields: list[str]
    acceptance_rules: list[str]
    rejection_rules: list[str]
    ui_copy: dict[str, str]


def _profile_adjustments(profile: str) -> dict[str, Any]:
    profile_key = profile if profile in VALID_PROFILES else "auto"
    mapping = {
        "solid": {"confidence_target": 0.90, "aruco_recommended": False},
        "wood": {"confidence_target": 0.85, "aruco_recommended": True},
        "stone": {"confidence_target": 0.85, "aruco_recommended": True},
        "metallic": {"confidence_target": 0.90, "aruco_recommended": True, "colorchecker_required": True},
        "high_gloss": {"confidence_target": 0.92, "aruco_recommended": True, "colorchecker_required": True},
        "auto": {"confidence_target": 0.85, "aruco_recommended": False},
    }
    return mapping[profile_key]


def get_sampling_standard(mode: str, profile: str = "auto") -> SamplingStandard:
    mode_key = mode if mode in VALID_MODES else "single"
    profile_key = profile if profile in VALID_PROFILES else "auto"
    adj = _profile_adjustments(profile_key)

    if mode_key == "dual":
        return SamplingStandard(
            mode="dual",
            profile=profile_key,
            border_ratio_dual=0.05,
            require_full_frame_in_dual=True,
            require_reference_present=True,
            colorchecker_required=bool(adj.get("colorchecker_required", False)),
            aruco_recommended=bool(adj.get("aruco_recommended", False)),
            confidence_target=float(adj.get("confidence_target", 0.85)),
            notes=[
                "标样与大货分开拍摄，每张图应尽量占满画面。",
                "双拍模式默认作为生产模式，优先于单拍。",
                "大货与标样应共享同一光源标准，后端按 paired white balance 处理。",
            ],
        )

    return SamplingStandard(
        mode="single",
        profile=profile_key,
        border_ratio_single=0.04,
        require_full_frame_in_dual=False,
        require_reference_present=True,
        colorchecker_required=bool(adj.get("colorchecker_required", False)),
        aruco_recommended=True,
        confidence_target=max(0.82, float(adj.get("confidence_target", 0.85)) - 0.03),
        notes=[
            "单拍模式下，标样必须与大货并排或置于右上角，禁止叠放。",
            "标样应占大货面积的约 1.5%~50%。",
            "单拍模式更依赖摆放质量和检测质量，适合快速筛查。",
        ],
    )


def build_capture_workflow(mode: str, profile: str = "auto") -> CaptureWorkflow:
    standard = get_sampling_standard(mode=mode, profile=profile)

    if standard.mode == "dual":
        return CaptureWorkflow(
            mode="dual",
            title="双拍标准流程",
            goal="先分别拍清楚标样和大货，再做高置信度对色",
            steps=[
                "确认工位光源为 D65 或已知标准光源，背景为中性灰。",
                "第 1 张只拍标样，样品尽量占满画面，避免背景过多。",
                "第 2 张只拍大货，样品尽量占满画面，避免边缘遮挡。",
                "两张图都关闭闪光灯，保持固定高度和稳定角度。",
                "上传后先做 preflight，再进入 paired white balance 和色差分析。",
            ],
            required_fields=["reference_image", "sample_image", "profile", "lot_id", "product_code"],
            recommended_fields=["light_source", "background_type", "camera_height_cm", "has_colorchecker"],
            acceptance_rules=[
                "标样和大货都应占各自画面的主体区域。",
                "两张图都通过 preflight 质量检查。",
                "不得使用闪光灯，不得混合自然光。",
            ],
            rejection_rules=[
                "任一张图模糊、过曝、过暗。",
                "任一张图主体面积太小或被标签/高光严重遮挡。",
                "双拍却上传成同一张混合图。",
            ],
            ui_copy={
                "ref_title": "标样照片",
                "ref_hint": "只拍标样，占满画面",
                "sample_title": "大货照片",
                "sample_hint": "只拍大货，占满画面",
                "status_hint": "推荐生产默认模式",
            },
        )

    return CaptureWorkflow(
        mode="single",
        title="单拍标准流程",
        goal="在一张图内同时稳定采到标样与大货，完成快速对色",
        steps=[
            "确认工位光源为 D65 或已知标准光源，背景为中性灰。",
            "大货平铺在背景板上，标样放在右上角或并排，禁止重叠。",
            "尽量让大货主体占画面中心，标样完整可见。",
            "若花纹复杂或边界不明显，建议使用 ArUco 或人工 ROI。",
            "上传后先做 preflight，再做检测、透视校正和取色。",
        ],
        required_fields=["image", "profile", "lot_id", "product_code"],
        recommended_fields=["sample_placement", "light_source", "background_type", "has_aruco"],
        acceptance_rules=[
            "标样与大货都完整出现在画面内。",
            "标样不能叠在大货上面。",
            "图像应清晰，且标样面积不能过小。",
        ],
        rejection_rules=[
            "标样缺失或与大货重叠。",
            "大货未居中，背景干扰过大。",
            "图像质量不足，导致检测置信度偏低。",
        ],
        ui_copy={
            "single_title": "上传一张同时包含大货和标样的照片",
            "single_hint": "标样放右上角或并排，禁止叠放",
            "status_hint": "适合快速筛查",
        },
    )


def validate_capture_submission(
    *,
    mode: str,
    file_count: int,
    profile: str = "auto",
    light_source: str = "unknown",
    background_type: str = "unknown",
    sample_placement: str = "unknown",
    has_colorchecker: bool = False,
    has_aruco: bool = False,
    camera_height_cm: float | None = None,
    overlap_detected: bool = False,
) -> dict[str, Any]:
    mode_key = mode if mode in VALID_MODES else "single"
    profile_key = profile if profile in VALID_PROFILES else "auto"
    standard = get_sampling_standard(mode=mode_key, profile=profile_key)

    errors: list[str] = []
    warnings: list[str] = []
    suggestions: list[str] = []

    if mode_key == "dual":
        if file_count != 2:
            errors.append("双拍模式必须上传 2 张图：标样 1 张，大货 1 张。")
        if sample_placement not in {"separate_full_frame", "unknown"}:
            warnings.append("双拍模式建议两张图都单独满幅拍摄，不要沿用单拍摆放逻辑。")
    else:
        if file_count != 1:
            errors.append("单拍模式必须上传 1 张同时包含标样和大货的图。")
        if sample_placement == "unknown":
            warnings.append("建议前端显式记录标样摆放方式，便于后端审计。")
        if sample_placement not in {"side_by_side", "top_right", "manual_roi", "unknown"}:
            errors.append("单拍模式下标样摆放方式不符合标准，应并排、右上角或人工框选。")
        if overlap_detected and standard.sample_overlap_forbidden:
            errors.append("单拍模式禁止标样与大货重叠。")

    if light_source not in VALID_LIGHTS:
        warnings.append("光源信息未识别，建议前端标准化枚举为 D65 / D50 / unknown。")
    elif light_source != "D65":
        warnings.append("当前不是 D65 光源，建议标注并纳入报告，避免跨工位误差。")

    if background_type not in VALID_BACKGROUNDS:
        warnings.append("背景类型未识别，建议前端标准化枚举为 N7_gray / neutral_gray / unknown。")
    elif background_type == "unknown":
        warnings.append("建议使用中性灰背景，减少自动检测偏差。")

    if camera_height_cm is not None:
        if camera_height_cm < 25 or camera_height_cm > 60:
            warnings.append("相机高度偏离推荐区间（30~45cm），可能影响透视一致性。")
    else:
        suggestions.append("建议前端记录 camera_height_cm，便于稽核采集一致性。")

    if standard.colorchecker_required and not has_colorchecker:
        warnings.append("当前材质建议带 ColorChecker 进行校准，否则高光/金属类精度会打折。")

    if standard.aruco_recommended and not has_aruco and mode_key == "single":
        suggestions.append("复杂花纹单拍建议启用 ArUco 或人工 ROI，降低误检率。")

    ok = len(errors) == 0
    return {
        "ok": ok,
        "mode": mode_key,
        "profile": profile_key,
        "standard": asdict(standard),
        "errors": errors,
        "warnings": warnings,
        "suggestions": suggestions,
    }


def build_frontend_contract(mode: str, profile: str = "auto") -> dict[str, Any]:
    workflow = build_capture_workflow(mode=mode, profile=profile)
    standard = get_sampling_standard(mode=mode, profile=profile)
    return {
        "mode": workflow.mode,
        "workflow": asdict(workflow),
        "sampling_standard": asdict(standard),
        "frontend_fields": {
            "required": workflow.required_fields,
            "recommended": workflow.recommended_fields,
            "enumerations": {
                "profile": sorted(VALID_PROFILES),
                "light_source": sorted(VALID_LIGHTS),
                "background_type": sorted(VALID_BACKGROUNDS),
                "sample_placement": sorted(VALID_SAMPLE_PLACEMENT),
            },
        },
    }


def standardization_backlog() -> list[dict[str, Any]]:
    return [
        {
            "priority": "P0",
            "title": "让首页前端显式采集标准字段",
            "detail": "至少补 light_source / background_type / sample_placement / has_colorchecker / camera_height_cm。",
        },
        {
            "priority": "P0",
            "title": "让 /v1/senia/analyze 和 /v1/senia/dual-shot 先做标准校验",
            "detail": "在真正分析前调用 validate_capture_submission()，不合规先拦截。",
        },
        {
            "priority": "P1",
            "title": "把采样标准写进 report",
            "detail": "每份报告记录 mode / light_source / placement / standard_version，方便审计。",
        },
        {
            "priority": "P1",
            "title": "前端按 mode 渲染不同 SOP 提示",
            "detail": "单拍明确提示“禁止叠放”，双拍明确提示“单独满幅拍摄”。",
        },
        {
            "priority": "P2",
            "title": "把标准流转成培训和质控看板",
            "detail": "统计不合规上传占比、重拍率、各工位采样偏差。",
        },
    ]


if __name__ == "__main__":
    single = build_frontend_contract(mode="single", profile="wood")
    dual = build_frontend_contract(mode="dual", profile="metallic")
    print("single workflow:")
    print(single)
    print("dual workflow:")
    print(dual)
    print("validation demo:")
    print(validate_capture_submission(
        mode="single",
        file_count=1,
        profile="wood",
        light_source="D65",
        background_type="N7_gray",
        sample_placement="side_by_side",
        has_colorchecker=False,
        has_aruco=True,
        camera_height_cm=40,
        overlap_detected=False,
    ))
