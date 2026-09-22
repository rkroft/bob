"""The release audit's private denylist.

FORBIDDEN names a few people in full. Real contacts reached the public repo
past it anyway: a first name in a docstring, a `first.last@` local part in a
test, a firm's domain written without an "@" (whole-tree sweep, 2026-09-22).
The maintainer's own contact list, kept outside the repo, is checked too.

All people here are the repo's fixture cast; the "real contact" below is an
invented stand-in for one.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))


def _release(tmp_path, terms=None):
    """The release module, with the private denylist pointed at a file here."""
    f = tmp_path / "private-denylist.txt"
    if terms is not None:
        f.write_text("\n".join(terms) + "\n", encoding="utf-8")
    os.environ["BOB_PRIVATE_DENYLIST"] = str(f)
    # tools/release.py is not shipped: in the public export this skips rather
    # than erroring, so the suite a stranger runs still collects.
    release = pytest.importorskip("release")
    return importlib.reload(release)


def _shipped(tmp_path, text, name="commands/x.md"):
    p = tmp_path / "export" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return [Path(name)], tmp_path / "export"


def test_a_contacts_first_name_is_caught(tmp_path):
    rel = _release(tmp_path, ["Quillan"])
    paths, base = _shipped(tmp_path, "an opener -- 'Hi Quillan and Alice'\n")
    assert rel.audit(paths, base)


def test_the_same_name_inside_another_word_is_not(tmp_path):
    rel = _release(tmp_path, ["Quillan"])
    paths, base = _shipped(tmp_path, "the quillanious test\n")
    assert rel.audit(paths, base) == []


def test_a_local_part_is_caught_whatever_the_case(tmp_path):
    rel = _release(tmp_path, ["quillan.stark"])
    paths, base = _shipped(tmp_path, "see Quillan.Stark@example.com\n")
    assert rel.audit(paths, base)


def test_a_domain_label_is_caught_without_an_address(tmp_path):
    rel = _release(tmp_path, ["quillanworks"])
    paths, base = _shipped(tmp_path, '"QuillanWorks.com" passes every test\n')
    assert rel.audit(paths, base)


def test_the_fixture_cast_passes(tmp_path):
    rel = _release(tmp_path, ["Quillan"])
    paths, base = _shipped(
        tmp_path, "Dana Okafor <dana.okafor@example.com> introduced Alice\n")
    assert rel.audit(paths, base) == []


def test_no_denylist_file_is_not_an_error(tmp_path):
    rel = _release(tmp_path)          # no file written
    paths, base = _shipped(tmp_path, "Dana Okafor\n")
    assert rel.audit(paths, base) == []


def test_a_name_lowercased_in_a_local_part_is_caught(tmp_path):
    """What the first version of this check missed: names ship lowercased in
    addresses as often as they ship capitalised in prose."""
    rel = _release(tmp_path, ["Quillan"])
    paths, base = _shipped(tmp_path, "quillan.walsh@example.com\n")
    assert rel.audit(paths, base)


def test_a_full_name_of_ordinary_words_is_caught_as_a_phrase(tmp_path):
    """Every word of some contacts' names is an ordinary English word, so no
    single word of theirs can be a term. The pair can."""
    rel = _release(tmp_path, ["Bright Hunter"])
    paths, base = _shipped(tmp_path, "a note from Bright  Hunter today\n")
    assert rel.audit(paths, base)
    paths, base = _shipped(tmp_path, "bright ideas from a hunter\n", "commands/y.md")
    assert rel.audit(paths, base) == []


def test_the_audit_never_echoes_the_name_it_found(tmp_path):
    rel = _release(tmp_path, ["Quillan"])
    paths, base = _shipped(tmp_path, "Hi Quillan and Alice\n")
    [hit] = rel.audit(paths, base)
    assert "Quillan" not in hit and "commands/x.md" in hit


def test_the_generated_readme_is_audited_too(tmp_path):
    rel = _release(tmp_path, ["Bob"])          # the README says Bob often
    written = rel.write_generated(tmp_path)
    assert rel.audit(written, tmp_path)


@pytest.fixture(autouse=True)
def _restore():
    before = os.environ.get("BOB_PRIVATE_DENYLIST")
    yield
    if before is None:
        os.environ.pop("BOB_PRIVATE_DENYLIST", None)
    else:
        os.environ["BOB_PRIVATE_DENYLIST"] = before
    # Leave the module pointing at the real list, not a deleted tmp file.
    if "release" in sys.modules:
        importlib.reload(sys.modules["release"])


def test_a_name_after_a_dot_is_caught(tmp_path):
    """"x.quillan@" and "email.quillanworks.com" are how a name and a firm's
    domain actually ship (gate review, 2026-09-22)."""
    rel = _release(tmp_path, ["Quillan", "quillanworks"])
    for text in ("alias x.quillan@example.com\n",
                 "see email.quillanworks.test for the firm\n"):
        paths, base = _shipped(tmp_path, text)
        assert rel.audit(paths, base), text


def test_a_hyphenated_full_name_is_caught(tmp_path):
    rel = _release(tmp_path, ["Bright Hunter"])
    paths, base = _shipped(tmp_path, "from Bright-Hunter today\n")
    assert rel.audit(paths, base)


def test_a_file_the_audit_cannot_read_is_reported_not_skipped(tmp_path):
    rel = _release(tmp_path, ["Quillan"])
    paths, base = _shipped(tmp_path, "x,y\n1,2\n", "commands/data.csv")
    [hit] = rel.audit(paths, base)
    assert "not audited" in hit


def test_the_dry_run_audits_the_generated_readme(tmp_path, monkeypatch, capsys):
    """Not audit() directly: main()'s wiring, which a tidy-up could drop."""
    rel = _release(tmp_path, ["Takeout"])      # a word only the README uses
    monkeypatch.setattr(sys, "argv", ["release.py", str(tmp_path / "out"),
                                      "--dry-run"])
    assert rel.main() == 1
    assert "README.md" in capsys.readouterr().err


