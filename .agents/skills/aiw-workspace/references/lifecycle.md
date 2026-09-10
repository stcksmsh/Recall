# Recovery and handoff

At session start and after compaction, use the hook-provided recovery packet or run
`aiw load`. Drill down only through `status`, paged `list`, `show`, `probe`, and
targeted source inspection. Treat missing runtime logs as expected disposal; task
receipts remain, but fresh verification may still be required.

Before a planned handoff, checkpoint the remaining action and any non-obvious fact
the next agent cannot derive cheaply. The receiving agent should get only the task
ID, repository/branch location, and instruction to run `aiw load --task ID`.

When an agent disappears unexpectedly, inspect Git and AIW state. Persist a blocker
if ownership is uncertain. Reset blocked work to pending only after confirming the
checkout contains the intended edits, then claim it under the new worker identity.
Re-verify in the combined checkout before completion.
