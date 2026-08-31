# Milestone Escrow Agent

Built for Razorpay AI Buildathon 2026 — Open Track.

**The itch (sourced from Razorpay's own Fix My Itch tool):**
"Why do freelancers ghost projects after partial payments without
accountability systems?" — and the inverse: clients ghosting freelancers
after real work is delivered.

## What it does

Splits a freelance project into milestones. Each milestone:

1. **PENDING_FUNDING** — client hasn't funded it yet
2. **FUNDED** — client funds it, money is "held" (Razorpay test-mode Order created)
3. **DELIVERED / FLAGGED** — freelancer submits proof of work; an AI layer
   reviews it and either passes it through clean (`DELIVERED`) or flags it
   for closer human attention (`FLAGGED`) based on deterministic checks
   (missing link, vague note, no scope-keyword overlap)
4. **RELEASED / DISPUTED / REFUNDED** — the client, a human, makes the
   actual call. The AI never releases or refunds money itself.

Every transition is written to an immutable audit log
(`AuditEvent` table) with actor, action, timestamp, and detail — visible
in the UI under "Audit trail" on each milestone.

## The guardrail (the whole point of this build)

`app/ai_review.py` is explicit about this in its docstring: the AI module
can only ever return a summary, a recommendation, and a list of flags.
It has zero ability to change a milestone's status to `RELEASED` or
`REFUNDED` — only `main.py`'s human-triggered routes (`/release`,
`/refund`) can do that. You could delete the AI module entirely and the
escrow flow still works correctly — it just loses the review assist.

## Running it

```bash
pip install -r requirements.txt --break-system-packages
python3 -m uvicorn app.main:app --reload
```

Visit http://localhost:8000

### Measuring AI review accuracy

`app/benchmark.py` runs the same `ai_review.review_deliverable()` function
the live app uses against a labeled batch of 10 synthetic submissions (5
clearly good, 5 clearly weak/suspicious) and reports accuracy:

```bash
python3 -m app.benchmark
```

Current result: **10/10 (100%)**, 0 false positives, 0 false negatives.

This is an initial benchmark, not a claim of production-grade accuracy —
the flag rules are deterministic (missing link, vague note, no scope
overlap), so they're expected to do well on clear-cut cases like these.
The honest next step with more time would be expanding this set with
genuinely ambiguous, borderline submissions to find where the simple
rules actually break.

### Optional: real Razorpay test-mode keys

Without any keys set, the app runs in **mock mode** — it fabricates
realistic-looking order IDs so the whole flow works end to end for a demo.

To hit the real Razorpay test-mode API:

```bash
export RAZORPAY_KEY_ID=rzp_test_xxxxxxxx
export RAZORPAY_KEY_SECRET=xxxxxxxxxxxxxxxx
```

Get test keys from Razorpay Dashboard → Settings → API Keys → Generate Test Key.

### Optional: Claude-powered AI summaries

Without a key, the AI review step falls back to a simple extractive
summary (still runs the deterministic flag checks either way).

```bash
export ANTHROPIC_API_KEY=sk-ant-xxxxxxxx
```

## Project structure

```
app/
  main.py            — FastAPI routes, the state machine transitions
  models.py           — SQLAlchemy models (Project, Milestone, AuditEvent)
  razorpay_client.py   — Razorpay test-mode wrapper (mock fallback)
  ai_review.py         — AI review layer (advisory only, never decides)
  templates/            — Jinja2 HTML (dashboard UI)
  static/style.css      — dark theme styling
```

## What's intentionally left out (given the build window)

- Auth / multi-user accounts — demo assumes a single-browser client +
  freelancer view for simplicity
- Real payout execution via Razorpay Route — release is logged and
  simulated; wiring actual payouts is a small, well-scoped follow-up
  (see the comment in `razorpay_client.release_payment`)
- File uploads for deliverables — links only, to keep the demo fast to
  build and test

## Metrics to report in the pitch

- % of test submissions correctly flagged vs. passed through clean
  (run a batch of good/bad synthetic submissions through `/deliver`
  and compare to your own labeling)
- Time from delivery submission to a state (delivered/flagged) —
  should be near-instant since review is heuristic + optional LLM call
- Every dispute has a full audit trail — screenshot the `<details>`
  audit log in the panel interview as your "explainable, bounded, gated"
  evidence
