"""The connector ring and its chain bracket.

One implementation, two ways out: ring_pane() returns (markup, css, script)
for render.py to embed in its Network tab -- the path that ships -- and
render_ring() wraps that same return value in a document of its own. They
were two implementations until they drifted; now the page cannot disagree
with the tab, because it is the tab.

No CDN, no webfont fetch, no analytics (Plugin MVP §9.6). Inline SVG and inline
CSS only -- the vendored physics library is not used by this view.

Every name here is attacker-controlled mail text. It reaches three sinks -- the
SVG <title>, the HTML label spans, and the JSON blob in the inline <script> --
and each gets its own escaping. Three injection holes were found through three
different sinks in one session; fixing one gives no protection against the next.

The JSON blob feeds the bracket a click draws: it is escaped so it cannot close
the <script> element, but that only makes the STRING safe. The runtime code
that reads it is a fourth thing that has to hold the line on its own -- every
name pulled out of BRACKETS reaches the page through `textContent`, never
through string concatenation into `innerHTML`. The bracket's shapes (paths,
circles) ARE built by string concatenation, but only ever out of numbers and
our own fixed class names -- never out of a name.

Spec: docs/superpowers/specs/2026-08-21-connector-ring-design.md
"""

from __future__ import annotations

import html
import json
import math
from pathlib import Path
from string import Template

from graph_model import chain_starters
from ring_layout import (
    BRACKET_W, CX, CY, DOT_R, VIEW_H, VIEW_W, X_CONN, X_KID, X_ON,
    RingEntry,
    bracket_layout, fan_offsets, place_labels, place_ring,
)

# Organic design system, from the handoff's token table.
GROUND, CARD, PANEL = "#f5ead8", "#fdfaf4", "#f9f4ed"
INK, INK2, MUTED = "#201e1d", "#474238", "#82796a"
TERRA, TERRA_DEEP, TERRA_TINT = "#c67139", "#8c491a", "#ffe1d0"
SAGE, SAGE_DEEP, SAGE_DARK = "#7a8a5e", "#56633f", "#3d472b"
N200, N300, N400, N800 = "#eee7db", "#dcd3c4", "#c0b6a5", "#474238"
ELBOW_YOU = "#a19786"
LINE = "rgba(32,30,29,.16)"
SANS = "-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif"
SERIF = "Georgia,'Times New Roman',serif"
# Display face for headings only, named but never fetched -- a missing display
# face costs less than a network call (handoff, "Design tokens").
DISPLAY = "'Caprasimo'," + SERIF


def _esc(s) -> str:
    return html.escape(str(s), quote=True)


def _json(obj) -> str:
    """JSON for an inline <script>. json.dumps escapes neither < nor /, so
    mail-derived text could close the script element early."""
    return json.dumps(obj).replace("<", "\\u003c")


def ring_entries(graph, principal: str, people=None) -> list:
    """Every introducer except the principal, counted in distinct people.

    The principal is in the DATA but not in the PICTURE: everyone here was
    introduced to them, so that node is true of all and informative about none.
    """
    principal = (principal or "").lower()
    services = {p.address for p in (people or []) if p.is_service}
    starters = set(chain_starters(graph))
    out = []
    for n in graph.nodes:
        if n.id.lower() == principal or n.people_given < 1:
            continue
        out.append(RingEntry(id=n.id, label=n.label, count=n.people_given,
                             is_service=n.id in services,
                             is_chain_starter=n.id in starters))
    out.sort(key=lambda e: (-e.count, e.label))
    return out


