"""
Questions, built from the simulators' truth.

Each question is computed twice by the builder: from the truth (corrected
values, retracted records gone) and from what was stated at the time (no
corrections, no retractions). When the second would be scored wrong, the
question carries the `correction` skill. The builders read the records and
the simulators' timelines directly; the checker (`check.py`) re-derives every
gold from the written events and `derivation` alone, with code of its own.

Slots are planned first so that every skill appears in every domain it applies
to and the correction and cross shares are met; each slot is then filled by
sampling candidates until one passes every rule, or fails loudly.
"""

from __future__ import annotations

import math
import random
import re
from collections.abc import Callable
from datetime import date, timedelta

from ledgerbench.generate.calendar import (
    WEEKDAYS,
    WEEKEND,
    WORKDAYS,
    iso,
    long_date,
    long_date_wd,
    month_label,
    month_name,
    range_words,
    week_words,
    weekday,
)  # fmt: skip
from ledgerbench.generate.core import Rec, UserCtx
from ledgerbench.generate.food import COUNT_WORDS, MEAL_ALIASES, MEALS, all_food_names
from ledgerbench.generate.spending import CATEGORIES, CATEGORY_ALIASES, CATEGORY_PHRASE
from ledgerbench.generate.training import EXERCISE_ALIASES, LABELS, SESSION_ALIASES, SESSIONS

AFTER = ["corrections", "retractions"]
DOMAIN_OF = {
    "expense": "spending", "meal": "food", "water": "food", "workout": "training", "run": "training",
    "weight": "body", "sleep_hours": "body", "steps": "body", "resting_hr": "body",
}  # fmt: skip
APPLIES = {
    "spending": ("lookup", "aggregate", "group", "window", "state", "as_of", "change", "correction", "budget"),
    "food": ("lookup", "aggregate", "group", "window", "state", "as_of", "change", "correction", "adherence"),
    "training": ("lookup", "aggregate", "group", "window", "state", "as_of", "change", "correction", "adherence"),
    "body": ("lookup", "aggregate", "group", "window", "state", "as_of", "change", "correction"),
    "cross": ("cross",),
}
REL_TOL = 0.01
# kind: (abs_tol, decimals the gold is rounded to)
KINDS = {
    "money": (0.005, 2), "money_avg": (0.05, 2), "kcal": (0.5, 0), "kcal_avg": (0.5, 1), "g": (0.5, 0), "g_avg": (0.5, 1),
    "bw": (0.05, 1), "bw_avg": (0.05, 2), "lift": (0.05, 2), "km": (0.05, 2), "km_avg": (0.05, 2), "hours": (0.05, 2),
    "hours_avg": (0.05, 2), "steps": (0.5, 0), "steps_avg": (0.5, 1), "bpm": (0.5, 0), "ml": (0.5, 0),
}  # fmt: skip
CORRECTION_SHARE = 0.13
CROSS_SHARE = 0.07
TEXT_SHARE = 0.03
MAX_ATTEMPTS = 400
MIN_RECORDS = 3
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
GROUP_MARGIN = 0.05
BUDGET_NAME = {"eating out": "eating-out"}


class GenerationError(RuntimeError):
    pass


def fmt_num(x: float, decimals: int) -> str:
    text = f"{x:.{decimals}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def join_words(items: list[str]) -> str:
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


# ------------------------------------------------------------------ names and their aliases
#
# A category or set question whose gold names an exercise or a food accepts every form this user typed
# for it ("squats", "BB rows", "slices of toast"), found in their own messages, plus the plain singular
# and plural of each, unless a form collides word for word (plurals aside) with another choice: with
# both back squat and front squat among the choices, "squat" and "squats" say neither.

SURFACE_FORMS = {
    "exercise": {name: list(forms) for name, forms in LABELS.items()},
    "food": {name: [name] + ([COUNT_WORDS[name]] if name in COUNT_WORDS else []) for name in all_food_names()},
}


def _stem(word: str) -> str:
    w = word.lower()
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if w.endswith(("sses", "shes", "ches", "xes")):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def _stems(text: str) -> list[str]:
    return [_stem(w) for w in re.findall(r"[a-z0-9]+", text.lower())]


def collides(a: str, b: str) -> bool:
    """One term's words, plurals aside, run inside the other's: 'squats' and 'front squat' do."""
    x, y = _stems(a), _stems(b)
    if len(x) > len(y):
        x, y = y, x
    return bool(x) and any(y[i : i + len(x)] == x for i in range(len(y) - len(x) + 1))


def number_forms(term: str) -> list[str]:
    """
    The term and its plain singular or plural. The scorer already accepts every term with "s" or "es"
    added, so a plural is written out only when it is not formed that way (blueberry, blueberries).
    Abbreviations and 'x and y' stay as they are.
    """
    words = term.split(" ")
    last = words[-1]
    if " and " in term or not last.isalpha() or (len(last) > 1 and last.isupper()):
        return [term]
    head = " ".join(words[:-1] + [""])
    lower = last.lower()
    if len(lower) > 4 and lower.endswith("ies"):
        return [term, head + last[:-3] + "y"]
    if lower.endswith(("sses", "shes", "ches", "xes")):
        return [term, head + last[:-2]]
    if len(lower) > 3 and lower.endswith("s") and not lower.endswith("ss"):
        return [term, head + last[:-1]]
    if len(lower) > 2 and lower.endswith("y") and lower[-2] not in "aeiou":
        return [term, head + last[:-1] + "ies"]
    return [term]


def named_aliases(gold: str, forms: list[str], choices: list[str]) -> list[str]:
    out = [gold]
    for form in [gold, *forms]:
        for f in number_forms(form):
            if f.lower() in (o.lower() for o in out):
                continue
            if any(c != gold and collides(f, c) for c in choices):
                continue
            out.append(f)
    return out


def forms_said(messages: list[str], kind: str) -> dict[str, list[str]]:
    """Which surface forms of each name the messages use, longest first so 'back squats' is not also 'squats'."""
    terms = sorted(
        ((form, name) for name, forms in SURFACE_FORMS[kind].items() for form in forms),
        key=lambda t: (-len(t[0]), t[0]),
    )
    found: dict[str, list[str]] = {}
    for text in messages:
        low = text.lower()
        taken: list[tuple[int, int]] = []
        for form, name in terms:
            for m in re.finditer(r"(?<![a-z0-9])" + re.escape(form.lower()) + r"(?![a-z0-9])", low):
                if any(m.start() < e and s < m.end() for s, e in taken):
                    continue
                taken.append((m.start(), m.end()))
                if form not in found.setdefault(name, []):
                    found[name].append(form)
    return {name: sorted(forms) for name, forms in found.items()}


# ------------------------------------------------------------------ views


class View:
    """The records as rows: the truth (corrected, retractions applied) or as stated at the time."""

    def __init__(self, recs: list[Rec], truth: bool):
        self.truth = truth
        self.by_type: dict[str, list[dict]] = {}
        self.by_id: dict[str, dict] = {}
        for r in recs:
            if truth and r.retracted:
                continue
            row = dict(r.truth if truth else r.stated)
            for k, target in r.links.items():
                row[k] = target.id
            row["id"] = r.id
            row["date"] = r.date
            row["_rec"] = r
            self.by_type.setdefault(r.type, []).append(row)
            self.by_id[r.id] = row

    def rows(self, type_: str) -> list[dict]:
        return self.by_type.get(type_, [])


def between(rows: list[dict], a: date, b: date, wds=None) -> list[dict]:
    return [r for r in rows if a <= r["date"] <= b and (wds is None or weekday(r["date"]) in wds)]


def meal_kcal(row: dict) -> int:
    return sum(it["kcal"] for it in row["items"])


def meal_protein(row: dict) -> int:
    return sum(it.get("protein_g", 0) for it in row["items"])


def daily(rows: list[dict], fn: Callable[[dict], float]) -> dict[date, float]:
    out: dict[date, float] = {}
    for r in rows:
        out[r["date"]] = out.get(r["date"], 0) + fn(r)
    return out


# ------------------------------------------------------------------ candidates


class Cand:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class Builder:
    def __init__(self, ctx: UserCtx, rng, distractor_numbers: list[float]):
        self.ctx = ctx
        self.p = ctx.persona
        self.uid = self.p["id"]
        self.cur = self.p["currency"]
        self.rng = rng
        self.first, self.last = ctx.first, ctx.last
        self.T = View(ctx.recs, True)
        self.N = View(ctx.recs, False)
        self.distractors = sorted(set(distractor_numbers))
        self.used: set[str] = set()
        self.focus: list[Rec] = []
        self.months = []
        d = date(self.first.year, self.first.month, 1)
        while d <= self.last:
            nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
            if d >= self.first:
                self.months.append(
                    (
                        d,
                        min(nxt - timedelta(days=1), self.last),
                        month_label(d.year, d.month),
                        nxt - timedelta(days=1) <= self.last,
                    )
                )
            d = nxt
        self.weeks = []
        d = self.first + timedelta(days=(7 - self.first.weekday()) % 7)
        while d + timedelta(days=6) <= self.last:
            self.weeks.append(d)
            d += timedelta(days=7)
        tr = ctx.timelines.get("training")
        self.plans = tr["plans"] if tr else []
        self.lift_unit = self.p["units"]["lifts"]
        self.bw_unit = self.p["units"]["body_weight"]
        self.messages = [m for s in getattr(ctx, "sessions", []) for m in s["messages"]]
        self._said: dict[str, dict[str, list[str]]] = {}

    def said(self, kind: str, name: str) -> list[str]:
        """The forms of an exercise or food name this user typed in their messages."""
        if kind not in self._said:
            self._said[kind] = forms_said(self.messages, kind)
        return self._said[kind].get(name, [])

    # -- periods ---------------------------------------------------------------
    def focused(self) -> list[date]:
        """When a slot needs a correction, the dates of corrected or retracted records it should cover."""
        return sorted({r.date for r in self.focus}) if self.focus and self.rng.random() < 0.8 else []

    def month(self, complete: bool = False):
        pool = [m for m in self.months if m[3] or not complete]
        f = self.focused()
        if f:
            pool = [m for m in pool if any(m[0] <= x <= m[1] for x in f)] or pool
        if not pool:
            return None
        a, b, label, complete = self.rng.choice(pool)
        return a, b, month_words(a, b, label, complete)

    def week(self):
        if not self.weeks:
            return None
        pool = self.weeks
        f = self.focused()
        if f:
            pool = [w for w in pool if any(w <= x <= w + timedelta(days=6) for x in f)] or pool
        a = self.rng.choice(pool)
        return a, a + timedelta(days=6), week_words(a)

    def range_(self, lo: int = 8, hi: int = 40):
        n_days = (self.last - self.first).days + 1
        hi = min(hi, n_days)
        if hi < lo:
            return None
        length = self.rng.randrange(lo, hi + 1)
        start = self.first + timedelta(days=self.rng.randrange(0, n_days - length + 1))
        f = self.focused()
        if f:
            x = self.rng.choice(f)
            lo_start = max(self.first, x - timedelta(days=length - 1))
            hi_start = min(x, self.last - timedelta(days=length - 1))
            if lo_start <= hi_start:
                start = lo_start + timedelta(days=self.rng.randrange((hi_start - lo_start).days + 1))
        end = start + timedelta(days=length - 1)
        return start, end, range_words(start, end)

    def period(self, kinds=("month", "week", "range")):
        kind = self.rng.choice(kinds)
        got = {"month": self.month, "week": self.week, "range": self.range_}[kind]()
        return got or self.range_()

    def day(self, rows: list[dict]):
        return self.pick(rows)["date"] if rows else None

    def pick(self, rows: list[dict]) -> dict:
        """A random row, preferring corrected records when the slot needs a correction."""
        if self.focus and self.rng.random() < 0.8:
            dates = {r.date for r in self.focus}
            near = [r for r in rows if r["_rec"] in self.focus] or [r for r in rows if r["date"] in dates]
            if near:
                return self.rng.choice(near)
        return self.rng.choice(rows)

    # -- the gate ----------------------------------------------------------------
    def make(
        self,
        *,
        domain: str,
        skills: list[str],
        question: str,
        atype: str,
        compute,
        derivation: dict,
        kind: str | None = None,
        noun: str = "",
        choices: list[str] | None = None,
        aliases=None,
        exempt: bool = False,
        need_fix: bool = False,
        gold_text: Callable | None = None,
        margin_of=None,
        extra=None,
    ):
        """Computes the gold both ways and applies every rule; returns a Cand or the reason it was refused."""
        gold, rows = compute(self.T)
        if gold is None:
            return "no answer"
        naive, nrows = compute(self.N)
        if question in self.used:
            return "already asked"
        unit = None
        rel = abs_tol = None
        if atype == "number":
            abs_tol, dec = KINDS[kind]
            gold = round(float(gold) + 0.0, dec)
            naive = None if naive is None else float(naive)  # unrounded, as the checker compares it
            rel = REL_TOL
            unit = {
                "money": self.cur,
                "money_avg": self.cur,
                "kcal": "kcal",
                "kcal_avg": "kcal",
                "g": "g",
                "g_avg": "g",
                "bw": self.bw_unit,
                "bw_avg": self.bw_unit,
                "lift": self.lift_unit,
                "km": "km",
                "km_avg": "km",
                "hours": "hours",
                "hours_avg": "hours",
                "steps": "steps",
                "steps_avg": "steps",
                "bpm": "bpm",
                "ml": "ml",
            }[kind]
            derivation = {**derivation, "round": dec}
            if gold <= 0:
                return "answer is not positive"
            tol = max(abs_tol, rel * abs(gold))
            depends = naive is None or abs(naive - gold) > tol + 1e-9
        elif atype == "count":
            gold = int(gold)
            rel, abs_tol, unit = 0.0, 0.0, noun
            if gold <= 0:
                return "count is zero"
            tol = 0.0
            depends = naive != gold
        elif atype == "set":
            depends = sorted(naive or []) != sorted(gold)
            tol = None
        else:
            depends = naive != gold
            tol = None
        if need_fix and not depends:
            return "does not depend on a correction"
        ids = {r["id"] for r in rows}
        if not exempt and len(ids) < MIN_RECORDS:
            return f"only {len(ids)} records"
        if tol is not None:
            for n in _NUM.findall(question):
                if abs(float(n.replace(",", "")) - gold) <= tol + 1e-9:
                    return f"the question states {n}, within tolerance of {gold}"
            for n in self.distractors:
                if abs(n - gold) <= tol + 1e-9:
                    return f"distractor {n:g} within tolerance of {gold}"
        if atype in ("category", "set"):
            members = gold if atype == "set" else [gold]
            if not members or any(m not in choices for m in members):
                return "gold not among the choices"
        if margin_of is not None and not margin_of(self.T):
            return "the top group does not win clearly"
        evidence = set(ids)
        extra_rows = (extra(self.T) + extra(self.N)) if extra else []
        evidence |= {r["id"] for r in extra_rows if r["id"] in self.T.by_id}
        for rs in (rows, nrows or [], extra_rows):
            for r in rs:
                rec = r.get("_rec")
                if rec is not None and rec.fixed is not None and not isinstance(rec.fixed, str):
                    evidence.add(rec.fixed.id)
        evidence = {e for e in evidence if re.fullmatch(r"u\d+:e\d+", e)}
        if depends and "correction" not in skills:
            skills = [*skills, "correction"]
        if atype == "number":
            text = gold_text(gold) if gold_text else f"{fmt_num(gold, KINDS[kind][1])} {unit}"
        elif atype == "count":
            text = f"{gold} {noun[:-1] if gold == 1 and noun.endswith('s') else noun}".strip()
        elif atype == "date":
            text = long_date_wd(gold)
            gold = iso(gold)
        elif atype == "set":
            text = join_words(gold)
        else:
            text = gold_text(gold) if gold_text else str(gold)
        derivation = {**derivation, "after": AFTER}
        self.used.add(question)
        return Cand(
            domain=domain,
            skills=skills,
            question=question,
            answer_type=atype,
            gold=gold,
            unit=unit,
            rel_tol=rel,
            abs_tol=abs_tol,
            gold_text=text,
            aliases=aliases if aliases is not None else [],
            choices=list(choices or []),
            evidence=sorted(evidence, key=lambda i: int(i.rsplit("e", 1)[1])),
            derivation=derivation,
            depends=depends,
        )

    # -- shared computations -------------------------------------------------------
    def spend(
        self, v: View, a: date, b: date, cat: str | None = None, wds=None, days: set | None = None, exclude: tuple = ()
    ):
        ex = [
            r
            for r in between(v.rows("expense"), a, b, wds)
            if (cat is None or r["category"] == cat)
            and r["category"] not in exclude
            and (days is None or r["date"] in days)
        ]
        rf = []
        for r in between(v.rows("refund"), a, b, wds):
            target = v.by_id.get(r["refers_to"])
            if target is None or (days is not None and r["date"] not in days):
                continue
            if (cat is None or target["category"] == cat) and target["category"] not in exclude:
                rf.append(r)
        total = sum(r["amount"] for r in ex) - sum(r["amount"] for r in rf)
        return total, ex + rf

    def plan_on(self, d: date) -> dict:
        found = self.plans[0][1]
        for eff, plan, _ in self.plans:
            if eff <= d:
                found = plan
        return found

    def plan_rec_on(self, d: date) -> Rec:
        found = self.plans[0][2]
        for eff, _, rec in self.plans:
            if eff <= d:
                found = rec
        return found

    def timeline_on(self, entries, d: date):
        """entries: (effective, value, rec) in statement order; the one in force on d, or None."""
        found = None
        for eff, value, rec in sorted(entries, key=lambda e: e[0]):
            if eff <= d:
                found = (eff, value, rec)
        return found

    def stable_on(self, entries, d: date) -> bool:
        """True when nothing said after d takes effect on or before d (no retroactive statements)."""
        return all(not (rec.date > d and eff <= d) for eff, _, rec in entries)

    @staticmethod
    def announced(entries, d: date) -> bool:
        """A change had been said by d but had not taken effect yet: 'now' or 'on d' could mean either value."""
        return any(rec.date <= d < eff for eff, _, rec in entries)

    @staticmethod
    def changes_on(entries, d: date) -> bool:
        """d is the day a change (not the first statement) takes effect: the boundary between two values."""
        if not entries:
            return False
        first = min(entries, key=lambda e: (e[2].date, e[0]))
        return any(eff == d for eff, _, rec in entries if rec is not first[2])

    def in_period(self, a: date, z: date, cat: str) -> bool:
        """At least one expense of the category falls in the period, so a question may name it."""
        return any(r["category"] == cat for r in between(self.T.rows("expense"), a, z))


