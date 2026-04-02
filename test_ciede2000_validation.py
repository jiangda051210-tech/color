"""
CIEDE2000 reference validation suite.

Uses the official CIE Technical Report test pairs from Sharma et al. (2005)
"The CIEDE2000 Color-Difference Formula: Implementation Notes,
Supplementary Test Data, and Mathematical Observations"

All 34 pairs are taken from Table 1 of that publication.
Expected dE values are the published reference answers (4 decimal places).
"""

from __future__ import annotations

import math
import sys

# ---------- Reference test data (Sharma 2005, Table 1) ----------
# Each tuple: (L1, a1, b1, L2, a2, b2, expected_dE00)
SHARMA_PAIRS: list[tuple[float, ...]] = [
    (50.0000, 2.6772, -79.7751, 50.0000, 0.0000, -82.7485, 2.0425),
    (50.0000, 3.1571, -77.2803, 50.0000, 0.0000, -82.7485, 2.8615),
    (50.0000, 2.8361, -74.0200, 50.0000, 0.0000, -82.7485, 3.4412),
    (50.0000, -1.3802, -84.2814, 50.0000, 0.0000, -82.7485, 1.0000),
    (50.0000, -1.1848, -84.8006, 50.0000, 0.0000, -82.7485, 1.0000),
    (50.0000, -0.9009, -85.5211, 50.0000, 0.0000, -82.7485, 1.0000),
    (50.0000, 0.0000, 0.0000, 50.0000, -1.0000, 2.0000, 2.3669),
    (50.0000, -1.0000, 2.0000, 50.0000, 0.0000, 0.0000, 2.3669),
    (50.0000, 2.4900, -0.0010, 50.0000, -2.4900, 0.0009, 7.1792),
    (50.0000, 2.4900, -0.0010, 50.0000, -2.4900, 0.0010, 7.1792),
    (50.0000, 2.4900, -0.0010, 50.0000, -2.4900, 0.0011, 7.2195),
    (50.0000, 2.4900, -0.0010, 50.0000, -2.4900, 0.0012, 7.2195),
    (50.0000, -0.0010, 2.4900, 50.0000, 0.0009, -2.4900, 4.8045),
    (50.0000, -0.0010, 2.4900, 50.0000, 0.0010, -2.4900, 4.8045),
    (50.0000, -0.0010, 2.4900, 50.0000, 0.0011, -2.4900, 4.7461),
    (50.0000, 2.5000, 0.0000, 50.0000, 0.0000, -2.5000, 4.3065),
    (50.0000, 2.5000, 0.0000, 73.0000, 25.0000, -18.0000, 27.1492),
    (50.0000, 2.5000, 0.0000, 61.0000, -5.0000, 29.0000, 22.8977),
    (50.0000, 2.5000, 0.0000, 56.0000, -27.0000, -3.0000, 31.9030),
    (50.0000, 2.5000, 0.0000, 58.0000, 24.0000, 15.0000, 19.4535),
    (50.0000, 2.5000, 0.0000, 50.0000, 3.1736, 0.5854, 1.0000),
    (50.0000, 2.5000, 0.0000, 50.0000, 3.2972, 0.0000, 1.0000),
    (50.0000, 2.5000, 0.0000, 50.0000, 1.8634, 0.5757, 1.0000),
    (50.0000, 2.5000, 0.0000, 50.0000, 3.2592, 0.3350, 1.0000),
    (60.2574, -34.0099, 36.2677, 60.4626, -34.1751, 39.4387, 1.2644),
    (63.0109, -31.0961, -5.8663, 62.8187, -29.7946, -4.0864, 1.2630),
    (61.2901, 3.7196, -5.3901, 61.4292, 2.2480, -4.9620, 1.8731),
    (35.0831, -44.1164, 3.7933, 35.0232, -40.0716, 1.5901, 1.8645),
    (22.7233, 20.0904, -46.6940, 23.0331, 14.9730, -42.5619, 2.0373),
    (36.4612, 47.8580, 18.3852, 36.2715, 50.5065, 21.2231, 1.4146),
    (90.8027, -2.0831, 1.4410, 91.1528, -1.6435, 0.0447, 1.4441),
    (90.9257, -0.5406, -0.9208, 88.6381, -0.8985, -0.7239, 1.5381),
    (6.7747, -0.2908, -2.4247, 5.8714, -0.0985, -2.2286, 0.6377),
    (2.0776, 0.0795, -1.1350, 0.9033, -0.0636, -0.5514, 0.9082),
]


