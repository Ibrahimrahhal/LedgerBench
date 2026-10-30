# LedgerBench specification, v1

LedgerBench measures whether an AI assistant's memory can **keep the books** on
a person's life: log structured records from casual chat, keep them correct
through corrections and plan changes, and answer questions that need
arithmetic, filtering, grouping and point-in-time state over them.

Public long-term-memory benchmarks (LoCoMo, LongMemEval) ask about facts and
events in conversation. None asks for a total. LedgerBench is only about
records: spending, food and calories, a training plan that keeps changing, and
body readings. Every answer is computed by the generator from structured truth
the systems never see, and almost every answer is scored without an LLM judge.

This document is the contract between the generator (`ledgerbench/generate/`),
the dataset files (`data/`), the scorer (`ledgerbench/scoring.py`) and the
runner (`ledgerbench/runner.py`). Change it first, then the code.

## 1. What a system sees

For each user, a system is given the user's **sessions in date order**. A
session is one calendar day: a date, its weekday, and the 1 to 10 messages the
user typed to their assistant that day, in order. Messages are first person and
casual. The system may process them however it likes (one call per message, per
session, or none at all) but it may only read what has been given so far: no
look-ahead, no peeking at questions or at the structured truth.

Then, for each question, the system gets the user id, the question text and
`asked_on` (the date "today" is for the user), and must answer from a fresh
context: nothing from answering one question may carry to the next.

Every question ends with the same format instruction, appended by the runner:

> End your reply with one line that starts with `Answer:` followed by only the answer.

The scorer reads the last `Answer:` line. If there is none, it falls back to the
whole reply (see 6).

## 2. Sizes

| Size | Users | Days per user | Messages per user | Questions per user | Purpose |
|---|---|---|---|---|---|
| `mini` | 3 | 21 | about 120 | 20 | Smoke tests, CI dry runs |
| `standard` | 12 | 90 | about 500 | 40 | The headline benchmark |
| `long` | 6 | 365 | about 2,000 | 60 | Histories past a context window |

The first days run long, because people state their rent, subscriptions,
targets and training plan up front.

Generation is deterministic given `(size, seed)`; the default seed is 2026.
Files: `data/ledgerbench-<size>.json` plus `data/ledgerbench-<size>.preview.md`.

## 3. Personas

Each user has a name, a one-sentence `profile` with no numbers, a home currency
(EUR, USD or GBP), a body-weight unit (kg or lb), a lift unit (kg or lb), and a
set of tracked domains. Every user tracks **spending**. Across a size, the
other domains are balanced so each appears for at least two thirds of users,
and at least a third of users track all four. A user only logs, and is only
asked about, the domains they track.

## 4. Domains and events

Every fact a question depends on is an **event** in the user's `events` list,
with a stable `id` (`u3:e117`), the `date` it is about (which may differ from
the session that mentions it, see "relative dates" below), the `session_date`
and the 0-based `message` index that stated it, and a `type`. The checker's
module docstring (`ledgerbench/generate/check.py`) documents every event's
fields and the `derivation` language in full.

### 4.1 Spending

- `expense`: `amount` (positive, 2 decimals, home currency), `category` (from a
  fixed taxonomy: groceries, eating out, coffee, transport, rent, utilities,
  subscriptions, health, clothing, entertainment, travel, gifts, household,
  other), optional `merchant`, optional `note`.
- `refund`: `amount`, `refers_to` an expense id, full or partial. Spending "after
  refunds" subtracts it.
- `split`: the user paid `amount` for something shared and `owed` of it is owed
  back by a named `person`. The expense counts the full amount as paid; the
  owed amount is tracked separately. `settled` events (person paid back) close it.
- `recurring`: rent, subscriptions and bills that repeat monthly on a day, with
  `price_change` events that change the amount from a date.
- `budget`: a monthly budget for a category, `amount`, effective from a date;
  may change.

### 4.2 Food

- `meal`: `meal` (breakfast, lunch, dinner, snack), `items`, each with a
  `name`, `qty`, `kcal` and, for users who track them, `protein_g`, `carbs_g`,
  `fat_g`. The user states the numbers: "lunch, chicken wrap 520 kcal, 38g
  protein", "3 eggs at 70 each". Some meals reference earlier ones: "same
  breakfast as yesterday" copies that meal.
- `water`: `ml`.
- `kcal_target` and `protein_target`: daily targets effective from a date.

### 4.3 Training

