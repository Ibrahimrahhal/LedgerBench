"""The OpenAI-backed systems, end to end through the runner, against a fake client."""

from __future__ import annotations

import pytest
from conftest import FakeOpenAI, gold_replier

from ledgerbench import FORMAT_INSTRUCTION, prices, results, runner
from ledgerbench.dataset import QuestionPrompt, Session, UserView
from ledgerbench.systems.base import SYSTEM_PROMPT, RunConfig, Usage, system_class, system_name
from ledgerbench.systems.fullcontext import FullContext
from ledgerbench.systems.mem0 import Mem0, config_for
from ledgerbench.systems.null import Null
from ledgerbench.systems.openai_client import OpenAIClient
from ledgerbench.systems.rag import Rag


def make_client(fake):
    return OpenAIClient(
        answer_model="gpt-5.4-mini", embedding_model="text-embedding-3-small", client=fake, sleep=lambda s: None
    )


def config(tmp_path, **kw):
    return RunConfig(run_id="t1", run_dir=tmp_path / "run", size="tiny", **kw)


def test_fullcontext_end_to_end(tiny, tmp_path):
    fake = FakeOpenAI(gold_replier(tiny))
    system = FullContext(client=make_client(fake))
    summary = runner.run(system, tiny, run_dir=tmp_path / "run", config=config(tmp_path), progress=False)

    assert summary["accuracy"] == 1.0
    assert summary["questions"] == {"selected": 10, "answered": 10, "scored": 10, "unjudged": 0}
    assert summary["cost_usd"]["ingestion"] == 0
    # One completion per question, and every one is priced.
    assert len(fake.chat_calls) == 10
    rows = results.read_jsonl(tmp_path / "run" / "answers.jsonl")
    expected = sum(prices.cost_usd("gpt-5.4-mini", r["usage"]["tokens_in"], r["usage"]["tokens_out"]) for r in rows)
    assert summary["cost_usd"]["answering"] == pytest.approx(expected, abs=1e-6)
    assert all(r["usage"]["by_model"]["gpt-5.4-mini"]["calls"] == 1 for r in rows)

    # The prompt: the shared system line, every session with its weekday and date, today, the question and the format line.
    call = next(c for c in fake.chat_calls if "groceries from 2 March" in c["messages"][-1]["content"])
    assert call["messages"][0] == {"role": "system", "content": SYSTEM_PROMPT}
    content = call["messages"][-1]["content"]
    assert "Monday 2 March 2026 (2026-03-02)" in content and "Thursday 5 March 2026 (2026-03-05)" in content
    assert "- oh the groceries on Monday were 64.20, not 46.20" in content
    assert "Today is Thursday 5 March 2026." in content
    assert content.rstrip().endswith(FORMAT_INSTRUCTION)
    # Each user's prompt holds only that user's sessions.
    tom = next(c for c in fake.chat_calls if "breakfast from 2 March" in c["messages"][-1]["content"])
    assert "groceries at Lidl" not in tom["messages"][-1]["content"]


def test_fullcontext_resume_restores_without_reingesting(tiny, tmp_path):
    fake = FakeOpenAI(gold_replier(tiny))
    runner.run(
        FullContext(client=make_client(fake)),
        tiny,
        run_dir=tmp_path / "run",
        config=config(tmp_path),
        max_questions=2,
        progress=False,
    )
    ingest_lines = len(results.read_jsonl(tmp_path / "run" / "ingest.jsonl"))
    fresh = FakeOpenAI(gold_replier(tiny))
    summary = runner.run(
        FullContext(client=make_client(fresh)), tiny, run_dir=tmp_path / "run", config=config(tmp_path), progress=False
    )
    assert len(results.read_jsonl(tmp_path / "run" / "ingest.jsonl")) == ingest_lines
    assert len(fresh.chat_calls) == 10 - 4  # only the questions not answered before
    assert summary["accuracy"] == 1.0 and summary["questions"]["answered"] == 10


