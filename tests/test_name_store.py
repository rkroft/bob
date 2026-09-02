"""name_store tests.

All people here are invented placeholders (repo rule — never real contacts).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from intro_store import IntroRow  # noqa: E402
from name_store import (  # noqa: E402
    Name, as_lookup, is_plausible, merge, read_names, worklist, write_names,
)

DANA = "dana.okafor@example.com"
ALICE = "alice.tran@examplecorp.com"
BEN = "ben.mercer@otherco.io"


def _row(tid, introducer, introduced, date="2026-03-04"):
    return IntroRow(thread_id=tid, date=date, direction="inbound",
                    introducer=introducer, introduced=tuple(introduced),
                    subject="Intro", thread_link="", confidence=0.9)


# --- plausibility ----------------------------------------------------------

def test_rejects_the_shapes_that_are_certainly_wrong():
    assert not is_plausible("")
    assert not is_plausible("   ")
    assert not is_plausible("dana.okafor@example.com")     # an address
    assert not is_plausible("12345")                        # no letters
    assert not is_plausible("Dana Okafor " + "x" * 60)      # swallowed a block
    assert not is_plausible("Dana Okafor Head Of Partnerships At Example Corp")


def test_accepts_ordinary_names_including_unusual_ones():
    """Not a spelling check — Bob cannot know how someone spells their name."""
    for n in ("Dana Okafor", "dana okafor", "Ana", "Jean-Luc Picard",
              "Mary Anne Van Der Berg"):
        assert is_plausible(n), n


# --- precedence ------------------------------------------------------------

def test_stronger_evidence_replaces_weaker():
    got = merge({}, [
        Name(DANA, "Dana", "greeting"),
        Name(DANA, "Dana Okafor", "signature"),
    ])
    assert got[DANA].name == "Dana Okafor"
    assert got[DANA].evidence == "signature"


def test_weaker_evidence_never_replaces_stronger():
    got = merge({}, [
        Name(DANA, "Dana Okafor", "signature"),
        Name(DANA, "Dana", "greeting"),
    ])
    assert got[DANA].name == "Dana Okafor"


def test_equal_evidence_does_not_replace_so_labels_are_stable():
    """Two signatures spelling it differently must not flip between runs.

    Whichever thread the scan read last would otherwise decide the label, and
    the graph would change for a reason the user cannot see.
    """
    got = merge({}, [
        Name(DANA, "Dana Okafor", "signature", "t1"),
        Name(DANA, "D. Okafor", "signature", "t2"),
    ])
    assert got[DANA].name == "Dana Okafor"
    assert got[DANA].thread_id == "t1"


def test_unknown_evidence_is_dropped_not_ranked_last():
    """A typo'd source would otherwise win simply by arriving first."""
    got = merge({}, [Name(DANA, "Dana Okafor", "signiture")])
    assert got == {}


def test_local_part_is_not_storable():
    """It stays a render-time fallback so storage never implies Bob knows."""
    assert merge({}, [Name(DANA, "Dana Okafor", "local_part")]) == {}


def test_implausible_names_are_dropped():
    assert merge({}, [Name(DANA, "dana.okafor@example.com", "signature")]) == {}


def test_addresses_are_normalized_and_names_cleaned():
    got = merge({}, [Name("  Dana <DANA.Okafor@Example.COM> ", "Dana Okafor,",
                          "signature")])
    assert list(got) == [DANA]
    assert got[DANA].name == "Dana Okafor"


# --- round trip ------------------------------------------------------------

def test_round_trip(tmp_path):
    p = tmp_path / "names.csv"
    names = merge({}, [Name(DANA, "Dana Okafor", "signature", "t1"),
                       Name(ALICE, "Alice", "greeting", "t2")])
    write_names(names, p)
    back = read_names(p)
    assert as_lookup(back) == {DANA: "Dana Okafor", ALICE: "Alice"}
    assert back[ALICE].evidence == "greeting"


def test_missing_file_is_empty_not_an_error(tmp_path):
    """A scan that never had a name pass is normal, not broken."""
    assert read_names(tmp_path / "nope.csv") == {}


def test_reading_applies_precedence_to_a_file_with_duplicates(tmp_path):
    p = tmp_path / "names.csv"
    p.write_text(
        "address,name,evidence,thread_id\n"
        f"{DANA},Dana,greeting,t1\n"
        f"{DANA},Dana Okafor,signature,t2\n", encoding="utf-8")
    assert read_names(p)[DANA].name == "Dana Okafor"


# --- worklist --------------------------------------------------------------

