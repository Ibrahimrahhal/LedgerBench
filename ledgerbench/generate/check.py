"""
The checker (spec section 8): re-derives every gold answer from a dataset's
`events` and each question's `derivation`, with code that shares nothing with
the question builders, and enforces the dataset's rules.

It reads only the written JSON (as a dict). It imports nothing from the rest
of the generator, so a bug in a builder cannot hide in a shared helper.

The derivation language
-----------------------
Every derivation has `op` and `after` (the corrections and retractions that
truth reflects: always both). Number golds carry `round`, the decimals the gold
was rounded to.

A *selection* picks rows:
  type        an event type, or a list of types
  unnest      a list field to expand: each element becomes a row with its
              parent's id and date (`exercises`, `items`)
  where       {field: value}, equality on the row (an element when unnested)
  exclude     {field: [values]}, rows whose field is one of these are dropped
  from, to    inclusive ISO dates on the event's `date`
  weekdays    weekday names the date must fall on
  days        a condition on the date (below)
  field       a path: `amount`, `items.*.kcal`, `sets.*.reps`, `sets.#`
              (the length of a list), `date`
  within      how a path that yields a list reduces within one row: `sum`
              (default), `max`, or `list` (kept as a list)
  per         `date`: rows are first summed per date, and the op runs over dates
  net_refunds subtract `refund` events dated in the period whose refunded
              expense still exists and passes `where` / `exclude`

ops: sum, count, count_days (distinct dates), avg, min, max (`return`: value
or date; the extreme must be unique), first, last (by date), lookup (exactly
one row), top (`by` a field or `weekday`; `measure` sum, count or avg;
`margin` {"abs": n} or {"rel": x} the winner must clear), as_of (`on` a date,
`of` one of plan, target, budget, recurring, reading, owed), diff (`left`
minus `right`), plan_count (`count`: planned, done or missed, using the plan in
force on each day).

Day conditions: {"has": {"type", "where"}}, {"below": {"type", "field",
"value"}}, {"over_target" | "at_least_target": {"type", "field", "target"}}
(the day's total against the target in force that day; only days with rows).
"""

from __future__ import annotations

import copy
import re
from datetime import date, timedelta

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
SIZES = {"mini": (3, 21, 20), "standard": (12, 90, 40), "long": (6, 365, 60)}
APPLIES = {
    "spending": {"lookup", "aggregate", "group", "window", "state", "as_of", "change", "correction", "budget"},
    "food": {"lookup", "aggregate", "group", "window", "state", "as_of", "change", "correction", "adherence"},
    "training": {"lookup", "aggregate", "group", "window", "state", "as_of", "change", "correction", "adherence"},
    "body": {"lookup", "aggregate", "group", "window", "state", "as_of", "change", "correction"},
    "cross": {"cross", "aggregate", "correction"},
}
REQUIRED = {(d, s) for d, skills in APPLIES.items() for s in skills if d != "cross" or s == "cross"}
ANSWER_TYPES = {"number", "count", "date", "category", "set", "text"}
MIN_RECORDS = 3
_ISO_IN_TEXT = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_PERIOD = re.compile(r"\b(?:" + "|".join(MONTHS) + r")\b[^?]*?\b20\d\d\b|\bnow\b")


class CheckError(AssertionError):
    pass


class Undefined(Exception):
    """The derivation has no answer on these events (for example, a lookup that finds two rows)."""


# ------------------------------------------------------------------ events


class Store:
    """A user's events with corrections and retractions applied (or not)."""

    def __init__(self, events: list[dict], apply: bool):
        self.order = {e["id"]: k for k, e in enumerate(events)}
        live = {e["id"]: copy.deepcopy(e) for e in events}
        if apply:
            for e in events:
                if e["type"] == "correction":
                    _set_path(live[e["refers_to"]], e["field"], e["value"])
            for e in events:
                if e["type"] == "retraction":
                    live.pop(e["refers_to"], None)
        self.live = live
        self.events = [live[e["id"]] for e in events if e["id"] in live]

    def of(self, types) -> list[dict]:
        types = types if isinstance(types, list) else [types]
        return [e for e in self.events if e["type"] in types]


