---
name: bob-roster
description: Fill in when you last spoke to each person — a second pass over the mailbox.
---

**Finding Bob and the folder.** Plugin settings are empty in Cowork. Use the bob-start skill's §1 to find the `bob.py` path and the folder, and use those wherever this file names `${CLAUDE_PLUGIN_ROOT}` or `$CLAUDE_PLUGIN_OPTION_DATA_DIR`. The address is saved in the folder: leave `--principal` out.

**Needs a Gmail token or a mail export.** There is no connector path for this
pass yet. On the connector alone, say it isn't available here yet and stop —
don't start it and let it fail.

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
