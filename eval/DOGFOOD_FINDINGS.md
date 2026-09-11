# Dogfood findings — consolidating Recall's own build history

Per decision [0007](../.ai/decisions/0007-dogfood-recall-on-its-own-build.md): this build is
Recall's first real corpus. This is the honest result, not a smoothed-over one.

## Setup

12 real episodic captures existed under `brain/episodic/2026/09/`, all provenance-tagged by AIW
task id:

- **4 from `aiw-adoption`** (2026-09-10 ~21:34) — AIW onboarding, the six re-stated design
  constraints, and two gaps found against the codebase.
- **8 from this session's task-by-task dogfooding** (`readme-accuracy` through
  `aiw-readonly-integration`, 2026-09-10 21:49 → 2026-09-11 09:18) — one non-obvious decision per
  task, per decision 0007.

`recall consolidate run` (real classifier, `claude-sonnet-5`, no mock — required by this task's
own constraint) processed all 12:

```
write_new: 7   supersede: 1   review: 4
```

The one `supersede` is a clean, correct case: a capture noting `recall status` was unbuilt got
superseded by a later capture noting it now is (`phase8-polish`). No verifier flag needed, none
raised — legitimate update, not a retraction.

## The two target questions

Decision 0007 asks retrieval to answer two things from this corpus: *why the dual-representation
split*, and *why the executor distrusts low-confidence classifications*.

**Neither is surfaced right now. Not smoothed over: here's exactly why, and it's two separate
problems, not one.**

### Problem 1 — the one capture that answers both is stuck in the review queue

The only capture that touches either question is `574721f8` ("Six Recall design constraints
re-stated..."), which states constraint 1 (dual-representation: "MD is source of truth, SQLite
is a rebuildable index, never the reverse") and constraint 4 (probabilistic classifier proposes /
deterministic executor writes / confidence-gated autonomy). The classifier scored it `update` at
confidence 0.72 against the AIW-adoption fact — correctly below the 0.90 gate, so it went to
**review**, not straight to the semantic tier. It is still pending; nobody has resolved it. Until
a human runs `recall review accept/override` on it, it is invisible to `recall retrieve` by
design (review-queue items are not indexed as facts). **0 corrections have been logged** despite
4 items sitting in the queue — the Phase 7 loop this whole exercise depends on has real backlog,
not activity, right now.

This is a legitimate finding about the pipeline, not just this run: architectural rationale
captured today does not become queryable today. That gap is by design (the review queue exists
precisely so nothing auto-applies below the confidence gate) — but it means "capture it and
retrieval will have it" is not true without a human closing the loop, and that step has no
urgency signal anywhere yet (`recall status` shows the count but nothing prompts action on it).

### Problem 2 (found *while checking Problem 1*) — retrieval can return an invalidated fact as "ground truth"

Querying `recall retrieve` for both target questions returned the **same 8 facts, differently
ranked, for both queries** — and one of the 8 (`ef9b8275`, the pre-Phase-8 "recall status not
built yet" note) has `invalid_at` set — it was invalidated by the one legitimate `supersede`
above. It should never appear in a retrieve result at all: the injection format frames every
returned fact as "verified... treat as ground truth," and this one is exactly the kind of
silently-wrong fact the entire product claims never to serve.

Root cause: `src/retrieve/hybrid.py`'s BM25 path (`_bm25_candidates`, querying
`semantic_facts_fts`) and the final by-id fetch in `search()` never filter `invalid_at IS NULL`
— unlike `_vector_candidates` (same file), `by_entity_or_scope` (`entity_scope.py`), and
`expand` (`graph_expand.py`), which all do. An invalidated fact can only lose the vector-path
filter and still surface if it wins on BM25 rank, which is exactly what happened here. **This is
a real correctness bug, caught only because this dogfood run had an actual invalidated fact to
retrieve against** — the existing retrieval test suite apparently has no case exercising an
invalidated fact through the BM25 path. Filed as task `fix-bm25-invalid-at-leak` (not fixed here
— out of this task's declared scope, `brain/` + this file only).

### A caveat on both findings

The corpus is tiny (7-8 active facts, `k=10` default). Getting the same result set for two
different queries is also just what happens when there are fewer facts than `k` — it is not by
itself evidence that BM25+vector fusion discriminates well or poorly. Real signal on retrieval
*quality* (not just this correctness bug) needs a bigger, longer-running corpus — i.e. it needs
`start-daily-usage` to actually happen, same dependency as everything else non-synthetic now.

## Verdict

**Does Recall's own retrieval currently answer "why did we do X" about its own build? No.** Not
because the retrieval algorithm is obviously bad, but because (1) the review queue has a real,
unaddressed backlog with no follow-up prompt, and (2) dogfooding this exposed an actual
invalidated-fact leak in the BM25 path that would have shipped invisibly otherwise. Both are
filed as real findings per decision 0007, not tuned away: Problem 1 needs a human to run
`recall review accept/override` (see `recall status`); Problem 2 is task
`fix-bm25-invalid-at-leak`.
