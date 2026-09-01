"""CLI wiring. No mail is read — GmailSource is never constructed here."""

from __future__ import annotations

import re

import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import bob  # noqa: E402


def test_gmail_link_points_at_the_thread():
    assert bob.gmail_link("abc123").endswith("#all/abc123")
    assert bob.gmail_link("abc123").startswith("https://mail.google.com/")


def test_scan_requires_a_source(capsys):
    with pytest.raises(SystemExit):
        bob.main(["scan"])


def test_mbox_scan_writes_a_csv(tmp_path, monkeypatch):
    import mailbox
    from email.message import EmailMessage

    m = EmailMessage()
    m["From"] = "dana.okafor@example.com"
    m["To"] = "alice.tran@examplecorp.com, ben.mercer@otherco.io"
    m["Subject"] = "Intro: Alice <> Ben"
    m["Date"] = "Tue, 03 Mar 2026 09:00:00 -0800"
    m["X-GM-THRID"] = "1"
    m.set_content("I'd like to introduce you two. Moving myself to bcc.")
    box = mailbox.mbox(str(tmp_path / "All mail.mbox"), create=True)
    box.add(m)
    box.flush()
    box.close()

    out = tmp_path / "intros.csv"
    # EVERY output path must be redirected into tmp_path. `scan` writes the
    # roster as well as intros.csv, and omitting --people sent it to the repo's
    # real reports/people.csv -- a test suite overwriting a user's actual data.
    rc = bob.main([
        "scan", "--mbox", str(tmp_path / "All mail.mbox"),
        "--principal", "alice.tran@examplecorp.com", "--out", str(out),
        "--people", str(tmp_path / "people.csv"),
    ])
    assert rc == 0
    assert out.exists()
    assert "dana.okafor@example.com" in out.read_text()


from datetime import date  # noqa: E402

from graph_model import build_graph  # noqa: E402
from intro_store import IntroRow, write_intros  # noqa: E402

ME = "alice.tran@examplecorp.com"


def _rows():
    return [IntroRow(f"t{i}", "2026-01-0%d" % (i + 1), "inbound",
                     "dana.okafor@example.com", (ME,), "Intro", "", 0.9)
            for i in range(3)]


def test_summary_leads_with_counts_and_a_date():
    g = build_graph(_rows(), ME, today=date(2026, 8, 20))
    text = bob.summary(g, ME)
    assert "3 introductions" in text
    assert "2026-01-01" in text


def test_summary_names_super_connectors():
    g = build_graph(_rows(), ME, today=date(2026, 8, 20))
    assert "dana" in bob.summary(g, ME).lower()


def test_summary_says_so_when_there_is_nothing():
    g = build_graph([], ME, today=date(2026, 8, 20))
    assert "no introductions" in bob.summary(g, ME).lower()


def test_graph_command_writes_html(tmp_path):
    csv_path = tmp_path / "intros.csv"
    write_intros(_rows(), csv_path)
    out = tmp_path / "network.html"
    rc = bob.main(["graph", "--intros", str(csv_path), "--principal", ME,
                   "--out", str(out), "--people", str(tmp_path / "people.csv")])
    assert rc == 0
    assert "<html" in out.read_text()


# --------------------------------------------------------------------------
# Task 9: the CLI has never been exercised end to end against the ring. The
# tests above cover `graph`'s summary/plumbing; these cover the page it
# writes.
# --------------------------------------------------------------------------

