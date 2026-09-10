# Adopt AIW in unfinished work

Run `aiw init` and `aiw integrate all --enforcement strict`. Inspect repository
structure, Git status, the current authoritative plan, recent commits, existing
agent instructions, and available verification commands. Do not assume an old
roadmap entry is the interrupted objective when later user requests or source
changes disagree.

Record a concise project description and only settled invariants in
`.ai/state.json`, then validate with `aiw doctor`. Create one plan for the current
coherent outcome and bounded tasks for actual executable units. Every task needs:

- acceptance criteria that distinguish success from code merely existing;
- relative scope paths and material constraints;
- literal verification argv with realistic timeouts;
- dependencies only where execution is actually blocked;
- an active task and checkpoint naming the next concrete action.

Measure the initial baseline through `aiw run`. A failing baseline is evidence to
persist, not permission to weaken acceptance. Keep prior vendor conversation out
of canonical state except for user intent or facts confirmed against the repository.
