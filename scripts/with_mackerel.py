#!/usr/bin/env python3
"""Run a bundled Mackerel CLI with the local .env key; never expose it in arguments."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
COMMANDS = {"publish", "observe"}

def local_api_key(path):
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip() == "MACKEREL_APIKEY":
            return value.strip().strip('"').strip("'")
    return None

def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print("Usage: python3 scripts/with_mackerel.py {publish|observe} <Skill CLI arguments>", file=sys.stderr)
        return 2
    environment = os.environ.copy()
    key = environment.get("MACKEREL_APIKEY") or local_api_key(ROOT / ".env")
    if not key:
        print("MACKEREL_APIKEY is not configured.", file=sys.stderr)
        return 2
    environment["MACKEREL_APIKEY"] = key
    command = ROOT / ".agents/skills/mackerel-dev-improve/scripts" / (sys.argv[1] + ".py")
    result = subprocess.run([sys.executable, str(command), *sys.argv[2:]], cwd=ROOT, env=environment, capture_output=True, text=True)
    # Defense in depth: an upstream error must not accidentally print the API key.
    sys.stdout.write(result.stdout.replace(key, "[REDACTED]"))
    sys.stderr.write(result.stderr.replace(key, "[REDACTED]"))
    return result.returncode

if __name__ == "__main__":
    raise SystemExit(main())
