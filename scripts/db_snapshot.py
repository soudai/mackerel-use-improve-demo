#!/usr/bin/env python3
"""Collect bounded database evidence without changing statistics or application data."""
import argparse
import datetime as dt
import json
from pathlib import Path
import subprocess

QUERIES = {
    "database": "SELECT current_database() AS database, pg_postmaster_start_time() AS server_started_at, stats_reset FROM pg_stat_database WHERE datname=current_database()",
    "statement_reset": "SELECT stats_reset, dealloc FROM pg_stat_statements_info",
    "statements": "SELECT queryid::text, left(query,2000) AS query, calls, total_exec_time, mean_exec_time, rows, shared_blks_hit, shared_blks_read, temp_blks_written FROM pg_stat_statements WHERE dbid=(SELECT oid FROM pg_database WHERE datname=current_database()) ORDER BY total_exec_time DESC LIMIT 30",
    "indexes": "SELECT s.schemaname,s.relname,s.indexrelname,s.idx_scan,s.idx_tup_read,pg_relation_size(s.indexrelid) AS bytes, i.indisprimary,i.indisunique,EXISTS(SELECT 1 FROM pg_constraint c WHERE c.conindid=s.indexrelid) AS supports_constraint FROM pg_stat_user_indexes s JOIN pg_index i ON i.indexrelid=s.indexrelid ORDER BY s.relname,s.indexrelname LIMIT 100",
    "tables": "SELECT schemaname,relname,seq_scan,seq_tup_read,idx_scan,n_live_tup,n_dead_tup,last_analyze,last_autoanalyze FROM pg_stat_user_tables ORDER BY seq_tup_read DESC LIMIT 30",
    "activity": "SELECT pid,state,wait_event_type,wait_event,pg_blocking_pids(pid) AS blocking_pids,extract(epoch FROM clock_timestamp()-query_start) AS query_age_seconds,left(query,1000) AS query FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid() ORDER BY query_start LIMIT 30",
}

SEARCH_SQL = "SELECT id,customer_id,status,total_cents,created_at FROM orders WHERE status='paid' AND created_at::date >= DATE '2026-01-01' AND created_at::date <= DATE '2026-01-02' ORDER BY created_at DESC,id DESC LIMIT 50"


def query(sql, explain=False):
    statement = "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql if explain else "SELECT coalesce(json_agg(snapshot),'[]'::json) FROM (" + sql + ") snapshot"
    try:
        result = subprocess.run(["docker", "compose", "exec", "-T", "db", "psql", "-X", "-A", "-t", "-v", "ON_ERROR_STOP=1", "-U", "demo", "-d", "demo", "-c", statement], capture_output=True, text=True, timeout=45)
    except (subprocess.TimeoutExpired, OSError) as error:
        return {"status": "error", "error": type(error).__name__}
    if result.returncode:
        return {"status": "error", "error": result.stderr.strip()[:3000]}
    try:
        return {"status": "complete", "data": json.loads(result.stdout)}
    except json.JSONDecodeError:
        return {"status": "error", "error": "psql did not return JSON"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--explain-search", action="store_true", help="also execute the fixed, bounded SELECT with EXPLAIN ANALYZE")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output already exists; choose a fresh path")
    result = {"schema_version": 1, "collected_at": dt.datetime.now(dt.timezone.utc).isoformat(),
              "scope": "local Compose database demo; cumulative counters need time-window deltas",
              "queries": {name: query(sql) for name, sql in QUERIES.items()}}
    if args.explain_search:
        result["queries"]["search_plan"] = {"sql": SEARCH_SQL, **query(SEARCH_SQL, explain=True)}
    complete = all(value["status"] == "complete" for value in result["queries"].values())
    result["status"] = "complete" if complete else "partial"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "status": result["status"]}))
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
