# Phase 2 follow-up — prompt fix attempt (part 1)

Companion to `PHASE2_FINDINGS.md`. Same harness (`eval/run_eval.py`), same 46-case real set
(`eval/classifier_set/real_examples.yaml`), same 22 `[HARD CASE]` markers. All runs are one real
inference call per example — no mock.

**Bottom line up front:** the prompt fix, in three variants, is a **net regression** on this
set. It is **not shipped** — `classifier.py` keeps the Phase 2 baseline prompt; only the
`parse_response` refactor is kept. (A cheaper-model comparison — Haiku 4.5, a local CPU 7B —
follows in a later commit, section 2.)

---

## Baseline (this session's re-run, for apples-to-apples)

Sonnet 5, Phase 2 prompt. Re-run because model output is non-deterministic and the Phase 2
`results_*.json` was not retained.

| | overall | hard (22) |
|---|---|---|
| this re-run | 27/46 = **58.7%** | 11/22 = **50.0%** |
| Phase 2 doc | 28/46 = 60.9% | 12/22 = 54.5% |

Run-to-run variance is ~2 points. Baseline confusion (rows expected, cols predicted):

```
                          new  update  contra  both  tot
new                        7      1       0      0    8
update                     0     10       5      1   16
contradiction              1      3       3      1    8
context_dependent_both     1      4       2      7   14
```

Four costly cases (Phase 2 SEV1 — wrong `update`/`both` at high confidence, truth
`contradiction`): **ex_003, ex_023, ex_040, ex_044 — all four wrong in the baseline re-run too.**

---

## 1. Prompt fix — three variants, all net-negative

The idea (from `PHASE2_FINDINGS.md`): make the model answer, per the JSON contract, whether the
prior fact was *valid when recorded and later superseded* (`update`) or *wrong from the start*
(`contradiction`), via a required `prior_fact_was_valid_when_recorded: true|false` field, and wire
`false` toward `contradiction`.

| variant | what changed | overall | hard | fixed vs baseline | regressions | SEV1 |
|---|---|---|---|---|---|---|
| **A** | full STEP 1 / STEP 2 rewrite, strong "false ⇒ contradiction" | 18/46 = 39.1%¹ | 12/22 = 54.5% | 3 | 12 | 0 |
| **B** | narrow `false` definition, rewritten class defs, `max_tokens` 1024 | 23/46 = 50.0% | 10/22 = 45.5% | 5 | 9 | 2 |
| **C** | baseline prompt + STEP 1 field only + deterministic guard (`false` + `update`/`both` → `contradiction`) | 23/46 = 50.0% | 14/22 = 63.6% | 7 | 11 | 3 |

¹ variant A also produced 3 hard JSON-truncation errors (the added reasoning blew past
`max_tokens=512`); even scoring those as "not wrong", it is 18/43 = 41.9%.

### Why it fails

Making the model reason explicitly about "was the prior fact valid" **reweights its entire
classification distribution**, not just the target boundary:

- Variant A/B: real `update` cases collapse into `contradiction` (A: 11 of 16 `update` →
  `contradiction`). The model rationalises nearly every conceptual refinement ("B is not a
  prediction box, it's a workspace") as "the original framing was an overstatement / wrong from
  the start."
- Variant C: adding the STEP 1 question destroys `new` detection — **all 8 `new` cases →
  `context_dependent_both`**. Prompted to find "the single most-related existing fact" and judge
  its validity, the model stops concluding "no meaningful overlap."
- The deterministic guard (variant C) fired on 3 cases: it corrected ex_003 and ex_044, and
  **broke ex_006** (a real `update` the model had right). Net +1 on 46 cases — noise.

The four costly cases: variant C fixed ex_003 and ex_044 (both via the guard) but ex_023 and
ex_040 stayed wrong (the model rated their prior fact *valid*, so the guard never engaged), and
SEV1 was still 3 (ex_023, ex_037, ex_040).

### Decision

**Reverted.** `classifier.py` keeps the Phase 2 baseline prompt verbatim. The 46-case set does
not support any prompt-level fix, and every variant traded the target error for collateral
damage across the other three classes. The real backstop remains Phase 6 verification (as
`PHASE2_FINDINGS.md` already concluded); the confidence gate stays at 0.90.

Kept from this pass: `classifier.parse_response()` split out of `classify()` so that other
callers (e.g. the model comparison in section 2) can feed raw model output through the identical
parser.

