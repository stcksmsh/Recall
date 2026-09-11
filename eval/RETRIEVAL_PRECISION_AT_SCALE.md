# Retrieval pads to k with near-zero-relevance facts once the store is topically varied

**Question:** once `brain/` holds facts spread across disparate topics, does
`src/retrieve/hybrid.py::search()` return only genuinely-matching facts, or does it pad its top-k
with near-random facts from unrelated topics?

**Before: yes, it padded.** For a 50-fact fixture across 5 disparate topics (finance, music,
cognitive-architecture, personal, work — `eval/run_retrieval_dilution.py`, same fixture as
`tests/test_retrieve_precision.py`), a finance query's #1 result was correct, but 6 of the
remaining 9 were off-topic (personal/work/music/cognitive-architecture), scored within **13%** of
the top result. A "tell me about the dog" query returned only 3 of 10 results actually about the
dog/personal topic; the rest scored within **15%** of the top. Reproduce the old numbers with
`.venv/bin/python eval/run_retrieval_dilution.py` (BEFORE column, frozen copy of the pre-fix
algorithm).

**After: no padding.** Same queries against the fixed `search()` return only genuinely-matching
facts (0–3 results, never forced to k=10), or an honest empty list when nothing in the corpus is a
real match — never padding. See AFTER column of the same script.

| query | before: results / off-topic | after: results / off-topic |
|---|---|---|
| "what brokerage does the user use for investing" | 10 / 6 | 2 / 0 |
| "tell me about the user's dog" | 10 / 7 | 1 / 0 |
| "what does the classifier do in the consolidation pipeline" | 10 / 6 | 3 / 0 |
| "what instrument does the user play" (no real match exists) | 10 / 10 (all padding) | 0 / 0 |

## Root cause — two compounding mechanisms, not one

1. **No stopword filtering.** `_tokenize` fed every token — including `what`, `does`, `the`,
   `user`, `use`, `for` — into both the BM25 `OR` match and the TF-IDF vocabulary. `user` alone
   appears in essentially every fact once bodies are phrased "User's ..." (47 of 50 facts matched
   the brokerage query via BM25 before the fix, most only on stopwords). TF-IDF's smoothed IDF
   (`log((n+1)/(df+1)) + 1`) never drives a near-universal term's weight below 1.0, so it still
   contributes non-trivial cosine similarity even for a term in every document.
2. **RRF only sees rank, not magnitude.** `_bm25_candidates` and `_vector_candidates` both
   discard the underlying relevance score and hand `search()` an ordinal rank. `1/(60+rank)`
   changes by only a few percent between adjacent ranks, so once the stopword-inflated candidate
   pool put 47 near-irrelevant facts in some rank position, RRF fused them into scores
   indistinguishable from the genuine top hit — the "near-flat scores among the irrelevant tail"
   named in the task.

Neither mechanism alone explains it: raw BM25/cosine magnitudes already show a real gap between
the true match and the rest (see the script's intermediate output during development, not
reproduced here) — it's specifically the combination of an inflated candidate pool *and* fusing by
rank-only that erases the gap.

## Fix (`src/retrieve/hybrid.py`)

1. `_tokenize` drops a small stopword list and single-character tokens (the regex splits `user's`
   into `user`, `s`; a bare `s` is exactly as near-universal a false signal as `user`). Applied to
   both the BM25 query and the TF-IDF corpus/query tokenization, so it shrinks the candidate pool
   at the source rather than re-ranking a polluted one.
2. `_vector_candidates` excludes zero-similarity docs from ranking at all — a doc sharing no
   vocabulary with the query is not a weak match, it isn't a match.
3. `search()` adds `RESULT_SCORE_FLOOR = 0.5`: a fused result must score at least half the top
   result's score to survive. With (1) and (2) removing the bulk of spurious candidates, genuine
   hits and any remaining padding separate into a real score gap, so this floor now has something
   real to act on — before the stopword fix, it would not have helped, since the padding scored
   within a few percent of the top result regardless (see the BEFORE numbers above).

This satisfies the task's "either/or/both": a real relevance-score floor was added to `search()`,
made effective by removing the false-candidate inflation feeding it. `sufficiency.check()` was not
changed — it already flags the "no entity match + weak best similarity score" case, and now that
`search()` doesn't pad, a query with no real match returns `[]`, correctly triggering the existing
`"no facts found"` insufficiency path instead of the dilution slipping past it.

## Caveats

