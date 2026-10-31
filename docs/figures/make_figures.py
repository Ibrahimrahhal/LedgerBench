"""
Draws the README's figures, in a light and a dark version each.

    python docs/figures/make_figures.py

The banner and the diagram are fixed; the two result charts are read from the
runs in results/ named by RUNS below, so they follow a re-run. Standard
library only, like the rest of the scoring path.
"""

from __future__ import annotations

import json
import math
from html import escape
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

# The runs the README reports, in no particular order: the charts sort them.
RUNS = {
    "fullcontext": ("Full context", ROOT / "results/standard/fullcontext/luna-allfour/summary.json"),
    "openmate": ("Open Mate", ROOT / "results/standard/openmate/luna-allfour/summary.json"),
    "mem0": ("Mem0 2.2.1", ROOT / "results/standard/mem0/luna-allfour/summary.json"),
    "rag": ("Naive RAG", ROOT / "results/standard/rag/luna-allfour/summary.json"),
}

# Skills that ask what was said, then skills that ask for something worked out.
RECALL = [("lookup", "Lookup"), ("state", "State now"), ("as_of", "As of a date")]
COMPUTE = [
    ("aggregate", "Aggregate"),
    ("window", "Window"),
    ("cross", "Cross-domain"),
    ("adherence", "Plan adherence"),
    ("group", "Top group"),
    ("change", "Change"),
    ("correction", "After a correction"),
    ("budget", "Budget left"),
]

SANS = "-apple-system,BlinkMacSystemFont,'Segoe UI','Noto Sans',Helvetica,Arial,sans-serif"
SERIF = "Georgia,'Iowan Old Style','Times New Roman',serif"
MONO = "ui-monospace,SFMono-Regular,'SF Mono',Menlo,Consolas,monospace"

THEMES = {
    "light": {
        "paper": "#faf8f3",
        "card": "#ffffff",
        "ink": "#1f2328",
        "muted": "#59636e",
        "rule": "#e4ddd0",
        "faint": "#f1ece2",
        "accent": "#0e7c6b",
        "accent_soft": "#d5ece6",
        "warn": "#b4581b",
        "track": "#efeae0",
        "on_accent": "#ffffff",
        "systems": {"fullcontext": "#3d4a5c", "openmate": "#0e7c6b", "mem0": "#b4581b", "rag": "#7c6f9b"},
    },
    "dark": {
        "paper": "#151b23",
        "card": "#0d1117",
        "ink": "#e6edf3",
        "muted": "#9198a1",
        "rule": "#2d3540",
        "faint": "#1b222c",
        "accent": "#3fc1a8",
        "accent_soft": "#173a35",
        "warn": "#f0883e",
        "track": "#1f2731",
        "on_accent": "#0d1117",
        "systems": {"fullcontext": "#8fa3bd", "openmate": "#3fc1a8", "mem0": "#f0883e", "rag": "#a99bd1"},
    },
}


def svg(width, height, body, label):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{escape(label)}">\n'
        f"<title>{escape(label)}</title>\n{body}\n</svg>\n"
    )


def text(x, y, content, size=16, fill="#000", family=SANS, weight=400, anchor="start", extra=""):
    return (
        f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" font-weight="{weight}" '
        f'fill="{fill}" text-anchor="{anchor}" {extra}>{escape(content)}</text>'
    )


# The banner


