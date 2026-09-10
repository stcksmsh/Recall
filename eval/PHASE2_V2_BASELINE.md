# Phase 2 baseline — full 76-case real set

`real_examples.yaml` is now the single canonical real set: 76 cases (`ex_001`-`ex_076`),
38 marked `[HARD CASE]`. Batch 1 = `ex_001`-`ex_046` (the set `PHASE2_FINDINGS.md` and
`PHASE2_FOLLOWUP_FINDINGS.md` ran on). Batch 2 = `ex_047`-`ex_076` (30 cases: binding-problem /
ant-colony, novelty-assessment-2, existence-proof, Recall-status sessions).

One run: current baseline prompt (`classifier.py`, post-revert, unchanged), `claude-sonnet-5`,
one API call per case, no mock. **The `prior_fact_was_valid_when_recorded` prompt fix is not
re-tested — three variants were already falsified on real data (see `PHASE2_FOLLOWUP_FINDINGS.md`
§1).** No threshold retune off this run.

## Headline

| slice | accuracy |
|---|---|
| overall (76) | **46/76 = 60.5%** |
| hard (38) | **21/38 = 55.3%** |
| easy (38) | 25/38 = 65.8% |

Consistent with the established range (Phase 2 58.7–60.9%, follow-up baseline 58.7%). Upper end,
not meaningfully different. Diff vs the batch-1 baseline JSON: 2 flips to correct, 1 to wrong
(ex_024) — run-to-run noise; the classifier is unchanged.

## Confusion matrix — full 76 (rows expected, cols predicted)

```
                        new  update  contra  both  tot
new                      11      2      0      6    19
update                    1     18      4      2    25
contradiction             1      5      5      2    13
context_dependent_both    2      3      2     12    19
tot                      15     28     11     22    76
```

Hard subset (38):
```
                        new  update  contra  both  tot
new                       1      0      0      3     4
update                    0      4      0      0     4
contradiction             1      5      4      1    11
context_dependent_both    2      3      2     12    19
```

## The informative check: "wrong-when-made" contradiction cases

Original costly-4 (batch 1) + the 4 batch-2 analogues (`ex_047`, `ex_051`, `ex_052`, `ex_069`),
plus `ex_050` (same category, also batch 2):

| id | batch | truth | predicted | conf | result | retraction style |
|---|---|---|---|---|---|---|
| ex_003 | 1 | contradiction | update | 0.85 | ✗ | "was oversold" |
| ex_023 | 1 | contradiction | update | 0.85 | ✗ | premise now false |
| ex_040 | 1 | contradiction | context_dependent_both | 0.60 | ✗ | design vs impl |
| ex_044 | 1 | contradiction | update | 0.92 | ✗ | "direction is backwards" |
| **ex_047** | 2 | contradiction | **contradiction** | 0.90 | **✓** | opens "That's wrong." |
| **ex_050** | 2 | contradiction | **contradiction** | 0.75 | **✓** | "directly conceded as false" |
| ex_051 | 2 | contradiction | update | 0.85 | ✗ | "I should be more careful… presented absence of knowledge as evidence of absence" |
| ex_052 | 2 | contradiction | update | 0.78 | ✗ | "I should have been harder on that step… gave it more weight than it deserved" |
| ex_069 | 2 | contradiction | context_dependent_both | 0.72 | ✗ | rebuts the premise |

**Combined recall on this category: 2/9.** The 4 new batch-2 "wrong-when-made" contradictions
(`ex_047/051/052/069`): **1/4 correct**, same as the original costly-4's 0/4.

**This is a general property of the classifier, not a quirk of the original 4 cases.** The
classifier maps "self-correction of an earlier judgment" to `update` — "supersedes the prior
estimate", "self-correction of the same metric", "retracts the assessment … supersedes the old
one" appear near-verbatim in its reasoning for ex_003, ex_051, ex_052. It only lands `contradiction`
when the capture uses blunt contradiction language up front ("That's wrong", "directly conceded as
false"); an epistemic or hedged retraction ("I should have been more careful") reads to it as a
normal update.

## The finer check: softened vs. retracted (ex_053)

`ex_053` — "'Extraordinary' is probably too strong … still a sharp analytical thinker" — truth
`update` (core claim survives, only the superlative softened). **Classified `update`, correct.**

But this is not the classifier *distinguishing* softening from retraction. It labels the whole
family `update` (`ex_051`, `ex_052`, `ex_053` all → `update`); `ex_053` is the one where `update`
is the right answer, so it scores. The retraction-vs-supersession boundary is not being drawn —
`ex_053` passing and `ex_051`/`ex_052` failing is one bias (toward `update`) landing correctly
once and wrongly twice.

## SEV1 (silent corruption: wrong `update`/`both`, truth `contradiction`)

7 of 76 (ex_003, ex_023, ex_040, ex_044, ex_051, ex_052, ex_069) — ~9%, same rate as the 46-case
runs (3–4 of 46). Confidences 0.60–0.92, still interleaved with correct auto-applies. No new
threshold justified; the gate stays 0.90. The fix is verification (Phase 6), which this run's
data now calibrates.
