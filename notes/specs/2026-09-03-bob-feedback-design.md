# `/bob-feedback` — design

**Date:** 2026-09-03
**Status:** sections 1–2 approved; section 3 drafted, not yet approved. Not ready for an
implementation plan.

## The problem

Once someone installs Bob, its author sees nothing. The only feedback path that exists today is a
single link on the landing page — *"Something broke → open an issue on GitHub"* — which reaches
people who already have a GitHub account and are annoyed enough to file. It captures no confusion,
no unmet expectation, and nothing at all from the largest and most important population: people who
installed Bob, hit friction, and stopped.

Two things are wanted from the same mechanism: signal about what to improve, and a way for users to
contribute to Bob rather than only consume it.

## Constraint that governs everything

Bob's pitch is *"no server, no account, no database, Bob's author holds nothing of yours."* That
sentence is the product's differentiator, not a footnote. Any mechanism that transmits without an
explicit human action costs more than it returns.

**Decision: no telemetry.** Nothing is transmitted in the background. Bob composes a report on the
user's machine, shows it in full, and the user sends it. README and FAQ need no changes.

Costed alternatives, for the record:

| | Build | Run | Returns | Costs |
|---|---|---|---|---|
| Local-only, human sends *(chosen)* | ~3 days | $0 | What to improve, in prose | Nothing |
| Opt-in anonymous counters | ~2–3 days | $0–5/mo (Worker + D1) | The funnel, incl. *did they come back* | "No server" becomes false; a public POST endpoint to own |
| Counters + error text + volumes | ~4–5 days | same | The above, plus real tracebacks | Tracebacks raised while parsing mailboxes carry addresses |

At an install base in the dozens, counters buy one meaningful number — repeat usage — and every
other metric is noise at that sample size.

**Accepted tradeoff:** silent churn stays invisible. Nobody who quits without speaking will ever
appear in a report. The sample is biased by construction, and the design compensates only by asking
better questions of the people who do speak.

## Section 1 — The interview *(approved)*

`/bob-feedback` is not a form. It is a short interview Claude runs and then writes up. Three rules.

**1. Never ask what you can already see.** Before the first question Bob reads local state: counts
from `intros.csv` and `people.csv`, last scan date, plugin version, Gmail-connector vs mbox path,
and whatever just happened in the conversation. Opening with "how was your experience?" when Bob can
see a zero-result scan wastes the turn.

**2. At most three questions.** Claude picks from a bank keyed to state, follows up once on anything
concrete, and stops when answers go short.

| What Bob can see | What it asks |
|---|---|
| No Bob folder — never ran a scan | "You installed Bob and never ran it. What stopped you?" |
| Scan returned zero intros | "Zero is almost always Bob's fault, not your mailbox's. Name one intro in there it should have caught." |
| Scan returned results | "Looking at that list — who's missing?" · "Anyone on it who isn't actually an intro?" |
| They ran `/bob-thanks` | "Did you actually send any of them?" |
| Second or later scan | "You came back. What would make this worth opening every week?" |
| A command crashed | "What were you doing right before?" |
| Always available, as the closer | "Was there a moment you nearly gave up?" |

Two of these do unusual work. *"What stopped you?"* is the only route to someone who installed Bob
and bounced. *"Was there a moment you nearly gave up?"* finds friction people don't volunteer,
because a near-miss doesn't feel like a bug.

Wishes are asked as **"what did you expect Bob to do that it doesn't"**, never "what do you want."
Expectation exposes a mental model. Wants produce a wishlist.

**3. Specifics get chased.** If a user names a missed intro, Claude *offers* — never assumes — to
open that message, build a structurally identical fixture with invented people, and show the real
one and the fixture side by side. Only the fixture travels. This keeps the repo's standing rule
(every person in tests and examples is invented) intact, and the artifact drops into `tests/`
unmodified.

## Section 2 — Categories as router *(approved)*

The category is not a label on the report. It routes.

