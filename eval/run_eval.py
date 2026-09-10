"""Run the classifier in isolation against the eval sets and report accuracy.

Per BUILD_PLAN.md §6 Phase 2: this must be measured *before* trusting the classifier's
confidence gate in consolidate/. Requires ANTHROPIC_API_KEY and makes one real API call per
example through src/consolidate/classifier.py (no mock).

Datasets:
- eval/classifier_set/example_*.yaml     -- one doc per file (the original 20 synthetic examples)
- eval/classifier_set/real_examples.yaml -- multi-document YAML, 46 real examples, 22 marked
  "[HARD CASE]" in their notes.

Usage:
    python eval/run_eval.py                 # real 46 + combined 66, confusion + threshold analysis
    python eval/run_eval.py --set real      # real 46 only
    python eval/run_eval.py --set synthetic # original 20 only
    python eval/run_eval.py --workers 1     # disable concurrency
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.consolidate.classifier import Capture, ExistingFact, classify  # noqa: E402

CLASSIFIER_SET_DIR = Path(__file__).parent / "classifier_set"
REAL_FILE = CLASSIFIER_SET_DIR / "real_examples.yaml"
CLASSES = ["new", "update", "contradiction", "context_dependent_both"]

# Classes the executor may auto-apply to the semantic tier without review.
#   new                    -> always auto-applied, NOT confidence-gated (executor.py)
#   update / both          -> auto-applied only when confidence >= threshold
#   contradiction          -> never auto-applied, always routed to review
GATED_AUTOAPPLY = {"update", "context_dependent_both"}


def _field_names(cls) -> set[str]:
    return {f.name for f in dataclasses.fields(cls)}


_CAPTURE_FIELDS = _field_names(Capture)
_FACT_FIELDS = _field_names(ExistingFact)


def _coerce(raw: dict, fields: set[str]) -> dict:
    """Drop keys the dataclass doesn't accept (real_examples.yaml carries a `scope` on facts
    that the current classifier dataclasses don't model) and stringify scalars."""
    return {k: ("" if v is None else str(v)) for k, v in raw.items() if k in fields}


def load_synthetic(directory: Path = CLASSIFIER_SET_DIR) -> list[dict]:
    out = []
    for path in sorted(directory.glob("example_*.yaml")):
        if path.name.startswith("_"):
            continue
        with path.open() as fh:
            doc = yaml.safe_load(fh)
        doc["_dataset"] = "synthetic"
        doc["_hard"] = False
        out.append(doc)
    return out


def load_real(path: Path = REAL_FILE) -> list[dict]:
    out = []
    with path.open() as fh:
        for doc in yaml.safe_load_all(fh):
            if not doc:
                continue
            doc["_dataset"] = "real"
            doc["_hard"] = "[HARD CASE]" in (doc.get("notes") or "")
            out.append(doc)
    return out


def classify_example(ex: dict) -> dict:
    new_capture = Capture(**_coerce(ex["new_capture"], _CAPTURE_FIELDS))
    existing = [ExistingFact(**_coerce(f, _FACT_FIELDS)) for f in ex.get("existing_facts", [])]
    expected = ex["expected_classification"]

    base = {
        "id": ex["id"], "dataset": ex["_dataset"], "hard": ex["_hard"], "expected": expected,
        "expected_conflicting_fact_id": ex.get("expected_conflicting_fact_id"),
    }

    err = None
    for attempt in range(3):
        try:
            res = classify(new_capture, existing)
            return {
                **base, "predicted": res.classification,
                "confidence": round(float(res.confidence), 4), "reasoning": res.reasoning,
                "predicted_conflicting_fact_id": res.conflicting_fact_id,
                "correct": res.classification == expected,
            }
        except Exception as e:  # noqa: BLE001 - surface + retry transient API errors
            err = e
            time.sleep(2 * (attempt + 1))

    return {
        **base, "predicted": "ERROR", "confidence": 0.0,
        "reasoning": f"classify() raised: {err!r}",
        "predicted_conflicting_fact_id": None, "correct": False,
    }


