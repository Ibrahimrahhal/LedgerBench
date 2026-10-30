# LedgerBench leaderboard

Built by `ledgerbench leaderboard` from every `summary.json` under `results/`. For each size, system and answer
model, the latest complete run. Accuracy is over scored answers; costs are in USD at list prices, ingestion apart
from answering. Systems are compared only within a table, where they share an answer model.

## standard

Dataset version 1.1, seed 2026.

### Answer model: gpt-6-luna

| System | Answer model | Accuracy | Spending | Food | Training | Body | Cross | Answered | Ingestion | Answering | Mean latency | Run |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| fullcontext (partial) | gpt-6-luna | 82.5% | 71.7% | 79.5% | 93.5% | 97.0% | 63.6% | 160/160 | $0.0000 | $0.33 | 8.60s | [luna-allfour](standard/fullcontext/luna-allfour) |
| openmate (partial) | gpt-6-luna | 68.8% | 56.5% | 76.9% | 67.7% | 81.8% | 54.5% | 160/160 | $5.30 | $0.37 | 8.95s | [luna-allfour](standard/openmate/luna-allfour) |
| mem0 (partial) | gpt-6-luna | 56.2% | 45.6% | 48.7% | 74.2% | 81.8% | 0.0% | 160/160 | $0.70 | $0.0515 | 4.46s | [luna-allfour](standard/mem0/luna-allfour) |
| rag (partial) | gpt-6-luna | 46.2% | 43.5% | 38.5% | 58.1% | 63.6% | 0.0% | 160/160 | $0.0016 | $0.0395 | 3.96s | [luna-allfour](standard/rag/luna-allfour) |