# How a state or as_of question says which value it means when a change was announced but not yet in force.
PENDING_NOW = ", before any announced change takes effect"
PENDING_THEN = ", as things stood that day, before any change I had announced took effect"


def pending_note(b: Builder, entries, d: date, now: bool) -> str:
    return (PENDING_NOW if now else PENDING_THEN) if b.announced(entries, d) else ""


def month_words(a: date, z: date, label: str, complete: bool) -> str:
    """'in March 2026' for a month the log covers to its end; 'so far in March 2026 (1 to 21 March)' otherwise."""
    if complete:
        return f"in {label}"
    return f"so far in {label} ({partial_days(a, z)})"


def partial_days(a: date, z: date) -> str:
    """'1 to 21 March', the days of a month the log covers so far."""
    return f"1 {month_name(z)} only" if z.day == 1 else f"1 to {z.day} {month_name(z)}"


def pseudo(rows) -> list[dict]:
    return [{"id": r.id} for r in rows]


# ======================================================================= generators
# Each takes (builder, need_fix) and returns a Cand or a reason string.


def sp_lookup(b: Builder, nf: bool):
    rng = b.rng
    if rng.random() < 0.6:
        rows = [r for r in b.T.rows("expense") if r["category"] not in ("rent", "other")]
        if not rows:
            return "no expenses"
        r = b.pick(rows)
        d, cat = r["date"], r["category"]
        same = [x for x in b.T.rows("expense") if x["date"] == d and x["category"] == cat]
        if len(same) != 1:
            return "not a single record"
        if not refund_split_ok(b, d, d, cat):
            return "refund straddles the day"
        q = f"How much did I spend on {CATEGORY_PHRASE[cat]} on {long_date(d)}{after_refunds(b, d, d, cat)}?"
        return b.make(
            domain="spending",
            skills=["lookup"],
            question=q,
            atype="number",
            kind="money",
            need_fix=nf,
            exempt=True,
            compute=lambda v: (lambda t: (round(t[0], 2), t[1]) if t[1] else (None, []))(b.spend(v, d, d, cat)),
            derivation={
                "op": "sum",
                "type": "expense",
                "where": {"category": cat},
                "from": iso(d),
                "to": iso(d),
                "net_refunds": True,
                "field": "amount",
            },
        )
    m = b.month()
    if m is None:
        return "no month"
    a, z, words = m

    def comp(v):
        rows = [r for r in between(v.rows("expense"), a, z) if r["category"] == "rent"]
        return (rows[0]["date"], rows) if len(rows) == 1 else (None, rows)

    return b.make(
        domain="spending",
        skills=["lookup"],
        question=f"On what date did my rent go out {words}?",
        atype="date",
        compute=comp,
        exempt=True,
        need_fix=nf,
        derivation={
            "op": "lookup",
            "type": "expense",
            "where": {"category": "rent"},
            "from": iso(a),
            "to": iso(z),
            "field": "date",
        },
    )


def sp_aggregate(b: Builder, nf: bool):
    rng = b.rng
    form = rng.choice(["sum", "sum", "count", "avg", "max", "max_date", "total"])
    per = b.period(("month", "month", "week"))
    if per is None:
        return "no period"
    a, z, words = per
    cats = [
        "groceries",
        "eating out",
        "coffee",
        "transport",
        "entertainment",
        "household",
        "clothing",
        "health",
        "subscriptions",
    ]
    cat = rng.choice(cats)
    if not refund_split_ok(b, a, z, None if form == "total" else cat):
        return "refund straddles the period"
    if form == "sum":
        q = f"How much did I spend on {CATEGORY_PHRASE[cat]} {words}{after_refunds(b, a, z, cat)}?"
        return b.make(
            domain="spending",
            skills=["aggregate"],
            question=q,
            atype="number",
            kind="money",
            need_fix=nf,
            compute=lambda v: nonempty(b.spend(v, a, z, cat)),
            derivation={
                "op": "sum",
                "type": "expense",
                "where": {"category": cat},
                "from": iso(a),
                "to": iso(z),
                "net_refunds": True,
                "field": "amount",
            },
        )
    if form == "total":
        included = "every category and rent included" if b.in_period(a, z, "rent") else "every category included"
        q = f"How much did I spend in total, {included}, {words}{after_refunds(b, a, z, None)}?"
        return b.make(
            domain="spending",
            skills=["aggregate"],
            question=q,
            atype="number",
            kind="money",
            need_fix=nf,
            compute=lambda v: nonempty(b.spend(v, a, z)),
            derivation={
                "op": "sum",
                "type": "expense",
                "from": iso(a),
                "to": iso(z),
                "net_refunds": True,
                "field": "amount",
            },
        )
    cat = rng.choice(["coffee", "groceries", "eating out", "transport"])
    if form == "count":
        verb = {
            "coffee": "buy coffee",
            "groceries": "buy groceries",
            "eating out": "eat out or get takeaway (lunches out included)",
            "transport": "pay for transport",
        }[cat]
        q = f"How many times did I {verb} {words}?"
        return b.make(
            domain="spending",
            skills=["aggregate"],
            question=q,
            atype="count",
            noun="times",
            need_fix=nf,
            compute=lambda v: (lambda rows: (len(rows), rows))(
                [r for r in between(v.rows("expense"), a, z) if r["category"] == cat]
            ),
            derivation={"op": "count", "type": "expense", "where": {"category": cat}, "from": iso(a), "to": iso(z)},
        )
    if form == "avg":
        noun = {
            "coffee": "coffee",
            "groceries": "grocery shop",
            "eating out": "meal out (lunches and takeaway included)",
            "transport": "transport payment",
        }[cat]
        q = f"What was my average spend per {noun} {words}, before any refunds?"
        return b.make(
            domain="spending",
            skills=["aggregate"],
            question=q,
            atype="number",
            kind="money_avg",
            need_fix=nf,
            compute=lambda v: avg_of(
                [r for r in between(v.rows("expense"), a, z) if r["category"] == cat], lambda r: r["amount"]
            ),
            derivation={
                "op": "avg",
                "type": "expense",
                "where": {"category": cat},
                "from": iso(a),
                "to": iso(z),
                "field": "amount",
            },
        )

    def biggest(v):
        rows = [r for r in between(v.rows("expense"), a, z) if r["category"] not in ("rent",)]
        if not rows:
            return None, []
        top = max(r["amount"] for r in rows)
        winners = [r for r in rows if r["amount"] == top]
        return (winners[0], rows) if len(winners) == 1 else (None, rows)

    rent = b.in_period(a, z, "rent")
    if form == "max":
        q = (
            f"Apart from rent, what was my single biggest expense {words}, before any refunds?"
            if rent
            else f"What was my single biggest expense {words}, before any refunds?"
        )
        return b.make(
            domain="spending",
            skills=["aggregate"],
            question=q,
            atype="number",
            kind="money",
            need_fix=nf,
            exempt=True,
            compute=lambda v: (lambda t: (max(r["amount"] for r in t[1]) if t[1] else None, t[1]))(biggest(v)),
            derivation={
                "op": "max",
                "type": "expense",
                "exclude": {"category": ["rent"]},
                "from": iso(a),
                "to": iso(z),
                "field": "amount",
                "return": "value",
            },
        )
    q = f"On what date was my single biggest expense {words}{', apart from rent' if rent else ''}?"
    return b.make(
        domain="spending",
        skills=["aggregate"],
        question=q,
        atype="date",
        need_fix=nf,
        exempt=True,
        compute=lambda v: (lambda t: (t[0]["date"] if t[0] else None, t[1]))(biggest(v)),
        derivation={
            "op": "max",
            "type": "expense",
            "exclude": {"category": ["rent"]},
            "from": iso(a),
            "to": iso(z),
            "field": "amount",
            "return": "date",
        },
    )


def after_refunds(b: Builder, a: date, z: date, cat) -> str:
    _, rows = b.spend(b.T, a, z, cat)
    if any("refers_to" in r and r["_rec"].type == "refund" for r in rows):
        return ", after refunds"
    return ""


def nonempty(t):
    total, rows = t
    return (round(total, 2), rows) if rows else (None, rows)


def avg_of(rows, fn):
    if not rows:
        return None, rows
    return sum(fn(r) for r in rows) / len(rows), rows


def refund_split_ok(b: Builder, a: date, z: date, cat: str | None = None) -> bool:
    """A refund and the expense it refunds fall on the same side of the period, so 'after refunds' is unambiguous."""
    for r in b.T.rows("refund"):
        target = b.T.by_id.get(r["refers_to"])
        if target is None or (cat is not None and target["category"] != cat):
            continue
        if (a <= r["date"] <= z) != (a <= target["date"] <= z):
            return False
    return True


