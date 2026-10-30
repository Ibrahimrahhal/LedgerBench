"""
Runs one system over a dataset: ingest every selected user's sessions in date
order, then answer every question with a fresh call, score it, and write the
results (spec sections 1, 10 and 11).

Resumable at both stages. A user whose ingestion finished in an earlier
process is restored (`MemorySystem.restore`) rather than ingested again; one
that was cut off is forgotten and ingested from the start. Questions already
in answers.jsonl are skipped.

`max_cost` caps what the run directory may spend in all (ingestion, answers
and the judge, across resumes). Before each user's ingestion and each question,
the runner adds the measured cost so far to a projection of the next piece of
work (the measured cost per message, or per question) and stops cleanly if
that would pass the cap. Whatever was done is kept and summarised.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from collections.abc import Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any

from ledgerbench import __version__, results, scoring
from ledgerbench.dataset import Dataset, Question, User
from ledgerbench.systems.base import MemorySystem, RunConfig, Stopwatch, Usage
from ledgerbench.systems.openai_client import FatalAPIError

_EPSILON = 1e-9  # so float sums of cents do not trip the budget guard early


class RunConflict(RuntimeError):
    """The run directory belongs to a different system or dataset."""


class _Stop(Exception):
    pass


def _logger(run_dir: Path) -> logging.Logger:
    logger = logging.getLogger(f"ledgerbench.run.{run_dir.resolve()}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    handler = logging.FileHandler(run_dir / results.LOG_FILE, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"))
    logger.addHandler(handler)
    # The libraries' own request logs would bury the run's.
    for name in ("httpx", "httpcore", "openai", "mem0", "qdrant_client", "urllib3"):
        logging.getLogger(name).setLevel(logging.WARNING)
    for name in ("ledgerbench.openai", "ledgerbench.systems"):
        lib = logging.getLogger(name)
        lib.setLevel(logging.INFO)
        lib.propagate = False
        if handler not in lib.handlers:
            lib.handlers = [h for h in lib.handlers if not isinstance(h, logging.FileHandler)] + [handler]
    return logger


class _Progress:
    """One line on stderr, rewritten in place on a terminal and printed now and then otherwise."""

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled
        self.tty = enabled and sys.stderr.isatty()
        self.last = 0.0
        self.width = 0

    def update(self, text: str, *, force: bool = False) -> None:
        if not self.enabled:
            return
        if self.tty:
            self.width = max(self.width, len(text))
            sys.stderr.write("\r" + text.ljust(self.width))
            sys.stderr.flush()
        elif force or time.monotonic() - self.last > 10:
            sys.stderr.write(text + "\n")
            sys.stderr.flush()
            self.last = time.monotonic()

    def done(self) -> None:
        if self.enabled and self.tty and self.width:
            sys.stderr.write("\n")
            sys.stderr.flush()
            self.width = 0


def _select(dataset: Dataset, users: Sequence[str] | None) -> list[User]:
    if not users:
        return list(dataset.users)
    by_id = {u.id: u for u in dataset.users}
    missing = [u for u in users if u not in by_id]
    if missing:
        raise ValueError(f"unknown users {missing}; the dataset has {', '.join(by_id)}")
    return [by_id[u] for u in users]


def _questions(user: User, max_questions: int | None) -> list[Question]:
    questions = list(user.questions)
    return questions[:max_questions] if max_questions is not None else questions


def _prepare(run_dir: Path, *, system_name: str, system_spec: str, dataset: Dataset, resume: bool) -> dict[str, Any]:
    run_dir.mkdir(parents=True, exist_ok=True)
    meta_path = run_dir / results.RUN_FILE
    if not resume:
        for name in (results.ANSWERS_FILE, results.INGEST_FILE, results.SUMMARY_FILE, results.RUN_FILE):
            path = run_dir / name
            if path.exists():
                path.unlink()
        state = run_dir / "state"
        if state.exists():
            import shutil

            shutil.rmtree(state)
    if meta_path.exists():
        meta = results.read_json(meta_path)
        if meta.get("system") != system_name:
            raise RunConflict(
                f"{run_dir} holds a run of {meta.get('system')!r}, not {system_name!r}; use another --run-id"
            )
        theirs = (meta.get("dataset") or {}).get("sha256")
        if theirs and dataset.sha256 and theirs != dataset.sha256:
            raise RunConflict(
                f"{run_dir} was run on a different dataset file (sha256 {theirs[:12]}...); use another --run-id"
            )
        return meta
    return {"started": results.now_iso()}


def run(
    system: MemorySystem,
    dataset: Dataset,
    *,
    run_dir: str | Path,
    users: Sequence[str] | None = None,
    max_questions: int | None = None,
    workers: int = 4,
    resume: bool = True,
    max_cost: float | None = None,
    judge: scoring.Judge | None = None,
    config: RunConfig | None = None,
    system_name: str | None = None,
    system_spec: str | None = None,
    ingest_workers: int = 1,
    progress: bool = True,
    extra_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Runs `system` and returns the summary (also written to summary.json).
    `max_questions` caps the questions per user (the first N in file order).
    `judge` scores `text` questions; without one they are saved unjudged and
    can be scored later with `ledgerbench score`.
    """
    run_dir = Path(run_dir)
    name = system_name or system.name
    meta = _prepare(run_dir, system_name=name, system_spec=system_spec or name, dataset=dataset, resume=resume)
    logger = _logger(run_dir)
    bar = _Progress(progress)
    config = config or RunConfig(run_id=run_dir.name, run_dir=run_dir, size=dataset.size, workers=workers)
    selected = _select(dataset, users)
    total_questions = sum(len(_questions(u, max_questions)) for u in selected)

    meta.update(
        {
            "run_id": config.run_id,
            "system": name,
            "system_spec": system_spec or name,
            "test_system": bool(system.privileged) or name in results.TEST_SYSTEMS,
            "dataset": {
                "name": dataset.name,
                "version": dataset.version,
                "size": dataset.size,
                "seed": dataset.seed,
                "generated_on": dataset.generated_on,
                "sha256": dataset.sha256,
                "path": str(Path(dataset.path).resolve()) if dataset.path else None,
            },
            "users": [u.id for u in selected],
            "max_questions": max_questions,
            "subset": len(selected) < len(dataset.users) or total_questions < len(dataset.questions()),
            "questions_selected": total_questions,
            "git_commit": results.git_commit(),
            "ledgerbench_version": __version__,
            "options": {
                "workers": workers,
                "ingest_workers": ingest_workers,
                "max_cost": max_cost,
                **(extra_options or {}),
            },
            "stopped": None,
            "updated": results.now_iso(),
        }
    )
    results.write_json(run_dir / results.RUN_FILE, meta)
    logger.info(
        "run %s: system %s on %s %s (%d users, %d questions)",
        config.run_id,
        name,
        dataset.name,
        dataset.size,
        len(selected),
        total_questions,
    )

    system.setup(config)
    meta["models"] = {
        "answer": config.answer_model,
        "embedding": config.embedding_model,
        "judge": config.judge_model if judge else None,
        **system.models(),
    }
    meta["notes"] = system.notes()
    results.write_json(run_dir / results.RUN_FILE, meta)

    ingest_log = results.IngestLog(run_dir / results.INGEST_FILE)
    answers_path = run_dir / results.ANSWERS_FILE
    answers_writer = results.JsonlWriter(answers_path)
    stopped: list[str] = []
    stop = threading.Event()
    spend_lock = threading.Lock()
    answer_rows = results.read_jsonl(answers_path)
    answered_cost = [sum(_row_cost(r) for r in answer_rows), len(answer_rows)]

    def spent() -> float:
        with spend_lock:
            return ingest_log.spent() + answered_cost[0]

    def halt(reason: str) -> None:
        if not stop.is_set():
            stopped.append(reason)
            logger.warning("stopping: %s", reason)
        stop.set()

    try:
        ingested = _ingest_all(system, selected, ingest_log, logger, bar, stop, halt, spent, max_cost, ingest_workers)
        if not stop.is_set():
            _answer_all(
                system, ingested, max_questions, answers_path, answers_writer, logger, bar, stop, halt, spent,
                spend_lock, answered_cost, max_cost, workers, judge,
            )  # fmt: skip
    except KeyboardInterrupt:
        halt("interrupted")
        raise
    finally:
        bar.done()
        try:
            system.teardown()
        except Exception as error:  # noqa: BLE001 - teardown must not hide the run's outcome
            logger.warning("teardown failed: %s", error)
        meta["stopped"] = "; ".join(stopped) or None
        meta["updated"] = results.now_iso()
        results.write_json(run_dir / results.RUN_FILE, meta)
        summary = results.summarize(run_dir)
        logger.info(
            "summary: accuracy %s over %d answers, cost $%.4f",
            summary["accuracy"],
            summary["questions"]["answered"],
            summary["cost_usd"]["total"],
        )
    return summary


