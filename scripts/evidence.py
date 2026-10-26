#!/usr/bin/env python3
"""Draft a trace-backed issue locally; publishing requires --create-issue and --repo."""
import argparse
import datetime as dt
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
MAX_SCAN_BYTES = 256 * 1024 * 1024
MAX_LINE_BYTES = 16 * 1024 * 1024


def attrs(items):
    result = {}
    for item in items or []:
        value = item.get("value", {})
        for key in ("stringValue", "intValue", "doubleValue", "boolValue"):
            if key in value:
                result[item.get("key", "")] = value[key]
                break
    return result


def extract_spans(document):
    spans = []
    for resource in document.get("resourceSpans", []):
        resource_attrs = attrs(resource.get("resource", {}).get("attributes"))
        for scope in resource.get("scopeSpans", resource.get("instrumentationLibrarySpans", [])):
            for span in scope.get("spans", []):
                try:
                    duration = (int(span["endTimeUnixNano"]) - int(span["startTimeUnixNano"])) / 1_000_000
                except (KeyError, TypeError, ValueError):
                    continue
                spans.append({"trace_id": span.get("traceId"), "span_id": span.get("spanId"),
                              "parent_span_id": span.get("parentSpanId"), "name": str(span.get("name", ""))[:240],
                              "duration_ms": round(duration, 3), "resource": resource_attrs,
                              "attributes": attrs(span.get("attributes")),
                              "links": [{"trace_id": link.get("traceId"), "span_id": link.get("spanId")}
                                        for link in span.get("links", [])]})
    return spans


def resolve_database_spans(spans):
    """PDO execution links to a prepare span; prepare/fetch/connect are not executions."""
    lookup = {(span["trace_id"], span["span_id"]): span for span in spans}
    groups = {}
    for span in spans:
        if span["name"] != "PDOStatement::execute":
            continue
        statement = span["attributes"].get("db.query.text", span["attributes"].get("db.statement"))
        source_span_id = span["span_id"]
        if not statement:
            for link in span.get("links", []):
                # Cross-trace links do not establish a same-request SQL attribution.
                if link["trace_id"] != span["trace_id"]:
                    continue
                source = lookup.get((link["trace_id"], link["span_id"]))
                if source:
                    statement = source["attributes"].get("db.query.text", source["attributes"].get("db.statement"))
                    if statement:
                        source_span_id = source["span_id"]
                        break
        if not statement:
            continue
        statement = " ".join(str(statement).split())[:2000]
        span["sql_statement"] = statement
        span["sql_source_span_id"] = source_span_id
        group = groups.setdefault(statement, {"sql": statement, "observed_execute_spans": 0, "total_execute_ms": 0, "trace_ids": set()})
        group["observed_execute_spans"] += 1
        group["total_execute_ms"] += span["duration_ms"]
        group["trace_ids"].add(span["trace_id"])
    for group in groups.values():
        group["total_execute_ms"] = round(group["total_execute_ms"], 3)
        group["trace_ids"] = sorted(group["trace_ids"])
    return sorted(groups.values(), key=lambda group: group["total_execute_ms"], reverse=True)


