"""
SENIA 对色报告单 — 替代人工对色员的完整输出
==========================================
目标: 一张照片进来, 输出对色员能直接看懂的报告单.

人工对色员做什么:
  1. 把标样(小板)放到大货(彩膜/大板)上
  2. 目视判断: 偏什么色、偏多少、能不能放行
  3. 手写记录: OK/NG、日期、色号、调色建议
  4. 给车间反馈: "加黄"、"减红"、"加深"

系统要输出什么 (比人工更好):
  1. 精确色差值 (人眼做不到)
  2. 明确偏色方向 + 调色建议 (人工凭经验, 系统量化)
  3. 板面一致性 (人工只能大概看, 系统逐块测)
  4. 可追溯记录 (人工手写容易丢)
  5. 同色异谱风险 (人眼完全看不到)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import cv2
import numpy as np


def _ciede2000_detail(lab1: dict, lab2: dict) -> dict[str, float]:
    """计算 CIEDE2000 并返回分量详情."""
    L1, a1, b1 = lab1["L"], lab1["a"], lab1["b"]
    L2, a2, b2 = lab2["L"], lab2["a"], lab2["b"]

    import math
    C1 = math.sqrt(a1**2 + b1**2)
    C2 = math.sqrt(a2**2 + b2**2)
    avg_C = (C1 + C2) / 2.0
    G = 0.5 * (1.0 - math.sqrt(avg_C**7 / (avg_C**7 + 25.0**7 + 1e-12)))
    a1p = (1.0 + G) * a1
    a2p = (1.0 + G) * a2
    C1p = math.sqrt(a1p**2 + b1**2)
    C2p = math.sqrt(a2p**2 + b2**2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360
    h2p = math.degrees(math.atan2(b2, a2p)) % 360

    dL = L2 - L1
    dC = C2p - C1p
    dh = h2p - h1p
    if dh > 180:
        dh -= 360
    elif dh < -180:
        dh += 360
    if C1p * C2p == 0:
        dh = 0
    dH = 2.0 * math.sqrt(C1p * C2p) * math.sin(math.radians(dh / 2.0))

    avg_L = (L1 + L2) / 2.0
    avg_Cp = (C1p + C2p) / 2.0
    if abs(h1p - h2p) > 180:
        avg_hp = (h1p + h2p + 360) / 2.0
    else:
        avg_hp = (h1p + h2p) / 2.0
    if C1p * C2p == 0:
        avg_hp = h1p + h2p

    T = (1.0 - 0.17 * math.cos(math.radians(avg_hp - 30))
         + 0.24 * math.cos(math.radians(2 * avg_hp))
         + 0.32 * math.cos(math.radians(3 * avg_hp + 6))
         - 0.20 * math.cos(math.radians(4 * avg_hp - 63)))
    dt = 30.0 * math.exp(-((avg_hp - 275) / 25) ** 2)
    RC = 2.0 * math.sqrt(avg_Cp**7 / (avg_Cp**7 + 25.0**7 + 1e-12))
    SL = 1.0 + 0.015 * (avg_L - 50) ** 2 / math.sqrt(20 + (avg_L - 50) ** 2)
    SC = 1.0 + 0.045 * avg_Cp
    SH = 1.0 + 0.015 * avg_Cp * T
    RT = -math.sin(math.radians(2 * dt)) * RC
    dE = math.sqrt((dL / SL) ** 2 + (dC / SC) ** 2 + (dH / SH) ** 2
                   + RT * (dC / SC) * (dH / SH))

    da = a2 - a1
    db = b2 - b1

    return {
        "dE00": round(dE, 2),
        "dL": round(dL, 2),
        "dC": round(dC, 2),
        "dH": round(dH, 2),
        "da": round(da, 2),
        "db": round(db, 2),
    }


def _color_direction(de: dict[str, float]) -> list[str]:
    """把色差分量翻译成对色员能听懂的偏色方向."""
    dirs = []
    dL, da, db = de["dL"], de["da"], de["db"]
    if abs(dL) > 0.5:
        dirs.append(f"偏{'亮' if dL > 0 else '暗'} (ΔL={dL:+.1f})")
    if abs(da) > 0.5:
        dirs.append(f"偏{'红' if da > 0 else '绿'} (Δa={da:+.1f})")
    if abs(db) > 0.5:
        dirs.append(f"偏{'黄' if db > 0 else '蓝'} (Δb={db:+.1f})")
    if abs(de["dC"]) > 0.5:
        dirs.append(f"{'鲜艳度偏高' if de['dC'] > 0 else '鲜艳度不足'} (ΔC={de['dC']:+.1f})")
    if not dirs:
        dirs.append("色差极小，肉眼无法分辨")
    return dirs


def _adjust_suggestion(de: dict[str, float]) -> list[str]:
    """根据偏色方向生成工艺调整建议 (对色员+车间都能看懂)."""
    suggestions = []
    dL, da, db = de["dL"], de["da"], de["db"]

    if dL > 1.0:
        suggestions.append(f"建议加深：产品偏亮 {dL:+.1f}，可增加墨量或降低印刷速度")
    elif dL < -1.0:
        suggestions.append(f"建议减浅：产品偏暗 {dL:+.1f}，可减少墨量或提高印刷速度")

    if da > 0.8:
        suggestions.append(f"建议减红加绿：偏红 {da:+.1f}")
    elif da < -0.8:
        suggestions.append(f"建议加红减绿：偏绿 {da:+.1f}")

    if db > 0.8:
        suggestions.append(f"建议减黄加蓝：偏黄 {db:+.1f}")
    elif db < -0.8:
        suggestions.append(f"建议加黄减蓝：偏蓝 {db:+.1f}")

    if not suggestions:
        suggestions.append("色差在可接受范围内，无需调整")

    return suggestions


def _judge_result(dE: float, profile: str = "wood") -> dict[str, Any]:
    """三级判定 + 对色员能理解的解释."""
    # 按材质的标准阈值 (木纹允许更大色差)
    thresholds = {
        "solid":     {"pass": 1.0, "marginal": 2.0, "name": "纯色"},
        "wood":      {"pass": 1.5, "marginal": 3.0, "name": "木纹"},
        "stone":     {"pass": 2.0, "marginal": 3.5, "name": "石纹"},
        "metallic":  {"pass": 1.2, "marginal": 2.5, "name": "金属"},
        "high_gloss": {"pass": 0.8, "marginal": 1.8, "name": "高光"},
    }
    t = thresholds.get(profile, thresholds["wood"])

    if dE <= t["pass"]:
        return {
            "verdict": "OK",
            "verdict_cn": "合格 ✓",
            "tier": "PASS",
            "dE00": dE,
            "threshold": t,
            "explanation": f"色差 ΔE={dE:.2f} ≤ {t['pass']}（{t['name']}标准），可以放行",
        }
    elif dE <= t["marginal"]:
        return {
            "verdict": "MARGINAL",
            "verdict_cn": "临界 △",
            "tier": "MARGINAL",
            "dE00": dE,
            "threshold": t,
            "explanation": f"色差 ΔE={dE:.2f} 在 {t['pass']}~{t['marginal']} 之间（{t['name']}标准），建议人工复核或微调后重测",
        }
    else:
        return {
            "verdict": "NG",
            "verdict_cn": "不合格 ✗",
            "tier": "FAIL",
            "dE00": dE,
            "threshold": t,
            "explanation": f"色差 ΔE={dE:.2f} > {t['marginal']}（{t['name']}标准），需要调色返工",
        }


def generate_color_match_report(
    image_bgr: np.ndarray,
    profile: str = "wood",
) -> dict[str, Any]:
    """
    一张照片 → 完整对色报告单.

    这是系统的核心输出, 替代人工对色员的全部工作:
      1. 自动找到大货和标样
      2. 测量色差 + 偏色方向
      3. 给出 OK/NG 判定
      4. 给出工艺调整建议
      5. 分析板面一致性
      6. 记录环境和拍摄质量
    """
    from senia_preflight import preflight_check
    from elite_color_match import (
        contour_candidates, detect_all_boards, choose_board_and_sample,
        detect_concrete_background, build_invalid_mask,
        apply_outdoor_white_balance, apply_shading_correction,
        texture_suppress, bgr_to_lab_float, robust_mean_lab,
        build_material_mask, order_quad,
    )
    from ultimate_color_film_system_v2_optimized import EnvironmentCompensatorV2

    h, w = image_bgr.shape[:2]
    report_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ── 0. 预检 ──
    preflight = preflight_check(image_bgr)
    env_info = preflight.get("environment", {})
    is_outdoor = env_info.get("environment_type") in ("outdoor", "mixed")

    # ── 1. 检测所有板材 ──
    cands = contour_candidates(image_bgr)
    all_boards = detect_all_boards(cands, image_bgr.shape, image_bgr)
    board_obj, sample_obj, detect_diag = choose_board_and_sample(
        cands, image_bgr.shape, image_bgr, multi_board=True,
    )

    # ── 2. 识别大货和标样 ──
    # 策略: 最大的是大货, 在大货上面或旁边最小的是标样
    boards_sorted = sorted(all_boards, key=lambda b: b["area_ratio"], reverse=True)
    main_board = boards_sorted[0] if boards_sorted else None
    sample_board = None
    planks = []

    for b in boards_sorted:
        if b is main_board:
            continue
        if b["area_ratio"] < main_board["area_ratio"] * 0.3 and sample_board is None:
            sample_board = b  # 第一个比大货小很多的 = 标样
        else:
            planks.append(b)

    # ── 3. 测量色差 ──
    color_match = None
    if main_board and main_board.get("mean_lab") and sample_board and sample_board.get("mean_lab"):
        de_detail = _ciede2000_detail(main_board["mean_lab"], sample_board["mean_lab"])
        color_match = {
            "delta_e": de_detail,
            "directions": _color_direction(de_detail),
            "judgment": _judge_result(de_detail["dE00"], profile),
            "adjust_suggestions": _adjust_suggestion(de_detail),
        }
    elif main_board and main_board.get("mean_lab") and len(planks) > 0:
        # 没找到明确标样, 用最大板和第二大板对比
        second = planks[0] if planks else boards_sorted[1] if len(boards_sorted) > 1 else None
        if second and second.get("mean_lab"):
            de_detail = _ciede2000_detail(main_board["mean_lab"], second["mean_lab"])
            color_match = {
                "delta_e": de_detail,
                "directions": _color_direction(de_detail),
                "judgment": _judge_result(de_detail["dE00"], profile),
                "adjust_suggestions": _adjust_suggestion(de_detail),
                "note": "未找到明确标样，使用最大两块板材对比",
            }

    # ── 4. 板面一致性 (多块板之间) ──
    consistency = None
    boards_with_lab = [b for b in all_boards if b.get("mean_lab")]
    if len(boards_with_lab) >= 2:
        pairs = []
        for i in range(len(boards_with_lab)):
            for j in range(i + 1, len(boards_with_lab)):
                de = _ciede2000_detail(boards_with_lab[i]["mean_lab"],
                                       boards_with_lab[j]["mean_lab"])
                pairs.append(de["dE00"])
        consistency = {
            "板材数量": len(boards_with_lab),
            "板间最小色差": round(min(pairs), 2),
            "板间最大色差": round(max(pairs), 2),
            "板间平均色差": round(float(np.mean(pairs)), 2),
            "一致性评价": "良好" if max(pairs) < 2.0 else "一般" if max(pairs) < 4.0 else "较差",
        }

    # ── 5. 环境评估 ──
    env_comp = EnvironmentCompensatorV2()
    lighting = env_comp.detect_lighting_source(image_bgr)
    bg = detect_concrete_background(image_bgr)

    environment = {
        "拍摄环境": {"outdoor": "户外", "indoor": "室内", "mixed": "半户外"}.get(
            env_info.get("environment_type", ""), "未知"),
        "光源类型": lighting.get("description", "未知"),
        "色温": f"{lighting.get('estimated_cct', 0):.0f}K",
        "背景类型": {"concrete": "水泥地面", "asphalt": "沥青地面"}.get(
            bg.get("background_type", ""), "其他"),
        "拍摄质量": preflight.get("quality", "unknown"),
    }
    if is_outdoor:
        penalty = env_comp.compute_outdoor_confidence_penalty(env_info)
        environment["户外置信度损失"] = f"{penalty['total_penalty']:.0%}"
        suggestions = env_comp.suggest_outdoor_capture(env_info)
        if suggestions:
            environment["改善建议"] = suggestions[:2]

    # ── 6. 组装报告单 ──
    report: dict[str, Any] = {
        "报告标题": "SENIA 自动对色报告单",
        "报告时间": report_time,
        "图片尺寸": f"{w}x{h}",
        "材质类型": profile,
    }

    # 检测结果
    report["检测结果"] = {
        "检测到板材数": len(all_boards),
        "大货": {
            "检测到": main_board is not None,
            "面积占比": f"{main_board['area_ratio']*100:.1f}%" if main_board else "N/A",
            "LAB": main_board.get("mean_lab") if main_board else None,
        },
        "标样": {
            "检测到": sample_board is not None,
            "面积占比": f"{sample_board['area_ratio']*100:.1f}%" if sample_board else "N/A",
            "LAB": sample_board.get("mean_lab") if sample_board else None,
        },
    }

    # 对色判定 (最重要的输出)
    if color_match:
        j = color_match["judgment"]
        report["对色判定"] = {
            "结论": j["verdict_cn"],
            "色差值": f"ΔE = {j['dE00']:.2f}",
            "判定标准": j["explanation"],
            "偏色方向": color_match["directions"],
            "色差分量": {
                "ΔL (明暗)": f"{color_match['delta_e']['dL']:+.2f}",
                "Δa (红绿)": f"{color_match['delta_e']['da']:+.2f}",
                "Δb (黄蓝)": f"{color_match['delta_e']['db']:+.2f}",
            },
        }
        report["工艺调整建议"] = color_match["adjust_suggestions"]
    else:
        report["对色判定"] = {
            "结论": "无法判定",
            "原因": "未能同时检测到大货和标样，请确保两者都在画面中",
        }
        report["工艺调整建议"] = ["请重新拍摄，确保标样放在大货上方"]

    # 板面一致性
    if consistency:
        report["板面一致性"] = consistency

    # 环境信息
    report["拍摄环境"] = environment

    # 预检警告
    if preflight.get("warnings"):
        report["拍摄注意事项"] = preflight["warnings"][:5]

    return report


def print_report(report: dict[str, Any]) -> str:
    """把报告格式化为对色员能看懂的文本."""
    lines = []
    lines.append("=" * 50)
    lines.append(f"  {report.get('报告标题', 'SENIA 对色报告')}")
    lines.append(f"  {report.get('报告时间', '')}")
    lines.append("=" * 50)

    # 对色判定 (最醒目)
    j = report.get("对色判定", {})
    lines.append("")
    verdict = j.get("结论", "N/A")
    lines.append(f"  【判定】{verdict}")
    if "色差值" in j:
        lines.append(f"  【色差】{j['色差值']}")
    if "判定标准" in j:
        lines.append(f"  【标准】{j['判定标准']}")
    if "偏色方向" in j:
        lines.append(f"  【偏色】{', '.join(j['偏色方向'])}")
    if "色差分量" in j:
        parts = j["色差分量"]
        lines.append(f"  【分量】{parts.get('ΔL (明暗)','')}  {parts.get('Δa (红绿)','')}  {parts.get('Δb (黄蓝)','')}")

    # 工艺建议
    suggestions = report.get("工艺调整建议", [])
    if suggestions:
        lines.append("")
        lines.append("  ── 工艺调整建议 ──")
        for s in suggestions:
            lines.append(f"  → {s}")

    # 一致性
    cons = report.get("板面一致性")
    if cons:
        lines.append("")
        lines.append("  ── 板面一致性 ──")
        lines.append(f"  板材数: {cons['板材数量']}  |  板间色差: {cons['板间最小色差']}~{cons['板间最大色差']}  |  评价: {cons['一致性评价']}")

    # 环境
    env = report.get("拍摄环境", {})
    if env:
        lines.append("")
        lines.append(f"  ── 拍摄环境 ──")
        lines.append(f"  环境: {env.get('拍摄环境','?')}  |  光源: {env.get('光源类型','?')}  |  色温: {env.get('色温','?')}  |  质量: {env.get('拍摄质量','?')}")

    # 检测信息
    det = report.get("检测结果", {})
    lines.append("")
    lines.append(f"  检测到 {det.get('检测到板材数', 0)} 块板材  |  大货: {'✓' if det.get('大货',{}).get('检测到') else '✗'}  |  标样: {'✓' if det.get('标样',{}).get('检测到') else '✗'}")

    lines.append("=" * 50)
    return "\n".join(lines)
