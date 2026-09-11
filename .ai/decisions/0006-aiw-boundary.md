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

## Status in codebase — MATCHES
- The AIW side is still read-only by construction: no AIW-specific reader exists (Recall does
  not read `.ai/` at all), and Recall's consolidation writes only to `brain/`.
- The other half — the session-start-safe boundary on Recall's *own* read path — is now
  implemented: `recall inject --for-session` (`src/inject/session_start.py`) reads only
  `brain/semantic/facts/` Markdown, makes zero network or model calls (the module imports
  nothing that could), and writes nothing anywhere — no index build, unlike the query-time
  `recall retrieve` path. Measured < 150ms at 100 facts (`tests/test_session_start.py`).
- This repo contains AIW's own files under `.ai/`, `.agents/`, `.codex/`, `.claude/`, separate
  from `brain/`.
- Consistent with `BUILD_PLAN.md` §7: "Scheduled/automatic consolidation triggers — manual
  invocation is fine until the manual version is trusted."
- Task **aiw-readonly-integration** (plan `recall-v1`) implemented this. Not yet done: actually
  wiring `recall inject --for-session` into a `.claude/`/`.codex/` hook — out of scope for that
  task by its own constraint ("just the readable command").

## Conflicts / gaps
None with baked decisions. This is a forward constraint on work not yet done.
