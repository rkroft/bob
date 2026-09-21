---
name: bob-ask
description: Answer "who introduced me to X?", "how do I know X?" or "did X introduce me to anyone?" from the user's Bob folder (intros.csv, people.csv) first and their mail second. Use whenever the user asks about one person's introduction history, in Claude Code or Cowork.
---

# One person: who connected us

The user is asking because they don't remember. "Not found" is only an answer
after every place it could be has been read. A thin check that comes back
empty is worse than no answer: the user believes it.

The folder is the one the bob-start skill's §1 finds. If it has no
`intros.csv`, the user hasn't scanned yet: say so, and go straight to §2 below.

For a question about one person's introductions, this skill wins over the
general "answer from the files" rule in bob-start.

## 1. The table first

Look the person up **by name** in `people.csv`, not only by an address the
user gave. People write from several addresses, and the table holds whichever
one the intro came from.

For "who introduced me to X", the answer is an `intros.csv` row with
`direction` inbound and one of X's addresses in `introduced`. Say who, the
date, and link the thread. A row where X is the `introducer` answers a
different question ("did X introduce me to anyone?"); mention it, don't
answer with it.

A row is the scan's judgment, not a fact. If the user doubts it, open the
thread and quote it rather than insist.

## 2. No row: read the mail, all of it

The table only holds what the scan scored as an introduction, so a missing row
is not an answer. If the Gmail tools aren't available here, say so and stop:
*"I only checked your Bob table. Mail isn't connected in this session, so I
can't say more."*

Search Gmail:

- by **full name** (`"Firstname Lastname"`) *and* by every address you know,
  `from:`, `to:` and `cc:` — one address is how a personal Gmail gets missed
  behind a work one;
- **every page**: keep asking for the next page until there is no page token.
  The count the search reports is an estimate; don't stop at it, and never
  stop after the first page. That is the failure this skill exists for.

For each thread, the search shows **only its newest five messages**. When it
shows exactly five and the thread's id is not among their ids, the first email
is cut off, and the first email is where an introduction happens. (Fewer than
five shown means the thread is whole; a thread the user started never carries
its own id.) Run
`get_thread` with `messageFormat: PLAIN_TEXT` on that thread before judging it.

If that comes to more than 100 threads, say the number and ask before going on.

What an introduction looks like: someone outside your own company adds the
person to a thread you are on, then steps back. Often it opens as an ask ("OK
if I introduce you to Dana?") and the person is added two or three messages
later. Not an introduction: a group invite, a newsletter, a calendar event
with them on it, or a colleague or assistant looped in to schedule or take
over work.

## 3. Say what you read

Answer in one line, then the evidence: who, when, the introducer's own words
if short, and the thread link. If nothing was found, say how much you read:
*"I read all 21 threads with Dana Okafor, under both addresses. None of
them is an introduction."* Then say where else it could be (in person, a text,
LinkedIn), since mail is one channel of several.

If you found an introduction the table lacks, say plainly that the scan missed
it and why, if you can see why (the thread was cut off, it opened as an ask).
Don't edit `intros.csv` by hand: the next scan rewrites that file and the row
would silently disappear.

## Done well

- The answer names who, when, and links the thread, or says how many
  threads under how many addresses were read before saying none.
- A miss by the scan is reported as a miss, with the reason if visible.

## Done badly

- "No introduction" with no count of threads read.
- Searching one address when the person has two.
- Judging a thread from its newest five messages when its first email is cut off.
- A hand-written row in `intros.csv`.
