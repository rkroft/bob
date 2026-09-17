---
name: bob-roster
description: Fill in when you last spoke to each person — a second pass over the mailbox.
---

**Finding Bob and the folder.** Plugin settings are empty in Cowork. Use the bob-start skill's §1 to find the `bob.py` path and the folder, and use those wherever this file names `${CLAUDE_PLUGIN_ROOT}` or `$CLAUDE_PLUGIN_OPTION_DATA_DIR`. The address is saved in the folder: leave `--principal` out.

The scan writes everyone into `people.csv` but leaves `Last email` blank. Only
this pass fills it, because last-contact is the one piece of the roster that has
to look **beyond intro threads** — Bob asks the mailbox about each person on
the roster and takes their most recent direct exchange.

Say that before starting. It is a second read of their mail, so it gets its own
yes rather than riding along with the scan.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/tools/bob.py" roster --gmail \
  --data-dir "$CLAUDE_PLUGIN_OPTION_DATA_DIR"
```

Use `--mbox <path>` instead of `--gmail` for a local export.

## On the Gmail connector

Bob's Python can't call the connector, so you search and Bob decides. About 3
minutes per 50 people. Say "Checking when you last spoke to each person…" and
give one progress line per batch — nothing else.

**Pick the run file.** List `$CLAUDE_PLUGIN_OPTION_DATA_DIR/roster-*.jsonl`.
If the newest one is dated within the last 7 days and its `roster-todo`
(step 1) shows `remaining` above 0, that run was stopped — continue it.
Otherwise start a new one named
`roster-<today, YYYY-MM-DD>.jsonl`. A finished file is never reused; that is
how a later run gets fresh dates instead of old ones. Call the chosen file
`RUN` below.

**How to write to `RUN`:** append only, one person at a time, with bash:

```bash
cat >> "RUN" <<'BOB_EOF'
{...one thread object, exactly as returned...}
{"asked": "X", "status": "ok"}
BOB_EOF
```

Never use a file-write tool on it — that replaces the file and loses the
markers. Searches may run in parallel; the appends happen one after another,
threads first, marker last.

**1. Get the next batch:**

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/tools/bob.py" roster-todo --connector "RUN" \
  --data-dir "$CLAUDE_PLUGIN_OPTION_DATA_DIR"
```

It prints `batch` (up to 50 addresses), `remaining` and `gave_up`. An empty
`batch` → step 4.

**2. For each address X in the batch** (searches 5–10 at a time):

- `search_threads`, query `from:X OR to:X`, `pageSize: 1`,
  `view: THREAD_VIEW_METADATA_ONLY`. Append each returned thread.
- **No shown message has X plus at most 5 addresses in total:** search again
  with `pageSize: 3` (same view) and append those threads too.
- **For any thread you appended where X is in none of the shown messages**
  (search shows only the newest 5): `get_thread` with
  `messageFormat: METADATA_ONLY` (never a format with bodies) and append it —
  **unless** the principal sent that thread's messages to more than 10 people.
  Those are announcements; skip the fetch, it is huge and can't count.
- Then append the marker: `{"asked": "X", "status": "ok"}` — including when
  there were zero threads. Any tool error → `{"asked": "X", "status":
  "blocked"}`. Anything other than `ok` counts as a failed lookup.

Don't decide who counts as contact. Bob's Python applies the rules (direct mail
only, machine senders out, newest date wins, dates never move backwards).

**3. Save the batch:**

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/tools/bob.py" roster --connector "RUN" \
  --data-dir "$CLAUDE_PLUGIN_OPTION_DATA_DIR"
```

**Exit code 1 → stop** and show what it printed. Otherwise back to step 1.

**4. Done.** Show the last `roster` summary as printed. It separates people with
nothing direct in their newest threads, people who could not be looked up, and
people not asked yet. If `gave_up` was not empty, say those people could not be
looked up after two tries. Then re-render (below).

A date on file only moves forward. If the dates were filled before a rule
change and look too recent, add `--reset-dates` to step 3 of a fresh run.

**No date filter, deliberately.** This used to pass `--query newer_than:5y`,
from when the command read the whole mailbox and narrowing it was the only way
to bound the work. Asking per person is bounded by the roster instead, so the
filter no longer buys speed — it only hides people. Someone last spoken to six
years ago is exactly who a "who have I lost touch with" list should surface,
and with the filter they came back blank, indistinguishable from someone Bob
had never seen.

**Last contact counts direct mail only.** A reply to an investor update, a
newsletter, or a life-update blast is not contact, and counting it fills the warm
set with people they have not actually spoken to in years. `Message.is_bulk`
already carries the List-Unsubscribe signal.

Afterwards, re-render so the roster shows it:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/tools/bob.py" graph \
  --data-dir "$CLAUDE_PLUGIN_OPTION_DATA_DIR"
```