def confusion_counts(results: list[dict]) -> Counter:
    return Counter((r["expected"], r["predicted"]) for r in results)


def print_confusion(title: str, results: list[dict]) -> None:
    counts = confusion_counts(results)
    cols = CLASSES + sorted({r["predicted"] for r in results} - set(CLASSES))
    w = max(len(c) for c in cols) + 2
    print(f"\n{title}  (n={len(results)})")
    print("rows = EXPECTED, cols = PREDICTED")
    print(" " * (w + 1) + "".join(f"{c:>{w}}" for c in cols) + f"{'tot':>{w}}")
    for row in CLASSES:
        cells = [counts.get((row, col), 0) for col in cols]
        rtot = sum(1 for r in results if r["expected"] == row)
        print(f"{row:>{w}} " + "".join(f"{v:>{w}}" for v in cells) + f"{rtot:>{w}}")
    ctot = [sum(1 for r in results if r["predicted"] == col) for col in cols]
    print(f"{'tot':>{w}} " + "".join(f"{v:>{w}}" for v in ctot) + f"{len(results):>{w}}")
    correct = sum(1 for r in results if r["correct"])
    print(f"accuracy: {correct}/{len(results)} = {correct / len(results):.1%}")


def print_misses(results: list[dict]) -> None:
    misses = [r for r in results if not r["correct"]]
    if not misses:
        print("\nNo misclassifications.")
        return
    print(f"\n{'=' * 78}\nMISCLASSIFIED ({len(misses)} of {len(results)})\n{'=' * 78}")
    for r in sorted(misses, key=lambda x: (not x["hard"], x["id"])):
        tag = " [HARD]" if r["hard"] else ""
        print(f"\n[{r['id']}]{tag}  expected={r['expected']}  predicted={r['predicted']}  "
              f"confidence={r['confidence']:.2f}")
        print(f"  expected_conflicting_fact_id={r['expected_conflicting_fact_id']}  "
              f"predicted={r['predicted_conflicting_fact_id']}")
        print(f"  reasoning: {r['reasoning']}")


def _utility_table(gated_right: list[dict], gated_wrong: list[dict]) -> None:
    print("\nAt candidate thresholds (gated update/both auto-applies only; `new` and "
          "`contradiction` predictions are unaffected by the gate):")
    print(f"  {'thr':>5}  {'correct auto-applied':>20}  {'WRONG auto-applied':>18}  "
          f"{'correct->review':>16}")
    for thr in [0.60, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95]:
        ca = sum(1 for r in gated_right if r["confidence"] >= thr)
        wa = sum(1 for r in gated_wrong if r["confidence"] >= thr)
        cr = sum(1 for r in gated_right if r["confidence"] < thr)
        print(f"  {thr:>5.2f}  {ca:>20}  {wa:>18}  {cr:>16}")