def sp_group(b: Builder, nf: bool):
    per = b.period(("month", "month", "week", "range"))
    if per is None:
        return "no period"
    a, z, words = per
    if not refund_split_ok(b, a, z):
        return "refund straddles the period"
    by_count = b.rng.random() < 0.3

    def totals(v):
        out: dict[str, float] = {}
        rows = []
        for cat in CATEGORIES:
            if cat == "rent" or (by_count and cat == "coffee"):
                continue
            if by_count:
                rs = [r for r in between(v.rows("expense"), a, z) if r["category"] == cat]
                t = len(rs)
            else:
                t, rs = b.spend(v, a, z, cat)
            if rs:
                out[cat] = t
                rows += rs
        return out, rows

    def comp(v):
        out, rows = totals(v)
        if len(out) < 2:
            return None, rows
        ranked = sorted(out.items(), key=lambda kv: (-kv[1], kv[0]))
        return ranked[0][0], rows

    def margin(v):
        out, _ = totals(v)
        ranked = sorted(out.values(), reverse=True)
        if by_count:
            return len(ranked) >= 2 and ranked[0] - ranked[1] >= 2
        return len(ranked) >= 2 and ranked[0] > ranked[1] * (1 + GROUP_MARGIN)

    # name an excluded category only when the period holds some of it
    left_out = [c for c in (["rent", "coffee"] if by_count else ["rent"]) if b.in_period(a, z, c)]
    apart = f"Apart from {join_words(left_out)}, " if left_out else ""
    if by_count:
        lead = "in which" if apart else "In which"
        q = f"{apart}{lead} spending category did I make the most purchases {words}, counting purchases rather than money?"
    else:
        lead = "which" if apart else "Which"
        q = f"{apart}{lead} spending category did I spend the most on {words}{after_refunds(b, a, z, None)}?"
    deriv = {
        "op": "top",
        "type": "expense",
        "exclude": {"category": ["rent", "coffee"] if by_count else ["rent"]},
        "by": "category",
        "measure": "count" if by_count else "sum",
        "from": iso(a),
        "to": iso(z),
        "margin": {"abs": 2} if by_count else {"rel": GROUP_MARGIN},
    }
    if not by_count:
        deriv.update({"field": "amount", "net_refunds": True})
    return b.make(
        domain="spending",
        skills=["group"],
        question=q,
        atype="category",
        compute=comp,
        need_fix=nf,
        choices=list(CATEGORIES),
        aliases=lambda g: CATEGORY_ALIASES[g],
        derivation=deriv,
        margin_of=margin,
    )


def sp_window(b: Builder, nf: bool):
    rng = b.rng
    cat = rng.choice(["coffee", "eating out", "groceries", "transport"])
    wd_mode = rng.choice(["weekdays", "weekends", "range"])
    per = b.range_(10, 45) if wd_mode == "range" or rng.random() < 0.5 else b.month()
    if per is None:
        return "no period"
    a, z, words = per
    wds = None if wd_mode == "range" else (list(WORKDAYS) if wd_mode == "weekdays" else list(WEEKEND))
    filt = (
        ""
        if wds is None
        else (" on weekdays (Monday to Friday)" if wd_mode == "weekdays" else " on weekends (Saturday and Sunday)")
    )
    if not refund_split_ok(b, a, z, cat):
        return "refund straddles the period"
    if rng.random() < 0.65:
        q = f"How much did I spend on {CATEGORY_PHRASE[cat]}{filt} {words}{after_refunds(b, a, z, cat)}?"
        deriv = {
            "op": "sum",
            "type": "expense",
            "where": {"category": cat},
            "from": iso(a),
            "to": iso(z),
            "net_refunds": True,
            "field": "amount",
        }
        if wds:
            deriv["weekdays"] = wds
        return b.make(
            domain="spending",
            skills=["window", "aggregate"],
            question=q,
            atype="number",
            kind="money",
            need_fix=nf,
            compute=lambda v: nonempty(b.spend(v, a, z, cat, wds)),
            derivation=deriv,
        )
    verb = {
        "coffee": "buy coffee",
        "groceries": "buy groceries",
        "eating out": "eat out or get takeaway (lunches out included)",
        "transport": "pay for transport",
    }[cat]
    q = f"How many times did I {verb}{filt} {words}?"
    deriv = {"op": "count", "type": "expense", "where": {"category": cat}, "from": iso(a), "to": iso(z)}
    if wds:
        deriv["weekdays"] = wds
    return b.make(
        domain="spending",
        skills=["window", "aggregate"],
        question=q,
        atype="count",
        noun="times",
        need_fix=nf,
        compute=lambda v: (lambda rows: (len(rows), rows))(
            [r for r in between(v.rows("expense"), a, z, wds) if r["category"] == cat]
        ),
        derivation=deriv,
    )


def recurring_on(b: Builder, name: str, d: date):
    tl = b.ctx.timelines["spending"]["recurring"][name]
    decl = tl[0]
    if decl[2].date > d:
        return None, []
    price, recs = decl[1], [decl[2]]
    for eff, new, rec in tl[1:]:
        if eff <= d:
            price, recs = new, [decl[2], rec]
    return price, recs


def owed_on(b: Builder, person: str, d: date):
    recs = [r for r in b.ctx.recs if r.type in ("split", "settled") and r.stated["person"] == person and r.date <= d]
    owed = sum(r.truth["owed"] for r in recs if r.type == "split") - sum(
        r.truth["amount"] for r in recs if r.type == "settled"
    )
    return round(owed, 2), recs


def sp_state(b: Builder, nf: bool, on: date | None = None):
    rng = b.rng
    d = on or b.last
    when = "now" if on is None else f"on {long_date(on)}"
    skill = "state" if on is None else "as_of"
    tl = b.ctx.timelines["spending"]
    form = rng.choice(["recurring", "recurring", "budget", "budget", "owed"])
    if form == "recurring":
        names = sorted(tl["recurring"])
        changed = [n for n in names if len(tl["recurring"][n]) > 1]
        name = rng.choice(changed if changed and rng.random() < 0.75 else names)
        price, recs = recurring_on(b, name, d)
        if price is None:
            return "not declared yet"
        entries = tl["recurring"][name]
        if on is not None and b.changes_on(entries, d):
            return "the price changes that day"
        what = {"rent": "rent", "the internet": "the internet"}.get(name, name)
        verb = "do I pay" if on is None else "was I paying"
        q = f"How much {verb} each month for {what} {when}{pending_note(b, entries, d, on is None)}?"
        return b.make(
            domain="spending",
            skills=[skill],
            question=q,
            atype="number",
            kind="money",
            exempt=True,
            need_fix=nf,
            compute=lambda v: (price, pseudo(recs)),
            derivation={"op": "as_of", "on": iso(d), "of": {"kind": "recurring", "name": name}},
        )
    if form == "budget":
        cat = rng.choice(sorted(tl["budgets"]))
        entries = tl["budgets"][cat]
        hit = b.timeline_on(entries, d)
        if hit is None or not b.stable_on(entries, d) or hit[2].date > d:
            return "no budget in force yet"
        if on is not None and b.changes_on(entries, d):
            return "the budget changes that day"
        verb = "is" if on is None else "was"
        q = f"What {verb} my monthly budget for {cat} {when}{pending_note(b, entries, d, on is None)}?"
        return b.make(
            domain="spending",
            skills=[skill],
            question=q,
            atype="number",
            kind="money",
            exempt=True,
            need_fix=nf,
            compute=lambda v: (hit[1], pseudo([hit[2]])),
            derivation={"op": "as_of", "on": iso(d), "of": {"kind": "budget", "category": cat}},
        )
    people = sorted({sp.stated["person"] for sp in tl["splits"]})
    if not people:
        return "no splits"
    person = rng.choice(people)
    owed, recs = owed_on(b, person, d)
    verb = "does" if on is None else "did"
    q = f"How much {verb} {person} owe me {when}, counting every shared bill and paying-back I mentioned?"
    return b.make(
        domain="spending",
        skills=[skill],
        question=q,
        atype="number",
        kind="money",
        exempt=True,
        need_fix=nf,
        compute=lambda v: (owed if owed > 0 else None, pseudo(recs)),
        derivation={"op": "as_of", "on": iso(d), "of": {"kind": "owed", "person": person}},
    )


def sp_as_of(b: Builder, nf: bool):
    d = b.first + timedelta(days=b.rng.randrange(3, max(4, (b.last - b.first).days - 3)))
    return sp_state(b, nf, on=d)


def sp_change(b: Builder, nf: bool):
    rng = b.rng
    form = rng.choice(["months", "months", "weeks", "ranges", "price", "budget"])
    if form in ("months", "weeks", "ranges"):
        if form == "ranges":
            length = rng.randrange(7, 15)
            span_days = (b.last - b.first).days + 1
            if span_days < 2 * length:
                return "window too short"
            a1 = b.first + timedelta(days=rng.randrange(0, span_days - 2 * length + 1))
            z1 = a1 + timedelta(days=length - 1)
            a2, z2 = z1 + timedelta(days=1), z1 + timedelta(days=length)
            w1, w2 = range_words(a1, z1), range_words(a2, z2)
        elif form == "months":
            full = [m for m in b.months if m[3]]
            if len(full) < 2:
                return "fewer than two full months"
            k = rng.randrange(len(full) - 1)
            (a1, z1, l1, _), (a2, z2, l2, _) = full[k], full[k + 1]
            w1, w2 = f"in {l1}", f"in {l2}"
        else:
            if len(b.weeks) < 2:
                return "fewer than two weeks"
            k = rng.randrange(len(b.weeks) - 1)
            a1, a2 = b.weeks[k], b.weeks[k + 1]
            z1, z2 = a1 + timedelta(days=6), a2 + timedelta(days=6)
            w1, w2 = week_words(a1).removeprefix("in "), week_words(a2).removeprefix("in ")
        cat = rng.choice(["groceries", "eating out", "coffee", "transport", "entertainment"])
        if not (refund_split_ok(b, a1, z1, cat) and refund_split_ok(b, a2, z2, cat)):
            return "refund straddles a period"
        t1, _ = b.spend(b.T, a1, z1, cat)
        t2, _ = b.spend(b.T, a2, z2, cat)
        more = t2 > t1
        left, right = ((a2, z2), (a1, z1)) if more else ((a1, z1), (a2, z2))
        refunds = after_refunds(b, a1, z1, cat) or after_refunds(b, a2, z2, cat)
        if form == "months":
            q = f"How much {'more' if more else 'less'} did I spend on {CATEGORY_PHRASE[cat]} in {l2} than in {l1}{refunds}?"
        elif form == "ranges":
            q = f"How much {'more' if more else 'less'} did I spend on {CATEGORY_PHRASE[cat]} {w2} than {w1}{refunds}?"
        else:
            q = f"How much {'more' if more else 'less'} did I spend on {CATEGORY_PHRASE[cat]} {week_words(a2)} than {week_words(a1)}{refunds}?"

        def comp(v):
            x, rx = b.spend(v, *left, cat)
            y, ry = b.spend(v, *right, cat)
            if not rx or not ry:
                return None, rx + ry
            return round(x - y, 2), rx + ry

        side = lambda p: {  # noqa: E731 - a derivation builder, closed over the loop
            "op": "sum",
            "type": "expense",
            "where": {"category": cat},
            "from": iso(p[0]),
            "to": iso(p[1]),
            "net_refunds": True,
            "field": "amount",
        }  # noqa: E731
        return b.make(
            domain="spending",
            skills=["change"],
            question=q,
            atype="number",
            kind="money",
            need_fix=nf,
            compute=comp,
            derivation={"op": "diff", "left": side(left), "right": side(right)},
        )
    tl = b.ctx.timelines["spending"]
    if form == "price":
        changed = [n for n in sorted(tl["recurring"]) if len(tl["recurring"][n]) > 1]
        if not changed:
            return "no price change"
        name = rng.choice(changed)
        eff = tl["recurring"][name][1][0]
        decl = tl["recurring"][name][0][2].date
        if eff > b.last or decl >= eff - timedelta(days=1):
            return "change not in force"
        if b.announced(tl["recurring"][name], b.last):
            return "a change is announced but not in force now"
        d1 = decl + timedelta(days=rng.randrange(0, (eff - decl).days))
        p1, r1 = recurring_on(b, name, d1)
        p2, r2 = recurring_on(b, name, b.last)
        q = f"By how much has my monthly price for {name} gone up between {long_date(d1)} and now?"
        return b.make(
            domain="spending",
            skills=["change", "state"],
            question=q,
            atype="number",
            kind="money",
            exempt=True,
            need_fix=nf,
            compute=lambda v: (round(p2 - p1, 2), pseudo(r1 + r2)),
            derivation={
                "op": "diff",
                "left": {"op": "as_of", "on": iso(b.last), "of": {"kind": "recurring", "name": name}},
                "right": {"op": "as_of", "on": iso(d1), "of": {"kind": "recurring", "name": name}},
            },
        )
    cats = [c for c in sorted(tl["budgets"]) if len(tl["budgets"][c]) > 1]
    if not cats:
        return "no budget change"
    cat = rng.choice(cats)
    entries = tl["budgets"][cat]
    first_eff, first_amt, first_rec = sorted(entries, key=lambda e: e[0])[0]
    now = b.timeline_on(entries, b.last)
    d1 = max(first_eff, first_rec.date)
    if now is None or now[1] == first_amt or d1 >= now[0]:
        return "no change in force"
    if b.announced(entries, b.last):
        return "a change is announced but not in force now"
    up = now[1] > first_amt
    q = f"How much {'higher' if up else 'lower'} is my monthly {BUDGET_NAME.get(cat, cat)} budget now than it was on {long_date(d1)}?"
    left, right = (b.last, d1) if up else (d1, b.last)
    val = abs(now[1] - first_amt)
    return b.make(
        domain="spending",
        skills=["change", "state"],
        question=q,
        atype="number",
        kind="money",
        exempt=True,
        need_fix=nf,
        compute=lambda v: (val, pseudo([first_rec, now[2]])),
        derivation={
            "op": "diff",
            "left": {"op": "as_of", "on": iso(left), "of": {"kind": "budget", "category": cat}},
            "right": {"op": "as_of", "on": iso(right), "of": {"kind": "budget", "category": cat}},
        },
    )


