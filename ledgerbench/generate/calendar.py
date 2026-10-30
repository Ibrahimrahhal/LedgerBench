"""
Dates as the generator writes them.

Questions name their period in words ("in March 2026", "between 9 and 22 March
2026, inclusive", "on 12 March 2026"); messages only ever use relative words
("yesterday", "on Tuesday", "on the 3rd"). Nothing here writes an ISO date into
text: ISO is for the JSON only.
"""

from __future__ import annotations

from datetime import date, timedelta

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)  # fmt: skip
WEEKEND = ("Saturday", "Sunday")
WORKDAYS = WEEKDAYS[:5]


def iso(d: date) -> str:
    return d.isoformat()


def parse(s: str) -> date:
    return date.fromisoformat(s)


def weekday(d: date) -> str:
    return WEEKDAYS[d.weekday()]


def month_name(d: date) -> str:
    return MONTHS[d.month - 1]


def long_date(d: date) -> str:
    """12 March 2026"""
    return f"{d.day} {month_name(d)} {d.year}"


def long_date_wd(d: date) -> str:
    """Thursday 12 March 2026"""
    return f"{weekday(d)} {d.day} {month_name(d)} {d.year}"


def month_label(year: int, month: int) -> str:
    return f"{MONTHS[month - 1]} {year}"


def ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def days_in_month(year: int, month: int) -> int:
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    return (nxt - timedelta(days=1)).day


def month_end(d: date) -> date:
    return date(d.year, d.month, days_in_month(d.year, d.month))


def next_month_start(d: date) -> date:
    return date(d.year + (d.month == 12), d.month % 12 + 1, 1)


def next_monday(d: date) -> date:
    """The Monday after d (never d itself)."""
    return d + timedelta(days=7 - d.weekday())


def span(start: date, n: int) -> list[date]:
    return [start + timedelta(days=i) for i in range(n)]


def range_words(a: date, b: date) -> str:
    """'between 9 and 22 March 2026 inclusive' and its cross-month and cross-year forms."""
    if a.year == b.year and a.month == b.month:
        inner = f"{a.day} and {b.day} {month_name(a)} {a.year}"
    elif a.year == b.year:
        inner = f"{a.day} {month_name(a)} and {b.day} {month_name(b)} {a.year}"
    else:
        inner = f"{long_date(a)} and {long_date(b)}"
    return f"between {inner} inclusive"


def week_words(monday: date) -> str:
    sunday = monday + timedelta(days=6)
    if monday.month == sunday.month:
        return f"in the week from Monday {monday.day} to Sunday {sunday.day} {month_name(sunday)} {sunday.year}"
    if monday.year == sunday.year:
        return f"in the week from Monday {monday.day} {month_name(monday)} to Sunday {sunday.day} {month_name(sunday)} {sunday.year}"
    return f"in the week from Monday {long_date(monday)} to Sunday {long_date(sunday)}"


def relative_day(when: date, said_on: date) -> str:
    """How a person refers back to `when` on `said_on`: yesterday, on Tuesday, last Tuesday, on the 3rd."""
    lag = (said_on - when).days
    if lag == 0:
        return "today"
    if lag == 1:
        return "yesterday"
    if lag <= 6:
        return f"on {weekday(when)}"
    if lag <= 13 and when.month == said_on.month:
        return f"on the {ordinal(when.day)}"
    if lag <= 13:
        return f"on the {ordinal(when.day)} of {month_name(when)}"
    raise ValueError("too far back to refer to casually")
