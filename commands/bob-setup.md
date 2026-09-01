---
name: bob-setup
description: Set up Bob — your folder, your addresses, and which mail source you can read.
---

Set the user up so `/bob-scan` can run. Ask as little as possible and never ask
for something you can read.

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

> `/bob-scan` — I'll read your mail and draw what I find. Six years takes about
> twenty minutes, most of it waiting.
