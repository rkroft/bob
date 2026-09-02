# Bob

Bob reads your mail, works out who introduced you to whom, and helps you
thank them.

It is a [Claude Code](https://claude.com/claude-code) plugin. Everything runs
on your machine. Bob has no server, no account, and no database — your
network lives in two CSV files in a folder you choose.

**What it does, in full:** https://rkroft.github.io/bob/

```
/plugin marketplace add rkroft/bob
/plugin install bob@bob
/bob-setup
```

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

Nowhere, unless you send it there.

`intros.csv`, `people.csv` and `network.html` are written to the folder you
name at setup. Bob's Python holds no credential but the Gmail token you
create yourself, and talks to no service but Gmail. The `/bob-table` command
is the one exception and it says so before it runs.

The [FAQ](https://rkroft.github.io/bob/faq.html) covers this properly, including the Google consent
screen you will see and why it says what it says.

## Running it

Python 3.9+.

```
pip install -r requirements.txt
python tools/bob.py scan --mbox path/to/mail.mbox --principal you@example.com
python tools/bob.py graph --principal you@example.com
```

`--mbox` takes a [Google Takeout](https://takeout.google.com) export and
needs no credential at all, which is the honest way to try Bob before
granting it access to anything. `--gmail` uses the API instead, after
`/bob-setup` walks you through making a token.

```
python -m pytest        # 352 tests
```

Every person in this repo's tests and examples is invented. That is a rule,
not an accident.

## Status

Early. The plugin front door works and the pipeline runs end to end; the
follow-up loop and the impact view are still being built. Issues and
observations welcome.

MIT licensed.