def sp_budget(b: Builder, nf: bool):
    tl = b.ctx.timelines["spending"]["budgets"]
    cat = b.rng.choice(sorted(tl))
    pool = []
    for a, z, label, complete in b.months:
        hit = b.timeline_on(tl[cat], a)
        if hit is not None:
            pool.append((a, z, label, complete, hit))
    if not pool:
        return "no month with a budget"
    a, z, label, complete, hit = b.rng.choice(pool)
    if not refund_split_ok(b, a, z, cat):
        return "refund straddles the month"
    spent, _ = b.spend(b.T, a, z, cat)
    left = hit[1] - spent
    name = BUDGET_NAME.get(cat, cat)
    # a month not over yet is named as the days it has had, never as the whole month
    so_far = f", going by my spending {month_words(a, z, label, complete)}"
    refunds = after_refunds(b, a, z, cat)
    if left > 0:
        q = (
            f"How much of my {name} budget for {label} was left at the end of the month{refunds}?"
            if complete
            else f"How much of my monthly {name} budget is left{so_far}{refunds}?"
        )
    else:
        q = (
            f"By how much did I go over my {name} budget for {label}{refunds}?"
            if complete
            else f"By how much am I over my monthly {name} budget{so_far}{refunds}?"
        )
    if CATEGORY_PHRASE[cat] != cat:
        q += f" Count everything that is {CATEGORY_PHRASE[cat]} against it."
    spend_d = {
        "op": "sum",
        "type": "expense",
        "where": {"category": cat},
        "from": iso(a),
        "to": iso(z),
        "net_refunds": True,
        "field": "amount",
    }
    budget_d = {"op": "as_of", "on": iso(a), "of": {"kind": "budget", "category": cat}}

    def comp(v):
        s, rows = b.spend(v, a, z, cat)
        if not rows:
            return None, rows
        val = hit[1] - s if left > 0 else s - hit[1]
        return round(val, 2), rows

    deriv = (
        {"op": "diff", "left": budget_d, "right": spend_d}
        if left > 0
        else {"op": "diff", "left": spend_d, "right": budget_d}
    )
    return b.make(
        domain="spending",
        skills=["budget"],
        question=q,
        atype="number",
        kind="money",
        need_fix=nf,
        compute=comp,
        derivation=deriv,
        extra=lambda v: pseudo([hit[2]]),
    )


# ------------------------------------------------------------------ food


def food_names(b: Builder) -> list[str]:
    names = set()
    for r in b.N.rows("meal"):
        for it in r["items"]:
            names.add(it["name"])
    return sorted(names)


def fd_lookup(b: Builder, nf: bool):
    rng = b.rng
    rows = [r for r in b.T.rows("meal") if r["meal"] != "snack"]
    if not rows:
        return "no meals"
    r = b.pick(rows)
    d, meal = r["date"], r["meal"]
    form = rng.choice(["kcal", "kcal", "items", "protein"])
    if form == "protein" and b.p["food_style"] == "kcal":
        form = "kcal"

    def one(v):
        rs = [x for x in v.rows("meal") if x["date"] == d and x["meal"] == meal]
        return rs[0] if len(rs) == 1 else None, rs

    if form == "kcal":
        q = f"How many calories was my {meal} on {long_date(d)}?"
        return b.make(
            domain="food",
            skills=["lookup"],
            question=q,
            atype="number",
            kind="kcal",
            exempt=True,
            need_fix=nf,
            compute=lambda v: (lambda t: (meal_kcal(t[0]) if t[0] else None, t[1]))(one(v)),
            derivation={
                "op": "lookup",
                "type": "meal",
                "where": {"meal": meal},
                "from": iso(d),
                "to": iso(d),
                "field": "items.*.kcal",
            },
        )
    if form == "protein":
        q = f"How much protein, in grams, was in my {meal} on {long_date(d)}?"
        return b.make(
            domain="food",
            skills=["lookup"],
            question=q,
            atype="number",
            kind="g",
            exempt=True,
            need_fix=nf,
            compute=lambda v: (lambda t: (meal_protein(t[0]) if t[0] else None, t[1]))(one(v)),
            derivation={
                "op": "lookup",
                "type": "meal",
                "where": {"meal": meal},
                "from": iso(d),
                "to": iso(d),
                "field": "items.*.protein_g",
            },
        )
    names = food_names(b)
    q = f"What did I have for {meal} on {long_date(d)}? Name every item."
    return b.make(
        domain="food",
        skills=["lookup"],
        question=q,
        atype="set",
        exempt=True,
        need_fix=nf,
        choices=names,
        aliases=lambda g: food_aliases(b, g, names),
        compute=lambda v: (lambda t: ([it["name"] for it in t[0]["items"]] if t[0] else None, t[1]))(one(v)),
        derivation={
            "op": "lookup",
            "type": "meal",
            "where": {"meal": meal},
            "from": iso(d),
            "to": iso(d),
            "field": "items.*.name",
            "within": "list",
        },
    )


def fd_aggregate(b: Builder, nf: bool):
    rng = b.rng
    forms = ["day_total", "avg_kcal", "avg_kcal", "snacks", "max_day", "max_date"]
    if b.p["food_style"] != "kcal":
        forms += ["avg_protein", "avg_protein"]
    if b.T.rows("water"):
        forms.append("water")
    form = rng.choice(forms)
    if form == "day_total":
        d = b.day(b.T.rows("meal"))
        if d is None:
            return "no meals"
        q = f"How many calories did I eat in total on {long_date(d)}, going by what I logged?"
        return b.make(
            domain="food",
            skills=["aggregate"],
            question=q,
            atype="number",
            kind="kcal",
            need_fix=nf,
            compute=lambda v: (lambda rs: (sum(meal_kcal(r) for r in rs), rs) if rs else (None, rs))(
                between(v.rows("meal"), d, d)
            ),
            derivation={"op": "sum", "type": "meal", "from": iso(d), "to": iso(d), "field": "items.*.kcal"},
        )
    per = b.period(("month", "week", "range"))
    if per is None:
        return "no period"
    a, z, words = per
    if form in ("avg_kcal", "avg_protein"):
        fn = meal_kcal if form == "avg_kcal" else meal_protein
        what = "calorie intake" if form == "avg_kcal" else "protein intake in grams"
        q = f"What was my average daily {what} {words}, counting only days I logged food?"
        return b.make(
            domain="food",
            skills=["aggregate"],
            question=q,
            atype="number",
            kind="kcal_avg" if form == "avg_kcal" else "g_avg",
            need_fix=nf,
            compute=lambda v: (lambda rs: (sum(daily(rs, fn).values()) / len(daily(rs, fn)), rs) if rs else (None, rs))(
                between(v.rows("meal"), a, z)
            ),
            derivation={
                "op": "avg",
                "type": "meal",
                "from": iso(a),
                "to": iso(z),
                "field": "items.*.kcal" if form == "avg_kcal" else "items.*.protein_g",
                "per": "date",
            },
        )
    if form == "snacks":
        q = f"How many snacks did I log {words}?"
        return b.make(
            domain="food",
            skills=["aggregate"],
            question=q,
            atype="count",
            noun="snacks",
            need_fix=nf,
            compute=lambda v: (lambda rs: (len(rs), rs))(
                [r for r in between(v.rows("meal"), a, z) if r["meal"] == "snack"]
            ),
            derivation={"op": "count", "type": "meal", "where": {"meal": "snack"}, "from": iso(a), "to": iso(z)},
        )
    if form == "water":
        q = f"How much water did I log in total {words}, in millilitres?"
        return b.make(
            domain="food",
            skills=["aggregate"],
            question=q,
            atype="number",
            kind="ml",
            need_fix=nf,
            compute=lambda v: (lambda rs: (sum(r["ml"] for r in rs), rs) if rs else (None, rs))(
                between(v.rows("water"), a, z)
            ),
            derivation={"op": "sum", "type": "water", "from": iso(a), "to": iso(z), "field": "ml"},
        )

    def top_day(v):
        rs = between(v.rows("meal"), a, z)
        totals = daily(rs, meal_kcal)
        if not totals:
            return (None, None), rs
        best = max(totals.values())
        winners = sorted(d for d, t in totals.items() if t == best)
        return (winners[0] if len(winners) == 1 else None, best), rs

    if form == "max_day":
        q = f"What was my highest daily calorie total {words}, going by what I logged?"
        return b.make(
            domain="food",
            skills=["aggregate"],
            question=q,
            atype="number",
            kind="kcal",
            need_fix=nf,
            exempt=True,
            compute=lambda v: (lambda t: (t[0][1], t[1]))(top_day(v)),
            derivation={
                "op": "max",
                "type": "meal",
                "from": iso(a),
                "to": iso(z),
                "field": "items.*.kcal",
                "per": "date",
                "return": "value",
            },
        )
    q = f"On which day {words} did I log my highest calorie total?"
    return b.make(
        domain="food",
        skills=["aggregate"],
        question=q,
        atype="date",
        need_fix=nf,
        exempt=True,
        compute=lambda v: (lambda t: (t[0][0], t[1]))(top_day(v)),
        derivation={
            "op": "max",
            "type": "meal",
            "from": iso(a),
            "to": iso(z),
            "field": "items.*.kcal",
            "per": "date",
            "return": "date",
        },
    )


def fd_group(b: Builder, nf: bool):
    per = b.period(("month", "week", "range"))
    if per is None:
        return "no period"
    a, z, words = per
    if b.rng.random() < 0.5:

        def totals(v):
            out = {}
            rs = between(v.rows("meal"), a, z)
            for r in rs:
                out[r["meal"]] = out.get(r["meal"], 0) + meal_kcal(r)
            return out, rs

        q = f"Which meal of the day (breakfast, lunch, dinner or snacks) gave me the most calories in total {words}?"
        choices, aliases = list(MEALS), meal_aliases_for
        deriv = {
            "op": "top",
            "type": "meal",
            "by": "meal",
            "measure": "sum",
            "field": "items.*.kcal",
            "from": iso(a),
            "to": iso(z),
            "margin": {"rel": GROUP_MARGIN},
        }
        margin_kind = "rel"
    else:

        def totals(v):
            out = {}
            rs = between(v.rows("meal"), a, z)
            for r in rs:
                for it in r["items"]:
                    out[it["name"]] = out.get(it["name"], 0) + 1
            return out, rs

        q = f"Which food did I log most often {words}, counting each meal it appeared in?"
        choices = food_names(b)
        aliases = lambda g: food_aliases(b, g, choices)  # noqa: E731
        deriv = {
            "op": "top",
            "type": "meal",
            "unnest": "items",
            "by": "name",
            "measure": "count",
            "from": iso(a),
            "to": iso(z),
            "margin": {"abs": 2},
        }
        margin_kind = "abs"

    def comp(v):
        out, rs = totals(v)
        if len(out) < 2:
            return None, rs
        return sorted(out.items(), key=lambda kv: (-kv[1], kv[0]))[0][0], rs

    def margin(v):
        ranked = sorted(totals(v)[0].values(), reverse=True)
        if len(ranked) < 2:
            return False
        return ranked[0] - ranked[1] >= 2 if margin_kind == "abs" else ranked[0] > ranked[1] * (1 + GROUP_MARGIN)

    return b.make(
        domain="food",
        skills=["group"],
        question=q,
        atype="category",
        compute=comp,
        need_fix=nf,
        choices=choices,
        aliases=aliases,
        derivation=deriv,
        margin_of=margin,
    )


def meal_aliases_for(gold):
    return MEAL_ALIASES[gold]


def fd_window(b: Builder, nf: bool):
    rng = b.rng
    wd_mode = rng.choice(["weekdays", "weekends", "range"])
    per = b.range_(10, 45) if wd_mode == "range" or rng.random() < 0.5 else b.month()
    if per is None:
        return "no period"
    a, z, words = per
    wds = None if wd_mode == "range" else (list(WORKDAYS) if wd_mode == "weekdays" else list(WEEKEND))
    filt = (
        ""
        if wds is None
        else (" on weekdays (Monday to Friday)" if wd_mode == "weekdays" else " on weekends (Saturday and Sunday)")
    )
    protein = b.p["food_style"] != "kcal" and rng.random() < 0.4
    fn = meal_protein if protein else meal_kcal
    what = "protein intake in grams" if protein else "calorie intake"
    q = f"What was my average daily {what}{filt} {words}, counting only days I logged food?"
    deriv = {
        "op": "avg",
        "type": "meal",
        "from": iso(a),
        "to": iso(z),
        "field": "items.*.protein_g" if protein else "items.*.kcal",
        "per": "date",
    }
    if wds:
        deriv["weekdays"] = wds
    return b.make(
        domain="food",
        skills=["window", "aggregate"],
        question=q,
        atype="number",
        kind="g_avg" if protein else "kcal_avg",
        need_fix=nf,
        compute=lambda v: (lambda rs: (sum(daily(rs, fn).values()) / len(daily(rs, fn)), rs) if rs else (None, rs))(
            between(v.rows("meal"), a, z, wds)
        ),
        derivation=deriv,
    )


def fd_state(b: Builder, nf: bool, on: date | None = None):
    tl = b.ctx.timelines["food"]
    kinds = ["kcal_target"] + (["protein_target"] if tl["protein_target"] else [])
    kind = b.rng.choice(kinds)
    d = on or b.last
    hit = b.timeline_on(tl[kind], d)
    if hit is None or not b.stable_on(tl[kind], d) or hit[2].date > d:
        return "no target in force"
    if on is not None and b.changes_on(tl[kind], d):
        return "the target changes that day"
    when = "now" if on is None else f"on {long_date(on)}"
    verb = "is" if on is None else "was"
    what = "daily calorie target" if kind == "kcal_target" else "daily protein target"
    unit = "" if kind == "kcal_target" else ", in grams"
    note = pending_note(b, tl[kind], d, on is None)
    return b.make(
        domain="food",
        skills=["state" if on is None else "as_of"],
        question=f"What {verb} my {what} {when}{unit}{note}?",
        atype="number",
        kind="kcal" if kind == "kcal_target" else "g",
        exempt=True,
        need_fix=nf,
        compute=lambda v: (hit[1], pseudo([hit[2]])),
        derivation={"op": "as_of", "on": iso(d), "of": {"kind": "target", "type": kind}},
    )


def fd_as_of(b: Builder, nf: bool):
    tl = b.ctx.timelines["food"]
    kind = b.rng.choice([k for k in ("kcal_target", "protein_target") if tl[k]])
    entries = sorted(tl[kind], key=lambda e: e[0])
    # prefer a day when an earlier target was in force
    if len(entries) > 1 and b.rng.random() < 0.8:
        k = b.rng.randrange(len(entries) - 1)
        lo, hi = max(entries[k][0], entries[k][2].date), entries[k + 1][0] - timedelta(days=1)
        if hi < lo:
            return "no gap"
        d = lo + timedelta(days=b.rng.randrange((hi - lo).days + 1))
    else:
        d = b.first + timedelta(days=b.rng.randrange(2, max(3, (b.last - b.first).days)))
    return fd_state(b, nf, on=d)