def _row_cost(row: dict[str, Any]) -> float:
    return float((row.get("usage") or {}).get("cost_usd", 0.0)) + float(
        (row.get("judge_usage") or {}).get("cost_usd", 0.0)
    )


# --------------------------------------------------------------------- ingestion


def _ingest_all(system, selected, ingest_log, logger, bar, stop, halt, spent, max_cost, ingest_workers) -> list[User]:
    ready: list[User] = []
    todo: list[User] = []
    for user in selected:
        if ingest_log.done(user.id):
            if system.restore(user.view(), list(user.sessions)):
                logger.info("%s: restored from an earlier ingestion", user.id)
                ready.append(user)
                continue
            logger.info("%s: ingested earlier but the system could not restore it; ingesting again", user.id)
        todo.append(user)
    if not todo:
        return ready

    total_sessions = sum(len(u.sessions) for u in todo)
    counter = {"sessions": 0}
    lock = threading.Lock()

    def ingest_user(user: User) -> bool:
        with lock:
            rate = ingest_log.rate_per_message()
            projected = rate * user.message_count if rate is not None else 0.0
            if max_cost is not None and spent() + projected > max_cost + _EPSILON:
                halt(
                    f"max cost ${max_cost:.2f}: ${spent():.4f} spent, ingesting {user.id} would cost about ${projected:.4f} more"
                )
                return False
        view = user.view()
        attempt = ingest_log.next_attempt(user.id)
        system.forget(view)
        total = Usage()
        seconds = 0.0
        for index, session in enumerate(user.sessions):
            if stop.is_set():
                return False
            if max_cost is not None and spent() > max_cost + _EPSILON:
                halt(f"max cost ${max_cost:.2f} passed during {user.id}'s ingestion")
                return False
            with Stopwatch() as watch:
                usage = system.ingest(view, session) or Usage()
            total.add(usage)
            seconds += watch.seconds
            ingest_log.write(
                {
                    "user": user.id, "attempt": attempt, "index": index, "date": session.date,
                    "messages": len(session.messages), "seconds": round(watch.seconds, 3), "usage": usage.to_dict(),
                }
            )  # fmt: skip
            with lock:
                counter["sessions"] += 1
                bar.update(
                    f"ingest {user.id} {index + 1}/{len(user.sessions)} | all {counter['sessions']}/{total_sessions} sessions | ${spent():.4f}"
                )
        ingest_log.write(
            {
                "user": user.id, "attempt": attempt, "done": True, "sessions": len(user.sessions),
                "messages": user.message_count, "seconds": round(seconds, 3), "usage": total.to_dict(),
            }
        )  # fmt: skip
        logger.info(
            "%s: ingested %d sessions, %d messages, $%.4f, %.1fs",
            user.id,
            len(user.sessions),
            user.message_count,
            total.cost_usd,
            seconds,
        )
        return True

    def guarded(user: User) -> bool:
        try:
            return ingest_user(user)
        except FatalAPIError as error:
            halt(f"API error during {user.id}'s ingestion: {error}")
        except Exception as error:  # noqa: BLE001 - one user's failure is logged; the rest go on
            logger.exception("%s: ingestion failed: %s", user.id, error)
        return False

    if ingest_workers <= 1:
        for user in todo:
            if stop.is_set():
                break
            if guarded(user):
                ready.append(user)
    else:
        with ThreadPoolExecutor(max_workers=ingest_workers) as pool:
            futures = {pool.submit(guarded, user): user for user in todo}
            for future, user in futures.items():
                if future.result():
                    ready.append(user)
    order = {u.id: i for i, u in enumerate(selected)}
    return sorted(ready, key=lambda u: order[u.id])


