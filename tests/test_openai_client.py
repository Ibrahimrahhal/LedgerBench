from __future__ import annotations

import os

import pytest
from conftest import APIError, FakeOpenAI, RateLimitError

from ledgerbench import prices
from ledgerbench.systems.base import Stopwatch, Usage
from ledgerbench.systems.openai_client import FatalAPIError, OpenAIClient, is_fatal, is_retryable, load_api_key


def client_with(fake, **kw):
    return OpenAIClient(
        answer_model="gpt-5.4-mini", embedding_model="text-embedding-3-small", client=fake, sleep=lambda s: None, **kw
    )


def test_complete_records_tokens_and_cost():
    fake = FakeOpenAI(lambda m, model, p: "Answer: 7", cached=8)
    usage = Usage()
    completion = client_with(fake).complete([{"role": "user", "content": "x" * 400}], usage=usage)
    assert completion.text == "Answer: 7"
    assert usage.tokens_in == 100 and usage.cached_in == 8 and usage.tokens_out == 3 and usage.calls == 1
    assert usage.cost_usd == pytest.approx(prices.cost_usd("gpt-5.4-mini", 100, 3, 8))
    assert usage.cost_usd == pytest.approx((92 * 0.75 + 8 * 0.075 + 3 * 4.50) / 1e6)
    assert usage.by_model["gpt-5.4-mini"]["calls"] == 1


def test_model_override():
    fake = FakeOpenAI()
    client_with(fake).complete([{"role": "user", "content": "hi"}], model="gpt-6-luna")
    assert fake.chat_calls[0]["model"] == "gpt-6-luna"


def test_retries_rate_limits_then_succeeds():
    waits = []
    fake = FakeOpenAI(errors=[RateLimitError("slow down", 429), APIError("bad gateway", 502)])
    client = OpenAIClient(client=fake, sleep=waits.append)
    assert client.complete([{"role": "user", "content": "hi"}]).text == "Answer: 42"
    assert len(fake.chat_calls) == 3 and len(waits) == 2 and waits[1] > waits[0] - 1


def test_no_credits_is_fatal_and_not_retried():
    error = RateLimitError(
        "Error code: 429 - You have no credits remaining. Add credits to continue", 429, code="insufficient_quota"
    )
    fake = FakeOpenAI(errors=[error])
    with pytest.raises(FatalAPIError):
        client_with(fake).complete([{"role": "user", "content": "hi"}])
    assert len(fake.chat_calls) == 1


@pytest.mark.parametrize(
    ("error", "fatal", "retryable"),
    [
        (RateLimitError("Rate limit reached", 429, code="rate_limit_exceeded"), False, True),
        (RateLimitError("You exceeded your current quota", 429, code="insufficient_quota"), True, False),
        (APIError("Incorrect API key provided", 401), True, False),
        (APIError("The model does not exist", 404), True, False),
        (APIError("server error", 500), False, True),
        (APIError("bad request", 400), False, False),
    ],
)
def test_classification(error, fatal, retryable):
    assert is_fatal(error) is fatal
    assert is_retryable(error) is retryable


def test_gives_up_after_max_attempts():
    fake = FakeOpenAI(errors=[APIError("down", 503)] * 3)
    with pytest.raises(APIError):
        client_with(fake, max_attempts=3).complete([{"role": "user", "content": "hi"}])
    assert len(fake.chat_calls) == 3


def test_drops_a_rejected_sampling_parameter_and_remembers():
    error = APIError("Unsupported parameter: 'temperature' is not supported with this model.", 400, param="temperature")
    fake = FakeOpenAI(errors=[error])
    client = client_with(fake)
    client.complete([{"role": "user", "content": "hi"}], temperature=0.0, top_p=1.0)
    client.complete([{"role": "user", "content": "again"}], temperature=0.0, top_p=1.0)
    assert fake.chat_calls[0]["params"] == {"temperature": 0.0, "top_p": 1.0}
    assert fake.chat_calls[1]["params"] == {"top_p": 1.0}
    assert fake.chat_calls[2]["params"] == {"top_p": 1.0}


def test_renames_max_tokens_when_asked():
    error = APIError(
        "Unsupported parameter: 'max_tokens' is not supported with this model. Use 'max_completion_tokens' instead.",
        400,
        param="max_tokens",
    )
    fake = FakeOpenAI(errors=[error])
    client_with(fake).complete([{"role": "user", "content": "hi"}], max_tokens=50)
    assert fake.chat_calls[1]["params"] == {"max_completion_tokens": 50}


def test_embed_batches_and_prices():
    fake = FakeOpenAI()
    vectors, usage = client_with(fake).embed([f"message number {i}" for i in range(250)], batch=100)
    assert len(vectors) == 250 and len(fake.embed_calls) == 3
    assert usage.tokens_in == 750 and usage.tokens_out == 0
    assert usage.cost_usd == pytest.approx(750 * 0.02 / 1e6)


def test_latency_leaves_out_retries():
    fake = FakeOpenAI(errors=[RateLimitError("slow", 429)])
    client = OpenAIClient(client=fake, sleep=lambda s: __import__("time").sleep(0.2), base_delay=0.0)
    with Stopwatch() as watch:
        client.complete([{"role": "user", "content": "hi"}])
    assert watch.seconds < 0.15


def test_unpriced_model_is_flagged():
    usage = Usage().record("some-new-model", 1000, 10)
    assert usage.cost_usd == 0 and usage.unpriced_models == ["some-new-model"]


def test_load_api_key_from_dotenv(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")  # so the key set below is undone after the test
    monkeypatch.delenv("OPENAI_API_KEY")
    monkeypatch.chdir(tmp_path)
    assert load_api_key() is False
    (tmp_path / ".env").write_text('# comment\nexport OPENAI_API_KEY="sk-test-123"\nOTHER=1\n', encoding="utf-8")
    assert load_api_key() is True
    assert os.environ["OPENAI_API_KEY"] == "sk-test-123"


def test_missing_key_is_fatal(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(FatalAPIError):
        OpenAIClient().complete([{"role": "user", "content": "hi"}])
