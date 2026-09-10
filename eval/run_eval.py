"""Run the classifier in isolation against eval/classifier_set/ and report accuracy.

Per BUILD_PLAN.md §6 Phase 2: this must be measured *before* the classifier is wired into
consolidate/. Requires ANTHROPIC_API_KEY and a real labeled eval set (see
eval/classifier_set/README.md) — files starting with "_" are format templates, not real examples,
and are skipped.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.consolidate.classifier import Capture, ExistingFact, classify

CLASSIFIER_SET_DIR = Path(__file__).parent / "classifier_set"


def load_examples(directory: Path = CLASSIFIER_SET_DIR) -> list[dict]:
    examples = []
    for path in sorted(directory.glob("*.yaml")):
        if path.name.startswith("_"):
            continue
        with path.open() as f:
            examples.append(yaml.safe_load(f))
    return examples


def run(directory: Path = CLASSIFIER_SET_DIR) -> None:
    examples = load_examples(directory)
    if not examples:
        print(
            f"No real eval examples found in {directory} (files starting with '_' are "
            "templates and are skipped). Hand-label some real examples first — see "
            f"{directory / 'README.md'}."
        )
        return

    correct = 0
    confusion = Counter()
    misses = []

    for ex in examples:
        new_capture = Capture(**ex["new_capture"])
        existing_facts = [ExistingFact(**f) for f in ex.get("existing_facts", [])]
        expected = ex["expected_classification"]

        result = classify(new_capture, existing_facts)
        confusion[(expected, result.classification)] += 1

        if result.classification == expected:
            correct += 1
        else:
            misses.append((ex["id"], expected, result.classification, result.reasoning))

    total = len(examples)
    accuracy = correct / total
    print(f"Accuracy: {correct}/{total} = {accuracy:.1%}")
    print("\nConfusion (expected -> got : count):")
    for (expected, got), count in sorted(confusion.items()):
        marker = "" if expected == got else "  <-- MISS"
        print(f"  {expected} -> {got}: {count}{marker}")

    if misses:
        print("\nMissed examples:")
        for example_id, expected, got, reasoning in misses:
            print(f"  [{example_id}] expected={expected} got={got}")
            print(f"    reasoning: {reasoning}")


if __name__ == "__main__":
    run()