def fd_change(b: Builder, nf: bool):
    rng = b.rng
    if rng.random() < 0.4:
        tl = b.ctx.timelines["food"]["kcal_target"]
        entries = sorted(tl, key=lambda e: e[0])
        if len(entries) < 2:
            return "target never changed"
        first = entries[0]
        now = b.timeline_on(entries, b.last)
        d1 = max(first[0], first[2].date)
        if now is None or now[1] == first[1] or now[0] <= d1:
            return "no change"
        if b.announced(entries, b.last):
            return "a change is announced but not in force now"
        up = now[1] > first[1]
        q = f"How much {'higher' if up else 'lower'} is my daily calorie target now than it was on {long_date(d1)}?"
        left, right = (b.last, d1) if up else (d1, b.last)
        return b.make(
            domain="food",
            skills=["change", "state"],
            question=q,
            atype="number",
            kind="kcal",
            exempt=True,
            need_fix=nf,
            compute=lambda v: (abs(now[1] - first[1]), pseudo([first[2], now[2]])),
            derivation={
                "op": "diff",
                "left": {"op": "as_of", "on": iso(left), "of": {"kind": "target", "type": "kcal_target"}},
                "right": {"op": "as_of", "on": iso(right), "of": {"kind": "target", "type": "kcal_target"}},
            },
        )
    full = [m for m in b.months if m[3]]
    if len(full) >= 2 and rng.random() < 0.6:
        k = rng.randrange(len(full) - 1)
        (a1, z1, l1, _), (a2, z2, l2, _) = full[k], full[k + 1]
        p1, p2 = f"in {l1}", f"in {l2}"
    else:
        if len(b.weeks) < 2:
            return "fewer than two weeks"
        k = rng.randrange(len(b.weeks) - 1)
        a1, a2 = b.weeks[k], b.weeks[k + 1]
        z1, z2 = a1 + timedelta(days=6), a2 + timedelta(days=6)
        p1, p2 = week_words(a1), week_words(a2)

    def avg(v, a, z):
        rs = between(v.rows("meal"), a, z)
        t = daily(rs, meal_kcal)
        return (sum(t.values()) / len(t) if t else None), rs

    x, _ = avg(b.T, a2, z2)
    y, _ = avg(b.T, a1, z1)
    if x is None or y is None:
        return "empty period"
    more = x > y
    left, right = ((a2, z2), (a1, z1)) if more else ((a1, z1), (a2, z2))
    q = (
        f"How many more calories a day did I eat on average {p2} than {p1}, counting only days I logged food?"
        if more
        else f"How many fewer calories a day did I eat on average {p2} than {p1}, counting only days I logged food?"
    )

    def comp(v):
        x, rx = avg(v, *left)
        y, ry = avg(v, *right)
        if x is None or y is None:
            return None, rx + ry
        return x - y, rx + ry

    side = lambda p: {  # noqa: E731 - a derivation builder, closed over the loop
        "op": "avg",
        "type": "meal",
        "from": iso(p[0]),
        "to": iso(p[1]),
        "field": "items.*.kcal",
        "per": "date",
    }  # noqa: E731
    return b.make(
        domain="food",
        skills=["change"],
        question=q,
        atype="number",
        kind="kcal_avg",
        need_fix=nf,
        compute=comp,
        derivation={"op": "diff", "left": side(left), "right": side(right)},
    )


def fd_adherence(b: Builder, nf: bool):
    tl = b.ctx.timelines["food"]
    protein = bool(tl["protein_target"]) and b.rng.random() < 0.4
    per = b.period(("month", "week", "range"))
    if per is None:
        return "no period"
    a, z, words = per
    kind = "protein_target" if protein else "kcal_target"
    entries = tl[kind]
    for d in (a, z):
        if not b.stable_on(entries, d) or b.timeline_on(entries, a) is None:
            return "target not settled in the period"

    def comp(v):
        rs = between(v.rows("meal"), a, z)
        totals = daily(rs, meal_protein if protein else meal_kcal)
        hits = []
        for d, t in sorted(totals.items()):
            target = b.timeline_on(entries, d)[1]
            if (t >= target) if protein else (t > target):
                hits.append(d)
        used = [r for r in rs if r["date"] in hits]
        return len(hits), used

    if protein:
        q = f"On how many days {words} did I reach my protein target (the target in force that day), counting only days I logged food?"
        cond = {"at_least_target": {"type": "meal", "field": "items.*.protein_g", "target": "protein_target"}}
    else:
        q = f"On how many days {words} did I go over my calorie target (the target in force that day), counting only days I logged food?"
        cond = {"over_target": {"type": "meal", "field": "items.*.kcal", "target": "kcal_target"}}
    return b.make(
        domain="food",
        skills=["adherence"],
        question=q,
        atype="count",
        noun="days",
        need_fix=nf,
        compute=comp,
        derivation={"op": "count_days", "type": "meal", "from": iso(a), "to": iso(z), "days": cond},
    )


# ------------------------------------------------------------------ training


def exercise_choices(b: Builder) -> list[str]:
    names = []
    for _, plan, _ in b.plans:
        for sess in plan["sessions"].values():
            for e in sess:
                if e["exercise"] not in names:
                    names.append(e["exercise"])
    return sorted(names)


def session_choices(b: Builder) -> list[str]:
    return list(SESSIONS)


def ex_aliases(b: Builder, name: str, choices: list[str]) -> list[str]:
    """The exercise's honest synonyms, every form this user typed for it, and their singulars and plurals."""
    return named_aliases(name, [*EXERCISE_ALIASES[name], *b.said("exercise", name)], choices)


def food_aliases(b: Builder, name: str, choices: list[str]) -> list[str]:
    return named_aliases(name, b.said("food", name), choices)


def lifted(row: dict, name: str):
    for e in row["exercises"]:
        if e["name"] == name:
            return e
    return None


def tr_lookup(b: Builder, nf: bool):
    rng = b.rng
    forms = []
    if b.T.rows("workout"):
        forms += ["weight", "weight", "session"]
    if b.T.rows("run"):
        forms += ["run"]
    if not forms:
        return "nothing logged"
    form = rng.choice(forms)
    if form == "run":
        d = b.day(b.T.rows("run"))
        q = f"How far did I run on {long_date(d)}, in km?"
        return b.make(
            domain="training",
            skills=["lookup"],
            question=q,
            atype="number",
            kind="km",
            exempt=True,
            need_fix=nf,
            compute=lambda v: (lambda rs: (rs[0]["km"], rs) if len(rs) == 1 else (None, rs))(
                between(v.rows("run"), d, d)
            ),
            derivation={"op": "lookup", "type": "run", "from": iso(d), "to": iso(d), "field": "km"},
        )
    r = b.pick(b.T.rows("workout"))
    d = r["date"]
    if form == "session":
        q = f"Which training session did I do on {long_date(d)}?"
        return b.make(
            domain="training",
            skills=["lookup"],
            question=q,
            atype="category",
            exempt=True,
            need_fix=nf,
            choices=session_choices(b),
            aliases=SESSION_ALIASES.get,
            compute=lambda v: (lambda rs: (rs[0]["session"], rs) if len(rs) == 1 else (None, rs))(
                between(v.rows("workout"), d, d)
            ),
            derivation={"op": "lookup", "type": "workout", "from": iso(d), "to": iso(d), "field": "session"},
        )
    ex = rng.choice(r["exercises"])
    if r["_rec"] in (b.focus or []) and "fixed_item" in r["_rec"].tags:
        ex = r["exercises"][r["_rec"].tags["fixed_item"]]
    name = ex["name"]

    def comp(v):
        rs = between(v.rows("workout"), d, d)
        if len(rs) != 1:
            return None, rs
        e = lifted(rs[0], name)
        if e is None or len({s["weight"] for s in e["sets"]}) != 1:
            return None, rs
        return e["sets"][0]["weight"], rs

    q = f"What weight did I use for {name} on {long_date(d)}, in {b.lift_unit}?"
    return b.make(
        domain="training",
        skills=["lookup"],
        question=q,
        atype="number",
        kind="lift",
        exempt=True,
        need_fix=nf,
        compute=comp,
        derivation={
            "op": "lookup",
            "type": "workout",
            "unnest": "exercises",
            "where": {"name": name},
            "from": iso(d),
            "to": iso(d),
            "field": "sets.*.weight",
            "within": "max",
        },
    )


def tr_aggregate(b: Builder, nf: bool):
    rng = b.rng
    forms = []
    if b.T.rows("workout"):
        forms += ["count_workouts", "sets", "reps", "max_weight"]
    if b.T.rows("run"):
        forms += ["km", "count_runs", "longest_date"]
    form = rng.choice(forms)
    per = b.period(("month", "month", "range", "week"))
    if per is None:
        return "no period"
    a, z, words = per
    if form == "count_workouts":
        q = f"How many gym sessions (not runs) did I log {words}?"
        return b.make(
            domain="training",
            skills=["aggregate"],
            question=q,
            atype="count",
            noun="sessions",
            need_fix=nf,
            compute=lambda v: (lambda rs: (len(rs), rs))(between(v.rows("workout"), a, z)),
            derivation={"op": "count", "type": "workout", "from": iso(a), "to": iso(z)},
        )
    if form == "count_runs":
        q = f"How many runs did I log {words}?"
        return b.make(
            domain="training",
            skills=["aggregate"],
            question=q,
            atype="count",
            noun="runs",
            need_fix=nf,
            compute=lambda v: (lambda rs: (len(rs), rs))(between(v.rows("run"), a, z)),
            derivation={"op": "count", "type": "run", "from": iso(a), "to": iso(z)},
        )
    if form == "km":
        q = f"How many kilometres did I run in total {words}?"
        return b.make(
            domain="training",
            skills=["aggregate"],
            question=q,
            atype="number",
            kind="km",
            need_fix=nf,
            compute=lambda v: (lambda rs: (sum(r["km"] for r in rs), rs) if rs else (None, rs))(
                between(v.rows("run"), a, z)
            ),
            derivation={"op": "sum", "type": "run", "from": iso(a), "to": iso(z), "field": "km"},
        )
    if form == "longest_date":

        def comp(v):
            rs = between(v.rows("run"), a, z)
            if not rs:
                return None, rs
            best = max(r["km"] for r in rs)
            w = [r for r in rs if r["km"] == best]
            return (w[0]["date"] if len(w) == 1 else None), rs

        q = f"On what date was my longest run {words}?"
        return b.make(
            domain="training",
            skills=["aggregate"],
            question=q,
            atype="date",
            exempt=True,
            need_fix=nf,
            compute=comp,
            derivation={"op": "max", "type": "run", "from": iso(a), "to": iso(z), "field": "km", "return": "date"},
        )
    names = sorted({e["name"] for r in between(b.T.rows("workout"), a, z) for e in r["exercises"]})
    if not names:
        return "no workouts in the period"
    name = rng.choice(names)

    def rows_with(v):
        return [r for r in between(v.rows("workout"), a, z) if lifted(r, name)]

    if form == "sets":
        q = f"How many working sets of {name} did I do in total {words}?"
        return b.make(
            domain="training",
            skills=["aggregate"],
            question=q,
            atype="count",
            noun="sets",
            need_fix=nf,
            compute=lambda v: (lambda rs: (sum(len(lifted(r, name)["sets"]) for r in rs), rs))(rows_with(v)),
            derivation={
                "op": "sum",
                "type": "workout",
                "unnest": "exercises",
                "where": {"name": name},
                "from": iso(a),
                "to": iso(z),
                "field": "sets.#",
            },
        )
    if form == "reps":
        q = f"How many reps of {name} did I do in total {words}, across all sets?"
        return b.make(
            domain="training",
            skills=["aggregate"],
            question=q,
            atype="count",
            noun="reps",
            need_fix=nf,
            compute=lambda v: (lambda rs: (sum(s["reps"] for r in rs for s in lifted(r, name)["sets"]), rs))(
                rows_with(v)
            ),
            derivation={
                "op": "sum",
                "type": "workout",
                "unnest": "exercises",
                "where": {"name": name},
                "from": iso(a),
                "to": iso(z),
                "field": "sets.*.reps",
            },
        )
    q = f"What was the heaviest weight I lifted for {name} {words}, in {b.lift_unit}?"
    return b.make(
        domain="training",
        skills=["aggregate"],
        question=q,
        atype="number",
        kind="lift",
        exempt=True,
        need_fix=nf,
        compute=lambda v: (
            lambda rs: (max(s["weight"] for r in rs for s in lifted(r, name)["sets"]), rs) if rs else (None, rs)
        )(rows_with(v)),
        derivation={
            "op": "max",
            "type": "workout",
            "unnest": "exercises",
            "where": {"name": name},
            "from": iso(a),
            "to": iso(z),
            "field": "sets.*.weight",
            "within": "max",
            "return": "value",
        },
    )


def tr_group(b: Builder, nf: bool):
    per = b.period(("month", "range"))
    if per is None:
        return "no period"
    a, z, words = per
    by_session = b.rng.random() < 0.5 or not b.T.rows("workout")

    if by_session:

        def totals(v):
            out = {}
            rs = between(v.rows("workout"), a, z) + between(v.rows("run"), a, z)
            for r in rs:
                s = r.get("session", "Run")
                out[s] = out.get(s, 0) + 1
            return out, rs

        runs = " counting runs as Run sessions" if between(b.T.rows("run"), a, z) else ""
        q = f"Which kind of training session did I do most often {words}{',' if runs else ''}{runs}?"
        choices, aliases = session_choices(b), SESSION_ALIASES.get
        deriv = {
            "op": "top",
            "type": ["workout", "run"],
            "by": "session",
            "default": {"session": "Run"},
            "measure": "count",
            "from": iso(a),
            "to": iso(z),
            "margin": {"abs": 2},
        }
    else:

        def totals(v):
            out = {}
            rs = between(v.rows("workout"), a, z)
            for r in rs:
                for e in r["exercises"]:
                    out[e["name"]] = out.get(e["name"], 0) + len(e["sets"])
            return out, rs

        q = f"Which exercise did I do the most working sets of {words}?"
        choices = exercise_choices(b)
        aliases = lambda g: ex_aliases(b, g, choices)  # noqa: E731
        deriv = {
            "op": "top",
            "type": "workout",
            "unnest": "exercises",
            "by": "name",
            "measure": "sum",
            "field": "sets.#",
            "from": iso(a),
            "to": iso(z),
            "margin": {"abs": 2},
        }

    def comp(v):
        out, rs = totals(v)
        if len(out) < 2:
            return None, rs
        return sorted(out.items(), key=lambda kv: (-kv[1], kv[0]))[0][0], rs

    def margin(v):
        ranked = sorted(totals(v)[0].values(), reverse=True)
        return len(ranked) >= 2 and ranked[0] - ranked[1] >= 2

    return b.make(
        domain="training",
        skills=["group"],
        question=q,
        atype="category",
        compute=comp,
        need_fix=nf,
        choices=choices,
        aliases=aliases,
        derivation=deriv,
        margin_of=margin,
    )