def banner(t):
    w, h = 1280, 420
    parts = [
        f'<rect x="0.5" y="0.5" width="{w - 1}" height="{h - 1}" rx="18" fill="{t["paper"]}" stroke="{t["rule"]}"/>'
    ]

    # Faint ledger lines across the whole card, like ruled paper.
    for y in range(64, h - 20, 32):
        parts.append(f'<line x1="24" y1="{y}" x2="{w - 24}" y2="{y}" stroke="{t["faint"]}" stroke-width="1"/>')
    parts.append(f'<line x1="92" y1="24" x2="92" y2="{h - 24}" stroke="{t["warn"]}" stroke-opacity="0.35"/>')

    parts.append(
        text(120, 104, "AN OPEN BENCHMARK FOR AGENT MEMORY", 15, t["accent"], weight=600, extra='letter-spacing="2.4"')
    )
    parts.append(text(116, 186, "LedgerBench", 84, t["ink"], SERIF, 700, extra='letter-spacing="-1.5"'))
    parts.append(text(120, 236, "Can an AI assistant's memory keep", 27, t["ink"], SERIF))
    parts.append(text(120, 272, "the books on a person's life?", 27, t["ink"], SERIF))

    # Georgia's figures are old style, so numbers are set in the sans face.
    stats = [("4", "domains"), ("11", "skills"), ("480", "questions"), ("1%", "judged by a model")]
    for i, (number, label) in enumerate(stats):
        x = 120 + i * 118
        parts.append(text(x, 340, number, 30, t["accent"], SANS, 700))
        parts.append(text(x, 364, label, 15, t["muted"]))

    # The ledger card on the right: what a person said, as records.
    cx, cy, cw = 724, 34, 512
    rows = [
        ("Day 1", "Rent, the 1st of every month", "$1,370.00", None),
        ("Day 1", "Cappuccino and a pastry", "$4.02", None),
        ("Day 1", "Poke bowl, lunch out", "$17.20", None),
        ("Day 1", "Bench press 4×6 @ 145", "upper", None),
        ("Day 1", "Slept 7h45", "7.75 h", None),
        ("Day 3", "Stir fry, yesterday's dinner", "572 kcal", "472"),
    ]
    ch = 66 + len(rows) * 34 + 96
    parts.append(
        f'<rect x="{cx + 6}" y="{cy + 8}" width="{cw}" height="{ch}" rx="12" fill="{t["rule"]}" opacity="0.6"/>'
    )
    parts.append(
        f'<rect x="{cx}" y="{cy}" width="{cw}" height="{ch}" rx="12" fill="{t["card"]}" stroke="{t["rule"]}"/>'
    )
    parts.append(text(cx + 24, cy + 36, "Owen's records", 17, t["ink"], weight=600))
    parts.append(text(cx + cw - 24, cy + 36, "from what he told the assistant", 13, t["muted"], anchor="end"))
    hy = cy + 66
    parts.append(f'<line x1="{cx + 16}" y1="{hy}" x2="{cx + cw - 16}" y2="{hy}" stroke="{t["rule"]}"/>')
    y = hy + 26
    for day, entry, amount, struck in rows:
        parts.append(text(cx + 24, y, day, 13, t["muted"], MONO))
        parts.append(text(cx + 92, y, entry, 15, t["ink"]))
        if struck:
            sx = cx + cw - 24 - 78
            parts.append(text(sx - 10, y, struck, 14, t["warn"], MONO, anchor="end"))
            parts.append(
                f'<line x1="{sx - 42}" y1="{y - 5}" x2="{sx - 8}" y2="{y - 5}" stroke="{t["warn"]}" stroke-width="1.6"/>'
            )
            parts.append(text(cx + cw - 24, y, amount, 14, t["warn"], MONO, 600, anchor="end"))
        else:
            parts.append(text(cx + cw - 24, y, amount, 14, t["ink"], MONO, anchor="end"))
        parts.append(f'<line x1="{cx + 16}" y1="{y + 11}" x2="{cx + cw - 16}" y2="{y + 11}" stroke="{t["faint"]}"/>')
        y += 34
    # A double rule, then a question and its gold answer.
    y += 2
    parts.append(
        f'<line x1="{cx + 16}" y1="{y}" x2="{cx + cw - 16}" y2="{y}" stroke="{t["ink"]}" stroke-opacity="0.5"/>'
    )
    parts.append(
        f'<line x1="{cx + 16}" y1="{y + 4}" x2="{cx + cw - 16}" y2="{y + 4}" stroke="{t["ink"]}" stroke-opacity="0.5"/>'
    )
    qy = y + 34
    parts.append(f'<rect x="{cx + 20}" y="{qy - 17}" width="22" height="22" rx="5" fill="{t["accent_soft"]}"/>')
    parts.append(text(cx + 31, qy - 1, "Q", 13, t["accent"], weight=700, anchor="middle"))
    parts.append(text(cx + 54, qy, "How many times did I eat out between", 15, t["ink"]))
    parts.append(text(cx + 54, qy + 22, "31 January and 21 February?", 15, t["ink"]))
    parts.append(text(cx + cw - 24, qy + 11, "Answer: 9", 16, t["accent"], MONO, 700, anchor="end"))

    return svg(w, h, "\n".join(parts), "LedgerBench: can an AI assistant's memory keep the books on a person's life?")