def read_spans(directory, max_spans=20000, trace_ids=None, expected_revision=None,
               max_scan_bytes=MAX_SCAN_BYTES, max_line_bytes=MAX_LINE_BYTES):
    """Filter while streaming so older runs cannot consume the matching-span budget."""
    spans, warnings = [], []
    scanned_bytes = 0
    wanted = None if trace_ids is None else {str(value).lower() for value in trace_ids}
    if not directory.is_dir():
        return [], ["trace directory does not exist"]
    if wanted == set():
        return [], []
    if max_spans < 1 or max_scan_bytes < 1 or max_line_bytes < 1:
        raise ValueError("trace collection limits must be positive")
    for path in sorted(directory.rglob("*")):
        if not path.is_file() or path.suffix not in (".json", ".jsonl"):
            continue
        with path.open("rb") as stream:
            while True:
                remaining = max_scan_bytes - scanned_bytes
                line = stream.readline(min(max_line_bytes, remaining) + 1)
                if not line:
                    break
                scanned_bytes += len(line)
                if scanned_bytes > max_scan_bytes:
                    return spans, warnings + ["trace scan byte limit reached; collection is partial; narrow the trace directory or increase --max-scan-mib"]
                if len(line) > max_line_bytes:
                    warnings.append(f"skipped oversized OTLP JSON line in {path.name}; collection is partial")
                    while line and not line.endswith(b"\n"):
                        remaining = max_scan_bytes - scanned_bytes
                        line = stream.readline(min(max_line_bytes, remaining) + 1)
                        scanned_bytes += len(line)
                        if scanned_bytes > max_scan_bytes:
                            return spans, warnings + ["trace scan byte limit reached; collection is partial; narrow the trace directory or increase --max-scan-mib"]
                    continue
                if not line.strip():
                    continue
                try:
                    candidates = extract_spans(json.loads(line))
                except (json.JSONDecodeError, UnicodeDecodeError, AttributeError, TypeError):
                    warnings.append(f"invalid OTLP JSON line in {path.name}")
                    continue
                for span in candidates:
                    if wanted is not None and str(span["trace_id"]).lower() not in wanted:
                        continue
                    if expected_revision is not None and span["resource"].get("service.version") != expected_revision:
                        continue
                    if len(spans) >= max_spans:
                        return spans, warnings + ["matching span limit reached; collection is partial"]
                    spans.append(span)
    return spans, warnings


def source_reference(span, revision, clean, root=ROOT):
    if not revision or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", revision) or not clean or span["resource"].get("service.version") != revision:
        return None
    attributes = span["attributes"]
    source_path = attributes.get("code.file.path", attributes.get("code.filepath"))
    line = attributes.get("code.line.number", attributes.get("code.lineno"))
    if not source_path:
        return None
    # Container paths are mapped to the repository; arbitrary external files are never read.
    relative = str(source_path)
    for prefix in ("/var/www/html/", "/app/", "/workspace/backend/"):
        if relative.startswith(prefix):
            relative = "backend/" + relative[len(prefix):]
            break
    if relative.startswith(("app/", "routes/", "database/", "config/", "tests/")):
        relative = "backend/" + relative
    path = (root / relative).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        return None
    if not path.is_file() or path.suffix != ".php":
        return None
    try:
        line = int(line) if line is not None else None
    except (TypeError, ValueError):
        line = None
    if line is not None and not 1 <= line <= len(path.read_text(encoding="utf-8").splitlines()):
        line = None
    return {"path": str(path.relative_to(root)), "line": line,
            "function": attributes.get("code.function.name", attributes.get("code.function"))}