- `plan`: the weekly schedule, effective from a date. A plan maps weekdays to a
  session name (Push, Pull, Legs, Upper, Lower, Full body, Run, Rest) and each
  session to prescribed exercises with sets, reps and a working weight in the
  lift unit. `plan_change` events describe one change in words the way a person
  says it ("move legs from Friday to Saturday from next week", "swap deadlifts
  for RDLs, 3x8", "bench goes up to 85") and carry the full resulting plan.
- `workout`: a logged session: `session` name, `exercises`, each with `sets`, a
  list of `{reps, weight}`. "Bench 4x6 at 80" is four sets of six at 80.
- `skip`: a planned session the user says they skipped, with a reason.
- `run`: `km`, `minutes`.

### 4.4 Body

- `weight` (in the user's body-weight unit), `sleep_hours`, `steps`,
  `resting_hr`.

### 4.5 What makes it hard, on purpose

- **Corrections** (`correction` event, `refers_to`, the changed field and new
  value): "the groceries on Tuesday were 64.20, not 46.20". About 3% of logged
  records are corrected later, from 1 to 10 days after. Truth uses the
  corrected value.
- **Retractions** (`retraction`, `refers_to`): "scratch the taxi I logged
  yesterday, I never took it". The record no longer exists.
- **Relative dates**: about 10% of records are logged on a later day ("forgot to
  say, yesterday's dinner was..."). The event's `date` is the day it happened.
- **Plan changes** happen 3 to 8 times per training user over 90 days, so "what
  is the plan now" and "what was the plan in week 3" differ.
- **Distractor numbers** in small talk ("watched 3 episodes", "the train was 20
  minutes late") that must never count.
- **Varied phrasing and units**: amounts as `6.40`, `€14`, `14 euros`, `$1,675`,
  occasionally in words; times as `31:10`, `1:02:32`; sleep as `7h20`, `7.5
  hours`; lifts as `4x6 @ 80`, `80kg for 4 sets of 6`.

## 5. Questions

Each question is answerable from the events alone, and states its period
explicitly (a named month, an inclusive date range, a weekday, or "now"), so no
system depends on its own idea of today. `asked_on` is the date of the user's
last session.

Every question has one `domain` (or `cross` for two), one `answer_type`, and
one or more `skills`:

| Skill | Meaning | Example |
|---|---|---|
| `lookup` | One record | "What did I have for dinner on 12 March?" |
| `aggregate` | Sum, count, average, min or max over records | "How much did I spend on groceries in March?" |
| `group` | The top group by a measure | "Which category did I spend the most on in February?" |
| `window` | A date range or weekday filter beyond a month | "How much coffee did I buy on weekdays in the week of 9 March?" |
| `state` | The current value of something that changed | "Which days am I training legs now?" |
| `as_of` | A value at a past date | "What was my bench working weight on 1 March?" |
| `change` | A difference between two points or periods | "How much did my weight change in March?" |
| `correction` | The answer depends on a correction or retraction | any of the above, flagged |
| `cross` | Joins two domains | "What was my average protein on days I trained?" |
| `adherence` | Planned against done | "How many planned sessions did I miss in March?" |
| `budget` | A budget against spending | "How much of my eating-out budget is left for March?" |

Per size, questions are spread so that every skill appears in every domain it
applies to, `correction` flags at least 10% of questions, and `cross` at least
5%. Numeric answers come from at least 3 records unless the skill is `lookup`,
`state`, `as_of`, or a min/max.

### 5.1 Answer types and how each is scored

| `answer_type` | Gold | Correct when |
|---|---|---|
| `number` | `gold` float, `unit` string, `rel_tol`, `abs_tol` | the first number in the answer is within `max(abs_tol, rel_tol × |gold|)` |
| `count` | `gold` int | the first number in the answer equals it exactly |
| `date` | `gold` ISO date | the first date in the answer (ISO, "12 March", "March 12th", "12/03" is not accepted) equals it; a missing year is taken from `asked_on` |
| `category` | `gold` string, `aliases` list | the answer contains the gold or an alias, and no other value from the question's `choices` list |
| `set` | `gold` list, `aliases` per member, `choices` | every gold member (or an alias) appears and no non-member from `choices` appears |
| `text` | `gold_text` | an LLM judge says it conveys the same thing; kept under 10% of questions |

`choices` is the closed vocabulary the answer must come from (the 14 spending
categories, the 7 weekdays, the user's exercise names, the session names), so
that listing everything is never rewarded. Numbers are parsed with thousands
separators and currency symbols removed; "1,240" is 1240.

`rel_tol` defaults to 0.01 and `abs_tol` to half the precision the answer is
naturally given in (0.005 for money, 0.5 for kcal, 0.05 for kg); averages use
`rel_tol` 0.01 and `abs_tol` 0.05 (0.5 for kcal). Generators set both
explicitly on every numeric question.

## 6. The scorer

`ledgerbench.scoring.score(question, reply) -> Score(correct, extracted, method, reason)`.

1. Take the text after the last line starting with `Answer:` (case-insensitive,
   markdown bold allowed). If none, take the whole reply and set
   `format_ok = False`. Format is reported, never penalised.
2. Apply the rule for the answer type above. `method` is `deterministic` or
   `judge`.
3. The judge is only called for `text`, with the prompt in
   `ledgerbench/judge.py`, and its model is recorded in every result.

## 7. Dataset file

```json
{
  "name": "LedgerBench", "version": "1.0", "size": "standard", "seed": 2026,
  "generated_on": "YYYY-MM-DD",
  "users": [{
    "id": "u1", "name": "Rana", "profile": "...", "currency": "EUR",
    "units": {"body_weight": "kg", "lifts": "kg"},
    "domains": ["spending", "food", "training", "body"],
    "sessions": [{"date": "2026-01-05", "weekday": "Monday", "messages": ["...", "..."]}],
    "questions": [{
      "id": "u1:q7", "domain": "spending", "skills": ["aggregate", "correction"],
      "question": "How much did I spend on groceries in February 2026?",
      "answer_type": "number", "gold": 412.35, "unit": "EUR",
      "rel_tol": 0.01, "abs_tol": 0.005,
      "gold_text": "412.35 EUR", "aliases": [], "choices": [],
      "asked_on": "2026-04-04",
      "evidence": ["u1:e12", "u1:e40"],
      "derivation": {"op": "sum", "type": "expense", "field": "amount", "where": {"category": "groceries"}, "from": "2026-02-01", "to": "2026-02-28", "after": ["corrections", "retractions"]}
    }],
    "events": [{"id": "u1:e12", "type": "expense", "date": "2026-02-03", "session_date": "2026-02-03", "message": 1, "amount": 46.2, "category": "groceries"}]
  }]
}
```

`events` and `derivation` are for reviewers and the checker. **No system may be
shown them**, and the runner never passes them on.

## 8. The checker

`ledgerbench.generate.check` re-derives every gold answer from `events` through
a second implementation that shares no code with the question builders, and
fails generation on any mismatch. It also asserts: dates consecutive, weekdays
right, every evidence id exists, every numeric aggregate has its minimum record
count, no distractor number is within tolerance of a numeric gold, every
question names its period, and the skill and domain coverage rules in 5.

## 9. Systems

A system implements `ledgerbench.systems.base.MemorySystem`:

```python
class MemorySystem:
    name: str

    def setup(self, run: RunConfig) -> None: ...  # once per run
    def ingest(self, user: User, session: Session) -> Usage: ...  # called per session, in order
    def answer(self, user: User, question: QuestionPrompt) -> Reply: ...  # fresh context every time
    def teardown(self) -> None: ...
```

`QuestionPrompt` carries only `id`, `text` (with the format instruction
appended) and `asked_on`. `Reply` carries `text`, `latency_s`, `usage` (tokens
in, cached in, out, cost in USD, by model) and optional `tools` (names the
system called). `Usage` from ingestion is summed per user.

Built in: `fullcontext` (every session so far in the prompt), `rag` (each
message embedded with its date; top k by cosine), `mem0` (the open-source
library), `oracle` (answers with `gold_text`; must score 100%), `null` (always
"I don't know"; must score 0%). External systems live in their own packages and
register by import path: `ledgerbench run --system mypkg.module:MySystem`.

## 10. Results

`results/<size>/<system>/<run-id>/` holds `answers.jsonl` (one line per
question: ids, skills, domain, the reply, the extracted answer, correct,
method, latency, usage, tools), `ingest.jsonl` (usage per user), and
`summary.json` (accuracy overall, by domain, by skill and by answer type with
counts; mean and p95 latency; ingestion and answering cost; models; the
dataset version and seed; the git commit; notes). Runs resume: questions
already in `answers.jsonl` are skipped.

`ledgerbench leaderboard` builds `results/LEADERBOARD.md` from every
`summary.json`, one table per size, with the answer model beside every row.

## 11. Fair comparison rules

1. Same answer model for every system in a table, named in the table.
2. Same inputs: every system gets the same sessions with dates.
3. Nothing sees the questions, `events` or `derivation` before or during
   ingestion.
4. A fresh context per question.
5. Cost and latency reported beside accuracy, ingestion separately.
6. Raw replies kept, so any score can be re-read.
