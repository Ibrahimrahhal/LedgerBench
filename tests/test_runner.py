"""The runner on the tiny fixture: test systems, resume, the budget guard, re-scoring."""

from __future__ import annotations

import pytest

from ledgerbench import results, runner
from ledgerbench.dataset import QuestionPrompt, Session, UserView
from ledgerbench.scoring import Verdict
from ledgerbench.systems.base import MemorySystem, Reply, Usage
from ledgerbench.systems.null import Null


def run(system_spec, dataset, run_dir, **kw):
    system, name = runner.make_system(system_spec, dataset)
    return runner.run(system, dataset, run_dir=run_dir, system_name=name, progress=False, **kw)


def test_oracle_scores_everything(tiny, tmp_path):
    summary = run("oracle", tiny, tmp_path / "oracle")
    assert summary["accuracy"] == 1.0 and summary["complete"] and summary["test_system"]
    assert summary["questions"]["unjudged"] == 0
    assert set(summary["by_answer_type"]) == {"number", "count", "category", "date", "set", "text"}


def test_null_scores_nothing(tiny, tmp_path):
    summary = run("null", tiny, tmp_path / "null")
    assert summary["accuracy"] == 0.0 and summary["questions"]["scored"] == 10


def test_summary_shape(tiny, tmp_path):
    summary = run("oracle", tiny, tmp_path / "run")
    for key in (
        "by_domain",
        "by_skill",
        "by_answer_type",
        "latency_s",
        "cost_usd",
        "models",
        "dataset",
        "git_commit",
        "notes",
    ):
        assert key in summary
    assert summary["dataset"]["version"] == "1.0" and summary["dataset"]["seed"] == 7
    assert summary["by_domain"]["spending"]["n"] == 6
    assert summary["by_skill"]["correction"] == {"n": 2, "correct": 2, "accuracy": 1.0}
    assert summary["ingestion"]["users"] == ["u1", "u2"] and summary["ingestion"]["sessions"] == 7
    row = results.read_jsonl(tmp_path / "run" / "answers.jsonl")[0]
    for key in (
        "question_id",
        "user",
        "skills",
        "domain",
        "reply",
        "extracted",
        "correct",
        "method",
        "latency_s",
        "usage",
        "tools",
    ):
        assert key in row


def test_users_and_max_questions(tiny, tmp_path):
    summary = run("oracle", tiny, tmp_path / "run", users=["u2"], max_questions=2)
    assert summary["questions"]["selected"] == 2 and summary["users"]["selected"] == ["u2"]
    with pytest.raises(ValueError):
        run("oracle", tiny, tmp_path / "other", users=["u9"])


def test_resume_skips_answered_questions(tiny, tmp_path):
    first = run("null", tiny, tmp_path / "run", max_questions=1)
    assert first["questions"]["answered"] == 2 and first["subset"]
    second = run("null", tiny, tmp_path / "run")
    assert second["questions"]["answered"] == 10 and second["complete"] and not second["subset"]
    ids = [r["question_id"] for r in results.read_jsonl(tmp_path / "run" / "answers.jsonl")]
    assert len(ids) == len(set(ids)) == 10


def test_conflicting_run_dir(tiny, tmp_path):
    run("null", tiny, tmp_path / "run")
    with pytest.raises(runner.RunConflict):
        run("oracle", tiny, tmp_path / "run")


def test_fresh_discards(tiny, tmp_path):
    run("null", tiny, tmp_path / "run", max_questions=1)
    summary = run("null", tiny, tmp_path / "run", max_questions=1, resume=False)
    assert summary["questions"]["answered"] == 2


class Costly(MemorySystem):
    """Each session and each answer costs one cent."""

    name = "costly"

    def __init__(self, fail_on: tuple[str, int] | None = None):
        super().__init__()
        self.fail_on = fail_on
        self.forgotten = []

    def forget(self, user):
        self.forgotten.append(user.id)

    def ingest(self, user: UserView, session: Session) -> Usage:
        if self.fail_on and (user.id, session.date) == self.fail_on:
            raise RuntimeError("boom")
        return Usage(cost_usd=0.01, calls=1)

    def restore(self, user, sessions):
        return True

    def answer(self, user: UserView, question: QuestionPrompt) -> Reply:
        return Reply("Answer: unknown", 0.01, Usage(cost_usd=0.01, calls=1))


