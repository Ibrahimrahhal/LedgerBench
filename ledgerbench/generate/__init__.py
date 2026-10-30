"""
The LedgerBench data generator (spec sections 2 to 8).

    from ledgerbench.generate import main
    main("standard", seed=2026, out_dir="data")   # -> data/ledgerbench-standard.json

or `python -m ledgerbench.generate --size mini --seed 2026`. Pure standard
library, deterministic for a given (size, seed) on Python 3.10 to 3.14; only
`generated_on` follows the clock. Writes the dataset and a preview, runs the
independent checker (`check.py`) on the written file, and raises on any
failure.

Layout: personas -> one simulator per domain (spending, food, training, body)
plus small talk (distractors) -> build (late logging, corrections, sessions,
event ids) -> questions (from the simulators' truth) -> check (from the events
alone).
"""

from __future__ import annotations

import json
import math
from collections import Counter
from datetime import date
from pathlib import Path

from ledgerbench.generate import check as checker
from ledgerbench.generate import personas, questions
from ledgerbench.generate.build import LOGGED, build_user, events_of

NAME = "LedgerBench"
VERSION = "1.0"

__all__ = ["main", "generate", "NAME", "VERSION"]


def generate(size: str = "standard", seed: int = 2026) -> tuple[dict, list[str]]:
    """Builds the dataset dict in memory. Returns (data, report lines)."""
    if size not in personas.SIZES:
        raise ValueError(f"unknown size {size!r}; one of {', '.join(personas.SIZES)}")
    people = personas.build(size, seed)
    ctxs = [build_user(p, seed, size) for p in people]
    n_q = personas.SIZES[size][2]
    text_budget = [math.floor(questions.TEXT_SHARE * n_q * len(people))]
    qs = questions.build_all(ctxs, n_q, f"{seed}:{size}", text_budget)
    users = []
    for ctx in ctxs:
        user = personas.public(ctx.persona)
        user["sessions"] = ctx.sessions
        user["questions"] = qs[ctx.persona["id"]]
        user["events"] = events_of(ctx)
        users.append(user)
    data = {
        "name": NAME,
        "version": VERSION,
        "size": size,
        "seed": seed,
        "generated_on": date.today().isoformat(),
        "users": users,
    }
    return data, coverage_report(data)


def coverage_report(data: dict) -> list[str]:
    qs = [q for u in data["users"] for q in u["questions"]]
    domains = ["spending", "food", "training", "body", "cross"]
    skills = [
        "lookup",
        "aggregate",
        "group",
        "window",
        "state",
        "as_of",
        "change",
        "correction",
        "cross",
        "adherence",
        "budget",
    ]
    grid = Counter((q["domain"], s) for q in qs for s in q["skills"])
    lines = [f"{data['size']}: {len(data['users'])} users, {len(qs)} questions", ""]
    head = f"{'':<10}" + "".join(f"{s[:9]:>10}" for s in skills) + f"{'questions':>11}"
    lines.append(head)
    for d in domains:
        row = f"{d:<10}" + "".join(f"{(grid[(d, s)] or '.'):>10}" for s in skills)
        row += f"{sum(q['domain'] == d for q in qs):>11}"
        lines.append(row)
    lines.append("")
    types = Counter(q["answer_type"] for q in qs)
    lines.append(
        "answer types: "
        + ", ".join(f"{k} {v} ({100 * v / len(qs):.1f}%)" for k, v in sorted(types.items(), key=lambda kv: -kv[1]))
    )
    corr = sum("correction" in q["skills"] for q in qs)
    cross = sum(q["domain"] == "cross" for q in qs)
    lines.append(
        f"correction-flagged: {corr} ({100 * corr / len(qs):.1f}%)   cross: {cross} ({100 * cross / len(qs):.1f}%)"
    )
    msgs = [sum(len(s["messages"]) for s in u["sessions"]) for u in data["users"]]
    evs = [len(u["events"]) for u in data["users"]]
    lines.append(
        f"messages per user: {min(msgs)}-{max(msgs)} (mean {sum(msgs) / len(msgs):.0f}, total {sum(msgs)});"
        f" events per user: {min(evs)}-{max(evs)} (total {sum(evs)})"
    )
    kinds = Counter(e["type"] for u in data["users"] for e in u["events"])
    logged = sum(kinds[t] for t in LOGGED)
    lines.append(
        f"logged records {logged}: corrections {kinds['correction']} ({100 * kinds['correction'] / logged:.1f}%), "
        f"retractions {kinds['retraction']} ({100 * kinds['retraction'] / logged:.1f}%)"
    )
    late = sum(1 for u in data["users"] for e in u["events"] if e["type"] in LOGGED and e["date"] != e["session_date"])
    lines.append(f"logged late: {late} ({100 * late / logged:.1f}%)")
    return lines


