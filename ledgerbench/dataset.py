"""
The dataset file (spec section 7), loaded into frozen dataclasses.

Two kinds of object come out of here. `Dataset`, `User`, `Question` and
`Event` carry the truth (gold answers, events, derivations) and are for the
runner, the scorer and reviewers. `UserView`, `Session` and `QuestionPrompt`
are all a system is ever handed: a `UserView` has no events and no questions,
and a `QuestionPrompt` has no gold, so a system cannot reach the truth by
accident.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from ledgerbench import FORMAT_INSTRUCTION

ANSWER_TYPES = ("number", "count", "date", "category", "set", "text")
DOMAINS = ("spending", "food", "training", "body", "cross")


def long_date(iso: str) -> str:
    """'2026-03-12' -> 'Thursday 12 March 2026'."""
    d = date.fromisoformat(iso)
    return f"{d.strftime('%A')} {d.day} {d.strftime('%B')} {d.year}"


@dataclass(frozen=True)
class Session:
    """One calendar day of messages, as a system sees it."""

    date: str
    weekday: str
    messages: tuple[str, ...]

    @property
    def long_date(self) -> str:
        return long_date(self.date)


@dataclass(frozen=True)
class Event:
    """One structured fact. `fields` holds everything beyond the common keys (amount, category, items...)."""

    id: str
    type: str
    date: str
    session_date: str
    message: int | None
    fields: dict[str, Any] = field(default_factory=dict, hash=False, compare=False)

    def get(self, key: str, default: Any = None) -> Any:
        return self.fields.get(key, default)


@dataclass(frozen=True)
class QuestionPrompt:
    """What a system is asked: the question with the format instruction appended, and the day it is asked on."""

    id: str
    text: str
    asked_on: str


@dataclass(frozen=True)
class Question:
    id: str
    domain: str
    skills: tuple[str, ...]
    question: str
    answer_type: str
    gold: Any
    gold_text: str
    asked_on: str
    unit: str | None = None
    rel_tol: float = 0.01
    abs_tol: float = 0.0
    # A list of strings for `category`. For `set`, per member: a dict {member: [aliases]} or a
    # list of lists parallel to `gold`.
    aliases: Any = ()
    choices: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    derivation: dict[str, Any] = field(default_factory=dict, hash=False, compare=False)

    @property
    def user_id(self) -> str:
        return self.id.split(":", 1)[0]

    def prompt(self) -> QuestionPrompt:
        return QuestionPrompt(id=self.id, text=f"{self.question}\n\n{FORMAT_INSTRUCTION}", asked_on=self.asked_on)

    def aliases_for(self, member: Any) -> tuple[str, ...]:
        """The accepted alternative spellings of one gold value."""
        aliases = self.aliases
        if not aliases:
            return ()
        if isinstance(aliases, dict):
            found = aliases.get(member)
            if found is None:
                lowered = {str(k).lower(): v for k, v in aliases.items()}
                found = lowered.get(str(member).lower(), ())
            return tuple(str(a) for a in found) if isinstance(found, (list, tuple)) else (str(found),)
        aliases = list(aliases)
        if self.answer_type == "set" and isinstance(self.gold, (list, tuple)):
            if all(isinstance(a, (list, tuple)) for a in aliases):
                gold = list(self.gold)
                index = gold.index(member) if member in gold else -1
                return tuple(str(a) for a in aliases[index]) if 0 <= index < len(aliases) else ()
            return ()  # a flat list of aliases cannot say which member it belongs to
        return tuple(str(a) for a in aliases if not isinstance(a, (list, tuple, dict)))


@dataclass(frozen=True)
class UserView:
    """Who the user is, without anything a system must not see."""

    id: str
    name: str
    profile: str
    currency: str
    units: dict[str, str] = field(default_factory=dict, hash=False, compare=False)
    domains: tuple[str, ...] = ()


@dataclass(frozen=True)
class User:
    id: str
    name: str
    profile: str
    currency: str
    units: dict[str, str]
    domains: tuple[str, ...]
    sessions: tuple[Session, ...]
    questions: tuple[Question, ...]
    events: tuple[Event, ...] = ()

    def view(self) -> UserView:
        return UserView(self.id, self.name, self.profile, self.currency, dict(self.units), self.domains)

    @property
    def message_count(self) -> int:
        return sum(len(s.messages) for s in self.sessions)


@dataclass(frozen=True)
class Dataset:
    name: str
    version: str
    size: str
    seed: int | None
    generated_on: str | None
    users: tuple[User, ...]
    path: str | None = None
    sha256: str | None = None

    def user(self, user_id: str) -> User:
        for user in self.users:
            if user.id == user_id:
                return user
        raise KeyError(f"no user {user_id!r}; the dataset has {', '.join(u.id for u in self.users)}")

    def questions(self) -> list[Question]:
        return [q for u in self.users for q in u.questions]

    def question(self, question_id: str) -> Question:
        for q in self.user(question_id.split(":", 1)[0]).questions:
            if q.id == question_id:
                return q
        raise KeyError(f"no question {question_id!r}")


def _float(value: Any, default: float) -> float:
    return default if value is None else float(value)


def _question(raw: dict[str, Any]) -> Question:
    if raw.get("answer_type") not in ANSWER_TYPES:
        raise ValueError(f"{raw.get('id')}: unknown answer_type {raw.get('answer_type')!r}")
    aliases = raw.get("aliases") or ()
    if isinstance(aliases, list):
        aliases = tuple(tuple(a) if isinstance(a, list) else a for a in aliases)
    gold = raw.get("gold")
    if isinstance(gold, list):
        gold = tuple(gold)
    return Question(
        id=raw["id"],
        domain=raw.get("domain", ""),
        skills=tuple(raw.get("skills") or ()),
        question=raw["question"],
        answer_type=raw["answer_type"],
        gold=gold,
        gold_text=str(raw.get("gold_text", "")),
        asked_on=raw["asked_on"],
        unit=raw.get("unit"),
        rel_tol=_float(raw.get("rel_tol"), 0.01),
        abs_tol=_float(raw.get("abs_tol"), 0.0),
        aliases=aliases,
        choices=tuple(raw.get("choices") or ()),
        evidence=tuple(raw.get("evidence") or ()),
        derivation=dict(raw.get("derivation") or {}),
    )


_EVENT_KEYS = ("id", "type", "date", "session_date", "message")


def _event(raw: dict[str, Any]) -> Event:
    return Event(
        id=raw["id"],
        type=raw["type"],
        date=raw.get("date", ""),
        session_date=raw.get("session_date", ""),
        message=raw.get("message"),
        fields={k: v for k, v in raw.items() if k not in _EVENT_KEYS},
    )


def _session(raw: dict[str, Any]) -> Session:
    weekday = raw.get("weekday") or date.fromisoformat(raw["date"]).strftime("%A")
    return Session(raw["date"], weekday, tuple(raw.get("messages") or ()))


def _user(raw: dict[str, Any]) -> User:
    return User(
        id=raw["id"],
        name=raw.get("name", raw["id"]),
        profile=raw.get("profile", ""),
        currency=raw.get("currency", ""),
        units=dict(raw.get("units") or {}),
        domains=tuple(raw.get("domains") or ()),
        sessions=tuple(_session(s) for s in sorted(raw.get("sessions") or (), key=lambda s: s["date"])),
        questions=tuple(_question(q) for q in raw.get("questions") or ()),
        events=tuple(_event(e) for e in raw.get("events") or ()),
    )


def from_dict(raw: dict[str, Any], *, path: str | None = None, sha256: str | None = None) -> Dataset:
    return Dataset(
        name=raw.get("name", "LedgerBench"),
        version=str(raw.get("version", "")),
        size=raw.get("size", "custom"),
        seed=raw.get("seed"),
        generated_on=raw.get("generated_on"),
        users=tuple(_user(u) for u in raw.get("users") or ()),
        path=path,
        sha256=sha256,
    )


def load(path: str | Path) -> Dataset:
    """Loads a dataset file. The file's SHA-256 is kept so a resumed run can check it is the same data."""
    path = Path(path)
    data = path.read_bytes()
    return from_dict(json.loads(data.decode("utf-8")), path=str(path), sha256=hashlib.sha256(data).hexdigest())
