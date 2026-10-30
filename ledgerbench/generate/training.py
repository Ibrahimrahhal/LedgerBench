"""
Training: a weekly plan that keeps changing, the sessions logged against it,
the ones skipped, and runs.

The plan maps all seven weekdays to a session name (Rest on days off) and each
session to prescribed exercises with sets, reps and a working weight. It is
stated in full on the first day, then changed 3 to 8 times per 90 days in the
words a person uses ("bench goes up to 85 from Monday", "moving legs from
Friday to Saturday from next week"); every change event carries the whole
resulting plan. Workouts happen on planned days at the planned weights, with
a few heavier days, a few short last sets, some skips with a reason and a few
sessions that are simply missed.
"""

from __future__ import annotations

import copy
from datetime import date

from ledgerbench.generate.calendar import WEEKDAYS, next_monday, weekday
from ledgerbench.generate.core import EVENING, MORNING, NIGHT, Rec, UserCtx
from ledgerbench.generate.phrasing import cap, km, lift_weight, run_time, sets_text, with_late

SESSIONS = ("Push", "Pull", "Legs", "Upper", "Lower", "Full body", "Run", "Rest")
SESSION_ALIASES = {
    "Push": ["push", "push day"],
    "Pull": ["pull", "pull day"],
    "Legs": ["legs", "leg day"],
    "Upper": ["upper", "upper body"],
    "Lower": ["lower", "lower body"],
    "Full body": ["full body", "full-body"],
    "Run": ["run", "running"],
    "Rest": ["rest", "rest day", "off"],
}

