"""Tests for market-disruptive modules: instant, predictor, passport, colorchecker."""
from __future__ import annotations
import sys


def test_instant_result_formatting():
    from senia_instant import InstantResult
    r = InstantResult(tier="MARGINAL", dE00=1.8, directions=["偏红", "偏黄"], top_advice="减少红色色精")
    text = r.to_text_message()
    assert "⚠️" in text
    assert "偏红" in text
    voice = r.to_voice_text()
    assert "临界" in voice
    card = r.to_wecom_card()
    assert card["msgtype"] == "template_card"
    print("  PASS: instant_result_formatting")


def test_instant_error_handling():
    from senia_instant import InstantResult
    r = InstantResult(error="无法解析图片")
    assert "❌" in r.to_text_message()
    assert "失败" in r.to_voice_text()
    print("  PASS: instant_error_handling")


def test_predictor_train_predict():
    from senia_predictor import ProductionPredictor
    pred = ProductionPredictor()
    for i in range(10):
        pred.record("P1", {"C": 40 + i, "M": 30 - i * 0.5}, (55 + i * 0.8, -2 + i * 0.2, 10 - i * 0.4))
    r = pred.predict("P1", {"C": 45, "M": 27.5})
    assert r.predicted_L > 0, f"Should predict, got L={r.predicted_L}"
    assert r.sample_count >= 10
    print(f"  PASS: predictor_train_predict (L={r.predicted_L}, conf={r.confidence})")


def test_predictor_optimize():
    from senia_predictor import ProductionPredictor
    pred = ProductionPredictor()
    for i in range(12):
        pred.record("P2", {"A": 10 + i, "B": 20 - i}, (50 + i, 0 + i * 0.5, 5 - i * 0.3))
    result = pred.optimize_recipe("P2", (56, 3, 3.2), {"A": 15, "B": 15})
    assert result.iterations > 0, "Should have run optimization"
    print(f"  PASS: predictor_optimize (dE={result.predicted_dE:.2f}, iters={result.iterations})")


def test_device_fingerprint():
    from senia_predictor import DeviceFingerprint
    fp = DeviceFingerprint()
    measured = [(int(115 * 1.05), int(82 * 1.08), int(68 * 1.12))] * 24
    expected = [(115, 82, 68)] * 24
    r = fp.learn_from_calibration("test_phone", measured, expected)
    assert r["learned"]
    corrected = fp.correct_image_rgb("test_phone", [(120, 85, 70)])
    assert corrected[0] != (120, 85, 70), "Should have corrected"
    print(f"  PASS: device_fingerprint (bias_r={r['current_bias']['r']:.3f})")


def test_passport_generate_verify():
    from senia_qr_passport import generate_passport, verify_passport
    p = generate_passport("L001", "FILM-A", "PASS", 0.85, ["色差极小"], (55.2, -1.3, 7.8), "wood")
    assert p["passport_id"], "Should have ID"
    assert p["signature"], "Should have signature"
    v = verify_passport(p)
    assert v["valid"], "Untampered passport should verify"
    # Tamper test
    p["dE00"] = 9.99
    v2 = verify_passport(p)
    assert not v2["valid"], "Tampered passport should fail"
    print("  PASS: passport_generate_verify")


def test_passport_html_render():
    from senia_qr_passport import generate_passport, render_passport_html
    p = generate_passport("L001", "FILM-A", "MARGINAL", 1.5, ["偏红"], (55, 1, 8), "wood")
    html = render_passport_html(p)
    assert "SENIA" in html
    assert "临界" in html
    assert "偏红" in html
    assert len(html) > 500
    print("  PASS: passport_html_render")


def main():
    print("=" * 60)
    print("SENIA Innovation Modules Tests")
    print("=" * 60)
    tests = [
        test_instant_result_formatting,
        test_instant_error_handling,
        test_predictor_train_predict,
        test_predictor_optimize,
        test_device_fingerprint,
        test_passport_generate_verify,
        test_passport_html_render,
    ]
    passed = failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"  FAIL: {t.__name__}: {e}")
    print(f"\n{'=' * 60}\nResults: {passed} passed, {failed} failed\n{'=' * 60}")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
