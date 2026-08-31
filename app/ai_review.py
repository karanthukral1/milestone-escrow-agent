"""
AI review layer.

DESIGN PRINCIPLE (this is the guardrail the whole project hinges on):
This module NEVER changes a milestone's status to RELEASED or REFUNDED.
It only ever produces:
  - a short summary of the deliverable
  - a recommendation string: "release" or "review"
  - a list of flag reasons (deterministic rule hits)

A human (the client, via the dashboard) reads this and makes the actual
call. If you rip this whole module out, the escrow flow still works —
it just loses the assist. That's intentional: the AI is a co-pilot on
the review step, not an actor with payment authority.

If ANTHROPIC_API_KEY is set, this uses Claude to write a natural-language
summary. If not, it falls back to a deterministic extractive summary so
the app still runs end to end without any key configured.
"""

import os
import re

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

_LINK_PATTERN = re.compile(r"https?://\S+")


def _stem(word: str) -> str:
    """Very basic suffix stripping so 'wireframes' matches 'wireframe',
    'delivered' matches 'delivery', etc. Not linguistically rigorous —
    just enough to stop obvious plural/tense mismatches from causing a
    false flag."""
    for suffix in ("ing", "edly", "ed", "es", "s", "ly"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def _rule_based_flags(scope_description: str, deliverable_link: str, deliverable_note: str) -> list[str]:
    """Deterministic checks — cheap, explainable, and run before any LLM call."""
    flags = []

    if not deliverable_link or not deliverable_link.strip():
        flags.append("no_link_submitted")
    elif not _LINK_PATTERN.match(deliverable_link.strip()):
        flags.append("link_not_valid_url")

    note_clean = (deliverable_note or "").strip()
    note_too_short = len(note_clean) < 15
    if note_too_short:
        flags.append("note_too_short")

    # Scope-keyword overlap check, softened: a note can legitimately use
    # different wording than the scope (e.g. "shipped the login flow" vs
    # scope "user authentication screens") without being suspicious on
    # its own. We only flag zero overlap when it's ALSO paired with a
    # short note -- a short note with zero overlap is the actual red flag
    # (looks like a placeholder), not a detailed note that just phrases
    # things differently.
    scope_words = {_stem(w) for w in re.findall(r"[a-zA-Z]{4,}", scope_description.lower())}
    note_words = {_stem(w) for w in re.findall(r"[a-zA-Z]{4,}", note_clean.lower())}
    if scope_words and note_words:
        overlap = scope_words & note_words
        if len(overlap) == 0 and (note_too_short or len(note_words) <= 4):
            flags.append("low_keyword_overlap_with_scope")

    return flags


def _fallback_summary(deliverable_note: str, flags: list[str]) -> str:
    note = (deliverable_note or "").strip()
    snippet = (note[:180] + "...") if len(note) > 180 else note
    if not snippet:
        snippet = "(no note provided by freelancer)"
    return f"Freelancer submitted: \"{snippet}\""


def _claude_summary(scope_description: str, deliverable_note: str, deliverable_link: str) -> str | None:
    """Optional: use Claude to write a tighter summary. Returns None on any failure
    so the caller can fall back cleanly — this must never crash the request."""
    if not ANTHROPIC_API_KEY:
        return None
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=150,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "You are assisting a client reviewing a freelance milestone. "
                        "Summarize in 1-2 short sentences whether the submitted note "
                        "plausibly matches the agreed scope. Do not make a release "
                        "decision — only summarize.\n\n"
                        f"Agreed scope: {scope_description}\n"
                        f"Submitted link: {deliverable_link}\n"
                        f"Freelancer note: {deliverable_note}"
                    ),
                }
            ],
        )
        return "".join(block.text for block in msg.content if hasattr(block, "text")).strip()
    except Exception:
        return None


def review_deliverable(scope_description: str, deliverable_link: str, deliverable_note: str) -> dict:
    """Returns {summary, recommendation, flags} — the AI's full output for a milestone.
    `recommendation` is advisory text only; nothing downstream treats it as authoritative."""
    flags = _rule_based_flags(scope_description, deliverable_link, deliverable_note)

    summary = _claude_summary(scope_description, deliverable_note, deliverable_link)
    if summary is None:
        summary = _fallback_summary(deliverable_note, flags)

    recommendation = "review" if flags else "release"

    return {
        "summary": summary,
        "recommendation": recommendation,
        "flags": flags,
    }
