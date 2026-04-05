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

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FutureTimeout
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

    skipped: int = 0
    error_categories: dict[str, int] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "success": self.success,
            "failed": self.failed,
            "skipped": self.skipped,
            "success_rate": round(self.success / max(self.total, 1) * 100, 1),
            "elapsed_sec": round(self.elapsed_sec, 2),
            "images_per_sec": round(self.total / max(self.elapsed_sec, 0.001), 2),
            "avg_time_per_image": round(self.elapsed_sec / max(self.success + self.failed, 1), 2),
            "error_categories": dict(self.error_categories),
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
    abort = False
    task_timeout = 90  # seconds per image

    def _run(path: Path) -> tuple[Path, dict[str, Any] | None, str | None]:
        try:
            if mode == "dual" and reference_path is not None:
                result = _analyze_one_dual(reference_path, path, profile, output_dir)
            else:
                result = _analyze_one_single(path, profile, output_dir)
            return path, result, None
        except Exception as exc:
            return path, None, str(exc)

    def _categorize_error(err: str) -> str:
        el = err.lower()
        if "timeout" in el:
            return "timeout"
        if "轮廓" in el or "contour" in el:
            return "detection_failed"
        if "memory" in el or "oom" in el:
            return "memory"
        if "corrupt" in el or "decode" in el or "read" in el:
            return "io_error"
        return "other"

    # Auto-tune workers: leave 1 core free, cap at 8
    cpu = os.cpu_count() or 4
    auto_workers = max(2, min(cpu - 1, 8))
    worker_count = max(1, min(max_workers or auto_workers, len(image_paths)))

    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        futures = {pool.submit(_run, p): p for p in image_paths}
        for future in as_completed(futures):
            if abort:
                batch.skipped += 1
                continue
            try:
                path, result, error = future.result(timeout=task_timeout)
            except FutureTimeout:
                path = futures[future]
                result, error = None, f"timeout_{task_timeout}s"
            except Exception as exc:
                path = futures[future]
                result, error = None, str(exc)
            completed += 1
            if error is None and result is not None:
                batch.success += 1
                batch.results.append({"path": str(path), "report": result})
            else:
                batch.failed += 1
                cat = _categorize_error(error or "unknown")
                batch.error_categories[cat] = batch.error_categories.get(cat, 0) + 1
                batch.errors.append({"path": str(path), "error": error or "unknown", "category": cat})
            # Early termination: abort if >30% fail after at least 5 processed
            processed = batch.success + batch.failed
            if processed >= 5 and batch.failed / processed > 0.30:
                abort = True
                batch.errors.append({"path": "", "error": "batch_aborted_high_error_rate", "category": "abort"})
            if on_progress is not None:
                try:
                    on_progress(completed, batch.total, str(path))
                except Exception:
                    pass

    batch.elapsed_sec = time.perf_counter() - start
    return batch
