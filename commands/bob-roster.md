---
name: bob-roster
description: Fill in when you last spoke to each person — a second pass over the mailbox.
---

The scan writes everyone into `people.csv` but leaves `Last email` blank. Only
this pass fills it, because last-contact is the one piece of the roster that has
to look **beyond intro threads** — Bob asks the mailbox about each person on
the roster and takes their most recent direct exchange.

Say that before starting. It is a second read of their mail, so it gets its own
yes rather than riding along with the scan.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/tools/bob.py" roster --gmail \
  --principal "$CLAUDE_PLUGIN_OPTION_PRINCIPAL" \
  --people "$CLAUDE_PLUGIN_OPTION_DATA_DIR/people.csv"
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
  --principal "$CLAUDE_PLUGIN_OPTION_PRINCIPAL" \
  --intros "$CLAUDE_PLUGIN_OPTION_DATA_DIR/intros.csv" \
  --people "$CLAUDE_PLUGIN_OPTION_DATA_DIR/people.csv" \
  --out "$CLAUDE_PLUGIN_OPTION_DATA_DIR/network.html"
```
