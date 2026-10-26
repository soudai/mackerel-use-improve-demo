#!/usr/bin/env python3
"""Bounded, repeatable HTTP workload. Measurements are observations, not SLOs."""
import argparse
import concurrent.futures
import datetime as dt
import json
import math
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request

SCENARIOS = {
    "orders": ("GET", "/api/orders?limit=50", None),
    "search": ("GET", "/api/orders/search?status=paid&from=2026-01-01&to=2026-01-02", None),
    "checkout": ("POST", "/api/checkout", {"customer_id": 1, "product_id": 1, "quantity": 1}),
    "report": ("GET", "/api/reports/sales?from=2026-01-01&to=2026-02-01", None),
}


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def percentile(values, fraction):
    """Nearest rank; return None for an empty sample, never a synthetic zero."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]


def request_once(base_url, scenario, timeout, sequence):
    method, path, body = SCENARIOS[scenario]
    payload = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(base_url.rstrip("/") + path, data=payload, method=method,
                                     headers={"Accept": "application/json", "Content-Type": "application/json"})
    started = time.perf_counter()
    result = {"sequence": sequence, "started_at": utc_now(), "status": None, "bytes": 0,
              "error": None, "trace_id": None, "query_count": None, "app_revision": None}
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            # Consume the complete body so timing includes response transfer.
            result["bytes"] = len(response.read())
            result["status"] = response.status
            result["trace_id"] = response.headers.get("X-Trace-Id")
            result["app_revision"] = response.headers.get("X-App-Revision")
            query_count = response.headers.get("X-Query-Count")
            result["query_count"] = int(query_count) if query_count and query_count.isdigit() else None
    except urllib.error.HTTPError as exc:
        result["status"] = exc.code
        result["bytes"] = len(exc.read())
        result["trace_id"] = exc.headers.get("X-Trace-Id") if exc.headers else None
        result["app_revision"] = exc.headers.get("X-App-Revision") if exc.headers else None
        result["error"] = "http_error"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        result["error"] = type(exc).__name__
    result["duration_ms"] = round((time.perf_counter() - started) * 1000, 3)
    return result


def summarize(samples, elapsed_seconds):
    successful = [item for item in samples if item["status"] is not None and 200 <= item["status"] < 400 and item["error"] is None]
    durations = [item["duration_ms"] for item in samples]
    success_durations = [item["duration_ms"] for item in successful]
    return {"requests": len(samples), "successful_requests": len(successful),
            "failed_requests": len(samples) - len(successful),
            "elapsed_seconds": round(elapsed_seconds, 3),
            "requests_per_second": round(len(samples) / elapsed_seconds, 3) if elapsed_seconds else None,
            "all_requests": {"p50_ms": percentile(durations, .5), "p95_ms": percentile(durations, .95)},
            "successful_requests_latency": {"p50_ms": percentile(success_durations, .5), "p95_ms": percentile(success_durations, .95)},
            "statuses": {str(status): sum(item["status"] == status for item in samples)
                         for status in sorted(set(item["status"] for item in samples), key=str)},
            "observed_app_revisions": sorted({item.get("app_revision") for item in samples} - {None, ""})}


def git_revision():
    result = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", choices=SCENARIOS)
    parser.add_argument("--base-url", default="http://127.0.0.1:18080")
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not (1 <= args.requests <= 10000 and 1 <= args.concurrency <= 64 and 0 <= args.warmup <= 100 and 0 < args.timeout <= 300):
        parser.error("requests: 1..10000; concurrency: 1..64; warmup: 0..100; timeout: (0,300]")
    if args.output.exists():
        parser.error("output already exists; use a fresh run path")
    # Serial warmup is separate from the measured request population.
    warmup = [request_once(args.base_url, args.scenario, args.timeout, index) for index in range(args.warmup)]
    if any(item["error"] or item["status"] is None or item["status"] >= 400 for item in warmup):
        parser.error("warmup failed; fix endpoint or seed data before measuring")
    started_at = utc_now()
    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        samples = list(executor.map(lambda index: request_once(args.base_url, args.scenario, args.timeout, index), range(args.requests)))
    summary = summarize(samples, time.perf_counter() - started)
    report = {"schema_version": 1, "scenario": args.scenario, "revision": git_revision(),
              "started_at": started_at, "finished_at": utc_now(),
              "conditions": {"base_url": args.base_url, "requests": args.requests, "concurrency": args.concurrency,
                             "warmup": args.warmup, "timeout_seconds": args.timeout, "request": SCENARIOS[args.scenario]},
              "summary": summary, "samples": samples}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), **summary}, ensure_ascii=False, indent=2))
    return 0 if summary["failed_requests"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
