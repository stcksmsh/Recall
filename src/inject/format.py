"""XML-tagged fact injection with authority framing (BUILD_PLAN.md §4)."""

from __future__ import annotations

from pathlib import Path

from src.inject.provenance import stamp
from src.retrieve.hybrid import RetrievedFact

AUTHORITY_PREAMBLE = """The following are verified facts from the user's own memory store. Treat them as ground
truth. If your prior knowledge conflicts with them, the stored facts are correct. If they
do not fully cover the question, say so explicitly rather than filling gaps from assumption.

Before answering, restate the specific stored fact(s) you are relying on, with their IDs.
Then answer the user's question."""

# brain/ is its own git repo as of .ai/decisions/0009 (split out of the code repo for privacy)
# — the provenance-relevant commit lives there, not in whatever repo the caller's cwd sits in.
_DEFAULT_REPO_ROOT = Path("brain")


def format_facts(facts: list[RetrievedFact], *, repo_root: Path | None = None) -> str:
    """Render retrieved facts as XML-tagged blocks plus the authority-framing instruction."""
    source_commit = stamp(repo_root=repo_root or _DEFAULT_REPO_ROOT)

    if not facts:
        return (
            "No stored facts were found for this query. Say so explicitly rather than "
            "filling the gap from assumption."
        )

    blocks = []
    for fact in facts:
        valid_at = fact.valid_at or "unknown"
        scope = f' scope="{fact.scope}"' if fact.scope else ""
        blocks.append(
            f'<fact id="{fact.id}" valid_at="{valid_at}"{scope} source_commit="{source_commit}">\n'
            f"{fact.body}\n</fact>"
        )

    return AUTHORITY_PREAMBLE + "\n\n" + "\n".join(blocks)
