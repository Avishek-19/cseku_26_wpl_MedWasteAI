"""Run the outbox worker independently from uvicorn.

Examples (from backend/):
    python scripts/run_workflow_worker.py --once
    python scripts/run_workflow_worker.py --interval 15

The heartbeat is a local-process diagnostic, not a distributed lease. Run ONE
worker unless claim/locking and distributed orchestration are configured.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.db import SessionLocal  # noqa: E402
from app.services.workflow_orchestrator import run_workflow_batch  # noqa: E402

LOG = logging.getLogger("medwaste.workflow_worker")
stop_requested = False


def request_stop(_signum, _frame):
    global stop_requested
    stop_requested = True


def write_heartbeat(path: Path, *, success: bool, processed: object = None, error: str | None = None):
    """Atomic heartbeat update so a monitor never observes incomplete JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"updated_at": datetime.now(timezone.utc).isoformat(), "success": success,
            "processed": str(processed) if processed is not None else None,
            "error": error[:300] if error else None}
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data), encoding="utf-8")
    temp.replace(path)


def run_once(health_path: Path) -> bool:
    try:
        with SessionLocal() as db:
            count = run_workflow_batch(db)
            from app.services.payment_reconciliation import reconcile_payment_batch
            if isinstance(count, dict):
                count["payments"] = reconcile_payment_batch(db)
        write_heartbeat(health_path, success=True, processed=count)
        LOG.info("Outbox batch completed: %s", count)
        return True
    except Exception as exc:
        # The SQLAlchemy session is closed even if a DB outage occurs. Do not
        # mark a failed batch as healthy or silently acknowledge the outbox.
        write_heartbeat(health_path, success=False, error=str(exc))
        LOG.exception("Outbox worker batch failed; will retry unless --once")
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MedWaste AI outbox worker")
    parser.add_argument("--once", action="store_true", help="Process one batch and exit nonzero on failure")
    parser.add_argument("--interval", type=float, default=15, help="Seconds between batches (min 1)")
    parser.add_argument("--health-file", type=Path, default=Path(os.environ.get(
        "WORKFLOW_HEALTH_FILE", ".runtime/workflow_worker.json")))
    args = parser.parse_args(argv)
    if args.interval < 1:
        parser.error("--interval must be at least 1 second")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    signal.signal(signal.SIGINT, request_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, request_stop)
    while not stop_requested:
        ok = run_once(args.health_file)
        if args.once:
            return 0 if ok else 1
        # Short sleeps allow orderly Ctrl+C/termination without waiting a full interval.
        remaining = args.interval
        while remaining > 0 and not stop_requested:
            sleep_for = min(remaining, 0.5)
            time.sleep(sleep_for)
            remaining -= sleep_for
    LOG.info("Outbox worker stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
