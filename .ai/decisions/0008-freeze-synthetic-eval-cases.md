# 0008 — Freeze hand-authored / synthetic eval-case creation

## Decision
Stop adding new hand-authored or synthetic cases to the eval sets
(`eval/classifier_set/`, `eval/verification_set/`, `eval/faithfulness_set/`). The 76-case real
classifier set and the 28-case verification set are frozen at their current size for v1.

Exceptions — still allowed:
- **Real cases from real usage.** A genuine capture-vs-fact conflict encountered while actually
  using Recall can be added, labelled, with its real provenance.
- **Regeneration, not expansion.** `eval/verification_set/generate.py` may be re-run to
  reproduce the existing set.

## Rationale
- **Diminishing returns.** Phase 2 accuracy has sat in a narrow band (58.7–60.9%) across every
  run and every set size (46 → 76). Batch 2 (30 new hand-authored cases) moved the headline by
  ~1 point. More of the same will not tell us anything new.
- **Overfitting risk, both directions.** The verifier's lexical cues were authored against the
  known-failure cases (`eval/COMBINED_CORRUPTION.md` calls the `ex_044` catch near-circular).
  Adding more hand-authored cases in the same style measures how well the check fits *our
  phrasing*, not how well it generalises. The batch-1/batch-2 split is the only real
  generalisation probe and it is already thin.
- **The real signal source is now available.** Phase 7's correction log
  (`wire-phase7-correction-log`) plus real daily usage (`start-daily-usage`) will produce
  naturally-occurring labelled examples. That is the corpus that matters for
  `retraction-classifier-revisit`; synthetic cases would dilute it.

## Status in codebase — MATCHES
- `eval/classifier_set/real_examples.yaml`: 76 cases, canonical, not to be extended.
- `eval/verification_set/verification_set.yaml`: 28 cases, regenerable.
- No code enforces this; it is a process constraint on future eval work. Relates to
  [0003](0003-classification-accuracy-ceiling.md) (measure, don't inflate) and
  [0007](0007-dogfood-recall-on-its-own-build.md) (real build history as corpus).

## Conflicts / gaps
Task `retraction-classifier-revisit` must not be started until the correction log holds real
retraction examples — this decision is the reason its "not before" constraint exists.
