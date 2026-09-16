---
name: bob-start
description: Use when someone has just installed Bob, asks to set Bob up, runs /bob-setup or /bob-scan, or asks to find their introductions or see their network for the first time — in Claude Code or Cowork, with or without a slash command.
---

# From install to their network, in one go

The user should not need a single slash command to get here. Setup runs
straight into the scan, the scan straight into the graph, and you say what is
happening as it happens. `commands/bob-setup.md` and `commands/bob-scan.md`
hold the detailed rules; this skill runs them back to back.

§1 is also where every other Bob command and skill finds Bob and the folder.

## What the user sees, in this order

1. **The welcome** from `commands/bob-setup.md` §0, as written.
2. **One short line per stage, as it starts** — plain words, no paths, flags or
   counts you have not got yet:
   - "Setting up your Bob folder…"
   - "Reading your mail for introductions — this part takes a while."
   - "Drawing your network…"
3. **The check table** once — folder, address, mail source, scope.
4. **What the scan printed**, then the link to their network.
5. **One question** — what next, in plain words (§5).

You stop and wait only when:
- **no folder is connected** (Cowork) — ask them to connect one,
- **no mail source works** — bob-setup §3's one question,
- **their address can't be read** — ask for it,
- **the folder may not persist** — preflight exit 2, ask its question,
- **the graph is done** — item 5.

Anything else goes straight on.

## 0. Already set up?

If `<folder>/intros.csv` exists (find the folder with §1 first), this person
has scanned before. Skip the welcome and don't rescan. Redraw the graph (§4,
the `graph` command only), answer what they asked from the files, and offer a
fresh scan as a choice. If `graph` stops because it doesn't know their address,
do the address part of §2 first, then redraw.

## 1. Find Bob and the folder

Plugin settings never reach Cowork, and `${CLAUDE_PLUGIN_ROOT}` may be empty
there, so never rely on either.

**The folder**, first match wins:
1. `$CLAUDE_PLUGIN_OPTION_DATA_DIR`, if it has a value (Claude Code).
2. Cowork: a `bob-network` folder inside the folder the user connected — so
   Bob's files don't scatter across a vault or a Documents folder. Exception:
   if the connected folder itself already holds `intros.csv`, use it as is.
   None connected → ask them to connect one and wait.
3. Claude Code with the setting empty → `~/bob-network`.

**Bob's own files.** Run this with the connected folder (or nothing) as the
last argument, so Bob is never picked up from inside the user's own files:

```bash
python3 - "${CLAUDE_PLUGIN_ROOT}" "${CLAUDE_SKILL_DIR}" "<connected folder>" <<'PY'
import json, os, sys, time
root_env, skill_dir, skip = (sys.argv[1:] + ["", "", ""])[:3]
skip = os.path.realpath(skip) if skip.strip() else None

def version(root):
    try:
        with open(os.path.join(root, ".claude-plugin", "plugin.json")) as fh:
            m = json.load(fh)
    except Exception:
        return None
    if m.get("name") != "bob" or not os.path.isfile(os.path.join(root, "tools", "bob.py")):
        return None
    try:
        return tuple(int(x) for x in str(m.get("version", "0")).split("."))
    except ValueError:
        return (0,)

def is_source(root):
    # A git checkout is someone's working copy of Bob, never the install.
    return os.path.exists(os.path.join(root, ".git"))

for root in (root_env, os.path.join(skill_dir, "..", "..") if skill_dir.strip() else ""):
    if root.strip() and version(root) is not None and not is_source(root):
        print(os.path.realpath(os.path.join(root, "tools", "bob.py"))); sys.exit(0)

found, deadline = [], time.time() + 60
for base in ("~/.claude/plugins", "/sessions", "/mnt", "/opt", "~"):
    base = os.path.expanduser(base)
    for d, dirs, _ in os.walk(base):
        if time.time() > deadline:
            break
        real = os.path.realpath(d)
        if skip and (real == skip or real.startswith(skip + os.sep)):
            dirs[:] = []; continue
        dirs[:] = [x for x in dirs if x not in (".git", "node_modules", "Library", ".venv")]
        v = version(d)
        if v is not None:
            if not is_source(d):
                installed = "/plugins/" in real + "/"
                found.append((installed, v, os.path.realpath(os.path.join(d, "tools", "bob.py"))))
            dirs[:] = []
    if found:
        break
if found:
    print(max(found)[2])
else:
    print("NOT FOUND"); sys.exit(1)
PY
```

It prints the path to `bob.py`. Shell variables don't survive between calls:
write that path out in full in every later command. The plugin's other files
(`commands/…`) are in the folder that contains `tools/`.

**If it prints NOT FOUND, stop:** tell them Bob's files can't be found and to
reinstall the plugin. Never read their mail some other way instead.

## 2. Setup

Say "Setting up your Bob folder…", then pick the mail source exactly as
`commands/bob-setup.md` §3 says. Then the address:

- **Gmail token:**
  `python3 "<bob.py>" setup --data-dir "<folder>" --gmail` — the token says
  whose mailbox it is.
- **Gmail connector:** search `in:sent` for 10 messages and take the From
  address that appears most often, then
  `python3 "<bob.py>" setup --data-dir "<folder>" --principal "<address>"`.
- **A mail export, or the connector search found nothing:** ask for it.

Exit `2` means Bob still has no address; exit `1` means it was refused — say
why in one sentence. Once saved, every later command reads it from the folder:
never pass `--principal` again. In Claude Code, what `bob setup` saves outranks
the plugin setting, so a correction sticks.

Show the table. If the address is wrong they'll say so; re-run setup with the
right one.

## 3. Scan

Say "Reading your mail for introductions — this part takes a while." Then
follow `commands/bob-scan.md` from "Before anything" onward, with these
substitutions everywhere it names them:

| It says | You use |
|---|---|
| `${CLAUDE_PLUGIN_ROOT}/tools/bob.py` | the `bob.py` path from §1 |
| `${CLAUDE_PLUGIN_ROOT}` alone | the folder that contains `tools/` |
| `$CLAUDE_PLUGIN_OPTION_DATA_DIR` | the folder |
| `--principal "$CLAUDE_PLUGIN_OPTION_PRINCIPAL"` | leave it out |

## 4. Graph

Say "Drawing your network…", then:

```bash
python3 "<bob.py>" graph --data-dir "<folder>"
```

Then show what the scan printed and the link, as `commands/bob-scan.md` says.

## 5. What next

Ask one question in plain words. Offer only what works here:

- **When they last spoke to each person** — only with a Gmail token or a mail
  export. The connector can't do this pass yet; leave it out rather than offer
  something that fails.
- **An Airtable base** they can sort and filter — only if the Airtable tools
  are on hand.
- **Thanking the people who introduced them** — only if the Gmail tools are on
  hand.
- **Nothing for now** — always.

Then: `commands/bob-roster.md`, the bob-table skill, or the bob-thanks skill.
Nothing → done. Don't chase it.

## Done right means

- No slash command was shown to the user.
- Nobody who had already scanned was rescanned without choosing it.
- The address was in the table before anything relied on it.
- An empty, failed or partial scan was never described as finding their
  introductions.
- No offer was made that can't run on this surface.