def _de2000_scalar(L1: float, a1: float, b1: float,
                   L2: float, a2: float, b2: float) -> float:
    """Pure-Python scalar CIEDE2000 for validation (no dependencies)."""
    rad = math.pi / 180.0
    C1 = math.hypot(a1, b1)
    C2 = math.hypot(a2, b2)
    C_bar = (C1 + C2) / 2.0
    G = 0.5 * (1.0 - math.sqrt(C_bar**7 / (C_bar**7 + 25.0**7)))
    a1p = a1 * (1.0 + G)
    a2p = a2 * (1.0 + G)
    C1p = math.hypot(a1p, b1)
    C2p = math.hypot(a2p, b2)

    h1p = math.degrees(math.atan2(b1, a1p)) % 360.0
    h2p = math.degrees(math.atan2(b2, a2p)) % 360.0

    dLp = L2 - L1
    dCp = C2p - C1p

    if C1p * C2p == 0:
        dhp = 0.0
    elif abs(h2p - h1p) <= 180.0:
        dhp = h2p - h1p
    elif h2p - h1p > 180.0:
        dhp = h2p - h1p - 360.0
    else:
        dhp = h2p - h1p + 360.0

    dHp = 2.0 * math.sqrt(C1p * C2p) * math.sin(dhp / 2.0 * rad)

    L_bar = (L1 + L2) / 2.0
    C_bar_p = (C1p + C2p) / 2.0

    if C1p * C2p == 0:
        h_bar_p = h1p + h2p
    elif abs(h1p - h2p) <= 180.0:
        h_bar_p = (h1p + h2p) / 2.0
    elif h1p + h2p < 360.0:
        h_bar_p = (h1p + h2p + 360.0) / 2.0
    else:
        h_bar_p = (h1p + h2p - 360.0) / 2.0

    T = (
        1.0
        - 0.17 * math.cos((h_bar_p - 30.0) * rad)
        + 0.24 * math.cos(2.0 * h_bar_p * rad)
        + 0.32 * math.cos((3.0 * h_bar_p + 6.0) * rad)
        - 0.20 * math.cos((4.0 * h_bar_p - 63.0) * rad)
    )

    SL = 1.0 + 0.015 * (L_bar - 50.0) ** 2 / math.sqrt(20.0 + (L_bar - 50.0) ** 2)
    SC = 1.0 + 0.045 * C_bar_p
    SH = 1.0 + 0.015 * C_bar_p * T

    RT = (
        -2.0
        * math.sqrt(C_bar_p**7 / (C_bar_p**7 + 25.0**7))
        * math.sin(math.radians(60.0 * math.exp(-((h_bar_p - 275.0) / 25.0) ** 2)))
    )

    return math.sqrt(
        (dLp / SL) ** 2
        + (dCp / SC) ** 2
        + (dHp / SH) ** 2
        + RT * (dCp / SC) * (dHp / SH)
    )