def tr_window(b: Builder, nf: bool):
    rng = b.rng
    wd_mode = rng.choice(["weekends", "weekdays", "range"])
    per = b.range_(14, 50) if wd_mode == "range" or rng.random() < 0.6 else b.month()
    if per is None:
        return "no period"
    a, z, words = per
    wds = None if wd_mode == "range" else (list(WORKDAYS) if wd_mode == "weekdays" else list(WEEKEND))
    filt = (
        ""
        if wds is None
        else (" on weekdays (Monday to Friday)" if wd_mode == "weekdays" else " on weekends (Saturday and Sunday)")
    )
    runs = bool(b.T.rows("run")) and (rng.random() < 0.5 or not b.T.rows("workout"))
    if runs:
        q = f"How many kilometres did I run{filt} {words}?"
        deriv = {"op": "sum", "type": "run", "from": iso(a), "to": iso(z), "field": "km"}
        if wds:
            deriv["weekdays"] = wds
        return b.make(
            domain="training",
            skills=["window", "aggregate"],
            question=q,
            atype="number",
            kind="km",
            need_fix=nf,
            compute=lambda v: (lambda rs: (sum(r["km"] for r in rs), rs) if rs else (None, rs))(
                between(v.rows("run"), a, z, wds)
            ),
            derivation=deriv,
        )
    if rng.random() < 0.5:
        q = f"How many gym sessions (not runs) did I log{filt} {words}?"
        deriv = {"op": "count", "type": "workout", "from": iso(a), "to": iso(z)}
        if wds:
            deriv["weekdays"] = wds
        return b.make(
            domain="training",
            skills=["window", "aggregate"],
            question=q,
            atype="count",
            noun="sessions",
            need_fix=nf,
            compute=lambda v: (lambda rs: (len(rs), rs))(between(v.rows("workout"), a, z, wds)),
            derivation=deriv,
        )
    names = sorted({e["name"] for r in between(b.T.rows("workout"), a, z, wds) for e in r["exercises"]})
    if not names:
        return "nothing in the window"
    name = rng.choice(names)
    q = f"How many working sets of {name} did I do{filt} {words}?"
    deriv = {
        "op": "sum",
        "type": "workout",
        "unnest": "exercises",
        "where": {"name": name},
        "from": iso(a),
        "to": iso(z),
        "field": "sets.#",
    }
    if wds:
        deriv["weekdays"] = wds
    return b.make(
        domain="training",
        skills=["window", "aggregate"],
        question=q,
        atype="count",
        noun="sets",
        need_fix=nf,
        compute=lambda v: (lambda rs: (sum(len(lifted(r, name)["sets"]) for r in rs), rs))(
            [r for r in between(v.rows("workout"), a, z, wds) if lifted(r, name)]
        ),
        derivation=deriv,
    )


def tr_state(b: Builder, nf: bool, on: date | None = None):
    rng = b.rng
    d = on or b.last
    if on is not None and b.changes_on(b.plans, d):
        return "the plan changes that day"
    plan = b.plan_on(d)
    rec = b.plan_rec_on(d)
    when = "now" if on is None else f"on {long_date(on)}"
    note = pending_note(b, b.plans, d, on is None)
    am = "am I" if on is None else "was I"
    skill = "state" if on is None else "as_of"
    sessions = [s for s in plan["sessions"] if s != "Rest"]
    lifts = sorted({e["exercise"] for s in plan["sessions"].values() for e in s})
    forms = ["days_for", "days_for", "session_on", "count_days"] + (["weight", "weight", "weight"] if lifts else [])
    if lifts and rng.random() < 0.5:
        forms += ["prescription", "prescription"]
    form = rng.choice(forms)
    base = {"op": "as_of", "on": iso(d)}
    if form == "days_for":
        s = rng.choice(sessions)
        days = [wd for wd in WEEKDAYS if plan["days"][wd] == s]
        label = "runs" if s == "Run" else f"{s.lower()} sessions" if s != "Full body" else "full body sessions"
        q = f"On which days of the week {am} scheduled to do {label} {when}, by my training plan{note}?"
        return b.make(
            domain="training",
            skills=[skill],
            question=q,
            atype="set",
            exempt=True,
            need_fix=nf,
            choices=list(WEEKDAYS),
            aliases={wd: [wd, wd + "s", wd[:3]] for wd in days},
            compute=lambda v: (days, pseudo([rec])),
            derivation={**base, "of": {"kind": "plan", "extract": "days_for", "session": s}},
        )
    if form == "session_on":
        wd = rng.choice(WEEKDAYS)
        s = plan["days"][wd]
        is_ = "is" if on is None else "was"
        q = f"Which session {is_} on my training plan for {wd}s {when}{note}? Say Rest if it {is_} a rest day."
        return b.make(
            domain="training",
            skills=[skill],
            question=q,
            atype="category",
            exempt=True,
            need_fix=nf,
            choices=list(SESSIONS),
            aliases=SESSION_ALIASES.get,
            compute=lambda v: (s, pseudo([rec])),
            derivation={**base, "of": {"kind": "plan", "extract": "session_on", "weekday": wd}},
        )
    if form == "count_days":
        n = sum(1 for wd in WEEKDAYS if plan["days"][wd] != "Rest")
        q = f"How many training days a week {'does' if on is None else 'did'} my plan have {when}, runs included{note}?"
        return b.make(
            domain="training",
            skills=[skill],
            question=q,
            atype="count",
            noun="days",
            exempt=True,
            need_fix=nf,
            compute=lambda v: (n, pseudo([rec])),
            derivation={**base, "of": {"kind": "plan", "extract": "count_days"}},
        )
    name = rng.choice(lifts)
    e = next(x for sess in plan["sessions"].values() for x in sess if x["exercise"] == name)
    if form == "prescription":
        text = f"{e['sets']}x{e['reps']} at {e['weight']:g} {b.lift_unit}"
        q = f"What {'is' if on is None else 'was'} my prescription for {name} on my plan {when}{note}: sets, reps and weight?"
        return b.make(
            domain="training",
            skills=[skill],
            question=q,
            atype="text",
            exempt=True,
            need_fix=nf,
            compute=lambda v: (text, pseudo([rec])),
            derivation={
                **base,
                "of": {"kind": "plan", "extract": "prescription", "exercise": name, "unit": b.lift_unit},
            },
        )
    q = f"What {'is' if on is None else 'was'} my working weight for {name} on my plan {when}{note}, in {b.lift_unit}?"
    return b.make(
        domain="training",
        skills=[skill],
        question=q,
        atype="number",
        kind="lift",
        exempt=True,
        need_fix=nf,
        compute=lambda v: (e["weight"], pseudo([rec])),
        derivation={**base, "of": {"kind": "plan", "extract": "weight", "exercise": name}},
    )


def tr_as_of(b: Builder, nf: bool):
    # a day when an earlier plan was in force, so the answer differs from "now" more often than not
    if len(b.plans) > 1 and b.rng.random() < 0.85:
        k = b.rng.randrange(len(b.plans) - 1)
        lo, hi = b.plans[k][0], b.plans[k + 1][0] - timedelta(days=1)
        if hi < lo:
            return "no gap"
        d = lo + timedelta(days=b.rng.randrange((hi - lo).days + 1))
    else:
        d = b.first + timedelta(days=b.rng.randrange(0, max(1, (b.last - b.first).days)))
    return tr_state(b, nf, on=d)


def tr_change(b: Builder, nf: bool):
    rng = b.rng
    if rng.random() < 0.55 and len(b.plans) > 1:
        names = sorted({e["exercise"] for s in b.plan_on(b.last)["sessions"].values() for e in s})
        if not names:
            return "no lifts"
        name = rng.choice(names)
        d1 = b.first + timedelta(days=rng.randrange(0, max(1, (b.last - b.first).days - 14)))
        p1 = b.plan_on(d1)
        w1 = next((x["weight"] for s in p1["sessions"].values() for x in s if x["exercise"] == name), None)
        w2 = next(x["weight"] for s in b.plan_on(b.last)["sessions"].values() for x in s if x["exercise"] == name)
        if w1 is None or w1 == w2:
            return "no change"
        if b.announced(b.plans, b.last):
            return "a change is announced but not in force now"
        up = w2 > w1
        q = f"By how much has my working weight for {name} gone {'up' if up else 'down'} on my plan between {long_date(d1)} and now, in {b.lift_unit}?"
        left, right = (b.last, d1) if up else (d1, b.last)
        return b.make(
            domain="training",
            skills=["change", "state"],
            question=q,
            atype="number",
            kind="lift",
            exempt=True,
            need_fix=nf,
            compute=lambda v: (abs(w2 - w1), pseudo([b.plan_rec_on(d1), b.plan_rec_on(b.last)])),
            derivation={
                "op": "diff",
                "left": {"op": "as_of", "on": iso(left), "of": {"kind": "plan", "extract": "weight", "exercise": name}},
                "right": {
                    "op": "as_of",
                    "on": iso(right),
                    "of": {"kind": "plan", "extract": "weight", "exercise": name},
                },
            },
        )
    full = [m for m in b.months if m[3]]
    if len(full) >= 2:
        k = rng.randrange(len(full) - 1)
        (a1, z1, l1, _), (a2, z2, l2, _) = full[k], full[k + 1]
        p1, p2 = f"in {l1}", f"in {l2}"
    else:
        if len(b.weeks) < 2:
            return "fewer than two weeks"
        k = rng.randrange(len(b.weeks) - 1)
        a1, a2 = b.weeks[k], b.weeks[k + 1]
        z1, z2 = a1 + timedelta(days=6), a2 + timedelta(days=6)
        p1, p2 = week_words(a1), week_words(a2)
    runs = bool(b.T.rows("run")) and (rng.random() < 0.5 or not b.T.rows("workout"))
    if runs:
        t2 = sum(r["km"] for r in between(b.T.rows("run"), a2, z2))
        t1 = sum(r["km"] for r in between(b.T.rows("run"), a1, z1))
        more = t2 > t1
        left, right = ((a2, z2), (a1, z1)) if more else ((a1, z1), (a2, z2))
        q = f"How many {'more' if more else 'fewer'} kilometres did I run {p2} than {p1}?"

        def comp(v):
            x = between(v.rows("run"), *left)
            y = between(v.rows("run"), *right)
            if not x or not y:
                return None, x + y
            return sum(r["km"] for r in x) - sum(r["km"] for r in y), x + y

        side = lambda p: {"op": "sum", "type": "run", "from": iso(p[0]), "to": iso(p[1]), "field": "km"}  # noqa: E731
        return b.make(
            domain="training",
            skills=["change"],
            question=q,
            atype="number",
            kind="km",
            need_fix=nf,
            compute=comp,
            derivation={"op": "diff", "left": side(left), "right": side(right)},
        )
    names = sorted({e["name"] for r in between(b.T.rows("workout"), a1, z2) for e in r["exercises"]})
    if not names:
        return "no lifts"
    name = rng.choice(names)

    def reps(v, a, z):
        rs = [r for r in between(v.rows("workout"), a, z) if lifted(r, name)]
        return sum(s["reps"] for r in rs for s in lifted(r, name)["sets"]), rs

    t2, _ = reps(b.T, a2, z2)
    t1, _ = reps(b.T, a1, z1)
    more = t2 > t1
    left, right = ((a2, z2), (a1, z1)) if more else ((a1, z1), (a2, z2))
    q = f"How many {'more' if more else 'fewer'} reps of {name} did I do {p2} than {p1}?"

    def comp(v):
        x, rx = reps(v, *left)
        y, ry = reps(v, *right)
        return x - y, rx + ry

    side = lambda p: {  # noqa: E731 - a derivation builder, closed over the loop
        "op": "sum",
        "type": "workout",
        "unnest": "exercises",
        "where": {"name": name},
        "from": iso(p[0]),
        "to": iso(p[1]),
        "field": "sets.*.reps",
    }  # noqa: E731
    return b.make(
        domain="training",
        skills=["change"],
        question=q,
        atype="count",
        noun="reps",
        need_fix=nf,
        compute=comp,
        derivation={"op": "diff", "left": side(left), "right": side(right)},
    )


def tr_adherence(b: Builder, nf: bool):
    per = b.period(("month", "range", "range"))
    if per is None:
        return "no period"
    a, z, words = per
    missed = b.rng.random() < 0.7

    def comp(v):
        planned, done, rows = 0, 0, []
        d = a
        while d <= z:
            s = b.plan_on(d)["days"][weekday(d)]
            if s != "Rest":
                planned += 1
                hit = (
                    [r for r in v.rows("run") if r["date"] == d]
                    if s == "Run"
                    else [r for r in v.rows("workout") if r["date"] == d and r["session"] == s]
                )
                if hit:
                    done += 1
                rows += hit
                rows.append({"id": f"planned:{iso(d)}"})
            d += timedelta(days=1)
        if planned < MIN_RECORDS:
            return None, rows
        return (planned - done if missed else done), rows

    if missed:
        q = f"How many of the sessions on my training plan {words} did I not do (skipped or just missed), using the plan in force on each day?"
    else:
        q = f"How many of the sessions on my training plan {words} did I actually do, using the plan in force on each day?"
    cand = b.make(
        domain="training",
        skills=["adherence"],
        question=q,
        atype="count",
        noun="sessions",
        need_fix=nf,
        compute=comp,
        derivation={"op": "plan_count", "count": "missed" if missed else "done", "from": iso(a), "to": iso(z)},
    )
    if isinstance(cand, Cand):
        cand.evidence = [e for e in cand.evidence if not e.startswith("planned:")]
        plan_ids = sorted(
            {b.plan_rec_on(a + timedelta(days=k)).id for k in range((z - a).days + 1)},
            key=lambda i: int(i.rsplit("e", 1)[1]),
        )
        cand.evidence = sorted(set(cand.evidence) | set(plan_ids), key=lambda i: int(i.rsplit("e", 1)[1]))
    return cand