def test_rag_end_to_end(tiny, tmp_path):
    fake = FakeOpenAI(gold_replier(tiny))
    system = Rag(client=make_client(fake), top_k=3)
    summary = runner.run(system, tiny, run_dir=tmp_path / "run", config=config(tmp_path), progress=False)
    assert summary["accuracy"] == 1.0

    # Ingestion is the embeddings: one call per session with messages, priced per token.
    ingest_calls = fake.embed_calls[: len([s for u in tiny.users for s in u.sessions])]
    tokens = sum(len(t.split()) for c in ingest_calls for t in c["input"])
    assert summary["usage"]["ingestion"]["tokens_in"] == tokens
    assert summary["cost_usd"]["ingestion"] == pytest.approx(tokens * 0.02 / 1e6, abs=1e-9)
    assert ingest_calls[0]["input"][0] == "[Monday 2026-03-02] groceries at Lidl, 46.20"

    # Answering embeds the question (without the format line) and pays for it too.
    query_calls = fake.embed_calls[len(ingest_calls) :]
    assert len(query_calls) == 10 and all(FORMAT_INSTRUCTION not in c["input"][0] for c in query_calls)
    rows = results.read_jsonl(tmp_path / "run" / "answers.jsonl")
    assert all(set(r["usage"]["by_model"]) == {"gpt-5.4-mini", "text-embedding-3-small"} for r in rows)
    assert all(r["tools"] == ["embed_search"] for r in rows)

    # The top 3 are shown in date order, with their dates.
    content = next(c for c in fake.chat_calls if "groceries from 2 March" in c["messages"][-1]["content"])["messages"][
        -1
    ]["content"]
    shown = [line for line in content.splitlines() if line.startswith("- [")]
    assert len(shown) == 3 and shown == sorted(shown, key=lambda line: line[3:20])


def test_rag_restore_skips_embedding(tiny, tmp_path):
    fake = FakeOpenAI(gold_replier(tiny))
    runner.run(
        Rag(client=make_client(fake)),
        tiny,
        run_dir=tmp_path / "run",
        config=config(tmp_path),
        max_questions=1,
        progress=False,
    )
    fresh = FakeOpenAI(gold_replier(tiny))
    summary = runner.run(
        Rag(client=make_client(fresh)), tiny, run_dir=tmp_path / "run", config=config(tmp_path), progress=False
    )
    assert all(len(c["input"]) == 1 for c in fresh.embed_calls)  # only question embeddings, no sessions
    assert summary["accuracy"] == 1.0


def test_rag_restore_refuses_changed_messages(tiny, tmp_path):
    fake = FakeOpenAI()
    system = Rag(client=make_client(fake))
    system.setup(config(tmp_path))
    user = tiny.users[0]
    for session in user.sessions:
        system.ingest(user.view(), session)
    other = Rag(client=make_client(fake))
    other.setup(config(tmp_path))
    assert other.restore(user.view(), list(user.sessions))
    edited = [Session(s.date, s.weekday, tuple(m + "!" for m in s.messages)) for s in user.sessions]
    assert not other.restore(user.view(), edited)


class FakeMemory:
    def __init__(self):
        self.added = []
        self.deleted = []

    def add(self, messages, *, user_id, metadata, prompt):
        self.added.append((user_id, messages, metadata, prompt))

    def delete_all(self, user_id):
        self.deleted.append(user_id)
        self.added = [a for a in self.added if a[0] != user_id]

    def search(self, query, *, filters, top_k):
        rows = [a for a in self.added if a[0] == filters["user_id"]][:top_k]
        return {"results": [{"memory": m[0]["content"], "metadata": md} for _, m, md, _ in rows]}


def test_mem0_adds_each_message_with_its_date(tiny, tmp_path):
    fake = FakeOpenAI(gold_replier(tiny))
    memory = FakeMemory()
    system = Mem0(client=make_client(fake), memory=memory, top_k=30)
    summary = runner.run(system, tiny, run_dir=tmp_path / "run", config=config(tmp_path), progress=False)
    assert summary["accuracy"] == 1.0
    assert memory.deleted == ["u1", "u2"]  # cleared before ingesting from the start
    assert len(memory.added) == sum(u.message_count for u in tiny.users)
    user_id, messages, metadata, prompt = memory.added[0]
    assert user_id == "u1" and messages == [{"role": "user", "content": "[Monday 2026-03-02] groceries at Lidl, 46.20"}]
    assert metadata == {"session_date": "2026-03-02", "weekday": "Monday"}
    assert "Monday 2026-03-02" in prompt and "Observation Date" in prompt
    content = fake.chat_calls[0]["messages"][-1]["content"]
    assert "(from Monday 2026-03-02)" in content


