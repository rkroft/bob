---
name: bob-thanks
description: Triage the user's introductions, ask what came of the ones that took hold, and draft thank-yous into their Gmail drafts. Use for /bob-thanks, or when the user wants to thank the people who introduced them, follow up on an intro, or record what came of one.
---

# What came of them, and the emails that follow

The graph is a poster without this. This is the verb.

The user has already seen their network — that is why the ask is answerable.
Never run this before a scan.

## 0. Check what you can actually see, before asking anything

**Where the files are.** The user's folder is `$CLAUDE_PLUGIN_OPTION_DATA_DIR` —
resolve every path from it and never write to the working directory. `intros.csv`,
`people.csv`, `outcomes.md` and `corrections.md` all live there. Writing a
sentence about a named third party into whatever repo the user happened to have
open is not an acceptable default.

**Gmail connector.** Required — it is where the drafts land. If the Gmail tools
are not available, say exactly that and offer the degraded path out loud: write
the drafts to `<data_dir>/drafts.md` instead, and say that is what happened. Do
not walk someone through nine questions and discover this at the end.

**Calendar connector.** Optional, and its absence changes what a bucket *means*.
If it is not connected, say so before showing any buckets: *"Calendar isn't
connected, so 'never landed' means 'no reply in mail' only. That's one channel."*
Silently degrading from two-channel evidence to one is the expensive failure.

**The triage signal, and how to read it.** `intros.csv` now carries it, taken
by the scan while each thread was in hand: `observed`, `replied`, `they_replied`,
`met`, `first_reply`, `last_exchange`. Use `intro_store.after_of(row)` and
`after.triage(...)` — do not re-derive the buckets yourself, and do not read the
columns raw.

**`observed` is the column that matters.** Empty means *the scan never looked* —
a row written before after-signal existed — and `triage()` returns `cant_tell`
for it. That is not the same as "nobody replied", and treating it as such would
draft a late-reply email to a real third party about an introduction that may
have gone perfectly well. A corpus scanned before this existed comes back
entirely `cant_tell`, correctly.

So: if the rows carry no `observed`, say so and offer a re-scan. Then:

- **Do not assign buckets anyway.** A guessed bucket becomes a *late-reply email
  drafted to a real third party* about an introduction that actually landed.
  That is a wrong message to someone who is not the user, and it is unrecoverable.
- **Do not re-read the mailbox to get it.** A connector-driven scan is roughly a
  thousand `get_thread` calls (measured 2026-08-31, §3.2). That is not this
  skill's job.
- **Say what you can do instead:** *"These were scanned before I started
  recording what came of each introduction, so I can't sort them. Re-scan and I
  can — or I can ask you about them unsorted."* Unsorted and honest is a fine
  outcome. Sorted and invented is not.

**Never say "you never replied."** `never_landed` means no reply *in the mail
Bob can see*, and an intro can land perfectly well over text, LinkedIn, or a
call. Say *"I don't see a reply — did it go somewhere else?"* A `met` row is the
exception worth naming out loud: a calendar invite in the thread is direct
evidence they met, not an inference.

## 1. Triage — three buckets, two of them actionable

| Bucket | Test | What it's for |
|---|---|---|
| **Took hold** | A reply from the user, sustained exchange, or a meeting | The thank-you |
| **Never landed** | No reply from the user, and — where calendar is connected — no meeting with that person | A late reply |
| **Can't tell** | Anything else | Nothing. Say nothing about these. |

**Never landed is the more valuable bucket.** A warm intro going to waste is a
door still open, and it is the cheaper email to send. Only surface recent ones
individually — an intro dropped three years ago is a pattern, not a task, and
replying three years late is worse than silence. Old ones stay a count.

**The honesty rule is not optional.** Bob sees one channel. An intro can land
perfectly well over text, LinkedIn, or a call. So: *"I don't see a reply — did it
go somewhere else?"* and **never** *"you never replied."* A correction is recorded
in `corrections.md` and that intro is not raised again.

**Show events and spans, never tallies.** *"You met that April, and you were
still writing in September"* — not *"14 messages."* A message count reads as
surveillance wherever it appears, including in the prompt.

## 2. Ask — a sentence each, or "skip"

```
Nine of these look like they took hold. What came of them?
A sentence each, or "skip".

1. Dana Whitford → Sarah Chen · March 2019 · you met 3 times   [thread]
>
```

- **Write each answer to `outcomes.md` the moment it is given**, keyed by
  `thread_id`. Someone who answers six and abandons the rest keeps all six and is
  not asked again next month.
- **Skipping is free and instant.** Four skips out of eight is a fine outcome.
- **Follow-ups are cheap.** *"Working together — at Stripe, or after she left?"*
  costs four words and doubles the specificity.
- **The thread is the memory aid.** On *"I don't remember"*, offer to read the
  thread and propose a sentence they correct. Editing beats a blank page, and
  nothing ships without their confirmation.
- **Their sentence is the copy.** You are not paraphrasing a form field — it is
  already prose, and it is already theirs.
- Offer the escape hatch: the same questions written to a markdown file with
  thread links and blank lines, for someone who would rather answer over three
  days in their own editor.

**Where no sentence is given, no email is drafted.** Silence is the correct
output for an intro nobody can say anything about.

## 3. Draft — two kinds, and they are not the same email

**Thank-yous**, for intros that took hold. Grouped by introducer, one email each,
one line per intro, most-impactful first so the first line they read is the good
one.

**Late replies**, for recent intros that never landed. Addressed to the person
they were introduced to, *not* the introducer. Short and unfussy — the note that
reopens a door, not one that explains why it closed. No elaborate apology.

Both rules:

- **Never send.** Not on confirmation, not ever, in this version. `create_draft`
  only.
- **State the count before creating, not after, and take a yes.** *"That's 11
  drafts — 6 thank-yous and 5 late replies. Want to see them all first, or shall
  I create them?"* §4.7's confirmation covers the proposed *sentence*; the
  assembled draft, addressed to a real person, needs its own.
- **Report what was measured or told, never what was concluded.** No inference
  presented as a verified fact.
- **No derived metric appears as copy.** A number is triage input. The
  specificity comes from the user's own sentence.
- Signature discloses that Bob drafted and the user reviewed. On by default.

Drafts land in **their** Gmail drafts through their own Claude connector. This is
the one place the connector is the right tool: a handful of `create_draft` calls,
not a mailbox scan.

## 4. Afterwards

Say how many drafts, and where they are. Then stop.

Whether a draft was ever sent is readable from their Sent mail later — do not ask
them. Do not follow up. A tool whose pitch is that it holds nothing of yours
cannot also nag.
