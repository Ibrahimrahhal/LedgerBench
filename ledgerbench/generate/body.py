"""
Body: weigh-ins, sleep, steps and resting heart rate at realistic frequency.

A sleep reading belongs to the morning it is reported for: "slept 7h15" said on
12 March is the night into 12 March, and its event date is 12 March. Weight
is in the user's body-weight unit, to one decimal.
"""

from __future__ import annotations

from ledgerbench.generate.core import BREAKFAST, MORNING, NIGHT, Rec, UserCtx
from ledgerbench.generate.phrasing import body_weight, cap, sleep, steps, with_late

TYPES = ("weight", "sleep_hours", "steps", "resting_hr")


def simulate(ctx: UserCtx) -> None:
    p = ctx.persona
    unit = p["units"]["body_weight"]
    rng = ctx.rng("body")
    rr = ctx.rng("body-render")
    days = ctx.days
    f = 1.0 if unit == "kg" else 2.2
    weight = round(rng.uniform(56, 96) * f, 1)
    drift = rng.uniform(-0.035, 0.012) * f
    sleep_mean = rng.uniform(6.4, 7.9)
    p_sleep = rng.uniform(0.72, 0.9)
    steps_mean = rng.uniform(6500, 11500)
    rhr = rng.randrange(50, 66)
    for d in days:
        recs: list[Rec] = []
        weight = weight + drift + rng.uniform(-0.25, 0.25) * f
        if rng.random() < p["weigh_rate"]:
            recs.append(ctx.rec("weight", d, {"value": round(weight, 1), "unit": unit}, tags={"key": ("weight",)}))
        if rng.random() < p_sleep:
            minutes = int(round(max(4.5, min(9.5, rng.gauss(sleep_mean, 0.75))) * 4)) * 15
            recs.append(ctx.rec("sleep_hours", d, {"value": minutes / 60}, tags={"key": ("sleep_hours",)}))
        if p["tracks_rhr"] and rng.random() < 0.3:
            recs.append(ctx.rec("resting_hr", d, {"value": rhr + rng.randrange(-3, 4)}, tags={"key": ("resting_hr",)}))
        if recs:
            if len(recs) > 1 and rng.random() < 0.9:
                ctx.say(d, MORNING, recs, morning_render(recs, unit, rr))
            else:
                for k, r in enumerate(recs):
                    ctx.say(
                        d,
                        MORNING + 0.1 * k if r.type != "resting_hr" else BREAKFAST,
                        [r],
                        morning_render([r], unit, rr),
                    )
        if p["tracks_steps"] and rng.random() < 0.45:
            n = int(max(1500, rng.gauss(steps_mean, 2600)))
            r = ctx.rec("steps", d, {"value": n}, tags={"key": ("steps",)})
            tpl = rr.choice(["{s}.", "Steps: {n}.", "Hit {s}.", "{s} on the watch.", "Walked a lot, {s}."])

            def render_steps(late, r=r, tpl=tpl):
                value = r.stated["value"]
                text = tpl.format(s=steps(value, rr), n=f"{value:,}" if rr.random() < 0.5 else str(value))
                return with_late(text, late, r.date, rr)

            ctx.say(d, NIGHT - 0.2, [r], render_steps)


def reading_text(r: Rec, unit: str, rng) -> str:
    v = r.stated["value"]
    if r.type == "weight":
        return rng.choice(
            [
                f"weighed {body_weight(v, unit, rng)}",
                f"{body_weight(v, unit, rng)} on the scale",
                f"weigh-in {body_weight(v, unit, rng)}",
            ]
        )
    if r.type == "sleep_hours":
        s = sleep(int(round(v * 60)), rng)
        return rng.choice([f"slept {s}", f"{s} of sleep", f"sleep was {s}"])
    if r.type == "resting_hr":
        return rng.choice([f"resting HR {v}", f"resting heart rate {v}", f"RHR {v}"])
    raise ValueError(r.type)


def morning_render(recs: list[Rec], unit: str, rng):
    def render(late: int) -> str:
        parts = [reading_text(r, unit, rng) for r in recs]
        body = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
        if not late and len(parts) > 1 and rng.random() < 0.4:
            body = "morning numbers: " + body
        return with_late(cap(body) + ".", late, recs[0].date, rng)

    return render


# ---------------------------------------------------------------- corrections


def correctable(rec: Rec) -> bool:
    return rec.type in ("weight", "sleep_hours", "steps")


def retractable(rec: Rec) -> bool:
    return rec.type == "weight"


def key(rec: Rec) -> tuple:
    return rec.tags["key"]


def misstate(rec: Rec, rng) -> tuple[str, object]:
    true = rec.truth["value"]
    if rec.type == "weight":
        s = f"{true:.1f}"
        whole, dec = s.split(".")
        if whole[-1] != dec and rng.random() < 0.6:
            wrong = float(whole[:-1] + dec + "." + whole[-1])  # 78.4 typed as 74.8
        else:
            wrong = round(true + rng.choice([-1.0, 1.0, -2.0, 2.0]), 1)
    elif rec.type == "sleep_hours":
        wrong = true + rng.choice([-1.0, 1.0, -0.5, 0.5])
        if not 3.5 <= wrong <= 10.5:
            wrong = true - 1.0
    else:
        s = str(true)
        if len(s) >= 4 and s[0] != s[1]:
            wrong = int(s[1] + s[0] + s[2:])
        else:
            wrong = true + rng.choice([-1000, 1000, 2000])
    rec.stated["value"] = wrong
    return "value", true


def correction_text(rec: Rec, when: str, unit: str, rng) -> str:
    new, old = rec.truth["value"], rec.stated["value"]
    if rec.type == "weight":
        return rng.choice(
            [
                f"Correction: the weigh-in {when} was {new:.1f}, not {old:.1f}.",
                f"Typo, I weighed {new:.1f} {when}, not {old:.1f}.",
            ]
        )
    if rec.type == "sleep_hours":
        return rng.choice(
            [
                f"Correction: the sleep I logged {when} was {sleep(int(round(new * 60)), rng)}, not {sleep(int(round(old * 60)), rng)}.",
                f"Watch re-synced, sleep {when} was actually {sleep(int(round(new * 60)), rng)}, not {sleep(int(round(old * 60)), rng)}.",
            ]
        )
    return rng.choice(
        [
            f"Correction: steps {when} were {new:,}, not {old:,}.",
            f"Mistyped the steps {when}, it was {new:,}. Not {old:,}.",
        ]
    )


def retraction_text(rec: Rec, when: str, rng) -> str:
    return rng.choice(
        [
            f"Ignore the weigh-in {when}, the scale was on the carpet.",
            f"Scratch the weight I logged {when}, I'd just eaten and had my shoes on.",
        ]
    )
