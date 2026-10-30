"""
Small talk. Fillers carry no numbers; distractors carry numbers that must never
count toward an answer: episodes watched, a late train, a friend's purchase, a
colleague's run. Each distractor is kept as an event of type `distractor` with
the numbers its text contains, so the checker can prove no numeric gold is
within tolerance of one.
"""

from __future__ import annotations

import re

from ledgerbench.generate.core import NIGHT, UserCtx
from ledgerbench.generate.phrasing import SYMBOL

FILLERS = [
    "Long day of meetings, nothing else to report.", "Started a new book on the train, quite good so far.",
    "Weather finally turned, feels like spring.", "Call with mum, all fine at home.", "Finished the quarterly report, finally.",
    "Quiet evening, early night.", "Laundry, emails, the usual.", "The neighbour's dog barked half the night again.",
    "Rainy all day, worked from home.", "Dentist appointment moved again.", "Rearranged the living room, looks bigger now.",
    "Work review went fine, nothing dramatic.", "Spent the evening fixing the bike's gears.", "Lost my umbrella somewhere.",
    "Board game night at a friend's, we lost badly.", "Cleaned the whole flat, feels good.", "Watched a documentary about octopuses.",
    "My manager is off sick, so the week is calmer.", "Planning a weekend away, nothing booked yet.", "Tried meditating, lasted about a minute.",
]  # fmt: skip

# {n}: a plain number from the user's pool; {f}: a friend; {m}: a money amount someone else spent.
DISTRACTORS = [
    "Watched {n} episodes of the new series, completely hooked.", "The train was {n} minutes late this morning.",
    "My sister turned {n} this week.", "The planning meeting ran {n} minutes over.", "Read {n} pages this weekend.",
    "{n} people showed up to the team drinks.", "The flight board says {n} minutes delay for my colleague.",
    "Podcast episode {n} was great, all about sleep.", "{n} degrees out, finally.", "{n} unread emails after the long weekend.",
    "{f} spent {m} on concert tickets, madness.", "{f} says their weekly shop is {m} now, mine's nowhere near that.",
    "{f} ran {n} km at the weekend, show-off.", "{f} claims to bench {n}.", "{f}'s new phone was {m}.",
    "Our team hit {n} percent of target this quarter.", "The bus was {n} minutes late again.",
]  # fmt: skip
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def simulate(ctx: UserCtx) -> None:
    rng = ctx.rng("talk")
    days = ctx.days
    cur = ctx.persona["currency"]
    friends = ctx.persona["friends"]
    # kept away from the user's own body weight, which a state question asks for and cannot be moved
    p = ctx.persona
    if "body" in p["domains"]:
        lo, hi = (45, 110) if p["units"]["body_weight"] == "kg" else (100, 240)
    else:
        lo = hi = -1
    away = lambda n: not lo <= n <= hi  # noqa: E731
    pool = sorted(
        rng.sample(
            [
                n
                for n in (
                    2,
                    3,
                    4,
                    5,
                    6,
                    8,
                    12,
                    14,
                    17,
                    18,
                    21,
                    23,
                    26,
                    27,
                    31,
                    34,
                    38,
                    45,
                    52,
                    64,
                    75,
                    90,
                    120,
                    140,
                    230,
                    320,
                    410,
                )
                if away(n)
            ],
            12,
        )
    )
    money_pool = [rng.choice([n for n in (65, 85, 120, 140, 180, 240, 310) if away(n)]) for _ in range(4)]
    fillers = list(FILLERS)
    rng.shuffle(fillers)
    k = 0
    for d in days:
        if rng.random() < 0.15:
            text = fillers[k % len(fillers)]
            k += 1
            ctx.say(d, NIGHT + 0.5 * rng.random(), [], lambda late, t=text: t, kind="filler", priority=1)
        if rng.random() < 0.25:
            tpl = rng.choice(DISTRACTORS)
            text = tpl.format(n=rng.choice(pool), f=rng.choice(friends), m=SYMBOL[cur] + str(rng.choice(money_pool)))
            numbers = [float(x.replace(",", "")) for x in NUMBER.findall(text)]
            r = ctx.rec("distractor", d, {"numbers": numbers})
            ctx.say(
                d,
                NIGHT + 0.5 * rng.random(),
                [r],
                lambda late, t=text: t,
                kind="distractor",
                priority=2,
                can_be_late=False,
            )
