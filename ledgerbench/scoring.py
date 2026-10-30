"""
The scorer (spec sections 5.1 and 6).

`score(question, reply)` reads the answer out of a reply and decides whether it
is right, without a model for every answer type but `text`. The rules are
deliberately small and written down here, because a benchmark is only as
trustworthy as its scorer:

1. The answer is the text after the last line that starts with `Answer:`
   (any case, markdown bold, a heading mark, a quote mark or a list dash
   allowed in front, and "Final answer:" too). If that line is empty, the next
   non-empty line is the answer. With no such line the whole reply is used and
   `format_ok` is False; format is reported, never penalised.
2. `number`: the first number in the answer, within
   `max(abs_tol, rel_tol * |gold|)`. `count`: the first number, exactly.
   "First" skips numbers that are not the answer: parts of dates ("12 March
   2026", "1-14 March", "2026-03-01"), clock times, sets-by-reps ("4x6"),
   ordinals, and numbers the question itself states, unless nothing else is
   left. With an "=" in the answer, only the text after the last "=" counts
   ("46.20 + 64.20 = 110.40"). When the gold is negative, an unsigned number
   next to a word of decrease or overspending ("lost 1.6 kg", "12.40 over
   budget") counts as negative.
3. `date`: the first date in the answer, in ISO form or with a month name
   ("12 March", "March 12th", "12th of March", "Mar 12", with or without a
   weekday and year). All-numeric forms like 12/03 are ambiguous and never
   read. A missing year is the year of `asked_on`, or the year before when that
   would put the date more than a month after `asked_on`.
4. `category` and `set`: case-insensitive whole-word matching of the gold (or
   an alias) with an optional plural "s", and no other value from `choices`
   anywhere in the answer, so listing every choice is never rewarded. Longer
   terms win over shorter ones inside them ("incline bench press" does not
   also count as "bench press"). An empty gold set needs a "none" and no
   choice.
5. `text`: an exact match of `gold_text` is right and an empty answer or an
   abstention ("I don't know", "unknown") is wrong, without a model; anything
   else goes to the LLM judge in `ledgerbench.judge`, when one is given. With
   none, `correct` is None (not judged yet).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from ledgerbench.dataset import Question

DETERMINISTIC = "deterministic"
JUDGE = "judge"


@dataclass(frozen=True)
class Score:
    correct: bool | None
    extracted: str | None
    method: str
    reason: str
    format_ok: bool = True
    judge_model: str | None = None
    judge_usage: dict[str, Any] | None = field(default=None, compare=False)


@dataclass(frozen=True)
class Verdict:
    """What a judge returns for one `text` answer."""

    correct: bool
    reason: str
    model: str
    usage: dict[str, Any] | None = None


Judge = Callable[[str, str, str], Verdict]  # (question, gold_text, answer) -> Verdict


# ------------------------------------------------------------------ the answer line

_ANSWER_LINE = re.compile(r"^[\s>#*_`\-]*(?:final\s+)?answer[\s*_`]*:[\s*_`]*(?P<rest>.*)$", re.IGNORECASE)


def _clean(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^[*_`\s]+|[*_`\s]+$", "", text)
    return text.strip()


def answer_span(reply: str) -> tuple[str, bool]:
    """(the answer text, format_ok)."""
    lines = (reply or "").splitlines()
    for i in range(len(lines) - 1, -1, -1):
        match = _ANSWER_LINE.match(lines[i])
        if not match:
            continue
        rest = _clean(match.group("rest"))
        if not rest:
            following = [_clean(line) for line in lines[i + 1 :]]
            following = [line for line in following if line]
            rest = following[0] if following else ""
        return rest, True
    return (reply or "").strip(), False


# --------------------------------------------------------------------- normalising


def _normalise(text: str) -> str:
    text = text.replace("−", "-").replace("–", "-").replace("—", " - ")
    text = text.replace(" ", " ").replace(" ", " ").replace(" ", " ")
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return text


# -------------------------------------------------------------------------- dates

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7,
    "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9,
    "oct": 10, "nov": 11, "dec": 12,
}  # fmt: skip
_MONTH = r"(?P<month>" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\.?"
_ORD = r"(?:st|nd|rd|th)?"

_ISO = re.compile(r"(?<!\d)(?P<year>\d{4})-(?P<m>\d{2})-(?P<day>\d{2})(?!\d)")
_DAY_MONTH = re.compile(rf"\b(?P<day>\d{{1,2}}){_ORD}\s+(?:of\s+)?{_MONTH}(?:,?\s+(?P<year>\d{{4}}))?\b", re.IGNORECASE)
_MONTH_DAY = re.compile(
    rf"\b{_MONTH}\s+(?:the\s+)?(?P<day>\d{{1,2}}){_ORD}\b(?:,?\s+(?P<year>\d{{4}})\b)?", re.IGNORECASE
)


def _resolve(year: int | None, month: int, day: int, asked_on: date | None) -> date | None:
    if year is None:
        if asked_on is None:
            return None
        year = asked_on.year
        try:
            found = date(year, month, day)
        except ValueError:
            return None
        if found > asked_on + timedelta(days=31):
            try:
                return date(year - 1, month, day)
            except ValueError:
                return None
        return found
    try:
        return date(year, month, day)
    except ValueError:
        return None


def find_dates(text: str, asked_on: str | date | None = None) -> list[tuple[int, int, date]]:
    """Every date in `text` as (start, end, date), in order, without overlaps."""
    if isinstance(asked_on, str):
        asked_on = date.fromisoformat(asked_on)
    text = _normalise(text)
    found: list[tuple[int, int, date]] = []
    for m in _ISO.finditer(text):
        d = _resolve(int(m["year"]), int(m["m"]), int(m["day"]), asked_on)
        if d:
            found.append((m.start(), m.end(), d))
    for pattern in (_DAY_MONTH, _MONTH_DAY):
        for m in pattern.finditer(text):
            year = int(m["year"]) if m["year"] else None
            d = _resolve(year, _MONTHS[m["month"].lower()], int(m["day"]), asked_on)
            if d:
                found.append((m.start(), m.end(), d))
    found.sort(key=lambda f: (f[0], -(f[1] - f[0])))
    kept: list[tuple[int, int, date]] = []
    for start, end, d in found:
        if kept and start < kept[-1][1]:
            continue
        kept.append((start, end, d))
    return kept


def first_date(text: str, asked_on: str | date | None = None) -> date | None:
    dates = find_dates(text, asked_on)
    return dates[0][2] if dates else None


# ------------------------------------------------------------------------ numbers

_NUMBER = re.compile(
    r"(?<![\w.])(?P<sign>[-+])?(?:(?:US\$|[€$£]|EUR|USD|GBP)\s?)?(?P<sign2>[-+])?"
    r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?(?!\d)|\d+,\d{1,2}(?![\d,])|\d+(?:\.\d+)?|\.\d+)",
    re.IGNORECASE,
)
_RANGE = r"(?:\s*(?:-|to|and|until|through|till)\s*\d{1,2}" + _ORD + r")?"
_DATEISH = [
    re.compile(r"(?<!\d)\d{4}-\d{2}(?:-\d{2})?(?!\d)"),
    re.compile(rf"\b\d{{1,2}}{_ORD}{_RANGE}\s+(?:of\s+)?{_MONTH}(?:,?\s+\d{{4}})?\b", re.IGNORECASE),
    re.compile(rf"\b{_MONTH}\s+(?:the\s+)?\d{{1,2}}{_ORD}{_RANGE}\b(?:,?\s+\d{{4}}\b)?", re.IGNORECASE),
    re.compile(rf"\b{_MONTH}\s+\d{{4}}\b", re.IGNORECASE),
    re.compile(r"\b(?:week|day|month)\s+\d{1,2}\b", re.IGNORECASE),
]
_CLOCK = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b")
_SETS_REPS = re.compile(r"\b\d+\s*[x×]\s*\d+\b", re.IGNORECASE)
_ORDINAL = re.compile(r"\b\d+(?:st|nd|rd|th)\b", re.IGNORECASE)

_DECREASE = (
    r"down|lost|lose|losing|loss of|decrease[sd]?|a decrease of|dropped|drop of|a drop of|dropping|fell|fallen|"
    r"reduced|reduction of|minus|negative|over budget by|overspent by|overspent|over by|exceeded by|in the red by"
)
_DECREASE_BEFORE = re.compile(
    rf"(?:{_DECREASE})(?:\s+by)?(?:\s+(?:about|around|roughly|approximately|approx\.?|~|just|only))?\s*$", re.IGNORECASE
)
_DECREASE_AFTER = re.compile(
    r"^\s*(?:[a-z%]{1,5}\.?\s*)?(?:less|lower|lighter|fewer|down|over budget|over the budget|over target|overspent|"
    r"below|under what|in the red)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _Number:
    value: float
    text: str
    start: int
    end: int
    signed: bool
    flags: frozenset[str]


def _to_float(raw: str) -> float:
    if re.fullmatch(r"\d+,\d{1,2}", raw):
        return float(raw.replace(",", "."))
    return float(raw.replace(",", ""))


def _spans(patterns: list[re.Pattern[str]], text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for p in patterns for m in p.finditer(text)]


def _inside(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
    return any(s <= start and end <= e for s, e in spans)


def question_numbers(text: str) -> set[float]:
    return {_to_float(m["num"]) for m in _NUMBER.finditer(_normalise(text or ""))}


def find_numbers(text: str, question: str = "") -> list[_Number]:
    text = _normalise(text)
    date_spans = _spans(_DATEISH, text)
    clock_spans = _spans([_CLOCK], text)
    sets_spans = _spans([_SETS_REPS], text)
    ordinal_spans = _spans([_ORDINAL], text)
    in_question = question_numbers(question)
    numbers = []
    for m in _NUMBER.finditer(text):
        start, end = m.start("num"), m.end("num")
        flags = set()
        if _inside(start, end, date_spans):
            flags.add("date")
        if _inside(start, end, clock_spans):
            flags.add("clock")
        if _inside(start, end, sets_spans):
            flags.add("sets")
        if _inside(start, end, ordinal_spans):
            flags.add("ordinal")
        value = _to_float(m["num"])
        negative = (m["sign"] == "-") or (m["sign2"] == "-")
        if value in in_question:
            flags.add("question")
        numbers.append(
            _Number(
                value=-value if negative else value,
                text=m.group(0).strip(),
                start=m.start(),
                end=m.end(),
                signed=bool(m["sign"] or m["sign2"]),
                flags=frozenset(flags),
            )
        )
    return numbers


def pick_number(text: str, question: str = "") -> _Number | None:
    """The answer's number, by the rules in this module's docstring."""
    text = _normalise(text)
    if "=" in text:
        after = text.rsplit("=", 1)[1]
        if find_numbers(after, question):
            text = after
    numbers = find_numbers(text, question)
    if not numbers:
        return None
    for allowed in (set(), {"question"}, {"question", "ordinal", "sets", "clock"}):
        for n in numbers:
            if n.flags <= allowed:
                return n
    return numbers[0]


def _decreasing(text: str, number: _Number) -> bool:
    text = _normalise(text)
    before = text[max(0, number.start - 40) : number.start]
    after = text[number.end : number.end + 30]
    return bool(_DECREASE_BEFORE.search(before) or _DECREASE_AFTER.search(after))


# ------------------------------------------------------------------ categories and sets

_NONE = re.compile(r"\b(?:none|no|nothing|zero|nil|neither)\b|^0$|^-$", re.IGNORECASE)
_ABSTAIN = re.compile(
    r"^(?:unknown|n/?a|not sure|unsure|i\s*(?:do not|don't|dont) know|no idea|cannot (?:be )?(?:determine|determined|tell|say)|"
    r"can't (?:determine|tell|say)|not (?:enough )?information|insufficient information|no (?:record|data|information)"
    r"(?: found| available)?|not recorded|unclear)\b",
    re.IGNORECASE,
)


def _norm_terms(text: str) -> str:
    text = _normalise(text).lower()
    text = re.sub(r"[*`_]", " ", text)
    text = re.sub(r"[-/]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _term_pattern(term: str) -> re.Pattern[str]:
    words = [re.escape(w) for w in _norm_terms(term).split(" ") if w]
    return re.compile(r"(?<![a-z0-9])" + r"\s+".join(words) + r"(?:s|es)?(?![a-z0-9])")


def match_terms(text: str, groups: dict[str, list[str]]) -> set[str]:
    """
    Which groups have a term in `text`. A group is a value and its aliases.
    Longer terms are matched first and mask what they cover, so a shorter term
    inside a longer one ("bench press" in "incline bench press") is not found
    again.
    """
    haystack = _norm_terms(text)
    terms = [(term, key) for key, values in groups.items() for term in values if _norm_terms(term)]
    terms.sort(key=lambda t: len(_norm_terms(t[0])), reverse=True)
    taken: list[tuple[int, int]] = []
    found: set[str] = set()
    for term, key in terms:
        for m in _term_pattern(term).finditer(haystack):
            if any(m.start() < e and s < m.end() for s, e in taken):
                continue
            taken.append((m.start(), m.end()))
            found.add(key)
    return found


def _gold_members(question: Question) -> list[str]:
    gold = question.gold
    if gold is None:
        return []
    if isinstance(gold, (list, tuple)):
        return [str(g) for g in gold]
    return [str(gold)]


def _choice_groups(question: Question, members: list[str]) -> tuple[dict[str, list[str]], set[str]]:
    groups: dict[str, list[str]] = {}
    member_keys = set()
    for member in members:
        key = "gold:" + member.lower()
        member_keys.add(key)
        groups[key] = [member, *question.aliases_for(member)]
    gold_terms = {_norm_terms(t) for key in member_keys for t in groups[key]}
    for choice in question.choices:
        if _norm_terms(choice) in gold_terms:
            continue
        groups.setdefault("other:" + choice.lower(), [choice])
    return groups, member_keys


# --------------------------------------------------------------------------- score


def score(question: Question, reply: str, *, judge: Judge | None = None) -> Score:
    span, format_ok = answer_span(reply)
    kind = question.answer_type
    if kind in ("number", "count"):
        return _score_number(question, span, format_ok)
    if kind == "date":
        return _score_date(question, span, format_ok)
    if kind == "category":
        return _score_terms(question, span, format_ok, single=True)
    if kind == "set":
        return _score_terms(question, span, format_ok, single=False)
    if kind == "text":
        return _score_text(question, span, format_ok, judge)
    raise ValueError(f"{question.id}: unknown answer_type {kind!r}")


def _score_number(question: Question, span: str, format_ok: bool) -> Score:
    number = pick_number(span, question.question)
    if number is None:
        return Score(False, None, DETERMINISTIC, "no number in the answer", format_ok)
    gold = float(question.gold)
    value = number.value
    note = ""
    if gold < 0 and not number.signed and value > 0 and _decreasing(span, number):
        value = -value
        note = " (read as negative from the wording)"
    if question.answer_type == "count":
        ok = abs(value - gold) < 1e-9
        return Score(ok, _fmt(value), DETERMINISTIC, f"count {_fmt(value)}{note} vs gold {_fmt(gold)}", format_ok)
    allowed = max(question.abs_tol, question.rel_tol * abs(gold))
    ok = abs(value - gold) <= allowed + 1e-12
    reason = f"{_fmt(value)}{note} vs gold {_fmt(gold)}, tolerance {_fmt(allowed)}"
    return Score(ok, _fmt(value), DETERMINISTIC, reason, format_ok)


def _fmt(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".") if value != int(value) else str(int(value))


def _score_date(question: Question, span: str, format_ok: bool) -> Score:
    found = first_date(span, question.asked_on)
    if found is None:
        return Score(
            False, None, DETERMINISTIC, "no date in the answer (numeric forms like 12/03 are not read)", format_ok
        )
    gold = date.fromisoformat(str(question.gold))
    return Score(
        found == gold, found.isoformat(), DETERMINISTIC, f"{found.isoformat()} vs gold {gold.isoformat()}", format_ok
    )


def _score_terms(question: Question, span: str, format_ok: bool, *, single: bool) -> Score:
    members = _gold_members(question)
    groups, member_keys = _choice_groups(question, members)
    found = match_terms(span, groups)
    present = sorted(k.split(":", 1)[1] for k in found & member_keys)
    others = sorted(k.split(":", 1)[1] for k in found - member_keys)
    extracted = ", ".join(present + others) or None
    if not members:
        none_said = bool(_NONE.search(_norm_terms(span)))
        ok = none_said and not others
        reason = (
            "gold is empty: "
            + ("said none" if none_said else "did not say none")
            + (f"; also named {others}" if others else "")
        )
        return Score(ok, extracted or ("none" if none_said else None), DETERMINISTIC, reason, format_ok)
    missing = sorted(k.split(":", 1)[1] for k in member_keys - found)
    ok = not missing and not others
    parts = []
    if missing:
        parts.append(f"missing {missing}")
    if others:
        parts.append(f"also named {others}")
    reason = "; ".join(parts) or ("matched the gold" if single else f"matched all {len(members)} members")
    return Score(ok, extracted, DETERMINISTIC, reason, format_ok)


def abstains(span: str) -> bool:
    text = _clean(_normalise(span)).strip(" .!")
    return not text or bool(_ABSTAIN.match(text))


def _score_text(question: Question, span: str, format_ok: bool, judge: Judge | None) -> Score:
    if abstains(span):
        return Score(False, span or None, DETERMINISTIC, "no answer, or an abstention", format_ok)
    if _norm_terms(span).strip(" .") == _norm_terms(question.gold_text).strip(" ."):
        return Score(True, span, DETERMINISTIC, "exactly the gold text", format_ok)
    if judge is None:
        return Score(None, span, JUDGE, "not judged: no judge configured", format_ok)
    verdict = judge(question.question, question.gold_text, span)
    return Score(verdict.correct, span, JUDGE, verdict.reason, format_ok, verdict.model, verdict.usage)