def test_worklist_skips_addresses_already_known():
    rows = [_row("t1", DANA, [ALICE])]
    known = merge({}, [Name(DANA, "Dana Okafor", "signature")])
    assert [a for a, _ in worklist([DANA, ALICE], known, rows)] == [ALICE]


def test_worklist_offers_only_threads_the_person_is_on():
    rows = [_row("t1", DANA, [ALICE]), _row("t2", DANA, [BEN])]
    got = dict(worklist([ALICE, BEN], {}, rows))
    assert got[ALICE] == ["t1"]
    assert got[BEN] == ["t2"]


def test_worklist_puts_the_best_evidenced_first():
    """A capped pass should spend its calls where they are likeliest to pay."""
    rows = [_row("t1", DANA, [ALICE]), _row("t2", DANA, [ALICE]),
            _row("t3", DANA, [BEN])]
    assert [a for a, _ in worklist([ALICE, BEN], {}, rows)] == [ALICE, BEN]


def test_worklist_omits_addresses_with_no_thread_to_look_in():
    """Nowhere to look is not a task — it would be a call that cannot pay."""
    rows = [_row("t1", DANA, [ALICE])]
    assert [a for a, _ in worklist([BEN], {}, rows)] == []


def test_worklist_excludes_the_principal():
    """The principal is on every row by design and needs no name lookup.

    The connector→principal edge is the fact the product exists to surface, so
    they appear as a party to every introduction — and would otherwise top a
    worklist ordered by how much evidence there is.
    """
    rows = [_row("t1", DANA, [ALICE]), _row("t2", BEN, [ALICE])]
    got = [a for a, _ in worklist([DANA, ALICE, BEN], {}, rows, exclude=[ALICE])]
    assert ALICE not in got
    assert sorted(got) == sorted([DANA, BEN])


# --- quoted-attribution extraction -----------------------------------------

from name_store import extract_quoted_names  # noqa: E402


def _names(body):
    return {n.address: n.name for n in extract_quoted_names(body)}


def test_extracts_a_plain_attribution():
    body = "On Tue, Feb 6, 2026 at 11:42 AM Dana Okafor <dana.okafor@example.com> wrote:"
    assert _names(body) == {DANA: "Dana Okafor"}


def test_trims_the_date_prefix_and_the_timezone_token():
    """The name is adjacent to the bracket; everything before it varies."""
    for prefix in ("On February 6, 2026, ",
                   "On Tue, Feb 6, 2026 at 11:42 AM ",
                   "On Tue, 6 Feb 2026 at 19:42 PST ",
                   ""):
        body = f"{prefix}Dana Okafor <dana.okafor@example.com> wrote:"
        assert _names(body) == {DANA: "Dana Okafor"}, prefix


def test_strips_quote_markers_so_a_nested_reply_still_matches():
    body = (">> On Tue, Feb 6, 2026 at 12:08 PM Dana Okafor <\n"
            ">> dana.okafor@example.com> wrote:\n")
    assert _names(body) == {DANA: "Dana Okafor"}


def test_handles_the_wrapped_address_with_a_mailto_duplicate():
    """Some clients emit "<addr\\n<mailto:addr>>", which hides the real closing
    bracket until the duplicate is removed. This shape is why the top connector
    on a real corpus had no name (HAP-318)."""
    body = ("> On Tue, Feb 6, 2026 at 11:42 AM Dana Okafor <dana.okafor@example.com\n"
            "> <mailto:dana.okafor@example.com>> wrote:\n")
    assert _names(body) == {DANA: "Dana Okafor"}


def test_ignores_a_bare_address_with_no_name():
    assert _names("please cc <dana.okafor@example.com> on this") == {}


def test_ignores_a_mailto_link_on_its_own():
    assert _names("<mailto:dana.okafor@example.com>") == {}


def test_drops_anything_that_does_not_trim_to_a_plausible_name():
    """A confident-looking wrong name is the failure mode being avoided."""
    body = "Sent from my iPhone 15 Pro Max Edition 2026 <dana.okafor@example.com>"
    assert _names(body) == {}


def test_several_attributions_in_one_body():
    body = ("On Tue Dana Okafor <dana.okafor@example.com> wrote:\n"
            "> On Mon Ben Mercer <ben.mercer@otherco.io> wrote:\n")
    assert _names(body) == {DANA: "Dana Okafor", "ben.mercer@otherco.io": "Ben Mercer"}


def test_quoted_header_outranks_signature_and_greeting():
    """It is a header one hop removed — the client copied it, already paired."""
    got = merge({}, [Name(DANA, "Dana", "greeting"),
                     Name(DANA, "Dana O", "signature"),
                     Name(DANA, "Dana Okafor", "quoted_header")])
    assert got[DANA].name == "Dana Okafor"
