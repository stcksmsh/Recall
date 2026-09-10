---
name: aiw-workspace
description: Resume, plan, execute, verify, checkpoint, or hand off coding work in a repository containing `.ai/state.json`; also use when asked to adopt AIW for unfinished work.
---

# AIW workspace

AIW state replaces conversation history as the durable record. The user's current
request remains authoritative; update AIW when it changes the recorded objective.

When `.ai/state.json` exists:

1. Run `aiw load` before broad repository exploration. Read `.ai/policy.md` once.
2. Run `aiw show task ID` for the selected task. If it is pending, claim it with
   a stable worker label before editing. Use `aiw probe` before broad source reads.
3. Work through the declared acceptance criteria and scope. Do not treat derived
   index data, an old checkpoint, or vendor memory as more authoritative than
   canonical state, Git, and source.
4. Inspect saved verification argv, then run `aiw verify ID --allow-exec`.
   Diagnose failures from compact receipts; fetch raw logs only when needed.
5. Before reporting completion, transition the task to `done` with a concrete
   result. If work cannot continue, checkpoint the exact next action and transition
   the task to `blocked` with the real reason before asking the user or stopping.
6. Checkpoint after meaningful progress, before likely context loss, and before
   handing work to another agent. Store facts and next action, not a transcript.

Strict lifecycle hooks may continue a turn once while an active task remains
pending or in progress. Finish it, or persist an honest blocked state; do not work
around the hook or claim success without fresh evidence.

For adopting AIW in an unfinished repository, read
[references/adopt.md](references/adopt.md). For handoff and recovery behavior,
read [references/lifecycle.md](references/lifecycle.md).