def _set_path(obj, path: str, value) -> None:
    parts = path.split(".")
    targets = [obj]
    for p in parts[:-1]:
        nxt = []
        for t in targets:
            if p == "*":
                nxt.extend(t)
            else:
                nxt.append(t[int(p)] if isinstance(t, list) else t[p])
        targets = nxt
    last = parts[-1]
    for t in targets:
        if last == "*":
            for i in range(len(t)):
                t[i] = value
        elif isinstance(t, list):
            t[int(last)] = value
        else:
            t[last] = value


def _get(obj, parts: list[str]):
    if not parts:
        return obj
    p = parts[0]
    if p == "#":
        return len(obj)
    if p == "*":
        out = []
        for x in obj:
            got = _get(x, parts[1:])
            out.extend(got if isinstance(got, list) else [got])
        return out
    if isinstance(obj, list):
        return _get(obj[int(p)], parts[1:])
    return _get(obj[p], parts[1:])


def field_value(row: dict, path: str, within: str = "sum"):
    if path == "date":
        return row["date"]
    v = _get(row, path.split("."))
    if isinstance(v, list):
        if within == "list":
            return v
        if within == "max":
            return max(v)
        return sum(v)
    return v


def wd(iso_date: str) -> str:
    return WEEKDAYS[date.fromisoformat(iso_date).weekday()]


def dates_between(a: str, b: str) -> list[str]:
    d, end = date.fromisoformat(a), date.fromisoformat(b)
    out = []
    while d <= end:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


# ------------------------------------------------------------------ the evaluator


class Result:
    def __init__(self, value, ids: set[str], n: int):
        self.value = value
        self.ids = ids
        self.n = n