def _ring_svg(placed) -> str:
    counts = sorted({p.count for p in placed})
    rad_of = {p.count: p.rad for p in placed}
    out = []
    for k in counts:
        out.append('<circle cx="%.0f" cy="%.0f" r="%.1f" fill="none" '
                   'stroke="%s" stroke-width="1" opacity=".5"/>'
                   % (CX, CY, rad_of[k], N300))
    for p in placed:
        if p.count < 2:
            continue
        out.append('<line class="spoke" data-id="%s" x1="%.0f" y1="%.0f" '
                   'x2="%.1f" y2="%.1f" stroke="%s" stroke-width="1" '
                   'opacity=".32"/>' % (_esc(p.id), CX, CY, p.x, p.y, N400))
    for p in placed:
        col = SAGE if p.is_service else TERRA
        for dx, dy in fan_offsets(p):
            out.append('<circle class="ring-dot" data-id="%s" cx="%.1f" cy="%.1f" '
                       'r="%.1f" fill="%s" opacity=".7"/>'
                       % (_esc(p.id), dx, dy, DOT_R, col))
    for p in placed:
        col = SAGE if p.is_service else TERRA
        tip = "%s — introduced you to %d %s" % (
            p.label, p.count, "person" if p.count == 1 else "people")
        title = "<title>%s</title>" % _esc(tip)
        if p.is_chain_starter:
            out.append('<circle class="starter-ring" data-id="%s" cx="%.1f" '
                       'cy="%.1f" r="%.1f" fill="none" stroke="%s" '
                       'stroke-width="2.2"/>'
                       % (_esc(p.id), p.x, p.y, p.r + 5.5, SAGE))
        opacity = ' opacity=".55"' if p.count == 1 else ""
        out.append('<circle class="node" data-id="%s" tabindex="0" cx="%.1f" '
                   'cy="%.1f" r="%.1f" fill="%s"%s>%s</circle>'
                   % (_esc(p.id), p.x, p.y, p.r, col, opacity, title))
        if p.count > 1:
            fs = 12 if p.count > 9 else 10
            out.append('<text class="count" data-id="%s" x="%.1f" y="%.1f" '
                       'text-anchor="middle" font-size="%d" font-weight="700" '
                       'fill="%s" pointer-events="none">%d</text>'
                       % (_esc(p.id), p.x, p.y + fs * 0.35, fs, CARD, p.count))
    out.append('<circle cx="%.0f" cy="%.0f" r="28" fill="none" stroke="%s" '
               'stroke-width="1"/>' % (CX, CY, N400))
    out.append('<circle cx="%.0f" cy="%.0f" r="20" fill="%s"/>' % (CX, CY, INK))
    out.append('<text x="%.0f" y="%.0f" text-anchor="middle" font-size="11" '
               'font-weight="700" fill="%s" pointer-events="none">you</text>'
               % (CX, CY + 4, GROUND))
    return "".join(out)


def _leaders(labels) -> str:
    out = []
    for l in labels:
        if not l.moved:
            continue
        p = l.placed
        ex = p.x + math.cos(p.angle) * (p.r + 2)
        ey = p.y + math.sin(p.angle) * (p.r + 2)
        out.append('<path class="leader" data-id="%s" d="M%.1f %.1f L%.1f %.1f '
                   'L%.1f %.1f" fill="none" stroke="%s" stroke-width="1" '
                   'opacity=".55"/>' % (_esc(p.id), ex, ey, l.x, l.y,
                                        l.x + (-6 if l.left else 6), l.y, N400))
    return "".join(out)


def _label_spans(labels) -> str:
    return "".join(
        '<span class="lbl %s" data-id="%s" style="left:%.3f%%;top:%.3f%%">%s</span>'
        % ("l" if l.left else "r", _esc(l.placed.id),
           l.x / VIEW_W * 100, l.y / VIEW_H * 100, _esc(l.placed.label))
        for l in labels)


