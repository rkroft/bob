---
name: bob-table
description: Mirror Bob's intros.csv and people.csv into the user's own Airtable base — one-way, idempotent, never deleting. Use when the user asks to put their introductions in Airtable, run /bob-table, or wants a sortable table of their network outside the CSV.
---

# Mirroring Bob's table into Airtable

Airtable is a **mirror, not the store**. `intros.csv` and `people.csv` remain the
source of truth. Bob works completely without this; it is strictly additive.

Bob's Python never writes to Airtable and holds no Airtable credential. This runs
through the **user's own Airtable connector**, with the MCP tools already on their
account — the same reasoning as *no MCP server*: Bob reaches nothing the host
agent cannot already reach.

## Before you write anything

**Where the files are.** The user's folder is `$CLAUDE_PLUGIN_OPTION_DATA_DIR` —
resolve every path from it and never write to the working directory. `intros.csv`,
`people.csv`, `outcomes.md` and `corrections.md` all live there. Writing a
sentence about a named third party into whatever repo the user happened to have
open is not an acceptable default.

1. **Say the cost.** "This copies your network to Airtable. It leaves your
   laptop." Once, at the decision, not in a README.
2. **Check the connector is actually there.** If the Airtable tools are not
   available, say exactly that and stop. Do not report a skipped sync as a
   completed one.
3. **Read both CSVs** from the user's data folder. If `intros.csv` is missing,
   point at `/bob-scan`; do not create an empty base.

## The schema

Two tables, mirroring the two files field-for-field. No derived fields, no
schema you invent, nothing that is not a fact from the mail.

**Introductions** — one row per introduction, not per edge.

| Field | Type | Source |
|---|---|---|
| Thread ID | single line text | `thread_id` — **the key** |
| Date | date | `date` |
| Direction | single select: `inbound`, `outbound` | `direction` |
| Introducer | single line text | `introducer` |
| Introduced | long text | `introduced`, `;`-separated |
| Subject | single line text | `subject` |
| Thread link | URL | `thread_link` |
| Confidence | number (2 dp) | `confidence` |
| Outcome | long text | `outcomes.md`, keyed by thread — blank when not collected |

**People** — one row per person.

| Field | Type | Source |
|---|---|---|
| Address | single line text | `address` — **the key** |
| Name | single line text | `name` |
| Company | single line text | domain of the most recent address seen |
| Intros for you | number | `intros_for_you` |
| Intros you made | number | `intros_you_made` |
| Introduced you to | long text | `introduced_you_to` |
| Last contact | date | `last_contact` |

**Company is where they emailed from, not where they work.** Carry the date with
it and never write "works at". A 2019 address is a 2019 fact.

## Writing, idempotently

This is the whole risk of the feature. A mirror that doubles the base on every
run is worse than no mirror, and the user will not notice until the numbers are
wrong.

1. Find or create the base. Search for one named **Bob Network** before creating
   anything — a second base is the same failure as a duplicated row. **Never
   write to a base the user did not name or approve in this conversation.**
2. For each table, page `list_records_for_table` **to exhaustion** — keep
   requesting until no pagination cursor comes back — and build a map from the
   key field (Thread ID / Address) to the Airtable record id.

   **This is the step that breaks.** A six-year mailbox makes hundreds of people
   rows. Page one returns a fraction; every key beyond it reads as "not in the
   map" and gets classified as a create. Run two doubles the base, silently, and
   the user finds out when the numbers are wrong.

   Count what you read and say it in the report — *"read 412 existing rows,
   created 18, updated 394."* **If the listing cannot be completed for any
   reason, stop and write nothing.** A partial key map produces duplicates, and
   duplicates are unrecoverable here because this skill never deletes.
3. Split the CSV rows into **creates** (key not in the map) and **updates** (key
   present). Batch both — Airtable takes **at most 10 records per create or
   update call**, so chunk accordingly rather than sending one large request.
4. Never `delete_records_for_table`. It is the user's base and they may have
   typed into a row. A detection retracted in `corrections.md` gets its Outcome
   left alone and a note added — it does not get removed.

## Report honestly

Say what happened in facts: rows created, rows updated, and anything that
failed. If some writes succeeded and some did not, say which — a partial sync
reported as complete is the failure mode this product cannot afford.

Then name where it is: the base URL, so they can open it.

## What this does not do

**Sync is one-way, Bob → Airtable.** Typing an outcome in Airtable does not reach
`outcomes.md`. Say so once, when they ask, rather than letting them discover it
after typing into twenty rows. Two-way sync is deferred deliberately — a file and
a cloud table that disagree is a stale side failing silently, which is the same
reason meeting notes are not a source yet.