# exercise: (sets, reps, kg low, kg high)
EXERCISES = {
    "bench press": (4, 6, 60, 100), "overhead press": (3, 8, 35, 60), "incline dumbbell press": (3, 10, 20, 32),
    "lateral raise": (3, 12, 8, 12), "triceps pushdown": (3, 12, 20, 35), "barbell row": (4, 8, 50, 90),
    "lat pulldown": (3, 10, 45, 70), "seated cable row": (3, 10, 45, 70), "face pull": (3, 15, 15, 25),
    "biceps curl": (3, 12, 10, 16), "back squat": (5, 5, 70, 140), "front squat": (4, 6, 50, 100),
    "deadlift": (3, 5, 90, 180), "leg press": (3, 10, 120, 220), "leg curl": (3, 12, 30, 55),
    "calf raise": (4, 12, 40, 100), "hip thrust": (3, 10, 60, 140), "walking lunge": (3, 12, 12, 24),
}  # fmt: skip
LABELS = {
    "bench press": ["bench", "bench press"], "overhead press": ["OHP", "overhead press"],
    "incline dumbbell press": ["incline DB press", "incline dumbbell press"], "lateral raise": ["lateral raises", "laterals"],
    "triceps pushdown": ["triceps pushdowns", "pushdowns"], "barbell row": ["barbell rows", "BB rows"],
    "lat pulldown": ["lat pulldowns", "pulldowns"], "seated cable row": ["cable rows", "seated cable rows"],
    "face pull": ["face pulls"], "biceps curl": ["biceps curls", "bicep curls"], "back squat": ["back squats", "squats"],
    "front squat": ["front squats"], "deadlift": ["deadlifts", "deads"], "leg press": ["leg press"],
    "leg curl": ["leg curls", "hamstring curls"], "calf raise": ["calf raises"], "hip thrust": ["hip thrusts"],
    "walking lunge": ["walking lunges", "lunges"],
}  # fmt: skip
EXERCISE_ALIASES = {
    "bench press": ["bench press", "bench"], "overhead press": ["overhead press", "OHP", "shoulder press"],
    "incline dumbbell press": ["incline dumbbell press", "incline DB press", "incline press"],
    "lateral raise": ["lateral raise", "laterals"], "triceps pushdown": ["triceps pushdown", "pushdowns", "tricep pushdown"],
    "barbell row": ["barbell row", "BB row"], "lat pulldown": ["lat pulldown", "pulldown"],
    "seated cable row": ["seated cable row", "cable row"], "face pull": ["face pull"],
    "biceps curl": ["biceps curl", "bicep curl"], "back squat": ["back squat"], "front squat": ["front squat"],
    "deadlift": ["deadlift", "deads"], "leg press": ["leg press"], "leg curl": ["leg curl", "hamstring curl"],
    "calf raise": ["calf raise"], "hip thrust": ["hip thrust"], "walking lunge": ["walking lunge", "lunges"],
}  # fmt: skip
TEMPLATES = {
    "Push": ["bench press", "overhead press", "incline dumbbell press", "lateral raise", "triceps pushdown"],
    "Pull": ["barbell row", "lat pulldown", "face pull", "biceps curl"],
    "Legs": ["back squat", "deadlift", "leg press", "leg curl", "calf raise"],
    "Upper": ["bench press", "barbell row", "overhead press", "lat pulldown", "biceps curl"],
    "Lower": ["back squat", "deadlift", "hip thrust", "leg curl", "calf raise"],
    "Full body": ["back squat", "bench press", "barbell row", "overhead press"],
    "Run": [],
}
SWAPS = {
    "back squat": ["front squat"], "deadlift": ["hip thrust"], "barbell row": ["seated cable row"],
    "bench press": ["incline dumbbell press"], "leg press": ["walking lunge"], "lat pulldown": ["seated cable row"],
    "lateral raise": ["face pull"], "biceps curl": ["face pull"],
}  # fmt: skip
PROGRAMS = {
    # name: list of possible week layouts (weekday index -> session)
    "ppl": [
        {0: "Push", 2: "Pull", 4: "Legs"},
        {0: "Push", 1: "Pull", 3: "Legs", 5: "Push"},
        {0: "Push", 1: "Pull", 2: "Legs", 4: "Push", 5: "Pull"},
    ],
    "upper_lower": [{0: "Upper", 1: "Lower", 3: "Upper", 4: "Lower"}, {0: "Upper", 2: "Lower", 4: "Upper"}],
    "full_run": [{0: "Full body", 2: "Run", 4: "Full body", 5: "Run"}, {1: "Full body", 3: "Full body", 6: "Run"}],
    "runner": [{1: "Run", 3: "Run", 5: "Run", 2: "Full body"}, {0: "Run", 2: "Run", 4: "Full body", 6: "Run"}],
}
SKIP_REASONS = [
    "knee is sore", "work ran late", "felt a cold coming on", "slept terribly", "the gym was closed for a staff event",
    "had to cover for a colleague", "back felt tight", "just wiped out",
]  # fmt: skip


def label(exercise: str, plan_vocab: set[str], rng) -> str:
    options = list(LABELS[exercise])
    if exercise == "back squat" and "front squat" in plan_vocab:
        options = ["back squats"]
    return rng.choice(options)


def plan_exercises(plan: dict) -> list[str]:
    out = []
    for s in plan["sessions"].values():
        for e in s:
            if e["exercise"] not in out:
                out.append(e["exercise"])
    return out


def describe_plan(plan: dict, unit: str, rng) -> str:
    """The first statement of the plan, in full."""
    days = [(wd, plan["days"][wd]) for wd in WEEKDAYS if plan["days"][wd] != "Rest"]
    sched = ", ".join(f"{wd} {s.lower() if s != 'Full body' else 'full body'}" for wd, s in days)
    parts = []
    vocab = set(plan_exercises(plan))
    for name in plan_session_order(plan):
        exs = plan["sessions"][name]
        if not exs:
            continue
        body = ", ".join(
            f"{label(e['exercise'], vocab, rng)} {e['sets']}x{e['reps']} @ {lift_weight(e['weight'], unit, rng, 0.2)}"
            for e in exs
        )
        parts.append(f"{name} is {body}")
    text = f"Here's my training plan: {sched}, everything else rest."
    if parts:
        text += " " + ". ".join(parts) + "."
    if any(s == "Run" for _, s in days):
        text += " Runs are whatever distance I feel like."
    return text


