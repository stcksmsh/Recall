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

**Score: 0.03333 → 0.03333. Unchanged.** This is the expected, correct result here, not a sign the
fix didn't land — and confirming *why* matters more than the number:

`run_retrieval_quality_set.py`'s own harness calls `src.index.flush.flush()` directly with
`entity="unsorted", scope=None` hardcoded in the script (line 48-49), and asserts against
`src.retrieve.hybrid.search()` directly — it never goes through `src.capture.capture()`,
`src.consolidate.run.run()`, or `src.retrieve.entity_scope.by_entity_or_scope()`, i.e. it never
touches any of the three places this fix lives. It is a regression test for `hybrid.py`'s
BM25/TF-IDF precision (retrieval-precision-at-scale, a prior task, unrelated component) and is
*structurally incapable* of reflecting an entity/scope change, no matter how correct that change
is. Re-running it was still worth doing per the task brief's own logic — it's a cheap, real check
that the fix hasn't regressed the hybrid-search path it does cover — but it is the wrong instrument
to evaluate this fix by. Acceptance 1 above (the cross-project test, run through the real capture →
consolidate pipeline this fix actually modifies) is the real empirical check, and it passed. The
real corpus's already-written 97 facts also don't move (episodic capture is append-only; this fix
is prospective, not retroactive — see the addendum in `eval/RETRIEVAL_PRECISION_AT_SCALE.md`).

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
