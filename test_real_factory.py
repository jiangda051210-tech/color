"""
模拟真实工厂拍照场景:
- 地板砖背景 (斜纹灰色, 非标准背景)
- 大货平铺在地上 (木纹膜)
- 标样放在大货上面 (颜色非常接近)
- 手写字+贴纸
- 透视畸变 (手机从上方拍)
- 自然光 (非标准D65)
"""

from __future__ import annotations
import sys
import tempfile
from pathlib import Path
import cv2
import numpy as np


def generate_realistic_factory_image(
    width: int = 1200,
    height: int = 1600,
) -> np.ndarray:
    """生成和用户照片一样的场景."""
    img = np.full((height, width, 3), (180, 180, 178), dtype=np.uint8)

    # 地板砖背景 (灰色, 有缝隙线条)
    for y in range(0, height, 80):
        cv2.line(img, (0, y), (width, y + 40), (160, 160, 158), 2)
    for x in range(0, width, 120):
        cv2.line(img, (x, 0), (x + 60, height), (160, 160, 158), 2)
    # 加噪点模拟砖面质感
    noise = np.random.RandomState(42).normal(0, 5, img.shape).astype(np.int16)
    img = np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)

    # 大货 (木纹膜, 占图片 55%, 居中偏上)
    bx0, by0 = int(width * 0.08), int(height * 0.06)
    bx1, by1 = int(width * 0.92), int(height * 0.82)
    board_base = np.full((by1 - by0, bx1 - bx0, 3), (138, 132, 124), dtype=np.uint8)

    # 木纹纹理 (水平条纹 + 结疤)
    rng = np.random.RandomState(123)
    for y in range(0, board_base.shape[0], 2):
        if rng.random() < 0.25:
            dark = rng.randint(8, 25)
            w_line = rng.randint(1, 3)
            x_start = rng.randint(0, max(1, board_base.shape[1] // 4))
            x_end = rng.randint(board_base.shape[1] * 3 // 4, board_base.shape[1])
            board_base[y:y+w_line, x_start:x_end] = np.clip(
                board_base[y:y+w_line, x_start:x_end].astype(np.int16) - dark, 0, 255
            ).astype(np.uint8)

    # 结疤 (几个深色椭圆)
    for _ in range(3):
        cx = rng.randint(100, board_base.shape[1] - 100)
        cy = rng.randint(100, board_base.shape[0] - 100)
        cv2.ellipse(board_base, (cx, cy), (rng.randint(20, 50), rng.randint(10, 30)),
                    rng.randint(0, 180), 0, 360, (120, 115, 108), -1)

    # 加噪点
    bnoise = rng.normal(0, 3, board_base.shape).astype(np.int16)
    board_base = np.clip(board_base.astype(np.int16) + bnoise, 0, 255).astype(np.uint8)
    img[by0:by1, bx0:bx1] = board_base

    # 标样 (小条, 放在大货右上方, 颜色非常接近但略有差异)
    # 关键: 标样和大货之间有一条可见的边缘 (标样是独立物体, 有投影)
    sx0 = int(width * 0.52)
    sy0 = int(height * 0.18)
    sx1 = int(width * 0.88)
    sy1 = int(height * 0.33)

    # 投影效果 (标样下方有暗色阴影)
    shadow_w = 4
    img[sy1:sy1+shadow_w, sx0:sx1+shadow_w] = np.clip(
        img[sy1:sy1+shadow_w, sx0:sx1+shadow_w].astype(np.int16) - 30, 0, 255
    ).astype(np.uint8)
    img[sy0:sy1+shadow_w, sx1:sx1+shadow_w] = np.clip(
        img[sy0:sy1+shadow_w, sx1:sx1+shadow_w].astype(np.int16) - 30, 0, 255
    ).astype(np.uint8)

    # 标样膜 (颜色比大货略亮偏暖)
    sample_base = np.full((sy1 - sy0, sx1 - sx0, 3), (142, 134, 125), dtype=np.uint8)
    # 也有木纹
    for y in range(0, sample_base.shape[0], 2):
        if rng.random() < 0.2:
            dark = rng.randint(5, 18)
            sample_base[y:y+1, :] = np.clip(
                sample_base[y:y+1, :].astype(np.int16) - dark, 0, 255
            ).astype(np.uint8)
    snoise = rng.normal(0, 2, sample_base.shape).astype(np.int16)
    sample_base = np.clip(sample_base.astype(np.int16) + snoise, 0, 255).astype(np.uint8)
    img[sy0:sy1, sx0:sx1] = sample_base

    # 手写文字
    cv2.putText(img, "2024-7-28", (bx0 + 20, by1 - 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (30, 30, 30), 2)
    cv2.putText(img, "AW 125470", (sx0 + 20, (sy0 + sy1) // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (30, 30, 30), 2)

    # 白色贴纸
    cv2.rectangle(img, (sx1 - 60, sy0 + 10), (sx1 - 5, sy0 + 45), (245, 245, 240), -1)
    cv2.putText(img, "B005", (sx1 - 55, sy0 + 35), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (40, 40, 40), 1)

    return img


def test_realistic_pipeline():
    """用真实工厂场景测试."""
    from senia_image_pipeline import analyze_photo

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        print("  生成模拟工厂照片...")
        img = generate_realistic_factory_image()
        img_path = tmpdir / "factory_real.jpg"
        cv2.imwrite(str(img_path), img)
        print(f"  图片尺寸: {img.shape[1]}x{img.shape[0]}")

        print("\n  运行分析管线...")
        try:
            result = analyze_photo(
                image_path=img_path,
                profile_name="wood",
                output_dir=tmpdir / "output",
                lot_id="L20240728-01",
                product_code="AW-125470",
            )
            tier = result["tier"]
            dE = result["result"]["summary"]["avg_delta_e00"]
            dirs = result["deviation"]["directions"]
            advice = result.get("recipe_advice", {}).get("advices", [])
            profile = result["profile"]["used"]
            conf = result["result"]["confidence"]["overall"]

            print(f"\n  ========================================")
            print(f"  判定: {tier}")
            print(f"  色差: ΔE = {dE:.2f}")
            print(f"  偏差: {dirs or ['无明显偏差']}")
            print(f"  材质: {profile}")
            print(f"  置信度: {conf:.2f}")
            if advice:
                print(f"  建议: {[a.get('action','') for a in advice[:3]]}")
            print(f"  检测方法: {result['detection'].get('sample_detection_method','?')}")
            print(f"  ========================================")
            return True

        except RuntimeError as e:
            print(f"\n  ❌ 管线失败: {e}")
            # 分析为什么失败
            from elite_color_match import contour_candidates, choose_board_and_sample
            cands = contour_candidates(img)
            print(f"  候选轮廓数: {len(cands)}")
            for i, c in enumerate(cands[:5]):
                r = c.rect_area / (img.shape[0] * img.shape[1])
                print(f"    #{i}: 面积比={r:.3f} 矩形度={c.rectangularity:.3f}")
            return False


def main():
    print("=" * 55)
    print("  SENIA 真实工厂场景测试")
    print("=" * 55)
    ok = test_realistic_pipeline()
    print(f"\n{'=' * 55}")
    print(f"  {'✅ 通过' if ok else '❌ 失败'}")
    print(f"{'=' * 55}")
    return ok


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
