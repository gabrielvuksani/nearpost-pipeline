from datetime import UTC, datetime, timedelta, timezone

import pytest

from nearpost.timeutil import format_utc, parse_utc, season_of


def test_format_utc_uses_z_suffix_and_drops_microseconds():
    moment = datetime(2026, 10, 10, 11, 30, 5, 123456, tzinfo=UTC)
    assert format_utc(moment) == "2026-10-10T11:30:05Z"


def test_format_utc_converts_other_offsets_to_utc():
    moment = datetime(2026, 10, 10, 12, 30, tzinfo=timezone(timedelta(hours=1)))
    assert format_utc(moment) == "2026-10-10T11:30:00Z"


def test_format_utc_rejects_naive_datetimes():
    with pytest.raises(ValueError, match="timezone-aware"):
        format_utc(datetime(2026, 10, 10, 11, 30))


def test_parse_utc_round_trips():
    assert parse_utc("2026-10-10T11:30:00Z") == datetime(2026, 10, 10, 11, 30, tzinfo=UTC)


def test_parse_utc_rejects_strings_without_offset():
    with pytest.raises(ValueError, match="timezone"):
        parse_utc("2026-10-10T11:30:00")


@pytest.mark.parametrize(
    ("moment", "season"),
    [
        (datetime(2026, 8, 21, tzinfo=UTC), "2026-27"),
        (datetime(2027, 5, 23, tzinfo=UTC), "2026-27"),
        (datetime(2027, 7, 1, tzinfo=UTC), "2027-28"),
        (datetime(2099, 12, 1, tzinfo=UTC), "2099-00"),
    ],
)
def test_season_of_switches_on_first_of_july(moment, season):
    assert season_of(moment) == season