class Evaluator:
    """`strict` enforces the quality rules on the gold (a top group's margin); the as-stated evaluation does not."""

    def __init__(self, store: Store, strict: bool = True):
        self.s = store
        self.strict = strict

    # -- selections
    def rows(self, d: dict) -> list[dict]:
        days = self.day_set(d["days"]) if d.get("days") is not None else None
        out = []
        for e in self.s.of(d["type"]):
            if "default" in d:
                e = {**d["default"], **e}
            if d.get("unnest"):
                for el in e.get(d["unnest"], []):
                    out.append({**el, "id": e["id"], "date": e["date"], "_parent": e})
            else:
                out.append(e)
        return [r for r in out if self.keep(r, d, days)]

    def keep(self, r: dict, d: dict, days: set[str] | None) -> bool:
        if "from" in d and r["date"] < d["from"]:
            return False
        if "to" in d and r["date"] > d["to"]:
            return False
        if d.get("weekdays") and wd(r["date"]) not in d["weekdays"]:
            return False
        for k, v in (d.get("where") or {}).items():
            if r.get(k) != v:
                return False
        for k, vs in (d.get("exclude") or {}).items():
            if r.get(k) in vs:
                return False
        if days is not None and r["date"] not in days:
            return False
        return True

    def refunds(self, d: dict) -> list[dict]:
        days = self.day_set(d["days"]) if d.get("days") is not None else None
        out = []
        for r in self.s.of("refund"):
            target = self.s.live.get(r["refers_to"])
            if target is None:
                continue
            probe = {**target, "date": r["date"]}
            if self.keep(probe, d, days):
                out.append(r)
        return out

    def day_set(self, cond: dict) -> set[str]:
        ((kind, spec),) = cond.items()
        if kind == "has":
            return {
                e["date"]
                for e in self.s.of(spec["type"])
                if all(e.get(k) == v for k, v in (spec.get("where") or {}).items())
            }
        if kind == "below":
            return {e["date"] for e in self.s.of(spec["type"]) if field_value(e, spec["field"]) < spec["value"]}
        if kind in ("over_target", "at_least_target"):
            totals: dict[str, float] = {}
            for e in self.s.of(spec["type"]):
                totals[e["date"]] = totals.get(e["date"], 0) + field_value(e, spec["field"])
            out = set()
            for day, t in totals.items():
                target = self.target_on(spec["target"], day)
                if target is None:
                    continue
                if (t > target[0]) if kind == "over_target" else (t >= target[0]):
                    out.add(day)
            return out
        raise ValueError(f"unknown day condition {kind}")

    # -- timelines
    def latest(self, events: list[dict], key) -> dict | None:
        best = None
        for e in events:
            k = (key(e), self.s.order[e["id"]])
            if best is None or k > best[0]:
                best = (k, e)
        return best[1] if best else None

    def plan_on(self, day: str) -> dict:
        cands = [e for e in self.s.of(["plan", "plan_change"]) if e["from"] <= day]
        e = self.latest(cands, lambda x: x["from"])
        if e is None:
            raise Undefined(f"no plan in force on {day}")
        return e

    @staticmethod
    def plan_body(e: dict) -> dict:
        return e["plan"] if e["type"] == "plan_change" else {"days": e["days"], "sessions": e["sessions"]}

    def target_on(self, type_: str, day: str):
        e = self.latest([x for x in self.s.of(type_) if x["from"] <= day], lambda x: x["from"])
        return None if e is None else (e["amount"], e)

    def as_of(self, on: str, spec: dict) -> Result:
        kind = spec["kind"]
        if kind == "plan":
            e = self.plan_on(on)
            plan = self.plan_body(e)
            x = spec["extract"]
            if x == "days_for":
                value = [w for w in WEEKDAYS if plan["days"][w] == spec["session"]]
                if not value:
                    raise Undefined("session not on the plan")
            elif x == "session_on":
                value = plan["days"][spec["weekday"]]
            elif x == "count_days":
                value = sum(1 for w in WEEKDAYS if plan["days"][w] != "Rest")
            else:
                found = [p for sess in plan["sessions"].values() for p in sess if p["exercise"] == spec["exercise"]]
                if not found:
                    raise Undefined("exercise not on the plan")
                p = found[0]
                if x == "weight":
                    value = p["weight"]
                elif x == "prescription":
                    value = f"{p['sets']}x{p['reps']} at {p['weight']:g} {spec['unit']}"
                else:
                    raise ValueError(x)
            return Result(value, {e["id"]}, 1)
        if kind == "target":
            got = self.target_on(spec["type"], on)
            if got is None:
                raise Undefined("no target")
            return Result(got[0], {got[1]["id"]}, 1)
        if kind == "budget":
            e = self.latest(
                [x for x in self.s.of("budget") if x["category"] == spec["category"] and x["from"] <= on],
                lambda x: x["from"],
            )
            if e is None:
                raise Undefined("no budget")
            return Result(e["amount"], {e["id"]}, 1)
        if kind == "recurring":
            decl = [x for x in self.s.of("recurring") if x["name"] == spec["name"] and x["date"] <= on]
            if not decl:
                raise Undefined("not declared")
            base = decl[-1]
            changes = [x for x in self.s.of("price_change") if x["refers_to"] == base["id"] and x["from"] <= on]
            ch = self.latest(changes, lambda x: x["from"])
            return Result(ch["amount"] if ch else base["amount"], {base["id"]} | ({ch["id"]} if ch else set()), 1)
        if kind == "reading":
            e = self.latest([x for x in self.s.of(spec["type"]) if x["date"] <= on], lambda x: x["date"])
            if e is None:
                raise Undefined("no reading")
            return Result(e["value"], {e["id"]}, 1)
        if kind == "owed":
            splits = [x for x in self.s.of("split") if x["person"] == spec["person"] and x["date"] <= on]
            settled = [x for x in self.s.of("settled") if x["person"] == spec["person"] and x["date"] <= on]
            value = sum(x["owed"] for x in splits) - sum(x["amount"] for x in settled)
            return Result(value, {x["id"] for x in splits + settled}, len(splits) + len(settled))
        raise ValueError(f"unknown as_of kind {kind}")

    # -- ops
    def eval(self, d: dict) -> Result:
        op = d["op"]
        if op == "diff":
            left, right = self.eval(d["left"]), self.eval(d["right"])
            return Result(left.value - right.value, left.ids | right.ids, left.n + right.n)
        if op == "as_of":
            return self.as_of(d["on"], d["of"])
        if op == "plan_count":
            planned = done = 0
            ids: set[str] = set()
            for day in dates_between(d["from"], d["to"]):
                e = self.plan_on(day)
                ids.add(e["id"])
                session = self.plan_body(e)["days"][wd(day)]
                if session == "Rest":
                    continue
                planned += 1
                if session == "Run":
                    hit = [x for x in self.s.of("run") if x["date"] == day]
                else:
                    hit = [x for x in self.s.of("workout") if x["date"] == day and x["session"] == session]
                if hit:
                    done += 1
                    ids |= {x["id"] for x in hit}
            value = {"planned": planned, "done": done, "missed": planned - done}[d["count"]]
            return Result(value, ids, planned)
        rows = self.rows(d)
        ids = {r["id"] for r in rows}
        within = d.get("within", "sum")
        if op == "count":
            return Result(len(rows), ids, len(ids))
        if op == "count_days":
            return Result(len({r["date"] for r in rows}), ids, len(ids))
        if op == "lookup":
            if len(rows) != 1:
                raise Undefined(f"lookup found {len(rows)} rows")
            return Result(field_value(rows[0], d["field"], within), ids, 1)
        if op == "top":
            return self.top(d, rows)
        values = [(r, field_value(r, d["field"], within)) for r in rows]
        refunds = self.refunds(d) if d.get("net_refunds") else []
        ids |= {r["id"] for r in refunds}
        n = len(ids)
        if d.get("per") == "date":
            by_day: dict[str, float] = {}
            for r, v in values:
                by_day[r["date"]] = by_day.get(r["date"], 0) + v
            series = sorted(by_day.items())
        else:
            series = [(r["date"], v) for r, v in values]
        if op == "sum":
            return Result(sum(v for _, v in series) - sum(r["amount"] for r in refunds), ids, n)
        if not series:
            raise Undefined("nothing selected")
        if op == "avg":
            return Result(sum(v for _, v in series) / len(series), ids, n)
        if op in ("min", "max"):
            best = (max if op == "max" else min)(v for _, v in series)
            if d.get("return") != "date":
                return Result(best, ids, n)
            winners = [day for day, v in series if v == best]
            if len(winners) != 1:
                raise Undefined("the extreme is shared, so it has no one date")
            return Result(winners[0], ids, n)
        if op in ("first", "last"):
            ordered = sorted(rows, key=lambda r: (r["date"], self.s.order[r["id"]]))
            pick = ordered[0] if op == "first" else ordered[-1]
            return Result(field_value(pick, d["field"], within), ids, n)
        raise ValueError(f"unknown op {op}")

    def top(self, d: dict, rows: list[dict]) -> Result:
        groups: dict[str, list[float]] = {}
        for r in rows:
            key = wd(r["date"]) if d["by"] == "weekday" else r.get(d["by"])
            v = 1 if d["measure"] == "count" else field_value(r, d["field"], d.get("within", "sum"))
            groups.setdefault(key, []).append(v)
        totals = {k: (sum(v) / len(v) if d["measure"] == "avg" else sum(v)) for k, v in groups.items()}
        ids = {r["id"] for r in rows}
        if d.get("net_refunds"):
            for rf in self.refunds(d):
                key = self.s.live[rf["refers_to"]].get(d["by"])
                totals[key] = totals.get(key, 0) - rf["amount"]
                ids.add(rf["id"])
        ranked = sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))
        if len(ranked) < 2:
            raise Undefined("fewer than two groups")
        (k1, v1), (_, v2) = ranked[0], ranked[1]
        m = (d.get("margin") or {}) if self.strict else {}
        if "abs" in m and not v1 - v2 >= m["abs"]:
            raise Undefined(f"top group wins by {v1 - v2}, under the margin")
        if "rel" in m and not v1 > v2 * (1 + m["rel"]):
            raise Undefined("top group wins by less than the relative margin")
        return Result(k1, ids, len(ids))