| | Meaning | Report must carry | Fix lives in | Default destination |
|---|---|---|---|---|
| **miss** | It was there; Bob didn't find it | Anonymized fixture | Detection heuristics | GitHub, public |
| **mistake** | Bob found it and got it wrong — not an intro, wrong direction, wrong people | Anonymized fixture | Detection heuristics | GitHub, public |
| **break** | It errored or crashed | Traceback, versions, what they were doing | Code | GitHub, public |
| **snag** | Nothing broke; they got stuck or confused | Which command, which step, what they expected | Copy, docs, flow | **Private** |
| **wish** | Expected something Bob doesn't do | The expectation, and what they'd have done with it | Roadmap | GitHub, public |

**Claude classifies; the user confirms.** Asking someone to self-select a category up front turns
the interview back into a form. Claude labels at the end — *"filing this as a snag, sound right?"* —
and one word moves it.

**The category picks public vs private, because the social cost of filing differs.** A miss reads as
a contribution and the reporter wants the credit. A snag reads as an admission — *"I didn't
understand your setup step"* — and public filing suppresses exactly the reports most worth having.
One word overrides either default.

**The public ones build the roadmap for free.** Five GitHub labels matching these names; the issue
list then sorts itself into *fix the core / fix the code / fix the words / build next*. The roadmap
is the `wish` label, and it fills itself.

**Accepted tradeoff:** five labels to maintain, and a misclassification sends a report to the wrong
place. Mitigated by the user-confirms step, not eliminated.

## Section 3 — Report, routing, failure *(drafted, NOT approved)*

**Report.** Dense enough to triage in under a minute; shown to the user verbatim before anything
moves.

```
Bob feedback — miss
v0.1.6 · gmail path · macOS 15.6 · py3.12
340 people · 12 intros · last scan 2026-09-01

What happened
  <their words, 2–4 lines>

What they expected
  <1–2 lines>

Nearly gave up
  <only if it came up>

Fixture
  miss-marcus-forward.eml  ← invented people, real structure
```

The context block is computed locally and displayed in full. Watching Bob take exactly three lines
of machine facts and nothing else *is* the trust demonstration.

**Routing.** Public → prefilled GitHub issue URL, category as its label. Private → a Gmail draft to
the Bob address through the same connector `/bob-thanks` already uses. Bob drafts, the user sends;
no new dependency.

**Three failure modes designed for:**

- *URL too long.* Prefilled issue URLs die north of ~8KB and a fixture will blow that. Above ~6KB,
  Bob writes the report to `<data_dir>/feedback/<date>-<kind>.md`, opens a plain new-issue page, and
  tells the user to paste the file. Never a silent truncation.
- *Answers get lost.* Bob writes the report to disk **before** attempting the issue URL or the
  connector, and names the path. Compose, persist, then transmit — a failed send must never eat
  typed text.
- *No Bob folder.* The command works anyway; the context block collapses to "no scan has been run,"
  and that fact is the headline.

Bob never guesses a fact it can't determine. An undetermined version prints `unknown`.

**Testing.** `tools/bob.py feedback context` emits the context block as JSON and takes ordinary unit
tests: no folder, empty CSVs, malformed CSVs, unknown version. The skill gets four scripted
walkthroughs — no-folder, zero-result scan, post-crash, happy-path-with-a-miss — asserting it asks
different questions in each, shows the report before routing, and sends nothing itself.

One test outranks the rest: **the fixture must contain no string drawn from the source message's
address fields or headers.** That assertion is what stands between this feature and the only failure
here that would actually cost trust.

## Explicitly not built

No endpoint. No counters. No server. No background transmission. No auto-send.

## Open questions

1. **`snag` as a fifth category** — proposed, not confirmed. Folding it into `wish` is the
   alternative; the cost is that copy fixes get buried in a feature backlog.
2. **The private address** — decided in principle (a dedicated address, not a `+alias`, not the
   personal inbox). Does not exist yet.
3. **Ambient invitation** — whether anything ever prompts for feedback unasked, or whether the
   command is the only door. If it exists it should obey the `session_start.py` doctrine already in
   the repo: speak only when there is something new, at most weekly, silent outside a Bob folder.
4. **Carrying cost** — every channel opened is a channel to tend. Three unanswered reports a week is
   worse than no channel. The report format is built for sub-minute triage; the promise made to
   reporters must be one that gets kept.

## Adjacent, and independent of this design

- `CONTRIBUTING.md` — does not exist.
- The landing page CTA is addressed only to people whose Bob broke. It should also invite "it worked
  but missed things" and "I expected it to do X."
- The five GitHub labels.
