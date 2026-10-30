"""
The naive RAG baseline: one chunk per message, prefixed with its session's
weekday and date, embedded with the run's embedding model (text-embedding-3-small
by default). A question embeds its own text, takes the top 20 chunks by
cosine and shows them in date order with their dates, then asks the answer
model once. Ingestion cost is the embeddings.

Vectors are kept under the run's state directory, so a resumed run restores a
user without paying for the embeddings again.
"""

from __future__ import annotations

import json
import threading
from typing import Any

from ledgerbench import FORMAT_INSTRUCTION
from ledgerbench.dataset import QuestionPrompt, Session, UserView
from ledgerbench.systems.base import MemorySystem, Reply, RunConfig, Stopwatch, Usage, answer_messages
from ledgerbench.systems.openai_client import OpenAIClient

TOP_K = 20
INTRO = "Here are the messages from {name} most relevant to the question, oldest first, each with the day it was sent:"


def chunk_text(session: Session, message: str) -> str:
    return f"[{session.weekday} {session.date}] {message}"


class _Index:
    def __init__(self) -> None:
        self.chunks: list[str] = []
        self.order: list[tuple[int, int]] = []  # (session index, message index), for date order
        self.vectors: list[Any] = []  # unit vectors, one numpy array per session


class Rag(MemorySystem):
    name = "rag"
    needs_openai = True

    def __init__(self, client: OpenAIClient | None = None, *, top_k: int = TOP_K, **options: Any) -> None:
        super().__init__(**options)
        self.client = client
        self.top_k = int(top_k)
        self.indexes: dict[str, _Index] = {}
        self.lock = threading.Lock()

    def setup(self, run: RunConfig) -> None:
        super().setup(run)
        import numpy  # noqa: F401 - fail early if the openai extra is missing

        if self.client is None:
            self.client = OpenAIClient(answer_model=run.answer_model, embedding_model=run.embedding_model)
        self.store = run.state_dir("rag")

    # ------------------------------------------------------------------ storage

    def _paths(self, user_id: str):
        return self.store / f"{user_id}.npy", self.store / f"{user_id}.json"

    def _save(self, user_id: str, index: _Index) -> None:
        import numpy as np

        vectors_path, meta_path = self._paths(user_id)
        matrix = np.concatenate(index.vectors) if index.vectors else np.zeros((0, 0), dtype=np.float32)
        with vectors_path.open("wb") as f:
            np.save(f, matrix)
        meta = {"model": self.client.embedding_model, "chunks": index.chunks, "order": index.order}
        meta_path.write_bytes(json.dumps(meta, ensure_ascii=False).encode("utf-8"))

    def forget(self, user: UserView) -> None:
        with self.lock:
            self.indexes.pop(user.id, None)
        for path in self._paths(user.id):
            if path.exists():
                path.unlink()

    def restore(self, user: UserView, sessions: list[Session]) -> bool:
        import numpy as np

        vectors_path, meta_path = self._paths(user.id)
        if not (vectors_path.exists() and meta_path.exists()):
            return False
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        expected = [chunk_text(s, m) for s in sessions for m in s.messages]
        if meta.get("chunks") != expected or meta.get("model") != self.client.embedding_model:
            return False
        index = _Index()
        index.chunks = list(meta["chunks"])
        index.order = [tuple(o) for o in meta["order"]]
        index.vectors = [np.load(vectors_path)]
        with self.lock:
            self.indexes[user.id] = index
        return True

    # ---------------------------------------------------------------- ingestion

    def ingest(self, user: UserView, session: Session) -> Usage:
        import numpy as np

        with self.lock:
            index = self.indexes.setdefault(user.id, _Index())
            session_number = len({o[0] for o in index.order})
        if not session.messages:
            return Usage()
        chunks = [chunk_text(session, m) for m in session.messages]
        vectors, usage = self.client.embed(chunks)
        matrix = np.asarray(vectors, dtype=np.float32)
        matrix /= np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-12)
        with self.lock:
            index.chunks.extend(chunks)
            index.order.extend((session_number, i) for i in range(len(chunks)))
            index.vectors.append(matrix)
            self._save(user.id, index)
        return usage

    # ---------------------------------------------------------------- answering

    def retrieve(self, user: UserView, query: str, usage: Usage) -> list[str]:
        import numpy as np

        with self.lock:
            index = self.indexes.get(user.id)
            if index is None or not index.chunks:
                return []
            matrix = np.concatenate(index.vectors)
            chunks = list(index.chunks)
            order = list(index.order)
        vectors, _ = self.client.embed([query], usage=usage)
        q = np.asarray(vectors[0], dtype=np.float32)
        q /= max(float(np.linalg.norm(q)), 1e-12)
        scores = matrix @ q
        top = np.argsort(-scores, kind="stable")[: self.top_k]
        return [chunks[i] for i in sorted(top.tolist(), key=lambda i: order[i])]

    def answer(self, user: UserView, question: QuestionPrompt) -> Reply:
        usage = Usage()
        query = question.text.replace(FORMAT_INSTRUCTION, "").strip()
        with Stopwatch() as watch:
            hits = self.retrieve(user, query, usage)
            material = "\n".join(f"- {h}" for h in hits)
            completion = self.client.complete(
                answer_messages(user, question, intro=INTRO, material=material), usage=usage
            )
        return Reply(completion.text, watch.seconds, usage, ["embed_search"])

    def models(self) -> dict[str, str]:
        return {"answer": self.client.answer_model, "embedding": self.client.embedding_model} if self.client else {}

    def notes(self) -> str:
        return (
            f"One chunk per message, '[weekday date] message', embedded with the run's embedding model; top {self.top_k} by cosine "
            "on the question's text (without the format instruction), shown in date order; one completion per question. "
            "Ingestion cost is the embeddings."
        )