# ------------------------------------------------------------------ the checks


def _singular(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith(("sses", "shes", "ches", "xes")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _contains(outer: str, inner: str) -> bool:
    """`inner`'s words run inside `outer`'s, plurals aside ('front squat' contains 'squats')."""
    a = [_singular(w) for w in re.findall(r"[a-z0-9]+", outer.lower())]
    b = [_singular(w) for w in re.findall(r"[a-z0-9]+", inner.lower())]
    return bool(b) and any(a[i : i + len(b)] == b for i in range(len(a) - len(b) + 1))


_BARE_MONTH = re.compile(r"(?<!\d )\b(?P<month>" + "|".join(MONTHS) + r") (?P<year>20\d\d)\b")
_RENT = re.compile(r"\brent\b", re.IGNORECASE)


def _whole_months(text: str, asked_on: str) -> list[str]:
    """
    A month named without a day ("in March 2026") must be over by `asked_on`. A month still running is
    named as the days it has had: "so far in March 2026 (1 to 21 March)".
    """
    asked = date.fromisoformat(asked_on)
    out = []
    for m in _BARE_MONTH.finditer(text):
        month, year = MONTHS.index(m["month"]) + 1, int(m["year"])
        nxt = date(year + (month == 12), month % 12 + 1, 1)
        if nxt - timedelta(days=1) <= asked:
            continue
        days = f"1 {m['month']} only" if asked.day == 1 else f"1 to {asked.day} {m['month']}"
        partial = (asked.year, asked.month) == (year, month)
        if not (partial and text[: m.start()].endswith("so far in ") and text[m.end() :].startswith(f" ({days})")):
            out.append(f"names {m['month']} {year} as a whole month, but the log ends on {asked_on}")
    return out


def _periods(d: dict) -> list[tuple[str, str]]:
    """Every (from, to) a derivation selects over, through diffs."""
    out = [(d["from"], d["to"])] if "from" in d and "to" in d else []
    for side in ("left", "right"):
        if isinstance(d.get(side), dict):
            out += _periods(d[side])
    return out


def _tolerance(q: dict) -> float:
    if q["answer_type"] == "count":
        return 0.0
    return max(q["abs_tol"], q["rel_tol"] * abs(q["gold"]))


def _same(q: dict, value, gold) -> bool:
    t = q["answer_type"]
    if t == "number":
        dec = q["derivation"]["round"]
        return abs(float(value) - float(gold)) <= 0.5 * 10 ** (-dec) + 1e-9
    if t == "count":
        return isinstance(value, (int, float)) and float(value).is_integer() and int(value) == gold
    if t == "set":
        return sorted(value) == sorted(gold)
    return value == gold


def _scored_right(q: dict, value) -> bool:
    """Would `value` be scored as the gold? Used for the correction flag."""
    t = q["answer_type"]
    if t == "number":
        return abs(float(value) - q["gold"]) <= _tolerance(q) + 1e-9
    if t == "count":
        return value == q["gold"]
    if t == "set":
        return sorted(value) == sorted(q["gold"])
    return value == q["gold"]


def check_question(
    q: dict, user: dict, ev_true: Evaluator, ev_naive: Evaluator, distractors: list[float], problems: list[str]
) -> None:
    qid = q["id"]
    say = lambda msg: problems.append(f"{qid}: {msg}")  # noqa: E731
    t = q["answer_type"]
    if t not in ANSWER_TYPES:
        return say(f"unknown answer_type {t}")
    if q["domain"] != "cross" and q["domain"] not in user["domains"]:
        say(f"asks about {q['domain']}, which the user does not track")
    for s in q["skills"]:
        if s not in APPLIES.get(q["domain"], set()):
            say(f"skill {s} does not apply to {q['domain']}")
    if not _PERIOD.search(q["question"]):
        say("the question does not name its period (a month and year, a date, or now)")
    for problem in _whole_months(q["question"], q["asked_on"]):
        say(problem)
    if _RENT.search(q["question"]):
        periods = _periods(q["derivation"])
        rents = [e["date"] for e in ev_true.s.of("expense") if e.get("category") == "rent"]
        if periods and not any(a <= r <= z for a, z in periods for r in rents):
            say("mentions rent, but no rent was paid in the period")
    if q["derivation"].get("after") != ["corrections", "retractions"]:
        say("derivation does not say it is after corrections and retractions")
    known = {e["id"] for e in user["events"]}
    for e in q["evidence"]:
        if e not in known:
            say(f"evidence {e} is not an event")
    if not q.get("gold_text"):
        say("empty gold_text")
    try:
        res = ev_true.eval(q["derivation"])
    except Undefined as exc:
        return say(f"derivation has no answer: {exc}")
    gold = q["gold"]
    if not _same(q, res.value, gold):
        return say(f"gold is {gold!r} but the events give {res.value!r}")
    missing = sorted(res.ids - set(q["evidence"]))
    if missing:
        say(f"evidence leaves out records the answer rests on: {missing[:5]}")
    if t in ("number", "count"):
        if q.get("rel_tol") is None or q.get("abs_tol") is None:
            say("numeric question without rel_tol and abs_tol")
        if t == "number" and not gold > 0:
            say(f"number gold {gold} is not positive")
        exempt = bool({"lookup", "state", "as_of"} & set(q["skills"])) or q["derivation"]["op"] in ("min", "max")
        if not exempt and res.n < MIN_RECORDS:
            say(f"rests on {res.n} records, fewer than {MIN_RECORDS}")
        tol = _tolerance(q)
        for n in distractors:
            if abs(n - gold) <= tol + 1e-9:
                say(f"distractor number {n:g} is within tolerance ({tol:g}) of the gold {gold}")
        for n in _NUMBER.findall(q["question"]):
            if abs(float(n.replace(",", "")) - gold) <= tol + 1e-9:
                say(f"the question itself states {n}, within tolerance of the gold {gold}")
        first = _NUMBER.search(q["gold_text"])
        if not first or abs(float(first.group().replace(",", "")) - gold) > tol + 1e-9:
            say(f"gold_text {q['gold_text']!r} does not lead with the gold")
    if t == "date":
        try:
            date.fromisoformat(gold)
        except (TypeError, ValueError):
            say(f"date gold {gold!r} is not ISO")
    if t in ("category", "set"):
        choices = q["choices"]
        members = gold if t == "set" else [gold]
        if not members:
            say("empty gold")
        for m in members:
            if m not in choices:
                say(f"gold member {m!r} is not among the choices")
        for i, a in enumerate(choices):
            for c in choices[i + 1 :]:
                if _contains(a, c) or _contains(c, a):
                    say(f"choices {a!r} and {c!r} contain one another")
        alias_map = q["aliases"] if t == "set" else {gold: q["aliases"]}
        if not isinstance(alias_map, dict):
            say("set aliases must be a dict per member")
            alias_map = {}
        for m, aliases in alias_map.items():
            for a in aliases:
                for c in choices:
                    if c != m and (_contains(a, c) or _contains(c, a)):
                        say(f"alias {a!r} of {m!r} overlaps the choice {c!r}")
    # the correction flag: on exactly when ignoring corrections and retractions would be scored wrong
    try:
        naive = ev_naive.eval(q["derivation"])
        depends = not _scored_right(q, naive.value)
    except Undefined:
        depends = True
    flagged = "correction" in q["skills"]
    if flagged != depends:
        say(
            "flagged as depending on a correction but does not"
            if flagged
            else "depends on a correction but is not flagged"
        )


def check(data: dict) -> dict:
    """Raises CheckError listing every problem; returns a few totals when all is well."""
    problems: list[str] = []
    size = data.get("size")
    if data.get("name") != "LedgerBench":
        problems.append("name is not LedgerBench")
    if size in SIZES:
        n_users, n_days, n_q = SIZES[size]
        if len(data["users"]) != n_users:
            problems.append(f"{size} needs {n_users} users, found {len(data['users'])}")
    else:
        n_days = n_q = None
    users = data["users"]
    seen_q: set[str] = set()
    for u in users:
        uid = u["id"]
        if any(ch.isdigit() for ch in u["profile"]):
            problems.append(f"{uid}: the profile contains a number")
        if u["currency"] not in ("EUR", "USD", "GBP"):
            problems.append(f"{uid}: currency {u['currency']}")
        if u["units"].get("body_weight") not in ("kg", "lb") or u["units"].get("lifts") not in ("kg", "lb"):
            problems.append(f"{uid}: units {u['units']}")
        if "spending" not in u["domains"]:
            problems.append(f"{uid}: does not track spending")
        sessions = u["sessions"]
        if n_days is not None and len(sessions) != n_days:
            problems.append(f"{uid}: {len(sessions)} sessions, expected {n_days}")
        for a, b in zip(sessions, sessions[1:], strict=False):
            if date.fromisoformat(b["date"]) - date.fromisoformat(a["date"]) != timedelta(days=1):
                problems.append(f"{uid}: sessions jump from {a['date']} to {b['date']}")
        index = {}
        for s in sessions:
            if s["weekday"] != wd(s["date"]):
                problems.append(f"{uid}: {s['date']} is a {wd(s['date'])}, not a {s['weekday']}")
            if not 1 <= len(s["messages"]) <= 10:
                problems.append(f"{uid}: {s['date']} has {len(s['messages'])} messages")
            for m in s["messages"]:
                if not m.strip():
                    problems.append(f"{uid}: empty message on {s['date']}")
                if _ISO_IN_TEXT.search(m):
                    problems.append(f"{uid}: an ISO date in a message on {s['date']}")
            index[s["date"]] = s
        ids = set()
        for k, e in enumerate(u["events"]):
            if e["id"] != f"{uid}:e{k + 1}":
                problems.append(f"{uid}: event {k} has id {e['id']}")
            ids.add(e["id"])
            s = index.get(e["session_date"])
            if s is None:
                problems.append(f"{e['id']}: session {e['session_date']} does not exist")
            elif not 0 <= e["message"] < len(s["messages"]):
                problems.append(f"{e['id']}: message {e['message']} is not in {e['session_date']}")
            if e["date"] > e["session_date"]:
                problems.append(f"{e['id']}: dated after the session that states it")
            for key in ("refers_to", "same_as"):
                if key in e and e[key] not in ids and e[key] not in {x["id"] for x in u["events"]}:
                    problems.append(f"{e['id']}: {key} {e[key]} does not exist")
        if n_q is not None and len(u["questions"]) != n_q:
            problems.append(f"{uid}: {len(u['questions'])} questions, expected {n_q}")
        ev_true = Evaluator(Store(u["events"], True))
        ev_naive = Evaluator(Store(u["events"], False), strict=False)
        distractors = [n for e in u["events"] if e["type"] == "distractor" for n in e["numbers"]]
        last = sessions[-1]["date"]
        for q in u["questions"]:
            if q["id"] in seen_q:
                problems.append(f"{q['id']}: duplicate id")
            seen_q.add(q["id"])
            if q["asked_on"] != last:
                problems.append(f"{q['id']}: asked_on {q['asked_on']} is not the last session {last}")
            check_question(q, u, ev_true, ev_naive, distractors, problems)

    # balance and coverage across the size
    n = len(users)
    for d in ("food", "training", "body"):
        if sum(d in u["domains"] for u in users) * 3 < 2 * n:
            problems.append(f"{d} is tracked by fewer than two thirds of users")
    if sum(len(u["domains"]) == 4 for u in users) * 3 < n:
        problems.append("fewer than a third of users track all four domains")
    qs = [q for u in users for q in u["questions"]]
    have = {(q["domain"], s) for q in qs for s in q["skills"]}
    for pair in sorted(REQUIRED - have):
        problems.append(f"coverage: no {pair[1]} question in {pair[0]}")
    total = len(qs) or 1
    flagged = sum("correction" in q["skills"] for q in qs)
    if flagged < 0.10 * total:
        problems.append(f"coverage: only {flagged} of {total} questions are flagged correction (needs 10%)")
    crossed = sum(q["domain"] == "cross" for q in qs)
    if crossed < 0.05 * total:
        problems.append(f"coverage: only {crossed} of {total} questions are cross (needs 5%)")
    texts = sum(q["answer_type"] == "text" for q in qs)
    if texts >= 0.10 * total:
        problems.append(f"coverage: {texts} text questions, 10% or more")
    if problems:
        shown = "\n  ".join(problems[:60])
        more = f"\n  ... and {len(problems) - 60} more" if len(problems) > 60 else ""
        raise CheckError(f"{len(problems)} problem(s) in the {size} dataset:\n  {shown}{more}")
    return {"questions": len(qs), "correction": flagged, "cross": crossed, "text": texts}


def check_file(path) -> dict:
    import json
    from pathlib import Path

    return check(json.loads(Path(path).read_text(encoding="utf-8")))


if __name__ == "__main__":  # python -m ledgerbench.generate.check data/ledgerbench-mini.json
    import sys

    for p in sys.argv[1:]:
        print(p, check_file(p))
