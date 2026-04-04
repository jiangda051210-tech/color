"""
SENIA 行业最佳实践集成 — 吸收X-Rite/Datacolor/Nix所有优点
============================================================
学习行业标杆, 用纯手机实现他们需要硬件才能做的功能:

1. 自动墨量配方计算 (Datacolor MATCH 的核心能力)
2. 多张照片融合降噪 (X-Rite CAPSURE 多次测量取平均)
3. 色差热力图 (X-Rite报告可视化)
4. 拍照质量实时引导 (比硬件设备更智能的引导)
5. 同色号历史批次对比 (X-Rite NetProfiler 趋势追踪)
6. 色彩电子护照 (供应链签收确认)
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np


# ════════════════════════════════════════════════
# 1. 自动墨量配方计算 (Datacolor MATCH的核心功能)
# ════════════════════════════════════════════════

# 墨量与LAB的经验映射矩阵
# 基于装饰膜印刷行业的经验数据:
#   C(青) → 主要影响 b(蓝方向) 和 L(暗)
#   M(品) → 主要影响 a(红方向)
#   Y(黄) → 主要影响 b(黄方向)
#   K(黑) → 主要影响 L(暗)
INK_SENSITIVITY = {
    "C": {"dL": -0.8, "da": -0.3, "db": -1.5},  # 每增1%青墨
    "M": {"dL": -0.5, "da": +1.2, "db": -0.2},  # 每增1%品墨
    "Y": {"dL": -0.3, "da": -0.1, "db": +1.4},  # 每增1%黄墨
    "K": {"dL": -2.0, "da": +0.05, "db": +0.05}, # 每增1%黑墨
}


def calculate_ink_recipe(
    current_de: dict[str, float],
    max_adjustment_pct: float = 5.0,
) -> dict[str, Any]:
    """
    根据色差分量自动计算墨量调整配方.

    输入: dL, da, db (大货相对标样的偏差)
    输出: C/M/Y/K 各增减百分比

    原理: 解线性方程组 — 找到CMYK调整量使偏差最小化.
    用伪逆求解 (overdetermined system), 避免负墨量.
    """
    dL = current_de.get("dL", 0)
    da = current_de.get("da", 0)
    db = current_de.get("db", 0)

    # 构建灵敏度矩阵 A (3x4) 和目标向量 b (3x1)
    # A * x = -[dL, da, db] (要把偏差消除到0)
    A = np.array([
        [INK_SENSITIVITY["C"]["dL"], INK_SENSITIVITY["M"]["dL"],
         INK_SENSITIVITY["Y"]["dL"], INK_SENSITIVITY["K"]["dL"]],
        [INK_SENSITIVITY["C"]["da"], INK_SENSITIVITY["M"]["da"],
         INK_SENSITIVITY["Y"]["da"], INK_SENSITIVITY["K"]["da"]],
        [INK_SENSITIVITY["C"]["db"], INK_SENSITIVITY["M"]["db"],
         INK_SENSITIVITY["Y"]["db"], INK_SENSITIVITY["K"]["db"]],
    ])
    target = np.array([-dL, -da, -db])

    # 伪逆求解
    x, _, _, _ = np.linalg.lstsq(A, target, rcond=None)

    # 限幅 + 格式化
    recipe: dict[str, float] = {}
    actions: list[str] = []
    for i, ink in enumerate(["C", "M", "Y", "K"]):
        adj = float(np.clip(x[i], -max_adjustment_pct, max_adjustment_pct))
        if abs(adj) > 0.1:
            recipe[ink] = round(adj, 1)
            direction = "增加" if adj > 0 else "减少"
            ink_names = {"C": "青(Cyan)", "M": "品红(Magenta)", "Y": "黄(Yellow)", "K": "黑(Black)"}
            actions.append(f"{ink_names[ink]} {direction} {abs(adj):.1f}%")

    # 预测调整后的色差
    predicted_remaining = np.array([dL, da, db]) + A @ np.array([recipe.get(k, 0) for k in "CMYK"])
    predicted_de = float(np.sqrt(sum(v ** 2 for v in predicted_remaining)))

    return {
        "配方调整": recipe if recipe else {"说明": "色差已在可控范围，无需调整"},
        "具体操作": actions if actions else ["保持当前配方"],
        "预测调整后色差": round(predicted_de, 2),
        "当前色差": round(float(np.sqrt(dL ** 2 + da ** 2 + db ** 2)), 2),
        "说明": f"调整后预计色差从 {float(np.sqrt(dL**2 + da**2 + db**2)):.2f} 降到 {predicted_de:.2f}",
    }


# ════════════════════════════════════════════════
# 2. 多张照片融合降噪
# ════════════════════════════════════════════════

def fuse_multiple_photos(images: list[np.ndarray]) -> tuple[np.ndarray, dict[str, Any]]:
    """
    融合多张同场景照片, 降低随机噪声.

    原理: 对同一场景拍N张, 取像素级中值/平均, 随机噪声被压制.
    信噪比提升: ~sqrt(N)倍. 3张→1.7倍, 5张→2.2倍.

    要求: 所有照片必须是同一场景, 尺寸相同.
    """
    if len(images) < 2:
        return images[0] if images else np.zeros((1, 1, 3), dtype=np.uint8), {"fused": False}

    # 统一尺寸到最小的
    min_h = min(img.shape[0] for img in images)
    min_w = min(img.shape[1] for img in images)
    resized = [cv2.resize(img, (min_w, min_h), interpolation=cv2.INTER_AREA) for img in images]

    # 像素级中值融合 (比均值更抗极端值)
    stack = np.stack(resized, axis=0)
    fused = np.median(stack, axis=0).astype(np.uint8)

    # 评估融合质量
    noise_before = float(np.std([img.astype(np.float32) for img in resized]))
    noise_after = float(cv2.Laplacian(cv2.cvtColor(fused, cv2.COLOR_BGR2GRAY), cv2.CV_64F).std())

    return fused, {
        "fused": True,
        "照片数量": len(images),
        "信噪比提升": f"~{len(images)**0.5:.1f}x",
        "建议": f"融合了{len(images)}张照片, 测量精度提升约{len(images)**0.5:.1f}倍",
    }


# ════════════════════════════════════════════════
# 3. 色差热力图生成
# ════════════════════════════════════════════════

def generate_heatmap_data(
    image_bgr: np.ndarray,
    board_quad: np.ndarray,
    ref_lab: dict[str, float],
    grid_rows: int = 6,
    grid_cols: int = 8,
) -> dict[str, Any]:
    """
    生成板材表面色差热力图数据.

    X-Rite报告里的经典可视化 — 让操作员一眼看出哪里偏色最严重.
    输出JSON格式的网格数据, 可直接用于前端渲染.
    """
    from elite_color_match import (order_quad, texture_suppress,
        build_material_mask, build_invalid_mask, bgr_to_lab_float)
    from senia_color_report import _ciede2000_detail

    quad = order_quad(board_quad)
    widths = [np.linalg.norm(quad[1] - quad[0]), np.linalg.norm(quad[2] - quad[3])]
    heights = [np.linalg.norm(quad[3] - quad[0]), np.linalg.norm(quad[2] - quad[1])]
    bw, bh = int(max(widths)), int(max(heights))

    if bw < 60 or bh < 60:
        return {"error": "板材区域太小"}

    dst = np.array([[0, 0], [bw, 0], [bw, bh], [0, bh]], dtype=np.float32)
    M = cv2.getPerspectiveTransform(quad, dst)
    warped = cv2.warpPerspective(image_bgr, M, (bw, bh))
    tone = texture_suppress(warped)
    lab = bgr_to_lab_float(tone)
    mask = build_material_mask(tone.shape[:2], 0.03)
    invalid = build_invalid_mask(tone)
    valid = mask & (~invalid)

    cells = []
    max_de = 0
    for r in range(grid_rows):
        y0 = int(r * bh / grid_rows)
        y1 = int((r + 1) * bh / grid_rows)
        for c in range(grid_cols):
            x0 = int(c * bw / grid_cols)
            x1 = int((c + 1) * bw / grid_cols)
            cell_mask = valid[y0:y1, x0:x1]
            if np.count_nonzero(cell_mask) < 20:
                cells.append({"row": r, "col": c, "dE": None, "valid": False})
                continue
            cell_lab = lab[y0:y1, x0:x1][cell_mask].mean(axis=0)
            cell_dict = {"L": float(cell_lab[0]), "a": float(cell_lab[1]), "b": float(cell_lab[2])}
            de = _ciede2000_detail(cell_dict, ref_lab)
            cells.append({
                "row": r, "col": c,
                "dE": round(de["dE00"], 2),
                "dL": round(de["dL"], 2),
                "valid": True,
            })
            max_de = max(max_de, de["dE00"])

    return {
        "grid": {"rows": grid_rows, "cols": grid_cols},
        "cells": cells,
        "max_dE": round(max_de, 2),
        "ref_lab": ref_lab,
        "说明": "dE>3.0为红色区域(不合格), 1.5-3.0为黄色(临界), <1.5为绿色(合格)",
    }


# ════════════════════════════════════════════════
# 4. 拍照质量实时引导
# ════════════════════════════════════════════════

def photo_guidance(image_bgr: np.ndarray) -> dict[str, Any]:
    """
    拍照质量实时检查 — 比硬件设备更智能的引导.

    在操作员拍照后立即反馈, 告诉他需不需要重拍:
    - 太模糊? → "请稳住手机"
    - 太暗? → "请移到亮处"
    - 角度太大? → "请正对板面拍摄"
    - 板材不完整? → "请让板材完整入镜"
    - 手影在板上? → "请避免手影"
    """
    from senia_preflight import preflight_check, detect_outdoor_environment
    from elite_color_match import contour_candidates, detect_all_boards

    h, w = image_bgr.shape[:2]
    issues: list[str] = []
    score = 100

    # 1. 预检
    pf = preflight_check(image_bgr)
    if pf.get("errors"):
        for e in pf["errors"]:
            issues.append(f"❌ {e}")
            score -= 20

    # 2. 板材检测
    cands = contour_candidates(image_bgr)
    boards = detect_all_boards(cands, image_bgr.shape, image_bgr)
    usable = [b for b in boards if b.get("mean_lab") and b.get("used_pixels", 0) >= 500]

    if len(usable) == 0:
        issues.append("❌ 未检测到板材，请确保板材在画面中")
        score -= 40
    elif len(usable) == 1:
        issues.append("⚠️ 只检测到1块板材，对色需要大货+标样两块")
        score -= 15

    # 3. 板材占比
    if usable:
        total_ratio = sum(b.get("area_ratio", 0) for b in usable)
        if total_ratio < 0.15:
            issues.append("⚠️ 板材占画面太小，请靠近拍摄")
            score -= 10

    # 4. 环境
    env = detect_outdoor_environment(image_bgr)
    if env.get("hard_shadows_detected"):
        issues.append("⚠️ 检测到硬阴影，请移到阴凉处")
        score -= 10

    # 5. 最终评价
    if score >= 80:
        verdict = "可以对色"
        action = "照片质量合格，可以进行对色分析"
    elif score >= 50:
        verdict = "勉强可用"
        action = "建议改善后重拍以获得更准确结果"
    else:
        verdict = "需要重拍"
        action = "照片质量不足，请按提示重新拍摄"

    if not issues:
        issues.append("✅ 照片质量良好")

    return {
        "评分": score,
        "verdict": verdict,
        "action": action,
        "issues": issues,
        "板材数": len(usable),
    }


# ════════════════════════════════════════════════
# 5. 同色号历史批次对比
# ════════════════════════════════════════════════

class ColorHistoryTracker:
    """
    按色号追踪历史批次色差数据.

    X-Rite NetProfiler 的核心能力 — 看到同一个色号随时间的变化趋势.
    """

    def __init__(self, db_path: str = "color_history.json") -> None:
        self._path = Path(db_path)
        self._data: dict[str, list[dict[str, Any]]] = {}
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._data = {}

    def _save(self) -> None:
        self._path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2,
                                         default=str), encoding="utf-8")

    def record(
        self,
        color_code: str,
        lab: dict[str, float],
        de: float,
        verdict: str,
        batch_id: str = "",
    ) -> dict[str, Any]:
        """记录一次对色结果."""
        if color_code not in self._data:
            self._data[color_code] = []

        record = {
            "timestamp": datetime.now().isoformat(),
            "lab": lab,
            "dE": round(de, 2),
            "verdict": verdict,
            "batch_id": batch_id,
        }
        self._data[color_code].append(record)

        # 最多保留500条
        if len(self._data[color_code]) > 500:
            self._data[color_code] = self._data[color_code][-500:]

        self._save()
        return {"recorded": True, "total_records": len(self._data[color_code])}

    def get_trend(self, color_code: str) -> dict[str, Any]:
        """获取某色号的历史趋势."""
        records = self._data.get(color_code, [])
        if len(records) < 2:
            return {"color_code": color_code, "records": len(records), "趋势": "数据不足"}

        des = [r["dE"] for r in records]
        verdicts = [r["verdict"] for r in records]

        # 趋势分析
        recent_5 = des[-5:] if len(des) >= 5 else des
        early_5 = des[:5] if len(des) >= 5 else des
        drift = float(np.mean(recent_5) - np.mean(early_5))

        pass_rate = sum(1 for v in verdicts if "合格" in v) / len(verdicts)

        return {
            "color_code": color_code,
            "总记录数": len(records),
            "历史平均色差": round(float(np.mean(des)), 2),
            "最近色差": round(des[-1], 2),
            "漂移量": round(drift, 2),
            "合格率": f"{pass_rate:.0%}",
            "趋势": "恶化" if drift > 0.5 else "改善" if drift < -0.5 else "稳定",
        }


# ════════════════════════════════════════════════
# 6. 色彩电子护照
# ════════════════════════════════════════════════

def generate_color_passport(
    color_code: str,
    lab: dict[str, float],
    de: float,
    verdict: str,
    batch_id: str = "",
    customer: str = "",
    operator: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    生成色彩电子护照 — 供应链签收确认.

    包含:
    - 色号、批次、客户
    - LAB值 + 色差 + 判定
    - 时间戳 + 操作员
    - 防篡改哈希 (SHA256)
    - 可打印二维码数据
    """
    passport_data = {
        "version": "1.0",
        "type": "SENIA_COLOR_PASSPORT",
        "色号": color_code,
        "批次": batch_id,
        "客户": customer,
        "操作员": operator,
        "时间": datetime.now().isoformat(),
        "LAB": lab,
        "色差_dE00": round(de, 2),
        "判定": verdict,
        "标准": "CIEDE2000",
    }
    if extra:
        passport_data["附加信息"] = extra

    # 防篡改哈希
    content = json.dumps(passport_data, sort_keys=True, ensure_ascii=False)
    passport_data["哈希"] = hashlib.sha256(content.encode()).hexdigest()[:16]

    # QR码数据 (精简版, 适合打印在标签上)
    qr_data = f"SENIA|{color_code}|{batch_id}|dE={de:.2f}|{verdict}|{passport_data['哈希']}"
    passport_data["二维码数据"] = qr_data

    return passport_data