# ---------------------------------------------------------------------- answering


def _answer_all(
    system, users, max_questions, answers_path, writer, logger, bar, stop, halt, spent, spend_lock,
    answered_cost, max_cost, workers, judge,
) -> None:  # fmt: skip
    done = results.answer_ids(answers_path)
    todo = [(u, q) for u in users for q in _questions(u, max_questions) if q.id not in done]
    if not todo:
        return
    logger.info("answering %d questions (%d already answered)", len(todo), len(done))
    stats = {"n": 0, "correct": 0, "scored": 0, "failed": 0}
    in_flight: dict[Future, Question] = {}
    queue = list(todo)

    def work(user: User, question: Question) -> dict[str, Any]:
        reply = system.answer(user.view(), question.prompt())
        try:
            score = scoring.score(question, reply.text, judge=judge)
        except FatalAPIError as error:
            score = scoring.score(question, reply.text, judge=None)
            score = scoring.Score(None, score.extracted, scoring.JUDGE, f"not judged: {error}", score.format_ok)
            halt(f"API error in the judge: {error}")
        except Exception as error:  # noqa: BLE001 - keep the paid-for reply; judge it later
            score = scoring.score(question, reply.text, judge=None)
            if score.method == scoring.JUDGE:
                score = scoring.Score(
                    None,
                    score.extracted,
                    scoring.JUDGE,
                    f"not judged: {type(error).__name__}: {error}",
                    score.format_ok,
                )
        return {
            "question_id": question.id,
            "user": user.id,
            "domain": question.domain,
            "skills": list(question.skills),
            "answer_type": question.answer_type,
            "question": question.question,
            "asked_on": question.asked_on,
            "gold": list(question.gold) if isinstance(question.gold, tuple) else question.gold,
            "gold_text": question.gold_text,
            "reply": reply.text,
            "extracted": score.extracted,
            "format_ok": score.format_ok,
            "correct": score.correct,
            "method": score.method,
            "reason": score.reason,
            "judge_model": score.judge_model,
            "latency_s": round(reply.latency_s, 3),
            "usage": reply.usage.to_dict(),
            "judge_usage": score.judge_usage,
            "tools": list(reply.tools),
        }

    def can_start() -> bool:
        if stop.is_set():
            return False
        if max_cost is None:
            return True
        with spend_lock:
            mean = answered_cost[0] / answered_cost[1] if answered_cost[1] else 0.0
        projected = mean * (len(in_flight) + 1)
        if spent() + projected > max_cost + _EPSILON:
            halt(f"max cost ${max_cost:.2f}: ${spent():.4f} spent, about ${mean:.5f} per question")
            return False
        return True

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        while queue or in_flight:
            while queue and len(in_flight) < max(1, workers) and can_start():
                user, question = queue.pop(0)
                in_flight[pool.submit(work, user, question)] = question
            if not in_flight:
                break
            finished, _ = wait(list(in_flight), return_when=FIRST_COMPLETED)
            for future in finished:
                question = in_flight.pop(future)
                try:
                    row = future.result()
                except FatalAPIError as error:
                    halt(f"API error while answering: {error}")
                    stats["failed"] += 1
                    continue
                except Exception as error:  # noqa: BLE001 - one failed question is retried on resume
                    stats["failed"] += 1
                    logger.error("%s failed: %s: %s", question.id, type(error).__name__, error)
                    continue
                writer.write(row)
                with spend_lock:
                    answered_cost[0] += _row_cost(row)
                    answered_cost[1] += 1
                stats["n"] += 1
                if row["correct"] is not None:
                    stats["scored"] += 1
                    stats["correct"] += int(bool(row["correct"]))
                logger.info(
                    "%s %s extracted=%r (%s)",
                    question.id,
                    {True: "RIGHT", False: "WRONG", None: "UNJUDGED"}[row["correct"]],
                    row["extracted"],
                    row["reason"],
                )
                accuracy = stats["correct"] / stats["scored"] if stats["scored"] else 0.0
                bar.update(
                    f"answer {stats['n']}/{len(todo)} | acc {accuracy:.3f} | failed {stats['failed']} | ${spent():.4f}"
                )
            if stop.is_set():
                queue.clear()
    bar.update(f"answered {stats['n']}/{len(todo)}, {stats['failed']} failed", force=True)
    if stats["failed"]:
        logger.warning("%d questions failed and will be retried on resume", stats["failed"])


