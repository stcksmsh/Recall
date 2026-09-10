"""Combined end-to-end silent-corruption eval: confidence gate + deterministic verifier together.

Question this answers: of the true SEV1 cases in the 76-case real set (truth=contradiction that the
classifier mislabelled `update`/`context_dependent_both` and would therefore auto-apply as a
destructive SUPERSEDE/DUAL_RETAIN), how many survive BOTH shipped layers undetected?

Layer 1 — confidence gate (src/consolidate/executor.decide, DEFAULT_CONFIDENCE_THRESHOLD=0.90):
    update/both below 0.90 -> review (safe). At/above -> destructive auto-apply candidate.
Layer 2 — deterministic verifier (src/verify.verify, shipped config: use_nli=False), which runs
    only on SUPERSEDE/DUAL_RETAIN decisions (src/consolidate/run.run). flagged -> review (safe).

The SEV1 set is the `verifier_must == "flag"` rows of the verification set whose source case is a
claude-sonnet-5 failure (i.e. excluding the Haiku-only ex_037). Confidence and classifier label
come from that file, which mirrors eval/PHASE2_V2_BASELINE.md.

Usage:
    .venv/bin/python eval/run_combined.py
"""

from __future__ import annotations

from pathlib import Path

import yaml

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.consolidate.executor import DEFAULT_CONFIDENCE_THRESHOLD, Action, decide  # noqa: E402
from src.consolidate.classifier import ClassificationResult  # noqa: E402
from src.verify import verify  # noqa: E402

VSET = Path(__file__).parent / "verification_set" / "verification_set.yaml"
HAIKU_ONLY = {"ex_037"}  # not a sonnet-5 failure; excluded from the sonnet-5 pipeline count


def load(path: Path = VSET) -> list[dict]:
    return [d for d in yaml.safe_load_all(path.read_text()) if d]


def main() -> None:
    cases = load()
    sev1 = [
        c for c in cases
        if c["verifier_must"] == "flag"
        and c["truth"] == "contradiction"
        and c["classifier_said"] in ("update", "context_dependent_both")
        and c["source_case"] not in HAIKU_ONLY
    ]

    print(f"\n{'=' * 78}\nCOMBINED SILENT-CORRUPTION EVAL  (gate {DEFAULT_CONFIDENCE_THRESHOLD:.2f} "
          f"+ deterministic verifier)\n{'=' * 78}")
    print(f"\nSEV1 cases (truth=contradiction, classifier said update/both) in the 76-case set: "
          f"{len(sev1)}\n")

    hdr = f"{'case':<8}{'said':<24}{'conf':>5}  {'gate':<10}{'verifier':<20}{'outcome'}"
    print(hdr)
    print("-" * len(hdr))

    stopped_by_gate = stopped_by_verifier = leaked = 0
    leaked_ids = []
    for c in sorted(sev1, key=lambda x: x["source_case"]):
        conf = float(c["classifier_confidence"])
        said = c["classifier_said"]
        result = ClassificationResult(
            classification=said, confidence=conf,
            reasoning="(from verification set / PHASE2_V2_BASELINE)",
            conflicting_fact_id=None,
        )
        decision = decide(result, capture_id=c["source_case"])

        if decision.action == Action.REVIEW:
            stopped_by_gate += 1
            print(f"{c['source_case']:<8}{said:<24}{conf:>5.2f}  {'REVIEW':<10}{'(not reached)':<20}safe")
            continue

        # destructive auto-apply candidate -> verifier runs (shipped: deterministic only)
        vres = verify(c["existing_facts"], c["new_capture"], said, use_nli=False)
        if vres.flagged:
            stopped_by_verifier += 1
            outcome = "safe"
            vcol = f"FLAG ({vres.stage})"
        else:
            leaked += 1
            leaked_ids.append(c["source_case"])
            outcome = "*** SILENT CORRUPTION ***"
            vcol = "pass (missed)"
        print(f"{c['source_case']:<8}{said:<24}{conf:>5.2f}  {decision.action.value:<10}{vcol:<20}{outcome}")

    print("-" * len(hdr))
    print(f"\nstopped by confidence gate : {stopped_by_gate}/{len(sev1)}")
    print(f"stopped by verifier        : {stopped_by_verifier}/{len(sev1)}")
    print(f"LEAKED THROUGH BOTH LAYERS  : {leaked}/{len(sev1)}"
          + (f"  -> {', '.join(leaked_ids)}" if leaked_ids else ""))
    print(f"\ncombined end-to-end silent-corruption rate: {leaked}/76 "
          f"= {leaked / 76:.1%} of the real set\n")


if __name__ == "__main__":
    main()
