# Bob

Bob reads your mail, works out who introduced you to whom, and helps you
thank them.

It is a [Claude Code](https://claude.com/claude-code) plugin. Bob has no
server, no account, and no database — your network lives in two CSV files in
a folder you choose. It reads your mail with a read-only Google credential you
create yourself and keep on your own machine. There is no shared application in
the middle, so Bob's author has no way to reach your mail.

**What it does, in full:** https://rkroft.github.io/bob/

```
/plugin marketplace add rkroft/bob
/plugin install bob@bob
```

Then ask Claude to **set up Bob**. It sets up your folder, reads your mail and
draws your network in one go, and asks only what it can't work out. The slash
commands below are there if you want them; you don't need them.

## What it does

**Finds the introductions in your mail.** Not contacts, not threads —
introductions. The three-body shape where someone put you and a stranger in
the same message and stepped back. `/bob-scan` reads your mailbox and writes
`intros.csv`.

**Shows you who your connectors are.** `/bob-graph` renders a local HTML page
of your network. Most people find that a handful of people account for most
of it, and that they had never counted.

**Helps you thank them.** `/bob-thanks` drafts a note to the people who
introduced you, with the specifics of what each intro became. Drafts only —
nothing sends itself.

**Optionally mirrors to Airtable.** `/bob-table` copies the CSVs into a base
you own, through your own Airtable connector. Strictly additive; the CSVs
stay the source of truth.

## What it can't do

- **Read LinkedIn.** No connections API has existed for third parties since
  2015, and scraping risks *your* account. LinkedIn is a CSV you export.
- **See intros that didn't happen over email.** A text message, a hallway,
  a Slack DM — Bob cannot see any of it. "Not found" means not found, never
  "didn't happen."
- **Send anything.** Bob drafts. You send.

## Where your data goes

`intros.csv`, `people.csv` and `network.html` are written to the folder you
name at setup, and stay there.

The reading is the part worth being precise about. Bob reads your mail with a
read-only Google credential that you create, on your own Google account, and
that never leaves your machine. Read-only is a scope, not a promise: sending
and deleting were never granted. There is no Bob server, no Bob account, and
no shared application in the middle.

Drafting is the exception, and it works differently. Drafts go through the
Claude connector already on your account, so they pass through Anthropic's
servers. That connector can also send, label and trash mail. Bob only ever
writes drafts — there it is a rule Bob keeps rather than a limit the connector
enforces, and it is more honest to say so than to imply otherwise.

`/bob-table` is the one command that moves anything off your machine, and it
says so before it runs.

The [FAQ](https://rkroft.github.io/bob/faq.html) covers all of this properly.

## Running it

Python 3.9+.

```
python tools/bob.py scan --mbox path/to/mail.mbox --principal you@example.com
python tools/bob.py graph --principal you@example.com
```

`--mbox` takes a [Google Takeout](https://takeout.google.com) export and
needs no credential and no install — the offline way to read the code and try
Bob before granting it anything. The `--gmail` path reads your live mailbox
instead, and needs the credential `tools/auth.py` walks you through plus the
packages below.

```
pip install -r requirements.txt   # for the --gmail path
python -m pytest                  # 542 tests
```

Every person in this repo's tests and examples is invented. That is a rule,
not an accident.

## Status

Early. The plugin front door works and the pipeline runs end to end; the
follow-up loop and the impact view are still being built. Issues and
observations welcome.

MIT licensed.
