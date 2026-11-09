"""One-command, read-only QuantEngine operator diagnostic.

Runs offline configuration checks first. Only a clean, exact Delta
region/environment + credential configuration proceeds to the read-only
identity and public product-catalog probe. No exchange writes are used.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from scripts.check_delta_connection import check_connection
from scripts.quantengine_preflight import inspect_configuration


def run_doctor(*, preflight=inspect_configuration, connection_check=check_connection, emit=print):
    report = preflight()
    if not isinstance(report, dict) or not report.get("ready_for_authenticated_read_only_check"):
        emit("Offline configuration preflight: NOT READY")
        if isinstance(report, dict):
            for error in report.get("errors", ()):
                emit("ERROR: " + str(error))
        emit("No network request was attempted.")
        return 1

    emit("Offline configuration preflight: PASS")
    emit("Selected venue: {}/{}".format(report["region"], report["environment"]))
    emit("Live execution flags: DISARMED")
    return connection_check(emit=emit)


def main() -> int:
    return run_doctor()


if __name__ == "__main__":
    raise SystemExit(main())