def _panel(graph, entries) -> str:
    """Right column, nothing selected: one sentence, then a row per chain
    starter. Copy and type sizes are the handoff's."""
    by_id = {e.id: e for e in entries}
    starters = [s for s in chain_starters(graph) if s in by_id]
    onward_of, carried_of = {}, {}
    for c in graph.chains:
        if not c.onward:
            continue
        onward_of[c.introducer] = onward_of.get(c.introducer, 0) + len(c.onward)
        carried_of[c.introducer] = carried_of.get(c.introducer, 0) + 1
    rows = []
    for a in starters:
        e = by_id[a]
        rows.append(
            '<button class="starter" data-id="%s" type="button">'
            '<span class="s-name">%s</span>'
            '<span class="s-count">%d</span>'
            '<span class="s-onward">+%d</span></button>'
            % (_esc(a), _esc(e.label), e.count, onward_of.get(a, 0)))
    # Denominator is every introducer the ring draws, not just repeat
    # connectors -- `starters` is already counted over all of them
    # (graph_model.chain_starters), and a sentence measured against a smaller
    # population than its own numerator contradicts the rows rendered right
    # below it. Five of eighteen starters on the real corpus were one-time
    # introducers; "N of your M repeat connectors" was false for those five.
    lead = ("%d of your %d introducers started a chain — someone they "
            "introduced went on to introduce you onward. Click a name to open "
            "their chain." % (len(starters), len(entries)))
    return '<p class="lead">%s</p>%s' % (_esc(lead), "".join(rows))


def _default_panel(graph, entries) -> str:
    """The right column with nothing selected. When nobody has made a second
    introduction yet there is no chain to describe -- instead of an empty panel,
    this message explains that chains start once someone introduces the principal
    to more than one person."""
    repeat = sum(1 for e in entries if e.count > 1)
    if repeat == 0:
        n = len(entries)
        return (
            '<p class="lead">You have %d %s so far, but no repeat connectors '
            'yet — nobody has introduced you to more than one person. Chains '
            'start once someone does that twice.</p>'
            % (n, "introducer" if n == 1 else "introducers")
        )
    return _panel(graph, entries)


def _header(graph, principal: str) -> tuple:
    """The header block, and the people-count it prints (reused for the
    bracket's "N% of TOTAL" line, so the two numbers can't drift apart)."""
    s = graph.stats
    total_people = (s.people - (1 if principal else 0)) if s else 0
    total_intros = s.intros if s else 0
    if s and s.first_date:
        span = "%s &rarr; %s &middot; %d in the last 12 months" % (
            _esc(s.first_date), _esc(s.last_date), s.last_12mo)
    else:
        span = "no introductions found"
    if graph.super_connectors:
        n = len(graph.super_connectors)
        sc = "%d %s account for half of them" % (
            n, "person" if n == 1 else "people")
        span = sc if span == "no introductions found" else span + " &middot; " + sc
    out = (
        '<div class="header"><h3>%d introduction%s &middot; %d %s</h3>'
        '<div class="sub">%s</div></div>'
        % (total_intros, "" if total_intros == 1 else "s", total_people,
           "person" if total_people == 1 else "people", span)
    )
    return out, total_people


def _path_d(points) -> str:
    """An SVG path 'd' string from a bracket elbow's points. Coordinates only
    -- nothing here is ever a name."""
    parts = []
    for i, (x, y) in enumerate(points):
        parts.append("%s%.1f %.1f" % ("M" if i == 0 else "L", x, y))
    return " ".join(parts)


def _bracket_data(graph, entries, people=None) -> dict:
    """id -> everything the click handler needs to draw that connector's
    chain bracket, client-side, from one JSON blob (handoff, "State
    management"). Node labels travel here as data, not markup -- the runtime
    reads them with `textContent`, never `innerHTML`."""
    label_of = {n.id: n.label for n in graph.nodes}
    services = frozenset(p.address for p in (people or []) if p.is_service)
    out = {}
    for e in entries:
        b = bracket_layout(e.id, e.label, graph.chains, label_of, services)
        out[e.id] = {
            "label": e.label,
            "height": round(b.height, 1),
            "reach": b.reach,
            "carried": b.carried,
            "kids": b.kids,
            "nodes": [
                {"id": n.id, "label": n.label, "kind": n.kind,
                 "x": round(n.x, 1), "y": round(n.y, 1),
                 "carried": n.carried, "is_service": n.is_service}
                for n in b.nodes
            ],
            "elbows": [
                {"kind": el.kind, "d": _path_d(el.points)} for el in b.elbows
            ],
        }
    return out