# How it works


def how_it_works(t):
    w, h = 1280, 300
    steps = [
        (
            "1",
            "Simulate",
            ["People chat with their", "assistant every day for", "weeks: spending, food,", "training, body."],
        ),
        ("2", "Ingest", ["Your memory system", "reads each day's", "messages, in order,", "and keeps what it wants."]),
        ("3", "Ask", ["Fresh questions about", "totals, plans, changes", "and corrections, each", "in a new context."]),
        ("4", "Score", ["The reply's Answer: line", "against gold worked out", "from records no system", "ever sees."]),
    ]
    parts = []
    bw, gap, top = 272, 30, 28
    x = (w - (bw * 4 + gap * 3)) / 2
    for i, (number, title, lines) in enumerate(steps):
        parts.append(
            f'<rect x="{x}" y="{top}" width="{bw}" height="210" rx="14" fill="{t["paper"]}" stroke="{t["rule"]}"/>'
        )
        parts.append(f'<circle cx="{x + 36}" cy="{top + 40}" r="17" fill="{t["accent"]}"/>')
        parts.append(text(x + 36, top + 46, number, 17, t["on_accent"], weight=700, anchor="middle"))
        parts.append(text(x + 64, top + 47, title, 23, t["ink"], SERIF, 700))
        for j, line in enumerate(lines):
            parts.append(text(x + 24, top + 96 + j * 25, line, 16, t["muted"]))
        if i < 3:
            ax = x + bw + 4
            ay = top + 105
            parts.append(
                f'<path d="M{ax} {ay} h{gap - 10} m-7 -6 l7 6 l-7 6" fill="none" stroke="{t["accent"]}" '
                f'stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>'
            )
        x += bw + gap
    notes = (
        "Built in: corrections · retractions · entries logged a day late · numbers in small talk · plans that change"
    )
    parts.append(text(w / 2, top + 252, notes, 15, t["warn"], anchor="middle"))
    return svg(w, h, "\n".join(parts), "How LedgerBench works: simulate, ingest, ask, score")


# Results


def load_runs():
    runs = []
    for key, (name, path) in RUNS.items():
        if not path.exists():
            continue
        summary = json.loads(path.read_text(encoding="utf-8"))
        runs.append({"key": key, "name": name, "summary": summary})
    runs.sort(key=lambda run: run["summary"]["accuracy"], reverse=True)
    return runs


def interval(accuracy, n):
    """The half-width of a normal 95% interval, as the leaderboard reports it."""
    return 1.96 * math.sqrt(accuracy * (1 - accuracy) / n) if n else 0.0


def money(value):
    return f"${value:,.2f}"


def overall(t, runs):
    w = 1280
    row, top, left, right = 76, 70, 230, 330
    h = top + row * len(runs) + 56
    track = w - left - right
    parts = []
    # The scale: gridlines every 25 points, labelled under the last row.
    for pct in range(0, 101, 25):
        gx = left + track * pct / 100
        parts.append(
            f'<line x1="{gx}" y1="{top - 18}" x2="{gx}" y2="{top + row * len(runs) - 18}" stroke="{t["rule"]}" '
            f'stroke-dasharray="{"0" if pct in (0, 100) else "3 5"}"/>'
        )
        parts.append(text(gx, top + row * len(runs) + 6, f"{pct}%", 13, t["muted"], anchor="middle"))
    parts.append(text(left, 30, "Accuracy on 160 standard questions", 15, t["muted"], weight=600))
    parts.append(text(w - 24, 30, "Spend per run", 15, t["muted"], weight=600, anchor="end"))

    for i, run in enumerate(runs):
        s = run["summary"]
        acc, n = s["accuracy"], s["questions"]["scored"]
        y = top + i * row
        color = t["systems"].get(run["key"], t["accent"])
        parts.append(text(left - 24, y + 14, run["name"], 19, t["ink"], weight=600, anchor="end"))
        parts.append(f'<rect x="{left}" y="{y - 6}" width="{track}" height="28" rx="6" fill="{t["track"]}"/>')
        parts.append(f'<rect x="{left}" y="{y - 6}" width="{track * acc:.1f}" height="28" rx="6" fill="{color}"/>')
        half = interval(acc, n)
        lo, hi = left + track * max(acc - half, 0), left + track * min(acc + half, 1)
        parts.append(
            f'<path d="M{lo:.1f} {y + 8} H{hi:.1f} M{lo:.1f} {y + 1} v14 M{hi:.1f} {y + 1} v14" '
            f'stroke="{t["ink"]}" stroke-opacity="0.55" stroke-width="1.6" fill="none"/>'
        )
        label_x = max(hi, left + track * acc) + 12
        parts.append(text(label_x, y + 15, f"{acc * 100:.1f}%", 19, t["ink"], SANS, 700))
        cost = s["cost_usd"]
        parts.append(text(w - 24, y + 4, f"{money(cost['answering'])} to answer", 14, t["ink"], anchor="end"))
        parts.append(text(w - 24, y + 24, f"{money(cost['ingestion'])} to ingest", 14, t["muted"], anchor="end"))
    parts.append(text(left, h - 10, "Whiskers: 95% interval. Every system answered with gpt-6-luna.", 13, t["muted"]))
    return svg(w, h, "\n".join(parts), "LedgerBench accuracy by system")


