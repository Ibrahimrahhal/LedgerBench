"""The scorer, case by case. Each case is (reply, expected correct), against a small question."""

from __future__ import annotations

from datetime import date

import pytest

from ledgerbench.dataset import Question
from ledgerbench.scoring import JUDGE, Verdict, answer_span, find_dates, pick_number, score

CATEGORIES = (
    "groceries", "eating out", "coffee", "transport", "rent", "utilities", "subscriptions",
    "health", "clothing", "entertainment", "travel", "gifts", "household", "other",
)  # fmt: skip
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def q(
    answer_type: str, gold, *, question: str = "How much did I spend on groceries in February 2026?", **kw
) -> Question:
    defaults = {"rel_tol": 0.01, "abs_tol": 0.005, "asked_on": "2026-04-04", "gold_text": str(gold)}
    defaults.update(kw)
    return Question(
        id="u1:q1",
        domain="spending",
        skills=("aggregate",),
        question=question,
        answer_type=answer_type,
        gold=gold,
        **defaults,
    )


MONEY = q("number", 412.35)

# ------------------------------------------------------------------ the answer line

ANSWER_LINES = [
    ("Answer: 412.35", "412.35", True),
    ("Some working.\nAnswer: 412.35 EUR", "412.35 EUR", True),
    ("**Answer:** 412.35", "412.35", True),
    ("**Answer: 412.35**", "412.35", True),
    ("__Answer__: 412.35", "412.35", True),
    ("### Answer: 412.35", "412.35", True),
    ("> Answer: 412.35", "412.35", True),
    ("- Answer: 412.35", "412.35", True),
    ("answer: 412.35", "412.35", True),
    ("Final answer: 412.35", "412.35", True),
    ("Answer: 100\nWait, I miscounted.\nAnswer: 412.35", "412.35", True),
    ("**Answer:**\n412.35", "412.35", True),
    ("You spent 412.35 on groceries.", "You spent 412.35 on groceries.", False),
    ("The answer: 412.35", "The answer: 412.35", False),
]


@pytest.mark.parametrize(("reply", "span", "format_ok"), ANSWER_LINES)
def test_answer_span(reply, span, format_ok):
    assert answer_span(reply) == (span, format_ok)


# ------------------------------------------------------------------------ numbers

NUMBERS = [
    ("Answer: 412.35", True),
    ("Answer: €412.35", True),
    ("Answer: 412.35 €", True),
    ("Answer: EUR 412.35", True),
    ("Answer: 412.35 EUR", True),
    ("Answer: 412,35 €", True),  # decimal comma
    ("Answer: about 412.4", True),  # within 1%
    ("Answer: roughly €410", True),  # 0.57% off: within rel_tol 0.01
    ("Answer: 400", False),  # 3% off
    ("Answer: 41.24", False),
    ("Answer: In February 2026 you spent €412.35 on groceries.", True),  # the question's year comes first
    ("Answer: From 1 to 28 February 2026: 412.35", True),  # a date range before the number
    ("Answer: 2026-02-01 to 2026-02-28: 412.35", True),
    ("Answer: 46.20 + 64.20 + 301.95 = 412.35", True),  # the total after "="
    ("Answer: unknown", False),
    ("Answer: I don't know", False),
    ("You spent about 412.35 euros in February.", True),  # no Answer line: whole reply
    ("Answer: **412.35**", True),
    ("Answer: `412.35`", True),
]


@pytest.mark.parametrize(("reply", "expected"), NUMBERS)
def test_number(reply, expected):
    assert score(MONEY, reply).correct is expected


def test_thousands_separator_and_codes():
    question = q("number", 1675.0)
    for reply in ("Answer: $1,675", "Answer: 1,675.00 USD", "Answer: USD 1,675", "Answer: US$1,675.00", "Answer: 1675"):
        assert score(question, reply).correct, reply
    assert score(question, "Answer: 1,6750").correct is False


def test_big_thousands():
    assert score(q("number", 12450.5), "Answer: €12,450.50").correct
    assert score(q("number", 1240.0), "Answer: 1,240").correct


def test_units_after_numbers():
    kcal = q("number", 2150.0, question="How many kcal did I eat on 12 March 2026?", abs_tol=0.5)
    assert score(kcal, "Answer: 2,150 kcal").correct
    assert score(kcal, "Answer: 2150kcal").correct
    protein = q("number", 38.0, question="How much protein did I have at lunch on 3 March 2026?", abs_tol=0.5)
    assert score(protein, "Answer: 38g").correct
    assert score(protein, "Answer: 38 g of protein").correct
    weight = q("number", 72.4, question="What did I weigh on 3 March 2026?", abs_tol=0.05)
    assert score(weight, "Answer: 72.4kg").correct
    assert score(weight, "Answer: 72.4 kg on 3 March 2026").correct
    assert score(q("number", 160.0, abs_tol=0.05), "Answer: 160 lb").correct


