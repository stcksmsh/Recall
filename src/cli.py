"""Recall CLI entry point."""

from __future__ import annotations

from pathlib import Path

import typer

from src.capture.capture import capture as do_capture
from src.consolidate.executor import DEFAULT_CONFIDENCE_THRESHOLD
from src.consolidate.review import accept as do_review_accept
from src.consolidate.review import list_pending as do_review_list
from src.consolidate.review import override as do_review_override
from src.consolidate.run import run as do_consolidate
from src.index.build import build as do_build
from src.retrieve.pipeline import retrieve_and_format

app = typer.Typer(
    name="recall",
    help="A self-maintaining AI memory system: plaintext-first, recoverable by construction.",
    no_args_is_help=True,
)

index_app = typer.Typer(help="Manage the derived SQLite index (Tier 2, rebuildable from Markdown).")
app.add_typer(index_app, name="index")

consolidate_app = typer.Typer(help="Run the batch consolidation loop (Tier 3).")
app.add_typer(consolidate_app, name="consolidate")

review_app = typer.Typer(help="Inspect and resolve flagged consolidation decisions.")
app.add_typer(review_app, name="review")


@review_app.callback(invoke_without_command=True)
def review_default(ctx: typer.Context):
    """`recall review` with no subcommand: launch the interactive TUI over pending items.
    `recall review list/accept/override` (below) still work unchanged for scripting/non-TTY
    use -- the TUI is a front end over the same review.accept/override calls, not a second
    data path."""
    if ctx.invoked_subcommand is not None:
        return
    from src.review_tui import launch

    summary = launch()
    typer.echo(summary.render())


@app.command()
def capture(
    text: str = typer.Argument(None, help="Text to capture. Omit to read from stdin."),
    file: Path = typer.Option(None, "--file", help="Read capture text from a file instead."),
    source: str = typer.Option("cli", help="Provenance tag for this capture."),
):
    """Write a new episodic capture. Instant — no model calls, no network calls."""
    if file is not None:
        content = file.read_text(encoding="utf-8")
    elif text is not None:
        content = text
    else:
        content = typer.get_text_stream("stdin").read()

    if not content.strip():
        typer.echo("Nothing to capture (empty input).", err=True)
        raise typer.Exit(code=1)

    path = do_capture(content, source=source)
    typer.echo(f"Captured -> {path}")


@index_app.command("build")
def index_build():
    """Rebuild the SQLite index from brain/episodic/ and brain/semantic/."""
    path = do_build()
    typer.echo(f"Index built -> {path}")


@consolidate_app.command("run")
def consolidate_run(
    confidence_threshold: float = typer.Option(
        DEFAULT_CONFIDENCE_THRESHOLD, help="Auto-apply above this confidence; below it goes to review."
    ),
    verify: bool = typer.Option(
        True, "--verify/--no-verify",
        help="Phase 6: run the lexical retraction check on auto-apply decisions; flags go to "
             "review instead of auto-applying. Cheap, no model. (The NLI stage is eval-only — "
             "see eval/PHASE6_FINDINGS.md.)"
    ),
):
    """Run the batch consolidation loop over any not-yet-consolidated episodic captures.

    Makes one classifier API call per capture — costs real money, however small. Nothing here
    is scheduled automatically; this is a manual, explicit trigger.
    """
    summary = do_consolidate(confidence_threshold=confidence_threshold, verify_decisions=verify)
    if summary.processed == 0:
        typer.echo("Nothing to consolidate.")
        return
    typer.echo(f"Processed {summary.processed} capture(s):")
    for action, count in sorted(summary.by_action.items()):
        typer.echo(f"  {action}: {count}")
    if summary.verifier_flagged:
        typer.echo(f"  ({summary.verifier_flagged} auto-apply decision(s) rerouted to review "
                   f"by the retraction check)")


@review_app.command("list")
def review_list():
    """List pending review-queue items."""
    items = do_review_list()
    if not items:
        typer.echo("Review queue is empty.")
        return
    typer.echo(f"{len(items)} pending review item(s):\n")
    for item in items:
        preview = item.content.strip().replace("\n", " ")[:100]
        typer.echo(f"[{item.id}]  {item.classification_given}  (confidence {item.confidence_given:.2f})")
        typer.echo(f"    capture:  {preview}")
        if item.conflicting_fact_id:
            conflicting = next(
                (f for f in item.candidate_facts if f.get("id") == item.conflicting_fact_id), None
            )
            if conflicting:
                fact_preview = str(conflicting.get("content", "")).strip().replace("\n", " ")[:100]
                typer.echo(f"    conflicts:{fact_preview}")
        typer.echo("")
    typer.echo("Resolve:  recall review accept <id>            (classifier was right)")
    typer.echo("          recall review override <id> <class>  (classifier was wrong)")


@review_app.command("accept")
def review_accept(
    review_id: str = typer.Argument(..., help="Review item id from `recall review list`."),
    note: str = typer.Option(
        None, "--note", help="Optional reason this was right, recorded on the correction record."
    ),
):
    """Confirm the classifier's original classification and apply its action."""
    path = do_review_accept(review_id, reviewer_note=note)
    typer.echo(f"Accepted -> {path}" if path else "Accepted (no fact written — see justification).")


@review_app.command("override")
def review_override(
    review_id: str = typer.Argument(..., help="Review item id from `recall review list`."),
    classification: str = typer.Argument(
        ..., help="new|update|contradiction|context_dependent_both — the correct classification."
    ),
    note: str = typer.Option(
        None, "--note", help="Optional reason the classifier was wrong, recorded on the correction record."
    ),
):
    """Supply the correct classification and apply its action instead of the classifier's."""
    path = do_review_override(review_id, classification, reviewer_note=note)
    typer.echo(f"Overridden -> {path}" if path else "Overridden (no fact written — see justification).")


@app.command()
def inject(
    for_session: bool = typer.Option(
        False, "--for-session",
        help="Emit every active semantic fact, injection-formatted, for a session-start hook."
    ),
):
    """Read-only context for a session-start hook: brain/semantic/ only, no query, no index
    build. Zero network calls, zero model calls, zero writes — see src/inject/session_start.py
    and .ai/decisions/0006 (Recall never writes .ai/; a session-start path stays cheap and local)."""
    if not for_session:
        typer.echo("recall inject: pass --for-session (the only mode today).", err=True)
        raise typer.Exit(code=1)
    from src.inject.session_start import render_for_session

    typer.echo(render_for_session())


@app.command()
def retrieve(
    query: str = typer.Argument(..., help="Query text."),
    entity: str = typer.Option(None, help="Filter to a specific entity (once entity resolution exists)."),
    scope: str = typer.Option(None, help="Filter to a specific scope tag."),
):
    """Retrieve and format stored facts for a query. No model calls — this is the read path
    that would feed an actual LLM conversation; nothing here talks to a model itself yet."""
    typer.echo(retrieve_and_format(query, entity=entity, scope=scope))


@app.command()
def status():
    """Show a read-only snapshot: capture / fact / review-queue / correction counts. No model calls."""
    from src.status import gather, render

    typer.echo(render(gather()))


if __name__ == "__main__":
    app()
