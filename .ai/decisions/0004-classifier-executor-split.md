# 0004 — Probabilistic classifier is split from the deterministic executor

## Decision
The classifier (uncertain, LLM-backed) **proposes**; the executor (deterministic, no model call)
is the only thing that **writes**. The LLM never both judges and acts unsupervised.

**Confidence-gated autonomy** — not binary human-in-loop:
- High confidence → auto-apply, logged with a justification.
- Low/mid confidence → review queue.
- Contradictions → review queue regardless of confidence (never auto-applied).
- The threshold is tunable and should move on measured revert rate.

This split is the architectural contribution to protect. Not "we use an LLM" — everyone does —
but that the LLM's output is a proposal a deterministic layer adjudicates.

## Rationale
A wrong auto-applied classification is a `git revert` + re-derive from the immutable episodic
tier, never permanent loss (ARCHITECTURE.md §2). That immutable backstop is what lets Recall set
its autonomy threshold higher than append-only competitors safely can.

## Status in codebase — MATCHES
- `src/consolidate/classifier.py` — emits `{classification, confidence, reasoning,
  conflicting_fact_id}`, applies no consequence.
- `src/consolidate/executor.py` — "Pure lookup table — no model calls, no judgment."
- `DEFAULT_CONFIDENCE_THRESHOLD = 0.90`; `contradiction` always → `REVIEW`; sub-threshold
  `update`/`context_dependent_both` → `REVIEW`.
- Phase 6 (`src/verify/`) adds a **second** deterministic gate: a flagged auto-apply decision is
  downgraded to `REVIEW` (`src/consolidate/run.py`). Strengthens this decision; does not
  contradict it. Verification never auto-corrects.

## Conflicts / gaps
None. This is the most fully realised of the six constraints.
