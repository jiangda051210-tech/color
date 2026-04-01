from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


def main() -> None:
    out_dir = Path(__file__).resolve().parent / "demo_data"
    out_dir.mkdir(parents=True, exist_ok=True)

    rows, cols = 6, 8
    cell_h, cell_w = 100, 120
    margin = 40

    h = rows * cell_h + margin * 2
    w = cols * cell_w + margin * 2

    ref = np.zeros((h, w, 3), dtype=np.uint8) + 240

    rng = np.random.default_rng(7)

    for r in range(rows):
        for c in range(cols):
            y0 = margin + r * cell_h
            x0 = margin + c * cell_w
            y1 = y0 + cell_h - 6
            x1 = x0 + cell_w - 6
            base = np.array(
                [
                    40 + c * 20 + rng.integers(-6, 6),
                    60 + r * 25 + rng.integers(-6, 6),
                    110 + (r + c) * 10 + rng.integers(-8, 8),
                ],
                dtype=np.int32,
            )
            color = np.clip(base, 0, 255).astype(np.uint8)
            cv2.rectangle(ref, (x0, y0), (x1, y1), tuple(int(v) for v in color), thickness=-1)

    # Build film image with global bias + local non-uniformity + slight geometric shift.
    film = ref.astype(np.float32)
    film[..., 0] = np.clip(film[..., 0] * 1.03 + 6.0, 0, 255)  # B up
    film[..., 1] = np.clip(film[..., 1] * 0.97 - 4.0, 0, 255)  # G down
    film[..., 2] = np.clip(film[..., 2] * 1.05 + 3.0, 0, 255)  # R up

    gradient = np.linspace(-10, 12, w, dtype=np.float32)
    film += gradient[np.newaxis, :, np.newaxis]
    film = np.clip(film, 0, 255).astype(np.uint8)

    matrix = np.float32([[1, 0, 2], [0, 1, -3]])
    film = cv2.warpAffine(film, matrix, (w, h), borderMode=cv2.BORDER_REFLECT)

    ref_path = out_dir / "sample_reference.png"
    film_path = out_dir / "film_capture.png"
    cv2.imwrite(str(ref_path), ref)
    cv2.imwrite(str(film_path), film)

    print(ref_path)
    print(film_path)


if __name__ == "__main__":
    main()
