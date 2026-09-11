# Retrieval-quality eval set

Distinct from `eval/classifier_set/` (which tests `src/consolidate/classifier.py` on
new-capture-vs-existing-fact pairs). This set tests `src/retrieve/hybrid.py` and
`src/retrieve/sufficiency.py` on precision: given a real query against a real slice of the store,
does `search()` return the right fact without padding the rest with noise?

Filed for task `retrieval-precision-at-scale`. Not covered by decision 0008 (freeze
hand-authored/synthetic eval-case creation) — that decision is scoped by name to the three
classifier-related sets, and a different component is under test here.

## Privacy note

Case content here is **synthetic**, not real. Recall's own repo is public; `brain/` (the private
repo, per `.ai/decisions/0009`) is where the user's real captured facts live and it must stay that
way — nothing from it gets copied into this repo's history. The real case that surfaced this bug
was investigated directly against the live real store with `eval/run_retrieval_quality.py`
(reads `brain/` at runtime, never embeds its content in a committed file); each case here then
reconstructs the same *structural* shape — one genuinely-relevant fact, several real-style but
topically-disparate distractors, the real query and the real observed score dynamics — with
placeholder content, so the regression is reproducible and public-repo-safe.

## Case format

```yaml
id: case_001
query: "the real query that surfaced the problem"
facts:
  - content: "verbatim real fact body"
    is_expected_top_result: true   # exactly one fact per case
notes: "what this case is regression-testing, and why"
```

Run `.venv/bin/python eval/run_retrieval_quality_set.py`. The same cases are also wired into
`tests/test_retrieve_precision.py` so `pytest` catches a regression, not just this script.
