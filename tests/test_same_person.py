"""One person, two addresses: Bob asks, remembers, and ranks them as one.

Measured 2026-09-21 on a real first scan: introducers who wrote from a work
address one year and a personal one the next were ranked as two people with
smaller counts. The connector returns no display names, and names read from
mail text connected almost none of them, so Bob proposes pairs by address and
the user decides. All people here are the repo's fixture cast.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from intro_store import IntroRow  # noqa: E402
from same_person import (  # noqa: E402
    apply, candidates, pending, read_answers, record,
)

ME = "alice.tran@examplecorp.com"


def _row(tid, introducer, introduced=(ME,)):
    return IntroRow(thread_id=tid, date="2026-01-01", direction="inbound",
                    introducer=introducer, introduced=tuple(introduced),
                    subject="Intro", thread_link="", confidence=0.9)


def _pairs(addresses):
    return {frozenset((a, b)) for a, b, _ in candidates(addresses)}


# --- which pairs are worth asking about -------------------------------------

def test_an_initial_plus_surname_matches_the_surname():
    assert frozenset(("dokafor@example.com", "okafor@otherco.io")) in _pairs(
        ["dokafor@example.com", "okafor@otherco.io"])


def test_the_same_full_name_at_two_domains_matches():
    assert _pairs(["dana.okafor@example.com", "dana.okafor@otherco.io"])


def test_a_surname_alone_matches_the_full_name():
    assert _pairs(["okafor@example.com", "dana.okafor@otherco.io"])


def test_a_first_name_inside_a_fuller_one_is_not_asked():
    """Measured on a real scan: a shared first name (nadia@ / nadia.okonjo@,
    dana@ / dana.okafor@) is not evidence."""
    assert not _pairs(["nadia@example.com", "nadia.okonjo@otherco.io"])


def test_a_shared_first_name_alone_is_not_asked():
    assert not _pairs(["dana@example.com", "dana@otherco.io"])


def test_role_addresses_are_never_paired():
    assert not _pairs(["hello@example.com", "hello@otherco.io"])


def test_the_same_domain_is_not_a_second_address():
    assert not _pairs(["dana.okafor@example.com", "d.okafor@example.com"])


def test_short_tokens_are_not_enough():
    assert not _pairs(["nadia.ok@example.com", "ok@otherco.io"])


# --- asking once ----------------------------------------------------------

def test_only_pairs_touching_an_introducer_are_asked_most_intros_first():
    rows = [_row(f"a{i}", "dokafor@example.com") for i in range(3)]
    rows += [_row("b", "okafor@otherco.io")]
    rows += [_row("c", "kai.rivera@example.com",
                  (ME, "nadia.okonjo@example.com", "nadia.okonjo@otherco.io"))]
    todo = pending(rows, {}, principal=ME)
    assert [set(p[:2]) for p in todo] == [{"dokafor@example.com", "okafor@otherco.io"}]


def test_an_answered_pair_is_not_asked_again(tmp_path):
    f = tmp_path / "same-person.csv"
    record(f, "dokafor@example.com", "okafor@otherco.io", False)
    rows = [_row("a", "dokafor@example.com"), _row("b", "okafor@otherco.io")]
    assert pending(rows, read_answers(f), principal=ME) == []


def test_the_last_answer_wins(tmp_path):
    f = tmp_path / "same-person.csv"
    record(f, "dokafor@example.com", "okafor@otherco.io", False)
    record(f, "okafor@otherco.io", "dokafor@example.com", True)
    assert read_answers(f)[frozenset(("dokafor@example.com", "okafor@otherco.io"))]


# --- applying a yes -------------------------------------------------------

def test_a_yes_ranks_both_addresses_as_one_under_the_busier_one(tmp_path):
    f = tmp_path / "same-person.csv"
    record(f, "dokafor@example.com", "okafor@otherco.io", True)
    rows = [_row("a", "dokafor@example.com"), _row("b", "dokafor@example.com"),
            _row("c", "okafor@otherco.io")]
    merged = apply(rows, read_answers(f))
    assert {r.introducer for r in merged} == {"dokafor@example.com"}
    assert len(merged) == 3


def test_a_yes_also_merges_the_person_where_they_were_introduced(tmp_path):
    f = tmp_path / "same-person.csv"
    record(f, "nadia.okonjo@example.com", "nadia.okonjo@otherco.io", True)
    rows = [_row("a", "kai.rivera@example.com", (ME, "nadia.okonjo@otherco.io")),
            _row("b", "nadia.okonjo@example.com")]
    merged = apply(rows, read_answers(f))
    assert "nadia.okonjo@example.com" in merged[0].introduced


def test_a_no_changes_nothing(tmp_path):
    f = tmp_path / "same-person.csv"
    record(f, "dokafor@example.com", "okafor@otherco.io", False)
    rows = [_row("a", "dokafor@example.com"), _row("c", "okafor@otherco.io")]
    assert apply(rows, read_answers(f)) == rows


def test_no_answers_file_is_no_answers(tmp_path):
    assert read_answers(tmp_path / "missing.csv") == {}


# --- the commands ----------------------------------------------------------

def _cli_folder(tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    from intro_store import write_intros
    rows = [_row(f"a{i}", "dokafor@example.com") for i in range(2)]
    rows += [_row("b", "okafor@otherco.io")]
    write_intros(rows, tmp_path / "intros.csv")
    return tmp_path


def test_todo_lists_the_pair_and_an_answer_clears_it(tmp_path, capsys):
    import json
    import bob
    d = _cli_folder(tmp_path)
    capsys.readouterr()
    assert bob.main(["same-person-todo", "--data-dir", str(d), "--principal", ME]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ask"][0]["intros"] == [2, 1]
    assert bob.main(["same-person", "dokafor@example.com", "okafor@otherco.io",
                     "--yes", "--data-dir", str(d)]) == 0
    capsys.readouterr()
    bob.main(["same-person-todo", "--data-dir", str(d), "--principal", ME])
    after = json.loads(capsys.readouterr().out)
    assert after["ask"] == []
    assert after["merged"] == {"okafor@otherco.io": "dokafor@example.com"}


def test_the_graph_ranks_a_confirmed_pair_as_one(tmp_path, capsys):
    import bob
    d = _cli_folder(tmp_path)
    bob.main(["same-person", "dokafor@example.com", "okafor@otherco.io",
              "--yes", "--data-dir", str(d)])
    capsys.readouterr()
    assert bob.main(["graph", "--data-dir", str(d), "--principal", ME]) == 0
    text = capsys.readouterr().out
    assert "3 intros" in text
    # intros.csv still says what the mail said
    assert "okafor@otherco.io" in (d / "intros.csv").read_text()


def test_a_no_between_two_members_stops_that_group_merging(tmp_path):
    """a~b yes, b~c yes, a~c no: the user said a and c differ, so nothing in
    that group is merged behind their back."""
    f = tmp_path / "same-person.csv"
    A, B, C = "dokafor@example.com", "okafor@otherco.io", "dana.okafor@otherco.io"
    record(f, A, B, True)
    record(f, B, C, True)
    record(f, A, C, False)
    rows = [_row("1", A), _row("2", B), _row("3", C)]
    assert {r.introducer for r in apply(rows, read_answers(f))} == {A, B, C}


def test_a_merge_never_lists_someone_as_introduced_by_themselves(tmp_path):
    f = tmp_path / "same-person.csv"
    record(f, "dokafor@example.com", "okafor@otherco.io", True)
    rows = [_row("1", "dokafor@example.com", (ME, "okafor@otherco.io")),
            _row("2", "dokafor@example.com")]
    [r, _] = apply(rows, read_answers(f))
    assert r.introducer not in r.introduced


def test_a_yes_rewrites_the_roster_as_one_person(tmp_path, capsys):
    import bob
    from people_store import read_people
    d = _cli_folder(tmp_path)
    bob.main(["scan", "--help"]) if False else None
    from people_store import build_people, write_people
    from intro_store import read_intros
    write_people(build_people(read_intros(d / "intros.csv"), ME, {}), d / "people.csv")
    bob.main(["same-person", "dokafor@example.com", "okafor@otherco.io", "--yes",
              "--data-dir", str(d), "--principal", ME])
    people = {p.address: p for p in read_people(d / "people.csv")}
    assert people["dokafor@example.com"].intros_for_you == 3
    assert "okafor@otherco.io" not in people


def test_an_answer_keeps_an_automated_platform_a_platform(tmp_path):
    import bob
    from dataclasses import replace
    from people_store import build_people, read_people, write_people
    from intro_store import read_intros, write_intros
    rows = [_row(f"m{i}", "matchbot@otherco.io") for i in range(2)]
    rows += [_row("a", "dokafor@example.com"), _row("b", "okafor@otherco.io")]
    write_intros(rows, tmp_path / "intros.csv")
    people = build_people(rows, ME, {}, automated={"matchbot@otherco.io"})
    write_people(people, tmp_path / "people.csv")
    bob.main(["same-person", "dokafor@example.com", "okafor@otherco.io", "--yes",
              "--data-dir", str(tmp_path), "--principal", ME])
    kinds = {p.address: p.kind for p in read_people(tmp_path / "people.csv")}
    assert kinds["matchbot@otherco.io"] == "platform"


def test_a_merged_person_is_written_to_at_their_most_recent_address(tmp_path, capsys):
    """Ranked under the busier address, emailed at the newer one: an address
    last used years ago may be a former employer's (gate review, 2026-09-21)."""
    import json
    import bob
    from intro_store import write_intros
    old = [IntroRow(f"o{i}", "2022-03-01", "inbound", "dokafor@example.com", (ME,),
                    "Intro", "", 0.9) for i in range(2)]
    new = [IntroRow("n", "2023-06-01", "inbound", "okafor@otherco.io", (ME,),
                    "Intro", "", 0.9)]
    write_intros(old + new, tmp_path / "intros.csv")
    bob.main(["same-person", "dokafor@example.com", "okafor@otherco.io", "--yes",
              "--data-dir", str(tmp_path), "--principal", ME])
    capsys.readouterr()
    bob.main(["same-person-todo", "--data-dir", str(tmp_path), "--principal", ME])
    out = json.loads(capsys.readouterr().out)
    assert out["merged"] == {"okafor@otherco.io": "dokafor@example.com"}
    assert out["write_to"] == {"dokafor@example.com": "okafor@otherco.io"}


