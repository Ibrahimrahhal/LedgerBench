"""
Mem0, the open-source `mem0ai` library (pinned to 2.2.1), on OpenAI and Qdrant.

Ported from the harness that ran Mem0 on LoCoMo and an earlier ledger
benchmark, keeping what it learned:

- One mem0 `user_id` per user, in a Qdrant collection named after the run, so
  runs never share memories and a resumed run finds its own. `forget` clears a
  user with `delete_all(user_id=...)` before ingesting it from the start.
- Every message is added as a `user` turn with its session's weekday and date
  written into the text. mem0's open-source `add()` refuses the platform's
  `timestamp`, so the session date also goes in as `add(prompt=...)`, the
  documented per-call instruction, telling the extractor to resolve
  "yesterday" against that date rather than against the real today.
- mem0 makes its own OpenAI clients and reports no usage, so every chat and
  embedding call made while a session is ingested or a question searched is
  metered by patching the OpenAI SDK's classes (`UsageMeter`), per thread.
- Adds are retried with backoff on anything transient; "no credits remaining"
  (a 429 that looks like a rate limit) stops the run at once.
- At question time `search(top_k=30)` and the shared answer prompt, with each
  memory listed with the date it came from.

Needs Qdrant: `docker run -d -p 6333:6333 qdrant/qdrant`, or set
LEDGERBENCH_QDRANT_URL.
"""

from __future__ import annotations

import logging
import os
import random
import re
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from ledgerbench import FORMAT_INSTRUCTION, prices
from ledgerbench.dataset import QuestionPrompt, Session, UserView
from ledgerbench.systems.base import MemorySystem, Reply, RunConfig, Stopwatch, Usage, answer_messages
from ledgerbench.systems.openai_client import FatalAPIError, OpenAIClient, is_fatal

log = logging.getLogger("ledgerbench.systems.mem0")

TOP_K = 30
INTRO = (
    "Here are the memories stored about {name} that are most relevant to the question, each with the day it came from:"
)
EMBEDDING_DIMS = {"text-embedding-3-small": 1536, "text-embedding-3-large": 3072, "text-embedding-ada-002": 1536}

# mem0 phones home by default; a benchmark does not.
os.environ.setdefault("MEM0_TELEMETRY", "False")


# ------------------------------------------------------------------- usage meter


class UsageMeter:
    """
    Tallies every OpenAI chat completion and embedding made on a thread while
    `track()` is open on it, by patching the SDK's resource classes once.
    """

    def __init__(self) -> None:
        self._local = threading.local()
        self._installed = False
        self._lock = threading.Lock()

    @contextmanager
    def track(self) -> Iterator[Usage]:
        usage = Usage()
        previous = getattr(self._local, "usage", None)
        self._local.usage = usage
        try:
            yield usage
        finally:
            self._local.usage = previous

    def _record(self, model: str, tokens_in: int, tokens_out: int, cached: int) -> None:
        usage = getattr(self._local, "usage", None)
        if usage is not None:
            usage.record(model, tokens_in, tokens_out, cached)

    def install(self) -> None:
        with self._lock:
            if self._installed:
                return
            from openai.resources import embeddings as embeddings_module
            from openai.resources.chat import completions as chat_completions

            meter = self
            original_chat = chat_completions.Completions.create
            original_embed = embeddings_module.Embeddings.create

            def chat_create(self_: Any, *args: Any, **kwargs: Any) -> Any:
                response = original_chat(self_, *args, **kwargs)
                try:
                    tokens_in, tokens_out, cached = prices.usage_of(response)
                    meter._record(kwargs.get("model") or getattr(response, "model", "?"), tokens_in, tokens_out, cached)
                except Exception:  # noqa: BLE001 - metering must never break a call
                    pass
                return response

            def embed_create(self_: Any, *args: Any, **kwargs: Any) -> Any:
                response = original_embed(self_, *args, **kwargs)
                try:
                    usage = getattr(response, "usage", None)
                    tokens = int(getattr(usage, "prompt_tokens", 0) or getattr(usage, "total_tokens", 0) or 0)
                    meter._record(kwargs.get("model") or getattr(response, "model", "?"), tokens, 0, 0)
                except Exception:  # noqa: BLE001
                    pass
                return response

            chat_completions.Completions.create = chat_create
            embeddings_module.Embeddings.create = embed_create
            self._installed = True


