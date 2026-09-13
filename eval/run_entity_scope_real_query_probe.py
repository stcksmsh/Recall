"""Per-task ask: pick 5-10 real queries against the real store (or a backfilled scratch copy,
never live), run them through the EXISTING retrieval paths (src/retrieve/hybrid.py,
src/retrieve/entity_scope.py -- both untouched), judge relevance by hand, and compare
entity/scope-anchored results before vs. after the entity-scope-and-aiw-import fix on the same
queries. Raw per-query results, not an aggregate score -- eval/run_retrieval_quality_set.py's
0.03333 has been retired as a signal for this fix; it never read brain/ at all (real or copied).

Never touches the live brain/: makes two scratch copies (BEFORE = untouched copy of the real
store, exactly its current live state; AFTER = same copy with src/consolidate/entity_extract.py
backfilled onto every existing fact, per eval/run_entity_scope_backfill_probe.py). Does not call
executor.decide() or modify hybrid.py/entity_scope.py/graph_expand.py -- calls them as-is.

Usage:
    .venv/bin/python eval/run_entity_scope_real_query_probe.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.config import BRAIN_ROOT  # noqa: E402
from src.index.build import build  # noqa: E402
from src.retrieve.entity_scope import by_entity_or_scope  # noqa: E402
from src.retrieve.hybrid import search  # noqa: E402
from eval.run_entity_scope_backfill_probe import backfill  # noqa: E402

# Each case: a real query a user might actually type, the real entity name (as
# src/consolidate/entity_extract.py would derive it from the source capture, already computed by
# eval/run_entity_scope_backfill_probe.py against the real corpus) that AFTER-fix retrieval should
# be able to anchor on, and a one-line note on what to look for.
CASES = [
    {
        "query": "why did BM25 retrieval leak an invalidated fact as ground truth",
        "entity": "invalid_at",
    },
    {
        "query": "what was the RoCars mixup about",
        "entity": "rocars",
    },
    {
        "query": "what is reviewer_note for and where does it get recorded",
        "entity": "reviewer_note",
    },
    {
        "query": "why does the review queue show considered candidates when there's no conflicting fact",
        "entity": "conflicting_fact_id",
    },
    {
        "query": "what does extractor_note surface in the review TUI",
        "entity": "extractor_note",
    },
    {
        "query": "how does recall inject avoid touching the SQLite index at session start",
        "entity": "session_start",
    },
    {
        "query": "how do the SessionStart hooks for AIW and Recall relate to each other",
        "entity": "sessionstart",
    },
    {
        "query": "what did the classifier provider portability change decouple",
        "entity": "run_eval",
    },
]


def _snippet(body: str, n: int = 160) -> str:
    return body.strip().replace("\n", " ")[:n]


def main() -> None:
    before_root = Path(tempfile.mkdtemp()) / "brain"
    shutil.copytree(BRAIN_ROOT, before_root, ignore=shutil.ignore_patterns(".brainindex"))
    before_db = build(brain_root=before_root)

    after_root = Path(tempfile.mkdtemp()) / "brain"
    shutil.copytree(BRAIN_ROOT, after_root, ignore=shutil.ignore_patterns(".brainindex"))
    backfill(after_root)
    after_db = build(brain_root=after_root)

    print(f"BEFORE copy (live store as-is): {before_root}")
    print(f"AFTER copy (entity-backfilled, scope still None -- can't be recovered): {after_root}\n")

    for i, case in enumerate(CASES, 1):
        query, entity = case["query"], case["entity"]
        print(f"=== case {i}: {query!r}  (target entity: {entity!r}) ===")

        before_anchor = by_entity_or_scope(before_db, entity=entity)
        after_anchor = by_entity_or_scope(after_db, entity=entity)
        print(f"  entity_scope.by_entity_or_scope(entity={entity!r})")
        print(f"    BEFORE: {len(before_anchor)} match(es)")
        for m in before_anchor:
            print(f"      - {_snippet(m.body)}")
        print(f"    AFTER:  {len(after_anchor)} match(es)")
        for m in after_anchor:
            print(f"      - {_snippet(m.body)}")

        before_hybrid = search(before_db, query, k=5)
        after_hybrid = search(after_db, query, k=5)
        same_top = (
            (before_hybrid[0].body if before_hybrid else None)
            == (after_hybrid[0].body if after_hybrid else None)
        )
        print(f"  hybrid.search() -- {len(before_hybrid)} result(s) before, {len(after_hybrid)} after, "
              f"top result identical: {same_top} (expected: hybrid doesn't consult entity/scope)")
        for m in before_hybrid[:3]:
            print(f"      [{m.score:.4f}] {_snippet(m.body)}")
        print()


if __name__ == "__main__":
    main()
