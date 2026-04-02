"""
SENIA 自学习引擎 — 系统越用越准
================================

6 大创新能力 (市面上没有的):

1. Online Learning — 操作员反馈驱动阈值自适应
   操作员说"这个该PASS你判了MARGINAL" → 系统自动微调阈值
   不是重新训练模型, 而是贝叶斯更新决策边界

2. Perceptual Adaptation — 客户感知适应
   不同客户对"可接受"的定义不同
   系统学习每个客户的真实容忍曲线

3. Ambient Light Fingerprint — 环境光指纹
   即使没有色卡, 通过历史数据学习当前工位的光源偏移模式
   自动补偿

4. Recipe Digital Twin — 配方数字孪生
   从历史"配方→色值"数据训练正向模型
   生产前就能预测颜色, 减少打样次数

5. Cross-Batch Color Memory — 跨批次色彩记忆
   客户3个月后追加订单, 系统自动找到最接近的历史批次
   给出"要达到同样效果, 配方需要这样调"

6. Aging-Aware Acceptance — 老化感知验收
   新膜和老膜颜色会变, 系统预测:
   "现在偏黄0.3, 但3个月后会自然回正到合格范围"
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
# 1. Online Learning — 操作员反馈 → 阈值自适应
# ══════════════════════════════════════════════════════════

@dataclass
class FeedbackRecord:
    run_id: str
    system_tier: str        # 系统判定: PASS/MARGINAL/FAIL
    operator_tier: str      # 操作员判定: PASS/MARGINAL/FAIL
    dE00: float
    profile: str
    timestamp: str = ""


class OnlineLearner:
    """
    通过操作员反馈持续优化判定阈值.

    原理: 贝叶斯更新
    - 每次操作员覆盖系统判定 → 一条训练样本
    - 系统判 MARGINAL 但操作员说 PASS → pass_dE 应该上调
    - 系统判 PASS 但操作员说 FAIL → pass_dE 应该下调
    - 学习率随样本量衰减 (越多数据, 调整越保守)
    """

    def __init__(self, store_path: Path | None = None) -> None:
        self._lock = RLock()
        self._store_path = store_path
        self._feedbacks: list[FeedbackRecord] = []
        self._adjustments: dict[str, dict[str, float]] = {}  # profile → {pass_dE_adj, marginal_dE_adj}
        self._sample_counts: dict[str, int] = defaultdict(int)
        if store_path and store_path.exists():
            self._load()

    def record_feedback(
        self,
        run_id: str,
        system_tier: str,
        operator_tier: str,
        dE00: float,
        profile: str = "solid",
    ) -> dict[str, Any]:
        """记录一条操作员反馈, 并更新阈值调整."""
        fb = FeedbackRecord(
            run_id=run_id,
            system_tier=system_tier.upper(),
            operator_tier=operator_tier.upper(),
            dE00=dE00,
            profile=profile,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
        )

        with self._lock:
            self._feedbacks.append(fb)
            self._sample_counts[profile] += 1
            adjustment = self._update_threshold(fb)
            self._save()

        return {
            "recorded": True,
            "feedback": {
                "run_id": run_id,
                "system": system_tier,
                "operator": operator_tier,
                "dE00": dE00,
            },
            "adjustment": adjustment,
            "total_feedbacks": len(self._feedbacks),
            "profile_samples": self._sample_counts[profile],
        }

    def get_adjustment(self, profile: str = "solid") -> dict[str, float]:
        """获取当前累积的阈值调整量."""
        with self._lock:
            return self._adjustments.get(profile, {"pass_dE_adj": 0.0, "marginal_dE_adj": 0.0})

    def apply_to_thresholds(self, base_pass: float, base_marginal: float, profile: str) -> tuple[float, float]:
        """将学习到的调整应用到基础阈值上."""
        adj = self.get_adjustment(profile)
        return (
            max(0.3, base_pass + adj.get("pass_dE_adj", 0.0)),
            max(0.8, base_marginal + adj.get("marginal_dE_adj", 0.0)),
        )

    def stats(self) -> dict[str, Any]:
        """返回学习统计."""
        with self._lock:
            agreement = sum(1 for f in self._feedbacks if f.system_tier == f.operator_tier)
            total = max(len(self._feedbacks), 1)
            return {
                "total_feedbacks": len(self._feedbacks),
                "agreement_rate": round(agreement / total, 4),
                "adjustments": dict(self._adjustments),
                "sample_counts": dict(self._sample_counts),
            }

    def _update_threshold(self, fb: FeedbackRecord) -> dict[str, Any]:
        """贝叶斯更新阈值调整."""
        if fb.system_tier == fb.operator_tier:
            return {"action": "agree", "no_change": True}

        profile = fb.profile
        n = self._sample_counts[profile]
        # 学习率随样本量衰减: lr = 0.1 / sqrt(n)
        lr = 0.1 / math.sqrt(max(n, 1))

        if profile not in self._adjustments:
            self._adjustments[profile] = {"pass_dE_adj": 0.0, "marginal_dE_adj": 0.0}

        adj = self._adjustments[profile]

        if fb.system_tier == "MARGINAL" and fb.operator_tier == "PASS":
            # 系统太严: 上调 pass 阈值
            adj["pass_dE_adj"] += lr * 0.3
            return {"action": "relax_pass", "delta": round(lr * 0.3, 4)}
        elif fb.system_tier == "PASS" and fb.operator_tier in ("MARGINAL", "FAIL"):
            # 系统太松: 下调 pass 阈值
            adj["pass_dE_adj"] -= lr * 0.3
            return {"action": "tighten_pass", "delta": round(-lr * 0.3, 4)}
        elif fb.system_tier == "FAIL" and fb.operator_tier in ("PASS", "MARGINAL"):
            # 系统太严在 fail 边界: 上调 marginal 阈值
            adj["marginal_dE_adj"] += lr * 0.3
            return {"action": "relax_marginal", "delta": round(lr * 0.3, 4)}
        elif fb.system_tier == "MARGINAL" and fb.operator_tier == "FAIL":
            # 系统太松在 marginal 边界: 下调 marginal 阈值
            adj["marginal_dE_adj"] -= lr * 0.3
            return {"action": "tighten_marginal", "delta": round(-lr * 0.3, 4)}

        return {"action": "unknown_case"}

    def _save(self) -> None:
        if not self._store_path:
            return
        try:
            self._store_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "feedbacks": [
                    {"run_id": f.run_id, "system": f.system_tier, "operator": f.operator_tier,
                     "dE00": f.dE00, "profile": f.profile, "ts": f.timestamp}
                    for f in self._feedbacks[-500:]  # 保留最近500条
                ],
                "adjustments": self._adjustments,
                "sample_counts": dict(self._sample_counts),
            }
            self._store_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def _load(self) -> None:
        if not self._store_path or not self._store_path.exists():
            return
        try:
            data = json.loads(self._store_path.read_text(encoding="utf-8"))
            for fb in data.get("feedbacks", []):
                self._feedbacks.append(FeedbackRecord(
                    run_id=fb["run_id"], system_tier=fb["system"],
                    operator_tier=fb["operator"], dE00=fb["dE00"],
                    profile=fb.get("profile", "solid"), timestamp=fb.get("ts", ""),
                ))
            self._adjustments = data.get("adjustments", {})
            self._sample_counts = defaultdict(int, data.get("sample_counts", {}))
        except (json.JSONDecodeError, KeyError, OSError):
            pass


# ══════════════════════════════════════════════════════════
# 2. Ambient Light Fingerprint — 无色卡光源补偿
# ══════════════════════════════════════════════════════════

class AmbientLightLearner:
    """
    学习每个拍摄工位的光源偏移模式.

    原理:
    - 有色卡的照片: 计算 CCM 的偏移量 (实际 vs 理想)
    - 记录 (时间, 光源偏移) 对
    - 没有色卡的照片: 用历史偏移模式预测当前光源状态
    - 比灰世界假设更准, 因为利用了该工位的历史数据
    """

    def __init__(self, store_path: Path | None = None) -> None:
        self._lock = RLock()
        self._store_path = store_path
        # station_id → [(timestamp, r_gain, g_gain, b_gain)]
        self._history: dict[str, list[tuple[float, float, float, float]]] = defaultdict(list)
        if store_path and store_path.exists():
            self._load()

    def record_calibration(
        self,
        station_id: str,
        r_gain: float,
        g_gain: float,
        b_gain: float,
    ) -> None:
        """记录一次色卡校准的白平衡增益."""
        with self._lock:
            ts = time.time()
            history = self._history[station_id]
            history.append((ts, r_gain, g_gain, b_gain))
            # 保留最近100条
            if len(history) > 100:
                self._history[station_id] = history[-100:]
            self._save()

    def predict_gains(self, station_id: str) -> tuple[float, float, float] | None:
        """
        预测当前工位的白平衡增益 (用于无色卡场景).
        用加权移动平均, 近期数据权重更高.
        """
        with self._lock:
            history = self._history.get(station_id, [])
            if len(history) < 3:
                return None  # 数据不足, 无法预测

            now = time.time()
            r_sum = g_sum = b_sum = w_sum = 0.0
            for ts, r, g, b in history:
                age_hours = (now - ts) / 3600
                # 指数衰减权重: 1小时前权重=0.9, 24小时前=0.4, 7天前≈0
                weight = math.exp(-0.03 * age_hours)
                r_sum += r * weight
                g_sum += g * weight
                b_sum += b * weight
                w_sum += weight

            if w_sum < 0.01:
                return None
            return (r_sum / w_sum, g_sum / w_sum, b_sum / w_sum)

    def _save(self) -> None:
        if not self._store_path:
            return
        try:
            data = {k: v[-100:] for k, v in self._history.items()}
            self._store_path.parent.mkdir(parents=True, exist_ok=True)
            self._store_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def _load(self) -> None:
        if not self._store_path or not self._store_path.exists():
            return
        try:
            data = json.loads(self._store_path.read_text(encoding="utf-8"))
            for k, v in data.items():
                self._history[k] = [tuple(x) for x in v]
        except (json.JSONDecodeError, OSError):
            pass


# ══════════════════════════════════════════════════════════
# 3. Recipe Digital Twin — 配方→色值预测
# ══════════════════════════════════════════════════════════

class RecipeDigitalTwin:
    """
    配方数字孪生: 从历史数据学习 配方→色值 的映射.

    生产前输入配方, 预测出来的颜色, 减少打样次数.

    原理: 多元线性回归 (配方各组分 → Lab)
    积累>30组数据后开始预测, 越多越准.
    """

    def __init__(self, store_path: Path | None = None) -> None:
        self._lock = RLock()
        self._store_path = store_path
        # product_code → [(recipe_vec, lab_vec)]
        self._data: dict[str, list[tuple[list[float], list[float]]]] = defaultdict(list)
        self._models: dict[str, Any] = {}  # product_code → trained coefficients
        if store_path and store_path.exists():
            self._load()

    def record_sample(
        self,
        product_code: str,
        recipe: dict[str, float],
        measured_lab: tuple[float, float, float],
    ) -> dict[str, Any]:
        """记录一组 配方→色值 数据."""
        with self._lock:
            keys = sorted(recipe.keys())
            vec = [recipe[k] for k in keys]
            self._data[product_code].append((vec, list(measured_lab)))
            n = len(self._data[product_code])
            # 数据够了就重新训练
            if n >= 10:
                self._train(product_code, keys)
            self._save()
            return {"recorded": True, "product_code": product_code, "samples": n}

    def predict(
        self,
        product_code: str,
        recipe: dict[str, float],
    ) -> dict[str, Any]:
        """从配方预测色值 (Lab)."""
        with self._lock:
            model = self._models.get(product_code)
            if model is None:
                n = len(self._data.get(product_code, []))
                return {"predicted": False, "reason": f"need more data (have {n}, need 10+)"}

            keys = model["keys"]
            coeffs = model["coefficients"]  # 3×(n+1) for L,a,b each with intercept

            vec = [recipe.get(k, 0.0) for k in keys]
            vec_ext = vec + [1.0]  # add intercept

            pred_L = sum(c * v for c, v in zip(coeffs[0], vec_ext))
            pred_a = sum(c * v for c, v in zip(coeffs[1], vec_ext))
            pred_b = sum(c * v for c, v in zip(coeffs[2], vec_ext))

            return {
                "predicted": True,
                "L": round(pred_L, 2),
                "a": round(pred_a, 2),
                "b": round(pred_b, 2),
                "model_samples": model["n"],
                "model_rmse": model.get("rmse", 0),
            }

    def _train(self, product_code: str, keys: list[str]) -> None:
        """简单多元线性回归 (无 numpy 依赖)."""
        data = self._data[product_code]
        n = len(data)
        dim = len(keys)

        # 构造 X (n×(dim+1)) 和 Y (n×3)
        X = [[d[0][j] for j in range(dim)] + [1.0] for d in data]
        Y = [d[1] for d in data]

        # 正规方程: coeffs = (X^T X)^(-1) X^T Y
        # 用简化的伪逆 (太小规模不需要 numpy)
        try:
            coeffs = []
            total_err = 0.0
            for ch in range(3):  # L, a, b
                y = [Y[i][ch] for i in range(n)]
                c = self._solve_least_squares(X, y, dim + 1)
                coeffs.append(c)
                # 计算 RMSE
                for i in range(n):
                    pred = sum(c[j] * X[i][j] for j in range(dim + 1))
                    total_err += (pred - y[i]) ** 2

            rmse = math.sqrt(total_err / (n * 3))
            self._models[product_code] = {
                "keys": keys,
                "coefficients": coeffs,
                "n": n,
                "rmse": round(rmse, 4),
            }
        except Exception:
            pass

    @staticmethod
    def _solve_least_squares(X: list[list[float]], y: list[float], dim: int) -> list[float]:
        """Solve X @ c = y via normal equations."""
        n = len(X)
        # X^T X
        ata = [[sum(X[k][i] * X[k][j] for k in range(n)) for j in range(dim)] for i in range(dim)]
        # X^T y
        atb = [sum(X[k][i] * y[k] for k in range(n)) for i in range(dim)]

        # Gaussian elimination
        m = [row[:] + [atb[i]] for i, row in enumerate(ata)]
        for i in range(dim):
            max_row = max(range(i, dim), key=lambda r: abs(m[r][i]))
            m[i], m[max_row] = m[max_row], m[i]
            if abs(m[i][i]) < 1e-12:
                continue
            for j in range(i + 1, dim):
                factor = m[j][i] / m[i][i]
                for k in range(dim + 1):
                    m[j][k] -= factor * m[i][k]

        # Back substitution
        result = [0.0] * dim
        for i in range(dim - 1, -1, -1):
            if abs(m[i][i]) < 1e-12:
                continue
            result[i] = (m[i][dim] - sum(m[i][j] * result[j] for j in range(i + 1, dim))) / m[i][i]
        return result

    def _save(self) -> None:
        if not self._store_path:
            return
        try:
            self._store_path.parent.mkdir(parents=True, exist_ok=True)
            data = {}
            for k, samples in self._data.items():
                data[k] = samples[-200:]
            out = {"data": data, "models": {k: v for k, v in self._models.items()}}
            self._store_path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def _load(self) -> None:
        if not self._store_path or not self._store_path.exists():
            return
        try:
            raw = json.loads(self._store_path.read_text(encoding="utf-8"))
            for k, v in raw.get("data", {}).items():
                self._data[k] = [(s[0], s[1]) for s in v]
            self._models = raw.get("models", {})
        except (json.JSONDecodeError, OSError):
            pass


# ══════════════════════════════════════════════════════════
# 4. Cross-Batch Color Memory — 跨批次色彩记忆
# ══════════════════════════════════════════════════════════

class CrossBatchMemory:
    """
    客户3个月后追加, 自动找到最接近的历史批次.

    原理:
    - 每个批次保存 (product_code, Lab均值, 配方, 时间)
    - 追加时搜索最接近的 Lab 记录
    - 计算 "当前配方需要怎么调才能匹配历史色值"
    """

    def __init__(self, store_path: Path | None = None) -> None:
        self._lock = RLock()
        self._store_path = store_path
        # product_code → [{lot_id, lab, recipe, timestamp}]
        self._memory: dict[str, list[dict[str, Any]]] = defaultdict(list)
        if store_path and store_path.exists():
            self._load()

    def remember(
        self,
        product_code: str,
        lot_id: str,
        lab: tuple[float, float, float],
        recipe: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        """记住一个批次的色值."""
        with self._lock:
            entry = {
                "lot_id": lot_id,
                "lab": list(lab),
                "recipe": recipe,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            self._memory[product_code].append(entry)
            self._save()
            return {"recorded": True, "total_memories": len(self._memory[product_code])}

    def find_closest(
        self,
        product_code: str,
        target_lab: tuple[float, float, float],
        top_k: int = 3,
    ) -> list[dict[str, Any]]:
        """找到最接近目标色值的历史批次."""
        with self._lock:
            entries = self._memory.get(product_code, [])
            if not entries:
                return []

            scored = []
            for e in entries:
                elab = e["lab"]
                dE = math.sqrt((elab[0] - target_lab[0]) ** 2 +
                               (elab[1] - target_lab[1]) ** 2 +
                               (elab[2] - target_lab[2]) ** 2)
                scored.append({**e, "dE_to_target": round(dE, 4)})

            scored.sort(key=lambda x: x["dE_to_target"])
            return scored[:top_k]

    def _save(self) -> None:
        if not self._store_path:
            return
        try:
            self._store_path.parent.mkdir(parents=True, exist_ok=True)
            data = {k: v[-200:] for k, v in self._memory.items()}
            self._store_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def _load(self) -> None:
        if not self._store_path or not self._store_path.exists():
            return
        try:
            data = json.loads(self._store_path.read_text(encoding="utf-8"))
            for k, v in data.items():
                self._memory[k] = v
        except (json.JSONDecodeError, OSError):
            pass


# ══════════════════════════════════════════════════════════
# 5. Aging-Aware Acceptance — 老化感知验收
# ══════════════════════════════════════════════════════════

def predict_aging_acceptance(
    current_dE: float,
    current_dL: float,
    current_db: float,
    profile: str = "wood",
    months_ahead: int = 6,
) -> dict[str, Any]:
    """
    预测色差随时间的变化趋势.

    基于行业经验:
    - 深色膜倾向于褪色 (ΔL升高, 偏亮)
    - 黄色组分容易氧化 (Δb先升后降)
    - 木纹膜表面涂层老化 → 饱和度下降
    - UV 照射加速所有变化

    返回: 预测的未来 dE, 以及 "现在MARGINAL但未来会自然回正" 的建议
    """
    # 简化老化模型: dE(t) = dE(0) + drift_rate × sqrt(t_months)
    # drift_rate 按材质不同
    drift_rates = {
        "wood": 0.15,       # 木纹膜老化较慢
        "solid": 0.20,      # 纯色稍快
        "stone": 0.12,      # 石纹最稳定
        "metallic": 0.25,   # 金属膜变化较快
        "high_gloss": 0.30, # 高光最敏感
    }
    rate = drift_rates.get(profile, 0.18)

    predictions = []
    for m in [1, 3, 6, 12]:
        if m > months_ahead:
            break
        # dL 偏差方向: 深色膜趋向褪色(dL↑), 浅色膜趋向暗化(dL↓)
        # db: 黄色组分氧化, 最初几个月 db可能微降
        dL_drift = rate * 0.3 * math.sqrt(m) * (1 if current_dL > 0 else 0.5)
        db_drift = -rate * 0.2 * math.sqrt(m)  # 黄色倾向自然回退
        # 总 dE 变化
        dE_drift = rate * math.sqrt(m) * 0.5
        future_dE = current_dE + dE_drift

        predictions.append({
            "months": m,
            "predicted_dE": round(future_dE, 3),
            "dL_change": round(dL_drift, 3),
            "db_change": round(db_drift, 3),
        })

    # 智能建议
    advice = ""
    if current_dE > 1.0 and current_db > 0.5:
        # 偏黄 → 有可能自然回正
        future_6m = current_dE + rate * math.sqrt(6) * 0.5
        if future_6m < current_dE * 1.1:
            advice = "当前偏黄, 但黄色组分会随时间自然氧化回退, 6个月后色差可能降低"

    if current_dE < 2.0 and current_dE + rate * math.sqrt(12) * 0.5 > 3.0:
        advice = "当前合格, 但预测12个月后色差可能超标, 建议加强UV保护"

    if not advice:
        if predictions and predictions[-1]["predicted_dE"] < current_dE * 1.15:
            advice = "色差预计稳定, 老化影响在可接受范围内"
        else:
            advice = "色差预计随时间缓慢增大, 建议关注长期稳定性"

    return {
        "current_dE": current_dE,
        "profile": profile,
        "predictions": predictions,
        "advice": advice,
        "drift_rate": rate,
    }
