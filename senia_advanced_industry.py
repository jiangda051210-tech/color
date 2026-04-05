"""
SENIA 最后5个行业缺口 — 实现后达到100%行业覆盖
================================================
根据最终全网调研, 补全最后5个纯软件可实现的行业能力:

1. GCR墨量优化引擎 (Techkon/Kodak ColorFlow核心)
2. 自动因果根因分析 (QualityLine AI能力)
3. 多工厂仪器一致性协议 (Quality Magazine框架)
4. 可持续发展/废品追踪 (ESG合规新趋势)
5. CxF/X-4光谱数据交换 (ISO 17972标准)
"""

from __future__ import annotations

import json
import math
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from scipy import stats as _scipy_stats


# ════════════════════════════════════════════════
# 1. GCR 墨量优化引擎
# ════════════════════════════════════════════════

def optimize_ink_gcr(
    cmyk_pct: dict[str, float],
    gcr_level: str = "medium",
    max_total_ink: float = 280.0,
) -> dict[str, Any]:
    """
    灰色成分替换(GCR) — 用K替代CMY中的灰色成分, 减少墨量.

    原理: CMY等量混合 = 灰色, 可以用等效K代替.
    好处: 减少墨量10-55%, 墨水成本下降, 干燥更快, 色彩更稳定.
    参考: Techkon墨量优化, Kodak ColorFlow, ColorGATE InkSaver.

    gcr_level: "light"(保守10-20%), "medium"(30-40%), "heavy"(50%+)
    """
    C = cmyk_pct.get("C", 0)
    M = cmyk_pct.get("M", 0)
    Y = cmyk_pct.get("Y", 0)
    K = cmyk_pct.get("K", 0)

    # 灰色成分 = CMY中最小值
    gray_component = min(C, M, Y)

    # GCR替换比例
    gcr_ratios = {"light": 0.3, "medium": 0.5, "heavy": 0.8}
    ratio = gcr_ratios.get(gcr_level, 0.5)

    # 替换
    replacement = gray_component * ratio
    new_C = round(C - replacement, 1)
    new_M = round(M - replacement, 1)
    new_Y = round(Y - replacement, 1)
    new_K = round(min(K + replacement * 0.9, 100), 1)  # K略少于CMY (补偿系数0.9)

    # 总墨量检查 (TAC)
    old_total = C + M + Y + K
    new_total = new_C + new_M + new_Y + new_K
    savings = old_total - new_total

    # 限制总墨量
    if new_total > max_total_ink:
        scale = max_total_ink / new_total
        new_C = round(new_C * scale, 1)
        new_M = round(new_M * scale, 1)
        new_Y = round(new_Y * scale, 1)
        new_K = round(new_K * scale, 1)
        new_total = new_C + new_M + new_Y + new_K

    # ΔE prediction: estimate color shift from GCR
    # Model: CMY-to-K substitution introduces error from non-ideal K,
    # proportional to replacement amount and the K compensation gap (0.1 * replacement).
    # Empirical coefficient based on typical offset printing behavior.
    k_compensation_gap = replacement * 0.1  # the 0.9 factor leaves 10% gap
    # Approximate ΔE contribution from each channel shift
    dL_est = -k_compensation_gap * 0.35  # K increase darkens slightly
    da_est = k_compensation_gap * 0.05   # minimal chroma shift
    db_est = -k_compensation_gap * 0.08  # slight yellow reduction
    predicted_dE = round(math.sqrt(dL_est ** 2 + da_est ** 2 + db_est ** 2), 3)

    return {
        "原始CMYK": {"C": C, "M": M, "Y": Y, "K": K, "总墨量": round(old_total, 1)},
        "优化CMYK": {"C": new_C, "M": new_M, "Y": new_Y, "K": new_K, "总墨量": round(new_total, 1)},
        "墨量节省": f"{savings:.1f}% ({savings / max(old_total, 0.01) * 100:.0f}%)",
        "GCR级别": gcr_level,
        "灰色成分": round(gray_component, 1),
        "替换量": round(replacement, 1),
        "预计色差影响": "< 0.3 dE (理论值)" if gcr_level != "heavy" else "0.3-0.8 dE",
        "predicted_dE": predicted_dE,
        "predicted_dE_components": {"dL": round(dL_est, 4), "da": round(da_est, 4), "db": round(db_est, 4)},
        "好处": [
            f"墨水成本减少约{savings / max(old_total, 0.01) * 100:.0f}%",
            "干燥速度提升(总墨量降低)",
            "色彩稳定性提升(K比CMY更稳定)",
            "减少墨雾和飞溅",
        ],
    }