def run_validation() -> bool:
    """Validate all implementations against reference data. Returns True if all pass."""
    tolerance = 0.0001
    all_pass = True

    # --- 1. Validate pure-Python reference implementation ---
    print("=" * 60)
    print("CIEDE2000 Validation: Pure-Python reference (34 pairs)")
    print("=" * 60)
    fail_count = 0
    for idx, pair in enumerate(SHARMA_PAIRS, 1):
        L1, a1, b1, L2, a2, b2, expected = pair
        got = _de2000_scalar(L1, a1, b1, L2, a2, b2)
        ok = abs(got - expected) < tolerance
        if not ok:
            fail_count += 1
            all_pass = False
            print(f"  FAIL pair {idx:2d}: expected={expected:.4f}  got={got:.4f}  diff={abs(got-expected):.6f}")
    if fail_count == 0:
        print(f"  ALL 34 PAIRS PASSED (tolerance={tolerance})")
    else:
        print(f"  {fail_count}/34 FAILED")

    # --- 2. Validate color_film_mvp_v2.de2000 ---
    try:
        from color_film_mvp_v2 import de2000 as de2000_v2
        print("\n" + "=" * 60)
        print("CIEDE2000 Validation: color_film_mvp_v2.de2000")
        print("=" * 60)
        fail_count = 0
        for idx, pair in enumerate(SHARMA_PAIRS, 1):
            L1, a1, b1, L2, a2, b2, expected = pair
            result = de2000_v2({"L": L1, "a": a1, "b": b1}, {"L": L2, "a": a2, "b": b2})
            got = result["total"] if isinstance(result, dict) else result
            ok = abs(got - expected) < tolerance
            if not ok:
                fail_count += 1
                all_pass = False
                print(f"  FAIL pair {idx:2d}: expected={expected:.4f}  got={got:.4f}  diff={abs(got-expected):.6f}")
        if fail_count == 0:
            print(f"  ALL 34 PAIRS PASSED (tolerance={tolerance})")
        else:
            print(f"  {fail_count}/34 FAILED")
    except ImportError:
        print("\n  SKIP: color_film_mvp_v2 not importable")

    # --- 3. Validate color_film_mvp_v3_optimized.de2000 ---
    try:
        from color_film_mvp_v3_optimized import de2000 as de2000_v3
        print("\n" + "=" * 60)
        print("CIEDE2000 Validation: color_film_mvp_v3_optimized.de2000")
        print("=" * 60)
        fail_count = 0
        for idx, pair in enumerate(SHARMA_PAIRS, 1):
            L1, a1, b1, L2, a2, b2, expected = pair
            result = de2000_v3({"L": L1, "a": a1, "b": b1}, {"L": L2, "a": a2, "b": b2})
            got = result["total"] if isinstance(result, dict) else result
            ok = abs(got - expected) < tolerance
            if not ok:
                fail_count += 1
                all_pass = False
                print(f"  FAIL pair {idx:2d}: expected={expected:.4f}  got={got:.4f}  diff={abs(got-expected):.6f}")
        if fail_count == 0:
            print(f"  ALL 34 PAIRS PASSED (tolerance={tolerance})")
        else:
            print(f"  {fail_count}/34 FAILED")
    except ImportError:
        print("\n  SKIP: color_film_mvp_v3_optimized not importable")

    # --- 4. Validate numpy vectorized (color_match_engine) ---
    try:
        import numpy as np
        from color_match_engine import ciede2000_array
        print("\n" + "=" * 60)
        print("CIEDE2000 Validation: color_match_engine.ciede2000_array")
        print("=" * 60)
        for idx, pair in enumerate(SHARMA_PAIRS, 1):
            L1, a1, b1, L2, a2, b2, expected = pair
            lab1 = np.array([[[L1, a1, b1]]], dtype=np.float32)
            lab2 = np.array([[[L2, a2, b2]]], dtype=np.float32)
            got = float(ciede2000_array(lab1, lab2).ravel()[0])
            ok = abs(got - expected) < tolerance
            if not ok:
                fail_count += 1
                all_pass = False
                print(f"  FAIL pair {idx:2d}: expected={expected:.4f}  got={got:.4f}  diff={abs(got-expected):.6f}")
        if fail_count == 0:
            print(f"  ALL 34 PAIRS PASSED (tolerance={tolerance})")
        else:
            print(f"  {fail_count}/34 FAILED")
    except ImportError:
        print("\n  SKIP: color_match_engine not importable (needs numpy/cv2)")

    print("\n" + "=" * 60)
    print(f"OVERALL: {'PASS' if all_pass else 'FAIL'}")
    print("=" * 60)
    return all_pass


if __name__ == "__main__":
    ok = run_validation()
    sys.exit(0 if ok else 1)
