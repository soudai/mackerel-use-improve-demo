#!/usr/bin/env python3
"""Read back bounded, version-scoped Mackerel evidence for completed A/B loads.

This never posts metrics or updates metadata. POST /logs is a read operation.
The audit records logical requests, not transport retries performed by Client.
"""
import argparse
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path

from audit_mackerel_reads import AuditClient, ROOT, load_module, observe, publish, stamp, utc_now

VERSIONS = {
    "before": "99b7ef70d97f809c80f751d6b338518fb59588f6",
    "after": "fbf320b4d777e0520afb1f52948853ba2e2f5406",
}
GROUPS = {"read": ("orders", "search", "report"), "checkout": ("checkout",)}


def epoch(value):
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Load timestamp lacks a timezone")
    return parsed.timestamp()


def build_plan(directory, phase, group):
    source = []
    for scenario in GROUPS[group]:
        path = directory / f"{phase}-{scenario}.json"
        if not path.is_file():
            raise FileNotFoundError(f"Load is not complete: {path.name}")
        raw = path.read_bytes()
        load = json.loads(raw)
        versions = load["summary"].get("observed_app_revisions", [])
        if versions != [VERSIONS[phase]]:
            raise ValueError(f"Unexpected runtime version in {path.name}: {versions}")
        if load["summary"].get("failed_requests") != 0:
            raise ValueError(f"Failed application requests in {path.name}")
        source.append({
            "scenario": scenario, "file": path.name,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "started_at": load["started_at"], "finished_at": load["finished_at"],
            "conditions": load["conditions"], "summary": load["summary"],
        })
    begin = math.floor(min(epoch(x["started_at"]) for x in source) - 2)
    end = math.ceil(max(epoch(x["finished_at"]) for x in source) + 2)
    config = {
        "schema_version": 1,
        "mackerel_service": "mackerel-seminar-demo",
        "identity": {
            "service_name": "mackerel-seminar-demo", "service_namespace": "demo",
            "environment": "development", "version": VERSIONS[phase],
        },
        "window": {"from": begin, "to": end},
        "metrics": [],
        "apm": {"http": True, "database": True,
                "sampling_context": "SDK always_on; Collector no sampling; local synthetic A/B demo"},
        "logs": {"enabled": True, "severities": ["INFO", "WARN", "ERROR", "FATAL"]},
    }
    return {"phase": phase, "group": group, "config": config,
            "window": {"from": stamp(begin), "to": stamp(end)}, "source_loads": source,
            "window_policy": "Union of completed loads in this group; floor(start - 2s), ceil(finish + 2s). Warmups may be included; APM population need not equal measured request count."}


def annotate_rows(result, requests):
    # The observer deliberately omits full log bodies; add only APM group names.
    for kind, suffix, keys in [("http", "http-server-stats", ("method", "route")),
                                ("database", "db-query-stats", ("query",))]:
        mapping = {}
        for request in requests:
            if request["path"].endswith(suffix):
                for raw in request.get("summary", {}).get("groups", []):
                    digest = hashlib.sha256(json.dumps([raw[k] for k in keys], ensure_ascii=False).encode()).hexdigest()
                    mapping[digest] = {k: raw[k] for k in keys}
        for row in result.get("signals", {}).get(kind, {}).get("rows", []):
            row.update(mapping.get(row.get("group_sha256"), {}))


def safe_write(path, data, key):
    blob = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode()
    if key and key.encode() in blob:
        raise RuntimeError("Secret leakage guard rejected output")
    path.write_bytes(blob)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=ROOT / "artifacts/verification/ab")
    parser.add_argument("--phase", choices=["before", "after", "both"], default="both")
    parser.add_argument("--group", choices=["read", "checkout", "both"], default="both")
    parser.add_argument("--plan", action="store_true", help="Validate inputs and print windows without accessing Mackerel")
    args = parser.parse_args()
    phases = ["before", "after"] if args.phase == "both" else [args.phase]
    groups = ["read", "checkout"] if args.group == "both" else [args.group]
    plans = [build_plan(args.directory, phase, group) for phase in phases for group in groups]
    if args.plan:
        print(json.dumps(plans, ensure_ascii=False, indent=2))
        return 0
    helper = load_module("ab_env_helper", ROOT / "scripts/with_mackerel.py")
    key = os.environ.get("MACKEREL_APIKEY") or helper.local_api_key(ROOT / ".env")
    client = AuditClient(publish.Client(key))
    evidence = {"schema_version": 1, "organization": "mackerel-seminar",
                "service": "mackerel-seminar-demo", "started_at_utc": utc_now(),
                "authentication": {"header_name": "X-Api-Key", "value_recorded": False},
                "request_capture": "Logical requests; final HTTP status, not individual Client retries. No writes to Mackerel.",
                "observations": [], "requests": []}
    existing = args.directory / "api-evidence.json"
    if existing.exists():
        prior = json.loads(existing.read_text())
        selected = {f"{x['phase']}-{x['group']}" for x in plans}
        evidence["observations"] = [x for x in prior.get("observations", []) if x["label"] not in selected]
        evidence["requests"] = [x for x in prior.get("requests", []) if x["phase"] not in selected]
    client.phase = "preflight"
    client.request("GET", "/api/v0/org")
    client.request("GET", "/api/v0/services")
    for plan in plans:
        label = f"{plan['phase']}-{plan['group']}"
        client.phase, client.identity = label, plan["config"]["identity"]
        start = len(client.records)
        result = observe.observe(plan["config"], client, "mackerel-seminar", max_pages=3, include_text=False)
        annotate_rows(result, client.records[start:])
        result["audit_input"] = plan
        safe_write(args.directory / f"observed-{label}.json", result, key)
        evidence["observations"].append({"label": label, "status": result["status"], "input": plan,
             "signals": {name: {key: val for key, val in signal.items() if key not in {"rows", "records"}}
                         for name, signal in result.get("signals", {}).items()}})
    evidence["requests"].extend(client.records)
    for number, request in enumerate(evidence["requests"], 1):
        request["sequence"] = number
    evidence["finished_at_utc"] = utc_now()
    evidence["request_count"] = len(evidence["requests"])
    safe_write(existing, evidence, key)
    print(json.dumps({"request_count": len(client.records),
          "http_statuses": sorted(set(x.get("http_status") for x in client.records), key=str),
          "observations": [{"label": x["label"], "status": x["status"]} for x in evidence["observations"]]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
