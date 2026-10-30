"""Results files, summaries and the leaderboard."""

from __future__ import annotations

from conftest import FakeOpenAI, gold_replier

from ledgerbench import leaderboard, results, runner
from ledgerbench.judge import parse_verdict
from ledgerbench.systems.base import RunConfig
from ledgerbench.systems.fullcontext import FullContext
from ledgerbench.systems.openai_client import OpenAIClient


def test_p95():
    assert results.p95([]) is None
    assert results.p95([1.0]) == 1.0
    assert results.p95([float(i) for i in range(1, 101)]) == 95.0
    assert results.p95([1.0, 2.0, 3.0]) == 3.0


def test_jsonl_tolerates_a_cut_line(tmp_path):
    path = tmp_path / "a.jsonl"
    path.write_bytes(b'{"question_id": "u1:q1"}\n{"question_id": "u1:q2"}\n{"question_')
    assert results.answer_ids(path) == {"u1:q1", "u1:q2"}


def test_files_are_lf(tiny, tmp_path):
    system, name = runner.make_system("null", tiny)
    runner.run(system, tiny, run_dir=tmp_path / "run", system_name=name, progress=False)
    for file in ("answers.jsonl", "ingest.jsonl", "summary.json", "run.json"):
        assert b"\r\n" not in (tmp_path / "run" / file).read_bytes(), file


def test_ingestion_totals_count_each_user_once():
    rows = [
        {"user": "u1", "attempt": 1, "index": 0, "usage": {"cost_usd": 0.5}},
        {"user": "u1", "attempt": 2, "index": 0, "usage": {"cost_usd": 0.4}},
        {"user": "u1", "attempt": 2, "index": 1, "usage": {"cost_usd": 0.4}},
        {
            "user": "u1",
            "attempt": 2,
            "done": True,
            "sessions": 2,
            "messages": 5,
            "seconds": 3.0,
            "usage": {"cost_usd": 0.8},
        },
    ]
    totals = results.ingestion_totals(rows)
    assert totals["cost_usd"] == 0.8 and totals["abandoned_cost_usd"] == 0.5 and totals["users"] == ["u1"]


def _run(spec, dataset, results_dir, run_id, **kw):
    system, name = runner.make_system(spec, dataset)
    run_dir = results_dir / dataset.size / name / run_id
    return runner.run(
        system,
        dataset,
        run_dir=run_dir,
        system_name=name,
        progress=False,
        config=RunConfig(run_id=run_id, run_dir=run_dir, size=dataset.size),
        **kw,
    )


def test_leaderboard(tiny, tmp_path):
    out = tmp_path / "results"
    _run("oracle", tiny, out, "o1")
    _run("null", tiny, out, "n1")
    fake = FakeOpenAI(gold_replier(tiny))
    client = OpenAIClient(answer_model="gpt-6-luna", client=fake)
    run_dir = out / "tiny" / "fullcontext" / "fc1"
    runner.run(
        FullContext(client=client),
        tiny,
        run_dir=run_dir,
        progress=False,
        config=RunConfig(run_id="fc1", run_dir=run_dir, size="tiny", answer_model="gpt-6-luna"),
    )
    run_dir = out / "tiny" / "fullcontext" / "partial"
    mini = OpenAIClient(answer_model="gpt-5.4-mini", client=fake)
    runner.run(
        FullContext(client=mini),
        tiny,
        run_dir=run_dir,
        progress=False,
        max_questions=1,
        config=RunConfig(run_id="partial", run_dir=run_dir, size="tiny", answer_model="gpt-5.4-mini"),
    )

    text = leaderboard.build(out)
    assert (out / "LEADERBOARD.md").read_text(encoding="utf-8") == text
    assert "## tiny" in text and "### Answer model: gpt-6-luna" in text
    assert "| fullcontext | gpt-6-luna | 100.0% |" in text
    assert "oracle" not in text and "null" not in text  # test systems are left out
    assert "partial" not in text  # so is the run that answered a subset

    shown = leaderboard.build(out, include_partial=True, include_test=True, write=False)
    assert "| oracle |" in shown and "| null |" in shown and "fullcontext (partial)" in shown


def test_empty_leaderboard(tmp_path):
    assert "No complete runs yet." in leaderboard.build(tmp_path / "nothing")


def test_parse_verdict():
    assert parse_verdict('{"reason": "same", "label": "CORRECT"}') == (True, "same")
    assert parse_verdict('{"reason": "no", "label": "wrong"}') == (False, "no")
    assert parse_verdict('Sure: {"reason": "ok", "label": "CORRECT"} done') == (True, "ok")
    assert parse_verdict("CORRECT")[0] is True
    assert parse_verdict("garbage")[0] is False


def test_llm_judge_uses_the_client(fake_openai):
    from ledgerbench.judge import LLMJudge

    fake = fake_openai(lambda m, model, p: '{"reason": "same plan", "label": "CORRECT"}')
    judge = LLMJudge("gpt-5.4-mini", client=OpenAIClient(client=fake))
    verdict = judge("What is my plan now?", "Push on Monday", "Monday is push")
    assert verdict.correct and verdict.model == "gpt-5.4-mini" and verdict.usage["calls"] == 1
    call = fake.chat_calls[0]
    assert call["params"] == {"response_format": {"type": "json_object"}}
    assert "Gold answer: Push on Monday" in call["messages"][0]["content"]