def plan_session_order(plan: dict) -> list[str]:
    seen = []
    for wd in WEEKDAYS:
        s = plan["days"][wd]
        if s != "Rest" and s not in seen:
            seen.append(s)
    return seen


def step_for(unit: str) -> float:
    return 2.5 if unit == "kg" else 5.0


def base_weight(exercise: str, unit: str, rng) -> float:
    _, _, lo, hi = EXERCISES[exercise]
    step = step_for(unit)
    w = rng.uniform(lo, hi) * (1 if unit == "kg" else 2.2)
    return float(round(w / step) * step)


def simulate(ctx: UserCtx) -> None:
    p = ctx.persona
    unit = p["units"]["lifts"]
    rng = ctx.rng("training")
    rr = ctx.rng("training-render")
    days = ctx.days
    step = step_for(unit)
    layout = rng.choice(PROGRAMS[p["program"]])
    weights: dict[str, float] = {}

    def prescription(exercise: str) -> dict:
        sets, reps, _, _ = EXERCISES[exercise]
        if exercise not in weights:
            weights[exercise] = base_weight(exercise, unit, rng)
        return {"exercise": exercise, "sets": sets, "reps": reps, "weight": weights[exercise]}

    plan = {"days": {wd: "Rest" for wd in WEEKDAYS}, "sessions": {}}
    for idx, s in sorted(layout.items()):
        plan["days"][WEEKDAYS[idx]] = s
        if s not in plan["sessions"]:
            n = len(TEMPLATES[s])
            keep = TEMPLATES[s][: max(3, n - rng.choice([0, 1]))] if n else []
            plan["sessions"][s] = [prescription(e) for e in keep]
    plan["sessions"] = {s: plan["sessions"][s] for s in plan_session_order(plan)}

    timeline: list[tuple[date, dict, Rec]] = []
    ctx.timelines["training"] = {"plans": timeline, "unit": unit}
    first = ctx.rec("plan", days[0], {"from": days[0].isoformat(), **copy.deepcopy(plan)})
    timeline.append((days[0], copy.deepcopy(plan), first))
    text0 = describe_plan(plan, unit, rr)
    ctx.say(days[0], MORNING + 0.5, [first], lambda late, t=text0: t, kind="statement", priority=10, can_be_late=False)

    # -- when the plan changes: 3 to 8 per 90 days, spaced so no two are pending at once
    per90 = rng.randrange(3, 9)
    n_changes = max(1, round(per90 * len(days) / 90)) if len(days) >= 60 else rng.choice([1, 2])
    lo, hi = 5, len(days) - 9
    change_days: list[int] = []
    if hi > lo:
        seg = (hi - lo) / n_changes
        for k in range(n_changes):
            a = int(lo + k * seg)
            b = int(lo + (k + 1) * seg) - 8
            if b <= a:
                b = a + 1
            change_days.append(rng.randrange(a, b))
    current = copy.deepcopy(plan)
    last_eff = days[0]
    for i in change_days:
        said = days[i]
        if said <= last_eff:
            continue
        new, words, eff = change_plan(current, said, unit, rng, rr, weights)
        if new is None or eff > days[-1]:
            continue
        r = ctx.rec("plan_change", said, {"from": eff.isoformat(), "change": words, "plan": copy.deepcopy(new)})
        timeline.append((eff, copy.deepcopy(new), r))
        current = new
        last_eff = eff
        slot = MORNING + 0.8 if eff == said else NIGHT  # "from today" is said before the day's session
        ctx.say(said, slot, [r], lambda late, t=words: t, kind="statement", priority=10, can_be_late=False)

    def plan_on(d: date) -> dict:
        found = timeline[0][1]
        for eff, pl, _ in timeline:
            if eff <= d:
                found = pl
        return found

    trips = ctx.timelines.get("trips", [])

    def trip_on(d: date) -> str | None:
        for a, b, dest in trips:
            if a <= d <= b:
                return dest
        return None

    pace = rng.uniform(4.6, 6.4)  # minutes per km
    for d in days:
        pl = plan_on(d)
        session = pl["days"][weekday(d)]
        if session == "Rest":
            continue
        roll = rng.random()
        away = trip_on(d)
        if away or roll < 0.09:
            reason = f"I'm away in {away}" if away else rng.choice(SKIP_REASONS)
            if away and rng.random() < 0.5:
                continue  # not even mentioned
            sk = ctx.rec("skip", d, {"session": session, "reason": reason}, tags={"key": ("skip",)})
            name = "the run" if session == "Run" else ("full body" if session == "Full body" else session.lower())
            tpl = rr.choice(
                [
                    f"Skipping {name}, {reason}.",
                    f"No {name} for me, {reason}.",
                    f"Missed {name}, {reason}.",
                ]
            )
            ctx.say(d, EVENING, [sk], lambda late, t=tpl, d=d: with_late(t, late, d, rr))
            continue
        if roll < 0.13:
            continue  # missed without a word
        if session == "Run":
            kind = rng.random()
            if d.weekday() >= 5 and kind < 0.5:
                dist = round(rng.uniform(10, 21), 1)
            elif kind < 0.75:
                dist = round(rng.uniform(4.5, 8.5), 1)
            else:
                dist = round(rng.uniform(6, 10), 1)
            seconds = int(round(dist * pace * rng.uniform(0.93, 1.08) * 60))
            r = ctx.rec(
                "run", d, {"km": dist, "minutes": round(seconds / 60, 2)}, tags={"key": ("run",), "seconds": seconds}
            )
            tpl = rr.choice(
                [
                    "Run done: {km} km in {t}.",
                    "{km}k in {t}, legs were heavy.",
                    "Ran {km} km, {t}.",
                    "Easy {km} km, {t} on the watch.",
                    "Got out for {km} km along the river, {t}.",
                ]
            )

            def render_run(late, r=r, tpl=tpl):
                secs = int(round(r.stated["minutes"] * 60))
                return with_late(tpl.format(km=km(r.stated["km"]), t=run_time(secs, rr)), late, r.date, rr)

            ctx.say(d, MORNING + 0.7 if rng.random() < 0.5 else EVENING, [r], render_run)
            continue
        exercises = []
        prescribed = pl["sessions"][session]
        todo = prescribed if rng.random() > 0.15 or len(prescribed) <= 3 else prescribed[:-1]
        for e in todo:
            w = e["weight"]
            if rng.random() < 0.05:
                w = w + step
            reps = [e["reps"]] * e["sets"]
            if rng.random() < 0.2:
                reps[-1] = max(1, reps[-1] - rng.choice([1, 2]))
            exercises.append({"name": e["exercise"], "sets": [{"reps": rp, "weight": w} for rp in reps]})
        r = ctx.rec("workout", d, {"session": session, "exercises": exercises}, tags={"key": ("workout",)})
        vocab = set(plan_exercises(pl))
        labels = [label(e["name"], vocab, rr) for e in exercises]
        opener = rr.choice([f"{session} done:", f"{session} day:", f"Gym, {session.lower()}:", f"{session} session:"])
        if session == "Full body":
            opener = rr.choice(["Full body done:", "Full body session:", "Gym, full body:"])

        def render_workout(late, r=r, labels=labels, opener=opener):
            parts = [sets_text(lb, ex["sets"], unit, rr) for lb, ex in zip(labels, r.stated["exercises"], strict=True)]
            return with_late(f"{opener} " + ", ".join(parts) + ".", late, r.date, rr)

        ctx.say(d, EVENING + 0.3, [r], render_workout)


