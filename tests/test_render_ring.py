"""The ring page. Invented placeholder people only (repo rule)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from graph_model import Chain, GraphData, Node, Stats  # noqa: E402
from render_ring import render_ring, ring_entries, ring_pane  # noqa: E402

ME = "alice.tran@examplecorp.com"
DANA = "dana.okafor@example.com"
MARCUS = "marcus.lee@thirdco.com"
CARA = "cara@thirdco.com"


def graph(nodes, chains=()):
    return GraphData(nodes=nodes, edges=[],
                     stats=Stats(9, 6, 3, 5, 0, "2019-03-14", "2026-01-02", 4),
                     super_connectors=[], top_connectors=[],
                     chains=list(chains))


G = graph([Node(ME, "Alice Tran", 0, 5, 0),
           Node(DANA, "Dana Okafor", 4, 0, 3),
           Node(MARCUS, "Marcus Lee", 2, 1, 2),
           Node("kai@fourthco.dev", "Kai Rivera", 1, 1, 1)],
          chains=[Chain(DANA, MARCUS, (CARA,)), Chain(DANA, CARA, ())])


def test_the_principal_is_never_a_ring_node():
    assert ME not in [e.id for e in ring_entries(G, ME, None)]


def test_people_who_introduced_nobody_are_not_on_the_ring():
    assert [e.id for e in ring_entries(G, ME, None)] == \
        [DANA, MARCUS, "kai@fourthco.dev"]


def test_a_chain_starter_is_marked_on_the_ring():
    entries = ring_entries(G, ME, None)
    assert [e.id for e in entries if e.is_chain_starter] == [DANA]


def test_the_page_states_how_many_introducers_it_counted():
    """Replaces test_the_caption_and_the_picture_cannot_disagree, which pinned
    the drawn-node count against the caption's number via data-drawn. With the
    ring parked there is no drawn count to disagree with; the surviving
    caption-vs-content invariant is one test further down --
    test_the_panel_sentence_matches_the_rows_rendered -- which checks the same
    sentence against the rows actually rendered beneath it."""
    markup, _, _ = ring_pane(G, principal=ME)
    assert "3 introducers" in markup


def test_the_page_fetches_nothing(tmp_path):
    out = tmp_path / "ring.html"
    render_ring(G, out, principal=ME)
    page = out.read_text()
    assert "http://" not in page and "https://" not in page


def test_a_name_cannot_close_the_script_element(tmp_path):
    g = graph([Node(ME, "Alice", 0, 1, 0),
               Node("x@example.com", "</script><script>alert(1)</script>",
                    2, 0, 2)])
    out = tmp_path / "ring.html"
    render_ring(g, out, principal=ME)
    assert "</script><script>alert(1)" not in out.read_text()


def test_a_name_cannot_inject_markup(tmp_path):
    g = graph([Node(ME, "Alice", 0, 1, 0),
               Node("x@example.com", "<img src=x onerror=alert(1)>", 4, 0, 4)])
    out = tmp_path / "ring.html"
    render_ring(g, out, principal=ME)
    page = out.read_text()
    # With the ring parked a name no longer reaches an HTML sink at all -- the
    # SVG <title> and the label spans went with the picture -- so the JSON blob
    # in the inline <script> is now the ONLY sink, and it carries the whole
    # load on its own.
    assert "<img src=x" not in page
    assert "\\u003cimg src=x" in page


def test_the_panel_lists_every_chain_starter(tmp_path):
    out = tmp_path / "ring.html"
    render_ring(G, out, principal=ME)
    page = out.read_text()
    assert page.count('class="starter"') == 1
    assert "Dana Okafor" in page


def test_the_panel_sentence_matches_the_rows_rendered(tmp_path):
    """FIX 2: the sentence's numerator must equal the number of starter rows
    actually drawn beneath it, and the denominator must be every introducer
    the ring draws -- `starters` is counted over all of them
    (graph_model.chain_starters), so measuring the sentence against repeat
    connectors only makes it false whenever a one-time introducer starts a
    chain, which is exactly what happened for five of eighteen on the real
    corpus."""
    out = tmp_path / "ring.html"
    render_ring(G, out, principal=ME)
    page = out.read_text()
    m = re.search(r'(\d+) of your (\d+) introducers started a chain', page)
    assert m is not None
    assert int(m.group(1)) == page.count('class="starter"')
    assert int(m.group(2)) == len(ring_entries(G, ME, None))


def test_the_bracket_kid_count_says_people_not_introductions(tmp_path):
    """FIX 3: `b.kids` is bracket_layout's distinct-people count, not a row
    count, so the word beside it must be 'people'. 32 of 169 connectors
    differed under the old 'introductions' wording -- Dana Okafor showed 6 in
    the leaderboard and 10 in the bracket from the same data."""
    out = tmp_path / "ring.html"
    render_ring(G, out, principal=ME)
    page = out.read_text()
    assert "' person'" in page and "' people')" in page
    assert "' introduction'" not in page and "' introductions')" not in page
    # Also verify the shipping path (ring_pane) has the same wording
    _, _, script = ring_pane(G, principal=ME)
    assert "' people')" in script and "' introductions')" not in script


def test_a_flat_mailbox_says_so(tmp_path):
    g = graph([Node(ME, "Alice", 0, 2, 0), Node("a@example.com", "Ada", 1, 0, 1),
               Node("b@example.com", "Bo", 1, 0, 1)])
    out = tmp_path / "ring.html"
    render_ring(g, out, principal=ME)
    assert "no repeat connectors yet" in out.read_text()


def test_no_introducers_does_not_draw_a_ring(tmp_path):
    g = graph([Node(ME, "Alice", 0, 0, 0)])
    out = tmp_path / "ring.html"
    render_ring(g, out, principal=ME)
    page = out.read_text()
    assert 'class="node"' not in page
    assert "no introductions found yet" in page


def test_motion_is_behind_a_reduced_motion_guard():
    """The handoff's interaction contract says selection is an opacity change
    and "any transition is at most a 120ms opacity fade behind
    prefers-reduced-motion". A test for exactly this was specified in the Task
    8 brief and never written, so the module shipped `transition: opacity .12s`
    rules with no guard at all: motion-sensitive users got the fade whether
    their OS asked for reduced motion or not.

    Every stylesheet the module can emit is discovered by name rather than
    listed, so one added later cannot slip through the same gap this one did.
    """
    import render_ring

    sheets = {n: v for n, v in vars(render_ring).items()
              if n.endswith("_CSS") and isinstance(v, str)}
    assert sheets, "no stylesheet found -- this test has stopped guarding anything"
    for name, css in sheets.items():
        if "transition" in css:
            assert "prefers-reduced-motion" in css, (
                "%s has a transition with no reduced-motion guard" % name)


def test_the_standalone_page_embeds_the_shipping_panes_own_markup(tmp_path):
    """The page and the pane drew the same picture from two separate
    implementations, and they had already drifted: the panel's wording had to
    be corrected in both places, and the kid-count test above still carries an
    "also verify the shipping path" assertion for exactly that reason. Building
    the page out of ring_pane() leaves nothing to drift -- there is one
    implementation and the page is a document shell around it.
    """
    out = tmp_path / "ring.html"
    render_ring(G, out, principal=ME)
    page = out.read_text()

    markup, css, script = ring_pane(G, principal=ME)
    assert markup in page, "the page does not draw the pane's picture"
    assert css in page, "the page does not use the pane's stylesheet"
    assert script in page, "the page does not use the pane's behaviour"


def test_every_entry_point_to_selection_is_keyboard_reachable():
    """Three things drive selectOrToggle(): a ring node, a leaderboard row and
    a chain-starter row. Ring nodes were focusable and answered Enter/Space;
    the leaderboard rows were wired for click only, so a keyboard user could
    reach the same selection through one door and not the other."""
    _, _, script = ring_pane(G, principal=ME)
    board = script[script.index("var boardRows"):]
    assert "keydown" in board, "leaderboard rows answer the mouse only"
    assert "tabindex" in board, "leaderboard rows are not focusable"


def test_every_focusable_control_shows_where_the_focus_is():
    """Making a row focusable without giving it a focus style moves the
    problem rather than fixing it: a keyboard user can now reach the control
    and still cannot see which one they are on. All three doors into
    selectOrToggle() carry the same 2px terracotta outline."""
    from render_ring import _RING_PANE_CSS

    # `.node:focus` is parked with the ring rather than deleted -- see
    # test_the_network_pane_draws_no_ring. These two render today.
    for sel in ("#board li:focus", ".starter:focus"):
        assert sel in _RING_PANE_CSS, "%s has no focus style" % sel
        rule = _RING_PANE_CSS.split(sel, 1)[1].split("}", 1)[0]
        assert "outline" in rule, "%s is focusable with nothing to see" % sel


def test_the_network_pane_draws_no_ring():
    """Parked 2026-08-27. The picture came out of the page while the question
    of what job it actually does in the product's scenario of use is still
    open. Nothing is deleted: ring_layout.py's geometry and the builders that
    consume it are kept unused, alongside src/layout.py, and both are waiting
    on the same product call."""
    markup, _, _ = ring_pane(G, principal=ME)
    assert 'id="ring-svg"' not in markup
    assert 'class="node"' not in markup
    assert 'class="labels"' not in markup


def test_the_bracket_is_still_reachable_without_the_ring():
    """The ring was one of three doors into a bracket. With it gone the
    chain-starter rows and the leaderboard rows are the only two left, so they
    now carry the whole interaction rather than merely duplicating it."""
    markup, _, script = ring_pane(G, principal=ME)
    assert 'class="starter"' in markup
    assert "var boardRows" in script
    assert "BRACKETS" in script


def test_the_panel_does_not_point_at_a_picture_that_is_gone():
    markup, _, _ = ring_pane(G, principal=ME)
    assert "ringed node" not in markup
