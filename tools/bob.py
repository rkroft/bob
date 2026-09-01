"""Bob's command line.

    bob scan  --mbox PATH --principal you@example.com
    bob scan  --gmail
    bob graph

`scan` reads mail and writes intros.csv. `graph` reads intros.csv and writes
network.html. They share the CSV and nothing else, so the graph can be redrawn
without touching the mailbox.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from graph_model import build_graph  # noqa: E402
from intro_store import read_intros, write_intros  # noqa: E402
from mail_source import best_name  # noqa: E402
from last_contact import last_direct_contact  # noqa: E402
from people_store import build_people, read_people, write_people  # noqa: E402
from mbox_source import MboxSource  # noqa: E402
from render import render  # noqa: E402
from intro_detect import search_queries  # noqa: E402
from scan import scan  # noqa: E402

DEFAULT_OUT = ROOT / "reports" / "intros.csv"
DEFAULT_HTML = ROOT / "reports" / "network.html"
DEFAULT_PEOPLE = ROOT / "reports" / "people.csv"
LEADERBOARD = 10


def gmail_link(thread_id: str) -> str:
    return f"https://mail.google.com/mail/u/0/#all/{thread_id}"


def build_source(args):
    """Returns (source, link_for). Imports GmailSource lazily so the mbox path
    never needs Google credentials on the machine."""
    if args.mbox:
        if not args.principal:
            raise SystemExit("--principal is required with --mbox")
        return MboxSource(args.mbox, principal=args.principal), None
    if args.gmail:
        from gmail_source import GmailSource
        return GmailSource(), gmail_link
    raise SystemExit("need --mbox PATH or --gmail")


def _announce(n: int) -> None:
    depth = "whole mailbox" if True else ""
    print(f"reading {n:,} candidate threads — roughly "
          f"{max(1, round(n / 170))} min", flush=True)


def cmd_scan(args) -> int:
    source, link_for = build_source(args)
    seen_names: dict = {}
    capped: list = []
    contacted: set = set()
    automated: set = set()
    rows = scan(source, link_for=link_for, names_out=seen_names,
                limit_per_query=args.limit_net, capped_out=capped,
                contacted_out=contacted, automated_out=automated,
                progress=_announce)
    names = {a: best_name(v) for a, v in seen_names.items()}

    out = Path(args.out)
    write_intros(rows, out)

    # The roster is derived, so it is rebuilt from scratch every scan — unlike
    # intros.csv, which is a record of events and never rewritten.
    people_path = Path(args.people)
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
                      f"{'person accounts' if len(graph.super_connectors) == 1 else 'people account'}"
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
    people_path = Path(args.people)
    people = read_people(people_path)
    if not people:
        print(f"No roster at {people_path}. Run `bob scan` first.")
        return 1

    source, _ = build_source(args)
    print(f"Reading headers for {len(people)} people. No message bodies are "
          f"read and none are kept.")
    seen = last_direct_contact(source, source.principal(),
                               addresses={p.address for p in people},
                               query=args.query, limit=args.limit_net or 100000)

    updated = [replace(p, last_contact=seen[p.address].date)
               if p.address in seen else p
               for p in people]
    write_people(updated, people_path)

    found = sum(1 for p in updated if p.last_contact)
    print(f"\n{found} of {len(updated)} have a direct exchange on record.")
    # Never let silence read as "you have never spoken". Bob sees one channel.
    missing = len(updated) - found
    if missing:
        print(f"{missing} have none that this mailbox can see — which means "
              f"not found, not never.")
    print(f"wrote {people_path}")
    return 0


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
    s.add_argument("--principal", help="the mailbox owner's address")
    s.add_argument("--out", type=Path, default=DEFAULT_OUT)
    s.add_argument("--people", type=Path, default=DEFAULT_PEOPLE)
    s.add_argument("--limit-net", type=int, default=None,
                   help="cap threads per search for a quick partial pass; "
                        "omitted means read the whole mailbox")
    s.set_defaults(fn=cmd_scan)

    r = sub.add_parser("roster", help="fill in when you last spoke to each person")
    r.add_argument("--mbox", type=Path, help=".mbox file or a directory of them")
    r.add_argument("--gmail", action="store_true", help="use the Gmail source")
    r.add_argument("--principal", help="the mailbox owner's address")
    r.add_argument("--people", type=Path, default=DEFAULT_PEOPLE)
    r.add_argument("--query", default="",
                   help="narrow the pass, e.g. 'newer_than:5y'. Empty reads "
                        "the whole mailbox.")
    r.add_argument("--limit-net", type=int, default=None,
                   help="cap threads read; omitted means read everything")
    r.set_defaults(fn=cmd_roster)

    g = sub.add_parser("graph", help="read intros.csv, write network.html")
    g.add_argument("--intros", type=Path, default=DEFAULT_OUT)
    g.add_argument("--principal", required=True)
    g.add_argument("--out", type=Path, default=DEFAULT_HTML)
    g.add_argument("--people", type=Path, default=DEFAULT_PEOPLE)
    g.set_defaults(fn=cmd_graph)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
