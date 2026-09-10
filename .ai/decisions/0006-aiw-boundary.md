# 0006 — Hard boundary between Recall and the sibling project AIW

## Decision
- Recall **only ever reads** AIW's tracked files (`.ai/state.json`, `.ai/decisions/`, …). It
  **never writes** to `.ai/`. Recall's write path targets only `brain/`.
- Recall's expensive work (LLM calls, consolidation) runs **entirely offline / in the
  background**, never inside a live session's startup path.
- A session-start hook that exposes Recall to an agent must do **only a cheap local read of the
  already-consolidated semantic tier** — no network, no LLM, no consolidation, bounded latency.

## Rationale
AIW is the durable task/decision record for this build; Recall is the subject being built. If
Recall wrote into `.ai/` it would corrupt its own ground truth. If Recall did expensive work at
session start it would make every agent session slow and non-deterministic — the opposite of
AIW's "cheap deterministic recovery" contract. This is the same principle as
[0002](0002-write-time-cost-discipline.md), applied at the integration seam.

## Status in codebase — NO CONFLICT; NOT YET IMPLEMENTED
- There is currently **no AIW integration in Recall's code** — no reader, no hook, nothing.
- This repo now contains AIW's own files under `.ai/`, `.agents/`, `.codex/`, `.claude/`. They
  are separate from `brain/`; Recall's consolidation writes only to `brain/`, so the read-only
  boundary holds by construction as long as that separation is kept.
- Consistent with `BUILD_PLAN.md` §7: "Scheduled/automatic consolidation triggers — manual
  invocation is fine until the manual version is trusted."
- Tracked as task **aiw-readonly-integration** under plan `recall-v1`.

## Conflicts / gaps
None with baked decisions. This is a forward constraint on work not yet done.
