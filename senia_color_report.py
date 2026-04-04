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
    precomputed_boards: list | None = None,
    precomputed_preflight: dict | None = None,
) -> dict[str, Any]:
    """
    一张照片 → 完整对色报告单.

    支持接收预计算数据 (避免重复计算):
      precomputed_boards: 已检测的板材列表 (跳过contour+detect)
      precomputed_preflight: 已完成的预检结果 (跳过preflight)
    """
    from senia_preflight import preflight_check
    from elite_color_match import (
        contour_candidates, detect_all_boards,
        detect_concrete_background,
        apply_outdoor_white_balance, apply_shading_correction,
        texture_suppress, bgr_to_lab_float, robust_mean_lab,
        build_material_mask, order_quad,
    )
    from ultimate_color_film_system_v2_optimized import EnvironmentCompensatorV2

    h, w = image_bgr.shape[:2]
    report_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 大图降采样
    MAX_EDGE = 2000
    if max(h, w) > MAX_EDGE:
        scale = MAX_EDGE / max(h, w)
        image_bgr = cv2.resize(image_bgr, (int(w * scale), int(h * scale)),
                               interpolation=cv2.INTER_AREA)
        h, w = image_bgr.shape[:2]

    # ── 0. 预检 (可复用) ──
    if precomputed_preflight is not None:
        preflight = precomputed_preflight
    else:
        preflight = preflight_check(image_bgr)
    env_info = preflight.get("environment", {})
    is_outdoor = env_info.get("environment_type") in ("outdoor", "mixed")

    # ── 1. 板材检测 (可复用) ──
    if precomputed_boards is not None:
        all_boards = precomputed_boards
    else:
        cands = contour_candidates(image_bgr)
        all_boards = detect_all_boards(cands, image_bgr.shape, image_bgr)

    # 严格过滤
    all_boards = [b for b in all_boards
                  if b.get("mean_lab")
                  and b.get("used_pixels", 0) >= 500
                  and b.get("valid_pixel_ratio", 0) >= 0.15]

    # ── 2. 智能识别大货和标样 ──
    # 优化: 阈值10(原15太松), 多数派投票, 光照校正后重测
    SIMILARITY_THRESHOLD = 10.0
    boards_sorted = sorted(all_boards, key=lambda b: b["area_ratio"], reverse=True)
    boards_with_lab = [b for b in boards_sorted if b.get("mean_lab")]

    main_board = None
    sample_board = None
    similar_planks = []
    other_objects = []
    layout = "unknown"

    if len(boards_with_lab) >= 2:
        for b in boards_with_lab:
            close_count = 0
            for other in boards_with_lab:
                if other is b:
                    continue
                de = _ciede2000_detail(b["mean_lab"], other["mean_lab"])["dE00"]
                if de < SIMILARITY_THRESHOLD:
                    close_count += 1
            b["_close_count"] = close_count

        boards_by_popularity = sorted(boards_with_lab,
                                      key=lambda b: (b["_close_count"], b["area_ratio"]),
                                      reverse=True)
        main_board = boards_by_popularity[0]

        for b in boards_with_lab:
            if b is main_board:
                continue
            de = _ciede2000_detail(main_board["mean_lab"], b["mean_lab"])
            b["_de_to_main"] = de["dE00"]
            b["_de_detail_to_main"] = de
            if de["dE00"] < SIMILARITY_THRESHOLD:
                similar_planks.append(b)
            else:
                other_objects.append(b)

    elif len(boards_with_lab) == 1:
        main_board = boards_with_lab[0]

    if main_board:
        if len(similar_planks) >= 3:
            layout = "multi_plank"
            small_similar = [b for b in similar_planks
                             if b["area_ratio"] < main_board["area_ratio"] * 0.5]
            if small_similar:
                sample_board = min(small_similar, key=lambda b: b["_de_to_main"])
        elif len(similar_planks) >= 1:
            small_similar = [b for b in similar_planks
                             if b["area_ratio"] < main_board["area_ratio"] * 0.5]
            if small_similar:
                layout = "board_and_sample"
                sample_board = min(small_similar, key=lambda b: b["_de_to_main"])
            else:
                layout = "multi_plank"
        else:
            layout = "single_board"

    # 排除高方差板材 (std_L>12 说明混入了文字/标签等异质内容)
    clean_similar = [b for b in similar_planks if b.get("quality_warning") != "high_variance"]
    if main_board and main_board.get("quality_warning") == "high_variance" and clean_similar:
        # 主板质量差, 用质量最好的替代
        main_board = clean_similar[0]
        clean_similar = clean_similar[1:]
    consistency_boards = ([main_board] + clean_similar) if main_board else []

    # ── 2b. 自动检测材质 ──
    if profile == "auto" and main_board and main_board.get("mean_lab"):
        lab_m = main_board["mean_lab"]
        chroma = (lab_m["a"] ** 2 + lab_m["b"] ** 2) ** 0.5
        if chroma < 3:
            profile = "solid"
        elif lab_m["L"] > 70 and chroma > 10:
            profile = "high_gloss"
        else:
            profile = "wood"

    # ── 2c. 颜色已在 detect_all_boards 中精确测量 ──
    # (透视校正 → 纹理抑制 → 无效掩码 → 白平衡 → IQR稳健统计)
    # 重新计算板间色差 (使用精确值)
    if main_board:
        for b in similar_planks:
            if b.get("mean_lab") and main_board.get("mean_lab"):
                de = _ciede2000_detail(main_board["mean_lab"], b["mean_lab"])
                b["_de_to_main"] = de["dE00"]
                b["_de_detail_to_main"] = de

    # ── 3. 测量色差 ──
    color_match = None
    if main_board and sample_board and sample_board.get("mean_lab"):
        de_detail = _ciede2000_detail(sample_board["mean_lab"], main_board["mean_lab"])
        color_match = {
            "delta_e": de_detail,
            "directions": _color_direction(de_detail),
            "judgment": _judge_result(de_detail["dE00"], profile),
            "adjust_suggestions": _adjust_suggestion(de_detail),
        }
    elif layout == "multi_plank" and len(consistency_boards) >= 2:
        # 多板材模式: 取所有板对中色差最小的一对作为对色判定
        # (颜色最接近的两块板 = 最可能是大货和标样的配对)
        best_de = float("inf")
        best_i, best_j = 0, 1
        for i in range(len(consistency_boards)):
            for j in range(i + 1, len(consistency_boards)):
                if consistency_boards[i].get("mean_lab") and consistency_boards[j].get("mean_lab"):
                    de = _ciede2000_detail(consistency_boards[i]["mean_lab"],
                                           consistency_boards[j]["mean_lab"])["dE00"]
                    if de < best_de:
                        best_de = de
                        best_i, best_j = i, j
        if best_de < float("inf"):
            de_detail = _ciede2000_detail(consistency_boards[best_i]["mean_lab"],
                                          consistency_boards[best_j]["mean_lab"])
            color_match = {
                "delta_e": de_detail,
                "directions": _color_direction(de_detail),
                "judgment": _judge_result(de_detail["dE00"], profile),
                "adjust_suggestions": _adjust_suggestion(de_detail),
                "note": f"多板材模式: {len(similar_planks)+1}块相似板中与主板最接近的对比",
            }

    # ── 4. 板面一致性 + 偏差最大板材标注 ──
    # 只统计同产品板对 (dE < 5), 排除误检入的非同产品区域
    consistency = None
    if len(consistency_boards) >= 2:
        all_pairs = []
        same_product_pairs = []
        board_avg_de: dict[int, list[float]] = {}
        for i in range(len(consistency_boards)):
            for j in range(i + 1, len(consistency_boards)):
                if consistency_boards[i].get("mean_lab") and consistency_boards[j].get("mean_lab"):
                    de = _ciede2000_detail(consistency_boards[i]["mean_lab"],
                                           consistency_boards[j]["mean_lab"])
                    all_pairs.append(de["dE00"])
                    # 只有dE<5的板对才计入一致性 (超过5说明不是同一产品)
                    if de["dE00"] < 5.0:
                        same_product_pairs.append(de["dE00"])
                    board_avg_de.setdefault(i, []).append(de["dE00"])
                    board_avg_de.setdefault(j, []).append(de["dE00"])
        pairs = same_product_pairs if same_product_pairs else all_pairs
        if pairs:
            worst_idx = max(board_avg_de,
                            key=lambda k: float(np.mean(board_avg_de[k]))) if board_avg_de else None
            worst_avg = round(float(np.mean(board_avg_de[worst_idx])), 2) if worst_idx is not None else 0

            # 测量可靠性: 用每块板的有效像素率加权
            reliability_scores = []
            for b in consistency_boards:
                vr = b.get("valid_pixel_ratio", 0.5)
                std_l = b.get("std_lab", {}).get("L", 5.0)
                # 高有效率+低方差 = 高可靠性
                rel = min(1.0, vr) * max(0.3, 1.0 - std_l / 20.0)
                reliability_scores.append(round(rel, 2))
            avg_reliability = round(float(np.mean(reliability_scores)), 2)

            consistency = {
                "板材数量": len(consistency_boards),
                "板间最小色差": round(min(pairs), 2),
                "板间最大色差": round(max(pairs), 2),
                "板间平均色差": round(float(np.mean(pairs)), 2),
                "一致性评价": "良好" if max(pairs) < 2.0 else "一般" if max(pairs) < 4.0 else "较差",
                "测量可靠性": f"{avg_reliability:.0%}",
            }
            if worst_idx is not None and worst_avg > 2.0:
                consistency["偏差最大板"] = f"第{worst_idx+1}块 (平均色差={worst_avg})"
            if other_objects:
                consistency["已排除非产品区域"] = len(other_objects)

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

    # ── 6. 置信度计算 ──
    confidence = 0.90  # 基线
    conf_factors = []
    # 预检质量
    if preflight.get("quality") == "good":
        pass
    elif preflight.get("quality") == "acceptable":
        confidence -= 0.05
        conf_factors.append("拍摄质量一般 -5%")
    else:
        confidence -= 0.15
        conf_factors.append("拍摄质量差 -15%")
    # 户外惩罚
    if is_outdoor:
        env_comp_check = EnvironmentCompensatorV2()
        pen = env_comp_check.compute_outdoor_confidence_penalty(env_info)
        confidence -= pen["total_penalty"]
        if pen["total_penalty"] > 0:
            conf_factors.append(f"户外环境 -{pen['total_penalty']:.0%}")
    # 检测到标样
    if sample_board is None and layout != "single_board":
        confidence -= 0.10
        conf_factors.append("未检测到标样 -10%")
    # 产品板数量
    if len(consistency_boards) >= 3:
        confidence += 0.05
        conf_factors.append("多板交叉验证 +5%")
    confidence = round(max(0.30, min(1.0, confidence)), 2)

    # ── 7. 组装报告单 ──
    report: dict[str, Any] = {
        "报告标题": "SENIA 自动对色报告单",
        "报告时间": report_time,
        "图片尺寸": f"{w}x{h}",
        "材质类型": profile,
        "置信度": f"{confidence:.0%}",
        "置信度因素": conf_factors if conf_factors else ["标准条件"],
    }

    # 检测结果
    layout_names = {
        "board_and_sample": "大货+标样",
        "multi_plank": "多板材一致性",
        "single_board": "单板",
        "unknown": "未识别",
    }
    report["检测结果"] = {
        "检测到板材数": len(all_boards),
        "识别为产品的板材": len(consistency_boards),
        "排除的非产品区域": len(other_objects),
        "布局模式": layout_names.get(layout, layout),
        "大货": {
            "检测到": main_board is not None,
            "面积占比": f"{main_board['area_ratio']*100:.1f}%" if main_board else "N/A",
            "LAB": main_board.get("mean_lab") if main_board else None,
        },
        "标样": {
            "检测到": sample_board is not None,
            "面积占比": f"{sample_board['area_ratio']*100:.1f}%" if sample_board else "N/A",
            "LAB": sample_board.get("mean_lab") if sample_board else None,
            "与大货色差": f"{sample_board.get('_de_to_main', 0):.2f}" if sample_board else "N/A",
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
    lines.append(f"  {report.get('报告时间', '')}  |  材质: {report.get('材质类型', '?')}  |  置信度: {report.get('置信度', '?')}")
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
        lines.append(f"  板材数: {cons['板材数量']}  |  板间色差: {cons['板间最小色差']}~{cons['板间最大色差']}  |  评价: {cons['一致性评价']}  |  可靠性: {cons.get('测量可靠性','?')}")
        if "偏差最大板" in cons:
            lines.append(f"  ⚠ 偏差最大: {cons['偏差最大板']}")
        if cons.get("已排除非产品区域"):
            lines.append(f"  已排除 {cons['已排除非产品区域']} 个非产品区域(背景/柱体等)")

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