def threshold_analysis(results: list[dict]) -> None:
    """The executor auto-applies `new` unconditionally, and `update`/`both` when
    confidence >= threshold. `contradiction` predictions always go to review. So the only
    errors a confidence threshold can prevent are wrong `update`/`both` predictions that would
    otherwise auto-apply. The worst of those is expected==contradiction: silent corruption of
    the semantic tier.
    """
    print(f"\n{'=' * 78}\nTHRESHOLD ANALYSIS  (real-46)\n{'=' * 78}")

    gated_wrong = [r for r in results if r["predicted"] in GATED_AUTOAPPLY and not r["correct"]]
    gated_right = [r for r in results if r["predicted"] in GATED_AUTOAPPLY and r["correct"]]
    sev1 = [r for r in gated_wrong if r["expected"] == "contradiction"]
    sev2 = [r for r in gated_wrong if r["expected"] != "contradiction"]

    # `new` predictions bypass the gate entirely -- flag any wrong ones, the threshold can't help.
    new_wrong = [r for r in results if r["predicted"] == "new" and not r["correct"]]

    def line(r):
        return (f"    [{r['id']}] expected={r['expected']} predicted={r['predicted']} "
                f"confidence={r['confidence']:.2f}{' [HARD]' if r['hard'] else ''}")

    print(f"\nGated auto-apply predictions (update/both): "
          f"{len(gated_right) + len(gated_wrong)}  correct={len(gated_right)}  "
          f"wrong={len(gated_wrong)}")
    print(f"\nSEV1 - wrong update/both, truth was CONTRADICTION (silent corruption): {len(sev1)}")
    for r in sorted(sev1, key=lambda x: -x["confidence"]):
        print(line(r))
    print(f"\nSEV2 - wrong update/both, truth was new/update/both (wrong write, recoverable): "
          f"{len(sev2)}")
    for r in sorted(sev2, key=lambda x: -x["confidence"]):
        print(line(r))
    print(f"\nUngated: wrong `new` predictions (auto-applied regardless of any threshold): "
          f"{len(new_wrong)}")
    for r in sorted(new_wrong, key=lambda x: -x["confidence"]):
        print(line(r))

    _utility_table(gated_right, gated_wrong)

    if not gated_wrong:
        print("\nVERDICT: no gated auto-apply prediction was wrong in this set. A confidence "
              "threshold has nothing to catch; its only effect here is sending correct "
              "predictions to review. Nothing in this data justifies a specific number.")
        return

    worst = sev1 or sev2
    max_bad = max(r["confidence"] for r in worst)
    saved_at = [thr for thr in [0.75, 0.80, 0.85, 0.90, 0.95] if thr > max_bad]
    print(f"\nMost confident wrong auto-apply ({'SEV1' if sev1 else 'SEV2'}): {max_bad:.2f}")
    print(f"  -> a threshold > {max_bad:.2f} would route it to review. "
          f"Candidate thresholds that clear it: {saved_at or 'none <= 0.95'}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", choices=["real", "synthetic", "both"], default="both")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    real = load_real() if args.set in ("real", "both") else []
    synthetic = load_synthetic() if args.set in ("synthetic", "both") else []
    examples = real + synthetic
    if not examples:
        print("No examples loaded.")
        return

    print(f"Classifying {len(examples)} examples via the real API "
          f"(real={len(real)}, synthetic={len(synthetic)}, workers={args.workers})...")
    t0 = time.time()
    if args.workers > 1:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            results = list(pool.map(classify_example, examples))
    else:
        results = [classify_example(ex) for ex in examples]
    print(f"done in {time.time() - t0:.0f}s")

    errored = [r for r in results if r["predicted"] == "ERROR"]
    if errored:
        print(f"\nWARNING: {len(errored)} example(s) errored: {[r['id'] for r in errored]}")

    real_res = [r for r in results if r["dataset"] == "real"]
    hard_res = [r for r in real_res if r["hard"]]
    easy_res = [r for r in real_res if not r["hard"]]

    if real_res:
        print_confusion("CONFUSION MATRIX - REAL (46)", real_res)
        if hard_res:
            hc = sum(1 for r in hard_res if r["correct"])
            ec = sum(1 for r in easy_res if r["correct"])
            print(f"\n  hard subset ([HARD CASE]):  {hc}/{len(hard_res)} = "
                  f"{hc / len(hard_res):.1%}")
            print(f"  easy subset:                 {ec}/{len(easy_res)} = "
                  f"{ec / max(len(easy_res), 1):.1%}")
            print_confusion("CONFUSION MATRIX - REAL / HARD SUBSET (22)", hard_res)
    if real_res and synthetic:
        print_confusion("CONFUSION MATRIX - COMBINED (66)", results)

    print_misses(real_res or results)
    threshold_analysis(real_res or results)

    out = args.out or (Path(__file__).parent /
                       f"results_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json")
    out.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": "claude-sonnet-5",
        "counts": {"real": len(real_res), "synthetic": len(synthetic), "hard": len(hard_res)},
        "results": results,
    }, indent=2))
    print(f"\nfull per-example results -> {out}")


if __name__ == "__main__":
    main()
