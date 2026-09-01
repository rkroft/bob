---
name: bob-roster
description: Fill in when you last spoke to each person — a second pass over the mailbox.
---

The scan writes everyone into `people.csv` but leaves `Last email` blank. Only
this pass fills it, because last-contact is the one piece of the roster that has
to look **beyond intro threads** — a pass over the mailbox collecting the most
recent direct exchange per address.

Say that before starting. It is a second read of their mail, so it gets its own
yes rather than riding along with the scan.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/tools/bob.py" roster --gmail \
  --principal "$CLAUDE_PLUGIN_OPTION_PRINCIPAL" \
  --people "$CLAUDE_PLUGIN_OPTION_DATA_DIR/people.csv" \
  --query "newer_than:5y"
```

Use `--mbox <path>` instead of `--gmail` for a local export. Drop `--query` to
read the whole mailbox; it is slower and rarely changes the answer.

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