def render_issue(title, report):
    load = report.get("load") or {}
    lines = [f"# {title}", "", "## 観測した事象", "", f"- 対象revision: `{report.get('revision') or '未確定'}`",
             f"- 証拠の状態: {report['status']}", f"- 負荷シナリオ: {load.get('scenario', '未指定')}",
             f"- 観測期間: {load.get('started_at', '未指定')} 〜 {load.get('finished_at', '未指定')}",
             f"- 負荷条件: `{json.dumps(load.get('conditions', {}), ensure_ascii=False)}`",
             f"- 実測結果: `{json.dumps(load.get('summary', {}), ensure_ascii=False)}`", "", "## トレースとソース", ""]
    for span in report["spans"]:
        name = span["name"].replace("`", "'").replace("\n", " ")
        lines.append(f"- `{name}`: {span['duration_ms']} ms / trace `{span['trace_id']}` / span `{span['span_id']}`")
        source = span.get("source")
        if source:
            suffix = f"#L{source['line']}" if source["line"] else ""
            url = f"https://github.com/soudai/mackerel-use-improve-demo/blob/{report['revision']}/{source['path']}{suffix}"
            lines.append(f"  - ソース: [{source['path']}]({url})")
    if report.get("database_executions"):
        lines += ["", "### 観測されたSQL実行", "", "PDOStatement::executeだけを数え、SQLは同一traceのprepareリンクから照合しています。prepare/fetch/connectのスパンを実行回数には加えません。", ""]
        for query in report["database_executions"][:10]:
            sql = query["sql"].replace("`", "'")
            lines.append(f"- 実行スパン {query['observed_execute_spans']}件 / 実行時間合計 {query['total_execute_ms']} ms: `{sql}`")
    if not report["spans"]:
        lines.append("- 対象期間・revisionに対応するトレース証拠がありません。原因は未特定です。")
    lines += ["", "## 原因仮説", "", "観測された呼出し回数・処理時間・DB統計とソースを照合して記入する。未確認の原因を断定しない。", "", "## 受入条件", "", "- 同じseed・負荷・計装条件で修正前後を比較する。", "- 該当業務の返却内容と整合性をテストする。", "- 目的指標、許容する資源変動、未検証範囲を記載する。", "", "## 計測の限界", ""]
    lines.extend(f"- {warning}" for warning in report["warnings"])
    if not report["warnings"]:
        lines.append("- 取得したファイルの範囲内の証拠。samplingと保持期間は別途確認する。")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--traces", type=Path, default=ROOT / "artifacts/otel")
    parser.add_argument("--load", type=Path)
    parser.add_argument("--output", type=Path, required=True, help="fresh output directory")
    parser.add_argument("--title", default="観測結果に基づく性能改善候補")
    parser.add_argument("--trace-id", help="restrict to a 32-character hexadecimal trace id")
    parser.add_argument("--max-scan-mib", type=int, default=256, help="bound streaming input to 1..1024 MiB; hitting the limit is partial")
    parser.add_argument("--create-issue", action="store_true")
    parser.add_argument("--repo", help="required only for explicit GitHub issue publication")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output already exists; use a fresh path")
    if not 1 <= args.max_scan_mib <= 1024:
        parser.error("--max-scan-mib must be between 1 and 1024")
    if args.trace_id and not re.fullmatch(r"[0-9a-fA-F]{32}", args.trace_id):
        parser.error("invalid trace id")
    if args.create_issue and args.repo != "soudai/mackerel-use-improve-demo":
        parser.error("--create-issue requires --repo soudai/mackerel-use-improve-demo")
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    revision = revision.stdout.strip() if revision.returncode == 0 else None
    dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=normal"], cwd=ROOT, capture_output=True, text=True)
    clean = dirty.returncode == 0 and not dirty.stdout.strip()
    load = json.loads(args.load.read_text(encoding="utf-8")) if args.load else None
    trace_ids = None
    if args.trace_id:
        trace_ids = {args.trace_id.lower()}
    elif load:
        trace_ids = {sample.get("trace_id") for sample in load.get("samples", [])} - {None, ""}
    spans, warnings = read_spans(args.traces, trace_ids=trace_ids,
                                max_scan_bytes=args.max_scan_mib * 1024 * 1024)
    if load and trace_ids == set():
        warnings.append("load samples contain no trace ids; no automatic trace attribution")
    if not spans:
        warnings.append("no matching spans; bottleneck identification is incomplete")
    if not clean:
        warnings.append("working tree differs from HEAD; source attribution disabled")
    if load and load.get("revision") != revision:
        warnings.append("load revision differs from current HEAD; source attribution disabled")
        clean = False
    if load:
        deployed = {sample.get("app_revision") for sample in load.get("samples", [])} - {None, ""}
        if deployed and deployed != {revision}:
            warnings.append("deployed app revision differs from current HEAD; source attribution disabled")
            clean = False
    database_executions = resolve_database_spans(spans)
    selected = sorted(spans, key=lambda span: span["duration_ms"], reverse=True)[:30]
    for span in selected:
        span["source"] = source_reference(span, revision, clean)
    if selected and not any(span["source"] for span in selected):
        warnings.append("no same-revision source attributes; inspect spans and deployed source manually")
    report = {"schema_version": 1, "revision": revision, "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
              "status": "partial" if warnings else "complete", "warnings": sorted(set(warnings)), "load": load,
              "spans": selected, "database_executions": database_executions, "matched_spans": len(spans),
              "selection": "30 longest matching spans; nested durations must not be summed; database counts include observed PDO execute spans only"}
    args.output.mkdir(parents=True)
    (args.output / "evidence.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    body = args.output / "issue.md"
    body.write_text(render_issue(args.title, report), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "status": report["status"], "matched_spans": len(spans)}))
    if args.create_issue:
        return subprocess.run(["gh", "issue", "create", "--repo", args.repo, "--title", args.title, "--body-file", str(body)]).returncode
    return 0 if spans else 1


if __name__ == "__main__":
    raise SystemExit(main())
