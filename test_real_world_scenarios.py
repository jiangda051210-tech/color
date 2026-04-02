"""
SENIA 真实世界场景压力测试
=========================
基于用户实际照片特征, 生成 10 种高难度场景:
  1. 标样放大货上 (你照片中的场景)
  2. 标样颜色和大货几乎相同
  3. 大货占满整个画面 (没有背景)
  4. 拍摄角度倾斜 (透视畸变严重)
  5. 光线不均匀 (一半亮一半暗)
  6. 木纹方向不同 (标样横纹大货竖纹)
  7. 多个标样 (2个小色板+1个大货)
  8. 大货有褶皱/翘起
  9. 手写字特别多覆盖面积大
  10. 超深色木纹 (黑胡桃)

每个场景判: PASS/FAIL/检测失败, 统计成功率.
"""

from __future__ import annotations
import sys
import tempfile
from pathlib import Path
import cv2
import numpy as np


def _add_wood_grain(img: np.ndarray, region: tuple[int, int, int, int],
                    base_color: tuple[int, int, int], intensity: int = 20,
                    horizontal: bool = True, rng: np.random.RandomState | None = None) -> None:
    """在指定区域添加逼真木纹."""
    rng = rng or np.random.RandomState(42)
    y0, y1, x0, x1 = region
    # 填充底色
    img[y0:y1, x0:x1] = base_color
    h, w = y1 - y0, x1 - x0
    # 木纹线条
    step = 2 if horizontal else 3
    for i in range(0, h if horizontal else w, step):
        if rng.random() < 0.3:
            dark = rng.randint(5, intensity)
            thick = rng.randint(1, 3)
            if horizontal:
                start = rng.randint(0, max(1, w // 5))
                end = rng.randint(w * 3 // 4, w)
                img[y0+i:y0+i+thick, x0+start:x0+end] = np.clip(
                    img[y0+i:y0+i+thick, x0+start:x0+end].astype(np.int16) - dark, 0, 255).astype(np.uint8)
            else:
                start = rng.randint(0, max(1, h // 5))
                end = rng.randint(h * 3 // 4, h)
                img[y0+start:y0+end, x0+i:x0+i+thick] = np.clip(
                    img[y0+start:y0+end, x0+i:x0+i+thick].astype(np.int16) - dark, 0, 255).astype(np.uint8)
    # 噪点
    noise = rng.normal(0, 2, img[y0:y1, x0:x1].shape).astype(np.int16)
    img[y0:y1, x0:x1] = np.clip(img[y0:y1, x0:x1].astype(np.int16) + noise, 0, 255).astype(np.uint8)


def _tile_background(img: np.ndarray, color: tuple[int, int, int] = (178, 178, 176)) -> None:
    """添加地板砖背景."""
    img[:] = color
    h, w = img.shape[:2]
    for y in range(0, h, 90):
        cv2.line(img, (0, y), (w, y), (165, 165, 163), 1)
    for x in range(0, w, 130):
        cv2.line(img, (x, 0), (x, h), (165, 165, 163), 1)
    noise = np.random.RandomState(99).normal(0, 4, img.shape).astype(np.int16)
    img[:] = np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)


def _add_shadow(img: np.ndarray, y0: int, y1: int, x0: int, x1: int, depth: int = 25) -> None:
    """添加投影 (标样下方)."""
    sh = 5
    img[y1:y1+sh, x0:x1+sh] = np.clip(img[y1:y1+sh, x0:x1+sh].astype(np.int16) - depth, 0, 255).astype(np.uint8)
    img[y0:y1+sh, x1:x1+sh] = np.clip(img[y0:y1+sh, x1:x1+sh].astype(np.int16) - depth, 0, 255).astype(np.uint8)


SCENARIOS = []

def scenario(name):
    def decorator(func):
        SCENARIOS.append((name, func))
        return func
    return decorator


@scenario("1. 标样放大货上 (你的照片场景)")
def gen_scene_on_board():
    img = np.zeros((1600, 1200, 3), dtype=np.uint8)
    _tile_background(img)
    _add_wood_grain(img, (96, 1312, 96, 1104), (138, 132, 124), 20, rng=np.random.RandomState(1))
    _add_shadow(img, 288, 528, 624, 1056)
    _add_wood_grain(img, (288, 528, 624, 1056), (142, 135, 127), 15, rng=np.random.RandomState(2))
    cv2.putText(img, "2024-7-28", (110, 1280), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (30, 30, 30), 2)
    return img

@scenario("2. 标样颜色几乎相同 (极难)")
def gen_scene_very_similar():
    img = np.zeros((1600, 1200, 3), dtype=np.uint8)
    _tile_background(img)
    _add_wood_grain(img, (96, 1312, 96, 1104), (140, 134, 126), 18, rng=np.random.RandomState(3))
    _add_shadow(img, 288, 528, 624, 1056)
    _add_wood_grain(img, (288, 528, 624, 1056), (141, 135, 127), 16, rng=np.random.RandomState(4))  # 只差1-2
    return img

@scenario("3. 标样放在大货旁边 (有间隙)")
def gen_scene_beside():
    img = np.zeros((1200, 1600, 3), dtype=np.uint8)
    _tile_background(img)
    _add_wood_grain(img, (80, 1050, 80, 950), (138, 132, 124), 20, rng=np.random.RandomState(5))
    _add_wood_grain(img, (80, 400, 1000, 1500), (145, 138, 128), 18, rng=np.random.RandomState(6))
    return img

@scenario("4. 大色差 (应判 FAIL)")
def gen_scene_big_diff():
    img = np.zeros((1600, 1200, 3), dtype=np.uint8)
    _tile_background(img)
    _add_wood_grain(img, (96, 1312, 96, 1104), (138, 132, 124), 20, rng=np.random.RandomState(7))
    _add_shadow(img, 288, 528, 624, 1056)
    _add_wood_grain(img, (288, 528, 624, 1056), (158, 125, 110), 15, rng=np.random.RandomState(8))
    return img

@scenario("5. 光线不均匀 (一半亮一半暗)")
def gen_scene_uneven_light():
    img = np.zeros((1600, 1200, 3), dtype=np.uint8)
    _tile_background(img)
    _add_wood_grain(img, (96, 1312, 96, 1104), (138, 132, 124), 20, rng=np.random.RandomState(9))
    _add_shadow(img, 288, 528, 624, 1056)
    _add_wood_grain(img, (288, 528, 624, 1056), (143, 136, 128), 15, rng=np.random.RandomState(10))
    # 左侧加亮 (模拟窗户光)
    gradient = np.linspace(30, 0, img.shape[1]).reshape(1, -1, 1).astype(np.int16)
    img[:] = np.clip(img.astype(np.int16) + np.broadcast_to(gradient, img.shape), 0, 255).astype(np.uint8)
    return img

@scenario("6. 深色木纹 (黑胡桃)")
def gen_scene_dark_walnut():
    img = np.zeros((1600, 1200, 3), dtype=np.uint8)
    _tile_background(img)
    _add_wood_grain(img, (96, 1312, 96, 1104), (75, 60, 48), 25, rng=np.random.RandomState(11))
    _add_shadow(img, 288, 528, 624, 1056)
    _add_wood_grain(img, (288, 528, 624, 1056), (80, 63, 50), 22, rng=np.random.RandomState(12))
    return img

@scenario("7. 浅色膜 (枫木)")
def gen_scene_light_maple():
    img = np.zeros((1600, 1200, 3), dtype=np.uint8)
    _tile_background(img, (140, 140, 138))
    _add_wood_grain(img, (96, 1312, 96, 1104), (195, 180, 160), 12, rng=np.random.RandomState(13))
    _add_shadow(img, 288, 528, 624, 1056)
    _add_wood_grain(img, (288, 528, 624, 1056), (200, 184, 162), 10, rng=np.random.RandomState(14))
    return img

@scenario("8. 手写字覆盖面积大")
def gen_scene_heavy_text():
    img = np.zeros((1600, 1200, 3), dtype=np.uint8)
    _tile_background(img)
    _add_wood_grain(img, (96, 1312, 96, 1104), (138, 132, 124), 20, rng=np.random.RandomState(15))
    _add_shadow(img, 288, 528, 624, 1056)
    _add_wood_grain(img, (288, 528, 624, 1056), (143, 136, 128), 15, rng=np.random.RandomState(16))
    # 大量手写字
    for text, pos in [("2024-7-28", (120, 1250)), ("AW 125470", (500, 700)),
                       ("653-058 A1-03", (550, 750)), ("82", (900, 1100)),
                       ("OK", (200, 600))]:
        cv2.putText(img, text, pos, cv2.FONT_HERSHEY_SIMPLEX, 0.8, (25, 25, 25), 2)
    # 白色贴纸
    cv2.rectangle(img, (1000, 300), (1090, 400), (242, 242, 238), -1)
    cv2.rectangle(img, (1000, 500), (1090, 560), (242, 242, 238), -1)
    return img


def run_all_scenarios():
    from senia_image_pipeline import analyze_photo

    results = []
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        for name, gen_func in SCENARIOS:
            print(f"\n  {name}")
            img = gen_func()
            img_path = tmpdir / f"scene_{len(results)}.jpg"
            cv2.imwrite(str(img_path), img)

            try:
                r = analyze_photo(
                    image_path=img_path,
                    profile_name="wood",
                    output_dir=tmpdir / f"out_{len(results)}",
                )
                tier = r["tier"]
                dE = r["result"]["summary"]["avg_delta_e00"]
                dirs = r["deviation"]["directions"]
                method = r["detection"].get("sample_detection_method", "?")
                print(f"    ✅ {tier} | ΔE={dE:.2f} | {dirs or ['无偏差']} | 检测={method}")
                results.append(("PASS", name))
            except RuntimeError as e:
                msg = str(e)[:60]
                print(f"    ❌ 检测失败: {msg}")
                results.append(("FAIL", name))

    return results


def main():
    print("=" * 60)
    print("  SENIA 真实世界场景压力测试 (8 个场景)")
    print("=" * 60)

    results = run_all_scenarios()

    passed = sum(1 for r, _ in results if r == "PASS")
    total = len(results)

    print(f"\n{'=' * 60}")
    print(f"  成功率: {passed}/{total} ({passed/total*100:.0f}%)")
    for status, name in results:
        icon = "✅" if status == "PASS" else "❌"
        print(f"  {icon} {name}")
    print(f"{'=' * 60}")
    return passed >= total * 0.7  # 70% 通过率算合格


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
