"""
SENIA 管线集成测试.
用合成数据验证 M1→M3→M4→M5→M6→M7 完整流程.
"""

from __future__ import annotations

import sys

from senia_calibration import ciede2000, srgb_to_lab_d50, fit_ccm_least_squares, COLORCHECKER_SRGB_D65
from senia_analysis import (
    compute_color_deviation,
    run_defect_pipeline,
    judge_three_tier,
    analyze_spatial_uniformity,
    ThresholdConfig,
    run_full_analysis,
)
from senia_recipe import generate_recipe_advice
from senia_pipeline import run_pipeline


def test_ciede2000_basic():
    """基本色差计算."""
    # 相同颜色 → ΔE = 0
    r = ciede2000(50, 0, 0, 50, 0, 0)
    assert r["dE00"] == 0.0, f"Same color should be 0, got {r['dE00']}"

    # 明显不同
    r = ciede2000(50, 0, 0, 80, 0, 0)
    assert r["dE00"] > 10, f"Large L diff should give large dE, got {r['dE00']}"
    print("  PASS: ciede2000 basic")


def test_color_deviation():
    """色偏方向检测."""
    ref = (50.0, 0.0, 0.0)
    sample = (55.0, 3.0, 5.0)  # 偏亮 + 偏红 + 偏黄
    dev = compute_color_deviation(ref, sample)
    assert dev.dE00 > 0
    assert "偏亮" in dev.directions, f"Should detect bright, got {dev.directions}"
    assert "偏红" in dev.directions, f"Should detect red, got {dev.directions}"
    assert "偏黄" in dev.directions, f"Should detect yellow, got {dev.directions}"
    print(f"  PASS: deviation directions = {dev.directions}")


def test_defect_pipeline():
    """缺陷检测管线."""
    # 均匀 L 值 → 无发花
    uniform_L = [50.0] * 16
    defects = run_defect_pipeline(uniform_L, [50.0] * 4, [50.0] * 4, [0.5] * 16)
    assert not defects.has_mottling, "Uniform L should not have mottling"

    # 不均匀 L 值 → 发花
    noisy_L = [40.0, 60.0, 42.0, 58.0, 41.0, 59.0, 43.0, 57.0,
               39.0, 61.0, 44.0, 56.0, 38.0, 62.0, 45.0, 55.0]
    defects2 = run_defect_pipeline(noisy_L, [50.0] * 4, [50.0] * 4, [1.0] * 16)
    assert defects2.has_mottling, f"Noisy L should detect mottling, severity={defects2.mottling_severity}"
    print(f"  PASS: defect pipeline (mottling={defects2.has_mottling})")


def test_three_tier_judgment():
    """三级判定."""
    from senia_analysis import ColorDeviationResult, DefectResult

    # 合格
    dev_ok = ColorDeviationResult(dE00=0.5, dL=0.2, dC=0.1, dH=0.1, da=0.1, db=0.1)
    defects_ok = DefectResult()
    j = judge_three_tier(dev_ok, defects_ok)
    assert j.tier == "PASS", f"Low dE should PASS, got {j.tier}"

    # 临界
    dev_mid = ColorDeviationResult(dE00=1.8, dL=1.0, dC=0.5, dH=0.3, da=0.6, db=0.8, directions=["偏亮", "偏黄"])
    j2 = judge_three_tier(dev_mid, defects_ok)
    assert j2.tier == "MARGINAL", f"Mid dE should be MARGINAL, got {j2.tier}"

    # 不合格
    dev_bad = ColorDeviationResult(dE00=4.0, dL=2.0, dC=1.5, dH=1.0, da=1.2, db=1.5, directions=["偏亮", "偏红", "偏黄"])
    j3 = judge_three_tier(dev_bad, defects_ok)
    assert j3.tier == "FAIL", f"High dE should FAIL, got {j3.tier}"

    print(f"  PASS: three-tier (PASS/MARGINAL/FAIL)")


def test_spatial_uniformity():
    """空间均匀性 → 配方 vs 工艺."""
    from senia_analysis import DefectResult

    # 均匀偏色 → 配方
    uniform_dE = [2.0, 2.1, 1.9, 2.0, 2.05, 1.95, 2.0, 2.1]
    u1 = analyze_spatial_uniformity(uniform_dE, DefectResult())
    assert u1.root_cause == "recipe", f"Uniform deviation should be recipe, got {u1.root_cause}"

    # 不均匀偏色 → 工艺
    patchy_dE = [0.5, 4.0, 0.3, 3.8, 0.6, 4.2, 0.4, 3.5]
    u2 = analyze_spatial_uniformity(patchy_dE, DefectResult())
    assert u2.root_cause == "process", f"Patchy deviation should be process, got {u2.root_cause}"

    print(f"  PASS: uniformity (recipe={u1.root_cause}, process={u2.root_cause})")


def test_recipe_advice():
    """调色建议."""
    # 偏亮+偏黄 → 减白优先
    adv = generate_recipe_advice(dL=2.0, da=0.1, db=1.5, dC=-0.2, root_cause="recipe")
    assert any("白" in a.action for a in adv.advices), f"Should suggest reduce white: {[a.action for a in adv.advices]}"

    # 工艺问题 → 工艺建议
    adv2 = generate_recipe_advice(dL=0.5, da=0.3, db=0.2, dC=0.1, root_cause="process", defect_types=["streaks"])
    assert adv2.is_process_issue
    assert any("刮刀" in a.action for a in adv2.advices), f"Should suggest check blade: {[a.action for a in adv2.advices]}"

    print(f"  PASS: recipe advice ({len(adv.advices)} recipe, {len(adv2.advices)} process)")


def test_full_pipeline():
    """完整管线端到端."""
    # 标样: 统一中性色
    ref_cells = [(128, 128, 128)] * 48  # 6×8 网格
    # 打样: 略偏红偏亮
    sample_cells = [(140, 125, 120)] * 48

    record = run_pipeline(
        ref_rgb_cells=ref_cells,
        sample_rgb_cells=sample_cells,
        grid_rows=6,
        grid_cols=8,
        profile="solid",
        lot_id="TEST-001",
        product_code="FILM-A",
    )

    assert record.session_id, "Should have session ID"
    assert record.analysis["tier"] in ("PASS", "MARGINAL", "FAIL")
    assert record.analysis["dE00"] > 0
    assert record.sha256, "Should have signature"
    assert record.analysis["uniformity"]["root_cause"] in ("ok", "recipe", "process", "mixed")

    tier = record.analysis["tier"]
    dE = record.analysis["dE00"]
    cause = record.analysis["uniformity"]["root_cause"]
    n_advice = len(record.recipe_advice.get("advices", []))

    print(f"  PASS: full pipeline (tier={tier}, dE={dE:.2f}, cause={cause}, {n_advice} advices)")
    print(f"         偏差方向: {record.analysis['deviation']['directions']}")
    if record.recipe_advice.get("advices"):
        for a in record.recipe_advice["advices"][:3]:
            print(f"         建议: [{a['priority']}] {a['action']}")


def main():
    print("=" * 60)
    print("SENIA Pipeline Integration Tests")
    print("=" * 60)

    tests = [
        test_ciede2000_basic,
        test_color_deviation,
        test_defect_pipeline,
        test_three_tier_judgment,
        test_spatial_uniformity,
        test_recipe_advice,
        test_full_pipeline,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as exc:
            failed += 1
            print(f"  FAIL: {test.__name__}: {exc}")

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)
    return failed == 0


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