def change_plan(plan: dict, said: date, unit: str, rng, rr, weights: dict) -> tuple[dict | None, str, date]:
    """One change in words. Returns (new plan, the words, effective date)."""
    new = copy.deepcopy(plan)
    step = step_for(unit)
    when = rng.choice(["today", "monday", "monday", "next week"])
    if when == "today":
        eff, phrase = said, rng.choice(["from today", "starting today"])
    elif when == "monday":
        eff, phrase = next_monday(said), "from Monday"
    else:
        eff, phrase = next_monday(said), "from next week"
    sessions_in_use = plan_session_order(new)
    training_days = [wd for wd in WEEKDAYS if new["days"][wd] != "Rest"]
    rest_days = [wd for wd in WEEKDAYS if new["days"][wd] == "Rest"]
    lifts = [(s, k) for s in sessions_in_use for k in range(len(new["sessions"][s]))]
    vocab = set(plan_exercises(new))
    kinds = ["weight", "weight", "weight", "move", "swap", "sets", "add", "drop"]
    rng.shuffle(kinds)
    for kind in kinds:
        if kind == "weight" and lifts:
            s, k = rng.choice(lifts)
            e = new["sessions"][s][k]
            name = e["exercise"]
            up = rng.random() < 0.85
            new_w = e["weight"] + (step if up else -step) * rng.choice([1, 1, 2])
            for sess in new["sessions"].values():  # a working weight is per exercise, wherever it appears
                for x in sess:
                    if x["exercise"] == name:
                        x["weight"] = new_w
            weights[name] = new_w
            lb = label(name, vocab, rr)
            w = lift_weight(new_w, unit, rr, 0.3)
            words = rr.choice(
                [
                    f"{cap(lb)} {'go' if lb.endswith('s') and not lb.endswith('ss') else 'goes'} {'up' if up else 'down'} to {w} {phrase}.",
                    f"Putting my {lb} {'up' if up else 'back down'} to {w} {phrase}.",
                    f"New working weight for {lb}: {w}, {phrase}.",
                ]
            )
            return new, words, eff
        if kind == "move" and training_days and rest_days:
            src = rng.choice(training_days)
            dst = rng.choice(rest_days)
            s = new["days"][src]
            new["days"][src], new["days"][dst] = "Rest", s
            name = "the run" if s == "Run" else ("full body" if s == "Full body" else s.lower())
            words = rr.choice(
                [
                    f"Moving {name} from {src} to {dst} {phrase}.",
                    f"{cap(name)} moves from {src}s to {dst}s {phrase}.",
                ]
            )
            new["sessions"] = {x: new["sessions"][x] for x in plan_session_order(new)}
            return new, words, eff
        if kind == "swap":
            options = [
                (s, k, alt)
                for s, k in lifts
                for alt in SWAPS.get(new["sessions"][s][k]["exercise"], [])
                if alt not in [x["exercise"] for x in new["sessions"][s]]
            ]
            if not options:
                continue
            s, k, alt = rng.choice(options)
            old = new["sessions"][s][k]["exercise"]
            sets, reps, _, _ = EXERCISES[alt]
            w = weights.get(alt) or base_weight(alt, unit, rng)
            weights[alt] = w
            new["sessions"][s][k] = {"exercise": alt, "sets": sets, "reps": reps, "weight": w}
            old_lb, new_lb = label(old, vocab | {alt}, rr), LABELS[alt][0]
            where = "full body" if s == "Full body" else s.lower()
            words = rr.choice(
                [
                    f"Swapping {old_lb} for {new_lb} on {where} day, {sets}x{reps} at {lift_weight(w, unit, rr, 0.5)}, {phrase}.",
                    f"{cap(phrase)}, {new_lb} instead of {old_lb} on {where} day: {sets}x{reps} @ {lift_weight(w, unit, rr, 0.5)}.",
                ]
            )
            return new, words, eff
        if kind == "sets" and lifts:
            s, k = rng.choice(lifts)
            e = new["sessions"][s][k]
            sets, reps = e["sets"], e["reps"]
            options = [
                (a, b)
                for a, b in ((3, 8), (3, 10), (4, 6), (4, 8), (4, 10), (5, 5), (3, 12), (5, 3))
                if (a, b) != (sets, reps)
            ]
            a, b = rng.choice(options)
            name = e["exercise"]
            for sess in new["sessions"].values():
                for x in sess:
                    if x["exercise"] == name:
                        x["sets"], x["reps"] = a, b
            lb = label(name, vocab, rr)
            words = rr.choice(
                [
                    f"{cap(lb)} {'go' if lb.endswith('s') and not lb.endswith('ss') else 'goes'} to {a}x{b} instead of {sets}x{reps} {phrase}, same weight.",
                    f"Changing {lb} to {a} sets of {b} {phrase}, weight stays.",
                ]
            )
            return new, words, eff
        if kind == "add" and len(training_days) < 5 and rest_days:
            dst = rng.choice(rest_days)
            s = rng.choice(sessions_in_use)
            new["days"][dst] = s
            name = "a run" if s == "Run" else ("a full body session" if s == "Full body" else f"a {s.lower()} day")
            words = f"Adding {name} on {dst}s {phrase}."
            new["sessions"] = {x: new["sessions"][x] for x in plan_session_order(new)}
            return new, words, eff
        if kind == "drop" and len(training_days) > 3:
            src = rng.choice(training_days)
            s = new["days"][src]
            if sum(1 for wd in WEEKDAYS if new["days"][wd] == s) < 2:
                continue  # never drop a session's only day; that would be a different program
            new["days"][src] = "Rest"
            name = "run" if s == "Run" else ("full body" if s == "Full body" else s.lower())
            words = rr.choice(
                [f"Dropping the {src} {name} {phrase}, too much on.", f"No more {name} on {src}s {phrase}."]
            )
            new["sessions"] = {x: new["sessions"][x] for x in plan_session_order(new)}
            return new, words, eff
    return None, "", eff


