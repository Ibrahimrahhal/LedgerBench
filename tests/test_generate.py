"""The generator: determinism, the files it writes, coverage, and that corrections matter."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from ledgerbench.generate import generate, main
from ledgerbench.generate.check import REQUIRED, Evaluator, Store, check

ROOT = Path(__file__).resolve().parents[1]


def without_date(data: dict) -> str:
    data = dict(data)
    data.pop("generated_on")
    return json.dumps(data, ensure_ascii=False, indent=1)


@pytest.fixture(scope="module")
def mini() -> dict:
    return generate("mini", 2026)[0]


@pytest.fixture(scope="module")
def standard() -> dict:
    return generate("standard", 2026)[0]


def test_mini_is_byte_identical_across_runs(tmp_path: Path, mini: dict) -> None:
    a = main("mini", 2026, tmp_path / "a")
    b = main("mini", 2026, tmp_path / "b")
    strip = lambda p: [line for line in p.read_bytes().split(b"\n") if b'"generated_on"' not in line]  # noqa: E731
    assert strip(a) == strip(b)
    assert without_date(json.loads(a.read_text(encoding="utf-8"))) == without_date(mini)
    assert b"\r\n" not in a.read_bytes()
    assert (tmp_path / "a" / "ledgerbench-mini.preview.md").exists()


def test_another_seed_gives_other_data(mini: dict) -> None:
    other = generate("mini", 2027)[0]
    assert without_date(other) != without_date(mini)


def test_checker_passes_on_mini_and_standard(mini: dict, standard: dict) -> None:
    assert check(mini)["questions"] == 3 * 20
    assert check(standard)["questions"] == 12 * 40


def test_module_entry_point(tmp_path: Path) -> None:
    done = subprocess.run(
        [sys.executable, "-m", "ledgerbench.generate", "--size", "mini", "--seed", "2026", "--out", str(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert done.returncode == 0, done.stderr
    assert (tmp_path / "ledgerbench-mini.json").exists()
    assert "check passed" in done.stdout


def test_format_matches_the_spec(mini: dict) -> None:
    assert {"name", "version", "size", "seed", "generated_on", "users"} <= set(mini)
    assert mini["name"] == "LedgerBench" and mini["size"] == "mini" and mini["seed"] == 2026
    for u in mini["users"]:
        assert set(u) == {"id", "name", "profile", "currency", "units", "domains", "sessions", "questions", "events"}
        assert len(u["sessions"]) == 21
        for e in u["events"]:
            assert {"id", "type", "date", "session_date", "message"} <= set(e)
        for q in u["questions"]:
            assert set(q) == {
                "id",
                "domain",
                "skills",
                "question",
                "answer_type",
                "gold",
                "unit",
                "rel_tol",
                "abs_tol",
                "gold_text",
                "aliases",
                "choices",
                "asked_on",
                "evidence",
                "derivation",
            }
            if q["answer_type"] == "set":
                assert isinstance(q["aliases"], dict) and set(q["aliases"]) == set(q["gold"])
            elif q["answer_type"] == "category":
                assert q["aliases"][0] == q["gold"]


def test_coverage_rules_on_standard(standard: dict) -> None:
    users = standard["users"]
    qs = [q for u in users for q in u["questions"]]
    have = {(q["domain"], s) for q in qs for s in q["skills"]}
    assert REQUIRED <= have, sorted(REQUIRED - have)
    assert sum("correction" in q["skills"] for q in qs) >= 0.10 * len(qs)
    assert sum(q["domain"] == "cross" for q in qs) >= 0.05 * len(qs)
    assert sum(q["answer_type"] == "text" for q in qs) < 0.05 * len(qs)
    for d in ("food", "training", "body"):
        assert sum(d in u["domains"] for u in users) * 3 >= 2 * len(users)
    assert sum(len(u["domains"]) == 4 for u in users) * 3 >= len(users)
    assert all("spending" in u["domains"] for u in users)
    for u in users:
        for q in u["questions"]:
            assert q["domain"] == "cross" or q["domain"] in u["domains"]
            assert q["asked_on"] == u["sessions"][-1]["date"]


def test_correction_and_retraction_rates(standard: dict) -> None:
    logged = {"expense", "meal", "water", "workout", "run", "weight", "sleep_hours", "steps", "resting_hr"}
    events = [e for u in standard["users"] for e in u["events"]]
    n = sum(e["type"] in logged for e in events)
    corrections = sum(e["type"] == "correction" for e in events)
    retractions = sum(e["type"] == "retraction" for e in events)
    late = sum(e["type"] in logged and e["date"] != e["session_date"] for e in events)
    assert 0.02 <= corrections / n <= 0.045
    assert 0.005 <= retractions / n <= 0.02
    assert 0.06 <= late / n <= 0.14
    for u in standard["users"]:
        by_id = {e["id"]: e for e in u["events"]}
        for e in u["events"]:
            if e["type"] in ("correction", "retraction"):
                target = by_id[e["refers_to"]]
                lag = (date.fromisoformat(e["session_date"]) - date.fromisoformat(target["session_date"])).days
                assert 1 <= lag <= 10, (e["id"], lag)


def test_corrections_change_the_gold(standard: dict) -> None:
    flagged = 0
    for u in standard["users"]:
        truth, naive = Evaluator(Store(u["events"], True)), Evaluator(Store(u["events"], False), strict=False)
        for q in u["questions"]:
            if "correction" not in q["skills"]:
                continue
            flagged += 1
            assert truth.eval(q["derivation"]).value is not None
            try:
                stale = naive.eval(q["derivation"]).value
            except Exception:
                continue  # with the retracted record back, the question has no single answer: it plainly differs
            if q["answer_type"] == "number":
                assert abs(stale - q["gold"]) > max(q["abs_tol"], q["rel_tol"] * abs(q["gold"])), q["id"]
            elif q["answer_type"] == "set":
                assert sorted(stale) != sorted(q["gold"]), q["id"]
            else:
                assert stale != q["gold"], q["id"]
        # every correction really changes its record: a lookup of the field gives the new value, not the old one
        for e in u["events"]:
            if e["type"] != "correction":
                continue
            fixed = Store(u["events"], True).live[e["refers_to"]]
            raw = next(x for x in u["events"] if x["id"] == e["refers_to"])
            path = e["field"].replace(".*", ".0").split(".")
            a, b = fixed, raw
            for p in path:
                a = a[int(p)] if p.isdigit() else a[p]
                b = b[int(p)] if p.isdigit() else b[p]
            assert a == e["value"] and b == e["was"] and a != b, e["id"]
    assert flagged >= 48


# ------------------------------------------------------------------ the wording rules of 1.1


def _timeline(u: dict, of: dict) -> list[tuple[str, str]]:
    """(said, effective) for every statement of the value an as_of derivation reads, from the events alone."""
    ev = u["events"]
    kind = of["kind"]
    if kind == "recurring":
        decl = [e for e in ev if e["type"] == "recurring" and e["name"] == of["name"]]
        ids = {e["id"] for e in decl}
        return [(e["date"], e["date"]) for e in decl] + [
            (e["date"], e["from"]) for e in ev if e["type"] == "price_change" and e["refers_to"] in ids
        ]
    if kind == "budget":
        return [(e["date"], e["from"]) for e in ev if e["type"] == "budget" and e["category"] == of["category"]]
    if kind == "target":
        return [(e["date"], e["from"]) for e in ev if e["type"] == of["type"]]
    if kind == "plan":
        return [(e["date"], e.get("from", e["date"])) for e in ev if e["type"] in ("plan", "plan_change")]
    return []


@pytest.mark.parametrize("size", ["mini", "standard"])
def test_pending_changes_are_named_and_boundary_days_avoided(size: str, mini: dict, standard: dict) -> None:
    data = {"mini": mini, "standard": standard}[size]
    seen = 0
    for u in data["users"]:
        for q in u["questions"]:
            d = q["derivation"]
            if d["op"] != "as_of":
                continue
            entries = _timeline(u, d["of"])
            if not entries:
                continue
            on = d["on"]
            first = min(entries)
            pending = any(said <= on < eff for said, eff in entries)
            if "state" in q["skills"]:
                assert pending == ("before any announced change takes effect" in q["question"]), q["id"]
            else:
                assert pending == ("as things stood that day" in q["question"]), q["id"]
                assert not any(eff == on for said, eff in entries if (said, eff) != first), q["id"]
            seen += pending
    assert size == "standard" or seen >= 1  # mini holds the u2 Disney+ case


def test_exercise_and_food_aliases_carry_what_the_user_typed(mini: dict, standard: dict) -> None:
    from ledgerbench.generate.questions import collides, forms_said

    checked = 0
    for data in (mini, standard):
        for u in data["users"]:
            messages = [m for s in u["sessions"] for m in s["messages"]]
            typed = {**forms_said(messages, "exercise"), **forms_said(messages, "food")}
            for q in u["questions"]:
                if q["answer_type"] not in ("category", "set"):
                    continue
                alias_map = q["aliases"] if q["answer_type"] == "set" else {q["gold"]: q["aliases"]}
                for member, aliases in alias_map.items():
                    if member not in typed:
                        continue
                    checked += 1
                    lowered = {a.lower() for a in aliases}
                    for form in typed[member]:
                        clash = any(c != member and collides(form, c) for c in q["choices"])
                        assert (form.lower() in lowered) != clash, (q["id"], member, form)
    assert checked >= 5


def test_back_squat_takes_squats_unless_front_squat_is_a_choice(mini: dict, standard: dict) -> None:
    cases = [
        q
        for data in (mini, standard)
        for u in data["users"]
        for q in u["questions"]
        if q["answer_type"] == "category" and q["gold"] == "back squat"
    ]
    assert cases
    for q in cases:
        front = "front squat" in q["choices"]
        assert ("squats" in q["aliases"]) != front and ("squat" in q["aliases"]) != front, q["id"]
