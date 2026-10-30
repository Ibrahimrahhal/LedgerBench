"""
The interface every memory system implements (spec section 9), the usage and
reply records, the one answer prompt every non-oracle system shares, and the
registry that turns a name or an import path into a system.

A system sees a `UserView` (no events, no questions), the user's `Session`s in
date order, and for each question a `QuestionPrompt` (id, text with the format
instruction, asked_on). Nothing else.
"""

from __future__ import annotations

import importlib
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ledgerbench import prices
from ledgerbench.dataset import QuestionPrompt, Session, UserView, long_date

DEFAULT_ANSWER_MODEL = "gpt-5.4-mini"
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_JUDGE_MODEL = "gpt-5.4-mini"


# ---------------------------------------------------------------------- records


@dataclass
class Usage:
    """Tokens and cost, in total and by model. `tokens_in` includes `cached_in`."""

    tokens_in: int = 0
    cached_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    calls: int = 0
    by_model: dict[str, dict[str, Any]] = field(default_factory=dict)

    def record(
        self, model: str, tokens_in: int = 0, tokens_out: int = 0, cached_in: int = 0, cost_usd: float | None = None
    ) -> Usage:
        cost = prices.cost_usd(model, tokens_in, tokens_out, cached_in) if cost_usd is None else cost_usd
        bucket = self.by_model.setdefault(
            model, {"calls": 0, "tokens_in": 0, "cached_in": 0, "tokens_out": 0, "cost_usd": 0.0}
        )
        bucket["calls"] += 1
        bucket["tokens_in"] += tokens_in
        bucket["cached_in"] += cached_in
        bucket["tokens_out"] += tokens_out
        bucket["cost_usd"] += cost
        self.calls += 1
        self.tokens_in += tokens_in
        self.cached_in += cached_in
        self.tokens_out += tokens_out
        self.cost_usd += cost
        return self

    def add(self, other: Usage | None) -> Usage:
        if other is None:
            return self
        self.tokens_in += other.tokens_in
        self.cached_in += other.cached_in
        self.tokens_out += other.tokens_out
        self.cost_usd += other.cost_usd
        self.calls += other.calls
        for model, theirs in other.by_model.items():
            bucket = self.by_model.setdefault(
                model, {"calls": 0, "tokens_in": 0, "cached_in": 0, "tokens_out": 0, "cost_usd": 0.0}
            )
            for key in bucket:
                bucket[key] += theirs.get(key, 0)
        return self

    def __add__(self, other: Usage) -> Usage:
        return Usage().add(self).add(other)

    @property
    def unpriced_models(self) -> list[str]:
        return sorted(
            m for m, b in self.by_model.items() if not prices.known(m) and (b.get("tokens_in") or b.get("tokens_out"))
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "tokens_in": self.tokens_in,
            "cached_in": self.cached_in,
            "tokens_out": self.tokens_out,
            "cost_usd": round(self.cost_usd, 8),
            "calls": self.calls,
            "by_model": {m: {**b, "cost_usd": round(b["cost_usd"], 8)} for m, b in sorted(self.by_model.items())},
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> Usage:
        raw = raw or {}
        return cls(
            tokens_in=int(raw.get("tokens_in", 0)),
            cached_in=int(raw.get("cached_in", 0)),
            tokens_out=int(raw.get("tokens_out", 0)),
            cost_usd=float(raw.get("cost_usd", 0.0)),
            calls=int(raw.get("calls", 0)),
            by_model={m: dict(b) for m, b in (raw.get("by_model") or {}).items()},
        )

    @classmethod
    def total(cls, usages: Iterable[Usage | None]) -> Usage:
        out = cls()
        for usage in usages:
            out.add(usage)
        return out


@dataclass
class Reply:
    text: str
    latency_s: float = 0.0
    usage: Usage = field(default_factory=Usage)
    tools: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RunConfig:
    """What a system is told about the run it is part of."""

    run_id: str
    run_dir: Path
    size: str = "custom"
    answer_model: str = DEFAULT_ANSWER_MODEL
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    judge_model: str = DEFAULT_JUDGE_MODEL
    workers: int = 4
    options: dict[str, Any] = field(default_factory=dict, hash=False, compare=False)

    def state_dir(self, system: str) -> Path:
        """A directory a system may keep its own state in, so a resumed run can restore it."""
        path = Path(self.run_dir) / "state" / system
        path.mkdir(parents=True, exist_ok=True)
        return path


# ------------------------------------------------------------------- the system


class MemorySystem:
    """
    Subclass this. `ingest` is called once per session, in date order, per
    user; `answer` once per question, possibly from several threads at once,
    and must not carry anything from one question to the next.

    Two optional hooks make runs resumable: `forget(user)` drops whatever the
    system stored for a user (called before a user is ingested from the start),
    and `restore(user, sessions)` brings back a user whose ingestion finished in
    an earlier process, returning False if it cannot (the runner then ingests
    the user again).
    """

    name: str = "base"
    #: True only for test systems that are handed the gold answers (the oracle).
    privileged: bool = False
    #: True when the system calls the OpenAI API and needs OPENAI_API_KEY.
    needs_openai: bool = False

    def __init__(self, **options: Any) -> None:
        self.options = options
        self.run: RunConfig | None = None

    def setup(self, run: RunConfig) -> None:
        self.run = run

    def ingest(self, user: UserView, session: Session) -> Usage:
        raise NotImplementedError

    def answer(self, user: UserView, question: QuestionPrompt) -> Reply:
        raise NotImplementedError

    def teardown(self) -> None:
        pass

    def forget(self, user: UserView) -> None:
        pass

    def restore(self, user: UserView, sessions: list[Session]) -> bool:
        return False

    def models(self) -> dict[str, str]:
        """The models this system used, for the summary: {"answer": ..., "embedding": ...}."""
        return {}

    def notes(self) -> str:
        """One paragraph on how the system was configured, for the summary."""
        return ""


# ------------------------------------------------------------- the answer prompt

SYSTEM_PROMPT = (
    "You answer questions about the user's own logged records (spending, food, training and body readings) "
    "from what they told you, and you compute totals, counts and averages carefully."
)

ANSWER_TEMPLATE = """{intro}

{material}

Today is {today}.

{question}"""


def answer_messages(user: UserView, question: QuestionPrompt, *, intro: str, material: str) -> list[dict[str, str]]:
    """The chat messages every non-oracle system answers with: the material, then the question."""
    content = ANSWER_TEMPLATE.format(
        intro=intro.format(name=user.name),
        material=material.strip() or "(nothing)",
        today=long_date(question.asked_on),
        question=question.text,
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": content}]


def session_heading(session: Session) -> str:
    """'Monday 5 January 2026 (2026-01-05)'."""
    return f"{long_date(session.date)} ({session.date})"


# --------------------------------------------------------------------- timing

_LOST = threading.local()


def add_lost_seconds(seconds: float) -> None:
    """Called by the API client for time spent on failed attempts and backoff, which latency leaves out."""
    _LOST.seconds = getattr(_LOST, "seconds", 0.0) + seconds


class Stopwatch:
    """Wall-clock seconds on this thread, minus the time the API client spent retrying."""

    def __enter__(self) -> Stopwatch:
        self._start = time.perf_counter()
        self._lost = getattr(_LOST, "seconds", 0.0)
        self.seconds = 0.0
        return self

    def __exit__(self, *exc: object) -> None:
        lost = getattr(_LOST, "seconds", 0.0) - self._lost
        self.seconds = max(time.perf_counter() - self._start - lost, 0.0)


# -------------------------------------------------------------------- registry

BUILTIN: dict[str, str] = {
    "fullcontext": "ledgerbench.systems.fullcontext:FullContext",
    "rag": "ledgerbench.systems.rag:Rag",
    "mem0": "ledgerbench.systems.mem0:Mem0",
    "oracle": "ledgerbench.systems.oracle:Oracle",
    "null": "ledgerbench.systems.null:Null",
}


def system_class(name: str) -> type[MemorySystem]:
    """A built-in name, or "package.module:Class" for a system in its own package."""
    path = BUILTIN.get(name, name)
    if ":" not in path:
        raise ValueError(
            f"unknown system {name!r}: use one of {', '.join(BUILTIN)} or an import path like mypkg.module:MySystem"
        )
    module_name, _, attr = path.partition(":")
    module = importlib.import_module(module_name)
    cls = getattr(module, attr, None)
    if cls is None:
        raise ValueError(f"{module_name} has no attribute {attr!r}")
    if not (isinstance(cls, type) and issubclass(cls, MemorySystem)):
        raise TypeError(f"{path} is not a subclass of ledgerbench.systems.base.MemorySystem")
    return cls


def system_name(name: str, cls: type[MemorySystem]) -> str:
    """The name results are filed under: the built-in name, or the class's `name` (falling back to the import path)."""
    if name in BUILTIN:
        return name
    own = getattr(cls, "name", "base")
    return own if own and own != "base" else name.replace(":", ".")
