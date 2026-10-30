"""
Spending: a person's money week by week.

Rent and bills on fixed days, subscriptions that renew (one of them gets
dearer), groceries once or twice a week, coffee on workdays, lunches and
dinners out, a trip with a burst of travel spending, a dinner split with a
friend and paid back later, a refund, and budgets that are set and later
changed. Every expense is said in a message; the declarations (rent, a
subscription, a budget) are statements that the state questions read.
"""

from __future__ import annotations

from datetime import date, timedelta

from ledgerbench.generate.calendar import ordinal, weekday
from ledgerbench.generate.core import AFTERNOON, BREAKFAST, COMMUTE, EVENING, MIDDAY, MORNING, NIGHT, Rec, UserCtx
from ledgerbench.generate.phrasing import cap, money, money_plain, with_late

CATEGORIES = (
    "groceries", "eating out", "coffee", "transport", "rent", "utilities", "subscriptions",
    "health", "clothing", "entertainment", "travel", "gifts", "household", "other",
)  # fmt: skip

# Honest synonyms a reply may use for a category; none of them contains another category's name.
CATEGORY_ALIASES = {
    "groceries": ["groceries", "grocery", "supermarket"],
    "eating out": ["eating out", "dining out", "restaurants", "takeaway"],
    "coffee": ["coffee", "coffees", "cafés", "cafes"],
    "transport": ["transport", "transportation", "taxis", "commuting"],
    "rent": ["rent", "housing"],
    "utilities": ["utilities", "bills", "utility bills"],
    "subscriptions": ["subscriptions", "subscription"],
    "health": ["health", "pharmacy", "medical"],
    "clothing": ["clothing", "clothes"],
    "entertainment": ["entertainment", "outings"],
    "travel": ["travel", "trips", "trip"],
    "gifts": ["gifts", "presents", "gift"],
    "household": ["household", "home goods"],
    "other": ["other", "miscellaneous"],
}

# How a question names a category, with a gloss where the boundary is not obvious.
CATEGORY_PHRASE = {
    "groceries": "groceries",
    "eating out": "eating out (restaurants, takeaway and lunches out, not coffee)",
    "coffee": "coffee (coffee and pastries at cafés)",
    "transport": "transport (taxis, transit and fuel, not trip travel)",
    "rent": "rent",
    "utilities": "utilities (energy, water and internet bills)",
    "subscriptions": "subscriptions",
    "health": "health (pharmacy, physio, dentist)",
    "clothing": "clothes",
    "entertainment": "entertainment (cinema, concerts, games and outings)",
    "travel": "travel (flights, hotels and train tickets for trips)",
    "gifts": "gifts",
    "household": "household things",
    "other": "other things",
}
CATEGORY_SHORT = {"clothing": "clothes", "household": "household things", "other": "other things"}

FX = {"EUR": 1.0, "USD": 1.15, "GBP": 0.88}
SUBSCRIPTIONS = {
    "EUR": [
        ("Netflix", 13.99),
        ("Spotify", 10.99),
        ("the gym", 34.90),
        ("iCloud", 2.99),
        ("the newspaper", 14.99),
        ("Disney+", 9.99),
    ],
    "USD": [
        ("Netflix", 15.49),
        ("Spotify", 11.99),
        ("the gym", 49.00),
        ("iCloud", 2.99),
        ("the newspaper", 9.99),
        ("Disney+", 13.99),
    ],
    "GBP": [
        ("Netflix", 10.99),
        ("Spotify", 11.99),
        ("the gym", 29.99),
        ("iCloud", 2.99),
        ("the newspaper", 12.99),
        ("Disney+", 8.99),
    ],
}
INTERNET = {"EUR": 39.90, "USD": 65.00, "GBP": 32.00}
DESTINATIONS = {
    "EUR": ["Porto", "Prague", "Seville", "Copenhagen", "Bologna"],
    "USD": ["New Orleans", "Portland", "Miami", "Montreal", "San Diego"],
    "GBP": ["Edinburgh", "Lisbon", "Amsterdam", "Cornwall", "Copenhagen"],
}
RESTAURANTS = [
    "the Thai place",
    "the new ramen bar",
    "the tapas bar",
    "the Italian round the corner",
    "the burger joint",
    "the Lebanese place",
]