def mix(a, b, f):
    """A colour a fraction f of the way from a to b."""
    a, b = a.lstrip("#"), b.lstrip("#")
    channels = [round(int(a[i : i + 2], 16) * (1 - f) + int(b[i : i + 2], 16) * f) for i in (0, 2, 4)]
    return "#" + "".join(f"{c:02x}" for c in channels)


def skills(t, runs):
    w = 1280
    label_w, top, cell_h, gap = 300, 96, 40, 6
    cols = len(runs)
    cell_w = (w - label_w - 24 - gap * (cols - 1)) / cols
    groups = [("What was said", RECALL), ("What has to be worked out", COMPUTE)]
    h = top + sum(len(items) for _, items in groups) * (cell_h + gap) + len(groups) * 44 + 30
    parts = []
    for c, run in enumerate(runs):
        x = label_w + c * (cell_w + gap) + cell_w / 2
        parts.append(text(x, 40, run["name"], 17, t["ink"], weight=600, anchor="middle"))
        parts.append(
            f'<rect x="{x - 18}" y="52" width="36" height="4" rx="2" fill="{t["systems"].get(run["key"], t["accent"])}"/>'
        )

    y = top
    for title, items in groups:
        parts.append(text(24, y + 6, title.upper(), 13, t["accent"], weight=700, extra='letter-spacing="1.6"'))
        parts.append(f'<line x1="24" y1="{y + 16}" x2="{w - 24}" y2="{y + 16}" stroke="{t["rule"]}"/>')
        y += 30
        for key, name in items:
            n = runs[0]["summary"]["by_skill"].get(key, {}).get("n", 0)
            parts.append(text(24, y + cell_h / 2 + 6, name, 17, t["ink"]))
            parts.append(text(label_w - 20, y + cell_h / 2 + 6, f"{n} q", 13, t["muted"], anchor="end"))
            for c, run in enumerate(runs):
                skill = run["summary"]["by_skill"].get(key)
                x = label_w + c * (cell_w + gap)
                if not skill:
                    continue
                acc = skill["accuracy"]
                fill = mix(t["track"], t["accent"], acc)
                ink = t["on_accent"] if acc >= 0.62 else t["ink"]
                parts.append(f'<rect x="{x:.1f}" y="{y}" width="{cell_w:.1f}" height="{cell_h}" rx="7" fill="{fill}"/>')
                parts.append(
                    text(x + cell_w / 2, y + cell_h / 2 + 6, f"{acc * 100:.0f}%", 17, ink, weight=600, anchor="middle")
                )
            y += cell_h + gap
        y += 14
    return svg(w, h, "\n".join(parts), "LedgerBench accuracy by skill and system")


def main():
    runs = load_runs()
    figures = {"banner": banner, "how-it-works": how_it_works}
    if runs:
        figures["results"] = lambda t: overall(t, runs)
        figures["skills"] = lambda t: skills(t, runs)
    for name, draw in figures.items():
        for theme, palette in THEMES.items():
            (HERE / f"{name}-{theme}.svg").write_text(draw(palette), encoding="utf-8", newline="\n")
    print(f"wrote {len(figures) * len(THEMES)} figures to {HERE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
