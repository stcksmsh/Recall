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

## Method

`eval/run_retrieval_dilution.py` builds the same 50-fact fixture as
`tests/test_retrieve_precision.py`, then runs each query through both a frozen copy of the pre-fix
algorithm (`old_search`, for reproducibility now that the real code has changed) and the shipped
`src.retrieve.hybrid.search()`. No model calls; deterministic and re-runnable.
