"""Pure turnaround-time calculations (no database access) so they are easy to unit test."""

from datetime import datetime


def minutes_between(start: datetime | None, end: datetime | None) -> float | None:
    """Elapsed minutes from start to end, or None if either timestamp is missing.

    Raises ValueError if end precedes start - that indicates corrupt timestamps.
    """
    if start is None or end is None:
        return None
    if end < start:
        raise ValueError("end timestamp precedes start timestamp")
    return (end - start).total_seconds() / 60


def turnaround_minutes(arrival_at: datetime | None, departed_at: datetime | None) -> float | None:
    """Turnaround = truck arrival at the site to departure."""
    return minutes_between(arrival_at, departed_at)


def loading_minutes(started_at: datetime | None, finished_at: datetime | None) -> float | None:
    return minutes_between(started_at, finished_at)


def is_within_target(turnaround: float | None, target_minutes: int) -> bool | None:
    if turnaround is None:
        return None
    return turnaround <= target_minutes


def percent(part: int | float, whole: int | float) -> float | None:
    """Percentage rounded to 1 dp, or None when there is nothing to measure."""
    if not whole:
        return None
    return round(part / whole * 100, 1)
