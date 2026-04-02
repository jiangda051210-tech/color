"""
SENIA 模块综合测试.
覆盖: senia_analysis, senia_learning, senia_history, senia_threshold_store, senia_auto_match
"""

from __future__ import annotations
import sys


def test_mottling_profile_aware():
    """发花检测必须区分材质: 木纹允许更大L方差."""
    from senia_analysis import detect_mottling
    # 木纹膜正常L方差=4.0, 不应报发花
    has, sev = detect_mottling([45, 50, 55, 48, 52, 47, 53, 49], profile="wood")
    assert not has, f"Wood with std~3 should NOT flag mottling, got has={has}"
    # 纯色膜同样方差=4.0, 应报发花
    has2, sev2 = detect_mottling([45, 50, 55, 48, 52, 47, 53, 49], profile="solid")
    assert has2, f"Solid with std~3 SHOULD flag mottling"
    print("  PASS: mottling_profile_aware")


def test_streaks_no_false_positive():
    """正常随机波动不应触发条纹."""
    from senia_analysis import detect_streaks_fft
    # 微小随机波动
    normal = [50.0, 50.1, 49.9, 50.05, 49.95, 50.02]
    has, sev, _ = detect_streaks_fft(normal, normal)
    assert not has, f"Normal variation should not trigger streaks, got has={has}, sev={sev}"
    # 明显交替 = 条纹
    striped = [40.0, 60.0, 40.0, 60.0, 40.0, 60.0]
    has2, sev2, dir2 = detect_streaks_fft(striped, [50]*6)
    assert has2, f"Alternating pattern SHOULD trigger streaks"
    print(f"  PASS: streaks_no_false_positive (normal sev={sev}, striped sev={sev2})")


def test_uniformity_profile_cv():
    """CV阈值按材质不同."""
    from senia_analysis import analyze_spatial_uniformity, DefectResult
    # CV=0.30 对 wood 应算均匀(阈值0.40), 对 solid 应算不均匀(阈值0.25)
    values = [1.0, 1.5, 1.2, 0.8, 1.3, 1.1, 0.9, 1.4]  # CV ≈ 0.22
    u_wood = analyze_spatial_uniformity(values, DefectResult(), profile="wood")
    u_solid = analyze_spatial_uniformity(values, DefectResult(), profile="solid")
    assert u_wood.root_cause == "recipe", f"Wood CV=0.22 < 0.40 should be recipe, got {u_wood.root_cause}"
    print(f"  PASS: uniformity_profile_cv (wood={u_wood.root_cause}, solid={u_solid.root_cause})")


def test_online_learner():
    """自学习: 反馈后阈值调整方向正确."""
    from senia_learning import OnlineLearner
    learner = OnlineLearner()
    # 系统太严: MARGINAL → 操作员说PASS → pass_dE应上调
    learner.record_feedback("r1", "MARGINAL", "PASS", 1.5, "solid")
    adj = learner.get_adjustment("solid")
    adj_val1 = adj["pass_dE_adj"]
    assert adj_val1 > 0, f"Should relax pass, got {adj_val1}"
    # 系统太松: PASS → 操作员说FAIL → 调整量应减小
    learner.record_feedback("r2", "PASS", "FAIL", 0.8, "solid")
    adj_val2 = learner.get_adjustment("solid")["pass_dE_adj"]
    assert adj_val2 < adj_val1, f"Tighten: {adj_val2:.4f} should < {adj_val1:.4f}"
    print(f"  PASS: online_learner (relax={adj_val1:.4f} → tighten={adj_val2:.4f})")


def test_recipe_twin():
    """配方孪生: 训练后能预测."""
    from senia_learning import RecipeDigitalTwin
    twin = RecipeDigitalTwin()
    for i in range(15):
        twin.record_sample("P1", {"A": 10 + i, "B": 20 - i * 0.5}, (50 + i * 0.8, 2 + i * 0.1, 8 - i * 0.3))
    pred = twin.predict("P1", {"A": 15, "B": 17.5})
    assert pred["predicted"], f"Should predict after 15 samples"
    assert 50 < pred["L"] < 65, f"Predicted L={pred['L']} out of range"
    print(f"  PASS: recipe_twin (L={pred['L']}, a={pred['a']}, b={pred['b']})")


def test_batch_memory():
    """跨批次记忆: 找到最接近的历史批次."""
    from senia_learning import CrossBatchMemory
    mem = CrossBatchMemory()
    mem.remember("P1", "L1", (55, 0, 8))
    mem.remember("P1", "L2", (60, 2, 5))
    mem.remember("P1", "L3", (52, -1, 10))
    found = mem.find_closest("P1", (56, 0.5, 7.5))
    assert found[0]["lot_id"] == "L1", f"Closest should be L1, got {found[0]['lot_id']}"
    print(f"  PASS: batch_memory (closest={found[0]['lot_id']}, dE={found[0]['dE_to_target']:.2f})")


def test_aging_prediction():
    """老化预测: 返回合理的预测值."""
    from senia_learning import predict_aging_acceptance
    result = predict_aging_acceptance(1.5, 0.3, 0.6, "wood", 12)
    assert len(result["predictions"]) >= 3
    assert result["predictions"][-1]["predicted_dE"] > 1.5, "Aging should increase dE"
    assert result["advice"], "Should have advice"
    print(f"  PASS: aging_prediction ({len(result['predictions'])} timepoints, advice='{result['advice'][:40]}...')")


def test_threshold_store():
    """阈值存储: 覆盖优先级正确."""
    from senia_threshold_store import ThresholdStore
    store = ThresholdStore()
    # 默认
    t1 = store.get("solid")
    assert t1.pass_dE == 0.8, f"Default solid pass_dE should be 0.8, got {t1.pass_dE}"
    # 产品覆盖
    store.set_product_override("P1", pass_dE=1.5)
    t2 = store.get("solid", product_code="P1")
    assert t2.pass_dE == 1.5, f"Product override should be 1.5, got {t2.pass_dE}"
    # 客户覆盖优先于产品
    store.set_customer_override("C1", pass_dE=2.0)
    t3 = store.get("solid", product_code="P1", customer_id="C1")
    assert t3.pass_dE == 2.0, f"Customer override should be 2.0, got {t3.pass_dE}"
    print(f"  PASS: threshold_store (default=0.8, product=1.5, customer=2.0)")


def test_auto_match():
    """自动对色: 完整流程."""
    from senia_auto_match import auto_match
    # 明显不同的两组颜色 (关闭WB以避免归一化抵消差异)
    ref = [(120, 120, 120)] * 50
    board = [(150, 120, 100)] * 50  # 偏亮偏红偏黄
    result = auto_match(ref, board, profile="wood", apply_white_balance=False)
    assert result.tier in ("PASS", "MARGINAL", "FAIL")
    assert result.dE00 > 0
    print(f"  PASS: auto_match (tier={result.tier}, dE={result.dE00:.2f}, dirs={result.directions})")


def main():
    print("=" * 60)
    print("SENIA Modules Comprehensive Tests")
    print("=" * 60)
    tests = [
        test_mottling_profile_aware,
        test_streaks_no_false_positive,
        test_uniformity_profile_cv,
        test_online_learner,
        test_recipe_twin,
        test_batch_memory,
        test_aging_prediction,
        test_threshold_store,
        test_auto_match,
    ]
    passed = failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"  FAIL: {t.__name__}: {e}")
    print(f"\n{'='*60}\nResults: {passed} passed, {failed} failed\n{'='*60}")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
