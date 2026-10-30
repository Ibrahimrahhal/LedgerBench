# LedgerBench

**Can an AI assistant's memory keep the books on a person's life?**

LedgerBench is a benchmark for agent memory on structured personal data. A
simulated person chats with their assistant every day for weeks or months:
what they spent, what they ate, the gym session they did, what the scale said,
the plan they changed, the number they got wrong yesterday. Then they ask the
kind of questions people actually ask of their own records:

- How much did I spend on groceries in March?
- What was my average daily calorie intake on weekends between 8 March and 1 April?
- On which days was I scheduled to do lower-body sessions on 1 March, by the plan I had then?
- How much did I spend on coffee in April on days after I slept under 7 hours?

Every answer is computed by the generator from structured truth that the
systems never see. Almost every answer is scored without an LLM judge.

## Why another memory benchmark

The public long-term-memory benchmarks, [LoCoMo](https://arxiv.org/abs/2402.17753)
and [LongMemEval](https://arxiv.org/abs/2410.10813), ask about facts and events
in a conversation: who said what, and when. They don't ask for a total. Yet a
total is what people want from an assistant that tracks their spending, food
or training. It's also where memory kept as prose fails. In a pilot on an
earlier version of this dataset, gpt-5.4-mini with the user's entire history
in its prompt got 2 of 24 spending totals right, while recalling 16 of 16
current facts correctly.

LedgerBench is only about records. To do well, a system has to:

1. **Log records** from casual messages ("Cappuccino and a pastry, $4.02", "bench 4x6 @ 145").
2. **Keep them correct** through corrections, retractions and things logged a day late.
3. **Track state that changes**: a training plan, a budget, a calorie target, a subscription price.
4. **Compute over them**: sums, counts, averages, maxima, differences, top groups, joins across domains.

## What's in it

**Four domains.**

| Domain | Records | Changes over time |
|---|---|---|
| Spending | Expenses in 14 categories, refunds, bills split with friends and paid back, recurring rent and subscriptions | Monthly budgets, subscription price rises |
| Food | Meals with items, calories and, for some people, protein or full macros; water | Calorie and protein targets |
| Training | Logged workouts with sets, reps and weights; runs; skipped sessions | A weekly plan changed 3 to 8 times in 90 days |
| Body | Weight, sleep, steps, resting heart rate | |

**What makes it hard, on purpose.**

- About 3% of records are corrected later and 1% retracted.
- About 10% are logged a day or more late ("forgot to say, yesterday...").
- Small talk carries numbers that must never count ("watched 3 episodes").
- Amounts, times and lifts come in many formats (`€14`, `14 euros`, `31:10`, `7h20`, `4x6 @ 80`, `80kg for 4 sets of 6`).
- People reference earlier entries ("same breakfast as yesterday").

**Eleven skills,** tagged on every question:

| Skill | Example |
|---|---|
| `lookup` | What did I weigh on 25 March 2026? |
| `aggregate` | How much did I spend on groceries in February? |
| `group` | Which category did I spend the most on in February? |
| `window` | Average daily calories on weekends between 8 March and 1 April? |
| `state` | How much do I pay for iCloud now? |
| `as_of` | What was my calorie target on 29 April? |
| `change` | How many more calories a day did I eat in March than in February? |
| `correction` | Any question whose answer changes if a correction is ignored |
| `cross` | What did I spend on coffee on days after a short night's sleep? |
| `adherence` | How many sessions on my plan in March did I not do? |
| `budget` | How much of my eating-out budget is left for March? |

**Three sizes,** generated deterministically from a seed (default 2026):

| Size | People | Days | Messages | Records | Questions | Use |
|---|---|---|---|---|---|---|
| `mini` | 3 | 21 | 357 | 424 | 60 | Smoke tests |
| `standard` | 12 | 90 | 6,039 | 7,300 | 480 | The headline benchmark |
| `long` | 6 | 365 | 12,177 | 14,937 | 360 | Histories past a context window |

In `standard`, 23% of questions depend on a correction or retraction and 7%
join two domains. Answer types: numbers 73%, counts 13%, categories 9%, dates
3%, sets 1%, free text under 1%.

### A day of data

From the first session of one `standard` user, Owen:

> So you know: my rent is $1,370, paid on the 1st of every month.
> Slept 7h45.
> Aiming for 2,100 calories a day.
> Here's my training plan: Monday upper, Tuesday lower, Thursday upper, Friday lower, everything else rest. Upper is bench press 4x6 @ 145, BB rows 4x8 @ 140, ...
> Cappuccino and a pastry, $4.02.
> Lunch out, poke bowl, 17.20 dollars.
> Dinner was salmon 451 calories, rice 260 kcal and steak 513.
> Upper day: bench: 4 sets of 6 at 145, barbell rows 140 for 8, 8, 8, 6, OHP 3x8 at 90lbs, ...

On his third day he writes: "Wrote the wrong number, the stir fry at dinner
yesterday was 572 calories. Not 472."

Three of Owen's 40 questions, with their gold answers:

| Question | Gold |
|---|---|
| How many times did I eat out or get takeaway between 31 January and 21 February 2026 inclusive? | 9 |
| On average, how many fewer steps a day did I log in March 2026 than in February 2026? | 218.6 steps |
| On which days of the week was I scheduled to do lower sessions on 1 March 2026, by my training plan? | Saturday, Sunday |

`data/ledgerbench-<size>.preview.md` shows more, with each question's evidence
and derivation.

## How answers are scored

Every question ends with the same instruction: end the reply with a line
starting `Answer:`. The scorer reads that line and applies a rule by answer
type:

| Answer type | Correct when |
|---|---|
| Number | The first number in the answer is within tolerance of the gold: 1% relative, or half the natural precision (a cent, half a kcal) |
| Count | The first number equals the gold exactly |
| Date | The first date (ISO or with a month name) is the gold date |
| Category, set | The gold (or an alias) is named, and no other option from the question's closed list is |
| Text | An LLM judge agrees (under 1% of questions) |

The number rule skips dates, clock times, sets-by-reps and numbers restated
from the question, so an answer can't win by repeating the question. The
closed lists mean an answer can't win by naming every category.

Before trusting a run, the scorer is checked against two test systems. An
oracle that answers with the gold scores 100% on every size, and a null
system that always says "I don't know" scores 0%.

## Results

No runs are published yet. The first table will compare full context, naive
RAG, [Mem0](https://github.com/mem0ai/mem0) and
[Open Mate](https://openmate.si) on `standard`, all answering with
`gpt-6-luna`. It will report accuracy by domain and skill, cost and latency.
`ledgerbench leaderboard` builds `results/LEADERBOARD.md` from every run's
`summary.json`.

## Quick start

Python 3.10 or newer. Generating, loading and scoring use only the standard
library.

```bash
git clone https://github.com/Ibrahimrahhal/ledger-bench.git
cd ledger-bench
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[openai]"

ledgerbench inspect --data data/ledgerbench-mini.json --user u1      # read one person's log
ledgerbench run --system oracle --data data/ledgerbench-mini.json    # free: must score 100%

export OPENAI_API_KEY=...                                            # or put it in .env
ledgerbench run --system fullcontext --data data/ledgerbench-mini.json \
    --answer-model gpt-6-luna --users u1 --max-questions 5 --max-cost 0.50
```

The datasets ship in `data/`. To regenerate them, or another seed:

```bash
ledgerbench generate --size standard --seed 2026 --out data
```

Generation fails if the independent checker in `ledgerbench/generate/check.py`
can't re-derive every gold answer from the records.

### Systems included

| System | What it does |
|---|---|
| `fullcontext` | Every session so far in the prompt, dated. The ceiling while a history fits in context. |
| `rag` | Each message embedded with its date; the 20 nearest go in the prompt. |
| `mem0` | The open-source Mem0 library (2.2.1) with Qdrant. Needs `pip install -e ".[mem0]"` and `docker run -p 6333:6333 qdrant/qdrant`. |
| `oracle`, `null` | Test systems that check the scorer. |

### `ledgerbench run` options

| Option | Meaning |
|---|---|
| `--system NAME` | A built-in name, or `package.module:Class` for your own |
| `--data PATH` | The dataset file |
| `--users u1 u2` | Only these people |
| `--max-questions N` | The first N questions of each person |
| `--answer-model`, `--embedding-model` | Defaults `gpt-5.4-mini`, `text-embedding-3-small` |
| `--judge-model` | For `text` questions only (default `gpt-5.4-mini`); `--no-judge` leaves them unjudged |
| `--workers N`, `--ingest-workers N` | Questions answered at once (4), people ingested at once (1) |
| `--max-cost USD` | Stop before work that would take the run's total spend past this |
| `--run-id ID` | Names the run directory; the same id resumes |
| `--fresh` | Discard earlier results in the run directory instead of resuming |
| `--option KEY=VALUE` | Passed to the system's constructor |

A run writes `results/<size>/<system>/<run-id>/` with every reply, the
extracted answer, the score and its reason, latency and cost per question, and
a `summary.json` broken down by domain, skill and answer type. Runs resume
where they stopped. `ledgerbench score --run-dir ...` re-scores saved replies
without calling any model.

## Add your memory system

A system subclasses `ledgerbench.systems.base.MemorySystem` and lives in its
own package. It sees each person's sessions in date order, then each question
on its own. It never sees the records, the questions in advance, or the gold.

```python
from ledgerbench.dataset import QuestionPrompt, Session, UserView
from ledgerbench.systems.base import MemorySystem, Reply, RunConfig, Stopwatch, Usage, answer_messages
from ledgerbench.systems.openai_client import OpenAIClient


class MySystem(MemorySystem):
    name = "mysystem"
    needs_openai = True

    def setup(self, run: RunConfig) -> None:
        super().setup(run)
        self.client = OpenAIClient(answer_model=run.answer_model, embedding_model=run.embedding_model)
        self.store: dict[str, list[str]] = {}

    def ingest(self, user: UserView, session: Session) -> Usage:
        """Once per session, in date order. Return what it cost."""
        self.store.setdefault(user.id, []).extend(f"{session.date}: {m}" for m in session.messages)
        return Usage()

    def answer(self, user: UserView, question: QuestionPrompt) -> Reply:
        """A fresh context every time; may run on several threads at once."""
        usage = Usage()
        material = "\n".join(self.store.get(user.id, []))
        with Stopwatch() as watch:
            completion = self.client.complete(
                answer_messages(user, question, intro="Here is what {name} told you:", material=material), usage=usage
            )
        return Reply(completion.text, watch.seconds, usage)
```

```bash
ledgerbench run --system mypkg.memory:MySystem --data data/ledgerbench-standard.json --answer-model gpt-6-luna
```

A system that calls models through its own client must still report what it
spent, with `Usage.record(model, tokens_in, tokens_out, cached_in, cost_usd)`.
Optional `forget` and `restore` hooks make long runs resumable.

### Fair comparison

1. Every system in a table answers with the same model, named in the table.
2. Every system gets the same sessions with the same dates.
3. Nothing sees the questions, the records or the derivations before or during ingestion.
4. Every question starts from a fresh context.
5. Cost and latency are reported beside accuracy, ingestion separately.
6. Raw replies are kept, so any score can be re-read.

## Repository layout

```
data/                      the three datasets and their previews
docs/SPEC.md               the contract: formats, question rules, scoring
ledgerbench/generate/      the simulators, question builders and the independent checker
ledgerbench/scoring.py     every scoring rule, with its reasoning
ledgerbench/runner.py      ingestion, answering, resuming, the budget guard
ledgerbench/systems/       the interface and the built-in systems
tests/                     no test calls a paid API
```

## Development

```bash
pip install -e ".[dev,openai]"
ruff check . && ruff format --check .
pytest
```

CI runs lint, the tests, and the oracle and null systems on `mini`, on Python
3.10 and 3.13.

## Citation

```bibtex
@misc{rahhal2026ledgerbench,
  title  = {LedgerBench: Can an AI Assistant's Memory Keep the Books on a Person's Life?},
  author = {Rahhal, Ibrahim},
  year   = {2026},
  url    = {https://github.com/Ibrahimrahhal/ledger-bench}
}
```

## License

MIT, see `LICENSE`. The data is synthetic: every person, place and number in
it was generated.
