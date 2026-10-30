"""
The synthetic users: who they are, what they track, and the habits the domain
simulators read. Only `PUBLIC_KEYS` go into the dataset.
"""

from __future__ import annotations

import math
import random
from datetime import date, timedelta

from ledgerbench.generate import phrasing

PUBLIC_KEYS = ("id", "name", "profile", "currency", "units", "domains")
DOMAIN_ORDER = ("spending", "food", "training", "body")
OPTIONAL = ("food", "training", "body")

SIZES = {
    # users, days per user, questions per user
    "mini": (3, 21, 20),
    "standard": (12, 90, 40),
    "long": (6, 365, 60),
}

NAMES = [
    "Rana", "Marcus", "Priya", "Diego", "Hanna", "Tomas", "Leila", "Sven", "Aisha", "Kenji", "Sofia", "Owen",
    "Mei", "Tariq", "Ines", "Callum", "Nadia", "Jonas", "Amara", "Luca", "Freya", "Omar", "Zoe", "Mateo",
]  # fmt: skip
FRIENDS = ["Sam", "Jo", "Alex", "Nina", "Ben", "Maya", "Theo", "Lena", "Ravi", "Chloe", "Dan", "Ana", "Kofi", "Ruth"]
CITIES = {
    "EUR": ["Lisbon", "Berlin", "Amsterdam", "Madrid", "Milan", "Vienna", "Dublin", "Lyon"],
    "USD": ["Chicago", "Austin", "Denver", "Seattle", "Boston", "Atlanta"],
    "GBP": ["Leeds", "Bristol", "Manchester", "Glasgow", "London", "Brighton"],
}
JOBS = [
    "nurse", "product designer", "secondary-school teacher", "backend developer", "pharmacist", "architect",
    "data analyst", "physiotherapist", "civil engineer", "accountant", "sous-chef", "paralegal",
]  # fmt: skip
STORES = {
    "EUR": ["Lidl", "Aldi", "Rewe", "Carrefour", "Albert Heijn", "Pingo Doce", "Mercadona", "Spar"],
    "USD": ["Trader Joe's", "Whole Foods", "Kroger", "Safeway", "H-E-B", "Costco"],
    "GBP": ["Tesco", "Sainsbury's", "Aldi", "Lidl", "Co-op", "Waitrose"],
}
CLAUSES = {
    "spending": [
        "keeping an eye on where my money goes",
        "trying to spend more deliberately",
        "saving up and watching my spending",
    ],
    "food": ["counting what I eat", "logging my meals to eat better", "keeping my food honest"],
    "training": {
        "gym": ["following a gym plan", "lifting a few times a week", "trying to get stronger at the gym"],
        "run": ["training for a race", "running most weeks and lifting a little"],
    },
    "body": ["tracking my weight and sleep", "watching my weight and how I sleep"],
}

for _n in NAMES + FRIENDS:
    phrasing.KEEP_CASE.add(_n)


def assign_domains(n: int, rng: random.Random) -> list[list[str]]:
    """
    Spending for everyone; at least a third track all four; every other domain for
    at least two thirds. Users not on all four take two of the three, rotating.
    """
    n_all = math.ceil(n / 3)
    pairs = [("food", "training"), ("training", "body"), ("food", "body")]
    rng.shuffle(pairs)
    order = list(range(n))
    rng.shuffle(order)
    out: list[list[str]] = [[] for _ in range(n)]
    for k, i in enumerate(order):
        extra = OPTIONAL if k < n_all else pairs[(k - n_all) % 3]
        out[i] = [d for d in DOMAIN_ORDER if d == "spending" or d in extra]
    need = math.ceil(2 * n / 3)
    for d in OPTIONAL:
        assert sum(d in x for x in out) >= need, (d, out)
    assert sum(len(x) == 4 for x in out) >= math.ceil(n / 3)
    return out


def start_dates(size: str, n: int, rng: random.Random) -> list[date]:
    if size == "mini":
        firsts = [date(2026, 2, 1), date(2026, 3, 1), date(2026, 4, 1), date(2026, 5, 1)]
        return [firsts[i % len(firsts)] for i in range(n)]
    if size == "long":
        base = date(2025, 1, 6)
        return [base + timedelta(days=rng.randrange(0, 70)) for _ in range(n)]
    base = date(2026, 1, 5)
    return [base + timedelta(days=rng.randrange(0, 46)) for _ in range(n)]


def build(size: str, seed: int) -> list[dict]:
    n, n_days, n_questions = SIZES[size]
    rng = random.Random(f"{seed}:{size}:personas")
    names = rng.sample(NAMES, n)
    domains = assign_domains(n, rng)
    starts = start_dates(size, n, rng)
    currencies = ["EUR", "USD", "GBP"]
    offset = rng.randrange(3)
    jobs = rng.sample(JOBS, min(n, len(JOBS))) + rng.sample(JOBS, max(0, n - len(JOBS)))
    people = []
    for i in range(n):
        cur = currencies[(i + offset) % 3]
        if cur == "USD":
            units = {"body_weight": "lb", "lifts": "lb"}
        elif cur == "EUR":
            units = {"body_weight": "kg", "lifts": "kg"}
        else:
            units = {"body_weight": rng.choice(["kg", "lb"]), "lifts": "kg"}
        city = rng.choice(CITIES[cur])
        program = rng.choice(["ppl", "upper_lower", "full_run", "runner", "ppl", "upper_lower"])
        p = {
            "id": f"u{i + 1}",
            "name": names[i],
            "currency": cur,
            "units": units,
            "domains": domains[i],
            "city": city,
            "job": jobs[i],
            "friends": rng.sample([f for f in FRIENDS if f != names[i]], 3),
            "stores": rng.sample(STORES[cur], 2),
            "start": starts[i],
            "n_days": n_days,
            "n_questions": n_questions,
            "food_style": ["kcal", "protein", "macros"][(i + rng.randrange(3)) % 3],
            "program": program,
            "weigh_rate": rng.choice([0.85, 0.6, 0.4, 0.3]),
            "tracks_steps": rng.random() < 0.7,
            "tracks_rhr": rng.random() < 0.5,
        }
        p["profile"] = profile(p, rng)
        people.append(p)
    return people


def profile(p: dict, rng: random.Random) -> str:
    parts = []
    for d in p["domains"]:
        if d == "training":
            kind = "run" if p["program"] in ("runner", "full_run") else "gym"
            parts.append(rng.choice(CLAUSES["training"][kind]))
        else:
            parts.append(rng.choice(CLAUSES[d]))
    if len(parts) == 1:
        tail = parts[0]
    else:
        tail = ", ".join(parts[:-1]) + " and " + parts[-1]
    article = "an" if p["job"][0] in "aeiou" else "a"
    text = f"I'm {p['name']}, {article} {p['job']} in {p['city']}, {tail}."
    assert not any(ch.isdigit() for ch in text), text
    return text


def public(p: dict) -> dict:
    return {k: p[k] for k in PUBLIC_KEYS}