- The stopword list is a small hand-picked set (`_STOPWORDS` in `hybrid.py`), not a general
  solution — a corpus phrased differently could still produce a near-universal non-stopword term
  (this fixture leans on `user` specifically because every fact is phrased "User ..."). This is a
  targeted fix for the demonstrated mechanism, not a general IR relevance model.
- `RESULT_SCORE_FLOOR = 0.5` is untuned beyond this fixture. It is a relative cutoff (fraction of
  the top score), so it adapts per query rather than assuming an absolute scale, but a corpus with
  several genuinely-relevant facts spread further apart in RRF score than 2x could see the floor
  drop a real (if weaker) match. No such case was observed in the 50-fact fixture.
- Real signal at true personal-corpus scale needs `start-daily-usage` to actually accumulate
  facts, same caveat as `eval/DOGFOOD_FINDINGS.md`. This fixture is synthetic-but-realistic
  (topic/phrasing shape mirrors `eval/DOGFOOD_FINDINGS.md`'s 73-fact real corpus that originally
  surfaced this), not a substitute for it.

## Method (Part 1)

`eval/run_retrieval_dilution.py` builds the same 50-fact fixture as
`tests/test_retrieve_precision.py`, then runs each query through both a frozen copy of the pre-fix
algorithm (`old_search`, for reproducibility now that the real code has changed) and the shipped
`src.retrieve.hybrid.search()`. No model calls; deterministic and re-runnable.

---

## Part 2 — revisited against the real corpus (2026-09-11)

Part 1 above was built and verified entirely against a synthetic 50-fact fixture. A follow-up task
brief supplied the actual reported query — *"what name did the bank wire transfer end up under?"*
— and required checking the fix against the real `brain/` store (97 active facts at investigation
time) before trusting it, per three candidate root causes, investigated in order.

**Honest first finding: the Part 1 fix did not fix the real case.** Run against the real query, the
Part-1-fixed `search()` still returned 10 padded results, barely different from the pre-fix
baseline — `RESULT_SCORE_FLOOR` on the *fused RRF score* turned out to be structurally unable to
help, and the fixture's stopword list didn't generalize to this query's vocabulary. See
`eval/run_retrieval_quality.py` for the reproducible investigation trail.

### Root cause investigation, in the specified order

1. **Entity/scope anchoring (`entity_scope.py`) — confirmed real, but not this failure's cause.**
   100% of the 97 real active facts have `entity="unsorted"`, `scope=null` — the "primary path" per
   BUILD_PLAN.md has never actually engaged in production. Nothing in the write path
   (`src/index/flush.py`) or the CLI (`src/cli.py`'s `--entity`/`--scope` are opt-in and require
   the caller to already know the exact value) ever populates or supplies one automatically. This
   is a real, confirmed structural gap. But the reported query contains no capitalized/named entity
   at all ("bank", "wire", "transfer" are generic nouns) — even a working entity/scope anchor would
   not have engaged for *this specific query*. Implementing entity extraction was therefore **not**
   the fix for this case, and was not built here — see Known limitation below.
