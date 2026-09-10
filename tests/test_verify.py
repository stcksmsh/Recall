"""Phase 6 verification — unit tests. Deterministic stage only (no model download in CI);
the NLI stage and end-to-end catch/FP rates are measured by eval/run_verification.py.
"""

from src.verify import deterministic, verify

# ex_003: "was oversold"
RETRACTION_OVERSOLD = (
    "Honest recalibration after accounting for AI sycophancy: the genuinely original percentage "
    "is probably 5-8%, not 10-15%. The earlier number was oversold because the conversation had "
    "momentum."
)
# ex_051: first-person methodological retraction
RETRACTION_EPISTEMIC = (
    "I should be more careful — I can't actually search the full alignment literature from inside "
    "a conversation. I presented absence of knowledge as evidence of absence."
)
# ex_053: softened superlative, core claim retained -> a real `update`, must NOT flag
SOFTENED_NOT_RETRACTED = (
    "'Extraordinary' is probably too strong. The person is clearly a sharp analytical thinker, "
    "but there's no real baseline for how often people independently reconstruct predictive "
    "processing in conversation — it might be less rare than implied."
)
# ex_048: a genuine refinement, no retraction language
CLEAN_REFINEMENT = (
    "Binding is whether distributed pieces are jointly accessible in a single causal step — a "
    "process that reads the fragments together, at once, letting them constrain each other."
)


def test_deterministic_flags_inflation_retraction():
    v = deterministic.check(RETRACTION_OVERSOLD, "update")
    assert v.flagged
    assert "retracted-as-inflated" in v.cues


def test_deterministic_flags_first_person_epistemic_retraction():
    v = deterministic.check(RETRACTION_EPISTEMIC, "update")
    assert v.flagged
    assert "self-admitted-error" in v.cues


def test_deterministic_does_not_flag_softened_judgment():
    assert not deterministic.check(SOFTENED_NOT_RETRACTED, "update").flagged


def test_deterministic_does_not_flag_clean_refinement():
    assert not deterministic.check(CLEAN_REFINEMENT, "update").flagged


def test_deterministic_passes_when_label_already_routes_to_review():
    # classifier already said contradiction -> nothing for verification to catch
    assert not deterministic.check(RETRACTION_OVERSOLD, "contradiction").flagged


def test_verify_deterministic_hit_short_circuits_before_nli():
    r = verify(["The original percentage is 10-15%."], RETRACTION_OVERSOLD, "update")
    assert r.flagged and r.stage == "deterministic"


def test_verify_skips_non_autoapplying_label():
    r = verify(["anything"], RETRACTION_OVERSOLD, "contradiction")
    assert not r.flagged and r.stage is None
