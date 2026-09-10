"""Regenerate verification_set.yaml from the classifier eval set + the recorded run JSONs.

Run from repo root: python eval/verification_set/generate.py
Inputs: eval/classifier_set/real_examples.yaml, eval/results_sonnet5-76.json,
        eval/results_haiku45.json

Buckets (`verifier_must`):
- flag   : a known classifier failure the verifier must catch before it auto-applies
           (classifier gave an auto-applying label; truth is contradiction).
- pass   : a correctly-classified case the verifier must NOT flag (false-positive test).
           ex_053 (softened-not-retracted) is the key finer-grained case.
- detect : the classifier already routed these to review (said "contradiction"), so the
           verifier never runs on them in production. Kept only to measure the raw NLI
           contradiction signal on real retractions — not in the catch-rate denominator.
"""

import json
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
real = {d["id"]: d for d in yaml.safe_load_all(
    (ROOT / "eval/classifier_set/real_examples.yaml").read_text()) if d}
s76 = {x["id"]: x for x in json.loads(
    (ROOT / "eval/results_sonnet5-76.json").read_text())["results"]}
haiku = {x["id"]: x for x in json.loads(
    (ROOT / "eval/results_haiku45.json").read_text())["results"]}

# truth=contradiction, classifier gave an auto-applying label -> silent-corruption risk.
FLAG_BATCH1 = ["ex_003", "ex_023", "ex_040", "ex_044"]   # original Phase 2 costly-4
FLAG_BATCH2 = ["ex_051", "ex_052", "ex_069"]             # batch-2 analogues (generalisation test)
FLAG_HAIKU = ["ex_037"]                                  # Haiku SEV1, truth contradiction
DETECT = ["ex_047", "ex_050"]                            # classifier said contradiction (correct)
PASS_SOFT = ["ex_053"]                                   # softened-not-retracted -> real update
PASS_HICONF = ["ex_001", "ex_006", "ex_007", "ex_010", "ex_017", "ex_018", "ex_020", "ex_026",
               "ex_028", "ex_033", "ex_039", "ex_048", "ex_065", "ex_066", "ex_068", "ex_070",
               "ex_074"]

SPEC = (
    [(i, "flag", "batch1-costly", haiku if False else s76) for i in FLAG_BATCH1]
    + [(i, "flag", "batch2-new", s76) for i in FLAG_BATCH2]
    + [(i, "flag", "haiku-sev1", haiku) for i in FLAG_HAIKU]
    + [(i, "detect", "contradiction-control", s76) for i in DETECT]
    + [(i, "pass", "softened-not-retracted", s76) for i in PASS_SOFT]
    + [(i, "pass", "high-confidence-correct", s76) for i in PASS_HICONF]
)


def facts(ex):
    return [f["content"] for f in ex.get("existing_facts", [])]


def conflicting(ex):
    cid = ex.get("expected_conflicting_fact_id")
    return next((f["content"] for f in ex.get("existing_facts", []) if f["id"] == cid), None)


docs = []
for n, (i, must, sub, src) in enumerate(SPEC, 1):
    ex, p = real[i], src[i]
    docs.append({
        "id": f"vs_{n:03d}", "source_case": i, "subset": sub,
        "existing_facts": facts(ex), "conflicting_fact": conflicting(ex),
        "new_capture": ex["new_capture"]["content"], "truth": ex["expected_classification"],
        "classifier_model": p.get("model", "claude-sonnet-5") if "haiku" not in sub
        else "claude-haiku-4-5-20251001",
        "classifier_said": p["predicted"], "classifier_confidence": p["confidence"],
        "verifier_must": must,
    })

out = Path(__file__).parent / "verification_set.yaml"
with out.open("w") as fh:
    fh.write("# Phase 6 verification eval set. Regenerate with eval/verification_set/generate.py\n"
             "# verifier_must: flag = must catch (known failure) | pass = must NOT flag (FP test)\n"
             "#                detect = classifier already routed to review; NLI-signal probe only\n\n")
    yaml.safe_dump_all(docs, fh, sort_keys=False, width=100, allow_unicode=True)

print(f"wrote {len(docs)} cases -> {out}")
print(Counter(d["verifier_must"] for d in docs))