2. **BM25/TF-IDF scoring quality, refined: RRF discards raw magnitude.** Raw signals already
   discriminate correctly on the real data — BM25 raw score **-15.3** (top) vs **-5.3** (#2), cosine
   similarity **0.23** vs **0.11**, both a genuine 2-3x gap. But `_bm25_candidates` and
   `_vector_candidates` (pre-this-revision) converted both to ordinal rank before RRF fusion, and
   `1/(rrf_constant+rank)` differs by only ~2% between rank 0 and rank 1 *regardless of the real
   magnitude gap* — that is what actually erased the signal, more fundamentally than stopword
   pollution (Part 1's diagnosis was real but incomplete: it fixed a fixture built around one
   dominant near-universal token, "user", and didn't generalize to a query with no such token).
3. **`sufficiency.check()` — confirmed shape-blind.** Ran it against the padded pre-fix results:
   `sufficient=True` — it only compares the single best score to `WEAK_SCORE_THRESHOLD`, never
   looks at the shape of the rest.

### Fix option comparison (score floor vs. smarter sufficiency gate)

Chose to fix `search()`'s candidate pool rather than `sufficiency.check()`'s gate. Reasoning:
`retrieve_and_format()` (`src/retrieve/pipeline.py`) formats **every** returned fact into the
injected context and only *appends a warning string* when `sufficiency.check()` says insufficient
— the noisy facts still reach the downstream consumer either way. A smarter sufficiency gate would
correctly *detect* dilution but not *prevent* it; the task's own complaint — "the surrounding
context handed to anything downstream is mostly noise" — needs the noise never returned in the
first place. Cost: a candidate that's a real but comparatively weak match (< `RAW_RELATIVE_FLOOR`
of the best on both signals) is now dropped rather than returned at a low rank; no case of a
too-aggressive drop was observed in the real spot-checks below, but see Known limitation.

### Fix, revised (`src/retrieve/hybrid.py`)

- `RAW_RELATIVE_FLOOR = 0.5` is now applied **before** rank/fusion, inside `_bm25_candidates` (on
  BM25's raw score magnitude) and `_vector_candidates` (on cosine similarity) — not after, on the
  fused RRF score (removed; it was inert on real data, see above).
- Two stopword-list gaps found via real-query spot-checking: `we`, `us`, reflexive pronouns, and
  `why`/`whose`/`whether` were missing. Each is rare enough in this specific 97-fact corpus that
  BM25's IDF gave a single incidental match on one of them outsized weight over a fact matching
  several genuine content words (e.g. a query containing `we` matched only 1/121 real facts, so
  that fact's raw BM25 score spiked far above a fact matching three real content words). A
  stopword list can never be provably complete against this pattern — see Known limitation.

### Real-corpus results

| query (real corpus, 97 active facts) | before (padded results / off-topic) | after |
|---|---|---|
| "what name did the bank wire transfer end up under?" | 10 / 9 off-topic | **1 result, correct** |
| "what guitar or instrument did he buy" | not separately measured pre-fix | **1 result, correct** |
| "what happened with the ETF degree transfer" | not separately measured pre-fix | **2 results, both on-topic** |
| "why does the executor distrust low-confidence classifications" | not separately measured pre-fix | **2 results, correct top-1** (only after adding `why` to stopwords — see below) |
| "what album name did we land on for the AI music project" | not separately measured pre-fix | **3 results, correct top-1** |
| "what did we decide about the classifier confidence threshold" | not separately measured pre-fix | **3 results, WRONG top-1** — known limitation, see below |

5 of 6 real spot-check queries, spanning finance, music, education, and two Recall-project queries,
now return small, correct, non-padded result sets. Reproduce with
`.venv/bin/python eval/run_retrieval_quality.py` (investigation) — real fact content is never
committed to this public repo; see `eval/retrieval_quality_set/README.md`'s privacy note for the
public-repo-safe synthetic regression case (`tests/test_retrieve_precision.py::test_retrieval_quality_set_cases`).

## Known limitation — this fix is partial, not complete

**Lexical collision / polysemy is not solved and cannot be by a purely lexical system.** The
6th spot-check query above still ranks a wrong fact #1: the real corpus happens to contain a
personal note on an unrelated philosophy-of-mind topic that uses the word "threshold" (2/121
real docs contain it at all), and BM25 weights that single rare-term match above a fact matching
three more common but genuinely relevant terms ("classifier", "confidence", "decide"). This is not
a stopword-list gap — "threshold" is legitimate content vocabulary in both facts, and the two uses
are topically unrelated only in *meaning*, which pure TF-IDF/BM25 cannot represent. This is exactly
the gap `hybrid.py`'s own module docstring already flags as deferred v1 scope ("Upgrade to real
embeddings when eval shows TF-IDF misses paraphrases that matter") — except this shows the failure
mode is not just *missing* a paraphrase, it can *actively outrank* the correct answer. Documented
in `LIMITATIONS.md`; not fixed here — fixing it needs real (semantic) embeddings, out of this
task's scope.

**Entity/scope anchoring (BUILD_PLAN.md's intended primary retrieval path) has never engaged in
production** — confirmed above, filed as a known limitation and a candidate future task, not
implemented here since it would not have fixed the reported case (no named entity in that query)
and a real implementation (even the cheap heuristic version — proper-noun/capitalized-term
extraction, or matching against `scope` as a controlled vocabulary) is a bigger lift than this
task's scope, and moot until real `scope` values exist on real facts (currently 0 do).

**No stopword list is provably complete.** Two gaps were found and closed by real-query
spot-checking in this session; a corpus-specific rare-but-meaningless word (whatever it turns out
to be, for a corpus not yet captured) can still spike BM25's score by the same mechanism. This is a
structural property of IDF-based scoring on a small, idiosyncratic personal corpus, not a bug with
a final fix.

## Method (Part 2)

`eval/run_retrieval_quality.py` runs the frozen pre-fix algorithm plus the three root-cause checks
against the live real `brain/` store (never commits its content). `eval/retrieval_quality_set/`
holds the standing regression case with synthetic-but-structurally-real content (privacy note in
its README); `eval/run_retrieval_quality_set.py` and
`tests/test_retrieve_precision.py::test_retrieval_quality_set_cases` both run it.