def test_negative_numbers():
    change = q("number", -1.6, question="How much did my weight change in March 2026?", abs_tol=0.05)
    assert score(change, "Answer: -1.6 kg").correct
    assert score(change, "Answer: −1.6 kg").correct  # a real minus sign
    assert score(change, "Answer: –1.6 kg").correct  # an en dash typed as a minus
    assert score(change, "Answer: lost 1.6 kg").correct  # the wording carries the sign
    assert score(change, "Answer: down by about 1.6 kg").correct
    assert score(change, "Answer: 1.6 kg lighter").correct
    assert score(change, "Answer: 1.6 kg").correct is False  # direction missing
    assert score(change, "Answer: +1.6 kg").correct is False
    gained = q("number", 1.6, question="How much did my weight change in March 2026?", abs_tol=0.05)
    assert score(gained, "Answer: -1.6 kg").correct is False
    assert score(gained, "Answer: gained 1.6 kg").correct


def test_budget_left_negative():
    left = q("number", -12.4, question="How much of my eating-out budget of 150 is left for March 2026?")
    assert score(left, "Answer: -€12.40").correct
    assert score(left, "Answer: €-12.40").correct
    assert score(left, "Answer: You are over budget by €12.40").correct
    assert score(left, "Answer: 12.40 EUR over budget").correct
    assert score(left, "Answer: 12.40").correct is False


def test_question_numbers_are_skipped():
    question = q(
        "number", 42.1, question="How much did I spend on coffee in the 2 weeks from 2 March to 15 March 2026?"
    )
    assert score(question, "Answer: In the 2 weeks you spent 42.10").correct
    assert score(question, "Answer: 2 weeks: €42.10").correct
    # When the answer really is a number the question names, it is still read.
    two = q("count", 2, question="How many times did I skip legs in the 2 weeks from 2 March to 15 March 2026?")
    assert score(two, "Answer: 2").correct
    assert score(two, "Answer: 2 times").correct


def test_sets_by_reps_are_skipped():
    weight = q("number", 80.0, question="What was my bench working weight on 1 March 2026?", abs_tol=0.05)
    assert score(weight, "Answer: 4x6 at 80 kg").correct
    assert score(weight, "Answer: 80 kg (4x6)").correct


def test_count_is_exact():
    count = q("count", 7, question="How many times did I eat out in March 2026?")
    assert score(count, "Answer: 7").correct
    assert score(count, "Answer: 7 times").correct
    assert score(count, "Answer: seven").correct is False  # words are not read
    assert score(count, "Answer: 7.0").correct
    assert score(count, "Answer: 8").correct is False
    assert score(count, "Answer: 6.9").correct is False


def test_number_trap_repeats_question_then_answer():
    question = q(
        "number",
        18.5,
        question="What was my average sleep from 1 March to 7 March 2026, in hours, over 7 nights?",
        abs_tol=0.05,
    )
    assert score(question, "Answer: Over the 7 nights from 1 to 7 March 2026 it was 18.5").correct


SLEEP = q(
    "number",
    7.75,
    question="Going by the most recent night I logged, how many hours am I sleeping now?",
    unit="hours",
    abs_tol=0.05,
)

DURATIONS = [
    ("Answer: 7 hours 45 minutes.", True),  # the u3:q11 reply in the first smoke run, once read as 7
    ("Answer: 7 hours 45 minutes", True),
    ("Answer: 7 hours and 45 minutes", True),
    ("Answer: 7 hours, 45 minutes", True),
    ("Answer: 7 hours 45", True),
    ("Answer: 7 hours 45.", True),
    ("Answer: 7 hrs 45 mins", True),
    ("Answer: 7h45", True),
    ("Answer: 7h45m", True),
    ("Answer: 7h 45m", True),
    ("Answer: 7 h 45 min", True),
    ("Answer: 7:45 hours", True),
    ("Answer: 7:45 h", True),
    ("Answer: 7.75 hours", True),  # decimals still work
    ("Answer: 7.75", True),
    ("Answer: about 7 hours 45 minutes a night", True),
    ("Answer: 7 hours 45 minutes (7.75 hours)", True),
    ("Answer: 7 hours", False),  # the minutes are missing
    ("Answer: 7 hours 30 minutes", False),
    ("Answer: 7h30", False),
    ("Answer: 8 hours 45 minutes", False),
    ("Answer: 7:45", False),  # without a unit it reads as a clock time, as before
    ("Answer: 7 hours 75 minutes", False),  # not a duration: 7 is the first number
]


@pytest.mark.parametrize(("reply", "expected"), DURATIONS)
def test_durations_in_hours(reply, expected):
    assert score(SLEEP, reply).correct is expected


