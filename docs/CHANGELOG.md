# Changelog

Dataset versions. The sessions and events of a size and seed only change when
this file says so; scores from different dataset versions are not comparable.

## 1.1

A first real run (full context on `mini`) found four of its misses were the
benchmark's fault, not the model's. Sessions, messages and events are
unchanged in every size; only questions and the scorer changed.

- **Durations are read whole.** For a question in hours (or minutes), "7 hours
  45 minutes", "7 hours 45", "7h45", "7h 45m", "7 h 45 min" and "7:45 hours" all
  count as 7.75 hours. Before, "7 hours 45 minutes" was read as 7.
- **An exercise or food is accepted under the names the user used for it.**
  Aliases now carry every form of the name that person typed in their messages
  ("squats", "BB rows", "deads", "slices of toast") and its plain singular,
  unless that form would also name another option in the question (with both
  back squat and front squat on the list, "squats" says neither). The checker
  now treats plurals as the same word when it looks for overlaps.
- **"Now" says which value it means when a change is coming.** When a price,
  budget, target or plan change has been announced but has not started yet,
  the question asks for the value in force "before any announced change takes
  effect" (or, for a past date, "as things stood that day"). Questions about the
  very day a change starts, and changes measured "until now" while another is
  pending, are no longer asked.
- **A month that has not ended is not asked about as a whole month.** A
  question about the current month now says "so far in March 2026 (1 to 21
  March)", and a question only mentions something (like rent) if the period
  holds at least one record of it. The checker enforces both.

In `standard`, 54 of 480 questions changed: 51 in wording (2 of them are new
questions, replacing ones asked about the day a change started) and 4 in their
aliases. In `long`, 23 of 360 changed in wording, 5 of them new questions. In
`mini`, 24 of 60 changed, 23 in wording and 2 in their aliases, and no answer
changed.

## 1.0

The first release: 3 sizes (`mini`, `standard`, `long`) generated from seed
2026, four domains (spending, food, training, body), eleven skills, and a
deterministic scorer for every answer type but free text.
