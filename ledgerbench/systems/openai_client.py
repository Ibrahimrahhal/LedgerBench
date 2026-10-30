"""
A small wrapper around OpenAI's chat completions and embeddings that every
built-in system and the judge go through, so each call is priced the same way.

- Tokens in, cached in and out are recorded per model into a `Usage`, priced
  from `ledgerbench.prices`.
- Rate limits, timeouts, dropped connections and 5xx are retried with
  exponential backoff and jitter; the time lost to them is left out of latency
  (`base.Stopwatch`).
- Errors that retrying cannot fix (no credits left, a bad key, an unknown
  model) raise `FatalAPIError` at once, so a run stops instead of hammering the
  API: the 429 "You have no credits remaining" looks like a rate limit and was
  retried for minutes by an earlier harness.
- A sampling parameter the model rejects ("Unsupported parameter:
  'temperature'") is dropped and remembered for that model; `max_tokens` is
  renamed `max_completion_tokens` when a model asks for it.

Nothing here ever prints or logs the API key.
"""

from __future__ import annotations

import logging
import os
import random
import re
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ledgerbench.systems.base import DEFAULT_ANSWER_MODEL, DEFAULT_EMBEDDING_MODEL, Usage, add_lost_seconds

log = logging.getLogger("ledgerbench.openai")


class FatalAPIError(RuntimeError):
    """An API error that retrying will not fix."""


@dataclass
class Completion:
    text: str
    model: str
    usage: Usage = field(default_factory=Usage)


# ------------------------------------------------------------------------ the key


def load_api_key(env_file: str | Path = ".env") -> bool:
    """
    Puts OPENAI_API_KEY into the environment from a .env file in the working
    directory when it is not set already. Returns whether a key is available.
    python-dotenv is used when installed; otherwise the file is read simply.
    """
    if os.environ.get("OPENAI_API_KEY"):
        return True
    path = Path(env_file)
    if not path.is_file():
        return False
    try:
        from dotenv import load_dotenv  # type: ignore[import-not-found]

        load_dotenv(path, override=False)
    except ImportError:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip().removeprefix("export ").strip()
            value = value.strip().strip('"').strip("'")
            if key and value and key not in os.environ:
                os.environ[key] = value
    return bool(os.environ.get("OPENAI_API_KEY"))


# ---------------------------------------------------------------- classification


def _status(error: BaseException) -> int | None:
    status = getattr(error, "status_code", None)
    if status is None:
        response = getattr(error, "response", None)
        status = getattr(response, "status_code", None)
    return status if isinstance(status, int) else None


def _code(error: BaseException) -> str:
    code = getattr(error, "code", None)
    if not code:
        body = getattr(error, "body", None)
        if isinstance(body, dict):
            inner = body.get("error")
            code = (inner.get("code") if isinstance(inner, dict) else None) or body.get("code")
    return str(code or "")


def is_fatal(error: BaseException) -> bool:
    status = _status(error)
    message = str(error).lower()
    if _code(error) == "insufficient_quota" or "no credits" in message or "exceeded your current quota" in message:
        return True
    if "billing" in message and status == 429:
        return True
    return status in (401, 403, 404)


def is_retryable(error: BaseException) -> bool:
    if is_fatal(error):
        return False
    name = type(error).__name__
    if name in (
        "RateLimitError",
        "APIConnectionError",
        "APITimeoutError",
        "InternalServerError",
        "ConnectError",
        "ReadTimeout",
    ):
        return True
    status = _status(error)
    return status is not None and (status == 429 or status == 408 or status >= 500)


_PARAM = re.compile(r"(?:unsupported (?:parameter|value)|not supported)[^']*'([a-z_]+)'", re.IGNORECASE)


def rejected_param(error: BaseException, params: dict[str, Any]) -> str | None:
    """The request parameter a 400 says the model does not support, if it is one we sent."""
    if _status(error) != 400:
        return None
    candidates = [getattr(error, "param", None)]
    candidates += _PARAM.findall(str(error))
    for name in candidates:
        if name and name in params:
            return name
    return None


# ------------------------------------------------------------------------ client