METER = UsageMeter()


# ------------------------------------------------------------------------ config


def _reasoning_flag(model: str) -> bool | None:
    """
    mem0 sends temperature, top_p and max_tokens unless it takes the model for a
    reasoning model. Its own guess is right for the gpt-5 family (which ran fine
    with mem0's defaults); newer families are told explicitly, which only drops
    those parameters.
    """
    base = model.lower().rsplit("/", 1)[-1]
    if base.startswith(("gpt-5", "gpt-4", "gpt-3.5")):
        return None
    return True


def config_for(run: RunConfig, *, collection: str, history_db: str, qdrant_url: str) -> dict[str, Any]:
    dims = EMBEDDING_DIMS.get(run.embedding_model, 1536)
    llm: dict[str, Any] = {"model": run.answer_model}
    flag = _reasoning_flag(run.answer_model)
    if flag is not None:
        llm["is_reasoning_model"] = flag
    return {
        "version": "v1.1",
        "llm": {"provider": "openai", "config": llm},
        "embedder": {"provider": "openai", "config": {"model": run.embedding_model, "embedding_dims": dims}},
        "vector_store": {
            "provider": "qdrant",
            "config": {"collection_name": collection, "url": qdrant_url, "embedding_model_dims": dims},
        },
        "history_db_path": history_db,
    }


def collection_name(run: RunConfig) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", f"ledgerbench_{run.size}_{run.run_id}")[:120]


# ------------------------------------------------------------------------ system


