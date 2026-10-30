"""The `ledgerbench` command: generate, run, score, leaderboard, inspect."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from ledgerbench import __version__


def _option(text: str) -> tuple[str, Any]:
    if "=" not in text:
        raise argparse.ArgumentTypeError(f"--option takes key=value, not {text!r}")
    key, _, raw = text.partition("=")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        value = raw
    return key.strip(), value


def build_parser() -> argparse.ArgumentParser:
    from ledgerbench.systems.base import BUILTIN, DEFAULT_ANSWER_MODEL, DEFAULT_EMBEDDING_MODEL, DEFAULT_JUDGE_MODEL

    parser = argparse.ArgumentParser(
        prog="ledgerbench",
        description="LedgerBench: can an assistant's memory keep the books on a person's life?",
    )
    parser.add_argument("--version", action="version", version=f"ledgerbench {__version__}")
    sub = parser.add_subparsers(dest="command", required=True, metavar="command")

    gen = sub.add_parser(
        "generate",
        help="generate a dataset file",
        description="Generate a dataset deterministically from (size, seed).",
    )
    gen.add_argument("--size", default="standard", choices=["mini", "standard", "long"])
    gen.add_argument("--seed", type=int, default=2026)
    gen.add_argument("--out", default="data", help="output directory (default: data)")

    run = sub.add_parser(
        "run",
        help="run a system on a dataset",
        description="Ingest every user's sessions, answer every question, score, and summarise. Resumes by default.",
    )
    run.add_argument("--system", required=True, help=f"one of {', '.join(BUILTIN)}, or package.module:Class")
    run.add_argument("--data", required=True, help="dataset file, e.g. data/ledgerbench-mini.json")
    run.add_argument("--users", nargs="+", metavar="USER", help="only these user ids (default: all)")
    run.add_argument("--max-questions", type=int, metavar="N", help="answer at most the first N questions of each user")
    run.add_argument("--answer-model", default=DEFAULT_ANSWER_MODEL, help=f"default: {DEFAULT_ANSWER_MODEL}")
    run.add_argument("--embedding-model", default=DEFAULT_EMBEDDING_MODEL, help=f"default: {DEFAULT_EMBEDDING_MODEL}")
    run.add_argument(
        "--judge-model", default=DEFAULT_JUDGE_MODEL, help=f"for text questions only (default: {DEFAULT_JUDGE_MODEL})"
    )
    run.add_argument(
        "--no-judge", action="store_true", help="save text answers unjudged (score them later with `ledgerbench score`)"
    )
    run.add_argument("--workers", type=int, default=4, help="questions answered at once (default: 4)")
    run.add_argument("--ingest-workers", type=int, default=1, help="users ingested at once (default: 1)")
    run.add_argument(
        "--max-cost", type=float, metavar="USD", help="stop before work that would take the run's total spend past this"
    )
    run.add_argument("--run-id", help="names the run directory; reuse it to resume (default: <answer-model>-<date>)")
    run.add_argument("--results-dir", default="results", help="default: results")
    run.add_argument(
        "--fresh", action="store_true", help="discard this run directory's earlier results instead of resuming"
    )
    run.add_argument(
        "--option",
        action="append",
        type=_option,
        default=[],
        metavar="KEY=VALUE",
        help="passed to the system's constructor, e.g. top_k=10 (repeatable)",
    )
    run.add_argument("--quiet", action="store_true", help="no progress line")

    score = sub.add_parser(
        "score",
        help="re-score a run's saved replies",
        description="Re-score saved replies with the current scorer and rebuild summary.json.",
    )
    score.add_argument("--run-dir", required=True)
    score.add_argument("--data", help="dataset file (default: the one named in run.json)")
    score.add_argument("--judge-model", default=DEFAULT_JUDGE_MODEL)
    score.add_argument("--no-judge", action="store_true", help="leave unjudged text answers unjudged")
    score.add_argument("--rejudge", action="store_true", help="judge text answers again even if already judged")

    board = sub.add_parser(
        "leaderboard", help="build results/LEADERBOARD.md", description="Build LEADERBOARD.md from every summary.json."
    )
    board.add_argument("--results-dir", default="results")
    board.add_argument("--include-partial", action="store_true", help="also show runs that did not finish")
    board.add_argument("--include-test", action="store_true", help="also show the oracle and null test systems")
    board.add_argument("--print", action="store_true", dest="show", help="also print it")

    inspect = sub.add_parser(
        "inspect",
        help="print a user's sessions and questions",
        description="Print one user's sessions and questions, with gold answers, for a human.",
    )
    inspect.add_argument("--data", required=True)
    inspect.add_argument("--user", required=True)
    inspect.add_argument("--questions-only", action="store_true")
    inspect.add_argument("--sessions-only", action="store_true")
    inspect.add_argument("--events", action="store_true", help="also print the structured events")
    return parser


# --------------------------------------------------------------------- commands


def cmd_generate(args: argparse.Namespace) -> int:
    try:
        from ledgerbench.generate import main as generate
    except ImportError as error:
        print(f"the generator is not available: {error}", file=sys.stderr)
        return 1
    path = generate(size=args.size, seed=args.seed, out_dir=args.out)
    print(path)
    return 0


def _judge(model: str, needed: bool, disabled: bool):
    from ledgerbench.systems.openai_client import load_api_key

    if not needed or disabled:
        return None
    if not load_api_key():
        print(
            "note: OPENAI_API_KEY is not set, so text answers will be saved unjudged (score them later with `ledgerbench score`)",
            file=sys.stderr,
        )
        return None
    from ledgerbench.judge import LLMJudge

    return LLMJudge(model)


def _print_summary(summary: dict[str, Any], run_dir: Path) -> None:
    q = summary["questions"]
    accuracy = summary.get("accuracy")
    print(f"{summary['system']} on {summary.get('size')}: accuracy {'n/a' if accuracy is None else f'{100 * accuracy:.1f}%'} "
          f"({summary['correct']}/{q['scored']} scored, {q['answered']}/{q['selected']} answered, {q['unjudged']} unjudged)")  # fmt: skip
    for title, key in (("domain", "by_domain"), ("answer type", "by_answer_type")):
        parts = [
            f"{k} {100 * v['accuracy']:.0f}% (n={v['n']})"
            for k, v in summary[key].items()
            if v.get("accuracy") is not None
        ]
        if parts:
            print(f"  by {title}: " + ", ".join(parts))
    cost = summary["cost_usd"]
    print(f"  cost: ingestion ${cost['ingestion']:.4f}, answering ${cost['answering']:.4f}, judge ${cost['judge']:.4f}; "
          f"latency mean {summary['latency_s']['mean']}s, p95 {summary['latency_s']['p95']}s")  # fmt: skip
    if summary.get("unpriced_models"):
        print(f"  warning: no price for {', '.join(summary['unpriced_models'])}; their cost is counted as 0")
    if summary.get("stopped"):
        print(f"  stopped: {summary['stopped']}")
    print(f"  results: {run_dir}")


def cmd_run(args: argparse.Namespace) -> int:
    from ledgerbench import runner
    from ledgerbench.dataset import load
    from ledgerbench.systems.base import RunConfig
    from ledgerbench.systems.openai_client import load_api_key

    dataset = load(args.data)
    try:
        system, name = runner.make_system(args.system, dataset, **dict(args.option))
    except (ValueError, TypeError, ImportError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if system.needs_openai and not load_api_key():
        print(
            "error: OPENAI_API_KEY is not set (in the environment or a .env file in the working directory)",
            file=sys.stderr,
        )
        return 2
    run_id = args.run_id or (
        f"{args.answer_model}-{datetime.now():%Y-%m-%d}" if system.needs_openai else f"{datetime.now():%Y-%m-%d}"
    )
    run_dir = Path(args.results_dir) / dataset.size / name / run_id
    users = args.users or [u.id for u in dataset.users]
    needs_judge = any(q.answer_type == "text" for u in dataset.users if u.id in users for q in u.questions)
    config = RunConfig(
        run_id=run_id,
        run_dir=run_dir,
        size=dataset.size,
        answer_model=args.answer_model,
        embedding_model=args.embedding_model,
        judge_model=args.judge_model,
        workers=args.workers,
        options=dict(args.option),
    )
    try:
        summary = runner.run(
            system,
            dataset,
            run_dir=run_dir,
            users=args.users,
            max_questions=args.max_questions,
            workers=args.workers,
            resume=not args.fresh,
            max_cost=args.max_cost,
            judge=_judge(args.judge_model, needs_judge, args.no_judge),
            config=config,
            system_name=name,
            system_spec=args.system,
            ingest_workers=args.ingest_workers,
            progress=not args.quiet,
            extra_options=dict(args.option),
        )
    except runner.RunConflict as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print(f"\ninterrupted; what was done is in {run_dir} and resumes with --run-id {run_id}", file=sys.stderr)
        return 130
    _print_summary(summary, run_dir)
    return 1 if summary.get("stopped") and "API error" in (summary.get("stopped") or "") else 0


def cmd_score(args: argparse.Namespace) -> int:
    from ledgerbench import runner
    from ledgerbench.dataset import load

    run_dir = Path(args.run_dir)
    dataset = load(args.data) if args.data else None
    judge = _judge(args.judge_model, True, args.no_judge)
    try:
        summary = runner.rescore(run_dir, dataset, judge=judge, rejudge=args.rejudge)
    except (runner.RunConflict, ValueError, FileNotFoundError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(f"re-scored {summary['questions']['answered']} answers, {summary.pop('_changed')} changed")
    _print_summary(summary, run_dir)
    return 0


def cmd_leaderboard(args: argparse.Namespace) -> int:
    from ledgerbench import leaderboard

    text = leaderboard.build(args.results_dir, include_partial=args.include_partial, include_test=args.include_test)
    if args.show:
        print(text)
    print(Path(args.results_dir) / "LEADERBOARD.md")
    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    from ledgerbench.dataset import load

    dataset = load(args.data)
    try:
        user = dataset.user(args.user)
    except KeyError as error:
        print(f"error: {error.args[0]}", file=sys.stderr)
        return 2
    units = ", ".join(f"{k} {v}" for k, v in user.units.items())
    print(f"{user.id} {user.name} | {user.currency} | {units} | tracks {', '.join(user.domains)}")
    print(user.profile)
    print(
        f"{len(user.sessions)} sessions, {user.message_count} messages, {len(user.questions)} questions, {len(user.events)} events"
    )
    if not args.questions_only:
        for session in user.sessions:
            print(f"\n== {session.weekday} {session.date}")
            for i, message in enumerate(session.messages):
                print(f"  [{i}] {message}")
    if args.events:
        print("\n== events")
        for event in user.events:
            fields = json.dumps(event.fields, ensure_ascii=False)
            print(f"  {event.id} {event.type} {event.date} (said {event.session_date} #{event.message}) {fields}")
    if not args.sessions_only:
        print("\n== questions")
        for q in user.questions:
            gold = list(q.gold) if isinstance(q.gold, tuple) else q.gold
            print(f"\n{q.id} [{q.domain}; {', '.join(q.skills)}; {q.answer_type}] asked {q.asked_on}")
            print(f"  Q: {q.question}")
            print(f"  gold: {json.dumps(gold, ensure_ascii=False)}  ({q.gold_text})")
            if q.answer_type == "number":
                print(f"  tolerance: rel {q.rel_tol}, abs {q.abs_tol}, unit {q.unit}")
            if q.choices:
                print(f"  choices: {', '.join(q.choices)}")
            if q.aliases:
                print(f"  aliases: {q.aliases}")
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    handlers = {
        "generate": cmd_generate,
        "run": cmd_run,
        "score": cmd_score,
        "leaderboard": cmd_leaderboard,
        "inspect": cmd_inspect,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
