"""
Load testing & benchmarking harness for SENIA Elite.

Measures throughput, latency, and resource usage for the analysis pipeline.

Usage:
    python elite_benchmark.py --mode single --images ./batch_test --workers 4 --rounds 3
    python elite_benchmark.py --mode api --url http://localhost:8877 --concurrency 8
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class BenchmarkResult:
    mode: str
    total_requests: int
    success_count: int
    error_count: int
    elapsed_sec: float
    throughput_rps: float
    latency_avg_ms: float
    latency_p50_ms: float
    latency_p95_ms: float
    latency_p99_ms: float
    latency_max_ms: float
    workers: int
    rounds: int
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "total_requests": self.total_requests,
            "success_count": self.success_count,
            "error_count": self.error_count,
            "elapsed_sec": round(self.elapsed_sec, 2),
            "throughput_rps": round(self.throughput_rps, 2),
            "latency_avg_ms": round(self.latency_avg_ms, 2),
            "latency_p50_ms": round(self.latency_p50_ms, 2),
            "latency_p95_ms": round(self.latency_p95_ms, 2),
            "latency_p99_ms": round(self.latency_p99_ms, 2),
            "latency_max_ms": round(self.latency_max_ms, 2),
            "workers": self.workers,
            "rounds": self.rounds,
            "error_sample": self.errors[:5],
        }

    def report(self) -> str:
        lines = [
            "=" * 60,
            f"  SENIA Elite Benchmark — {self.mode}",
            "=" * 60,
            f"  Workers:       {self.workers}",
            f"  Rounds:        {self.rounds}",
            f"  Total:         {self.total_requests}",
            f"  Success:       {self.success_count}",
            f"  Errors:        {self.error_count}",
            f"  Elapsed:       {self.elapsed_sec:.2f}s",
            f"  Throughput:    {self.throughput_rps:.2f} req/s",
            "-" * 60,
            f"  Latency avg:   {self.latency_avg_ms:.1f}ms",
            f"  Latency p50:   {self.latency_p50_ms:.1f}ms",
            f"  Latency p95:   {self.latency_p95_ms:.1f}ms",
            f"  Latency p99:   {self.latency_p99_ms:.1f}ms",
            f"  Latency max:   {self.latency_max_ms:.1f}ms",
            "=" * 60,
        ]
        return "\n".join(lines)


def _bench_local_single(image_paths: list[Path], profile: str) -> tuple[float, str | None]:
    """Benchmark a single local analysis. Returns (latency_sec, error)."""
    from elite_color_match import analyze_single_image
    start = time.perf_counter()
    try:
        for path in image_paths:
            analyze_single_image(str(path), profile=profile)
        return time.perf_counter() - start, None
    except Exception as exc:
        return time.perf_counter() - start, str(exc)


def _bench_api_request(url: str, image_path: Path) -> tuple[float, str | None]:
    """Benchmark an API analysis call. Returns (latency_sec, error)."""
    import urllib.request
    import urllib.error

    start = time.perf_counter()
    try:
        boundary = "----BenchBoundary"
        img_data = image_path.read_bytes()
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="image"; filename="{image_path.name}"\r\n'
            f"Content-Type: image/jpeg\r\n\r\n"
        ).encode() + img_data + f"\r\n--{boundary}--\r\n".encode()

        req = urllib.request.Request(
            f"{url}/analyze",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
            elapsed = time.perf_counter() - start
            return elapsed, None if resp.status == 200 else f"status={resp.status}"
    except Exception as exc:
        return time.perf_counter() - start, str(exc)


def run_local_benchmark(
    image_dir: Path,
    profile: str = "auto",
    workers: int = 4,
    rounds: int = 3,
    glob_pattern: str = "*.jpg",
) -> BenchmarkResult:
    """Run local pipeline benchmarks."""
    image_paths = sorted(image_dir.glob(glob_pattern))
    if not image_paths:
        image_paths = sorted(image_dir.glob("*.png"))
    if not image_paths:
        return BenchmarkResult(
            mode="local", total_requests=0, success_count=0, error_count=0,
            elapsed_sec=0, throughput_rps=0, latency_avg_ms=0, latency_p50_ms=0,
            latency_p95_ms=0, latency_p99_ms=0, latency_max_ms=0,
            workers=workers, rounds=rounds,
            errors=["No images found"],
        )

    latencies: list[float] = []
    errors: list[str] = []

    start = time.perf_counter()
    for _ in range(rounds):
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = []
            for path in image_paths:
                futures.append(pool.submit(_bench_local_single, [path], profile))
            for future in as_completed(futures):
                lat, err = future.result()
                latencies.append(lat)
                if err:
                    errors.append(err)
    total_elapsed = time.perf_counter() - start

    return _build_result("local", latencies, errors, total_elapsed, workers, rounds)


def run_api_benchmark(
    url: str,
    image_dir: Path,
    concurrency: int = 8,
    rounds: int = 3,
    glob_pattern: str = "*.jpg",
) -> BenchmarkResult:
    """Run API endpoint benchmarks."""
    image_paths = sorted(image_dir.glob(glob_pattern))
    if not image_paths:
        image_paths = sorted(image_dir.glob("*.png"))

    latencies: list[float] = []
    errors: list[str] = []

    start = time.perf_counter()
    for _ in range(rounds):
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = []
            for path in image_paths:
                futures.append(pool.submit(_bench_api_request, url, path))
            for future in as_completed(futures):
                lat, err = future.result()
                latencies.append(lat)
                if err:
                    errors.append(err)
    total_elapsed = time.perf_counter() - start

    return _build_result("api", latencies, errors, total_elapsed, concurrency, rounds)


def _build_result(
    mode: str, latencies: list[float], errors: list[str],
    elapsed: float, workers: int, rounds: int,
) -> BenchmarkResult:
    total = len(latencies)
    success = total - len(errors)
    lat_ms = [x * 1000 for x in latencies] if latencies else [0.0]
    lat_ms.sort()

    return BenchmarkResult(
        mode=mode,
        total_requests=total,
        success_count=success,
        error_count=len(errors),
        elapsed_sec=elapsed,
        throughput_rps=total / max(elapsed, 0.001),
        latency_avg_ms=statistics.mean(lat_ms),
        latency_p50_ms=lat_ms[int(len(lat_ms) * 0.50)] if lat_ms else 0,
        latency_p95_ms=lat_ms[int(len(lat_ms) * 0.95)] if lat_ms else 0,
        latency_p99_ms=lat_ms[int(len(lat_ms) * 0.99)] if lat_ms else 0,
        latency_max_ms=max(lat_ms),
        workers=workers,
        rounds=rounds,
        errors=errors,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="SENIA Elite Benchmark")
    parser.add_argument("--mode", choices=["local", "api"], default="local")
    parser.add_argument("--images", type=str, default="./batch_test")
    parser.add_argument("--profile", type=str, default="auto")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--url", type=str, default="http://127.0.0.1:8877")
    parser.add_argument("--output", type=str, default=None)
    args = parser.parse_args()

    image_dir = Path(args.images)

    if args.mode == "local":
        result = run_local_benchmark(image_dir, args.profile, args.workers, args.rounds)
    else:
        result = run_api_benchmark(args.url, image_dir, args.concurrency, args.rounds)

    print(result.report())

    if args.output:
        Path(args.output).write_text(
            json.dumps(result.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"\nResults saved to: {args.output}")


if __name__ == "__main__":
    main()
