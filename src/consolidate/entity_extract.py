"""Entity extraction for the write path.

Audit finding: `src/retrieve/entity_scope.py` (the entity/scope-anchored retrieval path, correct
as-is) never engages in production because nothing upstream of it ever populated a real `entity`
value -- `src/index/flush.py` has always accepted `entity`/`scope` parameters, but every real
caller left them at the "unsorted"/None default. Two facts about the same-named thing in two
different projects land pooled together with no way to tell them apart. This module is the
missing piece: it decides what `entity` a captured fact is about, deterministically, so
src/consolidate/run.py and src/consolidate/review.py have something real to pass into `flush()`
instead of the default.

Deterministic first, per the task brief: entity comes from lexical pattern matching over the
capture text itself (backtick-quoted, snake_case, or CamelCase identifiers -- the same shape a
project/module/table name takes, e.g. "the_database"), not a classifier guess. `scope` is a
separate, even simpler deterministic signal (the project/repo captured at write time --
src/capture/capture.py) and isn't this module's job.

Ambiguity -- more than one *equally-prominent* identifier-like candidate in one capture -- is not
resolved by picking one arbitrarily. The caller routes that case to the review queue instead,
reusing the executor's existing confidence-gated posture rather than inventing a new one. This
module never writes anything and never decides what happens next; it only classifies the text
in front of it, the same separation of concerns as src/consolidate/classifier.py.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from src.index.flush import UNSORTED_ENTITY

_BACKTICK_RE = re.compile(r"`([^`\n]+)`")
_CAMEL_CASE_RE = re.compile(r"\b[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+\b")
_SNAKE_CASE_RE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")


@dataclass
class EntityExtraction:
    entity: str
    ambiguous: bool
    candidates: list[str] = field(default_factory=list)


def _normalize(token: str) -> str:
    return token.strip().strip("`'\"").lower()


def _fold(normalized: str) -> str:
    """Collapse identifier-formatting differences that are the same name written two ways --
    "session_start" (snake_case) and "SessionStart" (CamelCase, normalized to "sessionstart" by
    `_normalize`) must compare and resolve as one entity, not split into two buckets just because
    one capture used underscores and another used capitals. Strips `_`/`-` only; a literal `.`
    (e.g. "hybrid.py") is not a casing artifact and is left alone.

    This is the comparison/grouping key AND the returned `entity` value -- the entity value has
    to be a pure function of the folded name alone (not of which spelling happened to appear in
    a given capture), or two independently-extracted captures using different spellings would
    resolve to two different entity strings despite this fold, defeating the point.
    """
    return re.sub(r"[_-]", "", normalized)


def extract_entity(content: str) -> EntityExtraction:
    """Find identifier-like tokens in `content` and pick the one this fact is most likely about.

    0 candidates: nothing identifiable in the text -- `entity` stays "unsorted", unchanged from
    today's behavior. There's no signal to extract, not an ambiguity to resolve.

    1 distinct (post-fold) candidate, or one candidate strictly more frequent than the others:
    unambiguous -- repetition is a deterministic (counted, not guessed) signal of which name the
    fact is actually about versus one mentioned only in passing. Frequency is counted on the
    folded form so "session_start" and "SessionStart" mentions add to the same count.

    A genuine tie among 2+ distinct folded candidates at the same frequency: no deterministic
    basis to prefer one, so this is flagged ambiguous rather than picked arbitrarily.
    """
    found = [
        _normalize(tok)
        for pattern in (_BACKTICK_RE, _CAMEL_CASE_RE, _SNAKE_CASE_RE)
        for tok in pattern.findall(content)
    ]

    if not found:
        return EntityExtraction(entity=UNSORTED_ENTITY, ambiguous=False, candidates=[])

    fold_counts = Counter(_fold(tok) for tok in found)
    top_count = max(fold_counts.values())
    leaders = sorted(key for key, n in fold_counts.items() if n == top_count)

    if len(leaders) == 1:
        return EntityExtraction(entity=leaders[0], ambiguous=False, candidates=sorted(fold_counts))

    return EntityExtraction(entity=UNSORTED_ENTITY, ambiguous=True, candidates=leaders)
