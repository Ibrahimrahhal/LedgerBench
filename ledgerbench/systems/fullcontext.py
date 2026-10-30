"""
The full-context baseline: every session ingested so far in the prompt, each
headed by its weekday and date, then the question, in one completion.
Ingestion is free. The ceiling on short histories and the yardstick every
memory layer is measured against; it stops fitting once a history outgrows
the model's context window (the `long` size).
"""

from __future__ import annotations

import threading
from typing import Any

from ledgerbench.dataset import QuestionPrompt, Session, UserView
from ledgerbench.systems.base import MemorySystem, Reply, RunConfig, Stopwatch, Usage, answer_messages, session_heading
from ledgerbench.systems.openai_client import OpenAIClient

INTRO = "Here is everything {name} has told you so far, day by day, oldest first:"


def transcript(sessions: list[Session]) -> str:
    return "\n\n".join(f"{session_heading(s)}\n" + "\n".join(f"- {m}" for m in s.messages) for s in sessions)


class FullContext(MemorySystem):
    name = "fullcontext"
    needs_openai = True

    def __init__(self, client: OpenAIClient | None = None, **options: Any) -> None:
        super().__init__(**options)
        self.client = client
        self.sessions: dict[str, list[Session]] = {}
        self.lock = threading.Lock()

    def setup(self, run: RunConfig) -> None:
        super().setup(run)
        if self.client is None:
            self.client = OpenAIClient(answer_model=run.answer_model, embedding_model=run.embedding_model)

    def forget(self, user: UserView) -> None:
        with self.lock:
            self.sessions.pop(user.id, None)

    def restore(self, user: UserView, sessions: list[Session]) -> bool:
        with self.lock:
            self.sessions[user.id] = list(sessions)
        return True

    def ingest(self, user: UserView, session: Session) -> Usage:
        with self.lock:
            self.sessions.setdefault(user.id, []).append(session)
        return Usage()

    def answer(self, user: UserView, question: QuestionPrompt) -> Reply:
        with self.lock:
            sessions = list(self.sessions.get(user.id, []))
        messages = answer_messages(user, question, intro=INTRO, material=transcript(sessions))
        with Stopwatch() as watch:
            completion = self.client.complete(messages)
        return Reply(completion.text, watch.seconds, completion.usage, [])

    def models(self) -> dict[str, str]:
        return {"answer": self.client.answer_model if self.client else ""}

    def notes(self) -> str:
        return "Every session in the prompt, oldest first, each headed by its weekday and date; one completion per question; no ingestion cost."
