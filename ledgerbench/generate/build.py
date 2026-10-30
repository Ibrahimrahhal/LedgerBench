"""
One user from persona to sessions and events.

1. The domain simulators write records and messages (text not yet rendered).
2. About 10% of the record messages are said a day or two late.
3. About 3% of the logged records get a misstatement that a later message
   corrects, and about 1% are retracted, 1 to 10 days after they were said.
4. Each day's messages are ordered, held to 1..10, and rendered; ids are given
   in session order, and the records become events.
"""

from __future__ import annotations

import copy
from datetime import timedelta

from ledgerbench.generate import body, distractors, food, spending, training
from ledgerbench.generate.calendar import iso, relative_day, span, weekday
from ledgerbench.generate.core import MORNING, Msg, Rec, UserCtx
from ledgerbench.generate.phrasing import cap

LOGGED = {
    "expense": "spending", "meal": "food", "water": "food", "workout": "training", "run": "training",
    "weight": "body", "sleep_hours": "body", "steps": "body", "resting_hr": "body",
}  # fmt: skip
FIXERS = {"spending": spending, "food": food, "training": training, "body": body}
CORRECTION_RATE = 0.03
RETRACTION_RATE = 0.01
LATE_RATE = 0.10
MAX_MESSAGES = 10


def build_user(persona: dict, seed: int, size: str) -> UserCtx:
    days = span(persona["start"], persona["n_days"])
    ctx = UserCtx(persona, days, f"{seed}:{size}:{persona['id']}")
    for domain, module in (("spending", spending), ("food", food), ("training", training), ("body", body)):
        if domain in persona["domains"]:
            module.simulate(ctx)
    distractors.simulate(ctx)
    make_late(ctx)
    make_fixes(ctx)
    pack(ctx)
    return ctx


def make_late(ctx: UserCtx) -> None:
    rng = ctx.rng("late")
    for m in ctx.msgs:
        if m.kind != "record" or not m.can_be_late or not m.recs:
            continue
        if any(r.tags.get("copy") or r.tags.get("copy_source") for r in m.recs):
            continue
        if rng.random() >= LATE_RATE:
            continue
        late = 1 if rng.random() < 0.8 else 2
        if m.day + timedelta(days=late) > ctx.last:
            continue
        m.late = late
        m.day = m.day + timedelta(days=late)
        m.slot = MORNING + rng.random() * 3


def make_fixes(ctx: UserCtx) -> None:
    rng = ctx.rng("fixes")
    rr = ctx.rng("fixes-render")
    cur = ctx.persona["currency"]
    units = ctx.persona["units"]
    logged = [r for r in ctx.recs if r.type in LOGGED]
    # what each record is called on its day, and how many share the name
    counts: dict[tuple, int] = {}
    for r in logged:
        k = (r.date, FIXERS[LOGGED[r.type]].key(r))
        counts[k] = counts.get(k, 0) + 1

    def unique(r: Rec) -> bool:
        return counts[(r.date, FIXERS[LOGGED[r.type]].key(r))] == 1

    def eligible(r: Rec, retract: bool) -> bool:
        if r.fixed is not None or r.msg is None or not unique(r):
            return False
        module = FIXERS[LOGGED[r.type]]
        ok = module.retractable(r) if retract else module.correctable(r)
        return ok and r.msg.day + timedelta(days=1) <= ctx.last

    n_corr = max(1, round(CORRECTION_RATE * len(logged)))
    n_retr = max(1, round(RETRACTION_RATE * len(logged)))
    by_domain: dict[str, list[Rec]] = {}
    for r in logged:
        by_domain.setdefault(LOGGED[r.type], []).append(r)
    chosen: list[tuple[Rec, bool]] = []
    # at least one correction in each domain the user tracks, then the rest at random
    for domain in ctx.persona["domains"]:
        pool = [r for r in by_domain.get(domain, []) if eligible(r, False)]
        if pool:
            r = rng.choice(pool)
            r.fixed = "pending"
            chosen.append((r, False))
    pool = [r for r in logged if eligible(r, False)]
    rng.shuffle(pool)
    for r in pool:
        if sum(1 for _, x in chosen if not x) >= n_corr:
            break
        if r.fixed is None:
            r.fixed = "pending"
            chosen.append((r, False))
    pool = [r for r in logged if eligible(r, True)]
    rng.shuffle(pool)
    for r in pool[:n_retr]:
        r.fixed = "pending"
        chosen.append((r, True))

    chosen.sort(key=lambda t: (t[0].date, ctx.recs.index(t[0])))
    for r, retract in chosen:
        lag = rng.choice([1, 1, 2, 2, 3, 4, 5, 6, 7, 8, 9, 10])
        said = r.msg.day + timedelta(days=lag)
        if said > ctx.last:
            said = ctx.last
        if (said - r.date).days > 12:
            said = r.date + timedelta(days=12)
        when = relative_day(r.date, said)
        domain = LOGGED[r.type]
        module = FIXERS[domain]
        if retract:
            fx = ctx.rec("retraction", r.date, {}, links={"refers_to": r})
            r.retracted = True
            text = module.retraction_text(r, when, rr)
            kind = "retraction"
        else:
            if domain == "training":
                field, value = module.misstate(r, rng, units["lifts"])
                text = module.correction_text(r, when, units["lifts"], rr)
            elif domain == "body":
                field, value = module.misstate(r, rng)
                text = module.correction_text(r, when, units["body_weight"], rr)
            elif domain == "spending":
                field, value = module.misstate(r, rng)
                text = module.correction_text(r, when, cur, rr)
            else:
                field, value = module.misstate(r, rng)
                text = module.correction_text(r, when, rr)
            was = get_path(r.stated, field)
            fx = ctx.rec("correction", r.date, {"field": field, "value": value, "was": was}, links={"refers_to": r})
            kind = "correction"
        r.fixed = fx
        said_text = cap(text)
        ctx.say(said, 2 + rng.random() * 4, [fx], lambda late, t=said_text: t, kind=kind, priority=8, can_be_late=False)


