---
name: bob-setup
description: Set up Bob — your folder, your addresses, and which mail source you can read.
---

**Run the bob-start skill.** It carries the user from here through the scan
to their network, and follows the sections below. Everything here assumes you
have its §1 (the `bob.py` path and the folder) in hand.

Set the user up and carry straight on into the scan (§4). Ask as little as possible and never ask
for something you can read.

## 0. Say what Bob is, before anything else

This may be the first sentence anyone ever reads about Bob, and the first real
user's note was that she *"was unclear so I asked it what to do."* Someone who
has just installed a plugin does not yet know what it is for. Open with it:

> Welcome to Bob. Bob is your networker in chief — it helps you strengthen the
> network you already have. It reads your mail, works out who introduced you to
> whom over the years, and helps you thank them.
>
> Let's start by finding the introductions people have made for you.

**The whole of what the user sees is three things:** that welcome, the check
table, and the line saying the scan is starting — plus, only when needed, the two questions
below (their address, if it can't be read; their mail source, if none works). Setup succeeds when they get from install
to their first scan fast. Nothing else goes in — no warnings about re-scanning
or overwriting files, no offers to back anything up, no notes on how Bob works
inside, no list of gaps or bugs you noticed along the way (even if the user
built Bob). If something is actually broken and blocks the scan, say what is
broken and the one thing to do about it, in a sentence, and stop. Everything else can wait until they ask.

Then check the setup. Two rules for everything after this point:

- **Show the check as a table** — folder, address, mail source, scope. That table
  was called out as genuinely useful: it is the reader seeing what Bob touches,
  in four lines, before granting anything.
- **Cut the jargon around it.** OAuth scope strings, package names and file modes
  belong in the table's cells where they can be skimmed past, never in prose the
  user has to read to find out what happens next. The same note said there is *"a
  lot of technical jargon here that I don't think the user needs to know."*
  Anything the user cannot act on does not need a sentence.

## 1. Their folder

The folder from bob-start §1 (in Cowork, `bob-network` inside the folder they
connected). Create it if it does not exist. Nothing personal
ever goes in the plugin directory — plugin updates replace it wholesale.

## 2. Their address

How Bob tells an intro made *for* them from one *they* made. bob-start §2 reads
it from the token or their sent mail and saves it with `bob setup`; ask only
when neither works.

## 3. Their mail source — pick one, don't compare them

Take the first of these that actually works and put it in the table's
mail-source row. Do not guess, and do not proceed as if mail is reachable when
it is not. /bob-scan checks the same list in the same order — keep the two in
step.

1. **A Gmail token already exists** (`~/.bob/google_token.json`). Row:
   "Gmail (read-only token)". Fastest path; someone who set it up keeps it.
2. **Their Gmail connector works.** The Gmail tools being listed is not enough —
   make one cheap call (a one-result search) before writing the row. Row:
   "Gmail (your connector)". This is the default in Cowork. If the address is
   still empty, the connector can often tell you whose mailbox it is — use that
   rather than asking.
3. **Neither.** This is the one place setup asks a question. One sentence:

   > Do you have a Google Takeout export (.mbox) of your mail? If not, I can
   > walk you through a ten-minute read-only Gmail connection.

   An .mbox → row "Mail export: <path>". The walkthrough → run it, below.

**Do not narrate the trade-offs.** No speed estimates, no thread counts, no
"names get filled in with an extra pass", no offer of an alternative source when
one already works. The first Cowork run did exactly that and the goal of setup
— get them to their introductions quickly — got lost in a paragraph of caveats
they could not act on. If they ask how it works, answer then.

### The Gmail walkthrough — only when they chose it

```bash
python3 -c "import googleapiclient" 2>/dev/null \
  || python3 -m pip install -r "${CLAUDE_PLUGIN_ROOT}/requirements.txt"
python3 "${CLAUDE_PLUGIN_ROOT}/tools/auth.py"
```

It walks them through making their own Google Cloud OAuth client (ten minutes,
once, free), opens the consent screen, and writes `~/.bob/google_token.json` at
0600 — read-only, mail only. Now that they have chosen it, tell them it is a
real piece of setup, and why it is theirs to make: no shared OAuth application
means nobody's mail is reachable by anyone but them.

## 4. Then go straight on

Don't end on "run /bob-scan" and wait. Say one line —

> Reading your mail for introductions now — this part takes a while.

— and carry on with `commands/bob-scan.md` in the same turn. The user asked to
be set up so they could see their introductions; stopping here makes them learn
a command to get what they already asked for.

If you ever do name a slash command:
**Write it as bare text — never in backticks or a fenced block.** A slash command
is not a shell command. Formatted as code it renders with a run-in-terminal
button, and the first real user clicked exactly that:

```
zsh: no such file or directory: /bob-scan
```

Twice — so it is what the affordance invites, not a slip. The most obvious
control on the screen ran the wrong thing and dead-ended the first run. This
applies to every slash command named in any Bob command or skill.
