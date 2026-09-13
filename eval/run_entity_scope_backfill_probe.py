"""Backfill probe for `entity-scope-and-aiw-import`: does retroactively applying
src/consolidate/entity_extract.py to the REAL, already-written 121 facts move
eval/run_retrieval_quality_set.py's score, or anything else measurable?

Never touches the live brain/ -- copies it to a tempdir first, backfills the copy in place
(re-derives `entity` for every existing fact from its source episodic capture's content, moves
the file to the matching semantic/facts/<entity>/ directory per SCHEMA.md, exactly what
src/consolidate/run.py would have done had entity_extract.py existed when these were written),
then reports on that copy. Read-only w.r.t. the real brain/.

Usage:
    .venv/bin/python eval/run_entity_scope_backfill_probe.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import frontmatter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.config import BRAIN_ROOT  # noqa: E402
from src.consolidate.entity_extract import extract_entity  # noqa: E402
from src.index.build import build  # noqa: E402
from src.retrieve.entity_scope import by_entity_or_scope  # noqa: E402


def _find_capture_content(brain_root: Path, capture_id: str) -> str | None:
    for path in (brain_root / "episodic").rglob("*.md"):
        post = frontmatter.load(path)
        if post.get("id") == capture_id:
            return post.content
    return None


def backfill(brain_root: Path) -> dict:
    """Mutates `brain_root` (expected to be a scratch copy) in place. Returns stats."""
    stats = {"total": 0, "changed": 0, "still_unsorted_no_signal": 0, "no_source_capture": 0}
    entity_counts: dict[str, int] = {}

    fact_paths = list((brain_root / "semantic" / "facts").rglob("*.md"))
    for path in fact_paths:
        post = frontmatter.load(path)
        stats["total"] += 1
        capture_id = post.get("source_capture_id")
        content = _find_capture_content(brain_root, capture_id) if capture_id else None
        if content is None:
            stats["no_source_capture"] += 1
            continue

        extraction = extract_entity(content)
        new_entity = "unsorted" if extraction.ambiguous else extraction.entity
        entity_counts[new_entity] = entity_counts.get(new_entity, 0) + 1

        if new_entity == "unsorted":
            stats["still_unsorted_no_signal"] += 1
            continue

        post["entity"] = new_entity
        new_dir = brain_root / "semantic" / "facts" / new_entity
        new_dir.mkdir(parents=True, exist_ok=True)
        new_path = new_dir / path.name
        new_path.write_bytes(frontmatter.dumps(post).encode("utf-8"))
        if new_path != path:
            path.unlink()
        stats["changed"] += 1

    stats["entity_counts"] = entity_counts
    # scope is NOT backfilled: historical episodic captures were written before this task added
    # the `project` field to capture() -- there is no project signal to recover for them. Any
    # entity collisions below are real facts that would STILL pool together even after this
    # backfill, because scope can only be known at capture time, not reconstructed after the fact.
    return stats


def main() -> None:
    tmp = Path(tempfile.mkdtemp()) / "brain"
    shutil.copytree(BRAIN_ROOT, tmp, ignore=shutil.ignore_patterns(".brainindex"))
    print(f"Copied real brain/ -> {tmp} (real brain/ untouched)\n")

    stats = backfill(tmp)
    print("=== Backfill result (on the copy only) ===")
    print(f"total facts: {stats['total']}")
    print(f"entity changed from 'unsorted' to something else: {stats['changed']}")
    print(f"stayed 'unsorted' (no identifier-like token in source capture): {stats['still_unsorted_no_signal']}")
    print(f"no source_capture_id / capture not found: {stats['no_source_capture']}")
    print()
    raw_collisions = {e: n for e, n in stats["entity_counts"].items() if e != "unsorted" and n > 1}
    print(f"distinct non-unsorted entities assigned: {len([e for e in stats['entity_counts'] if e != 'unsorted'])}")
    print(f"entities assigned to >1 fact, INCLUDING already-invalidated facts: {raw_collisions}")
    print()

    index_db = build(brain_root=tmp)
    print("=== by_entity_or_scope() on the backfilled copy, for each raw-colliding entity ===")
    print("(this separates a real, currently-live collision from one side being an already-")
    print(" invalidated/superseded fact that real retrieval would never surface anyway)")
    live_collisions = {}
    if not raw_collisions:
        print("(none -- no entity was assigned to more than one fact at all)")
    for entity in raw_collisions:
        matches = by_entity_or_scope(index_db, entity=entity)
        print(f"  entity={entity!r}: {raw_collisions[entity]} fact(s) assigned, "
              f"{len(matches)} currently ACTIVE (invalid_at IS NULL), scope={[m.scope for m in matches]}")
        if len(matches) > 1:
            live_collisions[entity] = len(matches)

    print()
    if live_collisions:
        print(f"LIVE collisions in the current active corpus: {live_collisions} -- these ARE two")
        print("distinct live facts sharing an entity name with no scope to tell them apart; entity")
        print("backfill alone does not fix this (scope can't be reconstructed for pre-existing")
        print("captures -- see backfill() docstring).")
    else:
        print("LIVE collisions in the current active corpus: none. Every raw collision above turned")
        print("out to be one active fact plus one already-invalidated/superseded fact -- not a real")
        print("pooling problem today, since real retrieval already excludes invalidated facts. This")
        print("means entity backfill alone would not currently produce any measurable retrieval")
        print("separation benefit on THIS corpus, as of now -- there is no live pair to separate.")

    print("\n=== eval/run_retrieval_quality_set.py, run normally (unaffected by any of the above) ===")
    import subprocess
    result = subprocess.run(
        [sys.executable, str(Path(__file__).parent / "run_retrieval_quality_set.py")],
        capture_output=True, text=True,
    )
    print(result.stdout.strip().splitlines()[-1] if result.stdout else "(no output)")
    print("This script's own harness builds a synthetic fixture in its own tempdir with")
    print("entity='unsorted', scope=None hardcoded (see its source, lines ~48-49) -- it never")
    print("reads brain/ (real or this backfilled copy) at all. The backfill above CANNOT move")
    print("this number, by construction, regardless of whether the entity/scope fix works.")


if __name__ == "__main__":
    main()