_PAGE = Template("""<!doctype html>
<html><head><meta charset="utf-8"><title>Your connector ring</title>
<style>${css}</style></head><body>
<div class="card">
${header}
${body}
</div>
</body></html>
""")


# --------------------------------------------------------------------------
# ring_pane(): the same picture, re-exposed for embedding inside an existing
# page's #pane-net (src/render.py). render_ring() below wraps this same
# return value in a document of its own, so there is one implementation and
# the tab and the page cannot drift apart.
#
# render.py's page already owns ids of its
# own -- including, until this task, an id="panel" for its force-graph click
# detail card -- so every id and CSS selector here is prefixed "ring-" or
# scoped under the ".ring-pane" wrapper, and the script looks elements up
# through that wrapper rather than `document`, so it can never collide with,
# or swallow clicks meant for, the rest of that page (the tabs, the
# leaderboard, the other three panes).
# --------------------------------------------------------------------------

_RING_PANE_STYLE = """
/* ring */
.ring-pane, .ring-pane * { box-sizing: border-box; }
.ring-pane { position: relative; border-radius: 28px; background: ${card}; box-shadow: 0 3px 10px rgba(46,43,37,.16); overflow: hidden; font: 14px/1.5 ${sans}; color: ${ink}; }
.ring-pane .grid { display: grid; grid-template-columns: 300px 1fr; gap: 30px; padding: 24px 28px 30px; align-items: start; }
.ring-pane .empty { padding: 60px 28px; text-align: center; color: ${muted}; font-size: 14px; }

/* Left column: the leaderboard card in normal flow, then the ring stage
   directly beneath it. #board is rendered by render.py's own page-level
   markup (unmodified, still class="card") and handed to ring_pane() so it
   can sit inside this column instead of overlapping it as an absolute
   overlay -- see render.py's `.card { position: absolute; ... }` page-level
   rule, which this overrides on ID + ancestor specificity rather than being
   edited itself, since that rule may still be what other callers expect. */
.ring-pane .ring-left { display: flex; flex-direction: column; gap: 20px; }
.ring-pane #board { position: static; top: auto; left: auto; margin: 0; }

.ring-pane .ring-col { position: relative; }
.ring-pane .ring-col svg { display: block; width: 100%; height: auto; }
.ring-pane .node { cursor: pointer; transition: opacity .12s; }
.ring-pane .node:focus,
.ring-pane #board li:focus,
.ring-pane .starter:focus { outline: 2px solid ${terra}; outline-offset: 2px; }
.ring-pane [data-id] { transition: opacity .12s; }
.ring-pane .dim { opacity: .2 !important; }
@media (prefers-reduced-motion: reduce) {
  .ring-pane .node, .ring-pane [data-id] { transition: none; }
}

.ring-pane .labels { position: absolute; inset: 0; pointer-events: none; }
.ring-pane .lbl { position: absolute; pointer-events: auto; font: 600 11.5px/1.2 ${sans}; color: ${ink2}; white-space: nowrap; padding: 0 3px; }
.ring-pane .lbl.l { transform: translate(-100%, -50%); }
.ring-pane .lbl.r { transform: translate(0, -50%); }

.ring-pane .panel { background: ${panel}; border-radius: 16px; padding: 20px 22px; }
.ring-pane .panel .lead { margin: 0 0 14px; font-size: 13.5px; line-height: 1.55; color: ${ink2}; }
.ring-pane .starter { display: flex; align-items: center; gap: 10px; width: 100%; text-align: left; background: none; border: none; border-radius: 999px; padding: 8px 12px; margin: 2px 0; cursor: pointer; font: inherit; }
.ring-pane .starter:hover { background: ${terra_tint}; }
.ring-pane .s-name { flex: 1; font: 600 14px/1.2 ${sans}; color: ${ink}; }
.ring-pane .s-count { font: 700 13px/1.2 ${sans}; color: ${terra_deep}; }
.ring-pane .s-onward { font: 700 12px/1.2 ${sans}; color: ${sage_deep}; }

.ring-pane .clear-pill { display: inline-block; font: inherit; font-size: 12.5px; background: ${n200}; color: ${muted}; border: none; padding: 5px 12px; border-radius: 999px; white-space: nowrap; cursor: pointer; }
.ring-pane .clear-pill:hover { background: ${terra_tint}; color: ${terra_deep}; }
.ring-pane .bracket-title { margin: 12px 0 10px; font: 400 22px/1.2 ${display}; color: ${ink}; }

.ring-pane .stat-strip { background: ${panel}; border-radius: 16px; padding: 12px 16px; font-size: 13px; color: ${ink2}; display: flex; flex-wrap: wrap; gap: 26px; }
.ring-pane .stat-strip b { font-weight: 700; color: ${ink}; }

.ring-pane .col-headers { position: relative; height: 14px; margin: 16px 0 8px; }
.ring-pane .col-headers span { position: absolute; top: 0; font: 700 12px/1 ${sans}; letter-spacing: .09em; text-transform: uppercase; color: ${muted}; white-space: nowrap; }

.ring-pane .bracket-wrap { position: relative; margin-top: 6px; }
.ring-pane .bracket-wrap svg { display: block; width: 100%; height: auto; }
.ring-pane .bn-conn { fill: ${terra}; }
.ring-pane .bn-conn.svc { fill: ${sage}; }
.ring-pane .bn-kid { fill: ${card}; stroke: ${terra}; stroke-width: 2; }
.ring-pane .bn-kid.carried { fill: ${terra}; stroke: none; }
.ring-pane .bn-onward { fill: ${sage}; }
.ring-pane .eb-you { stroke: ${elbow_you}; stroke-width: 2; fill: none; stroke-linejoin: round; opacity: .55; }
.ring-pane .eb-kid { stroke: ${terra}; stroke-width: 1.8; fill: none; stroke-linejoin: round; opacity: .55; }
.ring-pane .eb-onward { stroke: ${sage}; stroke-width: 1.6; fill: none; stroke-linejoin: round; opacity: .55; }

.ring-pane .bracket-labels { position: absolute; inset: 0; pointer-events: none; }
.ring-pane .bracket-labels span { position: absolute; transform: translateY(-50%); white-space: nowrap; pointer-events: auto; }
.ring-pane .bl-conn-name { font: 700 16px/1.2 ${sans}; color: ${ink}; }
.ring-pane .bl-conn-sub { font: 500 12.5px/1.2 ${sans}; color: ${muted}; }
.ring-pane .bl-kid { font: 500 13.5px/1.2 ${sans}; color: ${ink2}; }
.ring-pane .bl-kid.carried { font-weight: 700; }
.ring-pane .bl-onward { font: 500 13px/1.2 ${sans}; color: ${sage_dark}; }
/* end ring */
"""