def make_system(spec: str, dataset: Dataset, **options: Any) -> tuple[MemorySystem, str]:
    """Builds a system by name or import path. The oracle alone is handed the gold answers."""
    from ledgerbench.systems.base import system_class, system_name

    cls = system_class(spec)
    if cls.privileged:
        options = {**options, "gold": {q.id: q.gold_text for q in dataset.questions()}}
    return cls(**options), system_name(spec, cls)


def rescore(
    run_dir: str | Path, dataset: Dataset | None = None, *, judge: scoring.Judge | None = None, rejudge: bool = False
) -> dict[str, Any]:
    """
    Scores the saved replies in `run_dir` again with the current scorer (after
    a scorer fix, or to judge `text` answers saved unjudged) and rebuilds the
    summary. A judge verdict already given is kept unless `rejudge`; a new one
    adds its cost to what the old one cost.
    """
    from ledgerbench.dataset import load

    run_dir = Path(run_dir)
    meta = results.read_json(run_dir / results.RUN_FILE)
    if dataset is None:
        path = (meta.get("dataset") or {}).get("path")
        if not path:
            raise ValueError(f"{run_dir}/run.json does not name its dataset; pass --data")
        dataset = load(path)
    theirs = (meta.get("dataset") or {}).get("sha256")
    if theirs and dataset.sha256 and theirs != dataset.sha256:
        raise RunConflict(f"{run_dir} was run on a different dataset file than {dataset.path}")
    rows = results.read_jsonl(run_dir / results.ANSWERS_FILE)
    changed = 0
    for row in rows:
        question = dataset.question(row["question_id"])
        keep = (
            question.answer_type == "text"
            and row.get("method") == scoring.JUDGE
            and row.get("correct") is not None
            and not rejudge
        )
        if keep:
            continue
        before = (row.get("correct"), row.get("extracted"))
        try:
            score = scoring.score(question, row.get("reply", ""), judge=judge)
        except Exception as error:  # noqa: BLE001 - leave it unjudged and say why
            score = scoring.score(question, row.get("reply", ""), judge=None)
            score = scoring.Score(
                None, score.extracted, scoring.JUDGE, f"not judged: {type(error).__name__}: {error}", score.format_ok
            )
        judge_usage = Usage.from_dict(row.get("judge_usage")) if row.get("judge_usage") else None
        if score.judge_usage:
            judge_usage = (judge_usage or Usage()).add(Usage.from_dict(score.judge_usage))
        row.update(
            {
                "gold": list(question.gold) if isinstance(question.gold, tuple) else question.gold,
                "gold_text": question.gold_text,
                "extracted": score.extracted,
                "format_ok": score.format_ok,
                "correct": score.correct,
                "method": score.method,
                "reason": score.reason,
                "judge_model": score.judge_model or row.get("judge_model"),
                "judge_usage": judge_usage.to_dict() if judge_usage else None,
            }
        )
        changed += before != (row.get("correct"), row.get("extracted"))
    results.rewrite_jsonl(run_dir / results.ANSWERS_FILE, rows)
    meta["rescored"] = results.now_iso()
    results.write_json(run_dir / results.RUN_FILE, meta)
    summary = results.summarize(run_dir)
    summary["_changed"] = changed
    return summary
