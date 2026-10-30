"""Bounded pytest audit with process-tree timeout cleanup and atomic checkpoints.

This is an audit aid, not a replacement for the repository's canonical full-suite run.
Each test file is run in an isolated pytest subprocess. Results are atomically
checkpointed after every file so interruption does not corrupt the last report.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Replace a JSON report atomically, keeping the temp file beside its target."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def _classify(returncode: int, output: str) -> str:
    lowered = output.lower()
    if returncode == 0:
        return "passed"
    if returncode == 5 and "no tests ran" in lowered:
        return "no_tests"
    if "error collecting" in lowered or "importerror while loading conftest" in lowered:
        return "collection_error"
    return "failed"


def _terminate_process_tree(proc: subprocess.Popen[str]) -> None:
    """Terminate the whole child process group/tree after a timeout.

    Do not return just because the leader exited: a descendant may still hold
    the captured stdout pipe open.
    """
    if os.name == "nt":
        # taskkill /T addresses descendants too; fallback to direct kill if unavailable.
        try:
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=5, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            try:
                proc.kill()
            except OSError:
                pass
    else:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            try:
                proc.kill()
            except OSError:
                pass
            return
        # The leader may exit while a descendant still owns the captured pipe.
        # Always kill the process group after the grace period, not only when
        # proc.wait() times out, so communicate() cannot hang on inherited pipes.
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


def _run_one(path: Path, timeout_seconds: float) -> dict[str, Any]:
    started = time.monotonic()
    popen_kwargs: dict[str, Any] = {}
    if os.name == "nt":
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        popen_kwargs["start_new_session"] = True
    proc = subprocess.Popen(
        [sys.executable, "-m", "pytest", str(path), "-q"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding="utf-8", errors="replace", **popen_kwargs,
    )
    try:
        output, _ = proc.communicate(timeout=timeout_seconds)
        status = _classify(proc.returncode or 0, output)
        code = proc.returncode
    except subprocess.TimeoutExpired as exc:
        _terminate_process_tree(proc)
        prior = exc.output or ""
        if isinstance(prior, bytes):
            prior = prior.decode("utf-8", errors="replace")
        try:
            tail, _ = proc.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            # Never block the audit indefinitely while descendants keep a pipe open.
            if proc.stdout is not None:
                proc.stdout.close()
            tail = ""
        output = (str(prior) + str(tail))[-12000:]
        status, code = "timeout", None
    return {
        "path": str(path),
        "status": status,
        "returncode": code,
        "duration_seconds": round(time.monotonic() - started, 3),
        "output_tail": output[-12000:],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", help="test files/directories; defaults to tests/")
    parser.add_argument("--timeout-seconds", type=float, default=90.0)
    parser.add_argument("--max-files", type=int, default=0, help="0 means no limit")
    parser.add_argument("--output", type=Path, default=Path("phase222_test_audit.json"))
    args = parser.parse_args(argv)
    if args.timeout_seconds <= 0 or args.max_files < 0:
        parser.error("timeout must be positive and max-files nonnegative")
    roots = [Path(p) for p in args.paths] if args.paths else [Path("tests")]
    files: list[Path] = []
    for root in roots:
        if root.is_file():
            files.append(root)
        elif root.is_dir():
            files.extend(p for p in root.rglob("test_*.py") if p.is_file())
        else:
            parser.error(f"path does not exist: {root}")
    files = sorted(dict.fromkeys(p.resolve() for p in files))
    if args.max_files:
        files = files[:args.max_files]
    if not files:
        parser.error("no test files discovered")

    results: list[dict[str, Any]] = []
    started_all = time.monotonic()
    args.output.parent.mkdir(parents=True, exist_ok=True)

    def checkpoint() -> None:
        counts = {key: sum(r["status"] == key for r in results) for key in
                  ("passed", "failed", "timeout", "no_tests", "collection_error")}
        _atomic_write_json(args.output, {
            "schema_version": 2,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "timeout_seconds_per_file": args.timeout_seconds,
            "files_requested": len(files),
            "files_completed": len(results),
            "duration_seconds": round(time.monotonic() - started_all, 3),
            "counts": counts,
            "results": results,
        })

    for path in files:
        result = _run_one(path, args.timeout_seconds)
        results.append(result)
        checkpoint()
        print(f"{result['status'].upper():16} {path} ({result['duration_seconds']}s)", flush=True)
    summary = json.loads(args.output.read_text(encoding="utf-8"))
    print(f"AUDIT_JSON={args.output}")
    clean = not any(summary["counts"][key] for key in ("failed", "timeout", "collection_error"))
    print("PHASE222_BOUNDED_AUDIT_" + ("PASS" if clean else "ISSUES"))
    return 0 if clean else 1


if __name__ == "__main__":
    raise SystemExit(main())
