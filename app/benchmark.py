"""
Benchmark: measures the AI review layer's accuracy on a labeled batch of
synthetic deliverable submissions.

This exists to answer the question every judge asks: "you say it flags
weak submissions -- how well, actually?" Run this and you get a real,
reproducible number instead of a hand-wavy claim.

Each test case has a `should_flag` label (a human judgment call about
whether a reasonable client would want a closer look at this submission).
We run it through the SAME ai_review.review_deliverable() function the
live app uses -- not a separate mock -- so this number reflects the
actual shipped behavior, not an idealized version of it.

Usage:
    python3 -m app.benchmark
"""

from app.ai_review import review_deliverable

# Each case: (scope_description, deliverable_link, deliverable_note, should_flag, label)
CASES = [
    # --- Clearly good submissions (should NOT be flagged) ---
    (
        "Figma wireframes for 5 core screens, delivered as a shared link",
        "https://figma.com/file/abc123xyz",
        "Delivered Figma wireframes for all 5 core screens as agreed in scope. "
        "Includes homepage, product listing, product detail, cart, and checkout.",
        False,
        "good: detailed note, valid link, strong scope overlap",
    ),
    (
        "Full responsive HTML/CSS build of homepage matching approved wireframes",
        "https://github.com/priya-dev/homepage-build/pull/4",
        "Homepage build complete and responsive across mobile/tablet/desktop, "
        "matches the approved wireframes pixel-for-pixel. PR ready for review.",
        False,
        "good: PR link, specific technical detail, scope match",
    ),
    (
        "Logo design: 3 initial concepts as PNG/SVG",
        "https://drive.google.com/drive/folders/1abc2def3ghi",
        "Uploaded 3 logo concepts in PNG and SVG format as requested, "
        "with a short rationale doc for each direction.",
        False,
        "good: drive link, concrete deliverable count matches scope",
    ),
    (
        "API integration: connect payment webhook to internal order system",
        "https://github.com/priya-dev/webhook-integration/commit/9f2a1c",
        "Webhook integration complete, tested against Razorpay test events, "
        "order status now updates automatically on payment.captured.",
        False,
        "good: commit link, describes verification step",
    ),
    (
        "Blog post: 1200-word article on sustainable packaging trends",
        "https://docs.google.com/document/d/1xyz",
        "Draft is 1240 words, covers the 4 trends we discussed on the call, "
        "sources linked inline, ready for your edits.",
        False,
        "good: doc link, word count matches scope, describes content",
    ),

    # --- Clearly weak/suspicious submissions (SHOULD be flagged) ---
    (
        "Figma wireframes for 5 core screens, delivered as a shared link",
        "",
        "done",
        True,
        "bad: empty link, one-word note",
    ),
    (
        "Full responsive HTML/CSS build of homepage matching approved wireframes",
        "not a real url",
        "finished it, check it out",
        True,
        "bad: invalid URL format, vague note, no scope keywords",
    ),
    (
        "API integration: connect payment webhook to internal order system",
        "https://example.com",
        "",
        True,
        "bad: placeholder-looking link, no note at all",
    ),
    (
        "Blog post: 1200-word article on sustainable packaging trends",
        "https://google.com",
        "ok",
        True,
        "bad: unrelated link, near-empty note",
    ),
    (
        "Logo design: 3 initial concepts as PNG/SVG",
        "https://drive.google.com/somewhere",
        "will send later",
        True,
        "bad: note admits work isn't actually delivered yet",
    ),
    (
        "Figma wireframes for 5 core screens, delivered as a shared link",
        "https://figma.com/file/qrs789",
        "Shipped mockups for the homepage, listing, product, cart, and payment "
        "flow -- all reviewed against the brief we agreed on last week.",
        False,
        "good: paraphrases scope in different words, zero literal keyword "
        "overlap but clearly on-topic and detailed -- tests the softened "
        "overlap rule doesn't false-positive on legitimate rewording",
    ),
]


def run_benchmark():
    correct = 0
    false_positives = []  # good submissions incorrectly flagged
    false_negatives = []  # bad submissions incorrectly passed clean

    print(f"{'LABEL':<55} {'EXPECTED':<10} {'GOT':<10} {'RESULT'}")
    print("-" * 95)

    for scope, link, note, should_flag, label in CASES:
        result = review_deliverable(scope, link, note)
        was_flagged = len(result["flags"]) > 0

        correct_call = was_flagged == should_flag
        if correct_call:
            correct += 1
        elif should_flag and not was_flagged:
            false_negatives.append(label)
        elif not should_flag and was_flagged:
            false_positives.append(label)

        print(
            f"{label:<55} "
            f"{'flag' if should_flag else 'clean':<10} "
            f"{'flag' if was_flagged else 'clean':<10} "
            f"{'OK' if correct_call else 'MISS'}"
        )

    total = len(CASES)
    accuracy = correct / total * 100

    print("-" * 95)
    print(f"\nAccuracy: {correct}/{total} ({accuracy:.0f}%)")
    print(f"False positives (good work wrongly flagged): {len(false_positives)}")
    for fp in false_positives:
        print(f"  - {fp}")
    print(f"False negatives (weak work wrongly passed clean): {len(false_negatives)}")
    for fn in false_negatives:
        print(f"  - {fn}")


if __name__ == "__main__":
    run_benchmark()
