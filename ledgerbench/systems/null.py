"""The null system: always "I don't know". A test system that must score 0%."""

from __future__ import annotations

from ledgerbench.dataset import QuestionPrompt, Session, UserView
from ledgerbench.systems.base import MemorySystem, Reply, Usage

REPLY = "I don't know.\nAnswer: unknown"


class Null(MemorySystem):
    name = "null"

    def ingest(self, user: UserView, session: Session) -> Usage:
        return Usage()

    def restore(self, user: UserView, sessions: list[Session]) -> bool:
        return True

    def answer(self, user: UserView, question: QuestionPrompt) -> Reply:
        return Reply(REPLY)

    def notes(self) -> str:
        return "Test system: always replies that it does not know. Must score 0%."
