# Entity/scope population at write time

**Task:** `entity-scope-and-aiw-import`.

**Question:** `src/retrieve/entity_scope.py` (entity/scope-anchored retrieval, the "primary path" per
BUILD_PLAN.md §2.3) is correct, but nothing upstream of it ever populated real `entity`/`scope`
values — `src/index/flush.py` has always accepted those parameters, every real caller left them at
the default (`entity="unsorted"`, `scope=None`). Confirmed consequence: two facts about a
same-named thing in two different projects return pooled and undifferentiated on lookup — no
project/namespace field at all. Does populating them at write time fix that?

## Fix

Two independent, both deterministic, no model call:

1. **`scope` ← project context, captured at write time.** `src/capture/capture.py::_detect_project`
   shells out to local `git rev-parse --show-toplevel` in the cwd at capture time and records the
   repo directory name as a new `project` frontmatter field on the episodic capture (`None` outside
   a git repo). `src/consolidate/run.py` reads that field back (from the index's existing
   `frontmatter_json` column — no schema change) and passes it straight through as `scope` when it
   flushes a fact.
2. **`entity` ← lexical identifier extraction over the capture text.** `src/consolidate/entity_extract.py`
   looks for backtick-quoted, snake_case, or CamelCase tokens (the shape a project/module/table
   name actually takes — the audit's own example, `the_database`, is exactly this). Zero
   candidates → `entity` stays `"unsorted"` (unchanged default, nothing to extract). One candidate,
   or one strictly most-frequent candidate → that's the entity, deterministically (repetition is
   counted, not guessed). A genuine tie between 2+ distinct candidates → **not** picked arbitrarily:
   `src/consolidate/run.py` reroutes the decision to the review queue instead, the same way an
   Phase 6 verifier flag already reroutes a risky auto-apply — no second, ungated way to resolve it
   was invented. `src/consolidate/review.py`'s human-resolve path runs the same extraction and
   defaults to `"unsorted"` on an ambiguous tie there (a human is already resolving that item; there's
   no further gate to defer to).

`src/retrieve/entity_scope.py`, `hybrid.py`, `graph_expand.py`, and `src/consolidate/executor.py`
are unchanged — this is entirely an upstream write-path fix, not a retrieval change.

## Acceptance 1: cross-project collision, reproduced and fixed

`tests/test_consolidate_run.py::test_cross_project_same_entity_name_separated_by_scope` flushes two
captures, both mentioning `the_database`, tagged `project="project_a"` / `project="project_b"` at
capture time, through the real `capture()` → `consolidate.run()` pipeline (classifier mocked to
return `"new"`; nothing about entity/scope is mocked). Result: two facts, both `entity="the_database"`,
scopes `"project_a"` / `"project_b"` — `by_entity_or_scope(entity="the_database", scope="project_a")`
and `scope="project_b"` each return exactly one, non-overlapping fact. Before this fix both facts
would have landed as `entity="unsorted"`, `scope=None` — indistinguishable.

## Acceptance 2: `eval/run_retrieval_quality_set.py` re-run

**Score: 0.03333 → 0.03333. Does not move. Stated plainly, not framed as expected: re-running this
exact script produces the identical number before and after this fix, full stop.**

The reason is structural, verified by backfilling a *copy* of the real store (never the live one)
and re-running the same check against it — see `eval/run_entity_scope_backfill_probe.py` and
"Backfill test" below. `run_retrieval_quality_set.py`'s own harness calls `src.index.flush.flush()`
directly with `entity="unsorted", scope=None` hardcoded in the script (lines 48-49), builds its
fixture in a throwaway `tempfile.mkdtemp()`, and asserts against `src.retrieve.hybrid.search()`
directly. It never calls `src.capture.capture()`, `src.consolidate.run.run()`, or
`src.retrieve.entity_scope.by_entity_or_scope()` — the three places this fix actually lives — and
it never reads `brain/` (real or copied) at all. No backfill of any store, real or copied, can move
this number: the script doesn't read a store. Confirmed by running it against a backfilled copy
below; the score was identical for that reason, not because the fix doesn't work.

Acceptance 1 above (the cross-project test, run through the real `capture()` → `consolidate.run()`
pipeline this fix actually modifies) is the correct empirical check, and it passed.

## Backfill test: did this fix touch the existing 121 facts?

**No.** Confirmed directly: `entity="unsorted"` on all 121 pre-existing facts, unchanged, before and
after this task (`grep`-equivalent check: 0/121 have a non-`"unsorted"` entity as of this fix
shipping). `entity_extract.py` only runs in `src/consolidate/run.py`'s auto-apply loop and
`src/consolidate/review.py`'s human-resolve path — both operate on *new* captures / pending review
items, never re-scan already-written facts. This is by construction, not an oversight: the
episodic tier is immutable/append-only, and there is no code path that re-derives an existing
fact's frontmatter after the fact is written. **This fix is prospective only.**

