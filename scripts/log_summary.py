#!/usr/bin/env python3
"""Rank routes from the demo's structured access log, preserving time/version scope."""
import argparse
import datetime as dt
import json
from pathlib import Path
import subprocess

from load import percentile

ROOT = Path(__file__).resolve().parents[1]


def parse_time(value):
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed


def summarize_logs(entries):
    grouped = {}
    for entry in entries:
        key = (entry["method"], entry["route"])
        grouped.setdefault(key, []).append(entry)
    result = []
    for (method, route), rows in grouped.items():
        durations = [row["request_time"] * 1000 for row in rows]
        errors = sum(row["status"] >= 500 for row in rows)
        result.append({"method": method, "route": route, "requests": len(rows), "server_errors": errors,
                       "total_duration_ms": round(sum(durations), 3), "p95_ms": round(percentile(durations, .95), 3),
                       "max_query_count": max(row.get("query_count", 0) for row in rows),
                       "peak_memory_bytes": max(row.get("peak_memory_bytes", 0) for row in rows),
                       "slow_requests": [{"timestamp": row["timestamp"], "duration_ms": round(row["request_time"] * 1000, 3), "status": row["status"], "trace_id": row.get("trace_id")}
                                         for row in sorted(rows, key=lambda row: row["request_time"], reverse=True)[:5]]})
    return sorted(result, key=lambda row: row["total_duration_ms"], reverse=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, default=ROOT / "backend/storage/logs/access.jsonl")
    parser.add_argument("--revision", help="deployed commit; defaults to current HEAD")
    parser.add_argument("--since", help="inclusive ISO8601 time with timezone")
    parser.add_argument("--until", help="exclusive ISO8601 time with timezone")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output already exists; use a fresh path")
    revision = args.revision
    if revision is None:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
        if result.returncode:
            parser.error("--revision is required before the baseline is committed")
        revision = result.stdout.strip()
    try:
        since = parse_time(args.since) if args.since else None
        until = parse_time(args.until) if args.until else None
    except ValueError as error:
        parser.error(str(error))
    if since and until and since >= until:
        parser.error("since must precede until")
    entries, invalid, excluded = [], 0, 0
    with args.log.open(encoding="utf-8") as stream:
        for line in stream:
            try:
                row = json.loads(line)
                timestamp = parse_time(row["timestamp"])
                if row.get("service_version") != revision or (since and timestamp < since) or (until and timestamp >= until):
                    excluded += 1
                    continue
                if not isinstance(row["request_time"], (int, float)) or row["request_time"] < 0 or not isinstance(row["status"], int):
                    raise ValueError("invalid timing/status")
                if not isinstance(row["route"], str) or not isinstance(row["method"], str):
                    raise ValueError("invalid route")
                entries.append(row)
            except (KeyError, TypeError, ValueError):
                invalid += 1
    report = {"schema_version": 1, "revision": revision, "since": args.since, "until": args.until,
              "status": "partial" if invalid or not entries else "complete", "matched_requests": len(entries),
              "excluded_out_of_scope": excluded, "invalid_lines": invalid, "routes": summarize_logs(entries)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "status": report["status"], "matched_requests": len(entries)}))
    return 0 if report["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
