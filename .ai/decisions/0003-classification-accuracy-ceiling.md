# 0003 — Conflict-classification accuracy ceiling is a stated constraint, not a bug

## Decision
Three-way conflict classification (contradiction / update / context-dependent-both) has a
**measured research ceiling of ~65.3%** (best published model, Gemini 2.5 Flash, CONFLICTS
benchmark). Implicit conflicts requiring inference score far lower (~17.6%). Weak/non-reasoning
models collapse (observed 1/9).

This is kept **visible**, not hidden. Any change to the classifier must **report its own
measured accuracy on the real eval set** (`eval/classifier_set/real_examples.yaml`), never an
assumed or hoped-for number. "Fixing" a low number by inflating confidence or picking a
convenient framing is prohibited.

## Rationale
The product claim is "honest about its own error rate". A silently optimistic classifier breaks
that claim directly. The confidence threshold is meant to move on **measured revert rate**, not
a one-time guess (ARCHITECTURE.md §2).

## Status in codebase — MATCHES, and already enforced
- `eval/PHASE2_FINDINGS.md`, `eval/PHASE2_FOLLOWUP_FINDINGS.md`, `eval/PHASE2_V2_BASELINE.md`
  all report measured confusion matrices and accuracy.
- Recall's own measured accuracy on the 76-case real set is **60.5% overall / 55.3% hard** —
  *below* the 65.3% ceiling, and documented as such.
- The `prior_fact_was_valid_when_recorded` prompt-fix attempt was **reverted** specifically
  because three variants measured 39–50% vs a 58.7% baseline (`PHASE2_FOLLOWUP_FINDINGS.md`).
- `DEFAULT_CONFIDENCE_THRESHOLD = 0.90` in `src/consolidate/executor.py` is justified by
  measured SEV1 (silent-corruption) counts, not a guess.

## Conflicts / gaps
Minor wording: the codebase docs phrase the ceiling as "~65.3%" / "the general 65.3% ceiling".
ARCHITECTURE.md §2 does name the **CONFLICTS benchmark** and attributes 65.3% to Gemini 2.5
Flash. Consistent with the constraint as stated.