@pytest.fixture
def sample_intros(tmp_path):
    """A small intros.csv exercising both intro shapes the ring's picture
    needs. `_rows()` above only ever introduces ME -- and build_graph never
    credits a connector with `people_given` for introducing the principal
    (graph_model.py excludes `p == principal`), so a file of ME-only rows
    would render a page with an empty ring: `class="node"` would never
    appear, and a test asserting it would pass on a broken ring too. The
    second row here has an introducer connecting two OTHER people, which is
    what actually puts a labelled connector on the ring.
    """
    rows = [
        IntroRow("t1", "2026-01-05", "inbound", "dana.okafor@example.com",
                 (ME,), "Meet Dana", "", 0.9),
        IntroRow("t2", "2026-02-10", "inbound", "dana.okafor@example.com",
                 ("carol.nguyen@example.com", "erin.walsh@example.com"),
                 "Carol <> Erin", "", 0.9),
        IntroRow("t3", "2026-03-15", "outbound", ME,
                 ("frank.osei@example.com",), "Intro to Frank", "", 0.9),
    ]
    out = tmp_path / "intros.csv"
    write_intros(rows, out)
    return out


def test_graph_writes_a_page_with_all_four_tabs(tmp_path, sample_intros):
    """The ring replaced the graph inside the Network tab. It did not replace
    the page, and the CLI is the only place that is checked end to end."""
    out = tmp_path / "n.html"
    # --people points at a path that does not exist, on purpose, in every
    # test in this section: omitting the flag falls back to DEFAULT_PEOPLE,
    # which is reports/people.csv -- a real several-hundred-row roster on a
    # machine that has one. That both violates "no real contact data in
    # tests" and makes the test's outcome depend on whether reports/
    # happens to exist, rather than on the code being exercised.
    rc = bob.main(["graph", "--intros", str(sample_intros),
                   "--principal", ME, "--out", str(out),
                   "--people", str(tmp_path / "people.csv")])
    assert rc == 0
    page = out.read_text()
    for pane in ("pane-net", "pane-vol", "pane-time", "pane-table"):
        assert 'data-pane="%s"' % pane in page


def test_graph_writes_a_page_carrying_the_chain_panel(tmp_path, sample_intros):
    out = tmp_path / "n.html"
    bob.main(["graph", "--intros", str(sample_intros),
              "--principal", ME, "--out", str(out),
              "--people", str(tmp_path / "people.csv")])
    page = out.read_text()
    assert 'id="ring-panel"' in page
    assert 'id="ring-grid"' in page


def test_the_written_page_fetches_nothing(tmp_path, sample_intros):
    """The whole point of one self-contained file."""
    out = tmp_path / "n.html"
    bob.main(["graph", "--intros", str(sample_intros),
              "--principal", ME, "--out", str(out),
              "--people", str(tmp_path / "people.csv")])
    page = out.read_text()
    assert "http://" not in page and "https://" not in page


def test_graph_still_works_with_no_roster(tmp_path, sample_intros):
    """`--people` is optional, and when the file genuinely does not exist
    (`tmp_path / "people.csv"` is never written here) `read_people` takes its
    `return []` branch, so `names` is empty and every label render() emits
    comes from `graph_model._label` -- the local-part fallback -- rather than
    a roster. `rc == 0` alone would pass identically whether the roster was
    missing, empty, or fully populated; the fact worth guarding is the
    fallback label actually reaching the page. "dana.okafor@example.com"
    (from `sample_intros`) has no roster entry, so its introducer cell in
    the Introductions table can only read "Dana Okafor" via
    `_label`'s dot-to-space, capitalize-each-word derivation -- not because
    some other code path supplied it.
    """
    out = tmp_path / "n.html"
    rc = bob.main(["graph", "--intros", str(sample_intros),
                   "--principal", ME, "--out", str(out),
                   "--people", str(tmp_path / "people.csv")])
    assert rc == 0
    page = out.read_text()
    assert "Dana Okafor" in page


def test_summary_last_12mo_all_reads_as_all_not_n_of_n():
    """When every intro in the file falls in the last 12 months, `s.last_12mo
    == s.intros` and the generic "N of those N" phrasing is redundant enough
    to read like a template leak. That equality case must special-case to a
    plain "All N" sentence instead."""
    g = build_graph(_rows(), ME, today=date(2026, 8, 20))
    text = bob.summary(g, ME)
    assert "All 3 happened in the last 12 months." in text
    assert " of those " not in text