_RING_PANE_CSS = Template(_RING_PANE_STYLE).substitute(
    ground=GROUND, card=CARD, panel=PANEL, ink=INK, ink2=INK2, muted=MUTED,
    terra=TERRA, terra_deep=TERRA_DEEP, terra_tint=TERRA_TINT, sage=SAGE,
    sage_deep=SAGE_DEEP, sage_dark=SAGE_DARK, n200=N200, n300=N300, n400=N400,
    n800=N800, elbow_you=ELBOW_YOU, line=LINE, sans=SANS, serif=SERIF,
    display=DISPLAY,
)


_RING_PANE_MARKUP = Template("""<div class="ring-pane">
  <div class="grid" id="ring-grid">
    <div class="ring-left">
      ${board_html}
    </div>
    <div class="panel" id="ring-panel">${panel_html}</div>
  </div>
</div>""")

_EMPTY_RING_PANE = Template("""<div class="ring-pane">
  <div class="ring-left">
    ${board_html}
    <div class="empty">no introductions found yet</div>
  </div>
</div>""")


# The whole of the ring's behaviour, as one self-contained IIFE: the data
# blob lives INSIDE the closure (as `var`s) rather than as page-level
# `const`s, and every element lookup goes through `root`
# -- the ring's own grid container -- so nothing here can reach, or be
# reached by, an element belonging to the host page's other panes, tabs or
# leaderboard.
_RING_PANE_SCRIPT = Template("""(function () {
  var root = document.getElementById('ring-grid');
  if (!root) return;
  var panelEl = document.getElementById('ring-panel');
  var selected = null;
  var BRACKETS = ${brackets};
  var TOTAL_PEOPLE = ${total_people};
  var DEFAULT_PANEL = ${default_panel};
  var BRACKET_W = ${bracket_w};
  var X_CONN = ${x_conn}, X_KID = ${x_kid}, X_ON = ${x_on};

  function dim(id) {
    var els = root.querySelectorAll('[data-id]');
    for (var i = 0; i < els.length; i++) {
      els[i].classList.toggle('dim', els[i].getAttribute('data-id') !== id);
    }
  }

  function clearDim() {
    var els = root.querySelectorAll('[data-id]');
    for (var i = 0; i < els.length; i++) els[i].classList.remove('dim');
  }

  function wireDefaultPanel() {
    var rows = panelEl.querySelectorAll('.starter');
    for (var i = 0; i < rows.length; i++) {
      (function (row) {
        row.addEventListener('click', function () {
          openBracket(row.getAttribute('data-id'));
        });
      })(rows[i]);
    }
  }

  function clearSel() {
    selected = null;
    clearDim();
    panelEl.innerHTML = DEFAULT_PANEL;
    wireDefaultPanel();
  }

  // Select id, or clear if it is already selected -- the one selection
  // routine, shared by a ring node click/keydown and a leaderboard row
  // click, so the two entry points can never drift into different
  // behaviour (per the brief: reuse this, do not write a second one).
  function selectOrToggle(id) {
    if (selected === id) { clearSel(); } else { openBracket(id); }
  }

  // Coordinates and our own fixed class names only -- never a name. Names
  // reach the page a few lines down, through textContent.
  function circleFor(n) {
    if (n.kind === 'connector') {
      return '<circle class="bn-conn' + (n.is_service ? ' svc' : '') +
             '" cx="' + n.x + '" cy="' + n.y + '" r="19"/>';
    }
    if (n.kind === 'introduced') {
      var r = n.carried ? 9 : 7;
      return '<circle class="bn-kid' + (n.carried ? ' carried' : '') +
             '" cx="' + n.x + '" cy="' + n.y + '" r="' + r + '"/>';
    }
    return '<circle class="bn-onward" cx="' + n.x + '" cy="' + n.y + '" r="6"/>';
  }

  function pathFor(e) {
    return '<path class="eb-' + e.kind + '" d="' + e.d + '"/>';
  }

  function addLabel(labelsRoot, x, y, w, h, text, cls) {
    var span = document.createElement('span');
    span.className = cls;
    span.style.left = (x / w * 100) + '%';
    span.style.top = (y / h * 100) + '%';
    span.textContent = text;           // names are attacker text
    labelsRoot.appendChild(span);
  }

  function openBracket(id) {
    var b = BRACKETS[id];
    if (!b) return;
    selected = id;
    dim(id);

    panelEl.innerHTML = '';

    var back = document.createElement('button');
    back.type = 'button';
    back.className = 'clear-pill';
    back.textContent = '\\u2190 clear';
    back.addEventListener('click', clearSel);
    panelEl.appendChild(back);

    var h4 = document.createElement('h4');
    h4.className = 'bracket-title';
    h4.textContent = b.label;          // attacker text -> textContent
    panelEl.appendChild(h4);

    var stat = document.createElement('div');
    stat.className = 'stat-strip';
    var pct = TOTAL_PEOPLE ? (100 * b.reach / TOTAL_PEOPLE).toFixed(1) : '0.0';
    var onward = b.reach - b.kids;
    var items = [
      ['chain reaches ', b.reach + (b.reach === 1 ? ' person' : ' people')],
      ['carried further ', b.carried + ' of ' + b.kids + ' \\u2192 ' + onward + ' more'],
      ['', pct + '% of ' + TOTAL_PEOPLE]
    ];
    for (var i = 0; i < items.length; i++) {
      var s0 = document.createElement('span');
      s0.className = 'stat-item';
      s0.appendChild(document.createTextNode(items[i][0]));
      var strong = document.createElement('b');
      strong.textContent = items[i][1];
      s0.appendChild(strong);
      stat.appendChild(s0);
    }
    panelEl.appendChild(stat);

    var headers = document.createElement('div');
    headers.className = 'col-headers';
    var cols = [[X_CONN, 'the connector'],
                [X_KID, 'introduced you to'], [X_ON, 'who then introduced you to']];
    for (var j = 0; j < cols.length; j++) {
      var s1 = document.createElement('span');
      s1.style.left = (cols[j][0] / BRACKET_W * 100) + '%';
      s1.textContent = cols[j][1];
      headers.appendChild(s1);
    }
    panelEl.appendChild(headers);

    var wrap = document.createElement('div');
    wrap.className = 'bracket-wrap';
    var svgParts = [];
    for (var k = 0; k < b.elbows.length; k++) svgParts.push(pathFor(b.elbows[k]));
    for (var m = 0; m < b.nodes.length; m++) svgParts.push(circleFor(b.nodes[m]));
    wrap.innerHTML = '<svg viewBox="0 0 ' + BRACKET_W + ' ' + b.height + '">' +
                      svgParts.join('') + '</svg>';

    var labelsWrap = document.createElement('div');
    labelsWrap.className = 'bracket-labels';
    for (var p = 0; p < b.nodes.length; p++) {
      var n = b.nodes[p];
      if (n.kind === 'connector') {
        addLabel(labelsWrap, n.x + 26, n.y - 21, BRACKET_W, b.height, n.label, 'bl-conn-name');
        // b.kids is distinct PEOPLE this connector introduced (bracket_layout's
        // `kids`), not a row count -- "introductions" here would silently
        // relabel a people-count as a row-count, the exact mismatch FIX 3
        // exists to close (32 of 169 connectors differed on the real corpus).
        var introText = b.kids + (b.kids === 1 ? ' person' : ' people');
        addLabel(labelsWrap, n.x + 26, n.y + 19, BRACKET_W, b.height, introText, 'bl-conn-sub');
      } else if (n.kind === 'introduced') {
        addLabel(labelsWrap, n.x + 16, n.y, BRACKET_W, b.height, n.label,
                 n.carried ? 'bl-kid carried' : 'bl-kid');
      } else {
        addLabel(labelsWrap, n.x + 14, n.y, BRACKET_W, b.height, n.label, 'bl-onward');
      }
    }
    wrap.appendChild(labelsWrap);
    panelEl.appendChild(wrap);
  }

  var ringNodes = root.querySelectorAll('.node');
  for (var ni = 0; ni < ringNodes.length; ni++) {
    (function (n) {
      n.addEventListener('click', function () {
        selectOrToggle(n.getAttribute('data-id'));
      });
      n.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          selectOrToggle(n.getAttribute('data-id'));
        }
      });
    })(ringNodes[ni]);
  }

  // Leaderboard rows carry the same address a ring node does (render.py
  // stamps `li.dataset.id = r.id` when it builds each row) so a click there
  // can drive the exact same selection routine. Only wire rows whose
  // address IS a ring node's -- an address off the ring gets no click
  // handler and no pointer cursor, so nothing that looks inert lies about
  // being clickable, and nothing throws on a lookup miss.
  var boardRows = root.querySelectorAll('#board li[data-id]');
  for (var bi = 0; bi < boardRows.length; bi++) {
    (function (row) {
      var id = row.getAttribute('data-id');
      if (!BRACKETS[id]) return;
      row.style.cursor = 'pointer';
      // Same contract a ring node gets: focusable, announced as a control,
      // and answering Enter/Space. A row that responds to a click and not to
      // Enter is a door only some people can open.
      row.setAttribute('tabindex', '0');
      row.setAttribute('role', 'button');
      row.addEventListener('click', function () { selectOrToggle(id); });
      row.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          selectOrToggle(id);
        }
      });
    })(boardRows[bi]);
  }

  wireDefaultPanel();
})();""")


