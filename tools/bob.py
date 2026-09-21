"""Bob's command line.

    bob scan  --mbox PATH --principal you@example.com
    bob scan  --gmail
    bob scan  --connector FILE... --principal you@example.com
    bob graph

`scan` reads mail and writes intros.csv. `graph` reads intros.csv and writes
network.html. They share the CSV and nothing else, so the graph can be redrawn
without touching the mailbox.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from graph_model import build_graph  # noqa: E402
from preflight import (  # noqa: E402
    DURABLE, as_dir, confirm_marker, preflight, stamp_marker)
from scan_coverage import Coverage, beside, read_coverage  # noqa: E402
from intro_store import read_intros, write_intros  # noqa: E402
from mail_source import best_name, normalize_addr  # noqa: E402
from last_contact import is_automated, last_direct_contact  # noqa: E402
from people_store import build_people, read_people, write_people  # noqa: E402
from mbox_source import MboxSource  # noqa: E402
from render import render  # noqa: E402
from intro_detect import (  # noqa: E402
    HARD_NEGATIVE_SENDERS, REQUEST_SUBJECT, SUBJECT_ARROW, SUBJECT_INTRO_ONLY,
    SUBJECT_KEYWORD, SUBJECT_PAIR_INTRO, detect, search_queries,
)
from scan import scan, scan_threads  # noqa: E402
from connector_source import ConnectorSource, missing_opener  # noqa: E402
import bob_config  # noqa: E402
from name_store import (  # noqa: E402
    Name, as_lookup, extract_quoted_names, merge, read_names, worklist,
    write_names)

DEFAULT_OUT = ROOT / "reports" / "intros.csv"
DEFAULT_HTML = ROOT / "reports" / "network.html"
DEFAULT_PEOPLE = ROOT / "reports" / "people.csv"
LEADERBOARD = 10


def gmail_link(thread_id: str) -> str:
    return f"https://mail.google.com/mail/u/0/#all/{thread_id}"


def _addresses(raw: str | None) -> list[str]:
    """`--principal` as a list. The plugin's own config field describes it as
    comma-separated, so the CLI has to accept that shape even though Bob reads
    one mailbox at a time."""
    return [a.strip().lower() for a in (raw or "").split(",") if a.strip()]


def build_source(args):
    """Returns (source, link_for). Imports GmailSource lazily so the mbox path
    never needs Google credentials on the machine.

    Bob reads ONE mailbox per run. Where a second address is supplied it is
    reported and ignored rather than silently dropped: the plugin advertises
    `principal` as comma-separated, so a user who lists two has every reason
    to believe both were read. Saying so is the difference between a limit
    and a wrong answer.
    """
    given = _addresses(args.principal)

    if args.mbox:
        if not given:
            raise SystemExit("--principal is required with --mbox")
        if len(given) > 1:
            print(f"reading as {given[0]} — Bob reads one mailbox at a time, "
                  f"so {', '.join(given[1:])} "
                  f"{'is' if len(given) == 2 else 'are'} not read by this run.")
        return MboxSource(args.mbox, principal=given[0]), None

    if args.gmail:
        from gmail_source import GmailSource
        source = GmailSource()
        # The token decides whose mailbox this is; --principal cannot override
        # it. Previously it was accepted here and discarded without a word.
        whose = source.principal()
        others = [a for a in given if a != whose]
        if others:
            print(f"reading {whose} — the mailbox this token belongs to. "
                  f"{', '.join(others)} "
                  f"{'is' if len(others) == 1 else 'are'} not read by this "
                  f"run; a second mailbox needs its own token "
                  f"(BOB_GOOGLE_TOKEN) and its own output files.")
        return source, gmail_link

    if args.connector:
        # The file says nothing about whose mailbox it is -- the agent that
        # wrote it knew, and that knowledge did not survive to disk. So
        # --principal is required here for the same reason it is on --mbox,
        # and for the opposite reason it is refused on --gmail, where the
        # token is the authority.
        if not given:
            raise SystemExit("--principal is required with --connector")
        if len(given) > 1:
            print(f"reading as {given[0]} — Bob reads one mailbox at a time, "
                  f"so {', '.join(given[1:])} "
                  f"{'is' if len(given) == 2 else 'are'} not read by this run.")
        return ConnectorSource(given[0], list(args.connector)), gmail_link

    raise SystemExit("need --mbox PATH, --gmail, or --connector FILE...")


def _announce(n: int) -> None:
    depth = "whole mailbox" if True else ""
    print(f"reading {n:,} candidate threads — roughly "
          f"{max(1, round(n / 170))} min", flush=True)


def cmd_names_extract(args) -> int:
    """Pull names out of thread bodies the agent fetched, into names.csv.

    Deterministic and local — no judgment is spent here. The names come from
    the attribution a mail client writes when quoting a reply, which pairs a
    real display name with a real address (`name_store.extract_quoted_names`).
    That is the best source available once the connector has stripped the
    headers, and it is a parse rather than an inference.

    Input is the same JSONL shape the scan reads, plus `plaintextBody` on each
    message. Threads with no body contribute nothing and are counted, not
    skipped silently: a fetch that returned metadata only would otherwise look
    exactly like a mailbox with no names in it.
    """
    from connector_source import read_jsonl
    found: list = []
    threads = bodies = 0
    for obj in read_jsonl(Path(args.bodies)):
        threads += 1
        tid = obj.get("id", "")
        for m in (obj.get("messages") or []):
            body = m.get("plaintextBody") or ""
            if not body:
                continue
            bodies += 1
            for n in extract_quoted_names(body):
                found.append(Name(n.address, n.name, n.evidence, tid))

    path = Path(args.names)
    known = read_names(path)
    after = merge(known, found)
    write_names(after, path)
    print(f"{threads} threads · {bodies} messages with a body · "
          f"{len(found)} attributions seen")
    print(f"{len(after) - len(known)} new names · {len(after)} known in total")
    if threads and not bodies:
        print("no bodies present — was this fetched with messageFormat PLAIN_TEXT?")
    print(f"wrote {path}")
    return 0


def cmd_names_add(args) -> int:
    """Merge extracted names into names.csv. JSON on stdin or in a file.

    A CLI rather than the agent editing the CSV by hand, so every write goes
    through `merge` and inherits its rules — precedence, plausibility, and
    first-writer-holds. An agent hand-editing the file would silently bypass
    all three, and the failure would look like a name that changes between
    runs for no visible reason.

    Reports what it rejected. Silence about a dropped name would leave the
    agent believing a lookup succeeded when nothing was stored.
    """
    import json
    raw = (Path(args.json).read_text(encoding="utf-8")
           if args.json else sys.stdin.read())
    try:
        items = json.loads(raw)
    except json.JSONDecodeError as e:
        raise SystemExit(f"could not read the name list as JSON: {e}")
    if isinstance(items, dict):
        items = [items]

    path = Path(args.names)
    known = read_names(path)
    incoming = [Name(address=i.get("address", ""), name=i.get("name", ""),
                     evidence=(i.get("evidence") or "").strip(),
                     thread_id=i.get("thread_id", "")) for i in items]
    after = merge(known, incoming)
    write_names(after, path)

    added = len(after) - len(known)
    changed = sum(1 for a, n in after.items()
                  if a in known and known[a].name != n.name)
    rejected = [i.name or i.address for i in incoming
                if i.address and normalize_addr(i.address) not in after]
    # Rejected is its own number, never folded into "no change". A caller
    # told 2 unchanged when 2 were thrown away would believe the lookup
    # landed -- the same silent-success failure this file exists to avoid.
    kept = len(incoming) - len(rejected)
    print(f"{len(incoming)} offered · {added} new · {changed} upgraded · "
          f"{max(0, kept - added - changed)} already known · "
          f"{len(rejected)} rejected")
    if rejected:
        print(f"rejected: {', '.join(sorted(set(rejected))[:5])}"
              f"{' …' if len(set(rejected)) > 5 else ''}")
    print(f"wrote {path} ({len(after)} names)")
    return 0


def cmd_names_todo(args) -> int:
    """Print who still needs a name, and where to look for it.

    The connector strips display names (HAP-318), so on that path every person
    is labelled by address until this pass runs. Bob's Python cannot fetch the
    bodies itself — the connector belongs to the agent — so this emits the
    worklist and the agent does the reading. Deliberately narrow: confirmed
    introductions only, and only threads the person is actually on.
    """
    import json
    rows = read_intros(Path(args.intros))
    known = read_names(Path(args.names)) if args.names else {}
    addresses = {r.introducer for r in rows} | {p for r in rows for p in r.introduced}
    addresses.discard("")
    todo = worklist(addresses, known, rows, exclude=_addresses(args.principal))
    if args.limit:
        todo = todo[:args.limit]
    print(json.dumps(
        {"needed": len(todo),
         "known": len(known),
         "total_people": len(addresses),
         "work": [{"address": a, "threads": t[:3]} for a, t in todo]},
        indent=2))
    return 0


def cmd_scan(args) -> int:
    # The backstop behind commands/bob-scan.md's step 0. The prose gate is
    # unreachable in a compacted context, in a resumed session, or when someone
    # pastes the "## Run it" block, and until this existed there was nothing
    # behind it -- the entire enforcement was the model reading instructions.
    if getattr(args, "data_dir", None) and not args.allow_ephemeral:
        gate = preflight(args.data_dir, plugin_root=None)
        if gate.durability != DURABLE:
            print(gate.report())
            return gate.exit_code
        # The proof is about one folder. Nothing forces the output into it, and
        # a confirmed data_dir vouching for CSVs written elsewhere is the same
        # false assurance in a new shape.
        confirmed = as_dir(args.data_dir).resolve()
        for label, path in (("--out", args.out), ("--people", args.people)):
            try:
                as_dir(path).resolve().relative_to(confirmed)
            except ValueError:
                print(f"note: {label} is outside {confirmed}, the folder you "
                      f"confirmed persists. Bob cannot vouch for where that "
                      f"lands.")

    try:
        source, link_for = build_source(args)
    except (OSError, UnicodeDecodeError) as exc:
        # A bare traceback here reads as a crash in Bob rather than a file the
        # user can go and look at. Gated on the source: MboxSource raises
        # FileNotFoundError too, and the connector wording sent an mbox user to
        # a retrieval step they never ran.
        if args.connector:
            print(f"Bob could not read the scan file: "
                  f"{getattr(exc, 'filename', None) or exc}\n"
                  f"Nothing was read. This file is written by the retrieval "
                  f"step in /bob-scan; if that step did not run, there is "
                  f"nothing here to analyse.")
        else:
            print(f"Bob could not read the mailbox: {exc}\nNothing was read.")
        return 1

    _remember_principal(args, source.principal())

    seen_names: dict = {}
    capped: list = []
    contacted: set = set()
    automated: set = set()
    coverage = Coverage()
    if isinstance(source, ConnectorSource):
        # Retrieval already happened, in the agent, so there is no net to run
        # and no cap to hit. Coverage arrives as a manifest instead -- see
        # scan_coverage: this source cannot know a denominator.
        # The net is known code, so it is a legitimate denominator -- the
        # mbox path already reports "N of 15 searches". Only the count of what
        # EXISTS is unavailable on this path.
        coverage = read_coverage(
            args.coverage or beside(args.connector)).with_skipped(
                source.skipped_lines).with_threads_in_file(
                    source.threads_read).with_expected(list(search_queries()))
        if source.blocked:
            # `0 introductions` and `I could not look` must not be the same
            # value. An empty or unparseable scan file means retrieval wrote
            # nothing; reporting it as an empty mailbox would present a broken
            # scan as a finished one, and the user would believe it.
            print("Bob read nothing, so it has no result — this is not "
                  "'no introductions found'.\n"
                  f"The scan file held no usable threads"
                  + (f" ({source.skipped_lines} unreadable "
                     f"{'line' if source.skipped_lines == 1 else 'lines'})"
                     if source.skipped_lines else " and was empty")
                  + ".\nThe retrieval step in /bob-scan writes this file. Run "
                    "it again before reading anything into the silence.")
            print()
            print(coverage.report())
            return 1
        threads = source.all_threads()
        # No time estimate: the reading already happened. "roughly N min" here
        # would be a forecast of finished work.
        print(f"adjudicating {len(threads):,} "
              f"{'thread' if len(threads) == 1 else 'threads'} the retrieval "
              f"step wrote", flush=True)
        rows = scan_threads(threads, source.principal(), link_for=link_for,
                            names_out=seen_names, contacted_out=contacted,
                            automated_out=automated)
        # Every cut-off intro thread, whatever its markers say: a row built
        # without its opener may credit a later replier. Counted, never
        # silently kept.
        pending, gave_up, absent = _openers(source)
        unfetched, unrecoverable = len(pending), len(gave_up) + len(absent)
    else:
        unfetched = unrecoverable = 0
        rows = scan(source, link_for=link_for, names_out=seen_names,
                    limit_per_query=args.limit_net, capped_out=capped,
                    contacted_out=contacted, automated_out=automated,
                    progress=_announce)
    names = {a: best_name(v) for a, v in seen_names.items()}
    # A header name is the person's own spelling, so it outranks anything the
    # name pass recovered from prose. Overlay first, then let headers win.
    if args.names:
        found = as_lookup(read_names(Path(args.names)))
        names = {**found, **{a: n for a, n in names.items() if n}}

    out = as_dir(args.out)
    write_intros(rows, out)

    # The roster is derived, so it is rebuilt from scratch every scan. So is
    # intros.csv: write_intros replaces the file, and a row added by hand is
    # gone after the next scan.
    people_path = as_dir(args.people)
    people = build_people(rows, source.principal(), names,
                          contacted=contacted, automated=automated)
    write_people(people, people_path)

    inbound = sum(1 for r in rows if r.direction == "inbound")
    print(f"{len(rows)} introductions  ({inbound} inbound, "
          f"{len(rows) - inbound} you made)")
    # Count against the ROSTER, not against every address the scan happened to
    # see. `names` covers every participant of every thread the net returned --
    # thousands of people who are not in anyone's introductions. Reporting that
    # number under "those people" overstates it by 3x.
    named = sum(1 for pp in people if names.get(pp.address))
    print(f"{len(people)} people, {named} with a name from the headers "
          f"({len(people) - named} fall back to their email address)")
    print(f"wrote {out}")
    services = sum(1 for pp in people if pp.is_service)
    if services:
        print(f"{services} of them look like services rather than people "
              f"(role address, machine-generated mail, never written to)")
    print(f"wrote {people_path}")
    if capped:
        # Never let a bounded search pass for an exhaustive one.
        print(f"\n⚠  {len(capped)} of {len(list(search_queries()))} searches hit "
              f"the {args.limit_net}-result limit, so older mail was not read:")
        for q in capped:
            print(f"     {q}")
        print("   Re-run with a higher --limit-net to go further back.")
    # Plain words, no command: the user sees this line and cannot run the fix.
    # bob-scan.md tells the agent what to do when it appears.
    if unfetched:
        print(f"\n⚠  {_n(unfetched, 'long thread', 'long threads')} still "
              f"need their first email read. Until then, the introducer "
              f"shown on those may be someone who replied later.")
    if unrecoverable:
        print(f"\n⚠  {_n(unrecoverable, 'long thread', 'long threads')} "
              f"could not be read back to the first email (it failed, or the "
              f"email is gone). The introducer shown on those may be someone "
              f"who replied later.")
    if isinstance(source, ConnectorSource):
        # The connector's answer to `capped`. Same rule, different mechanism:
        # never let a bounded search pass for an exhaustive one.
        print()
        print(coverage.report())
        if not coverage.complete and rows:
            # Said here rather than in the report, because it qualifies a
            # result -- and only if there is one to qualify.
            print("   So treat these as some of your introductions rather "
                  "than all of them.")
    # Last, and never fatal. The scan has succeeded and both CSVs are on disk;
    # a traceback here reads as a failed scan and invites re-reading several
    # hundred threads. It also used to sit ABOVE the `capped` block, so a stamp
    # failure swallowed the "older mail was not read" disclosure.
    if getattr(args, "data_dir", None):
        try:
            stamp_marker(args.data_dir)
        except (OSError, ValueError) as exc:
            print(f"\nnote: the scan finished, but Bob could not record this "
                  f"run in {as_dir(args.data_dir)}: {exc}")
    return 0


def cmd_queries(args) -> int:
    """The retrieval net, one query per line.

    The connector path needs this: the agent runs retrieval there, and without
    the net in front of it it improvises a handful of searches — after which
    every run reports complete coverage, measured against whatever it happened
    to think of. See scan_coverage.Coverage.missing.
    """
    for q in search_queries():
        print(q)
    return 0


def cmd_preflight(args) -> int:
    """What Bob can prove before it reads anything.

    Exit 1 = something is broken. Exit 2 = nothing is broken and durability is
    unproven. Two codes rather than one so the command markdown branches on the
    status rather than on its own reading of the prose.
    """
    result = preflight(args.data_dir, plugin_root=args.plugin_root)
    print(result.report())
    return result.exit_code


def cmd_confirm_folder(args) -> int:
    """Records the user's answer to the durability question. Only ever called
    after they have actually been asked — see commands/bob-scan.md."""
    try:
        confirm_marker(args.data_dir)
    except (OSError, ValueError) as exc:
        print(f"Bob did not record that: {exc}")
        return 1
    print(f"Noted — {as_dir(args.data_dir)} is yours and persists. "
          f"Bob won't ask again.")
    return 0


def _n(count: int, singular: str, plural: str = None) -> str:
    """"1 intro", "4 intros" — the summary is the first thing a user reads."""
    return f"{count} {singular if count == 1 else (plural or singular + 's')}"


def summary(graph, principal: str) -> str:
    """What Rachel reads. Spec §7.1: scope before numbers, the three
    populations, and concentration as the reveal rather than a count."""
    s = graph.stats
    if not s or not s.intros:
        return "No introductions found."

    lines = [
        f"{_n(s.intros, 'introduction')} since {s.first_date}. "
        f"{_n(s.people, 'person', 'people')}.",
        "",
        f"   {_n(s.introducers, 'person', 'people')} "
        f"{'has' if s.introducers == 1 else 'have'} introduced you to someone",
        f"   {_n(s.introduced_to, 'person', 'people')} you were introduced to",
        f"   {_n(s.made_by_you, 'intro')} you made for someone else",
    ]
    # Dropped when it would deflate rather than land (spec §7.1).
    if s.last_12mo >= 3:
        if s.last_12mo == s.intros:
            # "N of those N" reads like a template leak, not something a
            # person wrote. Special-case the equality instead.
            lines += ["", f"   All {s.intros} happened in the last 12 months."]
        else:
            lines += ["", f"   {s.last_12mo} of those {s.intros} happened "
                          f"in the last 12 months."]

    if graph.super_connectors:
        share = sum(n for _, n in graph.super_connectors)
        # Denominator is INBOUND intros only. Dividing by every intro in the
        # file would fold in the ones the user made themselves and understate
        # the concentration.
        total = (s.intros - s.made_by_you) or 1
        lines += ["", f"   {len(graph.super_connectors)} "
                      f"{'introducer accounts' if len(graph.super_connectors) == 1 else 'introducers account'}"
                      f" for {round(100 * share / total)}% of everyone",
                  "   you've been introduced to.", ""]
        label = {n.id: n.label for n in graph.nodes}
        for addr, n in graph.top_connectors[:LEADERBOARD]:
            lines.append(f"   {label.get(addr, addr.partition('@')[0]):<24} "
                         f"{_n(n, 'intro')}")
        # Named set is capped (graph_model.SUPER_CONNECTOR_CAP); when there
        # are more introducers than the list names, say so instead of letting
        # the list read as the whole population.
        if s.introducers > min(LEADERBOARD, len(graph.top_connectors)):
            # Say how many are unlisted, not how many intros they made. The
            # old wording claimed "one person, or two" about people whose
            # counts were never checked — a fabricated statement in the
            # headline output, which the no-inference-as-fact rule forbids.
            rest = s.introducers - min(LEADERBOARD, len(graph.top_connectors))
            lines.append(f"   and {_n(rest, 'other person', 'other people')} "
                         f"who introduced you to someone")
    return "\n".join(lines)


def cmd_roster(args) -> int:
    """Fill in when the principal last actually spoke to each person.

    A separate command, and a separate mailbox pass, because it is the one
    part of the roster that has to look past intro threads (Plugin MVP §4.4).
    It is additive: it updates last_contact on the existing people.csv and
    touches nothing else, so a roster pass can never lose the scan's work.
    """
    people_path = as_dir(args.people)
    people = read_people(people_path)
    if not people:
        print(f"No roster at {people_path}. Run `bob scan` first.")
        return 1

    try:
        source, _ = build_source(args)
    except FileNotFoundError as exc:
        print(f"Could not read {exc.filename}. Nothing was changed.")
        return 1
    connector = bool(getattr(args, "connector", None))
    if connector and source.blocked:
        # An empty file is a retrieval that wrote nothing. Reporting it as
        # "nobody has been spoken to" would present a failure as an answer.
        print("Bob could not read anything from the connector file, so "
              "nothing was changed. Run the searches again.")
        return 1
    # flush: stdout is block-buffered when it is not a terminal, so a plugin
    # capturing this saw nothing at all until the process ended -- the exact
    # silence this whole change exists to remove.
    if connector:
        print(f"Reading the connector file for {len(people)} people.",
              flush=True)
    else:
        print(f"Reading headers for {len(people)} people. No message bodies "
              f"are read and none are kept.", flush=True)
        print("Working out what to read.", flush=True)

    # The roster size is not the work. This walks the mailbox, and saying
    # "517 people" while reading twenty thousand threads is how a two-hour run
    # looked like a hang -- the number on screen implied it was nearly done.
    def _announce(n: int, unit: str) -> None:
        if not n or connector:
            return
        # Two paths, two rates, both measured rather than guessed. Asking
        # about a person averaged 84/min against a real Gmail account; 80 is
        # used so the estimate errs long. The first version of this line said
        # 250 and promised "roughly 2 min" for a six-minute job -- the same
        # kind of small lie the rest of this command was fixed for.
        mins = round(n / (80 if unit == "people" else 170))
        when = f" — roughly {mins} min" if mins >= 2 else ""
        what = (f"Asking about each of the {n:,} people"
                if unit == "people" else f"That means reading {n:,} threads")
        print(f"{what}{when}. Progress below; partial results are saved as it "
              f"goes.", flush=True)

    # Who this pass actually looked at. Only they can be reset: blanking a
    # date the pass never checked would be a loss dressed up as a correction.
    looked = (source.asked - source.could_not_look if connector
              else {p.address for p in people})

    def _merged(seen_so_far: dict) -> list:
        out = []
        for p in people:
            new = seen_so_far[p.address].date if p.address in seen_so_far else ""
            if args.reset_dates and p.address in looked:
                out.append(replace(p, last_contact=new))
            # Never backwards. A pass that saw less (the connector reads a
            # person's newest thread or three) must not erase a later
            # conversation an earlier pass found. ISO days compare as
            # strings. --reset-dates is the way to correct a date set under
            # older, looser rules.
            elif new > p.last_contact:
                out.append(replace(p, last_contact=new))
            else:
                out.append(p)
        return out

    def _save(seen_so_far: dict) -> None:
        write_people(_merged(seen_so_far), people_path)

    def _tick(done: int, total: int, live: dict) -> None:
        if connector:
            return            # one file, read at once: nothing to count
        pct = round(100 * done / total) if total else 100
        print(f"  {done:,}/{total:,} ({pct}%) · "
              f"{len(live)} of {len(people)} people placed", flush=True)
        # Checkpoint. Nothing was written until the very end, so a run killed
        # at 95% left the roster exactly as it started -- two hours for nothing.
        _save(live)

    seen = last_direct_contact(source, source.principal(),
                               addresses={p.address for p in people},
                               query=args.query, limit=args.limit_net or 100000,
                               on_start=_announce, on_progress=_tick)

    updated = _merged(seen)
    write_people(updated, people_path)

    found = sum(1 for p in updated if p.last_contact)
    print(f"\n{found} of {len(updated)} have a direct exchange on record.")
    blank = {p.address for p in updated if not p.last_contact}
    if connector:
        # Three different blanks, and only the first is a finding. Lumping
        # them together reported people Bob never looked at as "not found".
        waiting = set(_roster_todo(updated, source.asked,
                                   source.could_not_look, source.failures,
                                   _addresses(args.principal)))
        failed = blank & source.could_not_look
        nothing = blank & (source.asked - source.could_not_look)
        if nothing:
            print(f"{len(nothing)} have nothing direct in their newest threads "
                  f"— not found, not never.")
        if failed:
            print(f"{len(failed)} could not be looked up — the search failed.")
        pending = (waiting - source.could_not_look) & blank
        if pending:
            print(f"{len(pending)} not asked about yet — `bob roster-todo` "
                  f"gives the next batch.")
    elif blank:
        # Never let silence read as "you have never spoken". Bob sees one
        # channel.
        print(f"{len(blank)} have none that this mailbox can see — which "
              f"means not found, not never.")
    print(f"wrote {people_path}")
    return 0


ROSTER_BATCH = 50


# A person whose lookup failed this many times is not asked again: one address
# that always errors would otherwise keep the batch loop going forever.
ROSTER_MAX_FAILURES = 2


def _roster_todo(people, asked, blocked, failures, principal) -> list:
    """Roster addresses still to ask about, in roster order.

    Never asked about: services, machine addresses the pass ignores anyway,
    the principal, anyone already looked up, and anyone who has failed
    `ROSTER_MAX_FAILURES` times. A person whose lookup failed fewer times is
    asked again.
    """
    skip = {a.lower() for a in principal}
    done = set(asked) - set(blocked)
    return [p.address for p in people
            if p.address and not p.is_service and not is_automated(p.address)
            and p.address not in skip and p.address not in done
            and failures.get(p.address, 0) < ROSTER_MAX_FAILURES]


def cmd_roster_todo(args) -> int:
    """The next batch for the agent to search on the connector (HAP-356).

    Bob's Python cannot call the connector, so the roster pass splits like the
    scan: this names who to ask about, the agent searches and writes the
    threads plus one `asked` marker per person, and `roster --connector`
    reads the file. People already marked done are left out, so a stopped
    batch resumes where it stopped.
    """
    import json
    people = read_people(as_dir(args.people))
    if not people:
        print(f"No roster at {as_dir(args.people)}. Run `bob scan` first.")
        return 1
    principal = _addresses(args.principal)
    existing = [f for f in (args.connector or []) if Path(f).exists()]
    asked, blocked, failures = set(), set(), {}
    if existing:
        src = ConnectorSource((principal or [""])[0], existing)
        asked, blocked, failures = src.asked, src.could_not_look, src.failures
    todo = _roster_todo(people, asked, blocked, failures, principal)
    gave_up = sorted(a for a in blocked
                     if failures.get(a, 0) >= ROSTER_MAX_FAILURES)
    print(json.dumps({
        "batch": todo[:args.batch],
        "remaining": len(todo),
        "done": len(asked - blocked),
        "gave_up": gave_up,
        "query": "from:{address} OR to:{address}",
    }, indent=2))
    return 0


#: Threads per opener-pass batch. Each is one `get_thread`.
OPENER_BATCH = 25
#: Failed fetches before a thread is given up on, as with the roster.
OPENER_MAX_FAILURES = 2

# Reply prefixes, including an out-of-office's, stripped before a subject is
# read -- "Automatic reply: Intro: Alice <> Ben" is still that intro's subject.
_REPLY_PREFIX = re.compile(
    r"^\s*(?:(?:re|fwd?|aw|automatic reply|auto(?:-| )?reply|out of office)"
    r"\s*:\s*)+", re.I)
_INTRO_SUBJECT = (SUBJECT_ARROW, SUBJECT_KEYWORD, SUBJECT_INTRO_ONLY,
                  SUBJECT_PAIR_INTRO, REQUEST_SUBJECT)


def _worth_opening(t) -> bool:
    """Does a cut-off thread look enough like an introduction to fetch?

    Judged across every visible message, not by running `detect`: detect reads
    the oldest *visible* message, which on a cut-off thread is a reply -- an
    out-of-office or a reply-all that grew past six people would disqualify an
    intro that is really there. Deliberately narrow: a separator word ("drinks
    and dinner") or three people on a reply is not enough, because each fetch
    costs the user tokens and a heavy mailbox has hundreds of long threads.
    """
    if not any(m.from_addr and not is_automated(m.from_addr)
               and not HARD_NEGATIVE_SENDERS.search(m.from_addr)
               for m in t.messages):
        return False
    for m in t.messages:
        subject = _REPLY_PREFIX.sub("", m.subject or "")
        if any(rx.search(subject) for rx in _INTRO_SUBJECT):
            return True
    # A handoff seen on a cut-off thread may be an artefact of the cut: the
    # people on the missing messages all look newly added. Fetch to be sure.
    # And anything already scoring as an intro: on a cut-off thread the
    # snippet of a reply can carry the intro wording, crediting the replier.
    d = detect(t)
    return (bool({"structural_dropout", "late_handoff"} & set(d.signals))
            or (d.is_intro and d.kind != "request"))


def _openers(source: ConnectorSource) -> tuple[list, list, list]:
    """Cut-off intro threads, split three ways: (to fetch, given up on,
    fetched but the first email still absent).

    Only the first list drives the loop. All three are disclosed by `scan`:
    whatever the markers say, a row built without its opener may credit a
    later replier. A thread marked fetched is never listed again -- a deleted
    first email stays deleted.
    """
    todo, gave_up, absent = [], [], []
    for t in source.all_threads():
        if not missing_opener(t) or not _worth_opening(t):
            continue
        st = source.fetches.get(t.id)
        if st and st["ok"]:
            absent.append(t)
        elif st and st["failures"] >= OPENER_MAX_FAILURES:
            gave_up.append(t)
        else:
            todo.append(t)
    newest = lambda t: max((m.date.timestamp() for m in t.messages if m.date),
                           default=0)
    todo.sort(key=newest, reverse=True)
    return ([t.id for t in todo], sorted(t.id for t in gave_up),
            sorted(t.id for t in absent))


def cmd_scan_todo(args) -> int:
    """Threads the agent should fetch whole before `scan` adjudicates.

    `search_threads` shows only the newest five messages, so on a long
    introduction thread the email that made the introduction is cut off and
    the introducer comes out as a later replier. This names those threads; the
    agent runs `get_thread` on each, appends the result and a `fetched`
    marker, and asks again until the batch is empty.
    """
    import json
    wanted = args.connector or (
        [Path(args.data_dir) / "threads.jsonl"] if args.data_dir else [])
    files = [f for f in wanted if Path(f).exists()]
    if not files:
        print("No scan file yet. The retrieval step in /bob-scan writes it.")
        return 1
    principal = _addresses(args.principal)
    src = ConnectorSource((principal or [""])[0], files)
    todo, gave_up, _ = _openers(src)
    print(json.dumps({
        "batch": todo[:args.batch],
        "remaining": len(todo),
        "done": sum(1 for st in src.fetches.values() if st["ok"]),
        "gave_up": gave_up,
        "format": "MINIMAL",
    }, indent=2))
    return 0


def cmd_setup(args) -> int:
    """The only command that writes the address. Exit 2 = Bob still needs it,
    so the caller asks rather than reading the prose."""
    folder = args.data_dir
    if args.gmail:
        # The token is the authority on whose mailbox this is (see
        # build_source), so the address comes from it, never from a guess.
        try:
            from gmail_source import GmailSource
            token_address = GmailSource().principal()
        except Exception as exc:  # no token, no packages, no network
            print(f"Bob could not read the address from your Gmail token: "
                  f"{exc}")
            return 1
        try:
            before = bob_config.read_config(folder).get("principal")
        except (OSError, ValueError):
            before = None
        if before and before.lower() != token_address.lower():
            print(f"note: your Gmail token reads {token_address}, not "
                  f"{before} — saving {token_address}.")
        args.principal = token_address
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"Bob could not create {folder}: {exc}")
        return 1
    if not args.principal:
        print(f"folder: {folder}\naddress: not set — Bob needs the email "
              f"address whose mail it reads.")
        return 2
    if not bob_config.looks_like_address(args.principal):
        print(f"{args.principal!r} isn't an email address. Bob needs the "
              f"address whose mail it reads.")
        return 1
    try:
        bob_config.save_principal(folder, args.principal)
    except (OSError, ValueError) as exc:
        print(f"Bob could not save your address in {folder}: {exc}")
        return 1
    print(f"folder: {folder}\naddress: {args.principal}")
    return 0


def _remember_principal(args, used: str) -> None:
    """Keep bob.json on the mailbox actually read. A Gmail token decides whose
    mail that is; a different saved address would make the graph draw a
    different "you" from the one the scan found."""
    folder = getattr(args, "data_dir", None)
    if folder is None or not used:
        return
    try:
        saved = bob_config.read_config(folder).get("principal")
    except (OSError, ValueError):
        return
    # Nothing saved yet means the address came from a flag or the plugin
    # setting; saving it here would freeze that setting against later edits.
    if not isinstance(saved, str) or not saved.strip() \
            or saved.strip().lower() == used.lower():
        return
    try:
        bob_config.save_principal(folder, used)
    except (OSError, ValueError):
        return
    print(f"note: this scan read {used}, not {saved} — saved {used} "
          f"as your address.")


def _resolve(args) -> None:
    """Fill in what plugin settings would have, from the folder.

    `--data-dir ""` is a failed substitution, not a request for the working
    directory, so it falls back to the plugin setting and otherwise stops."""
    folder = None
    if hasattr(args, "data_dir"):
        given = args.data_dir
        folder = bob_config.data_dir(given)
        if folder is None and given is not None:
            raise SystemExit("No Bob folder given — the folder setting came "
                             "through empty. Pass --data-dir with the real "
                             "folder.")
        args.data_dir = folder
    if hasattr(args, "principal"):
        args.principal = bob_config.principal(args.principal, folder)
    if hasattr(args, "plugin_root") and args.plugin_root is not None \
            and not str(args.plugin_root).strip():
        # Same failed substitution as a blank folder: not the working dir.
        args.plugin_root = None
    graph = args.fn is cmd_graph
    files = {"intros": ("intros.csv", DEFAULT_OUT),
             "people": ("people.csv", DEFAULT_PEOPLE),
             "out": ("network.html", DEFAULT_HTML) if graph
             else ("intros.csv", DEFAULT_OUT)}
    for name, (file, default) in files.items():
        if hasattr(args, name) and getattr(args, name) is None:
            setattr(args, name, folder / file if folder else default)
    if getattr(args, "needs_principal", False) and not args.principal:
        raise SystemExit("Bob doesn't know your email address yet. Run "
                         "`bob setup --data-dir <folder> --principal <you>`, "
                         "or pass --principal.")


def cmd_graph(args) -> int:
    rows = read_intros(Path(args.intros))
    if not rows:
        print(f"No rows in {args.intros}. Run `bob scan` first.")
        return 1
    # Names come from the roster the scan wrote. Absent it, labels fall back to
    # the local part and everything still works — just less legibly.
    roster = read_people(Path(args.people))
    names = {p.address: p.name for p in roster}
    graph = build_graph(rows, args.principal, today=date.today(), names=names)
    out = Path(args.out)
    render(graph, out, principal=args.principal, people=roster,
           intros=rows)
    print(summary(graph, args.principal))
    print(f"\nYour graph: {out}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="bob")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", help="read mail, write intros.csv")
    s.add_argument("--mbox", type=Path, help=".mbox file or a directory of them")
    s.add_argument("--gmail", action="store_true", help="use the Gmail source")
    s.add_argument("--connector", type=Path, nargs="+", metavar="FILE",
                   help="JSONL written by the agent from the Gmail connector")
    s.add_argument("--names", type=Path,
                   help="names.csv from a name pass (see `bob names-todo`)")
    s.add_argument("--coverage", type=Path, default=None,
                   help="coverage.json written by the retrieval step: which "
                        "queries ran, pages each, which errored. Defaults to "
                        "coverage.json beside the --connector file. Without "
                        "it the scan reports coverage as unknown, never as "
                        "complete")
    s.add_argument("--principal", help="the mailbox owner's address")
    s.add_argument("--out", type=Path, default=None)
    s.add_argument("--people", type=Path, default=None)
    s.add_argument("--limit-net", type=int, default=None,
                   help="cap threads per search for a quick partial pass; "
                        "omitted means read the whole mailbox")
    s.add_argument("--data-dir",
                   help="the user's Bob folder. Given, the scan refuses to "
                        "read mail until the folder is confirmed to persist, "
                        "and records the run once it has")
    s.add_argument("--allow-ephemeral", action="store_true",
                   help="scan even though the folder may be wiped when the "
                        "session ends. For the mbox path and for anyone who "
                        "means it; explicit so it cannot happen by accident")
    s.set_defaults(fn=cmd_scan)

    q = sub.add_parser("queries",
                       help="the retrieval net, one query per line — what the "
                            "connector path must run to claim full coverage")
    q.set_defaults(fn=cmd_queries)

    p = sub.add_parser("preflight",
                       help="what Bob can prove before it reads any mail")
    p.add_argument("--data-dir", required=True)
    p.add_argument("--plugin-root", default=None,
                   help="where the plugin is installed, for the version check")
    p.set_defaults(fn=cmd_preflight)

    cf = sub.add_parser("confirm-folder",
                        help="record that the user confirmed this folder "
                             "persists — only after actually asking them")
    cf.add_argument("--data-dir", required=True)
    cf.set_defaults(fn=cmd_confirm_folder)

    r = sub.add_parser("roster", help="fill in when you last spoke to each person")
    r.add_argument("--mbox", type=Path, help=".mbox file or a directory of them")
    r.add_argument("--gmail", action="store_true", help="use the Gmail source")
    r.add_argument("--connector", type=Path, nargs="+", metavar="FILE",
                   help="JSONL written by the agent from the Gmail connector: "
                        "threads plus one {\"asked\": address} line per person")
    r.add_argument("--principal", help="the mailbox owner's address")
    r.add_argument("--people", type=Path, default=None)
    r.add_argument("--data-dir", help="the user's Bob folder; people.csv and "
                   "the saved address are read from it")
    r.add_argument("--query", default="",
                   help="narrow the pass, e.g. 'newer_than:5y'. Empty reads "
                        "the whole mailbox.")
    r.add_argument("--limit-net", type=int, default=None,
                   help="cap threads read; omitted means read everything")
    r.add_argument("--reset-dates", action="store_true",
                   help="let this pass replace the dates of the people it "
                        "looked at, even with an older or empty one")
    r.set_defaults(fn=cmd_roster)

    rt = sub.add_parser("roster-todo",
                        help="the next people to search for on the connector")
    rt.add_argument("--connector", type=Path, nargs="*", metavar="FILE",
                    help="roster files written so far; missing ones are fine")
    rt.add_argument("--principal", help="the mailbox owner's address")
    rt.add_argument("--people", type=Path, default=None)
    rt.add_argument("--data-dir", help="the user's Bob folder")
    rt.add_argument("--batch", type=int, default=ROSTER_BATCH,
                    help=f"people per batch (default {ROSTER_BATCH})")
    rt.set_defaults(fn=cmd_roster_todo)

    st = sub.add_parser("scan-todo",
                        help="long threads to fetch whole before the scan, "
                             "so the introducer is the one who opened them")
    st.add_argument("--connector", type=Path, nargs="+", metavar="FILE",
                    help="the scan file(s) written so far")
    st.add_argument("--principal", help="the mailbox owner's address")
    st.add_argument("--data-dir", help="the user's Bob folder")
    st.add_argument("--batch", type=int, default=OPENER_BATCH,
                    help=f"threads per batch (default {OPENER_BATCH})")
    st.set_defaults(fn=cmd_scan_todo)

    g = sub.add_parser("graph", help="read intros.csv, write network.html")
    g.add_argument("--intros", type=Path, default=None)
    g.add_argument("--principal",
                   help="your address; omitted, the one saved by `bob setup`")
    g.add_argument("--out", type=Path, default=None)
    g.add_argument("--people", type=Path, default=None)
    g.add_argument("--data-dir", help="the user's Bob folder; files and the "
                   "saved address are read from it")
    g.set_defaults(fn=cmd_graph, needs_principal=True)

    su = sub.add_parser("setup", help="create the Bob folder and save your "
                        "address in it, so later commands need neither")
    su.add_argument("--data-dir", required=True)
    su.add_argument("--principal", help="your address; saved in bob.json")
    su.add_argument("--gmail", action="store_true",
                    help="take the address from the Gmail token")
    su.set_defaults(fn=cmd_setup)

    n = sub.add_parser("names-todo",
                       help="who still needs a name, and which threads to read")
    n.add_argument("--intros", type=Path, default=DEFAULT_OUT)
    n.add_argument("--names", type=Path,
                   help="existing names.csv, so known people are skipped")
    n.add_argument("--principal",
                   help="your address — you are on every row and need no lookup")
    n.add_argument("--limit", type=int,
                   help="cap the worklist; it is ordered best-evidenced first")
    n.set_defaults(fn=cmd_names_todo)

    na = sub.add_parser("names-add", help="merge extracted names into names.csv")
    na.add_argument("--names", type=Path, required=True)
    na.add_argument("--json", type=Path,
                    help="file of [{address,name,evidence,thread_id}]; "
                         "omit to read stdin")
    na.set_defaults(fn=cmd_names_add)

    ne = sub.add_parser("names-extract",
                        help="parse names out of fetched thread bodies")
    ne.add_argument("--bodies", type=Path, required=True,
                    help="JSONL of threads fetched with messageFormat PLAIN_TEXT")
    ne.add_argument("--names", type=Path, required=True)
    ne.set_defaults(fn=cmd_names_extract)

    args = ap.parse_args(argv)
    _resolve(args)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
