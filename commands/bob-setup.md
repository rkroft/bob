---
name: bob-setup
description: Set up Bob — your folder, your addresses, and which mail source you can read.
---

Set the user up so `/bob-scan` can run. Ask as little as possible and never ask
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

`${user_config.data_dir}` is where their network lives. Create it if it does not
exist. Nothing personal ever goes in the plugin directory — plugin updates
replace it wholesale.

## 2. Their addresses

`${user_config.principal}` is how Bob tells an intro made *for* them from one
*they* made. If it is empty, ask — this is the one question that has no default.

## 3. Their mail source — say the truth about this

Bob reads mail one of two ways today. Check which is available and tell them
plainly; do not guess and do not proceed as if mail is reachable when it is not.

**A local mailbox export** — `bob scan --mbox <path>`. Works immediately, no
credentials. Google Takeout produces one.

**Gmail directly** — `bob scan --gmail`. Needs a read-only token, which
`tools/auth.py` creates:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/tools/auth.py"
```

It walks them through making their own Google Cloud OAuth client (ten minutes,
once, free), opens the consent screen, and writes `~/.bob/google_token.json` at
0600. **Read-only and mail only** — Bob never sends from this credential;
drafts go through their own Claude connector.

Say plainly that this is a real piece of setup and not two questions, before
they start rather than after. And say why it is theirs to make rather than
Bob's: no shared OAuth application means nobody's mail is reachable by anyone
but them.

The Gmail path also needs three Python packages that nothing installs for them:
`google-api-python-client`, `google-auth`, `google-auth-oauthlib`. Check before
promising anything:

```bash
python3 -c "import googleapiclient" 2>/dev/null \
  || echo "missing: python3 -m pip install -r \"${CLAUDE_PLUGIN_ROOT}/requirements.txt\""
```

The mbox path is standard library only — no install, no credentials.

Check for the token. If it is absent, offer the mbox path first, because it is
the one that works this afternoon.

## 4. Then hand off

End by naming the next command, per the pipeline:

> Next, run /bob-scan — I'll read your mail and draw what I find. Six years takes
> about twenty minutes, most of it waiting.

**Write it as bare text — never in backticks or a fenced block.** A slash command
is not a shell command. Formatted as code it renders with a run-in-terminal
button, and the first real user clicked exactly that:

```
zsh: no such file or directory: /bob-scan
```

Twice — so it is what the affordance invites, not a slip. The most obvious
control on the screen ran the wrong thing and dead-ended the first run. This
applies to every slash command named in any Bob command or skill.