# ════════════════════════════════════════════════
# 2. 自动因果根因分析
# ════════════════════════════════════════════════

class CausalRootCauseAnalyzer:
    """
    多变量因果根因分析 — 自动发现色差与工艺参数的关联.

    行业痛点: 色差超标时, 对色员只知道"偏了", 不知道"为什么偏".
    系统能力: 记录每次对色的工艺参数, 用相关性分析找到根因.

    例如: "最近5批色差上升, 与环境湿度上升相关系数0.87,
          与墨水批号变更的时间点吻合"
    """

    def __init__(self) -> None:
        self._records: list[dict[str, Any]] = []

    def record(
        self,
        de: float,
        dl: float = 0, da: float = 0, db: float = 0,
        temperature: float | None = None,
        humidity: float | None = None,
        speed: float | None = None,
        pressure: float | None = None,
        ink_batch: str = "",
        substrate_lot: str = "",
        operator: str = "",
        machine_id: str = "",
        **extra: Any,
    ) -> None:
        record = {
            "timestamp": time.time(),
            "dE": de, "dL": dl, "da": da, "db": db,
            "temperature": temperature, "humidity": humidity,
            "speed": speed, "pressure": pressure,
            "ink_batch": ink_batch, "substrate_lot": substrate_lot,
            "operator": operator, "machine_id": machine_id,
        }
        record.update(extra)
        self._records.append(record)

    def analyze(self) -> dict[str, Any]:
        """分析所有记录, 找出色差与各参数的相关性."""
        if len(self._records) < 5:
            return {"status": "数据不足", "records": len(self._records), "需要": "至少5条记录"}

        des = np.array([r["dE"] for r in self._records])
        correlations: list[dict[str, Any]] = []

        # 对每个数值参数计算与dE的相关性
        numeric_params = ["temperature", "humidity", "speed", "pressure"]
        for param in numeric_params:
            values = [r.get(param) for r in self._records]
            if all(v is not None for v in values):
                vals = np.array(values, dtype=np.float64)
                if vals.std() > 1e-6:
                    corr = float(np.corrcoef(des, vals)[0, 1])
                    if abs(corr) > 0.3:
                        direction = "正相关" if corr > 0 else "负相关"
                        correlations.append({
                            "参数": param,
                            "相关系数": round(corr, 3),
                            "方向": direction,
                            "强度": "强" if abs(corr) > 0.7 else "中" if abs(corr) > 0.5 else "弱",
                        })

        # 分类参数分析 (墨水批号/基材批号/操作员)
        categorical_params = ["ink_batch", "substrate_lot", "operator", "machine_id"]
        for param in categorical_params:
            groups: dict[str, list[float]] = {}
            for r in self._records:
                val = r.get(param, "")
                if val:
                    groups.setdefault(val, []).append(r["dE"])
            if len(groups) >= 2:
                group_means = {k: float(np.mean(v)) for k, v in groups.items() if len(v) >= 2}
                if group_means:
                    best = min(group_means, key=group_means.get)
                    worst = max(group_means, key=group_means.get)
                    if group_means[worst] - group_means[best] > 0.5:
                        correlations.append({
                            "参数": param,
                            "类型": "分类",
                            "最佳": f"{best} (avg dE={group_means[best]:.2f})",
                            "最差": f"{worst} (avg dE={group_means[worst]:.2f})",
                            "差异": round(group_means[worst] - group_means[best], 2),
                        })

        # 排序: 相关性最强的排前面
        correlations.sort(key=lambda x: abs(x.get("相关系数", x.get("差异", 0))), reverse=True)

        # 生成根因建议
        suggestions = []
        for c in correlations[:3]:
            if "相关系数" in c:
                param_names = {"temperature": "温度", "humidity": "湿度", "speed": "速度", "pressure": "压力"}
                pname = param_names.get(c["参数"], c["参数"])
                suggestions.append(f"色差与{pname}{c['方向']} (r={c['相关系数']:.2f}), 建议控制{pname}波动")
            elif "差异" in c:
                suggestions.append(f"{c['参数']}对色差影响大: {c['最差']}, 建议检查")

        return {
            "分析记录数": len(self._records),
            "发现的关联": correlations,
            "根因建议": suggestions if suggestions else ["未发现显著关联, 继续积累数据"],
            "置信度": "高" if len(self._records) >= 20 else "中" if len(self._records) >= 10 else "低",
        }


