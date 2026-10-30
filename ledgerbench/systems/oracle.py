"""
The oracle: answers every question with its `gold_text`, which the runner
hands it as a privileged constructor argument. It checks the scorer and the
gold phrasing, and must score 100%. It is a test system, never a baseline,
and the leaderboard leaves it out.
"""

from __future__ import annotations

from typing import Any

from ledgerbench.dataset import QuestionPrompt, Session, UserView
from ledgerbench.systems.base import MemorySystem, Reply, Usage


class Oracle(MemorySystem):
    name = "oracle"
    privileged = True

    def __init__(self, gold: dict[str, str] | None = None, **options: Any) -> None:
        super().__init__(**options)
        if gold is None:
            raise ValueError("the oracle needs the gold answers; build it with ledgerbench.runner.make_system")
        self.gold = dict(gold)

    def ingest(self, user: UserView, session: Session) -> Usage:
        return Usage()

    def restore(self, user: UserView, sessions: list[Session]) -> bool:
        return True

    def answer(self, user: UserView, question: QuestionPrompt) -> Reply:
        return Reply(f"Answer: {self.gold[question.id]}")

    def notes(self) -> str:
        return "Test system: replies with each question's gold_text. Must score 100%."
