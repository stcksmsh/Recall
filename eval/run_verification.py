"""Phase 6 verification eval. Runs src/verify against eval/verification_set/verification_set.yaml.

Reports, per the Phase 6 scope:
- catch rate on the known-failure set (verifier_must=flag), broken out by subset so a
  regression on the batch-2 cases vs the original costly-4 is visible (that split tells you
  whether the verifier generalises or pattern-matches the original phrasing).
- false-positive rate on correctly-classified high-confidence cases (verifier_must=pass).
- real CPU latency per verification call on this hardware.

Usage:
    python eval/run_verification.py                 # deterministic only (the shipped config)
    python eval/run_verification.py --with-nli      # also run the eval-only NLI stage
    python eval/run_verification.py --with-nli --nli-threshold 0.9
"""

from __future__ import annotations

import argparse
import time
from collections import defaultdict
from pathlib import Path

import yaml

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.verify import verify  # noqa: E402

VSET = Path(__file__).parent / "verification_set" / "verification_set.yaml"


def load(path: Path = VSET) -> list[dict]:
    return [d for d in yaml.safe_load_all(path.read_text()) if d]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-nli", action="store_true", help="also run the eval-only NLI stage")
    ap.add_argument("--nli-threshold", type=float, default=0.55)
    ap.add_argument("--vset", type=Path, default=VSET)
    args = ap.parse_args()
    args.no_nli = not args.with_nli

    cases = load(args.vset)
    rows = []
    t_start = time.time()
    for c in cases:
        t0 = time.time()
        r = verify(c["existing_facts"], c["new_capture"], c["classifier_said"],
                   use_nli=not args.no_nli, nli_threshold=args.nli_threshold)
        # detect bucket: bypass the classifier-label gate to probe the raw NLI signal.
        if c["verifier_must"] == "detect":
            r = verify(c["existing_facts"], c["new_capture"], "update",
                       use_nli=not args.no_nli, nli_threshold=args.nli_threshold)
        rows.append({
            "id": c["id"], "source": c["source_case"], "subset": c["subset"],
            "must": c["verifier_must"], "truth": c["truth"],
            "said": c["classifier_said"], "conf": c["classifier_confidence"],
            "flagged": r.flagged, "stage": r.stage, "reason": r.reason,
            "latency_s": round(time.time() - t0, 3),
        })
    wall = time.time() - t_start

    flag_rows = [r for r in rows if r["must"] == "flag"]
    pass_rows = [r for r in rows if r["must"] == "pass"]
    detect_rows = [r for r in rows if r["must"] == "detect"]

    caught = [r for r in flag_rows if r["flagged"]]
    missed = [r for r in flag_rows if not r["flagged"]]
    fp = [r for r in pass_rows if r["flagged"]]

    print(f"\n{'=' * 74}\nPHASE 6 VERIFICATION EVAL"
          f"  (NLI {'off' if args.no_nli else 'on'}, threshold {args.nli_threshold})\n{'=' * 74}")

    print(f"\nCATCH RATE (verifier_must=flag): {len(caught)}/{len(flag_rows)} = "
          f"{len(caught) / len(flag_rows):.0%}")
    by_sub = defaultdict(lambda: [0, 0])
    for r in flag_rows:
        by_sub[r["subset"]][1] += 1
        if r["flagged"]:
            by_sub[r["subset"]][0] += 1
    for sub, (c, n) in sorted(by_sub.items()):
        print(f"  {sub:24} {c}/{n} = {c / n:.0%}")

    print(f"\n  by stage: "
          f"deterministic={sum(1 for r in caught if r['stage'] == 'deterministic')}, "
          f"nli={sum(1 for r in caught if r['stage'] == 'nli')}")

    if missed:
        print("\n  MISSED (silent-corruption risk remains):")
        for r in missed:
            print(f"    [{r['id']} / {r['source']}] {r['subset']}  said={r['said']}  "
                  f"{r['reason']}")

    print(f"\nFALSE-POSITIVE RATE (verifier_must=pass): {len(fp)}/{len(pass_rows)} = "
          f"{len(fp) / len(pass_rows):.0%}")
    for r in fp:
        print(f"    [{r['id']} / {r['source']}] {r['subset']}  stage={r['stage']}  {r['reason']}")
    soft = [r for r in pass_rows if r["subset"] == "softened-not-retracted"]
    if soft:
        s = soft[0]
        print(f"  softened-not-retracted (ex_053): flagged={s['flagged']}  "
              f"{'OK - kept as update' if not s['flagged'] else 'FALSE POSITIVE'}  ({s['reason']})")

    if detect_rows:
        print(f"\nNLI-SIGNAL PROBE (verifier_must=detect; classifier already routed these to "
              f"review):")
        for r in detect_rows:
            print(f"    [{r['id']} / {r['source']}] flagged={r['flagged']} stage={r['stage']}  "
                  f"{r['reason']}")

    lat = sorted(r["latency_s"] for r in rows)
    print(f"\nLATENCY per verification call (CPU, {len(rows)} calls, {wall:.0f}s wall):")
    print(f"  all:            min={lat[0]:.4f}s  median={lat[len(lat) // 2]:.4f}s  max={lat[-1]:.3f}s")
    if not args.no_nli:
        nli_lat = sorted(r["latency_s"] for r in rows
                         if r["stage"] not in ("deterministic", None) or r["latency_s"] > 0.05)
        if nli_lat:
            warm = nli_lat[:-1] if len(nli_lat) > 1 else nli_lat  # drop first (model load)
            print(f"  NLI path (warm): min={warm[0]:.3f}s  "
                  f"median={warm[len(warm) // 2]:.3f}s  max={warm[-1]:.3f}s  (n={len(warm)}); "
                  f"first call {nli_lat[-1] if nli_lat[-1] > warm[-1] else max(nli_lat):.1f}s incl. model load")
    else:
        print("  (deterministic stage only — regex, no model call)")

    print(f"\n{'=' * 74}\nPER-CASE\n{'=' * 74}")
    for r in rows:
        ok = "OK  " if (r["flagged"] == (r["must"] == "flag")) else "MISS"
        print(f"  {ok} [{r['id']}/{r['source']:7}] must={r['must']:4} flagged={str(r['flagged']):5} "
              f"stage={str(r['stage']):13} {r['subset']}")


if __name__ == "__main__":
    main()
