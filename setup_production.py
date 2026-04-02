"""
SENIA Elite 生产环境初始化脚本.
首次部署运行一次, 创建数据库、目录、默认配置.

Usage:
    python setup_production.py
    python setup_production.py --check   # 只检查, 不创建
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def setup(root: Path, check_only: bool = False) -> bool:
    ok = True
    print("=" * 55)
    print("  SENIA Elite Production Setup")
    print("=" * 55)

    # 1. Check Python version
    v = sys.version_info
    if v.major < 3 or (v.major == 3 and v.minor < 10):
        print(f"  [FAIL] Python {v.major}.{v.minor} — need 3.10+")
        ok = False
    else:
        print(f"  [OK] Python {v.major}.{v.minor}.{v.micro}")

    # 2. Check dependencies
    deps = ["cv2", "numpy", "fastapi", "pydantic", "uvicorn"]
    for dep in deps:
        try:
            __import__(dep)
            print(f"  [OK] {dep}")
        except ImportError:
            print(f"  [FAIL] {dep} — run: pip install -r requirements.txt")
            ok = False

    # 3. Create directories
    dirs = [
        root / "service_runs",
        root / "service_runs" / "image_archive",
        root / "service_runs" / "backups",
        root / "service_runs" / "event_queue",
        root / "logs",
        root / "data",
    ]
    for d in dirs:
        if d.exists():
            print(f"  [OK] {d.relative_to(root)}/")
        elif check_only:
            print(f"  [MISSING] {d.relative_to(root)}/")
            ok = False
        else:
            d.mkdir(parents=True, exist_ok=True)
            print(f"  [CREATED] {d.relative_to(root)}/")

    # 4. Initialize databases
    db_path = root / "data" / "quality_history.sqlite"
    if db_path.exists():
        print(f"  [OK] {db_path.relative_to(root)}")
    elif not check_only:
        try:
            from elite_db_migration import build_quality_history_migrations
            runner = build_quality_history_migrations()
            runner._db_path = db_path
            applied = runner.run()
            print(f"  [CREATED] {db_path.relative_to(root)} ({len(applied)} migrations)")
        except Exception as e:
            print(f"  [WARN] DB init failed: {e}")
    else:
        print(f"  [MISSING] {db_path.relative_to(root)}")

    # 5. Check config files
    configs = [
        "decision_policy.default.json",
        "customer_tier_policy.default.json",
        "process_action_rules.json",
        "profile_config.example.json",
    ]
    for cfg in configs:
        p = root / cfg
        if p.exists():
            print(f"  [OK] {cfg}")
        else:
            print(f"  [WARN] {cfg} not found (optional)")

    # 6. Run quick import test
    print("\n  Import test:")
    modules = [
        "senia_calibration", "senia_analysis", "senia_recipe",
        "senia_pipeline", "senia_auto_match", "senia_image_pipeline",
        "senia_learning", "senia_predictor", "senia_instant",
        "senia_qr_passport", "senia_colorchecker",
    ]
    for mod in modules:
        try:
            __import__(mod)
            print(f"    [OK] {mod}")
        except ImportError as e:
            print(f"    [FAIL] {mod}: {e}")
            ok = False

    print("\n" + "=" * 55)
    if ok:
        print("  Setup complete! Run: python elite_api.py")
        print(f"  Open: http://localhost:8877")
    else:
        print("  Issues found. Fix the above and re-run.")
    print("=" * 55)
    return ok


def main():
    parser = argparse.ArgumentParser(description="SENIA Production Setup")
    parser.add_argument("--check", action="store_true", help="Check only, don't create")
    parser.add_argument("--root", type=str, default=".", help="Project root")
    args = parser.parse_args()
    ok = setup(Path(args.root).resolve(), args.check)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