def get_path(obj, path: str):
    parts = path.split(".")
    cur = obj
    for i, p in enumerate(parts):
        if p == "*":
            return get_path(cur[0], ".".join(parts[i + 1 :]))
        cur = cur[int(p)] if p.isdigit() else cur[p]
    return cur


def pack(ctx: UserCtx) -> None:
    """Orders each day's messages, holds a day to 1..10 messages, renders, and gives ids."""
    rng = ctx.rng("pack")
    order = {id(m): k for k, m in enumerate(ctx.msgs)}
    by_day: dict = {d: [] for d in ctx.days}
    for m in ctx.msgs:
        by_day[m.day].append(m)
    dropped: set[int] = set()
    sessions = []
    for d in ctx.days:
        msgs = sorted(by_day[d], key=lambda m: (m.slot, order[id(m)]))
        while len(msgs) > MAX_MESSAGES:
            low = [m for m in msgs if m.kind in ("filler", "distractor")]
            if low:
                victim = min(low, key=lambda m: (m.priority, order[id(m)]))
                msgs.remove(victim)
                dropped.add(id(victim))
                continue
            # merge the two adjacent record messages with the fewest records
            k = min(range(len(msgs) - 1), key=lambda j: (len(msgs[j].recs) + len(msgs[j + 1].recs), j))
            a, b = msgs[k], msgs[k + 1]
            merged = Msg(
                d,
                a.slot,
                a.recs + b.recs,
                _join(a.render, b.render, a.late, b.late),
                "record",
                max(a.priority, b.priority),
                False,
            )
            merged.late = 0
            msgs[k : k + 2] = [merged]
        if not msgs:
            filler = rng.choice(distractors.FILLERS)
            msgs = [Msg(d, 5, [], lambda late, t=filler: t, "filler", 1)]
        for m in msgs:
            m.text = cap(m.render(m.late))
        sessions.append((d, msgs))
    ctx.recs = [r for r in ctx.recs if not (r.msg is not None and id(r.msg) in dropped)]
    n = 0
    for d, msgs in sessions:
        for idx, m in enumerate(msgs):
            for r in m.recs:
                n += 1
                r.id = f"{ctx.persona['id']}:e{n}"
                r.msg = m
                r.tags["session"] = d
                r.tags["index"] = idx
    ctx.recs = [r for r in ctx.recs if r.id is not None]
    ctx.recs.sort(key=lambda r: int(r.id.rsplit("e", 1)[1]))
    ctx.sessions = [{"date": iso(d), "weekday": weekday(d), "messages": [m.text for m in msgs]} for d, msgs in sessions]


def _join(ra, rb, la, lb):
    def render(_late: int) -> str:
        return ra(la) + " " + rb(lb)

    return render


def events_of(ctx: UserCtx) -> list[dict]:
    out = []
    for r in ctx.recs:
        e = {
            "id": r.id,
            "type": r.type,
            "date": iso(r.date),
            "session_date": iso(r.tags["session"]),
            "message": r.tags["index"],
        }
        fields = copy.deepcopy(r.stated)
        for k, target in r.links.items():
            fields[k] = target.id
        if r.type == "meal" and "same_as" in fields and fields["same_as"] is None:
            del fields["same_as"]
        e.update(fields)
        out.append(e)
    return out
