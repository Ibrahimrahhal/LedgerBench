"""The checker catches what it should, and owes nothing to the question builders."""

from __future__ import annotations

import ast
import copy
from pathlib import Path

import pytest

import ledgerbench.generate.check as check_module
from ledgerbench.generate import generate
from ledgerbench.generate.check import CheckError, check


@pytest.fixture(scope="module")
def mini() -> dict:
    return generate("mini", 2026)[0]


def first(data: dict, answer_type: str) -> dict:
    return next(q for u in data["users"] for q in u["questions"] if q["answer_type"] == answer_type)


def test_clean_data_passes(mini: dict) -> None:
    check(mini)


def test_a_wrong_number_is_caught(mini: dict) -> None:
    data = copy.deepcopy(mini)
    q = first(data, "number")
    q["gold"] = round(q["gold"] + 1.37, 2)
    with pytest.raises(CheckError, match=q["id"]):
        check(data)


def test_a_wrong_count_is_caught(mini: dict) -> None:
    data = copy.deepcopy(mini)
    q = first(data, "count")
    q["gold"] += 1
    with pytest.raises(CheckError, match=q["id"]):
        check(data)


def test_a_wrong_category_is_caught(mini: dict) -> None:
    data = copy.deepcopy(mini)
    q = first(data, "category")
    q["gold"] = next(c for c in q["choices"] if c != q["gold"])
    with pytest.raises(CheckError, match=q["id"]):
        check(data)


def test_a_changed_event_is_caught(mini: dict) -> None:
    data = copy.deepcopy(mini)
    for u in data["users"]:
        for q in u["questions"]:
            if (
                q["derivation"]["op"] == "sum"
                and q["derivation"].get("type") == "expense"
                and q["answer_type"] == "number"
            ):
                ev = next(e for e in u["events"] if e["id"] in q["evidence"] and e["type"] == "expense")
                ev["amount"] = round(ev["amount"] + 10, 2)
                with pytest.raises(CheckError, match=q["id"]):
                    check(data)
                return
    pytest.skip("no expense sum in mini")


def test_a_dropped_correction_flag_is_caught(mini: dict) -> None:
    data = copy.deepcopy(mini)
    q = next(q for u in data["users"] for q in u["questions"] if "correction" in q["skills"])
    q["skills"] = [s for s in q["skills"] if s != "correction"]
    with pytest.raises(CheckError, match="depends on a correction but is not flagged"):
        check(data)


def test_missing_evidence_is_caught(mini: dict) -> None:
    data = copy.deepcopy(mini)
    q = next(q for u in data["users"] for q in u["questions"] if len(q["evidence"]) >= 3)
    q["evidence"] = q["evidence"][1:]
    with pytest.raises(CheckError, match=q["id"]):
        check(data)


def test_session_rules_are_caught(mini: dict) -> None:
    data = copy.deepcopy(mini)
    data["users"][0]["sessions"][3]["weekday"] = "Funday"
    data["users"][1]["sessions"][2]["messages"].append("Groceries on 2026-03-02 were 40.")
    with pytest.raises(CheckError) as err:
        check(data)
    assert "Funday" in str(err.value) and "ISO date" in str(err.value)


def test_a_distractor_collision_is_caught(mini: dict) -> None:
    data = copy.deepcopy(mini)
    u = data["users"][0]
    q = next(q for q in u["questions"] if q["answer_type"] == "number")
    d = next(e for e in u["events"] if e["type"] == "distractor")
    d["numbers"] = [q["gold"]]
    with pytest.raises(CheckError, match="distractor"):
        check(data)


def test_coverage_is_enforced(mini: dict) -> None:
    data = copy.deepcopy(mini)
    for u in data["users"]:
        u["questions"] = [q for q in u["questions"] if q["domain"] != "cross"]
    with pytest.raises(CheckError, match="cross"):
        check(data)


def test_checker_shares_no_code_with_the_builders() -> None:
    tree = ast.parse(Path(check_module.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert "ledgerbench" not in imported, imported