# ------------------------------------------------------------------ body


BODY_WHAT = {"weight": "weight", "sleep_hours": "sleep", "steps": "steps", "resting_hr": "resting heart rate"}


def body_types(b: Builder) -> list[str]:
    return [t for t in ("weight", "sleep_hours", "steps", "resting_hr") if b.T.rows(t)]


def bd_kind(t: str, avg: bool = False) -> str:
    return {"weight": "bw", "sleep_hours": "hours", "steps": "steps", "resting_hr": "bpm"}[t] + (
        "_avg" if avg and t != "resting_hr" else ""
    )


def bd_lookup(b: Builder, nf: bool):
    t = b.rng.choice([x for x in body_types(b) if x != "resting_hr"] or ["weight"])
    d = b.day(b.T.rows(t))
    if d is None:
        return "no readings"
    q = {
        "weight": f"What did I weigh on {long_date(d)}, in {b.bw_unit}?",
        "sleep_hours": f"How many hours did I sleep the night before {long_date(d)}?",
        "steps": f"How many steps did I log on {long_date(d)}?",
    }[t]
    atype = "number"
    return b.make(
        domain="body",
        skills=["lookup"],
        question=q,
        atype=atype,
        kind=bd_kind(t),
        exempt=True,
        need_fix=nf,
        compute=lambda v: (lambda rs: (rs[0]["value"], rs) if len(rs) == 1 else (None, rs))(between(v.rows(t), d, d)),
        derivation={"op": "lookup", "type": t, "from": iso(d), "to": iso(d), "field": "value"},
    )


def bd_aggregate(b: Builder, nf: bool):
    rng = b.rng
    types = body_types(b)
    t = rng.choice(types)
    per = b.period(("month", "month", "week", "range"))
    if per is None:
        return "no period"
    a, z, words = per
    forms = ["avg", "avg", "count", "max", "min"] if t != "resting_hr" else ["avg"]
    if t == "steps":
        forms += ["max_date"]
    form = rng.choice(forms)
    what = {
        "weight": f"weight in {b.bw_unit}",
        "sleep_hours": "sleep per night in hours",
        "steps": "daily step count",
        "resting_hr": "resting heart rate",
    }[t]
    if form == "avg":
        q = f"What was my average {what} {words}, counting only the {'days' if t != 'sleep_hours' else 'nights'} I logged it?"
        return b.make(
            domain="body",
            skills=["aggregate"],
            question=q,
            atype="number",
            kind=bd_kind(t, True),
            need_fix=nf,
            compute=lambda v: avg_of(between(v.rows(t), a, z), lambda r: r["value"]),
            derivation={"op": "avg", "type": t, "from": iso(a), "to": iso(z), "field": "value"},
        )
    if form == "count":
        noun = {"weight": "weigh-ins", "sleep_hours": "nights", "steps": "days"}[t]
        q = {
            "weight": f"How many times did I weigh myself {words}?",
            "sleep_hours": f"On how many nights {words} did I log my sleep?",
            "steps": f"On how many days {words} did I log my steps?",
        }[t]
        return b.make(
            domain="body",
            skills=["aggregate"],
            question=q,
            atype="count",
            noun=noun,
            need_fix=nf,
            compute=lambda v: (lambda rs: (len(rs), rs))(between(v.rows(t), a, z)),
            derivation={"op": "count", "type": t, "from": iso(a), "to": iso(z)},
        )

    def ext(v, hi: bool):
        rs = between(v.rows(t), a, z)
        if not rs:
            return None, rs
        best = (max if hi else min)(r["value"] for r in rs)
        w = [r for r in rs if r["value"] == best]
        return (w[0] if len(w) == 1 else None), rs

    hi = form in ("max", "max_date")
    if form == "max_date":
        q = f"On which day {words} did I log my most steps?"
        return b.make(
            domain="body",
            skills=["aggregate"],
            question=q,
            atype="date",
            exempt=True,
            need_fix=nf,
            compute=lambda v: (lambda t_: (t_[0]["date"] if t_[0] else None, t_[1]))(ext(v, True)),
            derivation={"op": "max", "type": t, "from": iso(a), "to": iso(z), "field": "value", "return": "date"},
        )
    word = {
        "weight": ("highest weight", "lowest weight"),
        "sleep_hours": ("longest night of sleep", "shortest night of sleep"),
        "steps": ("highest step count", "lowest step count"),
    }[t][0 if hi else 1]
    unit = {"weight": f", in {b.bw_unit}", "sleep_hours": ", in hours", "steps": ""}[t]
    q = f"What was my {word} {words}{unit}?"
    return b.make(
        domain="body",
        skills=["aggregate"],
        question=q,
        atype="number",
        kind=bd_kind(t),
        exempt=True,
        need_fix=nf,
        compute=lambda v: (lambda rs: ((max if hi else min)(r["value"] for r in rs) if rs else None, rs))(
            between(v.rows(t), a, z)
        ),
        derivation={
            "op": "max" if hi else "min",
            "type": t,
            "from": iso(a),
            "to": iso(z),
            "field": "value",
            "return": "value",
        },
    )


def bd_group(b: Builder, nf: bool):
    t = b.rng.choice([x for x in ("steps", "sleep_hours") if b.T.rows(x)] or ["weight"])
    if t == "weight":
        return "nothing to group"
    per = b.period(("month", "range"))
    if per is None:
        return "no period"
    a, z, words = per

    def totals(v):
        sums: dict[str, list[float]] = {}
        rs = between(v.rows(t), a, z)
        for r in rs:
            sums.setdefault(weekday(r["date"]), []).append(r["value"])
        return {k: sum(x) / len(x) for k, x in sums.items()}, rs

    def comp(v):
        out, rs = totals(v)
        if len(out) < 5:
            return None, rs
        return sorted(out.items(), key=lambda kv: (-kv[1], kv[0]))[0][0], rs

    def margin(v):
        ranked = sorted(totals(v)[0].values(), reverse=True)
        return len(ranked) >= 2 and ranked[0] > ranked[1] * (1 + GROUP_MARGIN)

    what = "step count" if t == "steps" else "sleep (by the morning I logged it)"
    q = f"Which day of the week had my highest average {what} {words}?"
    return b.make(
        domain="body",
        skills=["group"],
        question=q,
        atype="category",
        compute=comp,
        need_fix=nf,
        choices=list(WEEKDAYS),
        aliases=lambda g: [g, g + "s", g[:3]],
        margin_of=margin,
        derivation={
            "op": "top",
            "type": t,
            "by": "weekday",
            "measure": "avg",
            "field": "value",
            "from": iso(a),
            "to": iso(z),
            "margin": {"rel": GROUP_MARGIN},
        },
    )


def bd_window(b: Builder, nf: bool):
    rng = b.rng
    t = rng.choice([x for x in ("sleep_hours", "steps", "weight") if b.T.rows(x)])
    wd_mode = rng.choice(["weekdays", "weekends", "range"])
    per = b.range_(10, 45) if wd_mode == "range" or rng.random() < 0.5 else b.month()
    if per is None:
        return "no period"
    a, z, words = per
    wds = None if wd_mode == "range" else (list(WORKDAYS) if wd_mode == "weekdays" else list(WEEKEND))
    if t == "sleep_hours":
        filt = (
            ""
            if wds is None
            else (
                " on weeknights (logged Monday to Friday mornings)"
                if wd_mode == "weekdays"
                else " on weekend nights (logged Saturday and Sunday mornings)"
            )
        )
    else:
        filt = (
            ""
            if wds is None
            else (" on weekdays (Monday to Friday)" if wd_mode == "weekdays" else " on weekends (Saturday and Sunday)")
        )
    what = {"weight": f"weight in {b.bw_unit}", "sleep_hours": "sleep in hours", "steps": "daily step count"}[t]
    q = f"What was my average {what}{filt} {words}, counting only what I logged?"
    deriv = {"op": "avg", "type": t, "from": iso(a), "to": iso(z), "field": "value"}
    if wds:
        deriv["weekdays"] = wds
    return b.make(
        domain="body",
        skills=["window", "aggregate"],
        question=q,
        atype="number",
        kind=bd_kind(t, True),
        need_fix=nf,
        compute=lambda v: avg_of(between(v.rows(t), a, z, wds), lambda r: r["value"]),
        derivation=deriv,
    )


def bd_state(b: Builder, nf: bool, on: date | None = None):
    types = [x for x in ("weight", "weight", "resting_hr", "sleep_hours") if b.T.rows(x)]
    t = b.rng.choice(types)
    d = on or b.last

    def comp(v):
        rs = [r for r in v.rows(t) if r["date"] <= d]
        if not rs:
            return None, []
        last = max(rs, key=lambda r: r["date"])
        return last["value"], [last]

    if on is None:
        q = {
            "weight": f"What do I weigh now, going by my most recent weigh-in, in {b.bw_unit}?",
            "resting_hr": "What is my resting heart rate now, going by my most recent reading?",
            "sleep_hours": "Going by the most recent night I logged, how many hours am I sleeping now?",
        }[t]
    else:
        q = {
            "weight": f"What did I weigh as of {long_date(on)}, going by my most recent weigh-in on or before that day, in {b.bw_unit}?",
            "resting_hr": f"What was my resting heart rate as of {long_date(on)}, going by my most recent reading on or before that day?",
            "sleep_hours": f"As of {long_date(on)}, how many hours had I slept on the most recent night I had logged (that morning or before)?",
        }[t]
    return b.make(
        domain="body",
        skills=["state" if on is None else "as_of"],
        question=q,
        atype="number",
        kind=bd_kind(t),
        exempt=True,
        need_fix=nf,
        compute=comp,
        derivation={"op": "as_of", "on": iso(d), "of": {"kind": "reading", "type": t}},
    )


def bd_as_of(b: Builder, nf: bool):
    d = b.first + timedelta(days=b.rng.randrange(3, max(4, (b.last - b.first).days - 2)))
    return bd_state(b, nf, on=d)


def bd_change(b: Builder, nf: bool):
    rng = b.rng
    if rng.random() < 0.6 and b.T.rows("weight"):
        per = b.period(("month", "range"))
        if per is None:
            return "no period"
        a, z, words = per

        def ends(v):
            rs = sorted(between(v.rows("weight"), a, z), key=lambda r: r["date"])
            if len(rs) < 2:
                return None, None, rs
            return rs[0], rs[-1], rs

        f0, l0, _ = ends(b.T)
        if f0 is None or f0["value"] == l0["value"]:
            return "no change"
        up = l0["value"] > f0["value"]
        q = f"How much weight did I {'gain' if up else 'lose'} {words}, from my first weigh-in in that period to my last, in {b.bw_unit}?"

        def comp(v):
            f, l_, rs = ends(v)
            if f is None:
                return None, rs
            return (l_["value"] - f["value"]) if up else (f["value"] - l_["value"]), rs

        first_d = {"op": "first", "type": "weight", "from": iso(a), "to": iso(z), "field": "value"}
        last_d = {"op": "last", "type": "weight", "from": iso(a), "to": iso(z), "field": "value"}
        return b.make(
            domain="body",
            skills=["change"],
            question=q,
            atype="number",
            kind="bw",
            need_fix=nf,
            compute=comp,
            derivation={"op": "diff", "left": last_d if up else first_d, "right": first_d if up else last_d},
        )
    t = rng.choice([x for x in ("sleep_hours", "steps") if b.T.rows(x)] or ["weight"])
    full = [m for m in b.months if m[3]]
    if len(full) >= 2:
        k = rng.randrange(len(full) - 1)
        (a1, z1, l1, _), (a2, z2, l2, _) = full[k], full[k + 1]
        p1, p2 = f"in {l1}", f"in {l2}"
    else:
        if len(b.weeks) < 2:
            return "fewer than two weeks"
        k = rng.randrange(len(b.weeks) - 1)
        a1, a2 = b.weeks[k], b.weeks[k + 1]
        z1, z2 = a1 + timedelta(days=6), a2 + timedelta(days=6)
        p1, p2 = week_words(a1), week_words(a2)
    x, _ = avg_of(between(b.T.rows(t), a2, z2), lambda r: r["value"])
    y, _ = avg_of(between(b.T.rows(t), a1, z1), lambda r: r["value"])
    if x is None or y is None:
        return "empty period"
    more = x > y
    left, right = ((a2, z2), (a1, z1)) if more else ((a1, z1), (a2, z2))
    what = {
        "sleep_hours": ("more hours of sleep a night", "fewer hours of sleep a night"),
        "steps": ("more steps a day", "fewer steps a day"),
        "weight": (f"more {b.bw_unit}", f"fewer {b.bw_unit}"),
    }[t][0 if more else 1]
    q = f"On average, how many {what} did I log {p2} than {p1}?"

    def comp(v):
        x, rx = avg_of(between(v.rows(t), *left), lambda r: r["value"])
        y, ry = avg_of(between(v.rows(t), *right), lambda r: r["value"])
        if x is None or y is None:
            return None, rx + ry
        return x - y, rx + ry

    side = lambda p: {"op": "avg", "type": t, "from": iso(p[0]), "to": iso(p[1]), "field": "value"}  # noqa: E731
    return b.make(
        domain="body",
        skills=["change"],
        question=q,
        atype="number",
        kind=bd_kind(t, True),
        need_fix=nf,
        compute=comp,
        derivation={"op": "diff", "left": side(left), "right": side(right)},
    )


# ------------------------------------------------------------------ cross


