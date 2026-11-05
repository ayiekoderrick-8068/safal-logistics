"""LogiTrack background worker.

Runs scheduled checks independently of browser activity:
  * operational alerts (compliance expiry / missing documents, inspections, maintenance,
    loading over target, missed dispatch, overdue deliveries, unresolved delays);
  * housekeeping of expired sign-in throttle counters.

Usage:
    uv run python -m app.worker          # loop, every LOGITRACK_WORKER_INTERVAL_SECONDS
    uv run python -m app.worker --once   # single run, e.g. from cron / a scheduler

Reliability:
  * idempotent - alert refresh deduplicates by condition key (partial unique index) and a
    PostgreSQL advisory lock stops two refreshes overlapping, so several workers, the
    read-time fallback and retries never create duplicates;
  * failures are logged with tracebacks and retried with exponential backoff (capped);
  * each run writes a heartbeat (app_settings.worker_heartbeat) exposed at
    GET /api/alerts/worker-status so staff can see whether checks are current;
  * SIGTERM / SIGINT stop the loop cleanly between runs.
"""

import argparse
import logging
import signal
import sys
import threading
from datetime import UTC, datetime
from typing import Any

from .config import get_settings
from .db import SessionLocal
from .services import throttle
from .services.alerts import refresh_alerts
from .services.app_settings import get_setting, set_setting

log = logging.getLogger("logitrack.worker")
HEARTBEAT_KEY = "worker_heartbeat"


def run_checks(now: datetime | None = None) -> dict[str, int]:
    """One unit of work in its own session/transaction."""
    with SessionLocal() as db:
        stats = refresh_alerts(db, now=now, force=True)
        purged = throttle.purge_expired(db, now)
        db.commit()
    return {**stats, "throttle_counters_purged": purged}


def write_heartbeat(
    ok: bool,
    *,
    stats: dict[str, Any] | None = None,
    error: str | None = None,
    consecutive_failures: int = 0,
    now: datetime | None = None,
) -> None:
    now = now or datetime.now(UTC)
    try:
        with SessionLocal() as db:
            previous = get_setting(db, HEARTBEAT_KEY) or {}
            set_setting(
                db,
                HEARTBEAT_KEY,
                {
                    "last_run_at": now.isoformat(),
                    "last_success_at": now.isoformat() if ok else previous.get("last_success_at"),
                    "status": "ok" if ok else "failed",
                    "last_error": None if ok else (error or "unknown error")[:300],
                    "consecutive_failures": consecutive_failures,
                    "last_stats": stats if ok else previous.get("last_stats"),
                    "interval_seconds": get_settings().worker_interval_seconds,
                },
            )
            db.commit()
    except Exception:  # the heartbeat must never take the worker down
        log.exception("Could not write worker heartbeat")


def backoff_seconds(consecutive_failures: int) -> int:
    s = get_settings()
    if consecutive_failures <= 0:
        return s.worker_interval_seconds
    return min(s.worker_max_backoff_seconds, s.worker_interval_seconds * 2**consecutive_failures)


class Worker:
    def __init__(self) -> None:
        self.stop_event = threading.Event()
        self.consecutive_failures = 0

    def tick(self) -> bool:
        try:
            stats = run_checks()
        except Exception as exc:
            self.consecutive_failures += 1
            log.exception(
                "Scheduled checks failed (attempt %d in a row)", self.consecutive_failures
            )
            write_heartbeat(
                False,
                error=f"{type(exc).__name__}: {exc}",
                consecutive_failures=self.consecutive_failures,
            )
            return False
        self.consecutive_failures = 0
        log.info("Scheduled checks completed: %s", stats)
        write_heartbeat(True, stats=stats)
        return True

    def run(self, max_iterations: int | None = None) -> None:
        done = 0
        log.info("Worker started (interval %ss)", get_settings().worker_interval_seconds)
        while not self.stop_event.is_set():
            self.tick()
            done += 1
            if max_iterations is not None and done >= max_iterations:
                break
            wait = backoff_seconds(self.consecutive_failures)
            if self.consecutive_failures:
                log.warning("Retrying in %ss", wait)
            self.stop_event.wait(wait)
        log.info("Worker stopped")

    def stop(self, *_: Any) -> None:
        self.stop_event.set()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.worker", description="LogiTrack background worker"
    )
    parser.add_argument(
        "--once", action="store_true", help="Run the checks once and exit (for cron)"
    )
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    worker = Worker()
    if args.once:
        return 0 if worker.tick() else 1
    signal.signal(signal.SIGTERM, worker.stop)
    signal.signal(signal.SIGINT, worker.stop)
    worker.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
