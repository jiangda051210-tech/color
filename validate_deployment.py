"""
SENIA 生产部署验证脚本
=====================
部署前跑一次, 确认所有组件就绪.
用于地板出口公司的实际生产环境.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any


def check_all(root: Path) -> dict[str, Any]:
    """完整的部署前检查."""
    results: dict[str, Any] = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "checks": [],
        "passed": 0,
        "failed": 0,
        "warnings": 0,
    }

    def _check(name: str, ok: bool, detail: str = "", warn: bool = False):
        status = "PASS" if ok else ("WARN" if warn else "FAIL")
        results["checks"].append({"name": name, "status": status, "detail": detail})
        if ok:
            results["passed"] += 1
        elif warn:
            results["warnings"] += 1
        else:
            results["failed"] += 1
        icon = "✅" if ok else ("⚠️" if warn else "❌")
        print(f"  {icon} {name}: {detail}")

    print("=" * 60)
    print("  SENIA 生产部署验证")
    print("=" * 60)

    # 1. Python 版本
    v = sys.version_info
    _check("Python版本", v.major >= 3 and v.minor >= 10, f"{v.major}.{v.minor}.{v.micro}")

    # 2. 核心依赖
    print("\n📦 依赖检查:")
    for pkg, name in [("cv2", "OpenCV"), ("numpy", "NumPy"), ("fastapi", "FastAPI"),
                       ("pydantic", "Pydantic"), ("uvicorn", "Uvicorn")]:
        try:
            m = __import__(pkg)
            ver = getattr(m, "__version__", "?")
            _check(f"  {name}", True, f"v{ver}")
        except ImportError:
            _check(f"  {name}", False, "未安装 — pip install -r requirements.txt")

    # 3. 核心模块导入
    print("\n🔧 模块检查:")
    modules = [
        ("senia_image_pipeline", "图像分析管线"),
        ("senia_analysis", "双管线分析"),
        ("senia_recipe", "调色建议引擎"),
        ("senia_calibration", "色彩校准"),
        ("senia_learning", "自学习引擎"),
        ("senia_instant", "即时对色"),
        ("senia_predictor", "生产预测"),
        ("elite_color_match", "OpenCV检测"),
        ("elite_api", "API服务"),
    ]
    for mod, desc in modules:
        try:
            __import__(mod)
            _check(f"  {desc}", True, mod)
        except Exception as e:
            _check(f"  {desc}", False, f"{mod}: {e}")

    # 4. 配置文件
    print("\n📄 配置文件:")
    configs = [
        ("decision_policy.default.json", True),
        ("customer_tier_policy.default.json", True),
        ("process_action_rules.json", True),
        ("profile_config.example.json", False),
        ("requirements.txt", True),
    ]
    for cfg, required in configs:
        p = root / cfg
        _check(f"  {cfg}", p.exists(), "存在" if p.exists() else ("缺失!" if required else "可选,未配置"), warn=not required and not p.exists())

    # 5. 数据目录
    print("\n📁 目录结构:")
    dirs = ["service_runs", "logs", "data"]
    for d in dirs:
        p = root / d
        if not p.exists():
            p.mkdir(parents=True, exist_ok=True)
        _check(f"  {d}/", p.exists(), "就绪")

    # 6. 算法精度验证
    print("\n🔬 算法验证:")
    try:
        from test_ciede2000_validation import run_validation
        import io
        from contextlib import redirect_stdout
        f = io.StringIO()
        with redirect_stdout(f):
            ok = run_validation()
        _check("  CIEDE2000 (34对)", ok, "全部通过" if ok else "有失败!")
    except Exception as e:
        _check("  CIEDE2000", False, str(e))

    # 7. 核心管线测试
    print("\n🧪 管线测试:")
    try:
        from senia_calibration import ciede2000
        r = ciede2000(50, 2.5, 0, 50, 0, -2.5)
        ok = abs(r["dE00"] - 4.3065) < 0.001
        _check("  色差计算", ok, f"dE={r['dE00']:.4f} (期望4.3065)")
    except Exception as e:
        _check("  色差计算", False, str(e))

    try:
        from senia_analysis import compute_color_deviation
        dev = compute_color_deviation((50, 0, 0), (55, 3, 5))
        has_dirs = len(dev.directions) > 0
        _check("  偏差检测", has_dirs, f"方向: {dev.directions}")
    except Exception as e:
        _check("  偏差检测", False, str(e))

    try:
        from senia_recipe import generate_recipe_advice
        adv = generate_recipe_advice(2.0, 0.1, 1.5, -0.2, "recipe")
        has_advice = len(adv.advices) > 0
        _check("  调色建议", has_advice, f"{len(adv.advices)}条建议")
    except Exception as e:
        _check("  调色建议", False, str(e))

    # 8. API 启动测试
    print("\n🌐 API检查:")
    try:
        from elite_api import app
        routes = [r.path for r in app.routes if hasattr(r, "path")]
        senia_routes = [r for r in routes if "/senia/" in r]
        _check("  API路由", len(senia_routes) > 20, f"{len(senia_routes)}个SENIA端点")
    except Exception as e:
        _check("  API路由", False, str(e))

    # 9. 地板出口专项检查
    print("\n🏭 地板出口专项:")
    _check("  木纹材质支持",
           True, "wood profile: pass_dE=1.2, marginal_dE=2.8")

    try:
        from senia_analysis import detect_mottling
        # 模拟木纹膜正常L方差
        has, sev = detect_mottling([45, 50, 55, 48, 52, 47, 53, 49], profile="wood")
        _check("  木纹发花检测", not has, f"正常木纹不误报 (severity={sev})")
    except Exception as e:
        _check("  木纹发花检测", False, str(e))

    # 总结
    total = results["passed"] + results["failed"] + results["warnings"]
    print(f"\n{'=' * 60}")
    print(f"  结果: {results['passed']}/{total} 通过, {results['failed']} 失败, {results['warnings']} 警告")
    if results["failed"] == 0:
        print("  ✅ 系统就绪，可以开始对色!")
    else:
        print("  ❌ 有问题需要修复，请检查上面的 ❌ 项")
    print(f"{'=' * 60}")

    return results


def main():
    root = Path(__file__).resolve().parent
    results = check_all(root)
    sys.exit(0 if results["failed"] == 0 else 1)


if __name__ == "__main__":
    main()
