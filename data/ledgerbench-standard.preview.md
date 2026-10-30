# LedgerBench standard preview

Seed 2026, version 1.0, generated 2026-10-30. This page shows one user; the JSON has 12.

```
standard: 12 users, 480 questions

              lookup aggregate     group    window     state     as_of    change correctio     cross adherence    budget  questions
spending          17        69        16        31        26         8        20        38         .         .        18        167
food               8        33         6        11        13        10        20        27         .         9         .         93
training          18        34         5        13        11         6         4        13         .        12         .         88
body              24        35         9        15         5        10        15        23         .         .         .         98
cross              .        34         .         .         .         .         .        11        34         .         .         34

answer types: number 350 (72.9%), count 64 (13.3%), category 42 (8.8%), date 15 (3.1%), set 6 (1.2%), text 3 (0.6%)
correction-flagged: 112 (23.3%)   cross: 34 (7.1%)
messages per user: 388-625 (mean 503, total 6039); events per user: 412-791 (total 7300)
logged records 6443: corrections 192 (3.0%), retractions 65 (1.0%)
logged late: 660 (10.2%)
```

## Owen (u1, USD, body weight in lb, lifts in lb)

Tracks spending, food, training, body. Profile: I'm Owen, an architect in Chicago, trying to spend more deliberately, counting what I eat, lifting a few times a week and tracking my weight and sleep.

### The first seven sessions

**Thursday 2026-01-22**

0. So you know: my rent is $1,370, paid on the 1st of every month.
1. Slept 7h45.
2. I pay $49 a month for the gym, it renews on the 26th.
3. Aiming for 2,100 calories a day.
4. Here's my training plan: Monday upper, Tuesday lower, Thursday upper, Friday lower, everything else rest. Upper is bench press 4x6 @ 145, BB rows 4x8 @ 140, overhead press 3x8 @ 90, lat pulldowns 3x10 @ 125, bicep curls 3x12 @ 30. Lower is squats 5x5 @ 155, deads 3x5 @ 370, hip thrusts 3x10 @ 185lbs, hamstring curls 3x12 @ 90.
5. Cappuccino and a pastry, $4.02.
6. Lunch out, poke bowl, 17.20 dollars.
7. Dinner was salmon 451 calories, rice 260 kcal and steak 513.
8. Upper day: bench: 4 sets of 6 at 145, barbell rows 140 for 8, 8, 8, 6, OHP 3x8 at 90lbs, pulldowns: 3 sets of 10 at 125, bicep curls 3x12 at 30 lbs.

**Friday 2026-01-23**

0. 189.4 on the scale.
1. iCloud is $2.99 a month, taken on the 19th.
2. Disney+ is $13.99 a month, taken on the 9th.
3. Missed this yesterday: breakfast: smoothie 280 calories; lunch: ham sandwich 408 calories.
4. Breakfast: avocado 152 kcal and Greek yogurt 142; for lunch, poke bowl 620 kcal and chicken wrap 546 kcal.
5. For a snack, dark chocolate 187 kcal.
6. For a snack, apple 105 kcal.
7. Drinks and tapas after work, 78.44 dollars.
8. For dinner, stir fry 472 kcal, rice 260 kcal and green salad 90.
9. Gym, lower: back squats: 5 sets of 5 at 155lbs, deads 370 lbs for 5, 5, 3, hip thrusts 185 for 10, 10, 9, hamstring curls 90 for 12, 12, 11.

**Saturday 2026-01-24**

0. 6 hours 15 of sleep.
1. Internet is $65 a month, billed on the 10th.
2. Breakfast was bagel 280 kcal.
3. Coffee and a croissant, 4.83.
4. Groceries at Whole Foods: 75.07 dollars.
5. A snack: protein bar 200 kcal.
6. Ordered Indian takeaway, 57.80.
7. Lunch: leftover lasagne 610 calories and lentil soup 294; dinner: stir fry 572 kcal and green salad 90.
8. Wrote the wrong number, the stir fry at dinner yesterday was 572 calories. Not 472.
9. New rule: $400 a month max on eating out, starting next month.

**Sunday 2026-01-25**

0. Morning numbers: weighed 189.4 and sleep was six and a half hours.
1. Catching up, Friday: oat latte, 4.02. Overpriced but needed.
2. Lunch was leftover lasagne 610 cals and chicken wrap 546 calories.
3. Steps: 10189.
4. New rule: $410 a month max on groceries, starting next month.
5. Work review went fine, nothing dramatic.

**Monday 2026-01-26**

