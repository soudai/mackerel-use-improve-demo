import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

ROOT = Path(__file__).resolve().parents[2]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


load = module("load")
evidence = module("evidence")
quality = module("quality")
import sys
sys.path.insert(0, str(ROOT / "scripts"))
log_summary = module("log_summary")


class LoadTests(unittest.TestCase):
    def test_nearest_rank_and_empty_population(self):
        self.assertIsNone(load.percentile([], .95))
        self.assertEqual(load.percentile(list(range(1, 101)), .95), 95)
        self.assertEqual(load.percentile([8], .95), 8)

    def test_failed_requests_are_not_successful_latency_samples(self):
        report = load.summarize([
            {"status": 200, "error": None, "duration_ms": 500},
            {"status": 500, "error": "http_error", "duration_ms": 1},
            {"status": None, "error": "TimeoutError", "duration_ms": 1000},
        ], 2)
        self.assertEqual(report["failed_requests"], 2)
        self.assertEqual(report["successful_requests_latency"]["p95_ms"], 500)
        self.assertEqual(report["all_requests"]["p95_ms"], 1000)

    @patch("urllib.request.urlopen", side_effect=urllib.error.URLError("connection refused"))
    def test_network_failure_is_saved_as_failure(self, _):
        sample = load.request_once("http://localhost", "orders", 1, 7)
        self.assertIsNone(sample["status"])
        self.assertEqual(sample["error"], "URLError")
        self.assertGreaterEqual(sample["duration_ms"], 0)


class EvidenceTests(unittest.TestCase):
    def test_missing_trace_directory_remains_missing(self):
        with tempfile.TemporaryDirectory() as temporary:
            spans, warnings = evidence.read_spans(Path(temporary) / "missing")
        self.assertEqual(spans, [])
        self.assertTrue(warnings)

    def test_otlp_span_time_is_converted_from_nanoseconds(self):
        document = {"resourceSpans": [{"resource": {"attributes": [{"key": "service.version", "value": {"stringValue": "a" * 40}}]},
                    "scopeSpans": [{"spans": [{"traceId": "1" * 32, "spanId": "2" * 16, "name": "orders.list",
                                              "startTimeUnixNano": "1000000000", "endTimeUnixNano": "1050000000"}]}]}]}
        spans = evidence.extract_spans(document)
        self.assertEqual(spans[0]["duration_ms"], 50)
        self.assertEqual(spans[0]["resource"]["service.version"], "a" * 40)

    def test_source_requires_same_clean_revision_and_contained_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "backend/app").mkdir(parents=True)
            (root / "backend/app/Example.php").write_text("<?php", encoding="utf-8")
            span = {"resource": {"service.version": "a" * 40}, "attributes": {"code.file.path": "/var/www/html/app/Example.php", "code.line.number": 1}}
            self.assertEqual(evidence.source_reference(span, "a" * 40, True, root)["path"], "backend/app/Example.php")
            span["attributes"]["code.file.path"] = "app/Example.php"
            self.assertEqual(evidence.source_reference(span, "a" * 40, True, root)["path"], "backend/app/Example.php")
            self.assertIsNone(evidence.source_reference(span, "b" * 40, True, root))
            self.assertIsNone(evidence.source_reference(span, "a" * 40, False, root))
            self.assertIsNone(evidence.source_reference(span, None, True, root))
            span["attributes"]["code.file.path"] = "../../outside.php"
            self.assertIsNone(evidence.source_reference(span, "a" * 40, True, root))

    def test_missing_evidence_does_not_claim_a_cause(self):
        body = evidence.render_issue("調査", {"revision": None, "status": "partial", "spans": [], "warnings": ["missing"]})
        self.assertIn("原因は未特定", body)
        self.assertIn("missing", body)

    def test_pdo_sql_is_resolved_from_same_trace_prepare_link(self):
        spans = [
            {"trace_id": "a", "span_id": "p", "name": "PDO::prepare", "duration_ms": 1, "attributes": {"db.query.text": "select * from customers where id = ?"}},
            {"trace_id": "a", "span_id": "e", "name": "PDOStatement::execute", "duration_ms": 5, "attributes": {}, "links": [{"trace_id": "a", "span_id": "p"}]},
            {"trace_id": "a", "span_id": "f", "name": "PDOStatement::fetchAll", "duration_ms": 2, "attributes": {}},
        ]
        queries = evidence.resolve_database_spans(spans)
        self.assertEqual(queries[0]["observed_execute_spans"], 1)
        self.assertEqual(queries[0]["total_execute_ms"], 5)
        self.assertEqual(spans[1]["sql_source_span_id"], "p")
        spans[1]["links"][0]["trace_id"] = "other"
        self.assertEqual(evidence.resolve_database_spans(spans), [])


class QualityTests(unittest.TestCase):
    def test_counts_actual_phpunit_list_xml_namespace(self):
        with tempfile.TemporaryDirectory() as temporary:
            plan = Path(temporary) / "plan.xml"
            report = Path(temporary) / "report.xml"
            plan.write_text('<testSuite xmlns="https://xml.phpunit.de/testSuite"><tests><testClass><testMethod id="A::a"/><testMethod id="A::b"/></testClass></tests><groups><group><test id="A::a"/></group></groups></testSuite>', encoding="utf-8")
            report.write_text('<testsuites><testsuite><testcase name="a"/><testcase name="b"/></testsuite></testsuites>', encoding="utf-8")
            self.assertEqual(quality.test_counts(plan, report), (2, 2))

    def test_missing_report_is_unknown_not_zero_tests(self):
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "missing.xml"
            self.assertEqual(quality.test_counts(missing, missing), (None, None))


class LogSummaryTests(unittest.TestCase):
    def test_routes_ranked_by_total_duration_keep_trace_ids(self):
        entries = [
            {"method": "GET", "route": "/a", "request_time": .2, "status": 200, "timestamp": "2026-01-01T00:00:00Z", "trace_id": "1" * 32},
            {"method": "GET", "route": "/a", "request_time": .3, "status": 500, "timestamp": "2026-01-01T00:00:01Z", "trace_id": "2" * 32},
            {"method": "GET", "route": "/b", "request_time": .4, "status": 200, "timestamp": "2026-01-01T00:00:02Z", "trace_id": "3" * 32},
        ]
        report = log_summary.summarize_logs(entries)
        self.assertEqual(report[0]["route"], "/a")
        self.assertEqual(report[0]["p95_ms"], 300)
        self.assertEqual(report[0]["server_errors"], 1)
        self.assertEqual(report[0]["slow_requests"][0]["trace_id"], "2" * 32)

    def test_unzoned_timestamp_is_rejected(self):
        with self.assertRaises(ValueError):
            log_summary.parse_time("2026-01-01T12:00:00")


if __name__ == "__main__":
    unittest.main()
