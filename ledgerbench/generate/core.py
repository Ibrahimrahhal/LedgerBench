"""
The objects the domain simulators share: a record (one future event), a
message (one line the user types, carrying zero or more records), and the
per-user context that collects them.

A record keeps two copies of its fields. `stated` is what the user typed at
the time and is what goes into the event; `truth` is what really happened.
They differ only when the record is later corrected, in which case the
correction event carries the truth. The question builders read `truth` (and
`stated`, to tell whether an answer depends on a correction); the checker reads
only the events.
"""

from __future__ import annotations

import copy
import random
from collections.abc import Callable
from datetime import date

from ledgerbench.generate.calendar import iso

# Rough time of day, for ordering a session's messages.
MORNING, BREAKFAST, COMMUTE, MIDDAY, AFTERNOON, EVENING, NIGHT = 0, 1, 2, 3, 4, 5, 6


class Rec:
    """One event-to-be. `links` holds references to other records (refers_to), resolved to ids on output."""

    __slots__ = ("type", "date", "stated", "truth", "links", "retracted", "fixed", "msg", "id", "tags")

    def __init__(self, type_: str, when: date, fields: dict, links: dict | None = None, tags: dict | None = None):
        self.type = type_
        self.date = when
        self.stated = fields
        self.truth = copy.deepcopy(fields)
        self.links = links or {}
        self.retracted = False
        self.fixed = None  # the correction or retraction record aimed at this one
        self.msg: Msg | None = None
        self.id: str | None = None
        self.tags = tags or {}  # generator-only notes (eligibility, descriptors); never written out

    def __repr__(self) -> str:
        return f"Rec({self.id or '?'} {self.type} {iso(self.date)} {self.stated})"


class Msg:
    """
    One message. `render(late)` writes its text from the records' *stated* fields,
    late in days (0 when said on the day itself). Rendering is deferred until the
    corrections have been chosen, so a misstatement is written as stated.
    """

    __slots__ = ("day", "slot", "recs", "render", "kind", "priority", "late", "text", "can_be_late")

    def __init__(
        self,
        day: date,
        slot: float,
        recs: list[Rec],
        render: Callable[[int], str],
        kind: str,
        priority: int = 5,
        can_be_late: bool = True,
    ):
        self.day = day  # the session it is said in
        self.slot = slot
        self.recs = recs
        self.render = render
        self.kind = kind  # record, statement, correction, retraction, filler, distractor
        self.priority = priority  # lower is dropped first when a day has too many messages
        self.late = 0
        self.text: str | None = None
        self.can_be_late = can_be_late
        for r in recs:
            r.msg = self


class UserCtx:
    """Everything one user's simulation writes into."""

    def __init__(self, persona: dict, days: list[date], seed_key: str):
        self.persona = persona
        self.days = days
        self.first = days[0]
        self.last = days[-1]
        self.seed_key = seed_key
        self.msgs: list[Msg] = []
        self.recs: list[Rec] = []
        self.timelines: dict = {}  # domain-specific truth the question builders read (plans, targets, budgets)
        self._rngs: dict[str, random.Random] = {}

    def rng(self, purpose: str) -> random.Random:
        """One independent stream per purpose, so a change in one domain does not reshuffle another."""
        if purpose not in self._rngs:
            self._rngs[purpose] = random.Random(f"{self.seed_key}:{purpose}")
        return self._rngs[purpose]

    def rec(self, type_: str, when: date, fields: dict, links: dict | None = None, tags: dict | None = None) -> Rec:
        r = Rec(type_, when, fields, links, tags)
        self.recs.append(r)
        return r

    def say(
        self,
        day: date,
        slot: float,
        recs: list[Rec],
        render: Callable[[int], str],
        kind: str = "record",
        priority: int = 5,
        can_be_late: bool = True,
    ) -> Msg:
        m = Msg(day, slot, recs, render, kind, priority, can_be_late)
        self.msgs.append(m)
        return m

    def in_window(self, d: date) -> bool:
        return self.first <= d <= self.last
