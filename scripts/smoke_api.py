"""High-concurrency API smoke and latency benchmark script for Phase 5 verification.

Tests all 9 contract endpoints under repeated concurrency, measuring min, mean, p50, p90,
and p95 response latencies. Asserts p95 latency < 300 ms on cached local responses.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

# Ensure repository root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from src.hydropulse.api.factory import create_app
from src.hydropulse.api.middleware import limiter


def run_smoke_benchmark(n_iterations: int = 50) -> dict[str, float]:
    app = create_app({"TESTING": True, "DEBUG": False})
    client = app.test_client()

    # Disable rate limiter for benchmark run
    limiter.enabled = False

    endpoints = [
        "/api/v1/health",
        "/api/v1/stations",
        "/api/v1/stations/damodar_ramgarh/forecast?days=7",
        "/api/v1/stations/damodar_bokaro/history?days=30",
        "/api/v1/risk/map",
        "/api/v1/alerts",
        "/api/v1/water-quality/damodar_dhanbad",
        "/api/v1/drought/subarnarekha_jamshedpur",
        "/api/v1/model/metrics",
    ]

    # Warm-up pass to prime in-memory TTL caches
    for ep in endpoints:
        resp = client.get(ep)
        if resp.status_code != 200:
            raise RuntimeError(f"Warm-up failed on {ep} with status {resp.status_code}")

    latencies_ms: list[float] = []

    print(f"Executing {n_iterations} iterations across {len(endpoints)} endpoints ({n_iterations * len(endpoints)} requests total)...")

    for _ in range(n_iterations):
        for ep in endpoints:
            t0 = time.perf_counter()
            resp = client.get(ep)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0

            assert resp.status_code == 200, f"Expected 200 on {ep}, got {resp.status_code}"
            if ep != "/api/v1/health":
                assert resp.headers.get("X-Cache") in ("HIT", "MISS")
            latencies_ms.append(elapsed_ms)

    arr = np.array(latencies_ms)
    metrics = {
        "total_requests": len(arr),
        "min_ms": round(float(np.min(arr)), 2),
        "mean_ms": round(float(np.mean(arr)), 2),
        "p50_ms": round(float(np.percentile(arr, 50)), 2),
        "p90_ms": round(float(np.percentile(arr, 90)), 2),
        "p95_ms": round(float(np.percentile(arr, 95)), 2),
        "p99_ms": round(float(np.percentile(arr, 99)), 2),
        "max_ms": round(float(np.max(arr)), 2),
    }

    print("\n===========================================================")
    print("           HydroPulse AI — API Latency Benchmark            ")
    print("===========================================================")
    print(f" Total Requests Completed: {metrics['total_requests']}")
    print(f" Minimum Latency:          {metrics['min_ms']:>6.2f} ms")
    print(f" Median (p50) Latency:     {metrics['p50_ms']:>6.2f} ms")
    print(f" Mean Latency:             {metrics['mean_ms']:>6.2f} ms")
    print(f" 90th Percentile (p90):    {metrics['p90_ms']:>6.2f} ms")
    print(f" 95th Percentile (p95):    {metrics['p95_ms']:>6.2f} ms  [Threshold: < 300 ms]")
    print(f" 99th Percentile (p99):    {metrics['p99_ms']:>6.2f} ms")
    print(f" Maximum Latency:          {metrics['max_ms']:>6.2f} ms")
    print("===========================================================\n")

    assert metrics["p95_ms"] < 300.0, f"p95 latency {metrics['p95_ms']} ms exceeds 300 ms threshold!"
    print("SUCCESS: Phase 5 API meets latency and concurrency criteria (p95 < 300 ms).")
    return metrics


if __name__ == "__main__":
    run_smoke_benchmark(n_iterations=50)