0. Weighed 188.8lbs.
1. From yesterday, forgot to log it: dinner: 4 slices of pizza at 285 each, spaghetti bolognese 748 cals and green salad 90 cals.
2. Cappuccino and a pastry, $5.17.
3. Metro card top-up, 28.75.
4. From yesterday, forgot to log it: a rain jacket, 64.08. Needed it.
5. Topped up on groceries at Whole Foods, $91.87.
6. Breakfast: bagel 280 calories, smoothie 280 and Greek yogurt 142 cals; dinner was green salad 90 cals.
7. Upper session: bench 145lbs for 4 sets of 6, BB rows 4x8 @ 140, overhead press 90 lbs for 3 sets of 8, pulldowns 3x10 @ 125.
8. Walked a lot, 6,553 steps.
9. Quiet evening, early night.

**Tuesday 2026-01-27**

0. H-E-B run, 9.49.
1. Gym, lower: back squats 5x5 at 155lbs, deadlifts 3x5 @ 370, hip thrusts: 3 sets of 10 at 185.
2. Deadlifts go to 3x12 instead of 3x5 from Monday, same weight.

**Wednesday 2026-01-28**

0. 8h45 of sleep.
1. Forgot to say, yesterday: six and a half hours of sleep.
2. From Monday, forgot to log it: the gym renewed, $49.
3. Logging all my food today. For breakfast, 2 eggs, 148 cals. Lunch was burrito bowl 715 kcal. Dinner was sweet potato 171 calories, salmon 451 and stir fry 572.

### A sample of events

```json
{"id": "u1:e231", "type": "expense", "date": "2026-02-20", "session_date": "2026-02-21", "message": 1, "amount": 33.24, "category": "eating out", "note": "dinner out"}
{"id": "u1:e61", "type": "refund", "date": "2026-01-29", "session_date": "2026-01-29", "message": 3, "amount": 64.08, "refers_to": "u1:e43"}
{"id": "u1:e389", "type": "split", "date": "2026-03-13", "session_date": "2026-03-13", "message": 5, "person": "Nina", "amount": 132.5, "owed": 66.25, "refers_to": "u1:e388"}
{"id": "u1:e177", "type": "settled", "date": "2026-02-14", "session_date": "2026-02-14", "message": 3, "person": "Jo", "amount": 56.58, "refers_to": "u1:e122"}
{"id": "u1:e3", "type": "recurring", "date": "2026-01-22", "session_date": "2026-01-22", "message": 2, "name": "the gym", "category": "subscriptions", "amount": 49.0, "day": 26}
{"id": "u1:e399", "type": "price_change", "date": "2026-03-15", "session_date": "2026-03-15", "message": 1, "amount": 4.49, "from": "2026-03-19", "refers_to": "u1:e11"}
{"id": "u1:e38", "type": "budget", "date": "2026-01-25", "session_date": "2026-01-25", "message": 4, "category": "groceries", "amount": 410.0, "from": "2026-02-01"}
{"id": "u1:e225", "type": "meal", "date": "2026-02-20", "session_date": "2026-02-20", "message": 4, "meal": "breakfast", "items": [{"name": "bagel", "qty": 1, "kcal": 280}, {"name": "smoothie", "qty": 1, "kcal": 280}]}
{"id": "u1:e4", "type": "kcal_target", "date": "2026-01-22", "session_date": "2026-01-22", "message": 3, "amount": 2100, "from": "2026-01-22"}
{"id": "u1:e187", "type": "plan_change", "date": "2026-02-15", "session_date": "2026-02-15", "message": 4, "from": "2026-02-16", "change": "Lower moves from Tuesdays to Sundays from Monday.", "plan": {"days": {"Monday": "Upper", "Tuesday": "Rest", "Wednesday": "Rest", "Thursday": "Upper", "Friday": "Lower", "Saturday": "Rest", "Sunday": "Lower"}, "sessions": {"Upper": [{"exercise": "bench press", "sets": 4, "reps": 6, "weight": 145.0}, {"exercise": "barbell row", "sets": 4, "reps": 8, "weight": 140.0}, {"exercise": "overhead press", "sets": 3, "reps": 8, "weight": 90.0}, {"exercise": "lat pulldown", "sets": 3, "reps": 10, "weight": 125.0}, {"exercise": "biceps curl", "sets": 3, "reps": 12, "weight": 30.0}], "Lower": [{"exercise": "back squat", "sets": 5, "reps": 5, "weight": 155.0}, {"exercise": "deadlift", "sets": 3, "reps": 12, "weight": 370.0}, {"exercise": "hip thrust", "sets": 3, "reps": 10, "weight": 185.0}, {"exercise": "leg curl", "sets": 3, "reps": 12, "weight": 90.0}]}}}
{"id": "u1:e243", "type": "workout", "date": "2026-02-20", "session_date": "2026-02-22", "message": 1, "session": "Lower", "exercises": [{"name": "back squat", "sets": [{"reps": 5, "weight": 155.0}, {"reps": 5, "weight": 155.0}, {"reps": 5, "weight": 155.0}, {"reps": 5, "weight": 155.0}, {"reps": 4, "weight": 155.0}]}, {"name": "deadlift", "sets": [{"reps": 12, "weight": 370.0}, {"reps": 12, "weight": 370.0}, {"reps": 11, "weight": 370.0}]}, {"name": "hip thrust", "sets": [{"reps": 10, "weight": 185.0}, {"reps": 10, "weight": 185.0}, {"reps": 8, "weight": 185.0}]}, {"name": "leg curl", "sets": [{"reps": 12, "weight": 90.0}, {"reps": 12, "weight": 90.0}, {"reps": 12, "weight": 90.0}]}]}
{"id": "u1:e253", "type": "skip", "date": "2026-02-23", "session_date": "2026-02-23", "message": 5, "session": "Upper", "reason": "had to cover for a colleague"}
{"id": "u1:e273", "type": "weight", "date": "2026-02-27", "session_date": "2026-02-27", "message": 0, "value": 187.7, "unit": "lb"}
{"id": "u1:e212", "type": "sleep_hours", "date": "2026-02-19", "session_date": "2026-02-19", "message": 0, "value": 6.5}
{"id": "u1:e293", "type": "steps", "date": "2026-03-01", "session_date": "2026-03-01", "message": 4, "value": 3806}
{"id": "u1:e234", "type": "correction", "date": "2026-02-15", "session_date": "2026-02-21", "message": 4, "field": "value", "value": 6675, "was": 5675, "refers_to": "u1:e186"}
{"id": "u1:e223", "type": "retraction", "date": "2026-02-13", "session_date": "2026-02-20", "message": 2, "refers_to": "u1:e168"}
{"id": "u1:e182", "type": "distractor", "date": "2026-02-14", "session_date": "2026-02-14", "message": 8, "numbers": [21.0]}
```