def ring_pane(graph, principal: str = "", people=None, board_html: str = "") -> tuple:
    """(markup, css, script) for the connector ring, embedded inside an
    existing page's #pane-net rather than shipped as its own document.

    Built from the exact same data and the same builders as render_ring()
    above -- _ring_svg, _leaders, _label_spans, _default_panel/_panel,
    _bracket_data -- so the two call paths can never draw a different
    picture from the same graph. What differs is only the wrapping: ids and
    CSS selectors are scoped so this can sit inside a page that already has
    ids and classes of its own.

    The header line ("N introductions... ") is deliberately NOT part of this
    return value -- the host page already prints it (render.py's own
    <header>), and repeating it here would either drift from that number or
    print it twice.

    `board_html` is the leaderboard card's markup, verbatim from render.py --
    id="board", class="card" and all. It is threaded through rather than
    built here so #board's markup stays owned by render.py (the brief: "Keep
    #board -- it is not part of this change"); this function only places it
    inside the ring's own grid, in normal flow above the ring stage, so it no
    longer has to collide with the ring as an absolute overlay.
    """
    principal = (principal or "").lower()
    _, total_people = _header(graph, principal)
    entries = ring_entries(graph, principal, people)

    if not entries:
        # Mirrors render_ring()'s empty state: say nothing looks identical to
        # a page that forgot to render, so say it explicitly instead. No
        # interactive script is needed when there is no ring to click -- the
        # leaderboard still renders, just inert (nothing to select).
        return (_EMPTY_RING_PANE.substitute(board_html=board_html),
               _RING_PANE_CSS, "")

    panel_html = _default_panel(graph, entries)
    brackets = _bracket_data(graph, entries, people)

    markup = _RING_PANE_MARKUP.substitute(
        board_html=board_html, panel_html=panel_html,
    )
    script = _RING_PANE_SCRIPT.substitute(
        brackets=_json(brackets), total_people=total_people,
        default_panel=_json(panel_html), bracket_w=BRACKET_W,
        x_conn=X_CONN, x_kid=X_KID, x_on=X_ON,
    )
    return markup, _RING_PANE_CSS, script


def render_ring(graph, out_path: Path, principal: str = "", people=None) -> None:
    """The ring as its own document.

    A shell around ring_pane(): the same markup, the same stylesheet and the
    same behaviour, so this page and the Network tab render.py embeds can
    never draw a different picture from the same graph. Two implementations
    stood here and had already drifted -- the panel's wording had to be
    corrected in both -- which is why the page now owns only the <head>, the
    header line and the card around them.
    """
    principal = (principal or "").lower()
    header, _ = _header(graph, principal)
    markup, css, script = ring_pane(graph, principal, people)
    # An empty ring returns no script; a bare <script></script> would still be
    # valid but says the page has behaviour when it has none.
    body = markup + ("\n<script>%s</script>" % script if script else "")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(_PAGE.substitute(css=css, header=header, body=body),
                        encoding="utf-8")