# ---------------------------------------------------------------- corrections


def correctable(rec: Rec) -> bool:
    if rec.type == "run":
        return True
    return rec.type == "workout" and any(e["sets"][0]["weight"] > 0 for e in rec.stated["exercises"])


def retractable(rec: Rec) -> bool:
    return False


def key(rec: Rec) -> tuple:
    return rec.tags["key"]


def misstate(rec: Rec, rng, unit: str) -> tuple[str, object]:
    if rec.type == "run":
        true = rec.truth["km"]
        s = f"{true:.1f}"
        whole, dec = s.split(".")
        if len(whole) == 2 and whole[0] != whole[1]:
            wrong = float(whole[1] + whole[0] + "." + dec)
        else:
            wrong = round(true + rng.choice([-2.0, 2.0, 1.0, -1.0]), 1)
        rec.stated["km"] = wrong
        return "km", true
    k = rng.randrange(len(rec.stated["exercises"]))
    true = rec.truth["exercises"][k]["sets"][0]["weight"]
    wrong = true + step_for(unit) * rng.choice([-2, -1, 1, 2, 4])
    for s in rec.stated["exercises"][k]["sets"]:
        s["weight"] = wrong
    rec.tags["fixed_item"] = k
    return f"exercises.{k}.sets.*.weight", true


def correction_text(rec: Rec, when: str, unit: str, rng) -> str:
    if rec.type == "run":
        new, old = rec.truth["km"], rec.stated["km"]
        return rng.choice(
            [
                f"Correction: the run {when} was {km(new)} km, not {km(old)}.",
                f"Typo, the run {when} was {km(new)}k. I wrote {km(old)}.",
            ]
        )
    k = rec.tags["fixed_item"]
    name = rec.truth["exercises"][k]["name"]
    new, old = rec.truth["exercises"][k]["sets"][0]["weight"], rec.stated["exercises"][k]["sets"][0]["weight"]
    lb = LABELS[name][0]
    be = "were" if lb.endswith("s") and not lb.endswith("ss") else "was"
    return rng.choice(
        [
            f"Correction: {lb} {when} {be} at {lift_weight(new, unit, rng, 0.5)}, not {lift_weight(old, unit, rng, 0.2)}, all sets.",
            f"Got the weight wrong, {lb} {when} {be} {lift_weight(new, unit, rng, 0.5)} for every set, not {lift_weight(old, unit, rng, 0.2)}.",
        ]
    )


def retraction_text(rec: Rec, when: str, rng) -> str:
    raise NotImplementedError
