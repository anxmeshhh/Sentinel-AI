"""Phase 2t: deterministic deadline extraction.

Most of these tests are about what must NOT be detected. A hallucinated or
over-eager deadline sends someone chasing a commitment that doesn't exist,
which costs more trust than a missed one.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.services.deadline_parser import find_deadline

# A fixed Wednesday, so weekday arithmetic is checkable by hand.
NOW = datetime(2026, 7, 15, 9, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "text",
    [
        "Sprint planning on Friday",  # a date, but no commitment
        "Meeting November 30 with the team",
        "Notes from yesterday's review",
        "Re: roadmap doc — added Q4 section",
        "Your order shipped",
        "",
    ],
)
def test_dates_without_a_deadline_keyword_are_not_deadlines(text):
    assert find_deadline(text, now=NOW) is None


@pytest.mark.parametrize(
    "text",
    [
        "Payment due",  # keyword, no date
        "Deadline approaching",
        "Submit by end of quarter",  # unparseable period
    ],
)
def test_keyword_without_a_resolvable_date_is_not_a_deadline(text):
    assert find_deadline(text, now=NOW) is None


def test_iso_date():
    due = find_deadline("Contract expires 2026-08-01", now=NOW)
    assert due is not None and due.date() == datetime(2026, 8, 1).date()


@pytest.mark.parametrize(
    "text,expected_day,expected_month",
    [
        # All kept inside the 120-day horizon from NOW (15 July) - a date
        # further out is correctly *not* a deadline, which
        # test_deadlines_beyond_the_horizon_are_dropped covers separately.
        ("Invoice due 30 September", 30, 9),
        ("Invoice due September 30", 30, 9),
        ("Renewal deadline 5th Aug", 5, 8),
        ("Submission closes Sept 12", 12, 9),
    ],
)
def test_written_month_formats(text, expected_day, expected_month):
    due = find_deadline(text, now=NOW)
    assert due is not None
    assert (due.day, due.month) == (expected_day, expected_month)


def test_relative_days_and_weeks():
    assert find_deadline("Invoice INV-2291 is due in 3 days", now=NOW).date() == (NOW + timedelta(days=3)).date()
    assert find_deadline("Renewal due in 2 weeks", now=NOW).date() == (NOW + timedelta(weeks=2)).date()


def test_tomorrow_and_today():
    assert find_deadline("Reply by tomorrow please", now=NOW).date() == (NOW + timedelta(days=1)).date()
    assert find_deadline("Last day is today", now=NOW).date() == NOW.date()


def test_weekday_resolves_forward():
    # NOW is a Wednesday; "by Friday" is 2 days out.
    assert find_deadline("Respond by Friday", now=NOW).date() == (NOW + timedelta(days=2)).date()


def test_same_weekday_means_next_week_not_today():
    """"Reply by Wednesday" sent on a Wednesday means the *next* one -
    resolving it to today would silently mark it already overdue."""
    assert find_deadline("Reply by Wednesday", now=NOW).date() == (NOW + timedelta(days=7)).date()


def test_bare_month_day_rolls_to_next_year_when_already_past():
    december = datetime(2026, 12, 20, 9, 0, tzinfo=timezone.utc)
    due = find_deadline("Renewal due 5 January", now=december)
    assert due is not None and (due.year, due.month, due.day) == (2027, 1, 5)


def test_past_deadlines_are_dropped():
    assert find_deadline("Invoice was due 1 January", now=NOW) is None


def test_deadlines_beyond_the_horizon_are_dropped():
    """Something due in eight months is a calendar entry, not attention."""
    assert find_deadline("Contract expires 2027-06-01", now=NOW) is None


def test_ambiguous_numeric_dates_are_deliberately_ignored():
    """11/12 is 11 December or November 12 depending on the writer. Guessing
    produces a confidently wrong deadline, so the parser stays silent."""
    assert find_deadline("Payment due 11/12", now=NOW) is None


def test_impossible_dates_do_not_crash():
    assert find_deadline("Offer expires 31 February", now=NOW) is None


def test_case_insensitive():
    assert find_deadline("PAYMENT DUE IN 2 DAYS", now=NOW) is not None
