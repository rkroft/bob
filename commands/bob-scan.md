---
name: bob-scan
description: Read the mail, detect introductions both directions, write the table and open the graph.
---

Run the scan and end with the graph already open. Both happen in one command —
with no server there is no second moment, so the first run carries the value.

## Before anything: prove the folder

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/tools/bob.py" preflight \
  --data-dir "$CLAUDE_PLUGIN_OPTION_DATA_DIR" \
  --plugin-root "${CLAUDE_PLUGIN_ROOT}"
```

**Read the exit code, not the prose.** It says which of the two situations you
are in, so you never have to judge that from the wording:

| Exit | Meaning | What to do |
|---|---|---|
| `0` | Everything proven | Scan. |
| `1` | Something is broken | Print what it printed and **stop**. Do not ask the durability question — it will not fix a broken folder. |
| `2` | Nothing broken, durability unproven | Ask, below. |

On exit `2` it prints a question. Ask them that question and wait. Do not answer
it for them, do not guess from the path, and do not scan first and ask
afterwards — a scan is several hundred threads and the point is to ask before
the cost, not after.

On a yes:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/tools/bob.py" confirm-folder \
  --data-dir "$CLAUDE_PLUGIN_OPTION_DATA_DIR"
```

On a no, or on "I'm not sure": **stop.** Tell them to connect a folder they own
and run /bob-scan again. Do not offer to scan into the temporary one "just to
see" — that is several hundred threads spent on output that gets deleted.

**Never route around a failed preflight.** Do not read mail through the
connector directly, do not estimate what a scan would have found, do not offer
another way. If Bob cannot prove where the output lands, nothing was read, and
that is the whole message.

The scan enforces this itself — `scan --data-dir` refuses before reading any
mail unless the folder is confirmed. So skipping this section does not get
anyone a scan; it only gets them the same refusal later and less clearly. There
is an `--allow-ephemeral` flag. It is for the mbox path and for someone who has
said in words that they accept losing the output. Never reach for it to get
past a refusal.

Why this exists: on some surfaces the working folder is a temporary container
wiped when the session ends. Bob cannot tell the difference from the inside — a
temporary folder exists and is writable exactly like a real one — and the
closing copy below promises the file outlives the session. Without this gate
that promise is a lie the pilot has no way to catch.

## Run it

Paths and addresses come from the environment, not from text substitution:
`$CLAUDE_PLUGIN_OPTION_DATA_DIR` and `$CLAUDE_PLUGIN_OPTION_PRINCIPAL` are
exported to every process, and `${CLAUDE_PLUGIN_ROOT}` is where the plugin is
installed. Never invoke `tools/bob.py` by a relative path — the working
directory is the user's folder, not the plugin's.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/tools/bob.py" scan --gmail \
  --principal "$CLAUDE_PLUGIN_OPTION_PRINCIPAL" \
  --data-dir "$CLAUDE_PLUGIN_OPTION_DATA_DIR" \
  --out "$CLAUDE_PLUGIN_OPTION_DATA_DIR/intros.csv" \
  --people "$CLAUDE_PLUGIN_OPTION_DATA_DIR/people.csv"
```

Substitute `--mbox <path>` for `--gmail` when that is their source. If neither is
configured, stop and run `/bob-setup` — do not report an empty scan as a result.

### On the connector path, you run the retrieval

Where mail comes from the user's own Gmail connector there is no OAuth token and
Bob's Python cannot reach the connector — it is a tool you hold, not something a
subprocess can call. So you fetch, and Bob analyses.

**Do not start retrieval until the preflight above has passed.** On this path
the Python backstop runs *after* the expensive step, so unlike the Gmail and
mbox paths the gate is the only thing standing between a pilot and several
hundred threads fetched into a folder that gets deleted.

**Run the whole net. Do not invent the query list — ask for it:**

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/tools/bob.py" queries
```

That prints every search Bob expects, one per line. A handful of searches you
thought of yourself will report *complete coverage* against your own list,
which is how a partial scan comes to look exhaustive.

**Page every query to exhaustion.** Keep requesting the next page while the
response carries a `nextPageToken`, and stop only when it does not.

**Start a fresh `threads.jsonl`** — truncate it. A file left from a previous run
mixes two scans, and the thread count then belongs to neither. Write each thread
object as one line of JSON to `$CLAUDE_PLUGIN_OPTION_DATA_DIR/threads.jsonl`,
exactly as the API returned it, no reformatting.

**`resultCountEstimate` is not a count.** Measured 2026-09-02: every query
returns `201` — `subject:intro`, `subject:introduction`, `subject:connecting`,
`"connecting you"`, `"like to introduce"` — and page 2 of `subject:intro` still
had a `nextPageToken`. It is a sentinel for "200+". Never report it, never use
it to decide you are done, and never soften it into "about N threads". Cowork's
own model was caught doing exactly that. You are done when there is no next
page, not when a number looks big enough.

