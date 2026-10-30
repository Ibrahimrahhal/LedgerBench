"""Shared fixtures: the tiny hand-written dataset and a fake OpenAI client that never touches the network."""

from __future__ import annotations

import re
import zlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from ledgerbench.dataset import load

FIXTURES = Path(__file__).parent / "fixtures"
TINY = FIXTURES / "tiny.json"
REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def tiny_path() -> Path:
    return TINY


@pytest.fixture
def tiny():
    return load(TINY)


def fake_vector(text: str, dims: int = 64) -> list[float]:
    """A deterministic bag-of-words embedding: similar words, similar vectors."""
    vector = [0.0] * dims
    for word in re.findall(r"[a-z]+", text.lower()):
        vector[zlib.crc32(word.encode()) % dims] += 1.0
    if not any(vector):
        vector[0] = 1.0
    return vector


class FakeOpenAI:
    """
    Shaped like `openai.OpenAI` for the two calls the wrapper makes. Chat
    replies come from `reply(messages, model, params)`; usage is counted as one
    token per four characters, with `cached` of the prompt tokens reported as
    cached. `errors` is a list of exceptions raised by the next calls, in order.
    """

    def __init__(self, reply=None, *, cached: int = 0, errors=None):
        self.reply = reply or (lambda messages, model, params: "Answer: 42")
        self.cached = cached
        self.errors = list(errors or [])
        self.chat_calls: list[dict] = []
        self.embed_calls: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._chat))
        self.embeddings = SimpleNamespace(create=self._embed)

    def _maybe_fail(self):
        if self.errors:
            raise self.errors.pop(0)

    def _chat(self, *, model, messages, **params):
        self.chat_calls.append({"model": model, "messages": messages, "params": params})
        self._maybe_fail()
        text = self.reply(messages, model, params)
        prompt = sum(len(m["content"]) for m in messages) // 4
        usage = SimpleNamespace(
            prompt_tokens=prompt,
            completion_tokens=len(text) // 4 + 1,
            prompt_tokens_details=SimpleNamespace(cached_tokens=min(self.cached, prompt)),
        )
        return SimpleNamespace(
            model=model, choices=[SimpleNamespace(message=SimpleNamespace(content=text))], usage=usage
        )

    def _embed(self, *, model, input):
        self.embed_calls.append({"model": model, "input": list(input)})
        self._maybe_fail()
        data = [SimpleNamespace(embedding=fake_vector(t)) for t in input]
        tokens = sum(len(t.split()) for t in input)
        return SimpleNamespace(model=model, data=data, usage=SimpleNamespace(prompt_tokens=tokens, total_tokens=tokens))


class APIError(Exception):
    """Looks like an openai status error to the wrapper's classifier."""

    def __init__(self, message: str, status_code: int, code: str | None = None, param: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.param = param


class RateLimitError(APIError):
    pass


@pytest.fixture
def fake_openai():
    return FakeOpenAI


def gold_replier(dataset):
    """A fake model that answers each question in the prompt with its gold text."""
    by_question = {q.question: q.gold_text for q in dataset.questions()}

    def reply(messages, model, params):
        content = messages[-1]["content"]
        for question, gold in by_question.items():
            if question in content:
                return f"Let me add that up.\nAnswer: {gold}"
        return "Answer: unknown"

    return reply