def cross(b: Builder, nf: bool):
    rng = b.rng
    doms = set(b.p["domains"])
    options = []
    if {"food", "training"} <= doms:
        options += ["food_training"] * 2
    if {"body", "training"} <= doms and b.T.rows("steps"):
        options += ["steps_training"]
    if {"spending", "food"} <= doms:
        options += ["eatout_over"]
    if {"spending", "training"} <= doms:
        options += ["coffee_training"]
    if {"body", "food"} <= doms and b.T.rows("sleep_hours"):
        options += ["kcal_sleep"]
    if {"spending", "body"} <= doms and b.T.rows("sleep_hours"):
        options += ["coffee_sleep"]
    if not options:
        return "no pair of domains"
    form = rng.choice(options)
    per = b.period(("month", "range"))
    if per is None:
        return "no period"
    a, z, words = per

    def trained(v) -> tuple[set, list]:
        rs = between(v.rows("workout"), a, z)
        return {r["date"] for r in rs}, rs

    def short_sleep(v) -> tuple[set, list]:
        rs = [r for r in between(v.rows("sleep_hours"), a, z) if r["value"] < 7]
        return {r["date"] for r in rs}, rs

    has_workout = {"has": {"type": "workout"}}
    slept_short = {"below": {"type": "sleep_hours", "field": "value", "value": 7}}

    if form == "food_training":
        protein = b.p["food_style"] != "kcal" and rng.random() < 0.6
        fn = meal_protein if protein else meal_kcal
        what = "protein intake in grams" if protein else "calorie intake"
        q = f"What was my average daily {what} {words} on the days I did a gym session (runs not counted), counting only days I also logged food?"

        def comp(v):
            days, _ = trained(v)
            rs = [r for r in between(v.rows("meal"), a, z) if r["date"] in days]
            t = daily(rs, fn)
            return ((sum(t.values()) / len(t)) if t else None), rs

        return b.make(
            domain="cross",
            skills=["cross", "aggregate"],
            question=q,
            atype="number",
            kind="g_avg" if protein else "kcal_avg",
            need_fix=nf,
            compute=comp,
            extra=lambda v: trained(v)[1],
            derivation={
                "op": "avg",
                "type": "meal",
                "from": iso(a),
                "to": iso(z),
                "field": "items.*.protein_g" if protein else "items.*.kcal",
                "per": "date",
                "days": has_workout,
            },
        )
    if form == "steps_training":
        q = f"What was my average step count {words} on the days I did a gym session (runs not counted)?"

        def comp(v):
            days, _ = trained(v)
            rs = [r for r in between(v.rows("steps"), a, z) if r["date"] in days]
            return (sum(r["value"] for r in rs) / len(rs) if rs else None), rs

        return b.make(
            domain="cross",
            skills=["cross", "aggregate"],
            question=q,
            atype="number",
            kind="steps_avg",
            need_fix=nf,
            compute=comp,
            extra=lambda v: trained(v)[1],
            derivation={
                "op": "avg",
                "type": "steps",
                "from": iso(a),
                "to": iso(z),
                "field": "value",
                "days": has_workout,
            },
        )
    if form in ("coffee_training", "coffee_sleep", "eatout_over"):
        cat = "eating out" if form == "eatout_over" else "coffee"
        if not refund_split_ok(b, a, z, cat):
            return "refund straddles the period"
        if form == "coffee_training":
            cond, cond_d = trained, has_workout
            tail = "on the days I did a gym session (runs not counted)"
        elif form == "coffee_sleep":
            cond, cond_d = short_sleep, slept_short
            tail = "on days after a night of under 7 hours' sleep (the sleep I logged that morning)"
        else:
            entries = b.ctx.timelines["food"]["kcal_target"]

            def cond(v):
                rs = between(v.rows("meal"), a, z)
                totals = daily(rs, meal_kcal)
                days = {d for d, t in totals.items() if t > b.timeline_on(entries, d)[1]}
                return days, [r for r in rs if r["date"] in days]

            if b.timeline_on(entries, a) is None or not b.stable_on(entries, a):
                return "no target at the start"
            cond_d = {"over_target": {"type": "meal", "field": "items.*.kcal", "target": "kcal_target"}}
            tail = "on days I went over my calorie target (the target in force that day)"
        q = f"How much did I spend on {CATEGORY_PHRASE[cat]} {words} {tail}{after_refunds(b, a, z, cat)}?"

        def comp(v):
            days, _ = cond(v)
            total, rows = b.spend(v, a, z, cat, days=days)
            return (round(total, 2) if rows else None), rows

        return b.make(
            domain="cross",
            skills=["cross", "aggregate"],
            question=q,
            atype="number",
            kind="money",
            need_fix=nf,
            compute=comp,
            extra=lambda v: cond(v)[1],
            derivation={
                "op": "sum",
                "type": "expense",
                "where": {"category": cat},
                "from": iso(a),
                "to": iso(z),
                "field": "amount",
                "net_refunds": True,
                "days": cond_d,
            },
        )
    q = f"What was my average daily calorie intake {words} on days after a night of under 7 hours' sleep (the sleep I logged that morning), counting only days I logged food?"

    def comp(v):
        days, _ = short_sleep(v)
        rs = [r for r in between(v.rows("meal"), a, z) if r["date"] in days]
        t = daily(rs, meal_kcal)
        return ((sum(t.values()) / len(t)) if t else None), rs

    return b.make(
        domain="cross",
        skills=["cross", "aggregate"],
        question=q,
        atype="number",
        kind="kcal_avg",
        need_fix=nf,
        compute=comp,
        extra=lambda v: short_sleep(v)[1],
        derivation={
            "op": "avg",
            "type": "meal",
            "from": iso(a),
            "to": iso(z),
            "field": "items.*.kcal",
            "per": "date",
            "days": slept_short,
        },
    )


GENERATORS = {
    ("spending", "lookup"): sp_lookup, ("spending", "aggregate"): sp_aggregate, ("spending", "group"): sp_group,
    ("spending", "window"): sp_window, ("spending", "state"): sp_state, ("spending", "as_of"): sp_as_of,
    ("spending", "change"): sp_change, ("spending", "budget"): sp_budget,
    ("food", "lookup"): fd_lookup, ("food", "aggregate"): fd_aggregate, ("food", "group"): fd_group, ("food", "window"): fd_window,
    ("food", "state"): fd_state, ("food", "as_of"): fd_as_of, ("food", "change"): fd_change, ("food", "adherence"): fd_adherence,
    ("training", "lookup"): tr_lookup, ("training", "aggregate"): tr_aggregate, ("training", "group"): tr_group,
    ("training", "window"): tr_window, ("training", "state"): tr_state, ("training", "as_of"): tr_as_of,
    ("training", "change"): tr_change, ("training", "adherence"): tr_adherence,
    ("body", "lookup"): bd_lookup, ("body", "aggregate"): bd_aggregate, ("body", "group"): bd_group, ("body", "window"): bd_window,
    ("body", "state"): bd_state, ("body", "as_of"): bd_as_of, ("body", "change"): bd_change,
    ("cross", "cross"): cross,
}  # fmt: skip
# Skills a correction slot may use: the ones whose answers rest on logged records.
FIX_SKILLS = {
    "spending": ("aggregate", "aggregate", "window", "lookup", "change", "budget", "group"),
    "food": ("aggregate", "aggregate", "window", "lookup", "change", "adherence"),
    "training": ("aggregate", "window", "lookup", "change", "aggregate"),
    "body": ("aggregate", "aggregate", "window", "lookup", "change", "as_of"),
    "cross": ("cross",),
}
STATE_CAP = {"spending": 3, "food": 1, "training": 3, "body": 1}
FILL_WEIGHTS = {
    "lookup": 2,
    "aggregate": 4,
    "group": 1.5,
    "window": 2.5,
    "state": 1.5,
    "as_of": 1.5,
    "change": 2,
    "budget": 1.5,
    "adherence": 2,
}


# ======================================================================= scheduling


class User:
    """One user's builder, the questions accepted so far, and what they still need."""

    def __init__(self, ctx: UserCtx, rng, distractor_numbers: list[float]):
        self.ctx = ctx
        self.id = ctx.persona["id"]
        self.domains = list(ctx.persona["domains"])
        self.b = Builder(ctx, rng, distractor_numbers)
        self.rng = rng
        self.fixed = [r.links["refers_to"] for r in ctx.recs if r.type in ("correction", "retraction")]
        self.fix_domains = {DOMAIN_OF[r.type] for r in self.fixed}
        self.cands: list[Cand] = []

    def has_state(self, domain: str) -> int:
        return sum(1 for c in self.cands if c.domain == domain and "state" in c.skills and "change" not in c.skills)

    def attempt(
        self, domain: str, skills: list[str], need_fix: bool, tries: int, text_budget: list[int], reasons: dict
    ):
        """Up to `tries` candidates for this domain, the skill drawn from `skills` each time."""
        self.b.focus = (
            [r for r in self.fixed if domain == "cross" or DOMAIN_OF.get(r.type) == domain] if need_fix else []
        )
        for _ in range(tries):
            skill = self.rng.choice(skills)
            got = GENERATORS[(domain, skill)](self.b, need_fix)
            if isinstance(got, Cand):
                if got.answer_type == "text" and text_budget[0] <= 0:
                    self.b.used.discard(got.question)
                    reasons["text budget spent"] = reasons.get("text budget spent", 0) + 1
                    continue
                if got.answer_type == "text":
                    text_budget[0] -= 1
                self.cands.append(got)
                return got
            reasons[got] = reasons.get(got, 0) + 1
        return None


def _explain(what: str, reasons: dict) -> GenerationError:
    detail = "; ".join(f"{k} x{v}" for k, v in sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0]))[:8])
    return GenerationError(f"no valid question for {what} after {MAX_ATTEMPTS} tries per user: {detail}")


def build_all(ctxs: list[UserCtx], n_per_user: int, seed_key: str, text_budget: list[int]) -> dict[str, list[dict]]:
    """
    Fills every user's questions in four passes, each sampling candidates until one passes every rule:
    1. every skill in every domain it applies to (the correction skill as a question that needs one),
       on whichever user tracking the domain can supply it, the least loaded first;
    2. cross questions up to CROSS_SHARE;
    3. questions that need a correction up to CORRECTION_SHARE, on users holding one in that domain;
    4. the rest, by domain and skill weights.
    A pass that cannot be met raises GenerationError with the reasons candidates were refused.
    """
    users = [
        User(
            ctx,
            random.Random(f"{seed_key}:{ctx.persona['id']}:questions"),
            [n for r in ctx.recs if r.type == "distractor" for n in r.stated["numbers"]],
        )
        for ctx in ctxs
    ]
    rng = random.Random(f"{seed_key}:schedule")
    total = n_per_user * len(users)

    def room(u: User) -> bool:
        return len(u.cands) < n_per_user

    def place(domain: str, skills: list[str], need_fix: bool, who: list, what: str, tries: int = MAX_ATTEMPTS) -> None:
        reasons: dict[str, int] = {}
        order = sorted((u for u in who if room(u)), key=lambda u: (len(u.cands), rng.random()))
        for u in order:
            if u.attempt(domain, skills, need_fix, tries, text_budget, reasons):
                return
        raise _explain(what, reasons)

    # 1. coverage
    for domain in ("spending", "food", "training", "body"):
        trackers = [u for u in users if domain in u.domains]
        for skill in APPLIES[domain]:
            if skill == "correction":
                place(
                    domain,
                    list(FIX_SKILLS[domain]),
                    True,
                    [u for u in trackers if domain in u.fix_domains],
                    f"{domain}/correction",
                )
            else:
                place(domain, [skill], False, trackers, f"{domain}/{skill}")
    # 2. cross share
    while sum(c.domain == "cross" for u in users for c in u.cands) < math.ceil(CROSS_SHARE * total):
        place("cross", ["cross"], False, users, "cross")

    # 3. correction share
    def flagged() -> int:
        return sum("correction" in c.skills for u in users for c in u.cands)

    guard = 0
    while flagged() < math.ceil(CORRECTION_SHARE * total) and guard < total:
        guard += 1
        options = [(u, d) for u in users if room(u) for d in u.domains if d in u.fix_domains]
        if not options:
            break
        low = min(len(u.cands) for u, _ in options)
        u, d = rng.choice([o for o in options if len(o[0].cands) == low])
        u.attempt(d, list(FIX_SKILLS[d]), True, MAX_ATTEMPTS // 4, text_budget, {})
    # 4. the rest
    weights = {"spending": 1.3, "food": 1.0, "training": 1.0, "body": 0.9}
    for u in users:
        misses: dict[str, int] = {}
        picks = 0
        while room(u):
            picks += 1
            if picks > 60 * n_per_user:
                raise _explain(f"{u.id} (filling)", misses)
            d = rng.choices(u.domains, weights=[weights[x] for x in u.domains])[0]
            skills = [
                s for s in APPLIES[d] if s != "correction" and not (s == "state" and u.has_state(d) >= STATE_CAP[d])
            ]
            s = rng.choices(skills, weights=[FILL_WEIGHTS[x] for x in skills])[0]
            u.attempt(d, [s], False, 40, text_budget, misses)
    out = {}
    for u in users:
        cands = list(u.cands)
        u.rng.shuffle(cands)
        out[u.id] = [question_dict(u.ctx, n, c) for n, c in enumerate(cands, start=1)]
    return out


def question_dict(ctx: UserCtx, n: int, cand: Cand) -> dict:
    return {
        "id": f"{ctx.persona['id']}:q{n}",
        "domain": cand.domain,
        "skills": cand.skills,
        "question": cand.question,
        "answer_type": cand.answer_type,
        "gold": cand.gold,
        "unit": cand.unit,
        "rel_tol": cand.rel_tol,
        "abs_tol": cand.abs_tol,
        "gold_text": cand.gold_text,
        "aliases": aliases_for(cand),
        "choices": cand.choices,
        "asked_on": iso(ctx.last),
        "evidence": cand.evidence,
        "derivation": cand.derivation,
    }


def aliases_for(cand: Cand):
    """A list for a category, a dict per member for a set, [] otherwise. The gold itself is always first."""
    a = cand.aliases
    if cand.answer_type == "category":
        found = a(cand.gold) if callable(a) else (a or [])
        return list(dict.fromkeys([cand.gold, *found]))
    if cand.answer_type == "set":
        out = {}
        for m in cand.gold:
            found = a(m) if callable(a) else (a.get(m, []) if isinstance(a, dict) else [])
            out[m] = list(dict.fromkeys([m, *found]))
        return out
    return []