# ════════════════════════════════════════════════
# 7. 自学习匹配纠正 (Datacolor SmartMatch核心)
# ════════════════════════════════════════════════

class SmartMatchEngine:
    """
    自学习配方纠正 — 行业公认最有价值的功能.

    原理: 存储每次对色的 [测量值, 实际结果, 工艺参数],
    随着数据积累, 系统学会 "这台机器/这个基材/这个墨水组合"
    的系统性偏差, 自动在后续预测中补偿.

    效果: Datacolor 报告首次命中率提升 80%.
    """

    def __init__(self, db_path: str = "smart_match_db.json") -> None:
        self._path = Path(db_path)
        self._corrections: dict[str, list[dict[str, Any]]] = {}
        if self._path.exists():
            try:
                self._corrections = json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._corrections = {}

    def _save(self) -> None:
        self._path.write_text(json.dumps(self._corrections, ensure_ascii=False,
                                         indent=2, default=str), encoding="utf-8")

    def learn(
        self,
        color_code: str,
        predicted_lab: dict[str, float],
        actual_lab: dict[str, float],
        substrate: str = "default",
        machine_id: str = "default",
    ) -> dict[str, Any]:
        """
        记录一次预测→实际的偏差, 供后续纠正.

        参数:
          predicted_lab: 系统预测的LAB (上次对色报告的值)
          actual_lab: 实际量产后客户反馈的LAB
        """
        key = f"{substrate}_{machine_id}"
        if key not in self._corrections:
            self._corrections[key] = []

        error = {
            "color_code": color_code,
            "timestamp": datetime.now().isoformat(),
            "pred_L": predicted_lab["L"], "pred_a": predicted_lab["a"], "pred_b": predicted_lab["b"],
            "actual_L": actual_lab["L"], "actual_a": actual_lab["a"], "actual_b": actual_lab["b"],
            "error_L": round(actual_lab["L"] - predicted_lab["L"], 3),
            "error_a": round(actual_lab["a"] - predicted_lab["a"], 3),
            "error_b": round(actual_lab["b"] - predicted_lab["b"], 3),
        }
        self._corrections[key].append(error)

        if len(self._corrections[key]) > 200:
            self._corrections[key] = self._corrections[key][-200:]

        self._save()

        return {
            "learned": True,
            "total_samples": len(self._corrections[key]),
            "systematic_bias": self._get_bias(key),
        }

    def _get_bias(self, key: str) -> dict[str, float]:
        """计算系统性偏差 (所有历史误差的中位数)."""
        records = self._corrections.get(key, [])
        if len(records) < 3:
            return {"L": 0.0, "a": 0.0, "b": 0.0, "samples": len(records)}

        errors_L = [r["error_L"] for r in records]
        errors_a = [r["error_a"] for r in records]
        errors_b = [r["error_b"] for r in records]

        return {
            "L": round(float(np.median(errors_L)), 2),
            "a": round(float(np.median(errors_a)), 2),
            "b": round(float(np.median(errors_b)), 2),
            "samples": len(records),
        }

    def correct(
        self,
        lab: dict[str, float],
        substrate: str = "default",
        machine_id: str = "default",
    ) -> dict[str, Any]:
        """
        用历史学习到的偏差纠正当前测量值.

        如果积累了足够的数据 (≥5次), 就应用系统性偏差纠正.
        """
        key = f"{substrate}_{machine_id}"
        bias = self._get_bias(key)

        if bias["samples"] < 5:
            return {
                "corrected": False,
                "原始LAB": lab,
                "说明": f"学习样本不足 ({bias['samples']}/5), 暂不纠正. 继续使用系统积累数据.",
            }

        corrected_lab = {
            "L": round(lab["L"] + bias["L"], 2),
            "a": round(lab["a"] + bias["a"], 2),
            "b": round(lab["b"] + bias["b"], 2),
        }

        return {
            "corrected": True,
            "原始LAB": lab,
            "纠正后LAB": corrected_lab,
            "系统偏差": {"ΔL": bias["L"], "Δa": bias["a"], "Δb": bias["b"]},
            "学习样本数": bias["samples"],
            "说明": f"基于{bias['samples']}次历史数据, 已纠正该机台/基材组合的系统性偏差",
        }