def test_summary_last_12mo_partial_reads_as_n_of_those_m():
    """When last_12mo is a strict subset of intros (still >= 3, so the line
    is not suppressed), the normal "N of those M" phrasing is the correct,
    non-redundant sentence and must not be collapsed to "All"."""
    rows = _rows() + [IntroRow("t_old", "2020-01-01", "inbound",
                               "dana.okafor@example.com", (ME,), "Intro", "", 0.9)]
    g = build_graph(rows, ME, today=date(2026, 8, 20))
    text = bob.summary(g, ME)
    assert "3 of those 4 happened in the last 12 months." in text


def test_summary_names_a_tail_line_when_more_introducers_than_named():
    """When the leaderboard doesn't cover every introducer, the summary must say
    so rather than letting the printed list read as the whole population — the
    failure mode a flat-distribution mailbox hit (45 unnamed introducers with no
    indication anyone was left out).

    Fourteen introducers against a leaderboard of ten, so four are genuinely
    unnamed. The fixture used ten when the list was capped at eight; with a
    ten-row leaderboard that no longer leaves anyone out, and the assertion
    would have been true for the wrong reason."""
    rows = [IntroRow(f"t{i}", "2026-01-01", "inbound",
                     f"introducer{i}@x.test", (ME,), "Intro", "", 0.9)
            for i in range(14)]
    g = build_graph(rows, ME, today=date(2026, 8, 20))
    text = bob.summary(g, ME)
    # The wording used to be "Everyone else introduced you to one person, or
    # two" -- a claim about counts nothing had checked. It now states only how
    # many people are unlisted, which is a fact the data supports.
    assert "other people who introduced you to someone" in text


def test_summary_omits_the_tail_line_when_every_introducer_is_named():
    """When the super-connector set already accounts for everyone, the tail
    line would be false ("everyone else" — there is no one else) and must
    not appear."""
    g = build_graph(_rows(), ME, today=date(2026, 8, 20))
    text = bob.summary(g, ME)
    assert "Everyone else" not in text


def test_summary_singular_counts_do_not_double_up_plurals():
    """Guards the first-run copy: at N=1 every hard-coded plural noun in the
    summary ("1 introductions", "1 people", "1 intros") reads like an
    unfinished tool. With exactly one introduction in the file, no count in
    the summary should render with a doubled-up plural."""
    rows = [IntroRow("t1", "2026-01-01", "inbound",
                     "dana.okafor@example.com", (ME,), "Intro", "", 0.9)]
    g = build_graph(rows, ME, today=date(2026, 8, 20))
    text = bob.summary(g, ME)
    assert "1 intros" not in text
    assert "1 introductions" not in text
    assert "1 people" not in text


def test_summary_uses_real_names_not_local_parts():
    rows = [IntroRow(f"t{i}", "2026-01-01", "inbound", "mlee@x.test", (ME,),
                     "Intro", "", 0.9) for i in range(3)]
    g = build_graph(rows, ME, today=date(2026, 8, 20),
                    names={"mlee@x.test": "Marcus Lee"})
    text = bob.summary(g, ME)
    assert "Marcus Lee" in text
    assert "mlee" not in text


def test_leaderboard_names_at_most_ten_people():
    rows = [IntroRow(f"t{i}", "2026-01-01", "inbound", f"c{i}@x.test", (ME,),
                     "Intro", "", 0.9) for i in range(40)]
    g = build_graph(rows, ME, today=date(2026, 8, 20))
    # Match only connector rows -- "   Name          3 intros". A looser filter
    # also catches "N people have introduced you to someone".
    rowpat = re.compile(r"^\s{3}\S.*\s\d+ intros?$")
    listed = [ln for ln in bob.summary(g, ME).splitlines() if rowpat.match(ln)]
    assert len(listed) == 10, listed