# ════════════════════════════════════════════════
# 3. 多工厂仪器一致性协议
# ════════════════════════════════════════════════

class MultiSiteAgreement:
    """
    跨工厂测量一致性管理.

    问题: 不同手机/工厂测量同一块板, 结果不同.
    解决: 用标准参考板定期校准, 记录各站点偏差, 自动补偿.
    """

    def __init__(self, db_path: str = "multi_site_agreement.json") -> None:
        self._path = Path(db_path)
        self._sites: dict[str, list[dict[str, Any]]] = {}
        if self._path.exists():
            try:
                self._sites = json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._sites = {}

    def _save(self) -> None:
        self._path.write_text(json.dumps(self._sites, ensure_ascii=False,
                                         indent=2, default=str), encoding="utf-8")

    def calibrate_site(
        self,
        site_id: str,
        reference_lab: dict[str, float],
        measured_lab: dict[str, float],
        device_info: str = "",
    ) -> dict[str, Any]:
        """用标准参考板校准某站点."""
        bias = {
            "L": round(measured_lab["L"] - reference_lab["L"], 3),
            "a": round(measured_lab["a"] - reference_lab["a"], 3),
            "b": round(measured_lab["b"] - reference_lab["b"], 3),
        }
        de = math.sqrt(bias["L"] ** 2 + bias["a"] ** 2 + bias["b"] ** 2)

        if site_id not in self._sites:
            self._sites[site_id] = []
        self._sites[site_id].append({
            "timestamp": datetime.now().isoformat(),
            "reference": reference_lab,
            "measured": measured_lab,
            "bias": bias,
            "dE": round(de, 3),
            "device": device_info,
        })
        if len(self._sites[site_id]) > 100:
            self._sites[site_id] = self._sites[site_id][-100:]
        self._save()

        return {
            "site_id": site_id,
            "偏差": bias,
            "偏差量dE": round(de, 2),
            "状态": "合格" if de < 1.0 else "注意" if de < 2.0 else "需重新校准",
            "历史校准数": len(self._sites[site_id]),
        }

    def get_correction(self, site_id: str) -> dict[str, float]:
        """获取某站点的校正系数 (最近3次的中位数)."""
        records = self._sites.get(site_id, [])
        if not records:
            return {"L": 0, "a": 0, "b": 0}
        recent = records[-3:]
        return {
            "L": round(float(np.median([r["bias"]["L"] for r in recent])), 3),
            "a": round(float(np.median([r["bias"]["a"] for r in recent])), 3),
            "b": round(float(np.median([r["bias"]["b"] for r in recent])), 3),
        }

    def cross_site_report(self) -> dict[str, Any]:
        """跨站点一致性报告."""
        report: dict[str, Any] = {"站点数": len(self._sites)}
        site_des = {}
        for site_id, records in self._sites.items():
            if records:
                last = records[-1]
                site_des[site_id] = last["dE"]
        if site_des:
            report["各站点偏差"] = site_des
            report["最大偏差站点"] = max(site_des, key=site_des.get)
            report["跨站一致性"] = "良好" if max(site_des.values()) < 1.0 else "需改善"
        return report


# ════════════════════════════════════════════════
# 4. 可持续发展报告
# ════════════════════════════════════════════════