def write_json(data: dict, path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")


def write_preview(data: dict, path: Path, report: list[str]) -> None:
    user = next((u for u in data["users"] if len(u["domains"]) == 4), data["users"][0])
    out = [
        f"# {NAME} {data['size']} preview",
        "",
        f"Seed {data['seed']}, version {data['version']}, generated {data['generated_on']}. "
        f"This page shows one user; the JSON has {len(data['users'])}.",
        "",
        "```",
        *report,
        "```",
        "",
        f"## {user['name']} ({user['id']}, {user['currency']}, body weight in {user['units']['body_weight']}, lifts in {user['units']['lifts']})",
        "",
        f"Tracks {', '.join(user['domains'])}. Profile: {user['profile']}",
        "",
        "### The first seven sessions",
        "",
    ]
    for s in user["sessions"][:7]:
        out.append(f"**{s['weekday']} {s['date']}**")
        out.append("")
        out.extend(f"{k}. {m}" for k, m in enumerate(s["messages"]))
        out.append("")
    out += ["### A sample of events", "", "```json"]
    by_type: dict[str, list[dict]] = {}
    for e in user["events"]:
        by_type.setdefault(e["type"], []).append(e)
    for t in (
        "expense",
        "refund",
        "split",
        "settled",
        "recurring",
        "price_change",
        "budget",
        "meal",
        "kcal_target",
        "plan_change",
        "workout",
        "skip",
        "run",
        "weight",
        "sleep_hours",
        "steps",
        "correction",
        "retraction",
        "distractor",
    ):
        if t in by_type:
            pick = by_type[t][len(by_type[t]) // 3]
            out.append(json.dumps(pick, ensure_ascii=False))
    out += ["```", "", "### Twelve questions", ""]
    qs = user["questions"]
    chosen, seen = [], Counter()
    pool = list(qs)
    while pool and len(chosen) < 12:
        pool.sort(key=lambda q: (seen[q["domain"]], "correction" not in q["skills"], int(q["id"].rsplit("q", 1)[1])))
        q = pool.pop(0)
        chosen.append(q)
        seen[q["domain"]] += 1
    for q in sorted(chosen, key=lambda q: int(q["id"].rsplit("q", 1)[1])):
        out.append(f"**{q['id']}** ({q['domain']}; {', '.join(q['skills'])}; {q['answer_type']}): {q['question']}")
        out.append("")
        out.append(f"- gold: `{json.dumps(q['gold'], ensure_ascii=False)}` ({q['gold_text']})")
        if q["choices"]:
            out.append(f"- choices: {len(q['choices'])}; aliases: `{json.dumps(q['aliases'], ensure_ascii=False)}`")
        ev = q["evidence"]
        out.append(f"- evidence ({len(ev)}): {', '.join(ev[:12])}{' ...' if len(ev) > 12 else ''}")
        out.append(f"- derivation: `{json.dumps(q['derivation'], ensure_ascii=False)}`")
        out.append("")
    path.write_text("\n".join(out), encoding="utf-8", newline="\n")


def main(size: str = "standard", seed: int = 2026, out_dir: str | Path = "data") -> Path:
    data, report = generate(size, seed)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"ledgerbench-{size}.json"
    write_json(data, path)
    write_preview(data, out / f"ledgerbench-{size}.preview.md", report)
    totals = checker.check_file(path)
    print("\n".join(report))
    print(
        f"check passed: {totals['questions']} questions re-derived from events; wrote {path} ({path.stat().st_size / 1e6:.2f} MB)"
    )
    return path
