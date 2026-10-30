"""
The LLM judge, used only for `text` questions (spec section 6), which the
generator keeps under 10% of the questions. Every other answer type is scored
without a model.

The prompt is adapted from Mem0's LoCoMo evaluation, by way of the harness
that ran it before LedgerBench: generous about wording and format, strict on
substance. The judge's model is recorded in every result it scores, and what
it costs is reported apart from the system's own answering cost.
"""

from __future__ import annotations

import json
import re

from ledgerbench.scoring import Verdict
from ledgerbench.systems.base import DEFAULT_JUDGE_MODEL, Usage
from ledgerbench.systems.openai_client import FatalAPIError, OpenAIClient

PROMPT = """Your task is to label an answer to a question as CORRECT or WRONG. You will be given:
(1) a question a person asked their assistant about their own logged records (spending, food, training, body readings),
(2) a gold (ground truth) answer, computed from those records,
(3) a generated answer.

The gold answer is usually short. The generated answer may be longer. Be generous: as long as it conveys the same thing as the gold answer, it is CORRECT. Extra correct detail does not make it WRONG, but extra detail that contradicts the gold answer does.

For dates and periods, be generous about format ("May 7th" and "7 May" are the same date) as long as it is the same date or period.

For amounts, the generated answer must give the same number as the gold answer, allowing for rounding and for currency symbols or units written differently. A different number is WRONG.

For plans, schedules and lists, every item in the gold answer must be there and nothing that contradicts it.

If the generated answer says it does not know, or gives no answer, it is WRONG.

Question: {question}
Gold answer: {gold}
Generated answer: {answer}

Reply with JSON only: {{"reason": "<one sentence>", "label": "CORRECT" or "WRONG"}}"""


def parse_verdict(text: str) -> tuple[bool, str]:
    """(correct, reason) from the judge's reply, tolerating prose around the JSON."""
    text = (text or "").strip()
    data = None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
            except json.JSONDecodeError:
                data = None
    if isinstance(data, dict):
        label = str(data.get("label", "")).strip().upper()
        reason = str(data.get("reason", ""))[:300]
        if label in ("CORRECT", "WRONG"):
            return label == "CORRECT", reason
    upper = text.upper()
    correct = "CORRECT" in upper and "WRONG" not in upper
    return correct, f"unparsed judge reply: {text[:200]}"


class LLMJudge:
    """Callable as a `scoring.Judge`. Thread-safe."""

    def __init__(self, model: str = DEFAULT_JUDGE_MODEL, client: OpenAIClient | None = None, attempts: int = 3) -> None:
        self.model = model
        self.client = client or OpenAIClient(answer_model=model)
        self.attempts = attempts

    def __call__(self, question: str, gold: str, answer: str) -> Verdict:
        prompt = PROMPT.format(question=question, gold=gold, answer=answer or "(no answer)")
        usage = Usage()
        last: Exception | None = None
        for _ in range(self.attempts):
            try:
                completion = self.client.complete(
                    [{"role": "user", "content": prompt}],
                    model=self.model,
                    usage=usage,
                    response_format={"type": "json_object"},
                )
                correct, reason = parse_verdict(completion.text)
                return Verdict(correct, reason, self.model, usage.to_dict())
            except FatalAPIError:
                raise
            except Exception as error:  # noqa: BLE001 - the client already retried transient errors; try a fresh call
                last = error
        raise RuntimeError(f"judge failed after {self.attempts} attempts: {last}")
