"""
Builds results/LEADERBOARD.md from every summary.json under the results
directory (spec section 10): one section per dataset size, and inside it one
table per answer model, since systems are only compared on the same answer
model (spec section 11). The answer model is also printed beside every row.

For each size, system and answer model the latest complete run is shown.
Partial runs and the test systems (oracle, null) are left out unless asked for.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ledgerbench import results

DOMAINS = ("spending", "food", "training", "body", "cross")
SIZE_ORDER = {"mini": 0, "standard": 1, "long": 2}


def _pct(value: float | None) -> str:
    return "–" if value is None else f"{100 * value:.1f}%"


def _money(value: float | None) -> str:
    return "–" if value is None else f"${value:.2f}" if value >= 0.1 else f"${value:.4f}"


def _row_key(summary: dict[str, Any]) -> tuple[str, str, str]:
    return (
        summary.get("size") or "?",
        summary.get("system") or "?",
        (summary.get("models") or {}).get("answer") or "?",
    )


def _rank(summary: dict[str, Any]) -> tuple[bool, str, str]:
    """Complete full runs first, then the latest."""
    return (
        bool(summary.get("complete")) and not summary.get("subset"),
        summary.get("started") or "",
        summary.get("date") or "",
    )


def select(
    found: list[tuple[Path, dict[str, Any]]], *, include_partial: bool = False, include_test: bool = False
) -> list[tuple[Path, dict[str, Any]]]:
    best: dict[tuple[str, str, str], tuple[Path, dict[str, Any]]] = {}
    for path, summary in found:
        if summary.get("test_system") and not include_test:
            continue
        if not (summary.get("complete") and not summary.get("subset")) and not include_partial:
            continue
        key = _row_key(summary)
        current = best.get(key)
        if current is None or _rank(summary) > _rank(current[1]):
            best[key] = (path, summary)
    return list(best.values())


def render(rows: list[tuple[Path, dict[str, Any]]], results_dir: Path) -> str:
    lines = [
        "# LedgerBench leaderboard",
        "",
        "Built by `ledgerbench leaderboard` from every `summary.json` under `results/`. For each size, system and answer",
        "model, the latest complete run. Accuracy is over scored answers; costs are in USD at list prices, ingestion apart",
        "from answering. Systems are compared only within a table, where they share an answer model.",
        "",
    ]
    if not rows:
        lines.append("No complete runs yet.")
        return "\n".join(lines) + "\n"
    by_size: dict[str, list[tuple[Path, dict[str, Any]]]] = {}
    for path, summary in rows:
        by_size.setdefault(summary.get("size") or "?", []).append((path, summary))
    for size in sorted(by_size, key=lambda s: (SIZE_ORDER.get(s, 9), s)):
        group = by_size[size]
        dataset = group[0][1].get("dataset") or {}
        lines += [
            f"## {size}",
            "",
            f"Dataset version {dataset.get('version', '?')}, seed {dataset.get('seed', '?')}.",
            "",
        ]
        by_model: dict[str, list[tuple[Path, dict[str, Any]]]] = {}
        for path, summary in group:
            by_model.setdefault((summary.get("models") or {}).get("answer") or "?", []).append((path, summary))
        for model in sorted(by_model):
            lines += [f"### Answer model: {model}", ""]
            header = [
                "System",
                "Answer model",
                "Accuracy",
                *[d.capitalize() for d in DOMAINS],
                "Answered",
                "Ingestion",
                "Answering",
                "Mean latency",
                "Run",
            ]
            lines.append("| " + " | ".join(header) + " |")
            lines.append("|" + "|".join(["---"] * len(header)) + "|")
            ordered = sorted(by_model[model], key=lambda r: -(r[1].get("accuracy") or 0.0))
            for path, s in ordered:
                by_domain = s.get("by_domain") or {}
                cost = s.get("cost_usd") or {}
                questions = s.get("questions") or {}
                latency = (s.get("latency_s") or {}).get("mean")
                name = s.get("system", "?") + ("" if s.get("complete") and not s.get("subset") else " (partial)")
                try:
                    link = path.parent.relative_to(results_dir).as_posix()
                except ValueError:
                    link = path.parent.as_posix()
                cells = [
                    name,
                    model,
                    _pct(s.get("accuracy")),
                    *[_pct((by_domain.get(d) or {}).get("accuracy")) for d in DOMAINS],
                    f"{questions.get('answered', 0)}/{questions.get('selected', 0)}",
                    _money(cost.get("ingestion")),
                    _money(cost.get("answering")),
                    "–" if latency is None else f"{latency:.2f}s",
                    f"[{s.get('run_id', '?')}]({link})",
                ]
                lines.append("| " + " | ".join(cells) + " |")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build(
    results_dir: str | Path = "results",
    *,
    include_partial: bool = False,
    include_test: bool = False,
    write: bool = True,
) -> str:
    results_dir = Path(results_dir)
    rows = select(results.summaries(results_dir), include_partial=include_partial, include_test=include_test)
    text = render(rows, results_dir)
    if write:
        results_dir.mkdir(parents=True, exist_ok=True)
        (results_dir / "LEADERBOARD.md").write_bytes(text.encode("utf-8"))
    return text
