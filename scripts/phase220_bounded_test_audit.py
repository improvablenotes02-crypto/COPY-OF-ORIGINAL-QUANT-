"""Run pytest files in isolated, bounded subprocesses and write a JSON summary.

Example:
  python scripts/phase220_bounded_test_audit.py --max-files 20 --timeout-seconds 90
  python scripts/phase220_bounded_test_audit.py tests/test_phase218_preflight_deployment_smoke.py

This is an audit aid, not a replacement for the canonical full-suite command.
Each test file gets a separate pytest process so a slow/hung module can be
identified without hiding results from modules already completed.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", help="test files or directories; defaults to tests/")
    parser.add_argument("--timeout-seconds", type=float, default=90.0)
    parser.add_argument("--max-files", type=int, default=0,
                        help="limit number of discovered test files (0 means no limit)")
    parser.add_argument("--output", type=Path, default=Path("phase220_test_audit.json"))
    args = parser.parse_args()
    if args.timeout_seconds <= 0 or args.max_files < 0:
        parser.error("timeout must be positive and max-files must be nonnegative")

    roots = [Path(p) for p in args.paths] if args.paths else [Path("tests")]
    files: list[Path] = []
    for root in roots:
        if root.is_file():
            files.append(root)
        elif root.is_dir():
            files.extend(sorted(p for p in root.rglob("test_*.py") if p.is_file()))
        else:
            parser.error(f"path does not exist: {root}")
    files = sorted(dict.fromkeys(p.resolve() for p in files))
    if args.max_files:
        files = files[:args.max_files]
    if not files:
        parser.error("no test files discovered")

    results = []
    started_all = time.monotonic()
    args.output.parent.mkdir(parents=True, exist_ok=True)

    def write_checkpoint() -> None:
        summary = {
            "schema_version": 1,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "timeout_seconds_per_file": args.timeout_seconds,
            "files_requested": len(files),
            "files_completed": len(results),
            "duration_seconds": round(time.monotonic() - started_all, 3),
            "counts": {key: sum(r["status"] == key for r in results)
                       for key in ("passed", "failed", "timeout", "no_tests")},
            "results": results,
        }
        args.output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    for path in files:
        started = time.monotonic()
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", str(path), "-q"],
                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                timeout=args.timeout_seconds, check=False,
            )
            code = proc.returncode
            output = proc.stdout[-12000:]
            if code == 0:
                status = "passed"
            elif code == 5 and "no tests ran" in output.lower():
                status = "no_tests"
            else:
                status = "failed"
        except subprocess.TimeoutExpired as exc:
            status, code = "timeout", None
            out = exc.stdout or ""
            if isinstance(out, bytes):
                out = out.decode("utf-8", errors="replace")
            output = str(out)[-12000:]
        results.append({
            "path": str(path), "status": status, "returncode": code,
            "duration_seconds": round(time.monotonic() - started, 3),
            "output_tail": output,
        })
        write_checkpoint()
        print(f"{status.upper():7} {path} ({results[-1]['duration_seconds']}s)", flush=True)

    write_checkpoint()
    summary = json.loads(args.output.read_text(encoding="utf-8"))
    print(f"AUDIT_JSON={args.output}")
    print("PHASE220_BOUNDED_AUDIT_" + ("PASS" if not summary["counts"]["failed"] and not summary["counts"]["timeout"] else "ISSUES"))
    return 0 if not summary["counts"]["failed"] and not summary["counts"]["timeout"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