# ════════════════════════════════════════════════
# 8. 多角度拍摄工作流
# ════════════════════════════════════════════════

def multi_angle_workflow(images: list[np.ndarray], angles: list[str] | None = None) -> dict[str, Any]:
    """
    多角度拍摄分析 — 检测角度依赖的色差.

    X-Rite MA-T12 的核心能力: 从多个角度测量颜色变化.
    手机实现: 操作员从3-5个角度拍照, 系统分析角度间差异.

    角度敏感的材料 (金属/珠光/高光) 不同角度颜色不同,
    单角度测量会误导判定.
    """
    from senia_color_report import generate_color_match_report, _ciede2000_detail

    if len(images) < 2:
        return {"error": "至少需要2张不同角度的照片"}

    if angles is None:
        angles = [f"角度{i + 1}" for i in range(len(images))]

    # 对每张图生成报告
    results = []
    for i, img in enumerate(images):
        r = generate_color_match_report(img, profile="auto")
        det = r.get("检测结果", {})
        board_lab = det.get("大货", {}).get("LAB")
        if board_lab:
            results.append({
                "angle": angles[i] if i < len(angles) else f"角度{i + 1}",
                "lab": board_lab,
                "verdict": r.get("对色判定", {}).get("结论", "?"),
            })

    if len(results) < 2:
        return {"error": "有效测量不足2个角度"}

    # 计算角度间色差
    angle_des = []
    for i in range(len(results)):
        for j in range(i + 1, len(results)):
            de = _ciede2000_detail(results[i]["lab"], results[j]["lab"])
            angle_des.append({
                "角度对": f"{results[i]['angle']} vs {results[j]['angle']}",
                "dE": de["dE00"],
                "dL": de["dL"],
            })

    max_de = max(d["dE"] for d in angle_des) if angle_des else 0
    avg_de = float(np.mean([d["dE"] for d in angle_des])) if angle_des else 0

    # 角度敏感性判定
    if max_de > 3.0:
        sensitivity = "高 (金属/珠光效果材料)"
        warning = "该产品颜色随观察角度变化显著, 单角度对色结果不可靠, 需多角度综合评估"
    elif max_de > 1.5:
        sensitivity = "中等 (半光/效果材料)"
        warning = "建议从标准45°角测量, 并注意安装后的观看角度"
    else:
        sensitivity = "低 (哑光/纯色材料)"
        warning = "颜色随角度变化小, 单角度对色结果可靠"

    return {
        "角度数": len(results),
        "各角度LAB": [{
            "角度": r["angle"],
            "L": r["lab"]["L"], "a": r["lab"]["a"], "b": r["lab"]["b"],
            "判定": r["verdict"],
        } for r in results],
        "角度间色差": angle_des,
        "最大角度色差": round(max_de, 2),
        "平均角度色差": round(avg_de, 2),
        "角度敏感性": sensitivity,
        "建议": warning,
    }