def test_duration_after_a_number_the_question_restates():
    question = q(
        "number",
        7.75,
        question="What was my average sleep per night, in hours, over the 3 weeks between 2 and 22 March 2026 inclusive?",
        unit="hours",
        abs_tol=0.05,
    )
    assert score(question, "Answer: Over the 3 weeks it came to 7 hours 45 a night.").correct
    assert score(question, "Answer: 3 weeks: 7h45 on average").correct
    assert score(question, "Answer: Between 2 and 22 March 2026, 7 hours 45 minutes").correct
    assert score(question, "Answer: Over the 3 weeks, 7 hours").correct is False
    result = score(question, "Answer: Over the 3 weeks it came to 7 hours 45 a night.")
    assert result.extracted == "7.75"


def test_durations_in_minutes():
    run = q("number", 75.0, question="How long did my run on 3 March 2026 take, in minutes?", unit="minutes")
    assert score(run, "Answer: 1 hour 15 minutes").correct
    assert score(run, "Answer: 1 hour 5 minutes").correct is False  # 65, not 75
    assert score(run, "Answer: 1").correct is False
    assert score(q("number", 65.0, unit="minutes", abs_tol=0.5), "Answer: 1 hour 5 minutes").correct
    assert score(q("number", 65.0, unit="minutes", abs_tol=0.5), "Answer: 1h05").correct
    assert score(q("number", 65.0, unit="minutes", abs_tol=0.5), "Answer: 65 min").correct


def test_durations_only_for_duration_units():
    money = q("number", 7.0, unit="EUR")
    assert score(money, "Answer: 7 hours 45 minutes").correct  # not a duration question: the first number
    kcal = q("number", 7.75, unit="kcal", abs_tol=0.5)
    assert pick_number("7h45", "", "kcal").value == 7
    assert score(kcal, "Answer: 7.75 kcal").correct


def test_extracted_and_reason_are_reported():
    result = score(MONEY, "**Answer:** about €412.35")
    assert result.correct and result.extracted == "412.35" and result.method == "deterministic" and result.format_ok
    assert "tolerance" in result.reason


def test_pick_number_returns_none_without_numbers():
    assert pick_number("no numbers here") is None


# -------------------------------------------------------------------------- dates

DATE_Q = q("date", "2026-03-12", question="On which day in March 2026 did I weigh the least?", asked_on="2026-04-04")

DATES = [
    ("Answer: 2026-03-12", True),
    ("Answer: 12 March 2026", True),
    ("Answer: 12 March", True),  # the year from asked_on
    ("Answer: March 12th", True),
    ("Answer: March 12, 2026", True),
    ("Answer: 12th of March", True),
    ("Answer: Mar 12", True),
    ("Answer: Mar. 12", True),
    ("Answer: Thursday, 12 March 2026", True),  # with a weekday
    ("Answer: Thursday 12 March", True),
    ("Answer: on the 12th of March 2026", True),
    ("Answer: 12/03", False),  # ambiguous numeric forms are never read
    ("Answer: 03/12/2026", False),
    ("Answer: 12.03.2026", False),
    ("Answer: 13 March 2026", False),
    ("Answer: 12 March 2025", False),
    ("Answer: Thursday", False),
    ("Answer: unknown", False),
]


@pytest.mark.parametrize(("reply", "expected"), DATES)
def test_date(reply, expected):
    assert score(DATE_Q, reply).correct is expected


def test_first_date_wins():
    assert score(DATE_Q, "Answer: 12 March 2026 (not 14 March)").correct
    assert score(DATE_Q, "Answer: 14 March, or maybe 12 March").correct is False


def test_missing_year_across_new_year():
    december = q("date", "2025-12-28", asked_on="2026-01-10")
    assert score(december, "Answer: 28 December").correct
    january = q("date", "2026-01-03", asked_on="2026-01-10")
    assert score(january, "Answer: January 3rd").correct


def test_find_dates_ignores_invalid():
    assert find_dates("31 February 2026, then 1 March 2026") == [(23, 35, date(2026, 3, 1))]


# ---------------------------------------------------------------------- categories

CATEGORY_Q = q(
    "category",
    "eating out",
    question="Which category did I spend the most on in February 2026?",
    aliases=("restaurants", "dining out"),
    choices=CATEGORIES,
)

CATEGORY_CASES = [
    ("Answer: eating out", True),
    ("Answer: Eating Out", True),
    ("Answer: eating-out", True),
    ("Answer: **Eating out**", True),
    ("Answer: restaurants", True),  # an alias
    ("Answer: Dining out (€310.20)", True),
    ("Answer: groceries", False),
    ("Answer: eating out and groceries", False),  # a second choice
    (
        "Answer: groceries, eating out, coffee, transport, rent, utilities, subscriptions, health, clothing, entertainment, travel, gifts, household, other",
        False,
    ),  # every category
    ("Answer: eating", False),
    ("Answer: unknown", False),
    ("I think it was eating out.", True),  # no Answer line: the whole reply, format not ok
]


