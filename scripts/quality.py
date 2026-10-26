#!/usr/bin/env python3
"""Run real PHPUnit/CCCC reports, normalize with the vendored Skill, then dry-run publication."""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".agents/skills/mackerel-dev-improve/scripts"


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def run(command):
    return subprocess.run([str(part) for part in command], cwd=ROOT, capture_output=True, text=True)


def phpunit(*arguments):
    return run(["docker", "compose", "exec", "-T", "-e", "OTEL_PHP_AUTOLOAD_ENABLED=false", "-e", "OTEL_SDK_DISABLED=true", "app", "vendor/bin/phpunit", *arguments])


def save(path, content):
    path.write_text(content, encoding="utf-8")


def test_counts(plan_path, report_path):
    try:
        plan = ET.parse(plan_path).getroot()
        report = ET.parse(report_path).getroot()
        expected = sum(1 for element in plan.iter() if element.tag.rsplit("}", 1)[-1] in ("testMethod", "phpt"))
        actual = sum(1 for element in report.iter() if element.tag.rsplit("}", 1)[-1] == "testcase")
        return expected, actual
    except (ET.ParseError, OSError):
        return None, None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="fresh directory below repository artifacts/")
    parser.add_argument("--cccc", type=Path, default=ROOT / ".tools/cccc")
    parser.add_argument("--artifact-uri", help="actual HTTPS URL of the uploaded run, required later for real publication")
    parser.add_argument("--service", default="mackerel-seminar-demo", help="Mackerel service receiving this quality baseline")
    args = parser.parse_args()
    revision = run(["git", "rev-parse", "HEAD"])
    if revision.returncode:
        parser.error("commit the baseline before measuring; a full source revision is required")
    revision = revision.stdout.strip()
    run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8]
    output = args.output.resolve() if args.output else ROOT / "artifacts/quality" / run_id
    try:
        container_output = "/artifacts/" + str(output.relative_to(ROOT / "artifacts"))
    except ValueError:
        parser.error("output must be below repository artifacts/ (mounted into app at /artifacts)")
    if output.exists():
        parser.error("output already exists; use a fresh directory")
    if not args.cccc.is_file():
        parser.error("CCCC binary is missing; run scripts/install-tools")
    cccc_version = run([args.cccc, "--version"])
    if cccc_version.returncode or not re.search(r"\b1\.8\.3\b", cccc_version.stdout):
        parser.error("CCCC 1.8.3 is required; run scripts/install-tools")
    phpunit_version = phpunit("--version")
    version_match = re.search(r"PHPUnit (12\.5\.\d+)", phpunit_version.stdout)
    if phpunit_version.returncode or not version_match:
        parser.error("running app with PHPUnit 12.5.x is required")
    output.mkdir(parents=True)
    raw = output / "raw"
    raw.mkdir()
    sources = sorted(ROOT.glob("backend/app/**/*.php"))
    expected_files = [str(path.relative_to(ROOT)) for path in sources]
    source_hashes = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    save(raw / "source-manifest.json", json.dumps(source_hashes, indent=2) + "\n")
    save(raw / "cccc-version.txt", cccc_version.stdout)
    save(raw / "phpunit-version.txt", phpunit_version.stdout)
    started_at = now()
    plan = phpunit("--list-tests-xml", container_output + "/raw/test-plan.xml")
    save(raw / "phpunit-plan.stdout.txt", plan.stdout)
    save(raw / "phpunit-plan.stderr.txt", plan.stderr)
    test_started = now()
    tests = phpunit("--log-junit", container_output + "/raw/phpunit.xml")
    test_finished = now()
    save(raw / "phpunit.stdout.txt", tests.stdout)
    save(raw / "phpunit.stderr.txt", tests.stderr)
    analysis = run([args.cccc, "--no-config", "--no-cache", "--min", "0", "--lang", "php", "backend/app"])
    save(raw / "cccc.json", analysis.stdout)
    save(raw / "cccc.stderr.txt", analysis.stderr)
    expected_count, actual_count = test_counts(raw / "test-plan.xml", raw / "phpunit.xml")
    sources_unchanged = source_hashes == {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in ROOT.glob("backend/app/**/*.php")}
    dirty = run(["git", "status", "--porcelain", "--untracked-files=normal"])
    config = {"schema_version": 1, "service": args.service, "environment": "development",
              "mackerel_service": args.service, "profiles": {
                  "unit": {"kind": "junit", "producer": "phpunit", "version": version_match.group(1), "selection": "full PHPUnit suite, one invocation, no retries; independent --list-tests-xml plan"},
                  "php_static": {"kind": "cccc", "producer": "moznion/cccc", "version": "1.8.3", "language": "php", "selection": "backend/app PHP sources; full JSON; min=0; no config; no cache", "cognitive_limit": 15, "cyclomatic_limit": 10}}}
    test_complete = plan.returncode == 0 and tests.returncode in (0, 1, 2) and expected_count is not None and expected_count > 0 and expected_count == actual_count
    manifest = {"revision": revision, "base_revision": None, "run_id": run_id, "attempt_id": "1", "started_at": started_at, "finished_at": now(),
                "working_tree_dirty": dirty.returncode != 0 or bool(dirty.stdout.strip()), "artifact_uri": args.artifact_uri,
                "test_wrapper_exit_code": 0 if sources_unchanged and plan.returncode == 0 else 1,
                "profiles": {
                    "unit": {"report": "raw/phpunit.xml", "version": version_match.group(1), "exit_code": tests.returncode,
                             "run_status": "completed" if tests.returncode in (0, 1, 2) else "aborted", "test_plan_complete": test_complete,
                             "started_at": test_started, "finished_at": test_finished},
                    "php_static": {"report": "raw/cccc.json", "version": "1.8.3", "exit_code": analysis.returncode,
                                   "expected_files": expected_files}}}
    if not sources_unchanged:
        # Keep the raw report, but do not normalize a source population that changed mid-run.
        manifest["profiles"].pop("php_static")
        manifest["collection_errors"] = ["source files changed during collection; static profile is invalid"]
    save(output / "project.json", json.dumps(config, indent=2) + "\n")
    save(output / "run.json", json.dumps(manifest, indent=2) + "\n")
    normalized = run([sys.executable, SKILL / "normalize.py", "--config", output / "project.json", "--run", output / "run.json", "--output", output / "normalized"])
    save(output / "normalize.stdout.txt", normalized.stdout)
    save(output / "normalize.stderr.txt", normalized.stderr)
    publisher = None
    if normalized.returncode == 0:
        publisher = run([sys.executable, SKILL / "publish.py", "--bundle", output / "normalized"])
        save(output / "publish.stdout.txt", publisher.stdout)
        save(output / "publish.stderr.txt", publisher.stderr)
    print(json.dumps({"output": str(output), "phpunit_exit": tests.returncode, "cccc_exit": analysis.returncode,
                      "planned_tests": expected_count, "reported_tests": actual_count, "normalize_exit": normalized.returncode,
                      "publication": "dry_run" if publisher and publisher.returncode == 0 else "not_verified"}, indent=2))
    return 0 if tests.returncode == 0 and analysis.returncode == 0 and normalized.returncode == 0 and publisher and publisher.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
