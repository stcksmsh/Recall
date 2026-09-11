"""Textual TUI for the review queue. `recall review` (no subcommand) launches this when there
are pending items; `recall review list/accept/override` keep working unchanged underneath for
scripting/non-TTY use -- this is a nicer front end over exactly those, not a second data path.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import Footer, Header, Input, Select, Static

from src.consolidate import review
from src.consolidate.classifier import VALID_CLASSIFICATIONS
from src.consolidate.review import ReviewItem
from src.review_tui.detail import ReviewDetail, load_detail

BRAIN_ROOT = Path("brain")
# Fixed, readable order for the Select widget -- VALID_CLASSIFICATIONS is a set.
CLASSIFICATIONS = ["new", "update", "contradiction", "context_dependent_both"]
assert set(CLASSIFICATIONS) == VALID_CLASSIFICATIONS


@dataclass
class SessionSummary:
    total: int
    accepted: int = 0
    overridden: int = 0

    @property
    def skipped_or_pending(self) -> int:
        """Deliberately one bucket, matching the spec: an explicit skip and just quitting
        before reaching an item are the same outcome for that item -- still pending."""
        return self.total - self.accepted - self.overridden

    def render(self) -> str:
        if self.total == 0:
            return "Review queue is empty."
        return (
            f"Session summary: {self.accepted} accepted, {self.overridden} overridden, "
            f"{self.skipped_or_pending} skipped/still pending (of {self.total})."
        )


def resolve_item(
    item: ReviewItem, selected: str, *, reviewer_note: str | None = None,
    brain_root: Path = BRAIN_ROOT,
) -> str:
    """The one place a confirm becomes a write -- same accept/override functions the CLI calls.
    Accept when the selection still matches the classifier's own proposal (a deliberate
    confirmation, not a silent default), override when it was changed. reviewer_note is optional
    free text, for either outcome, recorded on the correction only. Returns "accepted" or
    "overridden"."""
    if selected == item.classification_given:
        review.accept(item.id, reviewer_note=reviewer_note, brain_root=brain_root)
        return "accepted"
    review.override(item.id, selected, reviewer_note=reviewer_note, brain_root=brain_root)
    return "overridden"


class ReviewApp(App):
    CSS = """
    #progress { color: $text-muted; padding: 0 1; }
    .panel { border: round $primary; padding: 1; margin: 0 1 1 1; }
    #classifier_info { padding: 0 1; }
    #reasoning { padding: 0 1 1 1; color: $text-muted; }
    #extractor_note { padding: 0 1 1 1; color: $warning; }
    #classification_select { margin: 0 1; width: 50; }
    #reviewer_note { margin: 1 1 0 1; width: 76; }
    """

    BINDINGS = [
        Binding("c", "confirm", "Confirm", show=True),
        Binding("s", "skip", "Skip / defer", show=True),
        Binding("q", "quit_session", "Quit", show=True),
    ]

    def __init__(self, items: list[ReviewItem], *, brain_root: Path = BRAIN_ROOT):
        super().__init__()
        self.items = items
        self.brain_root = brain_root
        self.index = 0
        self.summary = SessionSummary(total=len(items))

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with VerticalScroll():
            yield Static(id="progress")
            yield Static(id="capture_content", classes="panel")
            yield Static(id="fact_content", classes="panel")
            yield Static(id="classifier_info")
            yield Static(id="reasoning")
            yield Static(id="extractor_note")
            yield Select(
                [(c, c) for c in CLASSIFICATIONS], id="classification_select", allow_blank=False,
            )
            yield Input(placeholder="optional note: why this call? (blank is fine)", id="reviewer_note")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "recall review"
        self._show_current()
        self.query_one("#classification_select", Select).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        # Enter in the note field confirms too -- typing a note then hitting Enter is one
        # motion, not "type note, tab away, press c".
        if event.input.id == "reviewer_note":
            self.action_confirm()

    def _show_current(self) -> None:
        if self.index >= len(self.items):
            self.exit()
            return

        item = self.items[self.index]
        detail = load_detail(item, brain_root=self.brain_root)

        self.query_one("#progress", Static).update(f"Item {self.index + 1} of {len(self.items)}")
        self.query_one("#capture_content", Static).update(
            f"[b]New capture[/b] (captured {item.captured_at}):\n\n{item.content}"
        )

        fact_widget = self.query_one("#fact_content", Static)
        if detail.conflicting_fact:
            f = detail.conflicting_fact
            fact_widget.update(
                f"[b]Existing fact[/b]  valid_at={f.valid_at or 'unknown'}  "
                f"scope={f.scope or '(none)'}\n\n{f.content}"
            )
        elif detail.considered_candidates:
            blocks = "\n\n".join(
                f"  valid_at={c.valid_at or 'unknown'}  scope={c.scope or '(none)'}\n  {c.content}"
                for c in detail.considered_candidates
            )
            fact_widget.update(
                "[b]Existing fact[/b]: none flagged as conflicting, but the classifier "
                f"considered {len(detail.considered_candidates)} candidate(s) (see reasoning "
                f"below for why none was named):\n\n{blocks}"
            )
        else:
            fact_widget.update("[b]Existing fact[/b]: none recorded for this item")

        self.query_one("#classifier_info", Static).update(
            f"Classifier proposed: [b]{item.classification_given}[/b]  "
            f"(confidence {item.confidence_given:.2f})"
        )
        self.query_one("#reasoning", Static).update(f"Reasoning: {detail.reasoning}")

        note_widget = self.query_one("#extractor_note", Static)
        if detail.extractor_note:
            note_widget.display = True
            note_widget.update(
                "[b]extractor_note[/b] (non-authoritative side observation -- not seen by the "
                f"classifier, not necessarily correct): {detail.extractor_note}"
            )
        else:
            note_widget.display = False
            note_widget.update("")

        select = self.query_one("#classification_select", Select)
        select.value = item.classification_given
        self.query_one("#reviewer_note", Input).value = ""

    def action_confirm(self) -> None:
        if self.index >= len(self.items):
            return
        item = self.items[self.index]
        selected = self.query_one("#classification_select", Select).value
        note = self.query_one("#reviewer_note", Input).value.strip() or None
        outcome = resolve_item(item, selected, reviewer_note=note, brain_root=self.brain_root)
        if outcome == "accepted":
            self.summary.accepted += 1
        else:
            self.summary.overridden += 1
        self.index += 1
        self._show_current()

    def action_skip(self) -> None:
        if self.index >= len(self.items):
            return
        self.index += 1
        self._show_current()

    def action_quit_session(self) -> None:
        self.exit()


def launch(*, brain_root: Path = BRAIN_ROOT) -> SessionSummary:
    """Entry point for `recall review` (no subcommand). Loads the current pending queue once
    (a snapshot for this session -- the same one `recall review list` would show), and runs the
    TUI over it. Returns the session summary for the caller to print after the terminal UI has
    exited (nothing here prints -- that's the CLI layer's job)."""
    items = review.list_pending(brain_root=brain_root)
    if not items:
        return SessionSummary(total=0)
    app = ReviewApp(items, brain_root=brain_root)
    app.run()
    return app.summary