@pytest.fixture(autouse=True)
def _redirect_every_default_output(tmp_path, monkeypatch):
    """Send every module-level output default into tmp_path, for every test.

    This is DEFENCE, replacing a guard that only pretended to be one. The
    original asserted that three hardcoded constants pointed at reports/ --
    restating the condition that caused the incident rather than preventing it,
    and staying green for any newly added argument. Adding --people to `scan`
    had already let the suite overwrite a real 504-row roster produced by a live
    Gmail scan, because existing tests passed --out and knew nothing about the
    new argument.

    Discovering the constants by prefix means a new one is covered the moment it
    is added, with no test needing to know it exists.
    """
    for attr in [a for a in dir(bob) if a.startswith("DEFAULT_")]:
        value = getattr(bob, attr)
        if isinstance(value, Path):
            monkeypatch.setattr(bob, attr, tmp_path / value.name)


def test_every_path_argument_lands_inside_the_test_directory(tmp_path):
    """And DETECTION, for a default that is not a DEFAULT_ constant.

    Walks the real parser rather than a list someone has to remember to update:
    every argument that produces a Path must default somewhere the fixture
    above redirected. A literal path inlined into add_argument() would fail
    here instead of quietly writing into the user's reports/ directory.
    """
    import argparse
    parser = None
    real = argparse.ArgumentParser.parse_args

    def capture(self, *a, **kw):
        nonlocal parser
        parser = parser or self
        raise SystemExit(0)

    monkey = argparse.ArgumentParser.parse_args
    argparse.ArgumentParser.parse_args = capture
    try:
        try:
            bob.main(["scan"])
        except SystemExit:
            pass
    finally:
        argparse.ArgumentParser.parse_args = monkey

    assert parser is not None, "could not reach the parser"
    checked = 0
    for action in parser._subparsers._group_actions[0].choices.values():
        for arg in action._actions:
            default = arg.default
            if isinstance(default, Path):
                checked += 1
                assert str(default).startswith(str(tmp_path)), (
                    f"{arg.option_strings} defaults to {default}, outside the "
                    f"test directory — a test omitting it would write there"
                )
    assert checked >= 3, f"expected several Path defaults, found {checked}"


def _mbox_with_a_later_direct_reply(tmp_path):
    """An intro in March, then a direct exchange in June. The roster pass has
    to find the June one, which no intro thread contains."""
    import mailbox
    from email.message import EmailMessage

    box = mailbox.mbox(str(tmp_path / "All mail.mbox"), create=True)
    intro = EmailMessage()
    intro["From"] = "dana.okafor@example.com"
    intro["To"] = "alice.tran@examplecorp.com, ben.mercer@otherco.io"
    intro["Subject"] = "Intro: Alice <> Ben"
    intro["Date"] = "Tue, 03 Mar 2026 09:00:00 -0800"
    intro["X-GM-THRID"] = "1"
    intro.set_content("I'd like to introduce you two. Moving myself to bcc.")
    box.add(intro)

    later = EmailMessage()
    later["From"] = "alice.tran@examplecorp.com"
    later["To"] = "dana.okafor@example.com"
    later["Subject"] = "coffee?"
    later["Date"] = "Mon, 15 Jun 2026 09:00:00 -0700"
    later["X-GM-THRID"] = "2"
    later.set_content("Free Thursday?")
    box.add(later)
    box.flush()
    box.close()
    return tmp_path / "All mail.mbox"


def test_roster_records_contact_that_no_intro_thread_contains(tmp_path):
    mbox = _mbox_with_a_later_direct_reply(tmp_path)
    people = tmp_path / "people.csv"
    assert bob.main(["scan", "--mbox", str(mbox), "--principal", ME,
                     "--out", str(tmp_path / "intros.csv"),
                     "--people", str(people)]) == 0
    assert bob.main(["roster", "--mbox", str(mbox), "--principal", ME,
                     "--people", str(people)]) == 0

    from people_store import read_people
    dana = [p for p in read_people(people)
            if p.address == "dana.okafor@example.com"][0]
    assert dana.last_contact == "2026-06-15"


