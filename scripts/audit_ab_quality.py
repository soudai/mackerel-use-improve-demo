#!/usr/bin/env python3
"""Read back an already published A/B quality bundle; never publish or mutate."""
import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlencode

from audit_ab import ROOT, VERSIONS, safe_write
from audit_mackerel_reads import AuditClient, load_module, publish, stamp, utc_now


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path, help="Normalized bundle containing metrics, manifest and publication-result JSON")
    parser.add_argument("--directory", type=Path, default=ROOT / "artifacts/verification/ab")
    args = parser.parse_args()
    metrics = json.loads((args.bundle / "metrics.json").read_text())
    manifest = json.loads((args.bundle / "manifest.json").read_text())
    publication = json.loads((args.bundle / "publication-result.json").read_text())
    if publication.get("status") != "verified":
        raise ValueError("Quality bundle publication is not verified")
    if manifest["mackerel_service"] != "mackerel-seminar-demo" or manifest["revision"] != VERSIONS["after"]:
        raise ValueError("Quality bundle identity differs from the A/B candidate")
    if len(metrics) != 25:
        raise ValueError("Expected exactly 25 candidate quality metrics")
    helper = load_module("ab_quality_env_helper", ROOT / "scripts/with_mackerel.py")
    key = os.environ.get("MACKEREL_APIKEY") or helper.local_api_key(ROOT / ".env")
    client = AuditClient(publish.Client(key))
    client.phase = "after-quality-readback"
    client.identity = {"version": VERSIONS["after"], "environment": "development"}
    started = utc_now()
    org = client.request("GET", "/api/v0/org")
    if org.get("name") != "mackerel-seminar":
        raise ValueError("Mackerel organization differs from the target")
    checks = []
    for metric in metrics:
        path = "/api/v0/services/mackerel-seminar-demo/metrics?" + urlencode({
            "name": metric["name"], "from": metric["time"] - 120, "to": metric["time"] + 120})
        result = client.request("GET", path)
        checks.append({"name": metric["name"], "expected_value": metric["value"],
                       "measurement": stamp(metric["time"]), "points": result.get("metrics", []),
                       "matches_expected": publish.metric_matches(result, metric)})
    metadata = client.request("GET", "/api/v0/services/mackerel-seminar-demo/metadata/dev-quality")
    expected_profiles = {name: {
        "revision": manifest["revision"], "run_id": manifest["run_id"], "attempt_id": manifest["attempt_id"],
        "comparison_key": profile["comparison_key"], "measured_at": manifest["publication"]["measurement_timestamp"],
        "artifact_uri": manifest["artifact_uri"], "report_completeness": manifest["collection"][name]["status"],
        "published_status": "verified", "payload_sha256": manifest["publication"]["payload_sha256"],
    } for name, profile in manifest["profiles"].items()}
    metadata_match = all(metadata.get("profiles", {}).get(name) == expected for name, expected in expected_profiles.items())
    matched = sum(item["matches_expected"] for item in checks)
    quality = {"label": client.phase, "status": "complete" if matched == len(checks) and metadata_match else "partial",
               "started_at_utc": started, "finished_at_utc": utc_now(),
               "revision": manifest["revision"], "run_id": manifest["run_id"], "attempt_id": manifest["attempt_id"],
               "artifact_uri": manifest["artifact_uri"], "payload_sha256": manifest["publication"]["payload_sha256"],
               "measurement": stamp(manifest["publication"]["measurement_timestamp"]),
               "matched_count": matched, "checked_count": len(checks), "series": checks,
               "metadata_profiles_match": metadata_match, "expected_profiles": expected_profiles,
               "original_publication": publication,
               "limitations": ["Service metrics have no version or environment selector; correlate timestamp, exact values, run and metadata digest.",
                                "Original publication is recorded from publisher artifacts; this audit performs only GET requests."]}
    safe_write(args.directory / "quality-api-readback.json", quality, key)
    audit_path = args.directory / "api-evidence.json"
    audit = json.loads(audit_path.read_text()) if audit_path.exists() else {"schema_version": 1, "requests": [], "observations": []}
    audit["requests"] = [x for x in audit.get("requests", []) if x["phase"] != client.phase] + client.records
    audit["observations"] = [x for x in audit.get("observations", []) if x["label"] != client.phase] + [quality]
    for number, request in enumerate(audit["requests"], 1):
        request["sequence"] = number
    audit["finished_at_utc"] = utc_now()
    audit["request_count"] = len(audit["requests"])
    safe_write(audit_path, audit, key)
    print(json.dumps({"request_count": len(client.records), "http_statuses": sorted(set(x.get("http_status") for x in client.records), key=str),
                      "matched_count": matched, "checked_count": len(checks), "metadata_profiles_match": metadata_match}, ensure_ascii=False))
    return 0 if quality["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