### Twelve questions

**u1:q1** (training; as_of; set): On which days of the week was I scheduled to do lower sessions on 1 March 2026, by my training plan?

- gold: `["Saturday", "Sunday"]` (Saturday and Sunday)
- choices: 7; aliases: `{"Saturday": ["Saturday", "Saturdays", "Sat"], "Sunday": ["Sunday", "Sundays", "Sun"]}`
- evidence (1): u1:e276
- derivation: `{"op": "as_of", "on": "2026-03-01", "of": {"kind": "plan", "extract": "days_for", "session": "Lower"}, "after": ["corrections", "retractions"]}`

**u1:q3** (food; window, aggregate, correction; number): What was my average daily calorie intake on weekends (Saturday and Sunday) between 8 March and 1 April 2026 inclusive, counting only days I logged food?

- gold: `1898.0` (1898 kcal)
- evidence (21): u1:e342, u1:e343, u1:e345, u1:e386, u1:e395, u1:e396, u1:e397, u1:e404, u1:e405, u1:e406, u1:e447, u1:e448 ...
- derivation: `{"op": "avg", "type": "meal", "from": "2026-03-08", "to": "2026-04-01", "field": "items.*.kcal", "per": "date", "weekdays": ["Saturday", "Sunday"], "round": 1, "after": ["corrections", "retractions"]}`

**u1:q4** (spending; window, aggregate, correction; count): How many times did I eat out or get takeaway (lunches out included) between 31 January and 21 February 2026 inclusive?

- gold: `9` (9 times)
- evidence (11): u1:e106, u1:e121, u1:e129, u1:e145, u1:e147, u1:e154, u1:e181, u1:e217, u1:e224, u1:e231, u1:e235
- derivation: `{"op": "count", "type": "expense", "where": {"category": "eating out"}, "from": "2026-01-31", "to": "2026-02-21", "after": ["corrections", "retractions"]}`

**u1:q7** (cross; cross, aggregate, correction; number): How much did I spend on coffee (coffee and pastries at cafés) between 20 February and 22 March 2026 inclusive on days after a night of under 7 hours' sleep (the sleep I logged that morning)?

- gold: `24.02` (24.02 USD)
- evidence (15): u1:e230, u1:e255, u1:e256, u1:e316, u1:e318, u1:e380, u1:e385, u1:e402, u1:e409, u1:e412, u1:e423, u1:e425 ...
- derivation: `{"op": "sum", "type": "expense", "where": {"category": "coffee"}, "from": "2026-02-20", "to": "2026-03-22", "field": "amount", "net_refunds": true, "days": {"below": {"type": "sleep_hours", "field": "value", "value": 7}}, "round": 2, "after": ["corrections", "retractions"]}`

**u1:q13** (body; change, correction; number): On average, how many fewer steps a day did I log in March 2026 than in February 2026?

