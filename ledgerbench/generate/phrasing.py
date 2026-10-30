"""
How numbers and records are written in messages.

Everything a message says that counts is exact: `€14` is 14.00, `fourteen fifty`
is 14.50, `7h15` is 7.25 hours, `4x6 @ 80` is four sets of six at 80. Nothing
that counts is ever approximate ("about 30" never appears in a record).
"""

from __future__ import annotations

import random
from datetime import date

from ledgerbench.generate.calendar import weekday

SYMBOL = {"EUR": "€", "USD": "$", "GBP": "£"}
CURRENCY_WORDS = {"EUR": ("euros",), "USD": ("dollars", "bucks"), "GBP": ("pounds", "quid")}

ONES = (
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen"
).split()
TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def words(n: int) -> str:
    if n < 20:
        return ONES[n]
    if n < 100:
        tens, ones = divmod(n, 10)
        return TENS[tens] + ("" if ones == 0 else "-" + ONES[ones])
    raise ValueError(n)


def cap(text: str) -> str:
    if not text or (len(text) > 1 and text[0].islower() and text[1].isupper()):  # iCloud stays iCloud
        return text
    return text[:1].upper() + text[1:]


def low(text: str) -> str:
    """Lower-cases the first letter, unless the first word is a name or an acronym."""
    if not text:
        return text
    first = text.split(" ", 1)[0].rstrip(",:.")
    if len(first) > 1 and (first[1:].lower() != first[1:] or first in KEEP_CASE):
        return text
    return text[:1].lower() + text[1:]


KEEP_CASE = set()  # filled with names by the personas module


def cents(amount: float) -> int:
    return int(round(amount * 100))


def money(amount: float, currency: str, rng: random.Random, words_ok: bool = True) -> str:
    """A money amount as a person types it."""
    c = cents(amount)
    whole, frac = divmod(c, 100)
    if whole >= 1000:
        plain = f"{whole:,}" + (f".{frac:02d}" if frac else "")
    elif frac or rng.random() < 0.12:
        plain = f"{whole}.{frac:02d}"
    else:
        plain = str(whole)
    roll = rng.random()
    if words_ok and roll < 0.04 and 2 <= whole < 100:
        if frac == 50:
            return f"{words(whole)} fifty"
        if frac == 0:
            return f"{words(whole)} {CURRENCY_WORDS[currency][0]}"
    if roll < 0.45:
        return plain
    if roll < 0.80:
        return SYMBOL[currency] + plain
    word = CURRENCY_WORDS[currency][0]
    if frac == 0 and len(CURRENCY_WORDS[currency]) > 1 and rng.random() < 0.4:
        word = CURRENCY_WORDS[currency][1]
    return f"{plain} {word}"


def money_plain(amount: float, currency: str) -> str:
    """For statements that should read cleanly: €1,250 or €12.99."""
    c = cents(amount)
    whole, frac = divmod(c, 100)
    body = f"{whole:,}" + (f".{frac:02d}" if frac else "")
    return SYMBOL[currency] + body


def thousands(n: int, rng: random.Random) -> str:
    return f"{n:,}" if n >= 1000 and rng.random() < 0.6 else str(n)


def kcal(n: int, rng: random.Random) -> str:
    unit = rng.choice(["kcal", "kcal", "cals", "calories", "kcal"])
    return f"{n} {unit}"


def grams(n: float) -> str:
    return f"{n:g}g"


def body_weight(value: float, unit: str, rng: random.Random) -> str:
    text = f"{value:.1f}"
    if unit == "kg":
        return text + rng.choice([" kg", "kg", "", " kilos"])
    return text + rng.choice([" lb", " lbs", "", "lbs"])


def sleep(minutes: int, rng: random.Random) -> str:
    h, m = divmod(minutes, 60)
    if m == 0:
        return rng.choice([f"{h} hours", f"{h}h", f"{words(h)} hours", f"{h} hours flat"])
    if m == 30:
        return rng.choice([f"{h}.5 hours", f"{h}h30", f"{words(h)} and a half hours", f"{h} and a half hours"])
    if m == 15:
        return rng.choice([f"{h}h15", f"{h}.25 hours", f"{h} hours 15"])
    if m == 45:
        return rng.choice([f"{h}h45", f"{h}.75 hours", f"{h} hours 45"])
    raise ValueError(minutes)


def steps(n: int, rng: random.Random) -> str:
    return f"{thousands(n, rng)} steps"


def run_time(seconds: int, rng: random.Random) -> str:
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    if s == 0 and rng.random() < 0.5:
        return f"{m} min"
    return f"{m}:{s:02d}"


def km(value: float) -> str:
    return f"{value:g}"


def lift_weight(value: float, unit: str, rng: random.Random, suffix_p: float = 0.35) -> str:
    text = f"{value:g}"
    if rng.random() < suffix_p:
        text += rng.choice([unit, " " + unit]) if unit == "kg" else rng.choice([" lb", "lbs", " lbs"])
    return text


def sets_text(label: str, sets: list[dict], unit: str, rng: random.Random) -> str:
    """One exercise as logged: 'bench 4x6 @ 80', '80kg for 4 sets of 6', 'squats 100 for 5, 5, 5, 4'."""
    n = len(sets)
    reps = [s["reps"] for s in sets]
    w = sets[0]["weight"]
    assert all(s["weight"] == w for s in sets)
    wt = lift_weight(w, unit, rng)
    if len(set(reps)) == 1:
        r = reps[0]
        form = rng.random()
        if form < 0.35:
            return f"{label} {n}x{r} @ {wt}"
        if form < 0.6:
            return f"{label} {n}x{r} at {wt}"
        if form < 0.8:
            return f"{label} {lift_weight(w, unit, rng, 1.0)} for {n} sets of {r}"
        return f"{label}: {n} sets of {r} at {wt}"
    return f"{label} {wt} for {', '.join(str(r) for r in reps)}"


def late_prefix(late: int, when: date, rng: random.Random) -> str:
    if late == 1:
        return rng.choice(
            [
                "Forgot to say, yesterday:",
                "Missed this yesterday:",
                "Logging this late, from yesterday:",
                "Oh and yesterday,",
                "From yesterday, forgot to log it:",
                "Didn't get to this yesterday:",
            ]
        )
    return rng.choice(
        [
            f"From {weekday(when)}, forgot to log it:",
            f"Catching up, {weekday(when)}:",
            f"Never logged this from {weekday(when)}:",
        ]
    )


def with_late(text: str, late: int, when: date, rng: random.Random) -> str:
    if not late:
        return cap(text)
    return f"{late_prefix(late, when, rng)} {low(text)}"
