"""US market (NYSE/NASDAQ) holiday calendar.

Lightweight implementation — no external dependency. Covers all NYSE-observed
holidays using standard federal holiday rules. Updates needed only if NYSE
changes its holiday schedule (rare).

Usage::

    from src.utils.market_holidays import is_us_market_holiday
    if is_us_market_holiday(date.today()):
        logger.info("US markets closed today — skipping cycle")
"""

from datetime import date


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """Return the *n*-th occurrence of *weekday* (0=Mon) in *month*/*year*."""
    first = date(year, month, 1)
    # Days until first occurrence of weekday
    offset = (weekday - first.weekday()) % 7
    return date(year, month, 1 + offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    """Return the last occurrence of *weekday* in *month*/*year*."""
    # Start from 5th occurrence and work back
    for n in (5, 4):
        try:
            d = _nth_weekday(year, month, weekday, n)
            if d.month == month:
                return d
        except ValueError:
            continue
    return _nth_weekday(year, month, weekday, 4)


def us_market_holidays(year: int) -> set[date]:
    """Return the set of NYSE-observed holidays for *year*.

    Covers:
      - New Year's Day (Jan 1, or nearest weekday)
      - Martin Luther King Jr. Day (3rd Mon Jan)
      - Presidents' Day (3rd Mon Feb)
      - Good Friday (Friday before Easter)
      - Memorial Day (last Mon May)
      - Juneteenth (Jun 19, or nearest weekday) — observed since 2022
      - Independence Day (Jul 4, or nearest weekday)
      - Labor Day (1st Mon Sep)
      - Thanksgiving (4th Thu Nov)
      - Christmas Day (Dec 25, or nearest weekday)

    When a holiday falls on Saturday, NYSE observes Friday.
    When a holiday falls on Sunday, NYSE observes Monday.
    """
    holidays: set[date] = set()

    def _observe(d: date) -> date:
        if d.weekday() == 5:  # Saturday → Friday
            return date(d.year, d.month, d.day - 1)
        if d.weekday() == 6:  # Sunday → Monday
            return date(d.year, d.month, d.day + 1)
        return d

    # New Year's Day
    holidays.add(_observe(date(year, 1, 1)))

    # MLK Day — 3rd Monday of January
    holidays.add(_nth_weekday(year, 1, 0, 3))

    # Presidents' Day — 3rd Monday of February
    holidays.add(_nth_weekday(year, 2, 0, 3))

    # Good Friday — Friday before Easter Sunday
    holidays.add(_easter_friday(year))

    # Memorial Day — last Monday of May
    holidays.add(_last_weekday(year, 5, 0))

    # Juneteenth — June 19 (observed since 2022)
    if year >= 2022:
        holidays.add(_observe(date(year, 6, 19)))

    # Independence Day — July 4
    holidays.add(_observe(date(year, 7, 4)))

    # Labor Day — 1st Monday of September
    holidays.add(_nth_weekday(year, 9, 0, 1))

    # Thanksgiving — 4th Thursday of November
    holidays.add(_nth_weekday(year, 11, 3, 4))

    # Christmas Day — December 25
    holidays.add(_observe(date(year, 12, 25)))

    return holidays


def _easter_friday(year: int) -> date:
    """Compute Good Friday via the Anonymous Gregorian algorithm for Easter."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    # Easter Sunday; Good Friday is 2 days before
    easter = date(year, month, day)
    from datetime import timedelta
    return easter - timedelta(days=2)


def is_us_market_holiday(d: date | None = None) -> bool:
    """Return True if *d* (default: today) is a US market holiday."""
    if d is None:
        d = date.today()
    return d in us_market_holidays(d.year)