def test_mem0_config_follows_the_run(tmp_path):
    run = RunConfig(run_id="r1", run_dir=tmp_path, answer_model="gpt-6-luna", embedding_model="text-embedding-3-large")
    cfg = config_for(run, collection="c", history_db="h.db", qdrant_url="http://q")
    assert cfg["llm"]["config"] == {"model": "gpt-6-luna", "is_reasoning_model": True}
    assert cfg["embedder"]["config"] == {"model": "text-embedding-3-large", "embedding_dims": 3072}
    assert cfg["vector_store"]["config"]["embedding_model_dims"] == 3072
    mini = config_for(
        RunConfig(run_id="r1", run_dir=tmp_path), collection="c", history_db="h.db", qdrant_url="http://q"
    )
    assert mini["llm"]["config"] == {"model": "gpt-5.4-mini"}


def test_mem0_meter_counts_sdk_calls_on_the_tracking_thread():
    """mem0 makes its own OpenAI clients; the meter sees their calls through the SDK."""
    httpx = pytest.importorskip("httpx")
    openai = pytest.importorskip("openai")
    from ledgerbench.systems.mem0 import METER

    def handler(request):
        if request.url.path.endswith("/embeddings"):
            body = {
                "object": "list",
                "model": "text-embedding-3-small",
                "data": [{"object": "embedding", "index": 0, "embedding": [0.1, 0.2]}],
                "usage": {"prompt_tokens": 5, "total_tokens": 5},
            }
        else:
            body = {
                "id": "x", "object": "chat.completion", "created": 0, "model": "gpt-5.4-mini",
                "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "{}"}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110, "prompt_tokens_details": {"cached_tokens": 40}},
            }  # fmt: skip
        return httpx.Response(200, json=body)

    METER.install()
    client = openai.OpenAI(
        api_key="test",
        base_url="http://fake.local/v1",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    client.chat.completions.create(model="gpt-5.4-mini", messages=[{"role": "user", "content": "hi"}])  # not tracked
    with METER.track() as usage:
        client.chat.completions.create(model="gpt-5.4-mini", messages=[{"role": "user", "content": "hi"}])
        client.embeddings.create(model="text-embedding-3-small", input=["hi"])
    assert usage.calls == 2 and usage.tokens_in == 105 and usage.cached_in == 40 and usage.tokens_out == 10
    assert usage.cost_usd == pytest.approx(
        prices.cost_usd("gpt-5.4-mini", 100, 10, 40) + prices.cost_usd("text-embedding-3-small", 5)
    )


def test_systems_never_get_the_truth(tiny):
    view = tiny.users[0].view()
    assert isinstance(view, UserView)
    assert not hasattr(view, "events") and not hasattr(view, "questions")
    prompt = tiny.users[0].questions[0].prompt()
    assert isinstance(prompt, QuestionPrompt)
    assert set(prompt.__dataclass_fields__) == {"id", "text", "asked_on"}
    assert prompt.text.endswith(FORMAT_INSTRUCTION)


def test_registry():
    assert system_class("null") is Null
    assert system_class("ledgerbench.systems.null:Null") is Null
    assert system_name("ledgerbench.systems.null:Null", Null) == "null"
    with pytest.raises(ValueError):
        system_class("nope")
    with pytest.raises(TypeError):
        system_class("ledgerbench.systems.base:Usage")


def test_oracle_needs_privilege(tiny):
    with pytest.raises(ValueError):
        system_class("oracle")()
    system, name = runner.make_system("oracle", tiny)
    assert name == "oracle" and system.privileged and len(system.gold) == 10


def test_usage_add_and_roundtrip():
    a = Usage().record("gpt-5.4-mini", 100, 10, 20)
    b = Usage().record("text-embedding-3-small", 50)
    total = a + b
    assert total.calls == 2 and total.tokens_in == 150
    assert Usage.from_dict(total.to_dict()).to_dict() == total.to_dict()
