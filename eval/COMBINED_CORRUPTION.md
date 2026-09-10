# Combined end-to-end silent-corruption rate

**Question:** with both shipped safety layers active — the 0.90 confidence gate *and* the
deterministic verifier — how many true SEV1 cases in the 76-case real set
(`eval/classifier_set/real_examples.yaml`) still silently corrupt the semantic tier?

**Answer: 0 of 76 on this corpus.** Reproduce with `.venv/bin/python eval/run_combined.py`.

## What counts as SEV1

A new capture that **retracts an existing fact as wrong-when-made** (truth = `contradiction`,
must go to review) which the classifier instead labelled `update` / `context_dependent_both`
with enough confidence that the executor would auto-apply it as a destructive `SUPERSEDE` /
`DUAL_RETAIN`. This is the one failure that invalidates or dual-retains a fact without a human in
the loop. `eval/PHASE2_V2_BASELINE.md` identified **7 of 76** (`ex_003`, `ex_023`, `ex_040`,
`ex_044`, `ex_051`, `ex_052`, `ex_069`), classifier `claude-sonnet-5`.

## The two layers, case by case

| case | classifier said | conf | stopped by | reached verifier? |
|---|---|---|---|---|
| ex_003 | update | 0.85 | confidence gate → review | no |
| ex_023 | update | 0.85 | confidence gate → review | no |
| ex_040 | context_dependent_both | 0.60 | confidence gate → review | no |
| ex_044 | update | 0.92 | **deterministic verifier** → review | yes, flagged |
| ex_051 | update | 0.85 | confidence gate → review | no |
| ex_052 | update | 0.78 | confidence gate → review | no |
| ex_069 | context_dependent_both | 0.72 | confidence gate → review | no |

- **6 of 7** are caught by the confidence gate alone: the classifier happened to assign them
  < 0.90.
- **1 of 7** (`ex_044`, 0.92) clears the gate on a mistake and is caught only by the verifier's
  lexical retraction check ("The direction is backwards").
- **0 of 7** reach the semantic tier.

## Caveats — why "0/76" is not "solved"

1. **Overfitting risk.** The verifier's lexical cues were authored against these same cases.
   `ex_044` being caught is partly circular. The batch-1 vs batch-2 split in
   `eval/PHASE6_FINDINGS.md` is the only generalisation probe, and its n is tiny (3–4 held-out
   analogues). A real retraction phrased in words no cue matches is not covered — see
   `LIMITATIONS.md`.
2. **The gate's 6/7 is luck, not design.** Nothing forces a misclassified retraction to score
   < 0.90. The classifier already gave `ex_044` 0.92 on a mistake, and `eval/PHASE2_V2_BASELINE.md`
   notes wrong auto-applies are "interleaved with correct ones" across the confidence range. A
   future retraction mislabelled `update` at ≥ 0.90 confidence **and** phrased without a
   first-person lexical cue would leak through both layers. That combination did not occur in
   these 76 cases; it is not structurally prevented.
3. **Missed corrections are separate and not counted here.** The full-76 confusion matrix in
   `eval/PHASE2_V2_BASELINE.md` shows 1 truth-`contradiction` case classified `new` → `WRITE_NEW`
   (no gate, no verifier). That does not invalidate or dual-retain anything, so it is not silent
   *corruption*, but the wrong-when-made fact does stay in the store uncorrected while the
   retraction is filed as an unrelated new fact.

## Method

`eval/run_combined.py` loads the 7 SEV1 rows from `eval/verification_set/verification_set.yaml`
(classifier label + confidence mirror `eval/PHASE2_V2_BASELINE.md`), runs each through
`src.consolidate.executor.decide` (the real 0.90 gate) and, for anything that clears the gate,
through `src.verify.verify(..., use_nli=False)` (the shipped verifier config, as wired in
`src.consolidate.run.run`). No model calls; deterministic and re-runnable.