@pytest.mark.parametrize(("reply", "expected"), CATEGORY_CASES)
def test_category(reply, expected):
    assert score(CATEGORY_Q, reply).correct is expected


def test_category_whole_words_only():
    coffee = q("category", "coffee", choices=CATEGORIES)
    assert score(coffee, "Answer: coffees").correct  # a plural
    assert score(coffee, "Answer: coffeehouse").correct is False
    other = q("category", "rent", choices=CATEGORIES)
    assert score(other, "Answer: rent").correct
    assert score(other, "Answer: rent, then other things").correct is False  # "other" is a choice


def test_longer_choice_masks_shorter():
    exercises = ("Bench press", "Incline bench press", "Squat", "Front squat")
    incline = q("category", "Incline bench press", choices=exercises)
    assert score(incline, "Answer: incline bench press").correct
    bench = q("category", "Bench press", choices=exercises)
    assert score(bench, "Answer: incline bench press").correct is False
    assert score(bench, "Answer: bench press").correct


# --------------------------------------------------------------------------- sets

SET_Q = q(
    "set", ("Tuesday", "Friday"), question="Which days am I training legs now?", gold_text="Tuesday and Friday",
    aliases={"Tuesday": ["Tue", "Tues"], "Friday": ["Fri"]}, choices=WEEKDAYS,
)  # fmt: skip

SETS = [
    ("Answer: Tuesday and Friday", True),
    ("Answer: Friday, Tuesday", True),
    ("Answer: Tuesdays and Fridays", True),
    ("Answer: Tue, Fri", True),
    ("Answer: tuesday & friday", True),
    ("Answer: Tuesday", False),  # a member missing
    ("Answer: Tuesday, Thursday and Friday", False),  # a non-member
    ("Answer: Monday, Tuesday, Wednesday, Thursday, Friday, Saturday, Sunday", False),  # every choice
    ("Answer: none", False),
    ("Answer: unknown", False),
]


@pytest.mark.parametrize(("reply", "expected"), SETS)
def test_set(reply, expected):
    assert score(SET_Q, reply).correct is expected


def test_set_with_parallel_alias_lists():
    question = q("set", ("Monday", "Thursday"), aliases=(("Mon",), ("Thu", "Thurs")), choices=WEEKDAYS)
    assert score(question, "Answer: Mon and Thurs").correct
    assert score(question, "Answer: Mon").correct is False


def test_empty_set_needs_none():
    empty = q(
        "set",
        (),
        question="On which days did I skip a planned session in the week of 9 March 2026?",
        gold_text="none",
        choices=WEEKDAYS,
    )
    assert score(empty, "Answer: none").correct
    assert score(empty, "Answer: No days, you did every session.").correct
    assert score(empty, "Answer: unknown").correct is False
    assert score(empty, "Answer: I don't know").correct is False
    assert score(empty, "Answer: Monday").correct is False
    assert score(empty, "Answer: none except Monday").correct is False


# --------------------------------------------------------------------------- text

TEXT_Q = q(
    "text", None, question="What is my plan on Fridays now?", gold_text="Legs: squat 5x5 at 100 kg, RDL 3x8 at 80 kg"
)


def test_text_exact_match_needs_no_judge():
    result = score(TEXT_Q, "Answer: Legs: squat 5x5 at 100 kg, RDL 3x8 at 80 kg")
    assert result.correct and result.method == "deterministic"


def test_text_abstention_needs_no_judge():
    for reply in (
        "I don't know.\nAnswer: unknown",
        "Answer: I do not know",
        "Answer: not enough information",
        "Answer:",
    ):
        result = score(TEXT_Q, reply)
        assert result.correct is False and result.method == "deterministic", reply


def test_text_without_judge_is_unjudged():
    result = score(TEXT_Q, "Answer: legs day with squats and RDLs")
    assert result.correct is None and result.method == JUDGE


def test_text_goes_to_the_judge():
    calls = []

    def judge(question, gold, answer):
        calls.append((question, gold, answer))
        return Verdict(True, "same plan", "fake-judge", {"cost_usd": 0.001})

    result = score(TEXT_Q, "Thinking...\nAnswer: legs: squats 5x5 @ 100, RDLs 3x8 @ 80", judge=judge)
    assert result.correct and result.method == JUDGE and result.judge_model == "fake-judge"
    assert calls == [(TEXT_Q.question, TEXT_Q.gold_text, "legs: squats 5x5 @ 100, RDLs 3x8 @ 80")]