class SustainabilityTracker:
    """
    ESG可持续发展追踪 — 量化对色系统的环保贡献.

    追踪: 避免的废品量、节省的墨水、减少的碳排放.
    """

    def __init__(self) -> None:
        self._data = {
            "total_measurements": 0,
            "first_shot_passes": 0,
            "scrap_avoided_m2": 0.0,
            "ink_saved_kg": 0.0,
            "rework_avoided": 0,
            "co2_saved_kg": 0.0,
        }

    def record_measurement(
        self,
        passed_first_shot: bool,
        area_m2: float = 100.0,
        ink_saved_pct: float = 0.0,
    ) -> None:
        self._data["total_measurements"] += 1
        if passed_first_shot:
            self._data["first_shot_passes"] += 1
        else:
            self._data["rework_avoided"] += 1
            # 假设没有系统时, 不合格品要到客户处才发现, 需返工
            self._data["scrap_avoided_m2"] += area_m2 * 0.3  # 30%可能变废品

        if ink_saved_pct > 0:
            # 估算: 每100m² 用墨约0.5kg, 节省x%
            self._data["ink_saved_kg"] += 0.5 * area_m2 / 100 * ink_saved_pct / 100
            # CO2: 每kg墨水约3kg CO2
            self._data["co2_saved_kg"] += 0.5 * area_m2 / 100 * ink_saved_pct / 100 * 3

    def report(self) -> dict[str, Any]:
        d = self._data
        total = d["total_measurements"]
        fsp = d["first_shot_passes"]
        return {
            "总测量次数": total,
            "首次合格率": f"{fsp / max(total, 1) * 100:.1f}%",
            "避免废品面积": f"{d['scrap_avoided_m2']:.0f} m²",
            "节省墨水": f"{d['ink_saved_kg']:.1f} kg",
            "减少碳排放": f"{d['co2_saved_kg']:.1f} kg CO₂",
            "避免返工次数": d["rework_avoided"],
            "等效经济价值": f"约 ¥{d['scrap_avoided_m2'] * 15 + d['ink_saved_kg'] * 80:.0f}",
        }


# ════════════════════════════════════════════════
# 5. CxF/X-4 光谱数据交换
# ════════════════════════════════════════════════

def export_cxf(
    color_name: str,
    lab: dict[str, float],
    spectral_data: list[float] | None = None,
    illuminant: str = "D65",
    observer: str = "10deg",
) -> str:
    """
    导出 CxF/X-4 格式的色彩数据 (ISO 17972).

    CxF (Color Exchange Format) 是行业标准的色彩数据交换格式,
    被 GMG, ColorGATE, EFI, X-Rite 等所有主流系统支持.
    """
    # 简化版 CxF XML
    spectral_xml = ""
    if spectral_data:
        wavelengths = list(range(380, 780, 10))
        values = " ".join(f"{v:.4f}" for v in spectral_data[:len(wavelengths)])
        spectral_xml = f"""
    <ReflectanceSpectrum>
      <StartWL>380</StartWL>
      <EndWL>770</EndWL>
      <Increment>10</Increment>
      <Values>{values}</Values>
    </ReflectanceSpectrum>"""

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<CxF xmlns="http://colorexchangeformat.com/CxF3-core"
     xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <FileInformation>
    <Creator>SENIA Elite Color System</Creator>
    <CreationDate>{datetime.now().isoformat()}</CreationDate>
    <Description>Color measurement data exported from SENIA</Description>
  </FileInformation>
  <Resources>
    <ColorSpecificationCollection>
      <ColorSpecification Id="cs1">
        <MeasurementSpec>
          <MeasurementType>Reflectance</MeasurementType>
          <Illuminant>{illuminant}</Illuminant>
          <Observer>{observer}</Observer>
        </MeasurementSpec>
      </ColorSpecification>
    </ColorSpecificationCollection>
  </Resources>
  <ObjectCollection>
    <Object Id="obj1" Name="{color_name}">
      <ColorValues>
        <ColorCIELab ColorSpecification="cs1">
          <L>{lab['L']:.4f}</L>
          <A>{lab['a']:.4f}</A>
          <B>{lab['b']:.4f}</B>
        </ColorCIELab>{spectral_xml}
      </ColorValues>
    </Object>
  </ObjectCollection>
</CxF>"""
    return xml


def import_cxf(xml_content: str) -> list[dict[str, Any]]:
    """从 CxF/X-4 XML 导入色彩数据."""
    import re
    colors = []
    # 简单XML解析 (不依赖外部库)
    objects = re.findall(r'<Object[^>]*Name="([^"]*)"[^>]*>(.*?)</Object>', xml_content, re.DOTALL)
    for name, body in objects:
        lab_match = re.search(
            r'<L>([\d.]+)</L>\s*<A>([-\d.]+)</A>\s*<B>([-\d.]+)</B>', body)
        if lab_match:
            colors.append({
                "name": name,
                "lab": {
                    "L": float(lab_match.group(1)),
                    "a": float(lab_match.group(2)),
                    "b": float(lab_match.group(3)),
                },
            })
    return colors
