"""
Food: meals and snacks with the numbers the user states, water, and daily
calorie and protein targets that change once or twice.

Every item's kcal is the total for the line ("3 eggs at 70 each" is one item,
qty 3, kcal 210). Users who track protein state it per item; users who track
macros state protein, carbs and fat. "Same breakfast as yesterday" copies the
items of yesterday's breakfast, which is then never corrected.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from ledgerbench.generate.calendar import WEEKDAYS, next_monday
from ledgerbench.generate.core import AFTERNOON, BREAKFAST, EVENING, MIDDAY, MORNING, NIGHT, Rec, UserCtx
from ledgerbench.generate.phrasing import cap, kcal, thousands, with_late

MEALS = ("breakfast", "lunch", "dinner", "snack")
MEAL_ALIASES = {
    "breakfast": ["breakfast", "breakfasts"],
    "lunch": ["lunch", "lunches"],
    "dinner": ["dinner", "dinners"],
    "snack": ["snack", "snacks"],
}

# name, kcal, protein, carbs, fat per unit; countable unit qty choices (None: one portion)
FOODS = {
    "breakfast": [
        ("porridge", 350, 12, 58, 7, None),
        ("eggs", 70, 6, 1, 5, (2, 3)),
        ("toast", 90, 3, 15, 1, (1, 2)),
        ("banana", 105, 1, 27, 0, None),
        ("Greek yogurt", 150, 15, 6, 6, None),
        ("granola", 220, 5, 30, 8, None),
        ("smoothie", 280, 10, 50, 4, None),
        ("bagel", 280, 10, 55, 2, None),
        ("blueberries", 60, 1, 14, 0, None),
        ("peanut butter", 190, 7, 7, 16, None),
        ("avocado", 160, 2, 9, 15, None),
    ],
    "lunch": [
        ("chicken wrap", 520, 38, 50, 16, None),
        ("tuna salad", 420, 32, 18, 24, None),
        ("lentil soup", 310, 18, 45, 6, None),
        ("burrito bowl", 650, 35, 75, 20, None),
        ("falafel pitta", 560, 18, 70, 20, None),
        ("sushi", 480, 20, 80, 8, None),
        ("ham sandwich", 430, 24, 45, 16, None),
        ("poke bowl", 590, 32, 70, 18, None),
        ("leftover lasagne", 610, 30, 52, 28, None),
    ],
    "dinner": [
        ("salmon", 410, 40, 0, 26, None),
        ("rice", 260, 5, 57, 1, None),
        ("broccoli", 55, 4, 10, 0, None),
        ("chicken curry", 620, 42, 40, 30, None),
        ("spaghetti bolognese", 680, 34, 80, 22, None),
        ("steak", 540, 50, 0, 36, None),
        ("sweet potato", 180, 4, 41, 0, None),
        ("stir fry", 520, 30, 55, 18, None),
        ("tofu", 190, 20, 4, 11, None),
        ("pizza", 285, 12, 36, 10, (2, 3, 4)),
        ("veggie chilli", 480, 24, 60, 14, None),
        ("green salad", 90, 2, 8, 6, None),
        ("garlic bread", 190, 5, 24, 8, None),
    ],
    "snack": [
        ("apple", 95, 0, 25, 0, None),
        ("protein bar", 210, 20, 22, 7, None),
        ("almonds", 170, 6, 6, 15, None),
        ("dark chocolate", 170, 2, 13, 12, None),
        ("hummus and carrots", 180, 6, 18, 9, None),
        ("protein shake", 160, 30, 5, 2, None),
        ("flapjack", 300, 4, 40, 14, None),
        ("orange", 60, 1, 15, 0, None),
        ("biscuits", 80, 1, 11, 4, (2, 3)),
    ],
}
COUNT_WORDS = {"eggs": "eggs", "toast": "slices of toast", "pizza": "slices of pizza", "biscuits": "biscuits"}


def all_food_names() -> list[str]:
    return [f[0] for meal in MEALS for f in FOODS[meal]]


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _contains(outer: str, inner: str) -> bool:
    a, b = _words(outer), _words(inner)
    return any(a[i : i + len(b)] == b for i in range(len(a) - len(b) + 1))


_NAMES = all_food_names()
for _x in _NAMES:
    for _y in _NAMES:
        assert _x == _y or not _contains(_x, _y), f"food names must not contain each other: {_x!r} has {_y!r}"


def simulate(ctx: UserCtx) -> None:
    p = ctx.persona
    style = p["food_style"]  # kcal, protein or macros
    rng = ctx.rng("food")
    rr = ctx.rng("food-render")
    days = ctx.days
    track_water = rng.random() < 0.5
    p_log = rng.uniform(0.78, 0.92)
    scale = {name: rng.choice([0.95, 1.0, 1.0, 1.05, 1.1]) for name in all_food_names()}
    favourites = {
        meal: rng.sample(
            FOODS[meal], min(len(FOODS[meal]), {"breakfast": 5, "lunch": 6, "dinner": 9, "snack": 6}[meal])
        )
        for meal in MEALS
    }

    # ------------------------------------------------------------- targets
    timeline: dict = {"kcal_target": [], "protein_target": []}
    ctx.timelines["food"] = timeline
    kcal_t = rng.choice(range(1800, 2700, 50))
    prot_t = rng.choice(range(110, 190, 5))
    n_kcal_changes = 1 if len(days) < 60 else (rng.choice([1, 2]) if len(days) < 200 else rng.randrange(4, 7))
    n_prot_changes = 0 if len(days) < 60 else (rng.choice([0, 1]) if len(days) < 200 else rng.randrange(2, 4))
    if style == "kcal":
        n_prot_changes = -1

    def schedule(n: int) -> list[int]:
        if n <= 0:
            return []
        lo, hi = 7, len(days) - 8
        if hi - lo < n * 10:
            return [rng.randrange(lo, max(lo + 1, hi))][:n] if hi > lo else []
        seg = (hi - lo) // n
        return [lo + k * seg + rng.randrange(0, max(1, seg - 8)) for k in range(n)]

    def target_statement(kind: str, said: date, eff: date, amount: int, first: bool, phrase: str) -> None:
        r = ctx.rec(kind, said, {"amount": amount, "from": eff.isoformat()})
        timeline[kind].append((eff, amount, r))
        if kind == "kcal_target":
            num = f"{amount:,}" if rng.random() < 0.6 else str(amount)
            text = (
                rng.choice(
                    [
                        f"My calorie target is {num} kcal a day{phrase}.",
                        f"Aiming for {num} calories a day{phrase}.",
                    ]
                )
                if first
                else rng.choice(
                    [
                        f"Changing my calorie target to {num} a day{phrase}.",
                        f"New calorie target: {num} kcal a day{phrase}.",
                    ]
                )
            )
        else:
            text = (
                rng.choice(
                    [
                        f"Protein target is {amount}g a day{phrase}.",
                        f"I'm aiming for {amount}g of protein a day{phrase}.",
                    ]
                )
                if first
                else rng.choice(
                    [
                        f"Moving my protein target to {amount}g a day{phrase}.",
                        f"Protein goal is now {amount}g a day{phrase}.",
                    ]
                )
            )
        ctx.say(said, MORNING + 0.3, [r], lambda late, t=text: t, kind="statement", priority=9, can_be_late=False)

    target_statement("kcal_target", days[0], days[0], kcal_t, True, "")
    if style != "kcal":
        target_statement(
            "protein_target", days[min(1, len(days) - 1)], days[min(1, len(days) - 1)], prot_t, True, " from today"
        )
    for kind, n in (("kcal_target", n_kcal_changes), ("protein_target", n_prot_changes)):
        for i in schedule(n):
            said = days[i]
            how = rng.choice(["today", "tomorrow", "monday"])
            if how == "today":
                eff, phrase = said, " from today"
            elif how == "tomorrow":
                eff, phrase = said + timedelta(days=1), " from tomorrow"
            else:
                eff, phrase = next_monday(said), " from Monday"
            if kind == "kcal_target":
                current = timeline[kind][-1][1]
                amount = current + rng.choice([-250, -200, -150, -100, 100, 150, 200])
                amount = max(1500, min(3000, amount))
            else:
                current = timeline[kind][-1][1]
                amount = max(90, min(220, current + rng.choice([-15, -10, 10, 15, 20])))
            if amount == current:
                amount += 50 if kind == "kcal_target" else 10
            target_statement(kind, said, eff, amount, False, phrase)
    for kind in timeline:
        timeline[kind].sort(key=lambda t: t[0])

    # ------------------------------------------------------------- meals
    yesterday_breakfast: Rec | None = None
    for d in days:
        if rng.random() > p_log:
            yesterday_breakfast = None
            continue
        meals_today: list[Rec] = []
        plan = []
        if rng.random() < 0.88:
            plan.append("breakfast")
        if rng.random() < 0.92:
            plan.append("lunch")
        if rng.random() < 0.94:
            plan.append("dinner")
        n_snacks = rng.choice([0, 0, 0, 1, 1, 2])
        plan += ["snack"] * n_snacks
        if len(plan) < 2:
            plan = ["lunch", "dinner"]
        plan = plan[:5]
        copied = None
        for meal in plan:
            if meal == "breakfast" and yesterday_breakfast is not None and rng.random() < 0.15:
                src = yesterday_breakfast
                items = [dict(it) for it in src.truth["items"]]
                r = ctx.rec(
                    "meal",
                    d,
                    {"meal": "breakfast", "items": items, "same_as": None},
                    links={"same_as": src},
                    tags={"copy": True, "key": ("meal", "breakfast")},
                )
                src.tags["copy_source"] = True
                copied = r
                meals_today.append(r)
                continue
            pool = favourites[meal]
            n_items = {
                "breakfast": rng.choice([1, 2, 2, 3]),
                "lunch": rng.choice([1, 1, 2]),
                "dinner": rng.choice([1, 2, 3, 3]),
                "snack": 1,
            }[meal]
            chosen = rng.sample(pool, min(n_items, len(pool)))
            items = []
            for name, kc, pr, cb, ft, counts in chosen:
                qty = rng.choice(counts) if counts else 1
                f = scale[name]
                item = {"name": name, "qty": qty, "kcal": int(round(kc * f)) * qty}
                if style in ("protein", "macros"):
                    item["protein_g"] = int(round(pr * f)) * qty
                if style == "macros":
                    item["carbs_g"] = int(round(cb * f)) * qty
                    item["fat_g"] = int(round(ft * f)) * qty
                items.append(item)
            snack_count = plan.count("snack")
            key = ("meal", meal) if meal != "snack" or snack_count == 1 else ("meal", "snack", "several")
            r = ctx.rec("meal", d, {"meal": meal, "items": items}, tags={"key": key})
            meals_today.append(r)
        yesterday_breakfast = next(
            (r for r in meals_today if r.stated["meal"] == "breakfast" and not r.tags.get("copy")), None
        )

        # how the day is told: meal by meal, or two at once, or all in one go at night
        mode = rng.random()
        if mode < 0.35 and len(meals_today) >= 3 and copied is None:
            say_meals(ctx, d, NIGHT, meals_today, style, rr, all_day=True)
        else:
            slots = {"breakfast": BREAKFAST, "lunch": MIDDAY, "dinner": EVENING, "snack": AFTERNOON}
            k = 0
            while k < len(meals_today):
                r = meals_today[k]
                nxt = meals_today[k + 1] if k + 1 < len(meals_today) else None
                if (
                    nxt is not None
                    and rng.random() < 0.6
                    and not r.tags.get("copy")
                    and not nxt.tags.get("copy")
                    and r.stated["meal"] != nxt.stated["meal"]
                ):
                    say_meals(ctx, d, slots[nxt.stated["meal"]], [r, nxt], style, rr)
                    k += 2
                else:
                    say_meals(
                        ctx,
                        d,
                        slots[r.stated["meal"]] + (0.1 * k if r.stated["meal"] == "snack" else 0),
                        [r],
                        style,
                        rr,
                    )
                    k += 1

        if track_water and rng.random() < 0.45:
            ml = rng.choice([1500, 1750, 2000, 2000, 2250, 2500, 3000])
            w = ctx.rec("water", d, {"ml": ml}, tags={"key": ("water",)})
            if ml % 1000 == 0:
                amount = f"{ml // 1000} litres"
            elif ml % 500 == 0:
                amount = f"{ml / 1000:g} litres"
            else:
                amount = f"{thousands(ml, rr)} ml"
            text = rr.choice([f"Drank {amount} of water.", f"Water: {amount}.", f"{amount} of water."])
            ctx.say(d, NIGHT + 0.2, [w], lambda late, t=text, d=d: with_late(t, late, d, rr))


def item_text(item: dict, style: str, rng, first: bool) -> str:
    name, qty, kc = item["name"], item["qty"], item["kcal"]
    unit = rng.random() < 0.6 or first
    if qty > 1:
        noun = COUNT_WORDS.get(name, name)
        each = kc // qty
        if style == "kcal":
            return rng.choice([f"{qty} {noun} at {each} each", f"{qty} {noun}, {kcal(kc, rng)}"])
        pe = item["protein_g"] // qty
        if style == "protein":
            return rng.choice(
                [
                    f"{qty} {noun} at {each} kcal and {pe}g protein each",
                    f"{qty} {noun}, {kc} kcal, {item['protein_g']}g protein",
                ]
            )
        return f"{qty} {noun}, {kc} kcal (P{item['protein_g']} C{item['carbs_g']} F{item['fat_g']})"
    kc_text = kcal(kc, rng) if unit else str(kc)
    if style == "kcal":
        return f"{name} {kc_text}"
    if style == "protein":
        return rng.choice(
            [f"{name} {kc_text}, {item['protein_g']}g protein", f"{name} {kc_text} ({item['protein_g']}g protein)"]
        )
    return rng.choice(
        [
            f"{name} {kc_text} (P{item['protein_g']} C{item['carbs_g']} F{item['fat_g']})",
            f"{name} {kc_text}, {item['protein_g']}g protein, {item['carbs_g']}g carbs, {item['fat_g']}g fat",
        ]
    )


def meal_text(r: Rec, style: str, rng) -> str:
    meal = r.stated["meal"]
    if r.tags.get("copy"):
        return rng.choice(
            ["same breakfast as yesterday", "breakfast was the same as yesterday", "same as yesterday for breakfast"]
        )
    items = r.stated["items"]
    parts = [item_text(it, style, rng, k == 0) for k, it in enumerate(items)]
    body = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
    label = "a snack" if meal == "snack" else meal
    return rng.choice([f"{label}: {body}", f"{label} was {body}", f"for {label}, {body}"])


def say_meals(ctx: UserCtx, d: date, slot: float, recs: list[Rec], style: str, rr, all_day: bool = False) -> None:
    def render(late: int, recs=recs) -> str:
        texts = [meal_text(r, style, rr) for r in recs]
        if all_day:
            body = (
                "food today. " + ". ".join(cap(t) for t in texts)
                if not late
                else "food. " + ". ".join(cap(t) for t in texts)
            )
            body = "Logging all my " + body
        else:
            body = "; ".join(texts)
        return with_late(body + ".", late, recs[0].date, rr)

    ctx.say(d, slot, recs, render, can_be_late=not any(r.tags.get("copy") or r.tags.get("copy_source") for r in recs))


# ---------------------------------------------------------------- corrections


def correctable(rec: Rec) -> bool:
    return (
        rec.type == "meal"
        and not rec.tags.get("copy")
        and not rec.tags.get("copy_source")
        and rec.tags.get("key", ("",))[-1] != "several"
    )


def retractable(rec: Rec) -> bool:
    return correctable(rec) and rec.stated["meal"] == "snack"


def key(rec: Rec) -> tuple:
    return rec.tags["key"]


def misstate(rec: Rec, rng) -> tuple[str, object]:
    items = rec.stated["items"]
    k = max(range(len(items)), key=lambda j: (items[j]["kcal"], -j))
    true = rec.truth["items"][k]["kcal"]
    wrong = true + rng.choice([-100, 100, -150, 150, 200]) if true > 220 else true + rng.choice([100, 150])
    s = str(true)
    if len(s) == 3 and s[0] != s[1] and rng.random() < 0.5:
        wrong = int(s[1] + s[0] + s[2])
    items[k]["kcal"] = wrong
    rec.tags["fixed_item"] = k
    return f"items.{k}.kcal", true


def correction_text(rec: Rec, when: str, rng) -> str:
    k = rec.tags["fixed_item"]
    name = rec.truth["items"][k]["name"]
    meal = rec.stated["meal"]
    new, old = rec.truth["items"][k]["kcal"], rec.stated["items"][k]["kcal"]
    at = "as a snack" if meal == "snack" else f"at {meal}"
    return rng.choice(
        [
            f"Correction: the {name} {at} {when} was {new} kcal, not {old}.",
            f"Wrote the wrong number, the {name} {at} {when} was {new} calories. Not {old}.",
            f"Checked the packet: the {name} {at} {when} was actually {new} kcal, I said {old}.",
        ]
    )


def retraction_text(rec: Rec, when: str, rng) -> str:
    name = rec.stated["items"][0]["name"]
    return rng.choice(
        [
            f"Scratch the {name} I logged as a snack {when}, I didn't end up eating it.",
            f"Remove the snack from {when.replace('on ', '')} ({name}), I gave it away in the end.",
        ]
    )


__all__ = ["simulate", "MEALS", "WEEKDAYS"]