def test_max_cost_stops_before_a_user_that_would_pass_it(tiny, tmp_path):
    summary = runner.run(Costly(), tiny, run_dir=tmp_path / "run", max_cost=0.05, progress=False)
    assert "max cost" in summary["stopped"]
    assert summary["users"]["ingested"] == ["u1"]  # u1 cost 0.04; u2 was projected at about 0.022 more
    assert summary["questions"]["answered"] == 0
    assert summary["cost_usd"]["total"] <= 0.05


def test_max_cost_stops_answering(tiny, tmp_path):
    summary = runner.run(Costly(), tiny, run_dir=tmp_path / "run", max_cost=0.12, workers=1, progress=False)
    assert summary["cost_usd"]["ingestion"] == pytest.approx(0.07)
    assert summary["questions"]["answered"] == 5
    assert summary["cost_usd"]["total"] == pytest.approx(0.12)
    assert "max cost" in summary["stopped"] and not summary["complete"]


def test_cut_off_ingestion_is_redone_and_its_cost_kept(tiny, tmp_path):
    system = Costly(fail_on=("u2", "2026-03-03"))
    summary = runner.run(system, tiny, run_dir=tmp_path / "run", progress=False)
    assert summary["users"]["ingested"] == ["u1"]
    again = Costly()
    summary = runner.run(again, tiny, run_dir=tmp_path / "run", progress=False)
    assert again.forgotten == ["u2"]
    assert summary["users"]["ingested"] == ["u1", "u2"]
    assert summary["cost_usd"]["ingestion"] == pytest.approx(0.07)
    assert summary["cost_usd"]["ingestion_abandoned"] == pytest.approx(0.01)
    assert summary["complete"]


class Flaky(Null):
    def answer(self, user, question):
        if question.id == "u1:q3":
            raise RuntimeError("transient")
        return super().answer(user, question)


def test_a_failed_question_is_retried_on_resume(tiny, tmp_path):
    summary = runner.run(Flaky(), tiny, run_dir=tmp_path / "run", system_name="null", progress=False)
    assert summary["questions"]["answered"] == 9 and not summary["complete"]
    summary = runner.run(Null(), tiny, run_dir=tmp_path / "run", progress=False)
    assert summary["questions"]["answered"] == 10 and summary["complete"]


class Paraphrase(MemorySystem):
    name = "paraphrase"

    def ingest(self, user, session):
        return Usage()

    def answer(self, user, question):
        return Reply("Answer: bench is 85 kg from the week of the 9th" if question.id == "u1:q6" else "Answer: unknown")


def test_text_judged_later_with_rescore(tiny, tmp_path):
    summary = runner.run(Paraphrase(), tiny, run_dir=tmp_path / "run", progress=False)
    assert summary["questions"]["unjudged"] == 1
    calls = []

    def judge(question, gold, answer):
        calls.append(answer)
        return Verdict(True, "same", "fake-judge", Usage().record("gpt-5.4-mini", 300, 20).to_dict())

    summary = runner.rescore(tmp_path / "run", judge=judge)
    assert calls == ["bench is 85 kg from the week of the 9th"]
    assert summary["questions"]["unjudged"] == 0 and summary["correct"] == 1
    assert summary["cost_usd"]["judge"] > 0 and summary["models"]["judge_used"] == ["fake-judge"]
    # A judged answer is not judged again unless asked.
    runner.rescore(tmp_path / "run", judge=judge)
    assert len(calls) == 1


def test_rescore_applies_a_scorer_change(tiny, tmp_path):
    run("oracle", tiny, tmp_path / "run")
    path = tmp_path / "run" / "answers.jsonl"
    rows = results.read_jsonl(path)
    for row in rows:
        row["correct"] = False
    results.rewrite_jsonl(path, rows)
    assert results.summarize(tmp_path / "run")["accuracy"] < 1.0
    summary = runner.rescore(tmp_path / "run")
    assert summary["accuracy"] == 1.0


def test_judge_failure_keeps_the_reply_unjudged(tiny, tmp_path):
    def broken(question, gold, answer):
        raise RuntimeError("judge down")

    summary = runner.run(Paraphrase(), tiny, run_dir=tmp_path / "run", judge=broken, progress=False)
    row = next(r for r in results.read_jsonl(tmp_path / "run" / "answers.jsonl") if r["question_id"] == "u1:q6")
    assert row["correct"] is None and "judge down" in row["reason"]
    assert summary["questions"]["answered"] == 10


def test_users_ingested_in_parallel(tiny, tmp_path):
    summary = runner.run(Costly(), tiny, run_dir=tmp_path / "run", ingest_workers=2, progress=False)
    assert summary["users"]["ingested"] == ["u1", "u2"] and summary["complete"]
    assert summary["cost_usd"]["ingestion"] == pytest.approx(0.07)