COFFEE = [
    "Flat white, {amt}.", "Coffee on the way in, {amt}.", "Cappuccino and a pastry, {amt}.",
    "Oat latte, {amt}. Overpriced but needed.", "Coffee from the kiosk by the office: {amt}.",
    "Espresso at the corner place, {amt}.", "Coffee and a croissant, {amt}.",
]  # fmt: skip
LUNCH = [
    "Lunch out, poke bowl, {amt}.", "Sandwich and a juice for lunch, {amt}.", "Team lunch at the noodle bar, my share {amt}.",
    "Falafel wrap from the food truck, {amt}.", "Bought lunch at the canteen, {amt}.", "Lunch at the salad place, {amt}.",
]  # fmt: skip
DINNER = [
    "Dinner at {place}, {amt}.", "Pizza with friends, my part came to {amt}.", "Takeaway sushi, {amt}.",
    "Drinks and tapas after work, {amt}.", "Burgers with {friend}, {amt}.", "Ordered Indian takeaway, {amt}.",
]  # fmt: skip
GROCERIES = [
    "Big shop at {store}, {amt}.", "Groceries at {store}: {amt}.", "{store} run, {amt}.",
    "Weekly shop done, {amt} at {store}.", "Topped up on groceries at {store}, {amt}.",
]  # fmt: skip
TAXI = ["Taxi home, {amt}.", "Uber back from {friend}'s, {amt}.", "Cab to the station, {amt}."]
TRANSIT = ["Topped up the transit card, {amt}.", "Weekly travel pass, {amt}.", "Metro card top-up, {amt}."]
FUEL = ["Filled up the car, {amt}.", "Gas for the car, {amt}."]
FUEL_GB = ["Filled up the car, {amt}.", "Petrol, {amt}."]
ENTERTAINMENT = [
    "Cinema tickets, {amt}.", "Concert tickets, {amt}.", "Bowling with the team, {amt}.",
    "Bought a new board game, {amt}.", "Museum entry, {amt}.", "Comedy night tickets, {amt}.",
]  # fmt: skip
CLOTHING = [
    "New running shoes, {amt}.",
    "Jeans, {amt}.",
    "A rain jacket, {amt}. Needed it.",
    "Two shirts for work, {amt}.",
    "Socks and a hoodie, {amt}.",
]
HEALTH = [
    "Pharmacy: painkillers and plasters, {amt}.",
    "Picked up my prescription, {amt}.",
    "Physio session, {amt}.",
    "Dentist check-up, {amt}.",
]
HOUSEHOLD = [
    "Cleaning stuff and bin bags, {amt}.",
    "New frying pan, {amt}.",
    "Light bulbs and batteries, {amt}.",
    "A lamp for the bedroom, {amt}.",
    "Bedsheets, {amt}.",
]
GIFTS = ["Birthday present for {friend}, {amt}.", "Flowers for my mum, {amt}.", "Wedding gift for my cousin, {amt}."]
OTHER = ["Haircut, {amt}.", "Dry cleaning, {amt}.", "Donation to the food bank, {amt}."]
ENERGY = ["Electricity bill came in, {amt}.", "Paid the gas and electric, {amt}.", "Water bill, {amt}."]

OCCASIONAL = (
    # category, chance per day, templates, low, high, slot, descriptor
    ("entertainment", 0.05, ENTERTAINMENT, 9, 60, EVENING, "tickets"),
    ("clothing", 0.04, CLOTHING, 18, 120, AFTERNOON, "clothes"),
    ("health", 0.03, HEALTH, 6, 70, AFTERNOON, "pharmacy"),
    ("household", 0.05, HOUSEHOLD, 5, 60, AFTERNOON, "household stuff"),
    ("other", 0.025, OTHER, 10, 40, AFTERNOON, "haircut"),
)
RETURNABLE = {"clothing", "household", "entertainment"}


def stable_number(text: str) -> int:
    """A stable small number from a string (str hashes are salted per process)."""
    return sum(ord(c) * (i + 1) for i, c in enumerate(text))