def test_an_answer_about_an_address_bob_never_saw_is_refused(tmp_path, capsys):
    import bob
    d = _cli_folder(tmp_path)
    assert bob.main(["same-person", "dokafor@example.com", "okafr@otherco.io",
                     "--yes", "--data-dir", str(d), "--principal", ME]) == 1
    assert not (d / "same-person.csv").exists()


def test_write_to_counts_only_addresses_the_person_sent_from():
    """Being cc'd at an old work address by someone else is not using it
    (HAP-381): "most recently used" means sent from."""
    from same_person import write_to
    rows = [IntroRow("o", "2022-01-01", "inbound", "dokafor@example.com", (ME,),
                     "Intro", "", 0.9),
            IntroRow("n", "2023-01-01", "inbound", "okafor@otherco.io", (ME,),
                     "Intro", "", 0.9),
            IntroRow("c", "2025-01-01", "inbound", "kai.rivera@example.com",
                     (ME, "dokafor@example.com"), "Intro", "", 0.9)]
    merged = {"okafor@otherco.io": "dokafor@example.com"}
    assert write_to(rows, merged) == {"dokafor@example.com": "okafor@otherco.io"}


def test_write_to_breaks_a_tie_the_same_way_every_time():
    from same_person import write_to
    rows = [IntroRow(f"h{i}", "2022-01-01", "inbound", "dokafor@example.com",
                     (ME,), "Intro", "", 0.9) for i in range(3)]
    rows += [IntroRow("b", "2024-01-01", "inbound", "okafor@otherco.io", (ME,),
                      "Intro", "", 0.9),
             IntroRow("c", "2024-01-01", "inbound", "dana.okafor@otherco.io",
                      (ME,), "Intro", "", 0.9)]
    merged = {"okafor@otherco.io": "dokafor@example.com",
              "dana.okafor@otherco.io": "dokafor@example.com"}
    assert write_to(rows, merged) == {"dokafor@example.com": "dana.okafor@otherco.io"}


def test_write_to_counts_addresses_the_principal_wrote_to():
    """One 2019 intro from the old address must not beat four 2025 intros the
    principal made to the other one (gate review, 2026-09-22)."""
    from same_person import write_to
    rows = [IntroRow("o", "2019-01-01", "inbound", "dokafor@example.com", (ME,),
                     "Intro", "", 0.9)]
    rows += [IntroRow(f"n{i}", "2025-01-0%d" % (i + 1), "outbound", ME,
                      ("okafor@otherco.io", f"p{i}@otherco.io"), "Intro", "", 0.9)
             for i in range(4)]
    merged = {"dokafor@example.com": "okafor@otherco.io"}
    assert write_to(rows, merged) == {}
