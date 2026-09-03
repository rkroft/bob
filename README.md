# Bob

Bob reads your mail, works out who introduced you to whom, and helps you
thank them.

It is a [Claude Code](https://claude.com/claude-code) plugin. Bob has no
server, no account, and no database — your network lives in two CSV files in
a folder you choose. It reads your mail through the Gmail connector already
on your Claude account, so there is no credential to create and none for Bob
to hold.

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

`intros.csv`, `people.csv` and `network.html` are written to the folder you
name at setup, and stay there.

The reading is the part worth being precise about. Bob asks Claude to read
your mail, through the Gmail connector on your own Claude account. Your mail
passes through Anthropic's servers on the way to the model. That is access
you already granted Claude — not a new grant, and not a credential Bob
holds. There is no Bob server, no Bob account, and Bob's author holds
nothing of yours.

That connector can also send, label and trash mail. Bob does none of those:
it reads, and it writes drafts. That is a rule Bob keeps, not a lock on the
connector, and it is more honest to say so than to imply a limit that isn't
there.

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
needs no credential, no connector and no install — the offline way to read
the code and try Bob before granting it anything. The plugin's own path uses
the Gmail connector instead, and needs neither the export nor `pip`.

```
pip install -r requirements.txt   # only for the older --gmail path
python -m pytest                  # 415 tests
```

Every person in this repo's tests and examples is invented. That is a rule,
not an accident.

## Status

Early. The plugin front door works and the pipeline runs end to end; the
follow-up loop and the impact view are still being built. Issues and
observations welcome.

MIT licensed.