class Mem0(MemorySystem):
    name = "mem0"
    needs_openai = True

    def __init__(
        self,
        client: OpenAIClient | None = None,
        *,
        top_k: int = TOP_K,
        qdrant_url: str | None = None,
        memory: Any = None,
        **options: Any,
    ) -> None:
        super().__init__(**options)
        self.client = client
        self.top_k = int(top_k)
        self.qdrant_url = qdrant_url or os.environ.get("LEDGERBENCH_QDRANT_URL", "http://localhost:6333")
        self.memory = memory  # tests pass a stand-in
        self.version = "?"
        self.collection = ""

    def setup(self, run: RunConfig) -> None:
        super().setup(run)
        if self.client is None:
            self.client = OpenAIClient(answer_model=run.answer_model, embedding_model=run.embedding_model)
        self.collection = collection_name(run)
        if self.memory is None:
            try:
                import mem0
                from mem0 import Memory
            except ImportError as error:  # pragma: no cover - depends on the install
                raise RuntimeError("mem0ai is not installed: pip install 'ledgerbench[mem0]'") from error
            self.version = getattr(mem0, "__version__", "?")
            _require_spacy(self.options)
            history_db = str(run.state_dir("mem0") / "history.db")
            self.memory = Memory.from_config(
                config_for(run, collection=self.collection, history_db=history_db, qdrant_url=self.qdrant_url)
            )
            METER.install()
        log.info("mem0 %s, collection %s, qdrant %s", self.version, self.collection, self.qdrant_url)

    @staticmethod
    def user_id(user: UserView) -> str:
        return user.id

    def _retry(self, what: str, call, attempts: int = 6) -> Any:
        for attempt in range(attempts):
            try:
                return call()
            except Exception as error:  # noqa: BLE001 - mem0 wraps the API's errors; classified here
                if is_fatal(error) or is_fatal(error.__cause__ or error):
                    raise FatalAPIError(f"{what}: {type(error).__name__}: {str(error)[:160]}") from error
                if attempt == attempts - 1:
                    raise
                wait = min(3 * (2**attempt), 60) + random.uniform(0, 1)
                log.warning("%s failed (%s: %s); retrying in %.0fs", what, type(error).__name__, str(error)[:120], wait)
                time.sleep(wait)
        raise AssertionError("unreachable")  # pragma: no cover

    # ---------------------------------------------------------------- ingestion

    def forget(self, user: UserView) -> None:
        uid = self.user_id(user)
        self._retry(f"{uid}: delete_all", lambda: self.memory.delete_all(user_id=uid))

    def restore(self, user: UserView, sessions: list[Session]) -> bool:
        return True  # the memories live in this run's Qdrant collection

    def ingest(self, user: UserView, session: Session) -> Usage:
        uid = self.user_id(user)
        when = f"{session.weekday} {session.date}"
        instruction = (
            f"These messages were written on {when}. Treat that as the Observation Date: resolve relative time "
            "references in them against it, not against the Current Date."
        )
        with METER.track() as usage:
            for message in session.messages:
                messages = [{"role": "user", "content": f"[{when}] {message}"}]
                metadata = {"session_date": session.date, "weekday": session.weekday}
                self._retry(
                    f"{uid}: add",
                    lambda m=messages, md=metadata: self.memory.add(
                        m, user_id=uid, metadata=dict(md), prompt=instruction
                    ),
                )
        return usage

    # ---------------------------------------------------------------- answering

    def search(self, user: UserView, query: str) -> list[dict[str, Any]]:
        uid = self.user_id(user)
        found = self._retry(
            f"{uid}: search", lambda: self.memory.search(query, filters={"user_id": uid}, top_k=self.top_k)
        )
        return found.get("results", []) if isinstance(found, dict) else list(found or [])

    def answer(self, user: UserView, question: QuestionPrompt) -> Reply:
        query = question.text.replace(FORMAT_INSTRUCTION, "").strip()
        with Stopwatch() as watch:
            with METER.track() as usage:
                memories = self.search(user, query)
            lines = []
            for m in memories:
                meta = m.get("metadata") or {}
                day = f"{meta.get('weekday', '')} {meta.get('session_date', '')}".strip() or "unknown"
                lines.append(f"- {m.get('memory', '')} (from {day})")
            completion = self.client.complete(
                answer_messages(user, question, intro=INTRO, material="\n".join(lines)), usage=usage
            )
        return Reply(completion.text, watch.seconds, usage, ["mem0_search"])

    def models(self) -> dict[str, str]:
        run = self.run
        return {
            "answer": self.client.answer_model if self.client else "",
            "mem0_llm": run.answer_model if run else "",
            "embedding": run.embedding_model if run else "",
            "mem0ai": self.version,
        }

    def notes(self) -> str:
        return (
            f"mem0ai {self.version} Memory.from_config: OpenAI llm (the run's answer model, mem0's own sampling defaults), "
            f"OpenAI embedder (the run's embedding model), Qdrant collection {self.collection}. One user_id per user; each message "
            "added on its own as a 'user' turn with '[weekday date]' in the text, metadata session_date and weekday, infer=True, "
            "and the session date passed as add(prompt=...) so the extractor resolves relative dates against it. "
            f"Answering: search(top_k={self.top_k}) on the question's text, memories listed with their day, the shared answer prompt. "
            "Ingestion and search usage metered by patching the OpenAI SDK."
        )


def _require_spacy(options: dict[str, Any]) -> None:
    """
    Mem0's hybrid search needs two optional packages, and without either it
    only logs a warning and runs degraded, which would understate it: spaCy
    (lemmatization for BM25 and entity extraction) and fastembed (the BM25
    encoder its Qdrant store uses; without it keyword search is off). The run
    refuses to start without them unless told `--option allow_degraded=true`.
    """
    if str(options.get("allow_degraded", "")).lower() in ("1", "true", "yes"):
        return
    try:
        import spacy

        spacy.load("en_core_web_sm", disable=["ner", "parser"])
    except Exception as error:  # noqa: BLE001 - any failure here means the same thing
        raise RuntimeError(
            "mem0 needs spaCy and its English model for full-strength search: "
            "pip install 'ledgerbench[mem0]' && python -m spacy download en_core_web_sm "
            "(or pass --option allow_degraded=true to run without them, and say so)"
        ) from error
    try:
        from fastembed import SparseTextEmbedding  # noqa: F401
    except Exception as error:  # noqa: BLE001
        raise RuntimeError(
            "mem0 needs fastembed for its BM25 keyword search: pip install 'ledgerbench[mem0]' "
            "(or pass --option allow_degraded=true to run without it, and say so)"
        ) from error