To measure what backfilling *would* do, `eval/run_entity_scope_backfill_probe.py` copies the real
`brain/` to a scratch tempdir (real `brain/` is never touched), re-derives `entity` for all 121
existing facts from each fact's source episodic capture content, and reports:

```
total facts: 121
entity changed from 'unsorted' to something else: 11
stayed 'unsorted' (no identifier-like token in source capture): 110
distinct non-unsorted entities assigned: 9
entities assigned to >1 fact, INCLUDING already-invalidated facts: {'rocars': 2, 'invalid_at': 2}
LIVE collisions in the current active corpus: none — every raw collision above turned out to be
one active fact plus one already-invalidated/superseded fact, which real retrieval already
excludes regardless of entity/scope.
```

So: entity backfill alone would move 11/121 facts off `"unsorted"`, but (a) **`scope` cannot be
backfilled at all** — historical episodic captures were written before this task added the
`project` field to `capture()`, so there is no project signal to recover for them; a content-based
guess at "which project was this" would be exactly the guessing the task brief said not to do —
and (b) there is currently no *live* pair of active facts sharing a backfilled entity name in this
corpus, so even with scope somehow reconstructed, there is nothing measurable to separate today.
Re-running `run_retrieval_quality_set.py` against this backfilled copy still produces 0.03333,
confirmed directly, for the structural reason above.

**Conclusion, stated directly: no eval score moves from this fix today, on the current real corpus
or via backfill, because (a) the one score requested is structurally incapable of reading any store
at all, and (b) the real corpus has no live entity collision to separate yet even after backfilling
what can be backfilled (entity, not scope).** The fix is real and verified through the mechanism
that actually exercises it (Acceptance 1, and this probe's `by_entity_or_scope` checks), not through
this score. A full historical backfill was deliberately not applied to the live store — see the
`--all` / `--since-revision` scope flag on `recall import-aiw` for the analogous decision on the
AIW-import side; the same "don't silently backfill" posture applies here too, and no backfill
tooling for existing *facts* (as opposed to AIW tasks) has been built or run.

## Retraction: eval/run_retrieval_quality_set.py's 0.03333 is not a validation signal for this fix

Retracted per owner review. That score never measured the real store, before this task or at all
-- it is a synthetic single-case fixture built inside the script itself, and always was. It should
not have been cited as evidence either way (including in the original audit that named it as a
baseline). See `eval/run_entity_scope_real_query_probe.py` for the real per-query comparison that
replaces it: 5-10 real queries against the real corpus (via scratch copies, live store untouched),
`entity_scope.by_entity_or_scope()` and `hybrid.search()` results before vs. after backfilling
`entity` onto the existing 121 facts, judged by hand, reported raw per query -- not one number.
Findings, including two real limitations the fix does not solve, are in the task conversation
record rather than duplicated here.

## Fix: casing-variant entities now fold together

Owner-identified gap from the real-query probe (cases 6/7): "session_start" (snake_case, from
`session_start.py`) and "SessionStart" (CamelCase, a hook name) were the same real-world name but
resolved to two different entity strings ("session_start" vs "sessionstart"), so each was only
findable under its own spelling. `entity_extract.py::_fold` now strips `_`/`-` (not `.`) before
both the frequency comparison AND the returned `entity` value itself -- the value has to be a pure
function of the folded name, not of which spelling appeared in a given capture, or two
independently-extracted captures using different spellings would still resolve to two different
strings. Confirmed: both source captures now independently extract to `entity='sessionstart'`, and
`by_entity_or_scope(entity="sessionstart")` on a backfilled copy returns both facts together.
Side effect: previously-underscored entity values are now written without separators (e.g. the
cross-project test's `"the_database"` example now extracts as `"thedatabase"`) -- less readable,
but deterministic and collision-safe across spellings, which is what was asked for.

## Caveats

- Entity extraction only engages on captures containing an identifier-like token (backtick,
  snake_case, CamelCase). Plain-prose captures with no such token stay `entity="unsorted"`, same as
  before — this is a targeted fix for the demonstrated collision pattern, not general NER.
- Ambiguous-tie routing to review means a capture mentioning two equally-frequent identifiers now
  gets reviewed instead of auto-written, where before it would have auto-written (uselessly) as
  `entity="unsorted"`. This trades a small amount of new review-queue volume for not guessing wrong;
  not measured against real review-queue throughput yet since it only affects *future* captures.
- `scope` now serves double duty (project namespace, and BUILD_PLAN.md's original "context tag for
  context-dependent-both facts" sense, e.g. "work"/"personal") — reusing the one field the schema
  already has rather than adding a second, per the task's explicit ask. A capture made outside any
  git repo (or via a source that doesn't go through `capture()`, e.g. a historical backfill) still
  gets `scope=None`, same as `context_dependent_both`'s tag would be today if no scope were passed.
