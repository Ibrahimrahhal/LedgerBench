from __future__ import annotations

import json

import pytest

from ledgerbench import FORMAT_INSTRUCTION
from ledgerbench.dataset import from_dict, load, long_date


def test_load_tiny(tiny):
    assert tiny.name == "LedgerBench" and tiny.version == "1.0" and tiny.size == "tiny" and tiny.seed == 7
    assert [u.id for u in tiny.users] == ["u1", "u2"]
    assert len(tiny.sha256) == 64
    rana = tiny.user("u1")
    assert rana.currency == "EUR" and rana.units == {"body_weight": "kg", "lifts": "kg"}
    assert rana.domains == ("spending", "food", "training", "body")
    assert [s.date for s in rana.sessions] == ["2026-03-02", "2026-03-03", "2026-03-04", "2026-03-05"]
    assert rana.sessions[0].weekday == "Monday" and rana.sessions[0].messages[0] == "groceries at Lidl, 46.20"
    assert rana.message_count == 10 and len(rana.events) == 9


def test_question_fields(tiny):
    q = tiny.question("u1:q1")
    assert q.answer_type == "number" and q.gold == 64.2 and q.unit == "EUR"
    assert q.rel_tol == 0.01 and q.abs_tol == 0.005
    assert q.skills == ("aggregate", "correction") and q.evidence == ("u1:e1", "u1:e5")
    assert q.derivation["op"] == "sum"
    assert q.user_id == "u1"
    s = tiny.question("u1:q7")
    assert s.gold == ("Wednesday", "Thursday") and s.aliases_for("Thursday") == ("Thu", "Thurs")
    assert tiny.question("u1:q3").aliases_for("groceries") == ("food shopping",)
    with pytest.raises(KeyError):
        tiny.question("u1:q99")


def test_events_keep_their_fields(tiny):
    event = tiny.user("u1").events[0]
    assert event.id == "u1:e1" and event.type == "expense" and event.message == 0
    assert event.get("amount") == 46.2 and event.get("merchant") == "Lidl"


def test_prompt_has_only_the_question(tiny):
    prompt = tiny.question("u2:q2").prompt()
    assert prompt.id == "u2:q2" and prompt.asked_on == "2026-03-04"
    assert prompt.text == "How many kcal did I have at breakfast from 2 March to 3 March 2026?\n\n" + FORMAT_INSTRUCTION


def test_view_hides_the_truth(tiny):
    view = tiny.user("u1").view()
    assert view.name == "Rana" and view.domains == ("spending", "food", "training", "body")
    assert not hasattr(view, "events") and not hasattr(view, "questions") and not hasattr(view, "sessions")


def test_sessions_sorted_and_weekday_filled():
    data = from_dict(
        {
            "users": [
                {
                    "id": "u1",
                    "sessions": [
                        {"date": "2026-03-03", "messages": ["b"]},
                        {"date": "2026-03-02", "weekday": "Monday", "messages": ["a"]},
                    ],
                    "questions": [],
                }
            ]
        }
    )
    assert [(s.date, s.weekday) for s in data.users[0].sessions] == [
        ("2026-03-02", "Monday"),
        ("2026-03-03", "Tuesday"),
    ]


def test_unknown_answer_type_is_refused(tmp_path):
    bad = {
        "users": [
            {
                "id": "u1",
                "sessions": [],
                "questions": [{"id": "u1:q1", "question": "?", "answer_type": "vibes", "asked_on": "2026-01-01"}],
            }
        ]
    }
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValueError, match="vibes"):
        load(path)


def test_long_date():
    assert long_date("2026-03-12") == "Thursday 12 March 2026"
