"""Run the classifier in isolation against the real eval set and report accuracy.

Per BUILD_PLAN.md §6 Phase 2: measured *before* trusting the classifier's confidence gate.
One real inference call per example through src/consolidate/classifier.py's prompt + parser
(no mock).

Providers:
- anthropic (default): hosted API, needs ANTHROPIC_API_KEY. --model picks the model.
- local: a GGUF model via llama-cpp-python, CPU. --model-path points at the .gguf. Runs
  single-threaded over examples (the model itself uses all cores); reports per-call latency.

Datasets:
- eval/classifier_set/real_examples.yaml   -- 46 real examples, 22 marked "[HARD CASE]"
- eval/classifier_set/example_*.yaml       -- 20 synthetic (only with --set both/synthetic)

Usage:
    python eval/run_eval.py                                   # sonnet-5, real 46
    python eval/run_eval.py --model claude-haiku-4-5-20251001 --label haiku
    python eval/run_eval.py --provider local --model-path models/qwen2.5-7b-q4.gguf --label qwen
    python eval/run_eval.py --baseline eval/results_sonnet.json   # diff vs a prior run
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

from src.consolidate.classifier import (  # noqa: E402
    Capture, ExistingFact, _build_prompt, classify, parse_response,
)

CLASSIFIER_SET_DIR = Path(__file__).parent / "classifier_set"
REAL_FILE = CLASSIFIER_SET_DIR / "real_examples.yaml"
CLASSES = ["new", "update", "contradiction", "context_dependent_both"]
GATED_AUTOAPPLY = {"update", "context_dependent_both"}
COSTLY_IDS = ["ex_003", "ex_023", "ex_040", "ex_044"]  # the Phase 2 silent-corruption misses


def _field_names(cls) -> set[str]:
    return {f.name for f in dataclasses.fields(cls)}


_CAPTURE_FIELDS = _field_names(Capture)
_FACT_FIELDS = _field_names(ExistingFact)


def _coerce(raw: dict, fields: set[str]) -> dict:
    return {k: ("" if v is None else str(v)) for k, v in raw.items() if k in fields}


def load_synthetic(directory: Path = CLASSIFIER_SET_DIR) -> list[dict]:
    out = []
    for path in sorted(directory.glob("example_*.yaml")):
        if path.name.startswith("_"):
            continue
        with path.open() as fh:
            doc = yaml.safe_load(fh)
        doc["_dataset"], doc["_hard"] = "synthetic", False
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


# --- inference backends -------------------------------------------------------

def anthropic_backend(model: str):
    def call(cap: Capture, facts: list[ExistingFact]):
        return classify(cap, facts, model=model)
    return call


def local_backend(model_path: str, n_ctx: int, n_threads: int | None):
    from llama_cpp import Llama

    llm = Llama(
        model_path=model_path, n_ctx=n_ctx, n_threads=n_threads, verbose=False,
        n_gpu_layers=0,
    )

    def call(cap: Capture, facts: list[ExistingFact]):
        prompt = _build_prompt(cap, facts)
        out = llm.create_chat_completion(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=512, temperature=0.0,
            response_format={"type": "json_object"},
        )
        return parse_response(out["choices"][0]["message"]["content"])

    return call, llm


# --- eval loop ---------------------------------------------------------------

def classify_example(ex: dict, backend) -> dict:
    new_capture = Capture(**_coerce(ex["new_capture"], _CAPTURE_FIELDS))
    existing = [ExistingFact(**_coerce(f, _FACT_FIELDS)) for f in ex.get("existing_facts", [])]
    expected = ex["expected_classification"]
    base = {
        "id": ex["id"], "dataset": ex["_dataset"], "hard": ex["_hard"], "expected": expected,
        "expected_conflicting_fact_id": ex.get("expected_conflicting_fact_id"),
    }

    err = None
    for attempt in range(3):
        t0 = time.time()
        try:
            res = backend(new_capture, existing)
            return {
                **base, "predicted": res.classification,
                "confidence": round(float(res.confidence), 4), "reasoning": res.reasoning,
                "predicted_conflicting_fact_id": res.conflicting_fact_id,
                "correct": res.classification == expected,
                "latency_s": round(time.time() - t0, 2),
            }
        except Exception as e:  # noqa: BLE001
            err = e
            time.sleep(2 * (attempt + 1))

    return {
        **base, "predicted": "ERROR", "confidence": 0.0,
        "reasoning": f"classify() raised: {err!r}", "predicted_conflicting_fact_id": None,
        "correct": False, "latency_s": 0.0,
    }


# --- reporting --------------------------------------------------------------

def print_confusion(title: str, results: list[dict]) -> None:
    counts = Counter((r["expected"], r["predicted"]) for r in results)
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
    c = sum(1 for r in results if r["correct"])
    print(f"accuracy: {c}/{len(results)} = {c / len(results):.1%}")


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
        print(f"  reasoning: {r['reasoning']}")


def print_costly(results: list[dict]) -> None:
    by_id = {r["id"]: r for r in results}
    print(f"\n{'=' * 78}\nPHASE 2 COSTLY CASES (were update/both @ high conf, truth=contradiction)"
          f"\n{'=' * 78}")
    for cid in COSTLY_IDS:
        r = by_id.get(cid)
        if not r:
            print(f"  {cid}: not in this run")
            continue
        mark = "FIXED" if r["correct"] else "STILL WRONG"
        print(f"\n  [{cid}] {mark}  expected={r['expected']} predicted={r['predicted']} "
              f"conf={r['confidence']:.2f}")
        if not r["correct"]:
            print(f"    reasoning: {r['reasoning']}")


def threshold_analysis(results: list[dict]) -> None:
    print(f"\n{'=' * 78}\nTHRESHOLD ANALYSIS  (real set)\n{'=' * 78}")
    gated_wrong = [r for r in results if r["predicted"] in GATED_AUTOAPPLY and not r["correct"]]
    gated_right = [r for r in results if r["predicted"] in GATED_AUTOAPPLY and r["correct"]]
    sev1 = [r for r in gated_wrong if r["expected"] == "contradiction"]
    sev2 = [r for r in gated_wrong if r["expected"] != "contradiction"]

    def line(r):
        return (f"    [{r['id']}] expected={r['expected']} predicted={r['predicted']} "
                f"conf={r['confidence']:.2f}{' [HARD]' if r['hard'] else ''}")

    print(f"\nGated (update/both) predictions: {len(gated_right) + len(gated_wrong)}  "
          f"correct={len(gated_right)}  wrong={len(gated_wrong)}")
    print(f"\nSEV1 - wrong update/both, truth=CONTRADICTION (silent corruption): {len(sev1)}")
    for r in sorted(sev1, key=lambda x: -x["confidence"]):
        print(line(r))
    print(f"\nSEV2 - wrong update/both, truth=new/update/both (recoverable): {len(sev2)}")
    for r in sorted(sev2, key=lambda x: -x["confidence"]):
        print(line(r))

    print("\n  thr   correct-auto  WRONG-auto  SEV1-through  correct->review")
    for thr in [0.60, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95]:
        ca = sum(1 for r in gated_right if r["confidence"] >= thr)
        wa = sum(1 for r in gated_wrong if r["confidence"] >= thr)
        s1 = sum(1 for r in sev1 if r["confidence"] >= thr)
        cr = sum(1 for r in gated_right if r["confidence"] < thr)
        print(f"  {thr:>4.2f}  {ca:>12}  {wa:>10}  {s1:>12}  {cr:>15}")


def diff_baseline(results: list[dict], baseline_path: Path) -> None:
    base = {r["id"]: r for r in json.loads(baseline_path.read_text())["results"]}
    now = {r["id"]: r for r in results}
    regressions, fixes = [], []
    for cid, r in now.items():
        b = base.get(cid)
        if not b:
            continue
        if b["correct"] and not r["correct"]:
            regressions.append((cid, b["predicted"], r["predicted"], r["expected"]))
        if not b["correct"] and r["correct"]:
            fixes.append((cid, b["predicted"], r["predicted"], r["expected"]))
    print(f"\n{'=' * 78}\nDIFF vs baseline {baseline_path.name}\n{'=' * 78}")
    print(f"\nFIXED ({len(fixes)}): correct now, wrong before")
    for cid, bp, np_, exp in fixes:
        print(f"  [{cid}] {bp} -> {np_}   (expected {exp})")
    print(f"\nREGRESSIONS ({len(regressions)}): wrong now, correct before  <-- the risk to watch")
    for cid, bp, np_, exp in regressions:
        print(f"  [{cid}] {bp} -> {np_}   (expected {exp})")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", choices=["real", "synthetic", "both"], default="real")
    ap.add_argument("--provider", choices=["anthropic", "local"], default="anthropic")
    ap.add_argument("--model", default="claude-sonnet-5")
    ap.add_argument("--model-path", default=None, help="GGUF path (provider=local)")
    ap.add_argument("--n-ctx", type=int, default=4096)
    ap.add_argument("--n-threads", type=int, default=None)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--label", default=None)
    ap.add_argument("--baseline", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    real = load_real() if args.set in ("real", "both") else []
    synthetic = load_synthetic() if args.set in ("synthetic", "both") else []
    examples = real + synthetic
    if not examples:
        print("No examples loaded.")
        return

    label = args.label or (args.model if args.provider == "anthropic"
                           else Path(args.model_path or "local").stem)

    if args.provider == "local":
        if not args.model_path:
            ap.error("--provider local requires --model-path")
        backend, llm = local_backend(args.model_path, args.n_ctx, args.n_threads)
        args.workers = 1
    else:
        backend = anthropic_backend(args.model)
        llm = None

    print(f"[{label}] provider={args.provider} model={args.model if args.provider=='anthropic' else args.model_path}")
    print(f"Classifying {len(examples)} examples (real={len(real)}, synthetic={len(synthetic)}, "
          f"workers={args.workers})...")
    t0 = time.time()
    if args.workers > 1:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            results = list(pool.map(lambda ex: classify_example(ex, backend), examples))
    else:
        results = [classify_example(ex, backend) for ex in examples]
    wall = time.time() - t0
    print(f"done in {wall:.0f}s")

    errored = [r for r in results if r["predicted"] == "ERROR"]
    if errored:
        print(f"\nWARNING: {len(errored)} errored: {[r['id'] for r in errored]}")
        print(f"  first error: {errored[0]['reasoning']}")

    lat = [r["latency_s"] for r in results if r["latency_s"] > 0]
    if lat:
        lat.sort()
        print(f"per-call latency: min={lat[0]:.2f}s  median={lat[len(lat)//2]:.2f}s  "
              f"max={lat[-1]:.2f}s  mean={sum(lat)/len(lat):.2f}s")

    real_res = [r for r in results if r["dataset"] == "real"]
    hard_res = [r for r in real_res if r["hard"]]
    easy_res = [r for r in real_res if not r["hard"]]
    target = real_res or results

    print_confusion(f"CONFUSION MATRIX - REAL ({len(real_res)}) [{label}]", real_res or results)
    if hard_res:
        hc = sum(1 for r in hard_res if r["correct"])
        ec = sum(1 for r in easy_res if r["correct"])
        print(f"\n  hard subset ([HARD CASE]):  {hc}/{len(hard_res)} = {hc/len(hard_res):.1%}")
        print(f"  easy subset:                 {ec}/{len(easy_res)} = {ec/max(len(easy_res),1):.1%}")
        print_confusion(f"CONFUSION MATRIX - HARD SUBSET ({len(hard_res)}) [{label}]", hard_res)
    if synthetic:
        print_confusion(f"CONFUSION MATRIX - COMBINED ({len(results)}) [{label}]", results)

    print_costly(target)
    print_misses(target)
    threshold_analysis(target)
    if args.baseline:
        diff_baseline(results, args.baseline)

    stamp = datetime.now(timezone.utc)
    out = args.out or (Path(__file__).parent /
                       f"results_{label.replace('/', '_')}_{stamp:%Y%m%dT%H%M%SZ}.json")
    out.write_text(json.dumps({
        "generated_at": stamp.isoformat(), "label": label, "provider": args.provider,
        "model": args.model if args.provider == "anthropic" else args.model_path,
        "wall_seconds": round(wall, 1),
        "counts": {"real": len(real_res), "synthetic": len(synthetic), "hard": len(hard_res)},
        "results": results,
    }, indent=2))
    print(f"\nfull per-example results -> {out}")
    if llm is not None:
        llm.close()


if __name__ == "__main__":
    main()
