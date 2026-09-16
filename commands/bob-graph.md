---
name: bob-graph
description: Re-render the network graph from the table you already have.
---

**Finding Bob and the folder.** Plugin settings are empty in Cowork. Use the bob-start skill's §1 to find the `bob.py` path and the folder, and use those wherever this file names `${CLAUDE_PLUGIN_ROOT}` or `$CLAUDE_PLUGIN_OPTION_DATA_DIR`. The address is saved in the folder: leave `--principal` out.

Re-draw `network.html` from `intros.csv` and `people.csv`. No mail is read —
this is a view of data Bob already has, so it is fast and works offline.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/tools/bob.py" graph \
  --data-dir "$CLAUDE_PLUGIN_OPTION_DATA_DIR"
```

Use this after a correction, or when they want the page back. If `intros.csv`
does not exist yet, say so and offer to find their introductions (the
bob-start skill) rather than rendering an empty graph.

The page makes no network requests. It is a file on their disk, opened in their
own browser — there is nothing to share unless they choose to.
