# Provider portability — what's swappable, and what it measures

`src/consolidate/classifier.py`'s `classify()` sends "prompt in, raw text out" through a
`ProviderFn` (`str -> str`) instead of hardcoding the Anthropic SDK shape. `provider=` selects
one by name from `PROVIDERS`, or accepts any callable directly (the seam a test or a future
backend uses). Config: `RECALL_CLASSIFIER_PROVIDER` env var, default `"anthropic"`.

```python
classify(capture, facts)                                   # default: anthropic, DEFAULT_MODEL
classify(capture, facts, model="claude-haiku-4-5-20251001") # anthropic, different model
classify(capture, facts, provider="local", model_path="models/qwen2.5-7b-q4.gguf")
classify(capture, facts, provider=my_fake_or_custom_fn)      # any str->str callable
```

This does not change `DEFAULT_CONFIDENCE_THRESHOLD` or the prompt — those stay exactly as
measured in `eval/PHASE2_V2_BASELINE.md`.

## What's actually measured, per provider

Per invariant 6, no "works with X" claim here is assumed — every number below already exists in
`eval/PHASE2_FOLLOWUP_FINDINGS.md`, measured on the batch-1 46-case real set (pre-dates the
batch-2 extension to 76; re-running batch-2 on these providers is not planned — see decision
0008, eval sets are frozen).

| provider | model | accuracy (46-case real) | contradiction recall | notable failure |
|---|---|---|---|---|
| `anthropic` (default) | `claude-sonnet-5` | 60.5% (76-case, `PHASE2_V2_BASELINE.md`) | 2/9 wrong-when-made | see `LIMITATIONS.md` |
| `anthropic` | `claude-haiku-4-5-20251001` | 43.5% | worse | **cannot classify `new` at all** — 0/8, all → `context_dependent_both` |
| `local` | Qwen2.5-7B-Instruct Q4_K_M (CPU, llama.cpp) | 28.3% | 0/8 | no usable confidence signal; ~15s/call |

**Conclusion this task doesn't change:** stay on `anthropic` / `claude-sonnet-5` for the real
write path. The `local` provider is a genuine second implementation (proves the seam works end
to end without any Anthropic-shaped object), not a recommendation — its accuracy is materially
worse and it is not wired into `consolidate/run.py`'s defaults.

## Why the RuntimeError changed

`classify()` used to say "no local classifier is supported" as an absolute, hardcoded to the one
provider that existed. It now names the provider that's actually configured and points at how to
change it:

> `ANTHROPIC_API_KEY is not set for classifier provider 'anthropic'. Set
> RECALL_CLASSIFIER_PROVIDER=local (with a model_path) to use a different configured provider,
> or set the key.`

## Tests

`tests/test_classifier.py` — `provider=` accepts a fake `str -> str` function with no network
call and no API key (`test_classify_accepts_a_fake_provider_function`), an unknown provider name
raises `ValueError` naming it, and the anthropic-provider error names the provider without the
old absolute claim.