class OpenAIClient:
    """
    `client` may be anything shaped like `openai.OpenAI` (tests pass a fake).
    One instance is safe to share across threads.
    """

    def __init__(
        self,
        *,
        answer_model: str = DEFAULT_ANSWER_MODEL,
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
        client: Any = None,
        max_attempts: int = 7,
        base_delay: float = 2.0,
        max_delay: float = 60.0,
        timeout: float = 120.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.answer_model = answer_model
        self.embedding_model = embedding_model
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.timeout = timeout
        self._sleep = sleep
        self._client = client
        self._lock = threading.Lock()
        self._dropped: dict[str, dict[str, str | None]] = {}  # model -> {param: renamed-to or None}

    @property
    def raw(self) -> Any:
        if self._client is None:
            with self._lock:
                if self._client is None:
                    try:
                        from openai import OpenAI
                    except ImportError as error:  # pragma: no cover - depends on the install
                        raise RuntimeError(
                            "the openai package is not installed: pip install 'ledgerbench[openai]'"
                        ) from error
                    if not os.environ.get("OPENAI_API_KEY"):
                        raise FatalAPIError(
                            "OPENAI_API_KEY is not set (in the environment or a .env file in the working directory)"
                        )
                    self._client = OpenAI(max_retries=0, timeout=self.timeout)
        return self._client

    # ----------------------------------------------------------------- retries

    def _with_retries(self, call: Callable[[], Any]) -> Any:
        for attempt in range(self.max_attempts):
            started = time.perf_counter()
            try:
                return call()
            except Exception as error:  # noqa: BLE001 - classified below
                if is_fatal(error):
                    raise FatalAPIError(f"{type(error).__name__}: {_short(error)}") from error
                if not is_retryable(error) or attempt == self.max_attempts - 1:
                    raise
                wait = min(self.base_delay * (2**attempt), self.max_delay) + random.uniform(0, 1)
                log.warning("retrying in %.1fs after %s: %s", wait, type(error).__name__, _short(error))
                self._sleep(wait)
                add_lost_seconds(time.perf_counter() - started)
        raise AssertionError("unreachable")  # pragma: no cover

    def _params_for(self, model: str, params: dict[str, Any]) -> dict[str, Any]:
        dropped = self._dropped.get(model, {})
        out = {}
        for key, value in params.items():
            if key in dropped:
                renamed = dropped[key]
                if renamed:
                    out[renamed] = value
                continue
            out[key] = value
        return out

    # -------------------------------------------------------------------- calls

    def complete(
        self, messages: Sequence[dict[str, str]], *, model: str | None = None, usage: Usage | None = None, **params: Any
    ) -> Completion:
        """One chat completion. Sampling parameters are optional and dropped if the model rejects them."""
        model = model or self.answer_model
        while True:
            sent = self._params_for(model, params)

            def call(sent: dict[str, Any] = sent) -> Any:
                return self.raw.chat.completions.create(model=model, messages=list(messages), **sent)

            try:
                response = self._with_retries(call)
                break
            except FatalAPIError:
                raise
            except Exception as error:  # noqa: BLE001
                bad = rejected_param(error, sent)
                if bad is None:
                    raise
                renamed = (
                    "max_completion_tokens" if bad == "max_tokens" and "max_completion_tokens" in str(error) else None
                )
                with self._lock:
                    dropped = self._dropped.setdefault(model, {})
                    # `bad` is either a parameter as the caller named it or the name it was renamed to.
                    original = next((k for k, v in dropped.items() if v == bad), bad)
                    dropped[original] = renamed if original == bad else None
                log.info("%s does not take %r; %s", model, bad, f"sending {renamed}" if renamed else "dropping it")

        from ledgerbench.prices import usage_of

        tokens_in, tokens_out, cached = usage_of(response)
        used = Usage().record(model, tokens_in, tokens_out, cached)
        if usage is not None:
            usage.add(used)
        choice = response.choices[0]
        text = (getattr(choice.message, "content", None) or "").strip()
        return Completion(text=text, model=getattr(response, "model", None) or model, usage=used)

    def embed(
        self, texts: Sequence[str], *, model: str | None = None, usage: Usage | None = None, batch: int = 100
    ) -> tuple[list[list[float]], Usage]:
        """Embeddings for `texts`, in order, in batches."""
        model = model or self.embedding_model
        vectors: list[list[float]] = []
        used = Usage()
        for i in range(0, len(texts), batch):
            chunk = [t.replace("\n", " ") or " " for t in texts[i : i + batch]]

            def call(chunk: list[str] = chunk) -> Any:
                return self.raw.embeddings.create(model=model, input=chunk)

            response = self._with_retries(call)
            vectors.extend(list(item.embedding) for item in response.data)
            api_usage = getattr(response, "usage", None)
            tokens = int(getattr(api_usage, "prompt_tokens", 0) or getattr(api_usage, "total_tokens", 0) or 0)
            used.record(model, tokens, 0, 0)
        if usage is not None:
            usage.add(used)
        return vectors, used


def _short(error: BaseException, limit: int = 200) -> str:
    text = str(error).replace("\n", " ")
    text = re.sub(r"sk-[A-Za-z0-9_\-]{8,}", "sk-***", text)  # never let a key reach a log
    return text[:limit]