def test_the_vendored_library_is_a_named_exception(tmp_path):
    rel = _release(tmp_path, ["Quillan"])
    paths, base = _shipped(tmp_path, "var a=1\n", "assets/vis-network.min.js")
    assert rel.audit(paths, base) == []


def test_a_name_glued_into_a_token_is_caught(tmp_path):
    """A firm's domain written as one word around a real name is the shape
    that shipped: no boundary for the pattern to hold on to (gate review,
    2026-09-22)."""
    rel = _release(tmp_path, ["Quillan Stark", "quillanworks"])
    # A term run together with other letters and no case change
    # ("quillanworkstalent") is still invisible: matching it would flag every
    # word containing a short name.
    for text in ('"QuillanStarkTalent.com" passes every other test\n',
                 "quillan_stark = 1\n",
                 "quillan.stark-talent.test\n"):
        paths, base = _shipped(tmp_path, text)
        assert rel.audit(paths, base), text


def test_every_test_module_can_run_in_the_export(tmp_path):
    """The exported suite must collect: a test importing a tool that does not
    ship has to importorskip it (gate review, 2026-09-22)."""
    import re as _re
    rel = _release(tmp_path, [])
    root = Path(__file__).resolve().parents[1]
    shipped = {str(p) for p in rel.SHIP_FILES}
    unshipped = {p.stem for p in (root / "tools").glob("*.py")
                 if f"tools/{p.name}" not in shipped}
    bad = []
    for f in sorted((root / "tests").glob("test_*.py")):
        text = f.read_text(encoding="utf-8")
        for m in _re.finditer(r"^(?:from|import) (\w+)", text, _re.M):
            mod = m.group(1)
            if mod in unshipped and f'importorskip("{mod}")' not in text:
                bad.append(f"{f.name}: imports {mod}, which does not ship")
    assert not bad, bad


def test_a_glued_hit_is_reported_even_when_an_earlier_file_hit_that_line(tmp_path):
    """The report must be complete: an audit that hides findings sends her
    round the loop once per file (gate review, 2026-09-22)."""
    rel = _release(tmp_path, ["Zorvex", "Quillan Stark"])
    base = tmp_path / "export"
    for name, text in (("commands/one.md", "Zorvex here\n"),
                       ("commands/two.md", '"QuillanStarkTalent.com"\n')):
        p = base / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    hits = rel.audit([Path("commands/one.md"), Path("commands/two.md")], base)
    assert any("two.md" in h for h in hits), hits


@pytest.mark.parametrize("text", [
    "ZorvexWorks is the firm\n", "ZORVEXWORKS\n", "Quill-Zorvex wrote\n",
    "QuillZorvex wrote\n",
])
def test_the_built_in_list_sees_case_and_glued_forms_too(tmp_path, monkeypatch,
                                                         text):
    """FORBIDDEN holds the highest-value strings -- her own fund and five
    named people -- and was matched case-sensitively, without the loose pass.
    Stand-in patterns here: the real ones must not ship inside a test."""
    rel = _release(tmp_path, [])
    monkeypatch.setattr(rel, "FORBIDDEN", [r"zorvexworks", r"\bQuill Zorvex\b"])
    paths, base = _shipped(tmp_path, text)
    assert rel.audit(paths, base), text


@pytest.mark.parametrize("extra", [[], ["--dry-run"]])
def test_both_release_paths_say_when_only_the_built_in_list_ran(
        tmp_path, monkeypatch, capsys, extra):
    """"audit clean" must not mean "did not look" -- on the path that
    publishes as much as on the one a review runs (gate review, 2026-09-22).
    Drives main(), so dropping either call site fails here."""
    rel = _release(tmp_path)               # no denylist file
    monkeypatch.setattr(sys, "argv",
                        ["release", str(tmp_path / "out"), *extra])
    assert rel.main() == 0
    assert "no private denylist" in capsys.readouterr().err
