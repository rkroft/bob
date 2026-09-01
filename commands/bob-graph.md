---
name: bob-graph
description: Re-render the network graph from the table you already have.
---

Re-draw `network.html` from `intros.csv` and `people.csv`. No mail is read —
this is a view of data Bob already has, so it is fast and works offline.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/tools/bob.py" graph \
  --principal "$CLAUDE_PLUGIN_OPTION_PRINCIPAL" \
  --intros "$CLAUDE_PLUGIN_OPTION_DATA_DIR/intros.csv" \
  --people "$CLAUDE_PLUGIN_OPTION_DATA_DIR/people.csv" \
  --out "$CLAUDE_PLUGIN_OPTION_DATA_DIR/network.html"
```

Use this after a correction, or when they want the page back. If `intros.csv`
does not exist yet, say so and point at `/bob-scan` rather than rendering an
empty graph.

The page makes no network requests. It is a file on their disk, opened in their
own browser — there is nothing to share unless they choose to.
