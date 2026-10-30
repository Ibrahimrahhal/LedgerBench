"""
The files a run writes (spec section 10) and the summary built from them.

    results/<size>/<system>/<run-id>/
      run.json        what was run: system, dataset (with its SHA-256), models, options, notes
      ingest.jsonl    one line per ingested session, and a `done` line per user
      answers.jsonl   one line per answered question
      summary.json    accuracy by domain, skill and answer type; latency; cost; models; git commit
      run.log         the progress log

Every file is written with LF line endings and appended to as work lands, so
a run that stops (a crash, a budget, Ctrl-C) keeps everything it paid for and
resumes where it left off.
"""

from __future__ import annotations

import json
import math
import statistics
import subprocess
import threading
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ledgerbench import __version__
from ledgerbench.systems.base import Usage

RUN_FILE = "run.json"
INGEST_FILE = "ingest.jsonl"
ANSWERS_FILE = "answers.jsonl"
SUMMARY_FILE = "summary.json"
LOG_FILE = "run.log"
TEST_SYSTEMS = ("oracle", "null")


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes((json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    tmp.replace(path)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # a line cut short by a crash; the work it stood for is redone
    return rows


class JsonlWriter:
    """Appends JSON lines from any thread."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.Lock()

    def write(self, row: dict[str, Any]) -> None:
        data = (json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8")
        with self.lock, self.path.open("ab") as f:
            f.write(data)


def rewrite_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows).encode("utf-8"))
    tmp.replace(path)


def git_commit(start: Path | None = None) -> str | None:
    """The commit of the ledger-bench checkout this package runs from, with -dirty if it has local changes."""
    root = Path(start or Path(__file__).resolve().parents[1])
    if not (root / ".git").exists():
        return None
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, timeout=10)
        if commit.returncode != 0:
            return None
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
        )
        dirty = status.returncode == 0 and bool(status.stdout.strip())
        return commit.stdout.strip() + ("-dirty" if dirty else "")
    except (OSError, subprocess.SubprocessError):
        return None


# ---------------------------------------------------------------------- ingestion


class IngestLog:
    """
    ingest.jsonl. Session lines: {"user", "attempt", "index", "date", "messages",
    "seconds", "usage"}. After a user's last session: {"user", "attempt",
    "done": true, "sessions", "messages", "seconds", "usage"}. A user is
    ingested when its latest attempt has a done line; earlier, unfinished
    attempts stay in the file because their cost was spent.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.writer = JsonlWriter(path)
        self.lock = threading.Lock()
        self.rows = read_jsonl(path)

    def write(self, row: dict[str, Any]) -> None:
        with self.lock:
            self.rows.append(row)
        self.writer.write(row)

    def done(self, user_id: str) -> dict[str, Any] | None:
        with self.lock:
            latest = self._latest_attempt(user_id)
            for row in reversed(self.rows):
                if row.get("user") == user_id and row.get("done") and row.get("attempt") == latest:
                    return row
        return None

    def _latest_attempt(self, user_id: str) -> int:
        return max((int(r.get("attempt", 1)) for r in self.rows if r.get("user") == user_id), default=0)

    def next_attempt(self, user_id: str) -> int:
        with self.lock:
            return self._latest_attempt(user_id) + 1

    def spent(self) -> float:
        """Everything ingestion has cost in this run directory, finished or not."""
        with self.lock:
            return sum(float((r.get("usage") or {}).get("cost_usd", 0.0)) for r in self.rows if not r.get("done"))

    def rate_per_message(self) -> float | None:
        """Measured ingestion cost per message, over finished users; None before any finished."""
        with self.lock:
            done = [r for r in self.rows if r.get("done")]
        messages = sum(int(r.get("messages", 0)) for r in done)
        if not messages:
            return None
        return sum(float((r.get("usage") or {}).get("cost_usd", 0.0)) for r in done) / messages


def ingestion_totals(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Ingestion as reported: each user's finished attempt, plus what unfinished attempts cost."""
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("done"):
            latest[row["user"]] = row  # the last done line per user wins
    counted = {(u, r.get("attempt")) for u, r in latest.items()}
    abandoned = Usage.total(
        Usage.from_dict(r.get("usage"))
        for r in rows
        if not r.get("done") and (r.get("user"), r.get("attempt")) not in counted
    )
    usage = Usage.total(Usage.from_dict(r.get("usage")) for r in latest.values())
    return {
        "users": sorted(latest),
        "sessions": sum(int(r.get("sessions", 0)) for r in latest.values()),
        "messages": sum(int(r.get("messages", 0)) for r in latest.values()),
        "seconds": round(sum(float(r.get("seconds", 0.0)) for r in latest.values()), 2),
        "cost_usd": round(usage.cost_usd, 8),
        "abandoned_cost_usd": round(abandoned.cost_usd, 8),
        "usage": usage.to_dict(),
        "per_user": {
            u: {
                "cost_usd": round(float((r.get("usage") or {}).get("cost_usd", 0.0)), 8),
                "seconds": r.get("seconds"),
                "messages": r.get("messages"),
            }
            for u, r in sorted(latest.items())
        },
        "_abandoned_usage": abandoned,
    }


# ------------------------------------------------------------------------ answers


def answer_ids(path: Path) -> set[str]:
    return {r["question_id"] for r in read_jsonl(path) if "question_id" in r}


def _bucket(rows: list[dict[str, Any]], key) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        keys = key(row)
        for k in keys if isinstance(keys, (list, tuple)) else [keys]:
            bucket = out.setdefault(str(k), {"n": 0, "correct": 0, "unjudged": 0})
            if row.get("correct") is None:
                bucket["unjudged"] += 1
                continue
            bucket["n"] += 1
            bucket["correct"] += int(bool(row["correct"]))
    for bucket in out.values():
        bucket["accuracy"] = round(bucket["correct"] / bucket["n"], 4) if bucket["n"] else None
        if not bucket["unjudged"]:
            del bucket["unjudged"]
    return dict(sorted(out.items()))


def p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(math.ceil(0.95 * len(ordered)) - 1, 0)]


def summarize(run_dir: Path, *, write: bool = True) -> dict[str, Any]:
    """Builds summary.json from the files in `run_dir` alone, so it can be rebuilt after a re-score."""
    run_dir = Path(run_dir)
    meta = read_json(run_dir / RUN_FILE) if (run_dir / RUN_FILE).exists() else {}
    answers = read_jsonl(run_dir / ANSWERS_FILE)
    ingest = ingestion_totals(read_jsonl(run_dir / INGEST_FILE))
    abandoned: Usage = ingest.pop("_abandoned_usage")

    scored = [r for r in answers if r.get("correct") is not None]
    correct = sum(bool(r["correct"]) for r in scored)
    latencies = [float(r.get("latency_s") or 0.0) for r in answers]
    answer_usage = Usage.total(Usage.from_dict(r.get("usage")) for r in answers)
    judge_usage = Usage.total(Usage.from_dict(r.get("judge_usage")) for r in answers if r.get("judge_usage"))
    ingest_usage = Usage.from_dict(ingest["usage"])
    selected = int(meta.get("questions_selected") or 0)
    judge_models = sorted({r["judge_model"] for r in answers if r.get("judge_model")})
    unpriced = sorted(
        set(
            answer_usage.unpriced_models
            + judge_usage.unpriced_models
            + ingest_usage.unpriced_models
            + abandoned.unpriced_models
        )
    )
    dataset = meta.get("dataset") or {}

    summary = {
        "benchmark": dataset.get("name", "LedgerBench"),
        "system": meta.get("system"),
        "system_spec": meta.get("system_spec"),
        "test_system": bool(meta.get("test_system")) or meta.get("system") in TEST_SYSTEMS,
        "run_id": meta.get("run_id", run_dir.name),
        "size": dataset.get("size"),
        "dataset": {k: dataset.get(k) for k in ("name", "version", "size", "seed", "generated_on", "sha256")},
        "date": now_iso()[:10],
        "started": meta.get("started"),
        "git_commit": meta.get("git_commit"),
        "ledgerbench_version": meta.get("ledgerbench_version", __version__),
        "models": {**(meta.get("models") or {}), **({"judge_used": judge_models} if judge_models else {})},
        "complete": bool(selected) and len(answers) >= selected and not meta.get("stopped"),
        "subset": bool(meta.get("subset")),
        "questions": {
            "selected": selected,
            "answered": len(answers),
            "scored": len(scored),
            "unjudged": len(answers) - len(scored),
        },
        "users": {"selected": meta.get("users") or [], "ingested": ingest["users"]},
        "accuracy": round(correct / len(scored), 4) if scored else None,
        "correct": correct,
        "by_domain": _bucket(answers, lambda r: r.get("domain", "")),
        "by_skill": _bucket(answers, lambda r: r.get("skills") or []),
        "by_answer_type": _bucket(answers, lambda r: r.get("answer_type", "")),
        "by_method": _bucket(answers, lambda r: r.get("method", "")),
        "format_ok_rate": round(sum(bool(r.get("format_ok")) for r in answers) / len(answers), 4) if answers else None,
        "latency_s": {
            "mean": round(statistics.fmean(latencies), 3) if latencies else None,
            "p95": round(p95(latencies), 3) if latencies else None,
        },
        "cost_usd": {
            "ingestion": round(ingest_usage.cost_usd, 8),
            "ingestion_abandoned": round(abandoned.cost_usd, 8),
            "answering": round(answer_usage.cost_usd, 8),
            "judge": round(judge_usage.cost_usd, 8),
            "total": round(
                ingest_usage.cost_usd + abandoned.cost_usd + answer_usage.cost_usd + judge_usage.cost_usd, 8
            ),
            "answering_per_question": round(answer_usage.cost_usd / len(answers), 8) if answers else None,
        },
        "usage": {
            "ingestion": ingest_usage.to_dict(),
            "answering": answer_usage.to_dict(),
            "judge": judge_usage.to_dict(),
        },
        "unpriced_models": unpriced,
        "ingestion": {k: v for k, v in ingest.items() if k != "usage"},
        "stopped": meta.get("stopped"),
        "options": meta.get("options") or {},
        "notes": meta.get("notes", ""),
    }
    if write:
        write_json(run_dir / SUMMARY_FILE, summary)
    return summary


def summaries(results_dir: Path) -> list[tuple[Path, dict[str, Any]]]:
    """Every summary.json under `results_dir`, with its path."""
    out = []
    for path in sorted(Path(results_dir).glob("**/" + SUMMARY_FILE)):
        try:
            out.append((path, read_json(path)))
        except (OSError, json.JSONDecodeError):
            continue
    return out
