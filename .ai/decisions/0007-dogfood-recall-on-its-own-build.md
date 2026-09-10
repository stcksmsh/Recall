# 0007 — Dogfood Recall on its own development

## Decision
This build is Recall's first real corpus. Every agent working plan `recall-v1`:

1. **Captures as it goes.** Before transitioning any AIW task to `done`, run `recall capture`
   for each non-obvious decision made, conflict hit, owner correction received, or surprising
   thing discovered while doing that task. One capture per distinct point; `--source` names the
   task id. Captures are append-only — never rewrite a capture to make later consolidation look
   good.
2. **Runs the loop against this history.** Task `dogfood-consolidation` runs `recall consolidate
   run` over the accumulated captures and writes `eval/DOGFOOD_FINDINGS.md` answering: does
   retrieval actually surface *"why the dual-representation split"* and *"why the executor
   distrusts low-confidence classifications"* the way it is supposed to for any other project,
   months from now?
3. **Treats a bad result as signal, not a side detail.** If Recall consolidates or retrieves its
   own build history poorly, `DOGFOOD_FINDINGS.md` says so plainly and it is filed as a real
   finding about Recall's quality. Do not paper over it, do not tune the eval to hide it.

## Rationale
A memory system that cannot remember why its own architecture was chosen is not doing its job.
Its own build is the cheapest, highest-signal test corpus available, and the decisions here
(0001–0006) are exactly the kind of "why did we do X" a user would query months later.

## Status in codebase
- `recall capture` works today (Phase 1). No model call, no key needed.
- Consolidation (`recall consolidate run`) needs `ANTHROPIC_API_KEY` and uses the real
  classifier — measured, per invariant 6.
- First captures already exist under `brain/episodic/2026/09/` (AIW adoption, the six
  constraints, the two gaps).

## Conflicts / gaps
`dogfood-consolidation` acceptance already requires "captures exist for the material decisions
of this build" — so a session that skips capture-as-it-goes will fail that task's acceptance
later. This decision makes the practice continuous rather than a scramble at the end.