- gold: `218.6` (218.6 steps)
- evidence (31): u1:e116, u1:e148, u1:e153, u1:e156, u1:e170, u1:e186, u1:e211, u1:e220, u1:e232, u1:e234, u1:e236, u1:e262 ...
- derivation: `{"op": "diff", "left": {"op": "avg", "type": "steps", "from": "2026-02-01", "to": "2026-02-28", "field": "value"}, "right": {"op": "avg", "type": "steps", "from": "2026-03-01", "to": "2026-03-31", "field": "value"}, "round": 1, "after": ["corrections", "retractions"]}`

**u1:q18** (food; change, correction; number): How many more calories a day did I eat on average in March 2026 than in February 2026, counting only days I logged food?

- gold: `112.3` (112.3 kcal)
- evidence (166): u1:e78, u1:e80, u1:e81, u1:e82, u1:e85, u1:e88, u1:e90, u1:e91, u1:e93, u1:e97, u1:e98, u1:e99 ...
- derivation: `{"op": "diff", "left": {"op": "avg", "type": "meal", "from": "2026-03-01", "to": "2026-03-31", "field": "items.*.kcal", "per": "date"}, "right": {"op": "avg", "type": "meal", "from": "2026-02-01", "to": "2026-02-28", "field": "items.*.kcal", "per": "date"}, "round": 1, "after": ["corrections", "retractions"]}`

**u1:q22** (cross; cross, aggregate; number): How much did I spend on coffee (coffee and pastries at cafés) in April 2026 on days after a night of under 7 hours' sleep (the sleep I logged that morning)?

- gold: `14.36` (14.36 USD)
- evidence (9): u1:e524, u1:e525, u1:e551, u1:e552, u1:e575, u1:e585, u1:e621, u1:e629, u1:e639
- derivation: `{"op": "sum", "type": "expense", "where": {"category": "coffee"}, "from": "2026-04-01", "to": "2026-04-21", "field": "amount", "net_refunds": true, "days": {"below": {"type": "sleep_hours", "field": "value", "value": 7}}, "round": 2, "after": ["corrections", "retractions"]}`

**u1:q23** (body; lookup, correction; number): What did I weigh on 25 March 2026, in lb?

- gold: `183.6` (183.6 lb)
- evidence (2): u1:e462, u1:e490
- derivation: `{"op": "lookup", "type": "weight", "from": "2026-03-25", "to": "2026-03-25", "field": "value", "round": 1, "after": ["corrections", "retractions"]}`

**u1:q28** (body; lookup, correction; number): How many hours did I sleep the night before 25 March 2026?

- gold: `8.0` (8 hours)
- evidence (2): u1:e463, u1:e527
- derivation: `{"op": "lookup", "type": "sleep_hours", "from": "2026-03-25", "to": "2026-03-25", "field": "value", "round": 2, "after": ["corrections", "retractions"]}`

**u1:q30** (training; lookup, correction; number): What weight did I use for hip thrust on 28 March 2026, in lb?

- gold: `190.0` (190 lb)
- evidence (2): u1:e493, u1:e507
- derivation: `{"op": "lookup", "type": "workout", "unnest": "exercises", "where": {"name": "hip thrust"}, "from": "2026-03-28", "to": "2026-03-28", "field": "sets.*.weight", "within": "max", "round": 2, "after": ["corrections", "retractions"]}`

**u1:q33** (spending; change, correction; number): How much more did I spend on transport (taxis, transit and fuel, not trip travel) in March 2026 than in February 2026?

- gold: `45.98` (45.98 USD)
- evidence (11): u1:e87, u1:e105, u1:e140, u1:e190, u1:e248, u1:e295, u1:e350, u1:e403, u1:e408, u1:e457, u1:e506
- derivation: `{"op": "diff", "left": {"op": "sum", "type": "expense", "where": {"category": "transport"}, "from": "2026-03-01", "to": "2026-03-31", "net_refunds": true, "field": "amount"}, "right": {"op": "sum", "type": "expense", "where": {"category": "transport"}, "from": "2026-02-01", "to": "2026-02-28", "net_refunds": true, "field": "amount"}, "round": 2, "after": ["corrections", "retractions"]}`

**u1:q36** (spending; change, correction; number): How much more did I spend on coffee (coffee and pastries at cafés) in March 2026 than in February 2026?

- gold: `28.72` (28.72 USD)
- evidence (35): u1:e96, u1:e104, u1:e112, u1:e119, u1:e139, u1:e152, u1:e160, u1:e189, u1:e205, u1:e207, u1:e222, u1:e223 ...
- derivation: `{"op": "diff", "left": {"op": "sum", "type": "expense", "where": {"category": "coffee"}, "from": "2026-03-01", "to": "2026-03-31", "net_refunds": true, "field": "amount"}, "right": {"op": "sum", "type": "expense", "where": {"category": "coffee"}, "from": "2026-02-01", "to": "2026-02-28", "net_refunds": true, "field": "amount"}, "round": 2, "after": ["corrections", "retractions"]}`
