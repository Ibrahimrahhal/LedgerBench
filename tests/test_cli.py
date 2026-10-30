from __future__ import annotations

import json

import pytest

from ledgerbench.cli import build_parser, main


def test_help_lists_every_command(capsys):
    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    for command in ("generate", "run", "score", "leaderboard", "inspect"):
        assert command in out


def test_run_options():
    args = build_parser().parse_args(
        [
            "run",
            "--system",
            "rag",
            "--data",
            "d.json",
            "--users",
            "u1",
            "u2",
            "--max-questions",
            "3",
            "--max-cost",
            "1.5",
            "--option",
            "top_k=10",
        ]
    )
    assert (
        args.users == ["u1", "u2"]
        and args.max_questions == 3
        and args.max_cost == 1.5
        and args.option == [("top_k", 10)]
    )
    assert (
        args.answer_model == "gpt-5.4-mini"
        and args.embedding_model == "text-embedding-3-small"
        and args.judge_model == "gpt-5.4-mini"
    )


def test_run_score_leaderboard(tiny_path, tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert (
        main(
            ["run", "--system", "oracle", "--data", str(tiny_path), "--results-dir", "res", "--run-id", "r1", "--quiet"]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "accuracy 100.0%" in out
    summary = json.loads((tmp_path / "res" / "tiny" / "oracle" / "r1" / "summary.json").read_text(encoding="utf-8"))
    assert summary["accuracy"] == 1.0

    assert (
        main(
            [
                "run",
                "--system",
                "ledgerbench.systems.null:Null",
                "--data",
                str(tiny_path),
                "--results-dir",
                "res",
                "--run-id",
                "r1",
                "--quiet",
            ]
        )
        == 0
    )
    assert "accuracy 0.0%" in capsys.readouterr().out

    assert main(["score", "--run-dir", str(tmp_path / "res" / "tiny" / "oracle" / "r1"), "--no-judge"]) == 0
    assert "0 changed" in capsys.readouterr().out

    assert main(["leaderboard", "--results-dir", "res", "--include-test", "--print"]) == 0
    assert "| oracle |" in capsys.readouterr().out


def test_openai_system_needs_a_key(tiny_path, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert main(["run", "--system", "fullcontext", "--data", str(tiny_path), "--quiet"]) == 2
    assert "OPENAI_API_KEY" in capsys.readouterr().err


def test_unknown_system(tiny_path, capsys):
    assert main(["run", "--system", "nope", "--data", str(tiny_path), "--quiet"]) == 2
    assert "unknown system" in capsys.readouterr().err


def test_inspect(tiny_path, capsys):
    assert main(["inspect", "--data", str(tiny_path), "--user", "u1", "--events"]) == 0
    out = capsys.readouterr().out
    assert (
        "u1 Rana | EUR" in out
        and "== Monday 2026-03-02" in out
        and "u1:q1 [spending; aggregate, correction; number]" in out
    )
    assert "u1:e1 expense" in out
    assert main(["inspect", "--data", str(tiny_path), "--user", "u9"]) == 2
