"""
SENIA Predictive Engine — 生产前预测, 不需要打样
==============================================

颠覆点: 行业现状是 "打样→测色→调配方→再打样" 循环 3-5 次.
我们的方案: 输入配方+机台+环境 → 直接预测出来的颜色 → 推荐最优配方.
把 3-5 次打样缩减到 0-1 次.

核心模型:
  1. 多因素回归: recipe + machine_state + environment → Lab
  2. 逆向优化: target_Lab → optimal_recipe (在约束条件下)
  3. 置信区间: 告诉你"预测可靠度", 不可靠就建议打样

为什么颠覆: X-Rite 只能测, 我们能预测.
             卖的不是"检测工具", 是"每次节省一天打样时间".
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


@dataclass
class PredictionResult:
    """颜色预测结果."""
    predicted_L: float = 0.0
    predicted_a: float = 0.0
    predicted_b: float = 0.0
    confidence: float = 0.0       # 0~1 预测置信度
    rmse: float = 0.0             # 模型历史 RMSE
    suggestion: str = ""          # "可直接生产" / "建议打样验证" / "数据不足"
    factors_used: list[str] = field(default_factory=list)
    sample_count: int = 0         # 训练样本数


@dataclass
class RecipeOptimizeResult:
    """配方优化结果."""
    target_lab: tuple[float, float, float] = (0, 0, 0)
    current_recipe: dict[str, float] = field(default_factory=dict)
    optimized_recipe: dict[str, float] = field(default_factory=dict)
    adjustments: dict[str, float] = field(default_factory=dict)
    predicted_dE: float = 0.0     # 优化后预测色差
    confidence: float = 0.0
    iterations: int = 0


class ProductionPredictor:
    """
    多因素颜色预测器.

    输入因素:
      - recipe: 配方组分 {C: 40, M: 30, Y: 25, K: 5}
      - machine: 机台状态 {speed: 120, temperature: 65, pressure: 3.5}
      - environment: 环境 {humidity: 55, ambient_temp: 25}

    通过历史数据学习 全因素 → Lab 的映射,
    然后反向优化出"达到目标色的最优配方".
    """

    def __init__(self, store_path: Path | None = None) -> None:
        self._lock = RLock()
        self._store_path = store_path
        # product_code → [{"recipe": {}, "machine": {}, "env": {}, "lab": [L,a,b], "ts": ""}]
        self._data: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._models: dict[str, dict[str, Any]] = {}
        if store_path and store_path.exists():
            self._load()

    def record(
        self,
        product_code: str,
        recipe: dict[str, float],
        measured_lab: tuple[float, float, float],
        machine: dict[str, float] | None = None,
        environment: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        """记录一条 全因素→色值 数据."""
        with self._lock:
            entry = {
                "recipe": recipe,
                "machine": machine or {},
                "env": environment or {},
                "lab": list(measured_lab),
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            self._data[product_code].append(entry)
            n = len(self._data[product_code])
            if n >= 8:
                self._train(product_code)
            self._save()
            return {"recorded": True, "product_code": product_code, "samples": n,
                    "model_ready": product_code in self._models}

    def predict(
        self,
        product_code: str,
        recipe: dict[str, float],
        machine: dict[str, float] | None = None,
        environment: dict[str, float] | None = None,
    ) -> PredictionResult:
        """预测颜色."""
        with self._lock:
            model = self._models.get(product_code)
            if model is None:
                n = len(self._data.get(product_code, []))
                return PredictionResult(
                    suggestion=f"数据不足 (有{n}条, 需要≥8条), 请继续积累",
                    sample_count=n,
                )

            vec = self._build_feature_vec(recipe, machine, environment, model["keys"])
            vec_ext = vec + [1.0]

            pred = []
            for ch in range(3):
                coeffs = model["coefficients"][ch]
                val = sum(c * v for c, v in zip(coeffs, vec_ext))
                pred.append(round(val, 2))

            rmse = model.get("rmse", 999)
            n = model.get("n", 0)
            # 置信度: 基于 RMSE 和样本量
            if rmse < 1.0 and n >= 20:
                confidence = 0.95
                suggestion = "预测可靠, 可直接生产 ✅"
            elif rmse < 2.0 and n >= 10:
                confidence = 0.75
                suggestion = "预测较可靠, 建议小批量验证"
            elif rmse < 3.0:
                confidence = 0.50
                suggestion = "预测仅供参考, 建议打样验证"
            else:
                confidence = 0.25
                suggestion = "数据噪声较大, 必须打样"

            return PredictionResult(
                predicted_L=pred[0], predicted_a=pred[1], predicted_b=pred[2],
                confidence=confidence, rmse=rmse, suggestion=suggestion,
                factors_used=model["keys"], sample_count=n,
            )

    def optimize_recipe(
        self,
        product_code: str,
        target_lab: tuple[float, float, float],
        current_recipe: dict[str, float],
        machine: dict[str, float] | None = None,
        environment: dict[str, float] | None = None,
        max_iterations: int = 50,
        max_step: float = 2.0,
    ) -> RecipeOptimizeResult:
        """
        逆向优化: 给定目标色, 求最优配方.
        使用梯度下降法在配方空间中搜索.
        """
        result = RecipeOptimizeResult(
            target_lab=target_lab,
            current_recipe=dict(current_recipe),
        )

        model = self._models.get(product_code)
        if model is None:
            result.optimized_recipe = dict(current_recipe)
            return result

        keys = model["keys"]
        recipe_keys = [k for k in keys if not k.startswith("m_") and not k.startswith("e_")]

        best_recipe = dict(current_recipe)
        best_dE = 999.0

        for iteration in range(max_iterations):
            # 预测当前配方的色值
            pred = self.predict(product_code, best_recipe, machine, environment)
            if pred.predicted_L == 0 and pred.predicted_a == 0:
                break

            dL = pred.predicted_L - target_lab[0]
            da = pred.predicted_a - target_lab[1]
            db = pred.predicted_b - target_lab[2]
            dE = math.sqrt(dL ** 2 + da ** 2 + db ** 2)

            if dE < best_dE:
                best_dE = dE
            if dE < 0.5:
                break  # 足够接近

            # 数值梯度: 每个配方参数微调 → 看色值怎么变
            lr = max_step * (1.0 - iteration / max_iterations)  # 学习率衰减
            for key in recipe_keys:
                if key not in best_recipe:
                    continue
                # 正向扰动
                test_recipe = dict(best_recipe)
                test_recipe[key] = best_recipe[key] + 0.5
                pred_plus = self.predict(product_code, test_recipe, machine, environment)
                # 计算梯度 (对 dE 的影响)
                dL_plus = pred_plus.predicted_L - target_lab[0]
                da_plus = pred_plus.predicted_a - target_lab[1]
                db_plus = pred_plus.predicted_b - target_lab[2]
                dE_plus = math.sqrt(dL_plus ** 2 + da_plus ** 2 + db_plus ** 2)
                grad = (dE_plus - dE) / 0.5
                # 沿梯度反方向调整
                adjustment = -grad * lr
                adjustment = max(-max_step, min(max_step, adjustment))
                best_recipe[key] = max(0, best_recipe[key] + adjustment)

            result.iterations = iteration + 1

        result.optimized_recipe = {k: round(v, 2) for k, v in best_recipe.items()}
        result.adjustments = {
            k: round(best_recipe.get(k, 0) - current_recipe.get(k, 0), 2)
            for k in recipe_keys if k in current_recipe
        }
        result.predicted_dE = round(best_dE, 3)
        result.confidence = self.predict(product_code, best_recipe, machine, environment).confidence
        return result

    # ── 内部方法 ──

    def _build_feature_vec(self, recipe: dict[str, float],
                           machine: dict[str, float] | None,
                           environment: dict[str, float] | None,
                           keys: list[str]) -> list[float]:
        all_features: dict[str, float] = {}
        all_features.update(recipe)
        if machine:
            all_features.update({f"m_{k}": v for k, v in machine.items()})
        if environment:
            all_features.update({f"e_{k}": v for k, v in environment.items()})
        return [all_features.get(k, 0.0) for k in keys]

    def _train(self, product_code: str) -> None:
        data = self._data[product_code]
        n = len(data)
        if n < 8:
            return

        # 收集所有特征键
        all_keys: set[str] = set()
        for d in data:
            all_keys.update(d["recipe"].keys())
            all_keys.update(f"m_{k}" for k in d.get("machine", {}).keys())
            all_keys.update(f"e_{k}" for k in d.get("env", {}).keys())
        keys = sorted(all_keys)
        dim = len(keys) + 1  # +1 for intercept

        X = []
        Y = []
        for d in data:
            vec = self._build_feature_vec(d["recipe"], d.get("machine"), d.get("env"), keys)
            X.append(vec + [1.0])
            Y.append(d["lab"])

        try:
            from senia_learning import RecipeDigitalTwin
            solver = RecipeDigitalTwin._solve_least_squares

            coeffs = []
            total_err = 0.0
            for ch in range(3):
                y = [Y[i][ch] for i in range(n)]
                c = solver(X, y, dim)
                coeffs.append(c)
                for i in range(n):
                    pred = sum(c[j] * X[i][j] for j in range(dim))
                    total_err += (pred - y[i]) ** 2

            rmse = math.sqrt(total_err / (n * 3))
            self._models[product_code] = {
                "keys": keys, "coefficients": coeffs,
                "n": n, "rmse": round(rmse, 4),
            }
        except (ValueError, Exception):
            pass

    def _save(self) -> None:
        if not self._store_path:
            return
        try:
            self._store_path.parent.mkdir(parents=True, exist_ok=True)
            out = {
                "data": {k: v[-300:] for k, v in self._data.items()},
                "models": dict(self._models),
            }
            tmp = self._store_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self._store_path)
        except OSError:
            pass

    def _load(self) -> None:
        if not self._store_path or not self._store_path.exists():
            return
        try:
            raw = json.loads(self._store_path.read_text(encoding="utf-8"))
            for k, v in raw.get("data", {}).items():
                self._data[k] = v
            self._models = raw.get("models", {})
        except (json.JSONDecodeError, OSError):
            pass


# ══════════════════════════════════════════════════════════
# 设备指纹: 自动学习每台手机的色彩偏差
# ══════════════════════════════════════════════════════════

class DeviceFingerprint:
    """
    每台 iPhone/手机的摄像头都有微小的色彩偏差.
    通过多次 ColorChecker 校准, 学习每台设备的偏差模式.
    之后即使没有色卡, 也能自动补偿这台设备的偏差.

    颠覆点: 不需要每次都放色卡, 系统记住了你这台手机的"个性".
    """

    def __init__(self, store_path: Path | None = None) -> None:
        self._lock = RLock()
        self._store_path = store_path
        # device_id → [{"r_bias": float, "g_bias": float, "b_bias": float, "ts": str}]
        self._fingerprints: dict[str, list[dict[str, float]]] = defaultdict(list)
        if store_path and store_path.exists():
            self._load()

    def learn_from_calibration(
        self,
        device_id: str,
        measured_rgb: list[tuple[int, int, int]],
        expected_rgb: list[tuple[int, int, int]] | None = None,
    ) -> dict[str, Any]:
        """
        从一次 ColorChecker 校准中学习设备偏差.
        measured_rgb: 这台设备拍到的色块 RGB
        expected_rgb: 标准值 (默认 ColorChecker)
        """
        from senia_calibration import COLORCHECKER_SRGB_D65
        if expected_rgb is None:
            expected_rgb = COLORCHECKER_SRGB_D65

        n = min(len(measured_rgb), len(expected_rgb))
        if n < 6:
            return {"learned": False, "reason": "need at least 6 patches"}

        r_biases = []
        g_biases = []
        b_biases = []
        for i in range(n):
            mr, mg, mb = measured_rgb[i]
            er, eg, eb = expected_rgb[i]
            if er > 10:
                r_biases.append(mr / er)
            if eg > 10:
                g_biases.append(mg / eg)
            if eb > 10:
                b_biases.append(mb / eb)

        with self._lock:
            self._fingerprints[device_id].append({
                "r_bias": statistics.mean(r_biases) if r_biases else 1.0,
                "g_bias": statistics.mean(g_biases) if g_biases else 1.0,
                "b_bias": statistics.mean(b_biases) if b_biases else 1.0,
                "samples": n,
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            })
            # 保留最近 20 次
            self._fingerprints[device_id] = self._fingerprints[device_id][-20:]
            self._save()

        return {
            "learned": True,
            "device_id": device_id,
            "calibration_count": len(self._fingerprints[device_id]),
            "current_bias": {
                "r": round(statistics.mean(r_biases), 4),
                "g": round(statistics.mean(g_biases), 4),
                "b": round(statistics.mean(b_biases), 4),
            },
        }

    def correct_image_rgb(
        self,
        device_id: str,
        rgb_values: list[tuple[int, int, int]],
    ) -> list[tuple[int, int, int]]:
        """用学习到的设备偏差校正图像 RGB."""
        with self._lock:
            history = self._fingerprints.get(device_id, [])
            if not history:
                return rgb_values  # 无指纹, 不校正

            # 加权平均偏差 (最近的权重更高)
            r_bias = sum(h["r_bias"] * (i + 1) for i, h in enumerate(history)) / sum(range(1, len(history) + 1))
            g_bias = sum(h["g_bias"] * (i + 1) for i, h in enumerate(history)) / sum(range(1, len(history) + 1))
            b_bias = sum(h["b_bias"] * (i + 1) for i, h in enumerate(history)) / sum(range(1, len(history) + 1))

        if abs(r_bias) < 0.01 or abs(g_bias) < 0.01 or abs(b_bias) < 0.01:
            return rgb_values

        return [
            (max(0, min(255, int(r / r_bias + 0.5))),
             max(0, min(255, int(g / g_bias + 0.5))),
             max(0, min(255, int(b / b_bias + 0.5))))
            for r, g, b in rgb_values
        ]

    def _save(self) -> None:
        if not self._store_path:
            return
        try:
            self._store_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._store_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(dict(self._fingerprints), ensure_ascii=False), encoding="utf-8")
            tmp.replace(self._store_path)
        except OSError:
            pass

    def _load(self) -> None:
        if not self._store_path or not self._store_path.exists():
            return
        try:
            data = json.loads(self._store_path.read_text(encoding="utf-8"))
            for k, v in data.items():
                self._fingerprints[k] = v
        except (json.JSONDecodeError, OSError):
            pass
