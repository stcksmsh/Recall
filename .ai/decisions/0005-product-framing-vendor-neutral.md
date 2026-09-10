# 0005 — Product differentiation: vendor-neutral, portable, auditable, honest

## Decision
Recall's differentiation is **not** "it's a memory system" — every platform has one now. It is:
- **vendor-neutral** — data format independent of any provider;
- **portable across providers** — the classifier is not locked to one LLM vendor;
- **auditable in plaintext / git** — every stored fact and every consolidation decision is a
  readable file with a justification and a commit hash;
- **honest about its own error rate** — see [0003](0003-classification-accuracy-ceiling.md).

Weigh any format or dependency choice against lock-in. Prefer plaintext, standard formats, and
provider-swappable interfaces.

## Rationale
The moat is trust and portability, not features. A memory layer users can `cat`, `git log`, and
move between providers is the thing incumbents structurally will not build.

## Status in codebase — PARTIAL. One real gap.
- **Data format: MATCHES.** Markdown + frontmatter + git. `README.md`: "cat it if we vanish".
  Provenance stamping ties each injected fact to a commit hash.
- **Auditability: MATCHES.** Every executor decision writes a `justification` block; the review
  queue and `corrections/` records are plaintext.
- **Provider portability: GAP.** `src/consolidate/classifier.py` is hardcoded to Anthropic —
  `import anthropic`, `DEFAULT_MODEL = "claude-sonnet-5"`, and it raises
  `RuntimeError("ANTHROPIC_API_KEY is not set ... no local classifier is supported")`. Only the
  **eval** harness (`eval/run_eval.py`) is multi-provider (Anthropic + local llama.cpp). The
  production write path is single-vendor.
  - Not a contradiction with a baked decision: `BUILD_PLAN.md` §3 always intended
    "Claude API (Sonnet-class) **or GPT-4o-class**", i.e. swappable. It was just never built.
  - Tracked as task **provider-portability** under plan `recall-v1`.

## Conflicts / gaps
The provider-portability gap above. Closing it is required for the "portable across providers"
half of this constraint to be true of the code, not just the docs.