def simulate(ctx: UserCtx) -> None:
    p = ctx.persona
    cur = p["currency"]
    rng = ctx.rng("spending")
    rr = ctx.rng("spending-render")
    fx = FX[cur]
    days = ctx.days
    friends = p["friends"]
    long_window = len(days) >= 60

    def amt(lo: float, hi: float, step: float = 0.01) -> float:
        n = round((rng.uniform(lo, hi) * fx) / step)
        return round(n * step, 2)

    def expense(
        d: date,
        slot: float,
        category: str,
        amount: float,
        note: str,
        templates: list[str],
        merchant: str | None = None,
        fmt: dict | None = None,
        tags: dict | None = None,
        can_be_late: bool = True,
    ) -> Rec:
        fields = {"amount": round(amount, 2), "category": category}
        if merchant:
            fields["merchant"] = merchant
        fields["note"] = note
        tag = {"descriptor": note, "key": ("expense", category)}
        tag.update(tags or {})
        rec = ctx.rec("expense", d, fields, tags=tag)
        template = rng.choice(templates)
        extra = dict(fmt or {})

        def render(late: int, rec=rec, template=template, extra=extra) -> str:
            text = template.format(amt=money(rec.stated["amount"], cur, rr), **extra)
            return with_late(text, late, rec.date, rr)

        ctx.say(d, slot, [rec], render, can_be_late=can_be_late)
        return rec

    # ---------------------------------------------------------------- recurring
    rent_amount = float(rng.randrange(int(850 * fx) // 10, int(1600 * fx) // 10) * 10)
    rent_day = rng.choice([1, 1, 1, 2, 3, 5, 28])
    subs = rng.sample(SUBSCRIPTIONS[cur], 3 if long_window else 2)
    sub_days = rng.sample([4, 7, 9, 12, 14, 17, 19, 21, 23, 26], len(subs))
    internet_day = rng.choice([6, 10, 15, 20])
    recurring = [("rent", "rent", rent_amount, rent_day)]
    recurring += [(name, "subscriptions", price, day) for (name, price), day in zip(subs, sub_days, strict=True)]
    recurring.append(("the internet", "utilities", INTERNET[cur], internet_day))
    rec_recs: dict[str, Rec] = {}
    timeline: dict = {"recurring": {}, "budgets": {}, "splits": [], "recurring_meta": {}}
    ctx.timelines["spending"] = timeline
    declare_days = [days[0], days[0], days[1], days[1], days[2], days[2]]
    for k, (name, category, price, day) in enumerate(recurring):
        when = declare_days[min(k, len(declare_days) - 1)]
        r = ctx.rec("recurring", when, {"name": name, "category": category, "amount": price, "day": day})
        rec_recs[name] = r
        timeline["recurring"][name] = [(when, price, r)]
        timeline["recurring_meta"][name] = {"category": category, "day": day}
        if name == "rent":
            texts = [
                f"For the record, rent is {money_plain(price, cur)} a month and goes out on the {ordinal(day)}.",
                f"So you know: my rent is {money_plain(price, cur)}, paid on the {ordinal(day)} of every month.",
            ]
        elif name == "the internet":
            texts = [f"Internet is {money_plain(price, cur)} a month, billed on the {ordinal(day)}."]
        else:
            texts = [
                f"I pay {money_plain(price, cur)} a month for {name}, it renews on the {ordinal(day)}.",
                f"{cap(name)} is {money_plain(price, cur)} a month, taken on the {ordinal(day)}.",
            ]
        text = rng.choice(texts)
        ctx.say(when, MORNING + 0.1 * k, [r], lambda late, t=text: t, kind="statement", priority=9, can_be_late=False)

    # one subscription gets dearer (two in a long window)
    changes: dict[str, list[tuple[date, float]]] = {}
    base_price = {name: price for name, _, price, _ in recurring}
    sub_names = [s[0] for s in subs]
    n_rises = 1 if len(days) < 200 else 2
    for name in sorted(rng.sample(sub_names, n_rises)):
        day = next(dd for n, _, _, dd in recurring if n == name)
        lo, hi = (len(days) // 4, len(days) * 2 // 3) if len(days) > 30 else (2, 8)
        said = days[rng.randrange(lo, hi)]
        eff = said + timedelta(days=1)  # from the next renewal after it is said
        while eff.day != day:
            eff += timedelta(days=1)
        new_price = round(base_price[name] + rng.choice([1.0, 1.5, 2.0, 3.0]), 2)
        r = ctx.rec(
            "price_change", said, {"amount": new_price, "from": eff.isoformat()}, links={"refers_to": rec_recs[name]}
        )
        timeline["recurring"][name].append((eff, new_price, r))
        changes.setdefault(name, []).append((eff, new_price))
        text = rng.choice(
            [
                f"{cap(name)} is going up to {money_plain(new_price, cur)} a month from the next bill. Annoying.",
                f"Heads up, {name} raised the price: {money_plain(new_price, cur)} a month from the next renewal.",
            ]
        )
        ctx.say(said, EVENING, [r], lambda late, t=text: t, kind="statement", priority=9, can_be_late=False)

    def recurring_price(name: str, d: date) -> float:
        price = base_price[name]
        for eff, new in changes.get(name, []):
            if d >= eff:
                price = new
        return price

    # ---------------------------------------------------------------- budgets
    budget_cats = rng.sample(["eating out", "groceries", "coffee", "transport"], 2)
    budget_levels = {"eating out": (300, 520), "groceries": (300, 520), "coffee": (40, 90), "transport": (60, 140)}
    first = days[0]
    for k, cat in enumerate(budget_cats):
        lo, hi = budget_levels[cat]
        amount = float(round(rng.uniform(lo, hi) * fx / 10) * 10)
        if first.day <= 3:
            said, eff, phrase = days[min(k, len(days) - 1)], date(first.year, first.month, 1), "starting this month"
        else:
            nm = date(first.year + (first.month == 12), first.month % 12 + 1, 1)
            said, eff, phrase = days[min(2 + k, len(days) - 1)], nm, "starting next month"
        stated = [(said, eff, amount, phrase)]
        n_changes = 0 if len(days) < 60 else (1 if len(days) < 200 else 3)
        cursor = eff
        for _ in range(n_changes):
            month_starts = [d for d in days if d.day == 1 and d > cursor + timedelta(days=27)]
            if len(month_starts) < 2:
                break
            eff2 = rng.choice(month_starts[:2])
            said2 = eff2 - timedelta(days=rng.randrange(3, 12))
            if said2 <= stated[-1][0] or said2 < days[0]:
                break
            step = rng.choice([-60, -40, -20, 20, 40, 60, 80])
            amount = float(max(40, round((amount + step * fx) / 10) * 10))
            stated.append((said2, eff2, amount, "from next month"))
            cursor = eff2
        timeline["budgets"][cat] = []
        for j, (said, eff, amount, phrase) in enumerate(stated):
            r = ctx.rec("budget", said, {"category": cat, "amount": amount, "from": eff.isoformat()})
            timeline["budgets"][cat].append((eff, amount, r))
            name = CATEGORY_SHORT.get(cat, cat)
            if j == 0:
                text = rng.choice(
                    [
                        f"Setting myself a budget of {money_plain(amount, cur)} a month for {name}, {phrase}.",
                        f"New rule: {money_plain(amount, cur)} a month max on {name}, {phrase}.",
                    ]
                )
            else:
                text = rng.choice(
                    [
                        f"Changing my {name} budget to {money_plain(amount, cur)} a month {phrase}.",
                        f"Going to make the {name} budget {money_plain(amount, cur)} a month {phrase}.",
                    ]
                )
            ctx.say(said, NIGHT, [r], lambda late, t=text: t, kind="statement", priority=9, can_be_late=False)

    # ---------------------------------------------------------------- trips
    trips: list[tuple[date, date, str]] = []
    if len(days) >= 40:
        n_trips = max(1, len(days) // 120)
        dests = rng.sample(DESTINATIONS[cur], n_trips)
        seg = len(days) // n_trips
        for t in range(n_trips):
            start_i = t * seg + rng.randrange(max(12, seg // 4), max(13, seg - 10))
            length = rng.choice([3, 4, 4, 5])
            if start_i + length >= len(days) - 4:
                continue
            trips.append((days[start_i], days[start_i + length - 1], dests[t]))
    ctx.timelines["trips"] = trips
    on_trip: dict[date, str] = {}
    for a, b, dest in trips:
        d = a
        while d <= b:
            on_trip[d] = dest
            d += timedelta(days=1)
        book = max(days[0] + timedelta(days=2), a - timedelta(days=rng.randrange(10, 26)))
        if rng.random() < 0.5:
            expense(book, EVENING, "travel", amt(90, 320), "flights", [f"Booked flights to {dest}, {{amt}}."])
        else:
            expense(book, EVENING, "travel", amt(45, 140), "train tickets", [f"Train tickets to {dest}, {{amt}}."])
        expense(
            book + timedelta(days=1),
            NIGHT,
            "travel",
            amt(180, 520),
            "hotel",
            [f"Hotel in {dest} booked, {{amt}} for the stay."],
        )

    # ---------------------------------------------------------------- habits
    p_coffee = rng.uniform(0.4, 0.75)
    coffee_prices = sorted(rng.sample([2.8, 3.2, 3.5, 3.9, 4.2, 4.5, 4.8, 5.6], 3))
    p_lunch = rng.uniform(0.1, 0.3)
    shop_days = sorted(rng.sample(range(7), rng.choice([1, 2])))
    commute = rng.choice(["transit", "transit", "fuel"]) if cur != "EUR" else rng.choice(["transit", "transit", "bike"])
    commute_day = rng.choice([0, 1])
    energy_day = 12 + stable_number(p["id"]) % 6
    split_every = rng.randrange(20, 32)
    next_split = rng.randrange(6, 16)
    refund_every = rng.randrange(28, 45)
    next_refund_after = rng.randrange(5, 20)
    birthdays = sorted(rng.sample(range(len(days)), max(1, len(days) // 70)))
    returnable: list[Rec] = []

    for i, d in enumerate(days):
        wd = d.weekday()
        workday = wd < 5
        trip = on_trip.get(d)

        # fixed payments
        for name, category, _, day in recurring:
            if d.day == day:
                price = recurring_price(name, d)
                if name == "rent":
                    tpl = ["Rent went out, {amt}.", "Paid the rent, {amt}.", "Rent day, {amt} gone."]
                    note = "rent"
                elif name == "the internet":
                    tpl = ["Internet bill, {amt}.", "Internet came off the card, {amt}."]
                    note = "internet bill"
                else:
                    tpl = [
                        f"{cap(name)} renewed, {{amt}}.",
                        f"{cap(name)} came off the card, {{amt}}.",
                        f"Monthly charge for {name}, {{amt}}.",
                    ]
                    note = name
                expense(
                    d,
                    MORNING + 0.5,
                    category,
                    price,
                    note,
                    tpl,
                    merchant=None if name in ("rent", "the internet") else name,
                    tags={"fixed": True, "recurring": name},
                )
        if d.day == energy_day:
            expense(d, AFTERNOON, "utilities", amt(38, 110), "energy bill", ENERGY)

        if trip:
            expense(
                d,
                MIDDAY,
                "eating out",
                amt(12, 28),
                "lunch",
                [f"Lunch in {trip}, {{amt}}.", "Lunch by the water, {amt}."],
                tags={"trip": True},
            )
            expense(
                d,
                EVENING,
                "eating out",
                amt(28, 75),
                "dinner",
                [f"Dinner out in {trip}, {{amt}}.", "Dinner at a place the hotel recommended, {amt}."],
                tags={"trip": True},
            )
            if rng.random() < 0.6:
                expense(d, AFTERNOON, "entertainment", amt(10, 30), "museum", [f"Museum in {trip}, {{amt}}."])
            if rng.random() < 0.5:
                expense(d, BREAKFAST, "coffee", round(rng.choice(coffee_prices) * fx, 2), "coffee", COFFEE)
            continue

        if rng.random() < (p_coffee if workday else 0.25):
            expense(
                d, BREAKFAST + rng.random() * 0.5, "coffee", round(rng.choice(coffee_prices) * fx, 2), "coffee", COFFEE
            )
        if workday and rng.random() < p_lunch:
            expense(d, MIDDAY, "eating out", amt(8, 16.5, 0.1), "lunch out", LUNCH)
        if wd in shop_days and rng.random() < 0.9:
            expense(
                d, AFTERNOON, "groceries", amt(28, 110), "groceries", GROCERIES, fmt={"store": rng.choice(p["stores"])}
            )
        elif rng.random() < 0.08:
            expense(
                d, AFTERNOON, "groceries", amt(6, 25), "groceries", GROCERIES, fmt={"store": rng.choice(p["stores"])}
            )
        if commute == "transit" and wd == commute_day:
            expense(d, COMMUTE, "transport", round(rng.choice([20, 25, 30]) * fx, 2), "travel pass", TRANSIT)
        elif commute == "fuel" and wd == commute_day and rng.random() < 0.8:
            expense(d, COMMUTE, "transport", amt(38, 62), "fuel", FUEL if cur == "USD" else FUEL_GB)
        if rng.random() < 0.06:
            expense(d, NIGHT, "transport", amt(9, 32), "taxi", TAXI, fmt={"friend": rng.choice(friends)})

        # dinners out, one of them split with a friend now and then
        if i >= next_split and wd in (4, 5) and i < len(days) - 3:
            next_split = i + split_every
            split_dinner(ctx, d, i, rng, rr, cur, amt, friends, timeline)
        elif rng.random() < (0.4 if wd in (4, 5) else 0.06):
            expense(
                d,
                EVENING,
                "eating out",
                amt(16, 70),
                "dinner out",
                DINNER,
                fmt={"place": rng.choice(RESTAURANTS), "friend": rng.choice(friends)},
            )

        # occasional purchases
        for cat, p_day, tpls, lo, hi, slot, note in OCCASIONAL:
            if rng.random() < p_day:
                r = expense(d, slot, cat, amt(lo, hi), note, tpls, fmt={"friend": rng.choice(friends)})
                if cat in RETURNABLE and r.stated["amount"] >= 15:
                    returnable.append(r)
        if i in birthdays:
            expense(d, EVENING, "gifts", amt(20, 80), "present", GIFTS, fmt={"friend": rng.choice(friends)})

        # a refund on something bought a few days ago
        if i >= next_refund_after and returnable:
            candidates = [r for r in returnable if 3 <= (d - r.date).days <= 12 and not r.tags.get("refunded")]
            if candidates and rng.random() < 0.5:
                target = rng.choice(candidates)
                target.tags["refunded"] = True
                full = rng.random() < 0.6
                amount = (
                    target.stated["amount"]
                    if full
                    else round(target.stated["amount"] * rng.choice([0.25, 0.4, 0.5]), 2)
                )
                rf = ctx.rec("refund", d, {"amount": amount}, links={"refers_to": target})
                what = target.stated["note"]
                bought = (
                    f" from {weekday(target.date)}"
                    if (d - target.date).days <= 6
                    else f" from the {ordinal(target.date.day)}"
                )
                if full:
                    text = rng.choice(
                        [
                            f"Returned the {what}{bought}, got {money(amount, cur, rr, False)} back.",
                            f"Refund came through for the {what}{bought}: {money(amount, cur, rr, False)}.",
                        ]
                    )
                else:
                    text = f"Got a partial refund on the {what}{bought}, {money(amount, cur, rr, False)} back."
                ctx.say(d, AFTERNOON, [rf], lambda late, t=text: t, can_be_late=False)
                next_refund_after = i + refund_every


def split_dinner(ctx: UserCtx, d: date, i: int, rng, rr, cur: str, amt, friends: list[str], timeline: dict) -> None:
    days = ctx.days
    friend = rng.choice(friends)
    total = amt(48, 120, 0.02)
    owed = round(total / 2, 2)
    half = rng.random() < 0.5
    place = rng.choice(RESTAURANTS)
    ex = ctx.rec(
        "expense",
        d,
        {"amount": total, "category": "eating out", "note": f"dinner with {friend}"},
        tags={"descriptor": f"dinner with {friend}", "key": ("expense", "eating out"), "split": True},
    )
    sp = ctx.rec("split", d, {"person": friend, "amount": total, "owed": owed}, links={"refers_to": ex})
    if half:
        tpl = "Dinner at {place} with {friend}, I paid the whole {amt}; we're going halves, so {friend} owes me half."
    else:
        tpl = rng.choice(
            [
                "Dinner at {place} with {friend}, I paid {amt} for both of us; {friend} owes me {owed}.",
                "Got the bill at {place}, {amt} for me and {friend}. {friend} owes me {owed}.",
            ]
        )

    def render(late, ex=ex, sp=sp, tpl=tpl):
        text = tpl.format(
            place=place,
            friend=friend,
            amt=money(ex.stated["amount"], cur, rr, False),
            owed=money(sp.stated["owed"], cur, rr, False),
        )
        return with_late(text, late, ex.date, rr)

    ctx.say(d, EVENING, [ex, sp], render, can_be_late=False)
    timeline["splits"].append(sp)
    pay_i = i + rng.randrange(2, 12)
    if pay_i >= len(days) or rng.random() >= 0.85:
        return  # not paid back by the end
    parts = [owed]
    if rng.random() < 0.3 and owed > 20:
        first_part = float(int(owed // 2))
        parts = [first_part, round(owed - first_part, 2)]
    j = pay_i
    for k, part in enumerate(parts):
        if k:
            j += rng.randrange(3, 9)
        if j >= len(days):
            break
        when = days[j]
        st = ctx.rec("settled", when, {"person": friend, "amount": part}, links={"refers_to": sp})
        if len(parts) == 1:
            text = rng.choice(
                [
                    f"{friend} paid me back the {money(part, cur, rr, False)} for dinner.",
                    f"Got {money(part, cur, rr, False)} from {friend} for the dinner, we're square.",
                ]
            )
        elif k == 0:
            text = f"{friend} sent {money(part, cur, rr, False)} of the dinner money, rest later."
        else:
            text = f"{friend} sent the rest of the dinner money, {money(part, cur, rr, False)}."
        ctx.say(when, AFTERNOON, [st], lambda late, t=text: t, can_be_late=False)


# ---------------------------------------------------------------- corrections


def correctable(rec: Rec) -> bool:
    return (
        rec.type == "expense"
        and not rec.tags.get("fixed")
        and not rec.tags.get("split")
        and not rec.tags.get("refunded")
        and rec.stated["amount"] >= 3
    )


def retractable(rec: Rec) -> bool:
    return correctable(rec) and rec.stated["category"] in (
        "transport",
        "eating out",
        "entertainment",
        "household",
        "coffee",
        "other",
    )


def key(rec: Rec) -> tuple:
    """What a message uses to point at this record on its day."""
    return ("expense", rec.stated["category"])


def misstate(rec: Rec, rng) -> tuple[str, object]:
    """Writes a wrong amount into `stated`; returns (field, true value)."""
    true = rec.truth["amount"]
    c = int(round(true * 100))
    whole, frac = divmod(c, 100)
    options = []
    s = str(whole)
    if len(s) >= 2 and s[-1] != s[-2]:
        options.append(int(s[:-2] + s[-1] + s[-2]) * 100 + frac)  # two digits swapped
    if frac and frac % 10 != frac // 10:
        options.append(whole * 100 + (frac % 10) * 10 + frac // 10)
    options.append(c + rng.choice([-1000, 1000, 500, -500]))
    options = [o for o in options if o > 100 and abs(o - c) >= 50] or [c + 500, c + 1000]
    wrong = rng.choice(options) / 100
    rec.stated["amount"] = round(wrong, 2)
    return "amount", round(true, 2)


def correction_text(rec: Rec, when: str, cur: str, rng) -> str:
    note = rec.tags.get("descriptor", rec.stated.get("note"))
    new = money(rec.truth["amount"], cur, rng, False)
    old = money(rec.stated["amount"], cur, rng, False)
    return rng.choice(
        [
            f"Correction: the {note} {when} was {new}, not {old}.",
            f"Typo earlier, the {note} {when} came to {new}, not {old}.",
            f"Just checked my banking app, the {note} {when} was actually {new}. I wrote {old}.",
        ]
    )


def retraction_text(rec: Rec, when: str, rng) -> str:
    note = rec.tags.get("descriptor", rec.stated.get("note"))
    reason = {
        "transport": "I ended up walking",
        "coffee": "it was on a colleague in the end",
        "eating out": "a friend paid in the end",
        "entertainment": "the event got cancelled before I was charged",
        "household": "the order got cancelled",
        "other": "it got cancelled",
    }[rec.stated["category"]]
    return rng.choice(
        [
            f"Scratch the {note} I logged {when}, {reason}.",
            f"Please ignore the {note} {when}, {reason}.",
        ]
    )
