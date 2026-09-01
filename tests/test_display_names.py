"""Display names survive from the mail headers to the Message.

All people here are invented placeholders (repo rule — never real contacts).
"""

from __future__ import annotations

import mailbox
import sys
from email.message import EmailMessage
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mail_source import Message, best_name  # noqa: E402
from mbox_source import MboxSource  # noqa: E402

ALICE = "alice.tran@examplecorp.com"


def _mbox(tmp_path, headers, body="hello"):
    m = EmailMessage()
    for k, v in headers.items():
        m[k] = v
    m["Subject"] = "Intro: Alice <> Ben"
    m["Date"] = "Tue, 03 Mar 2026 09:00:00 -0800"
    m["X-GM-THRID"] = "1"
    m.set_content(body)
    p = tmp_path / "All mail.mbox"
    box = mailbox.mbox(str(p), create=True)
    box.add(m)
    box.flush()
    box.close()
    return MboxSource(p, principal=ALICE)


# -- Message carries names alongside addresses ---------------------------


def test_message_keeps_the_from_display_name():
    m = Message(id="m1", from_addr="Dana Okafor <dana@example.com>",
                from_name="Dana Okafor")
    assert m.from_addr == "dana@example.com"
    assert m.from_name == "Dana Okafor"


def test_names_default_to_empty_not_missing():
    m = Message(id="m1", from_addr="dana@example.com")
    assert m.from_name == ""
    assert m.to_names == [] and m.cc_names == []


def test_recipient_names_line_up_with_recipient_addresses():
    m = Message(
        id="m1", from_addr="dana@example.com",
        to_addrs=["alice@examplecorp.com", "ben@otherco.io"],
        to_names=["Alice Tran", "Ben Mercer"],
    )
    assert dict(zip(m.to_addrs, m.to_names)) == {
        "alice@examplecorp.com": "Alice Tran",
        "ben@otherco.io": "Ben Mercer",
    }


# -- the mbox source populates them --------------------------------------


def test_mbox_source_captures_display_names(tmp_path):
    src = _mbox(tmp_path, {
        "From": "Dana Okafor <dana@example.com>",
        "To": "Alice Tran <alice.tran@examplecorp.com>, Ben Mercer <ben@otherco.io>",
    })
    (thread,) = src.fetch(["1"])
    msg = thread.messages[0]
    assert msg.from_name == "Dana Okafor"
    assert msg.to_names == ["Alice Tran", "Ben Mercer"]


def test_an_address_with_no_display_name_yields_an_empty_name(tmp_path):
    src = _mbox(tmp_path, {"From": "dana@example.com",
                           "To": "alice.tran@examplecorp.com"})
    (thread,) = src.fetch(["1"])
    assert thread.messages[0].from_name == ""
    assert thread.messages[0].to_names == [""]


def test_quoted_and_encoded_display_names_are_decoded(tmp_path):
    src = _mbox(tmp_path, {
        "From": '"Okafor, Dana" <dana@example.com>',
        "To": "=?utf-8?q?Zo=C3=AB_Bj=C3=B8rn?= <zoe@examplecorp.com>",
    })
    (thread,) = src.fetch(["1"])
    msg = thread.messages[0]
    assert msg.from_name == "Okafor, Dana"
    assert msg.to_names == ["Zoë Bjørn"]


# -- picking one name per address ----------------------------------------


def test_best_name_prefers_the_most_frequent_spelling():
    assert best_name(["Nadia", "Nadia Okonjo", "Nadia Okonjo"]) == "Nadia Okonjo"


def test_best_name_breaks_ties_by_most_recent():
    # Equal counts: the last one seen wins, because it is the newest evidence.
    assert best_name(["Nadia", "Nadia Okonjo"]) == "Nadia Okonjo"


def test_best_name_ignores_blanks():
    assert best_name(["", "Dana Okafor", ""]) == "Dana Okafor"


def test_best_name_of_nothing_is_empty():
    assert best_name([]) == ""
    assert best_name(["", ""]) == ""


def test_best_name_strips_surrounding_quotes_and_space():
    assert best_name(['  "Dana Okafor"  ']) == "Dana Okafor"


# --------------------------------------------------------------------------
# Where a name came from matters as much as how often it appears.
# --------------------------------------------------------------------------


def test_best_name_prefers_a_well_attested_fuller_form():
    """"Marcus Leyva Lee" contains "Marcus Leyva". Someone who goes by all three
    names appears under each, and the plurality winner is a truncation of who
    they are — but the fuller form must itself be well attested, or a lone
    signature block wins. Three sightings of the short form, two of the long."""
    names = ["Marcus Leyva"] * 3 + ["Marcus Leyva Lee"] * 2
    assert best_name(names) == "Marcus Leyva Lee"


def test_a_lone_decorated_header_cannot_beat_the_common_form():
    """The failure the frequency rule exists to prevent: one signature line or
    one "(via Acme Scheduling)" suffix outvoting ninety-nine normal headers."""
    assert best_name(["Dana Okafor"] * 99 + ["Dana Okafor | Acme — Head of BD"]) \
        == "Dana Okafor"
    assert best_name(["Dana Okafor"] * 99 + ["Dana Okafor (via Acme Scheduling)"]) \
        == "Dana Okafor"


def test_casing_variants_are_one_candidate_not_two():
    """"DANA OKAFOR" is not a different person, and must not split the vote or
    win by being a token-superset of itself."""
    assert best_name(["Dana Okafor"] * 99 + ["DANA OKAFOR"]) == "Dana Okafor"


def test_control_characters_never_survive():
    """A display name is printed to a terminal. An escape sequence in it can
    retitle the window or, via OSC 52, reach the clipboard."""
    assert best_name(["Dana\x1b]0;pwned\x07 Okafor"]) == "Dana]0;pwned Okafor"


def test_a_fuller_form_must_contain_every_token_not_merely_be_longer():
    # "Dana Okafor-Smith" is not a superset of {dana, okafor}: different tokens.
    assert best_name(["Dana Okafor", "Dana Okafor", "Someone Else Entirely"]) == "Dana Okafor"


def test_superset_preference_does_not_override_a_different_person():
    assert best_name(["Nadia Okonjo", "Nadia Okonjo", "Nadia"]) == "Nadia Okonjo"
