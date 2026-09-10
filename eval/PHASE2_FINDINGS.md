# Phase 2 — Classifier eval findings

> **Reproducibility note (added later):** the runs below are on **batch 1 only** — the first 46
> cases (`ex_001`-`ex_046`) of `real_examples.yaml`. That file is now the 76-case canonical set
> (batch 2 = `ex_047`-`ex_076` merged in). To reproduce these exact numbers, filter to
> `ex_001`-`ex_046`. The 76-case baseline is in `eval/PHASE2_V2_BASELINE.md`.

Run: `python eval/run_eval.py` (real API, `claude-sonnet-5`, one call per example, no mock).
Dataset: `eval/classifier_set/real_examples.yaml` — 46 real examples pulled from actual
conversation history, 22 marked `[HARD CASE]`. The original 20 synthetic examples
(`example_*.yaml`) are still run and reported as a combined-66 number, but the threshold
decision is based on the real 46 only.

Raw per-example output (predicted label, confidence, reasoning) is written to
`eval/results_<timestamp>.json` on each run.

## Headline numbers (real 46)

| Slice | Accuracy |
|---|---|
| Real, all 46 | 28/46 = **60.9%** |
| Real, 22 hard cases | 12/22 = **54.5%** |
| Real, 24 easy cases | 16/24 = 66.7% |
| Combined 66 (real + synthetic) | 47/66 = 71.2% |

The general research ceiling cited in `ARCHITECTURE.md` §2 is ~65.3%. Domain-scoped accuracy on
this set is **at or below** that, not above it — the working assumption that "our facts are
narrower so we'll beat the ceiling" is not supported by this data.

## Confusion matrix — real 46 (rows = expected, cols = predicted)

```
                          new   update   contradiction   both    tot
new                        6      1            0           1       8
update                     0     11            4           1      16
contradiction              1      3            3           1       8
context_dependent_both     1      3            2           8      14
tot                        8     18            9          11      46
```

### Confusion matrix — 22 hard cases only

```
                          new   update   contradiction   both    tot
new                        1      0            0           0       1
update                     0      1            0           0       1
contradiction              1      3            2           0       6
context_dependent_both     1      3            2           8      14
tot                        3      7            4           8      22
```

The dominant error is the **update ↔ contradiction boundary**, in both directions:
- 4× `contradiction` called `update`
- 4× `update` called `contradiction`
- plus 3× `context_dependent_both` called `update` and 2× `contradiction` called `new`.

Three of the four `contradiction → update` misses are the same distinction: the new capture
**retracts the earlier fact as having been wrong when made**, not merely outdated (ex_003
"the earlier number was oversold", ex_023 company-laptop IP problem, ex_044 "reversing the
pitch… apparently erroneous framing"). The prompt in `classifier.py` never asks "was the prior
fact ever valid?" — that is the exact question these turn on.

## The threshold question

The executor gate only affects `update` / `context_dependent_both` predictions. `new` is
auto-applied unconditionally; `contradiction` always goes to review. So the only error a
confidence threshold can prevent is a wrong `update`/`both` that would otherwise auto-apply.

Gated (`update`/`both`) predictions on real 46: 29 total — 19 correct, 10 wrong.

**Confidences are fully interleaved between correct and wrong:**

```
correct gated auto-applies:  0.93, 0.90×5, 0.86, 0.85×3, 0.82, 0.78×3, 0.75, 0.72, 0.70×2, 0.65
wrong   gated auto-applies:  0.93, 0.85×2, 0.82, 0.78, 0.72, 0.70×2, 0.68, 0.62
```

The single most-confident gated prediction in the whole set (0.93) is a **tie**: one correct
(a real `update`) and one silent-corruption error (ex_044, a `contradiction` called `update`).

SEV1 — wrong `update`/`both` where the truth was `contradiction` (this silently corrupts the
semantic tier):

| id | predicted | confidence | note |
|---|---|---|---|
| ex_044 | update | **0.93** | pitch reversal framed as error-correction [HARD] |
| ex_003 | update | 0.85 | originality % "oversold", retracted [HARD] |
| ex_023 | update | 0.85 | company-laptop IP risk [HARD] |
| ex_040 | both | 0.70 | batch-API claim vs classifier.py |

Threshold utility on the real 46:

| threshold | correct auto-applied | wrong auto-applied | SEV1 through |
|---|---|---|---|
| 0.75 (old) | 15 | 5 | 3 |
| 0.80 | 11 | 4 | 2 |
| 0.85 | 10 | 3 | 2 |
| **0.90** | **6** | **1** | **1** |
| 0.95 | 0 | 0 | 0 |

There is **no threshold that stops all SEV1 errors while still auto-applying anything**: ex_044
sits at 0.93, and at 0.94+ zero correct predictions clear the gate either.

## Decision

`DEFAULT_CONFIDENCE_THRESHOLD`: **0.75 → 0.90.**

Justification, and its limits:
- 0.75 is **demonstrably unsafe** on real data — 3 silent-corruption auto-applies. It is not
  "fine".
- 0.90 is the highest value that still functions as a gate rather than an off switch: wrong
  gated auto-applies fall to their floor (1) and 6 correct ones still pass. Five correct
  predictions cluster exactly at 0.90, so 0.90-inclusive is meaningfully better than 0.91.
- 0.90 does **not** make the gate the real safety mechanism. ex_044 (0.93) still auto-applies.
  The classifier's self-reported confidence does not separate its worst mistakes from its
  correct calls, so no number here is fully defensible — 0.90 is the least-bad, not a solution.

What actually needs to happen (out of Phase 2 scope, do not do yet):
1. Prompt revision in `classifier.py` targeting the retracted-as-error vs. aged-out distinction
   — explicitly ask whether the prior fact was ever valid.
2. Phase 6 verification as the backstop for confident-but-wrong auto-applies.
3. Consider routing every `update`/`both` prediction that names a `conflicting_fact_id` to
   review in v1 regardless of confidence — the data does not yet support trusting that path.
4. More labeled data. 46 examples / 19 gated-correct is too thin to place a threshold to two
   decimals with real confidence.
