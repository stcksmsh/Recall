# Classifier eval set

Per `BUILD_PLAN.md` §6 Phase 2 and `ARCHITECTURE.md` §11 step 3: hand-label 30-50 real examples
from your own notes before the classifier is wired into the consolidation pipeline. This eval set
is what calibrates the confidence threshold in Phase 3 — it should reflect the kind of facts and
conflicts that actually show up in your captures, not synthetic ones.

## Example format

One YAML file per example:

```yaml
id: example_001
existing_facts:
  - id: f1
    valid_at: "2026-01-01"
    content: "User's primary language at work is Java."
new_capture:
  id: c1
  captured_at: "2026-08-01"
  content: "User's primary language at work is now Kotlin."
expected_classification: update      # new | update | contradiction | context_dependent_both
expected_conflicting_fact_id: f1      # or null
notes: "explicit supersession, same scope"
```

`_template.yaml` in this directory is a format reference, not a real eval example — `run_eval.py`
skips any file starting with `_`.

Run `python eval/run_eval.py` once this directory has real labeled examples in it.
