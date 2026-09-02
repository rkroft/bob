---
name: bob-scan
description: Read the mail, detect introductions both directions, write the table and open the graph.
---

Run the scan and end with the graph already open. Both happen in one command —
with no server there is no second moment, so the first run carries the value.

## Run it

Paths and addresses come from the environment, not from text substitution:
`$CLAUDE_PLUGIN_OPTION_DATA_DIR` and `$CLAUDE_PLUGIN_OPTION_PRINCIPAL` are
exported to every process, and `${CLAUDE_PLUGIN_ROOT}` is where the plugin is
installed. Never invoke `tools/bob.py` by a relative path — the working
directory is the user's folder, not the plugin's.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/tools/bob.py" scan --gmail \
  --principal "$CLAUDE_PLUGIN_OPTION_PRINCIPAL" \
  --out "$CLAUDE_PLUGIN_OPTION_DATA_DIR/intros.csv" \
  --people "$CLAUDE_PLUGIN_OPTION_DATA_DIR/people.csv"
```

Substitute `--mbox <path>` for `--gmail` when that is their source. If neither is
configured, stop and run `/bob-setup` — do not report an empty scan as a result.

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
> It stays there; it is a file on your disk, not a session. Run /bob-graph to
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
