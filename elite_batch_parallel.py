"""
Parallel batch image processing for SENIA Elite.

Wraps the existing single/dual analysis functions with concurrent
execution using ThreadPoolExecutor, providing:
  - Configurable worker count
  - Progress callbacks
  - Partial failure tolerance (one bad image doesn't kill the batch)
  - Aggregated summary statistics

Usage:
    from elite_batch_parallel import run_parallel_batch

    results = run_parallel_batch(
        image_paths=[Path("a.jpg"), Path("b.jpg"), ...],
        mode="single",
        profile="auto",
        max_workers=4,
    )
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class BatchResult:
    """Aggregated result of a parallel batch run."""
    total: int = 0
    success: int = 0
    failed: int = 0
    results: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    elapsed_sec: float = 0.0

    def summary(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "success": self.success,
            "failed": self.failed,
            "elapsed_sec": round(self.elapsed_sec, 2),
            "images_per_sec": round(self.total / max(self.elapsed_sec, 0.001), 2),
        }


def _analyze_one_single(
    image_path: Path,
    profile: str,
    output_dir: Path | None,
) -> dict[str, Any]:
    from elite_color_match import analyze_single_image
    return analyze_single_image(
        str(image_path),
        profile=profile,
        output_dir=str(output_dir) if output_dir else None,
    )


def _analyze_one_dual(
    reference_path: Path,
    film_path: Path,
    profile: str,
    output_dir: Path | None,
) -> dict[str, Any]:
    from elite_color_match import analyze_dual_image
    return analyze_dual_image(
        str(reference_path),
        str(film_path),
        profile=profile,
        output_dir=str(output_dir) if output_dir else None,
    )


def run_parallel_batch(
    image_paths: list[Path],
    mode: str = "single",
    profile: str = "auto",
    output_dir: Path | None = None,
    reference_path: Path | None = None,
    max_workers: int = 4,
    on_progress: Any | None = None,
) -> BatchResult:
    """
    Run batch analysis in parallel.

    Args:
        image_paths: List of image files to analyze.
        mode: "single" or "dual". For dual, reference_path is required.
        profile: Material profile (auto/solid/wood/stone/metallic/high_gloss).
        output_dir: Optional directory for output reports.
        reference_path: Reference image for dual mode.
        max_workers: Number of concurrent workers.
        on_progress: Optional callback(completed: int, total: int, path: str).

    Returns:
        BatchResult with per-image results and aggregated summary.
    """
    batch = BatchResult(total=len(image_paths))
    if not image_paths:
        return batch

    start = time.perf_counter()
    completed = 0

    def _run(path: Path) -> tuple[Path, dict[str, Any] | None, str | None]:
        try:
            if mode == "dual" and reference_path is not None:
                result = _analyze_one_dual(reference_path, path, profile, output_dir)
            else:
                result = _analyze_one_single(path, profile, output_dir)
            return path, result, None
        except Exception as exc:
            return path, None, str(exc)

    worker_count = max(1, min(max_workers, len(image_paths)))

    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        futures = {pool.submit(_run, p): p for p in image_paths}
        for future in as_completed(futures):
            path, result, error = future.result()
            completed += 1
            if error is None and result is not None:
                batch.success += 1
                batch.results.append({"path": str(path), "report": result})
            else:
                batch.failed += 1
                batch.errors.append({"path": str(path), "error": error or "unknown"})
            if on_progress is not None:
                try:
                    on_progress(completed, batch.total, str(path))
                except Exception:
                    pass

    batch.elapsed_sec = time.perf_counter() - start
    return batch
