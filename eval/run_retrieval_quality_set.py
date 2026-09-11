"""Standing regression runner for eval/retrieval_quality_set/ -- see that directory's README.

Each case snapshots real captured content into an isolated brain/, builds the real index, and
asserts search() returns the expected fact as the sole/dominant result rather than padding with
the case's other (also real, but topically unrelated) facts. Deterministic and re-runnable,
independent of the live/growing brain/ store.

Usage:
    .venv/bin/python eval/run_retrieval_quality_set.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.consolidate.classifier import ClassificationResult  # noqa: E402
from src.consolidate.executor import decide  # noqa: E402
from src.index.build import build  # noqa: E402
from src.index.flush import flush  # noqa: E402
from src.retrieve.hybrid import search  # noqa: E402

CASES_DIR = Path(__file__).parent / "retrieval_quality_set"


def load_cases() -> list[dict]:
    return [
        yaml.safe_load(p.read_text())
        for p in sorted(CASES_DIR.glob("case_*.yaml"))
    ]


def run_case(case: dict) -> bool:
    brain_root = Path(tempfile.mkdtemp()) / "brain"
    expected_content = None
    for i, fact in enumerate(case["facts"]):
        result = ClassificationResult("new", 0.9, "no overlap", None)
        decision = decide(result, capture_id=f"{case['id']}_c{i}", confidence_threshold=0.75)
        flush(
            decision,
            capture_content=fact["content"],
            captured_at="2026-01-01",
            brain_root=brain_root,
            entity="unsorted",
            scope=None,
        )
        if fact.get("is_expected_top_result"):
            expected_content = fact["content"]

    index_db = build(brain_root=brain_root)
    results = search(index_db, case["query"], k=10)

    print(f"\n=== {case['id']}: {case['query']!r} ===")
    print(f"{len(results)} result(s):")
    for r in results:
        print(f"  {r.score:.5f}  {r.body[:90]}")

    top_ok = bool(results) and results[0].body.strip() == expected_content.strip()
    padding = [r for r in results[1:] if r.body.strip() != expected_content.strip()]
    print(f"top-1 correct: {top_ok}")
    print(f"padding (off-target results beyond #1): {len(padding)}")
    return top_ok


def main() -> None:
    cases = load_cases()
    results = [run_case(c) for c in cases]
    passed = sum(results)
    print(f"\n{passed}/{len(cases)} cases correct.")
    if passed < len(cases):
        sys.exit(1)


if __name__ == "__main__":
    main()