Then — **last, after the final page of the final query** — write
`$CLAUDE_PLUGIN_OPTION_DATA_DIR/coverage.json` recording what you actually did:

```json
{"queries": [
  {"query": "subject:intro", "pages": 3, "threads": 412, "exhausted": true},
  {"query": "putting you in touch", "pages": 0, "threads": 0, "error": "connector timed out"}
]}
```

Writing it last matters: a run that dies mid-retrieval then leaves no manifest
rather than a manifest describing a scan that did not finish.

`exhausted` must be the literal `true` and only when `nextPageToken` was absent
on the last page. Leave it out or set it `false` if you stopped for any other
reason — a query you gave up on and recorded as exhausted is the one lie this
whole mechanism exists to prevent. Record a query that errored with its `error`;
an errored query means mail that exists and was not read, and dropping it makes
a failure indistinguishable from an empty result.

Then hand it to Bob:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/tools/bob.py" scan \
  --connector "$CLAUDE_PLUGIN_OPTION_DATA_DIR/threads.jsonl" \
  --principal "$CLAUDE_PLUGIN_OPTION_PRINCIPAL" \
  --data-dir "$CLAUDE_PLUGIN_OPTION_DATA_DIR" \
  --out "$CLAUDE_PLUGIN_OPTION_DATA_DIR/intros.csv" \
  --people "$CLAUDE_PLUGIN_OPTION_DATA_DIR/people.csv"
```

It finds `coverage.json` beside the threads file on its own. Without one it
reports coverage as unknown, which is honest but weaker than what you can give
it — so write the manifest.

Bob cross-checks it against the file and against the net: a query it never
sees, a query not shown to have finished, or a manifest claiming more threads
than the file holds all make the scan report as partial. That is the mechanism
working, not a bug to route around.

**If the scan exits nonzero on this path, it read nothing.** Print what it said
and stop. Do not describe an empty result as "no introductions found", do not
estimate what a scan would have turned up, and do not go and read the mail
yourself to fill the gap.

Then render, without being asked:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/tools/bob.py" graph \
  --principal "$CLAUDE_PLUGIN_OPTION_PRINCIPAL" \
  --intros "$CLAUDE_PLUGIN_OPTION_DATA_DIR/intros.csv" \
  --people "$CLAUDE_PLUGIN_OPTION_DATA_DIR/people.csv" \
  --out "$CLAUDE_PLUGIN_OPTION_DATA_DIR/network.html"
```

**Do not open it yourself.** Hand them the path and let them click.

This reverses an earlier decision. The original reasoning was that with no server
there is no second moment, so the page had to appear or the value would be lost
to a path in scrollback. The first real user found the window seizing the screen
*jarring* — which is not how anyone should meet their own network for the first
time. A link clicked now lands in the same moment and lets them arrive rather
than be dropped. The fear was "forgotten", never "one click".

Say where it is, that it persists, and how to redraw it — none of which the user
can otherwise know:

> Your network is at **<data_dir>/network.html** — open it whenever you like.
>
> It stays there — this is a folder you connected, so the file outlives the
> session. Run /bob-graph to
> redraw it from what Bob already has, in seconds, without touching your mail
> again. The table behind it is intros.csv in the same folder, and it is yours
> to keep, edit, or delete.

Write the real resolved path, not the variable.

**Never put a slash command or a path in backticks in anything the user sees.**
Formatted as code it renders with a run-in-terminal button, and a slash command
is not a shell command. The first real user clicked exactly that and got
`zsh: no such file or directory: /bob-scan`, twice — the most obvious control on
the screen dead-ended the first run.

## What to say

Print what the scan printed. It already carries the counts, the recency split,
and the one surprising fact. Do not restate it in your own words and do not add
a metric it did not produce.

Two things are load-bearing:

- **Confident detections only**, with the maybes offered as a count they can ask
  for. Every row links back to its thread, which is what makes the table
  checkable rather than assertable.
- **Never assert absence.** "I don't see a reply — did it go somewhere else?"
  and never "you never replied." Bob sees one channel.

## Then offer the next step, and name it

The scan leaves `Last email` blank for everyone — filling it is a second pass
over the mailbox, so it gets its own consent rather than being smuggled in here.

> - /bob-roster — *fill in when you last spoke to each of these people.*
> *This one walks the whole mailbox rather than the intro threads, so it is
> slow — tens of minutes on a large account.*
> - /bob-table — *put these in an Airtable base you can sort and filter*
> - *or nothing — the graph is yours, and it'll be here*

Doing nothing is a finished outcome. Do not chase it.
