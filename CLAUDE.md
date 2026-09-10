<!-- aiw:begin generated v1 -->
# AIW bootstrap

Run `aiw load` from this repository before exploring. The `aiw` CLI must be on
`PATH`; install it from the AIW source repository if it is missing. Use the
`aiw-workspace` skill for adoption, recovery, verification, and handoff.
Read `.ai/policy.md` once, then use `aiw show task ID` for the selected task.
Canonical project state is `.ai/state.json`; decisions are `.ai/decisions/`.
Use `aiw verify ID --allow-exec` for declared checks after reviewing commands.
Persist results with `aiw task transition` and next actions with `aiw checkpoint`.
This block is generated; vendor-specific guidance belongs outside the markers.
<!-- aiw:end -->

# Recall project

You are building Recall using two tools you must dogfood:

- **AIW** — the task/decision tracker. `aiw load` first; work the active task; `aiw verify`
  before `done`; checkpoint before stopping. `.ai/state.json` + `.ai/decisions/` are ground
  truth for what is built and what is left — trust them over your own memory of progress.
- **Recall itself** — its own `recall` CLI (`.venv/bin/recall`, `--help` for commands). As you
  work a task, run `recall capture --source <task-id> "<the decision / conflict / correction>"`
  for anything non-obvious, **before** transitioning that task to `done`. This build is Recall's
  first real corpus (see `.ai/decisions/0007`). If Recall later consolidates or retrieves its
  own build history badly, that is a finding to surface in `eval/DOGFOOD_FINDINGS.md`, not to
  hide.

Read `ARCHITECTURE.md` and `BUILD_PLAN.md` for the design; `.ai/decisions/0001`-`0007` are the
locked constraints and their current status against the code. Commit per task, directly to
`master`, push when the suite is green.
