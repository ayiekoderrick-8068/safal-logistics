from datetime import UTC, datetime, timedelta

import pytest

from app.services.turnaround import (
    is_within_target,
    loading_minutes,
    percent,
    turnaround_minutes,
)

T0 = datetime(2026, 11, 2, 7, 0, tzinfo=UTC)


def test_turnaround_is_arrival_to_departure() -> None:
    assert turnaround_minutes(T0, T0 + timedelta(hours=2, minutes=24)) == 144


def test_missing_timestamp_gives_none() -> None:
    assert turnaround_minutes(T0, None) is None
    assert loading_minutes(None, T0) is None


def test_reversed_timestamps_are_rejected() -> None:
    with pytest.raises(ValueError):
        turnaround_minutes(T0, T0 - timedelta(minutes=1))


@pytest.mark.parametrize(("minutes", "expected"), [(119.9, True), (120, True), (120.1, False)])
def test_target_boundary(minutes: float, expected: bool) -> None:
    assert is_within_target(minutes, 120) is expected


def test_percent_handles_empty_denominator() -> None:
    assert percent(3, 0) is None
    assert percent(2, 3) == 66.7