def test_roster_keeps_everything_the_scan_wrote(tmp_path):
    """The pass is additive. A roster run that rebuilt the file would drop the
    intro counts and the names the scan spent a whole mailbox read collecting."""
    mbox = _mbox_with_a_later_direct_reply(tmp_path)
    people = tmp_path / "people.csv"
    bob.main(["scan", "--mbox", str(mbox), "--principal", ME,
              "--out", str(tmp_path / "intros.csv"), "--people", str(people)])
    from people_store import read_people
    before = {p.address: (p.name, p.intros_for_you) for p in read_people(people)}

    bob.main(["roster", "--mbox", str(mbox), "--principal", ME,
              "--people", str(people)])
    after = {p.address: (p.name, p.intros_for_you) for p in read_people(people)}
    assert after == before


def test_roster_without_a_scan_says_what_to_run(tmp_path, capsys):
    rc = bob.main(["roster", "--mbox", str(tmp_path / "nope.mbox"),
                   "--principal", ME, "--people", str(tmp_path / "none.csv")])
    assert rc == 1
    assert "bob scan" in capsys.readouterr().out


# --------------------------------------------------------------------------
# One mailbox per run, said out loud
#
# `/bob-scan` passes --principal on the --gmail path, where the token decides
# whose mailbox it is. That argument used to be accepted and discarded without
# a word, while the plugin's config field described it as comma-separated --
# so a user listing two addresses had every reason to think both were read.
# --------------------------------------------------------------------------

def test_a_second_address_is_reported_not_silently_dropped(capsys):
    """The mbox path: first address wins, the rest are named as unread."""
    from bob import build_source

    class Args:
        mbox = str(Path(__file__).parent / "fixtures")
        gmail = False
        principal = "alice.tran@examplecorp.com, dana.okafor@example.com"

    try:
        build_source(Args())
    except (SystemExit, FileNotFoundError):
        pass  # no fixture mbox here; the message before it is what matters
    out = capsys.readouterr().out
    assert "alice.tran@examplecorp.com" in out
    assert "dana.okafor@example.com" in out
    assert "one mailbox at a time" in out


def test_the_gmail_token_decides_and_says_so(capsys):
    """The Gmail path: the token's account is authoritative, and an address
    that is not it is reported as unread rather than ignored."""
    import bob as bob_mod

    class FakeGmail:
        def principal(self):
            return "alice.tran@examplecorp.com"

    class Args:
        mbox = None
        gmail = True
        principal = "alice.tran@examplecorp.com,dana.okafor@example.com"

    fake_mod = types.ModuleType("gmail_source")
    fake_mod.GmailSource = FakeGmail
    # Save and restore rather than delete: gmail_source may already be
    # imported, and dropping it breaks whatever imports it next.
    saved = sys.modules.get("gmail_source")
    sys.modules["gmail_source"] = fake_mod
    try:
        source, link = bob_mod.build_source(Args())
    finally:
        if saved is not None:
            sys.modules["gmail_source"] = saved
        else:
            sys.modules.pop("gmail_source", None)

    out = capsys.readouterr().out
    assert source.principal() == "alice.tran@examplecorp.com"
    assert "dana.okafor@example.com" in out
    assert "not read by this run" in out
    assert "BOB_GOOGLE_TOKEN" in out


def test_the_only_address_produces_no_noise(capsys):
    """One address is the normal case and must say nothing extra."""
    import bob as bob_mod

    class FakeGmail:
        def principal(self):
            return "alice.tran@examplecorp.com"

    class Args:
        mbox = None
        gmail = True
        principal = "alice.tran@examplecorp.com"

    fake_mod = types.ModuleType("gmail_source")
    fake_mod.GmailSource = FakeGmail
    # Save and restore rather than delete: gmail_source may already be
    # imported, and dropping it breaks whatever imports it next.
    saved = sys.modules.get("gmail_source")
    sys.modules["gmail_source"] = fake_mod
    try:
        bob_mod.build_source(Args())
    finally:
        if saved is not None:
            sys.modules["gmail_source"] = saved
        else:
            sys.modules.pop("gmail_source", None)

    assert "not read by this run" not in capsys.readouterr().out
