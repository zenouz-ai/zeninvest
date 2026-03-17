"""Tests for US market holiday calendar."""

from datetime import date

from src.utils.market_holidays import is_us_market_holiday, us_market_holidays


def test_known_2026_holidays():
    """Verify well-known 2026 NYSE holidays."""
    holidays = us_market_holidays(2026)
    # New Year's Day: Jan 1, 2026 is Thursday
    assert date(2026, 1, 1) in holidays
    # MLK Day: 3rd Monday of January = Jan 19
    assert date(2026, 1, 19) in holidays
    # Presidents' Day: 3rd Monday of February = Feb 16
    assert date(2026, 2, 16) in holidays
    # Good Friday: April 3, 2026
    assert date(2026, 4, 3) in holidays
    # Memorial Day: last Monday of May = May 25
    assert date(2026, 5, 25) in holidays
    # Juneteenth: June 19, 2026 is Friday
    assert date(2026, 6, 19) in holidays
    # Independence Day: July 4, 2026 is Saturday → observed Friday July 3
    assert date(2026, 7, 3) in holidays
    assert date(2026, 7, 4) not in holidays
    # Labor Day: 1st Monday of September = Sep 7
    assert date(2026, 9, 7) in holidays
    # Thanksgiving: 4th Thursday of November = Nov 26
    assert date(2026, 11, 26) in holidays
    # Christmas: Dec 25, 2026 is Friday
    assert date(2026, 12, 25) in holidays


def test_sunday_observation_shifts_to_monday():
    """When holiday falls on Sunday, observed Monday."""
    holidays = us_market_holidays(2023)
    # Jan 1, 2023 is Sunday → observed Monday Jan 2
    assert date(2023, 1, 2) in holidays
    assert date(2023, 1, 1) not in holidays


def test_saturday_observation_shifts_to_friday():
    """When holiday falls on Saturday, observed Friday."""
    holidays = us_market_holidays(2021)
    # July 4, 2021 is Sunday → observed Monday July 5
    assert date(2021, 7, 5) in holidays
    # Christmas 2021 is Saturday → observed Friday Dec 24
    assert date(2021, 12, 24) in holidays


def test_is_us_market_holiday_returns_false_for_regular_day():
    # A random Tuesday in February
    assert is_us_market_holiday(date(2026, 2, 10)) is False


def test_is_us_market_holiday_returns_true_for_holiday():
    assert is_us_market_holiday(date(2026, 12, 25)) is True


def test_juneteenth_not_observed_before_2022():
    holidays = us_market_holidays(2021)
    assert date(2021, 6, 18) not in holidays  # Would-be observed Friday
    assert date(2021, 6, 19) not in holidays


def test_holiday_count_reasonable():
    """NYSE has 9-10 holidays per year."""
    for year in (2024, 2025, 2026, 2027):
        holidays = us_market_holidays(year)
        assert 9 <= len(holidays) <= 11, f"Year {year}: {len(holidays)} holidays"
