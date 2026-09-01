"""GraphData -> one self-contained network.html.

"Self-contained" literally: there are no CDN references, webfonts or
analytics. The CRM's renderer called itself self-contained while loading
vis-network from unpkg at open time — so the graph needed internet to display
and every viewing pinged a third party. For a product whose whole claim is
that nothing leaves the user's machine, that contradiction sat inside the one
artifact they look at (Plugin MVP §9.6).

**The Network tab draws the connector ring, not a physics graph.** The
force-directed vis-network view this file used to build here was a scope
error, now corrected: `render_ring.ring_pane()` supplies the picture instead,
and the vendored `assets/vis-network.min.js` is no longer embedded on this
page at all. `render()` no longer takes a `vendor_js` argument or checks for
that file's existence — nothing here reads it any more, so gating on its
presence was a live failure mode with no upside. The file itself still sits
in `assets/` for now; deleting it is a separate decision.

**Fonts fall back on purpose.** Fraunces and Nunito are named to match the Bob
brand, but no `@import` or `<link>` fetches them: that would be a network
request. Where they are installed the page uses them; elsewhere it falls back to
Georgia and the system sans.

**The template is a `string.Template`, not an f-string or `.format()`.** CSS and
JavaScript are made of braces, and a `.format()` template needs every one of
them doubled — a rule that silently produced `KeyError` at render time twice
while this file was being built. `$placeholders` do not care about braces.
"""

from __future__ import annotations

import html as _html
import json
from pathlib import Path
from string import Template

from graph_model import GraphData
from render_ring import ring_pane
from timeline import arrival_columns, month_buckets, year_ticks

# The leaderboard card, verbatim -- no dynamic content of its own (the rows
# are built client-side by the page script below from `$board`). Handed to
# ring_pane() so it can sit in the ring's own grid, in normal flow above the
# ring stage, instead of overlapping it as a `.card`-driven absolute overlay.
_BOARD_HTML = ('<div id="board" class="card"><h2>Leaderboard</h2>'
              '<div class="sub">introductions made for you</div><ol></ol></div>')

INK, CREAM, CORAL, AMBER, MUTED = "#111b21", "#fffdfa", "#d65b3c", "#e6a94b", "#667781"
# Red: an introduction made TO you. Green: one YOU made.
# Validated with the dataviz palette checker, not by eye. The first pair tried
# was coral/green — the obvious choice, and a deuteranopia ΔE of 5.7, below even
# the floor that secondary encoding can rescue. Red/green is the classic
# colour-vision collision and it looked fine. This pair scores 19.8.
IN_COLOR, OUT_COLOR = "#c0492f", "#4a7fb5"
SERIF = "'Fraunces','Georgia',serif"
SANS = "'Nunito',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif"

_TEMPLATE = Template("""<!doctype html>
<html><head><meta charset="utf-8"><title>Your introduction network</title>
<style>
  :root { color-scheme: light dark; }
  body { margin:0; font:15px/1.5 $sans; background:$cream; color:$ink; }
  @media (prefers-color-scheme: dark) { body { background:#171513; color:#eee8e2; } }
  header { padding:18px 24px 14px; }
  h1 { margin:0 0 4px; font:600 21px/1.25 $serif; font-style:italic; }
  .sub { color:$muted; font-size:13px; }
  .legend { margin-top:8px; font-size:12px; color:$muted; }
  .key { display:inline-block; width:16px; height:0; border-top:3px solid;
         margin:0 5px 0 14px; vertical-align:middle; }
  .sq { display:inline-block; width:8px; height:8px; background:#a8a29b;
        margin:0 5px 0 14px; vertical-align:middle; }
  .dot { display:inline-block; width:9px; height:9px; border-radius:50%;
         background:$coral; margin-right:5px; vertical-align:middle; }
  #tabs { padding:0 24px; border-bottom:1px solid rgba(128,128,128,.2); }
  .tab { font:inherit; font-size:13px; background:none; border:0; cursor:pointer;
         padding:9px 2px; margin-right:20px; color:$muted;
         border-bottom:2px solid transparent; }
  .tab.on { color:$coral; border-bottom-color:$coral; font-weight:600; }
  .pane { display:none; }
  .pane.on { display:block; }
  .note { margin:14px 24px 4px; font-size:12px; color:$muted; max-width:62em; }
  .dim { color:$muted; }
  #chart { padding:4px 12px 12px; }
  #chart .hit:hover { fill:rgba(214,91,60,.10); }
  #tip { display:none; position:absolute; padding:7px 10px; border-radius:9px;
         background:$ink; color:#fff; font-size:12px; pointer-events:none; }
  #tbl { width:calc(100% - 48px); margin:8px 24px 40px; border-collapse:collapse;
         font-size:13px; }
  #tbl th { text-align:left; font-weight:600; color:$muted; font-size:11px;
            text-transform:uppercase; letter-spacing:.04em; padding:6px 10px;
            border-bottom:1px solid rgba(128,128,128,.25); }
  #tbl td { padding:6px 10px; border-bottom:1px solid rgba(128,128,128,.12);
            vertical-align:top; }
  #tbl .out { color:$muted; }
  #filter { margin:10px 24px 0; }
  #filter .f { font:inherit; font-size:12px; padding:4px 11px; margin-right:7px;
               border:1px solid rgba(128,128,128,.35); border-radius:999px;
               background:none; color:$muted; cursor:pointer; }
  #filter .f.on { background:$coral; border-color:$coral; color:#fff; }
  #strip.only-inbound .mk.outbound,
  #strip.only-outbound .mk.inbound { display:none; }
  #strip { margin:4px 24px 40px; overflow-x:auto; cursor:grab; }
  #strip.drag { cursor:grabbing; }
  #scrub { width:calc(100% - 48px); margin:10px 24px 0; accent-color:$coral; }
  .card { position:absolute; padding:14px 16px; border-radius:16px;
          background:#fff; border:1px solid rgba(17,27,33,.10);
          box-shadow:0 8px 30px rgba(17,27,33,.10); overflow:auto; }
  @media (prefers-color-scheme: dark) { .card { background:#221f1c;
          border-color:rgba(255,255,255,.10); } }
  #board { top:16px; left:20px; width:250px; max-height:calc(76vh - 32px); }
  #board h2 { margin:0; font:600 14px/1.3 $serif; font-style:italic; }
  #board .sub { font-size:11px; margin-bottom:9px; }
  #board ol { margin:0; padding-left:20px; }
  #board li { padding:3px 0; border-radius:6px; }
  #board li:hover { background:rgba(214,91,60,.09); }
  #board li b { float:right; font-weight:600; color:$coral; }
$ring_style
</style></head><body>
<header>
  <h1>$intros introductions &middot; $people people</h1>
  <div class="sub">$span</div>
  <div class="legend"><span class="dot"></span>$sc
    <span class="key" style="border-color:$incolor"></span>introduced you to someone
    <span class="key" style="border-color:$outcolor"></span>an intro you made
    <span class="sq"></span>a service, not a person
  </div>
</header>
<div id="tip"></div>
<nav id="tabs">
  <button class="tab on" data-pane="pane-net">Network</button>
  <button class="tab" data-pane="pane-vol">Volume</button>
  <button class="tab" data-pane="pane-time">Timeline</button>
  <button class="tab" data-pane="pane-roster">The list</button>
  <button class="tab" data-pane="pane-table">Introductions</button>
</nav>
<section id="pane-net" class="pane on">
$ring_markup
</section>
<section id="pane-vol" class="pane">
  <p class="note">$months months, $active with at least one introduction.
     Empty months are shown as gaps &mdash; skipping them would compress the
     time axis and invent a rhythm that is not in the data.</p>
  <svg id="chart" viewBox="0 0 $chartw $charth" width="100%" role="img"
       aria-label="Introductions per month">$bars</svg>
</section>
<section id="pane-time" class="pane">
  <p class="note">Who came into your network, and when. Each mark is a person,
     placed at the month they first arrived &mdash; so this answers who joined
     your world rather than what happened that month. Drag the strip or use the
     scrubber; hover a mark for the name.</p>
  <div id="filter" role="group" aria-label="Which arrivals to show">
    <button class="f on" data-show="all">Everyone</button>
    <button class="f" data-show="inbound">Came into my network</button>
    <button class="f" data-show="outbound">People I introduced</button>
  </div>
  <input id="scrub" type="range" min="0" max="1000" value="1000"
         aria-label="Scrub through time">
  <div id="strip"><svg viewBox="0 0 $stripw $striph" width="$stripw"
       height="$striph" role="img" aria-label="Arrivals over time">$stripsvg</svg></div>
</section>
<section id="pane-roster" class="pane">
  <p class="note">$rosternote</p>
  <table id="rost"><thead><tr><th>Who</th><th>Where</th>
    <th>How you know them</th><th>Last email</th></tr></thead><tbody></tbody></table>
</section>
<section id="pane-table" class="pane">
  <p class="note">Newest first. <b>Outcome</b> is not collected yet &mdash; it
     arrives with the check-in step, which is not built. The column is shown
     empty rather than filled with a guess.</p>
  <table id="tbl"><thead><tr><th>When</th><th>Who introduced</th>
    <th>To whom</th><th>Subject</th><th>Outcome</th></tr></thead><tbody></tbody></table>
</section>
<script>
  // The Network pane's picture (the connector ring and its chain bracket) is
  // its own self-contained IIFE, injected below as a separate script tag
  // after this one, which runs after this script finishes (script tags run
  // in document order) -- so by the time it looks for leaderboard rows to
  // wire up, the rows below already exist.

  const roster = $roster;
  const rbody = document.querySelector('#rost tbody');
  roster.forEach(r => {
    const tr = document.createElement('tr');
    // textContent everywhere: every one of these is mail-derived text.
    const who = document.createElement('td'); who.textContent = r.name;
    const where = document.createElement('td');
    where.textContent = r.where || (r.personal ? 'personal address' : '—');
    if (!r.where) { where.className = 'dim'; }
    const how = document.createElement('td'); how.textContent = r.how || '—';
    const last = document.createElement('td');
    last.textContent = r.last || '—';       // blank means not known, not never
    if (!r.last) { last.className = 'dim'; }
    tr.append(who, where, how, last);
    rbody.append(tr);
  });

  const board = $board;
  const ol = document.querySelector('#board ol');
  board.forEach(r => {
    const li = document.createElement('li');
    li.dataset.id = r.id;                // shared key: lets the ring wire this row to its own node
    const b = document.createElement('b');
    b.textContent = r.n;                 // textContent: names are attacker text
    li.textContent = r.name;
    li.appendChild(b);
    ol.appendChild(li);
  });

  // --- tabs -------------------------------------------------------------
  document.querySelectorAll('.tab').forEach(t => t.onclick = () => {
    document.querySelectorAll('.tab').forEach(x => x.classList.remove('on'));
    document.querySelectorAll('.pane').forEach(x => x.classList.remove('on'));
    t.classList.add('on');
    document.getElementById(t.dataset.pane).classList.add('on');
  });

  // --- chart hover ------------------------------------------------------
  const tip = document.getElementById('tip');
  document.querySelectorAll('#chart .hit').forEach(r => {
    r.onmousemove = ev => {
      const i = +r.dataset.i, o = +r.dataset.o;
      tip.textContent = r.dataset.m + ' — ' + (i + o)
        + (i + o === 1 ? ' introduction' : ' introductions')
        + (i && o ? ' (' + i + ' for you, ' + o + ' you made)'
                  : o ? ' you made' : '');
      tip.style.display = 'block';
      tip.style.left = (ev.pageX + 12) + 'px';
      tip.style.top = (ev.pageY - 34) + 'px';
    };
    r.onmouseleave = () => tip.style.display = 'none';
  });

  // --- arrivals strip: filter, scrubber, drag-to-pan --------------------
  // Two different things were sharing one view: people who came INTO the
  // network, and people the user pushed OUT to someone else. Same marks, and
  // opposite meanings.
  document.querySelectorAll('#filter .f').forEach(b => b.onclick = () => {
    document.querySelectorAll('#filter .f').forEach(x => x.classList.remove('on'));
    b.classList.add('on');
    const st = document.getElementById('strip');
    st.classList.remove('only-inbound', 'only-outbound');
    if (b.dataset.show !== 'all') st.classList.add('only-' + b.dataset.show);
  });

  const strip = document.getElementById('strip');
  const scrub = document.getElementById('scrub');
  const maxScroll = () => Math.max(1, strip.scrollWidth - strip.clientWidth);
  // Start at the present. The most recent arrivals are the ones still worth
  // acting on, and a strip that opens in 2010 looks like an archive.
  requestAnimationFrame(() => { strip.scrollLeft = maxScroll(); });
  scrub.oninput = () => { strip.scrollLeft = (scrub.value / 1000) * maxScroll(); };
  strip.onscroll = () => { scrub.value = (strip.scrollLeft / maxScroll()) * 1000; };
  let down = false, startX = 0, startL = 0;
  strip.onmousedown = e => { down = true; startX = e.pageX; startL = strip.scrollLeft;
                             strip.classList.add('drag'); };
  window.onmouseup = () => { down = false; strip.classList.remove('drag'); };
  window.onmousemove = e => { if (down) strip.scrollLeft = startL - (e.pageX - startX); };

  // --- table ------------------------------------------------------------
  // Every cell written with textContent. These are mail-derived strings and a
  // table built by string concatenation is the same sink the panel already
  // had to be fixed for.
  const tbody = document.querySelector('#tbl tbody');
  $table.forEach(r => {
    const tr = document.createElement('tr');
    const cells = [r.d, r.from, r.to.join(', '), null, '—'];
    cells.forEach((v, i) => {
      const td = document.createElement('td');
      if (i === 3) {
        if (r.u) {
          const a = document.createElement('a');
          a.href = r.u; a.target = '_blank'; a.rel = 'noopener noreferrer';
          a.textContent = r.s || '(no subject)';
          td.appendChild(a);
        } else { td.textContent = r.s || '(no subject)'; }
      } else {
        td.textContent = v;
        if (i === 4) td.className = 'out';
      }
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
</script>
<script>$ring_script</script>
</body></html>
""")


CHART_W, CHART_H, PAD_L, PAD_B = 1180, 230, 34, 26


def _bars(buckets) -> str:
    """Stacked bars as SVG. Geometry is computed here rather than in the
    browser so it can be tested; hover lives in JS over transparent hit rects
    that are wider than the bars, because a 4px target is not clickable."""
    if not buckets:
        return '<text x="20" y="40" fill="#667781">no dated introductions</text>'
    top = max(b["total"] for b in buckets) or 1
    n = len(buckets)
    slot = (CHART_W - PAD_L - 8) / n
    bw = max(1.6, slot - 2)          # 2px surface gap between adjacent bars
    plot = CHART_H - PAD_B
    out = []

    for gy in range(0, top + 1, max(1, -(-top // 4))):
        y = plot - (gy / top) * (plot - 8)
        out.append(f'<line x1="{PAD_L}" y1="{y:.1f}" x2="{CHART_W - 8}" '
                   f'y2="{y:.1f}" stroke="rgba(128,128,128,.16)"/>')
        out.append(f'<text x="{PAD_L - 6}" y="{y + 4:.1f}" text-anchor="end" '
                   f'font-size="10" fill="#667781">{gy}</text>')

    for i, b in enumerate(buckets):
        x = PAD_L + i * slot
        hit = (f'<rect class="hit" x="{x:.1f}" y="0" width="{slot:.1f}" '
               f'height="{plot}" fill="transparent" data-m="{b["month"]}" '
               f'data-i="{b["inbound"]}" data-o="{b["outbound"]}"/>')
        if not b["total"]:
            out.append(hit)
            continue
        y = plot
        for key, color in (("inbound", IN_COLOR), ("outbound", OUT_COLOR)):
            v = b[key]
            if not v:
                continue
            h = (v / top) * (plot - 8)
            y -= h
            out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" '
                       f'height="{h:.1f}" rx="{min(2, bw / 2):.1f}" fill="{color}"/>')
            y -= 2 if b["inbound"] and b["outbound"] else 0
        out.append(hit)

    for t in year_ticks(buckets):
        x = PAD_L + t["i"] * slot
        out.append(f'<text x="{x:.1f}" y="{CHART_H - 8}" font-size="10" '
                   f'fill="#667781">{t["label"]}</text>')
    return "".join(out)


SLOT, DOT, ROW_H, TOP = 26, 4.2, 13, 26


def _strip(columns, label_of, service_ids) -> tuple:
    """The horizontal arrivals strip. Returns (svg, width)."""
    if not columns:
        return '<text x="16" y="30" fill="#667781">no dated arrivals</text>', 400
    tallest = max((len(c["people"]) for c in columns), default=0) or 1
    width = len(columns) * SLOT + 40
    height = TOP + tallest * ROW_H + 30
    out = [f'<line x1="0" y1="{TOP - 10}" x2="{width}" y2="{TOP - 10}" '
           f'stroke="rgba(128,128,128,.25)"/>']

    seen_year = set()
    for i, col in enumerate(columns):
        x = 20 + i * SLOT
        year = col["month"][:4]
        if year not in seen_year:
            seen_year.add(year)
            out.append(f'<line x1="{x}" y1="{TOP - 16}" x2="{x}" y2="{height - 18}" '
                       f'stroke="rgba(128,128,128,.16)"/>')
            out.append(f'<text x="{x + 3}" y="{height - 6}" font-size="10" '
                       f'fill="#667781">{year}</text>')
        for j, person in enumerate(col["people"]):
            cy = TOP + j * ROW_H
            colour = OUT_COLOR if person["direction"] == "outbound" else IN_COLOR
            name = label_of.get(person["person"], person["person"])
            by = label_of.get(person["by"], person["by"])
            tip = _html.escape(f'{name} — {"you introduced them" if person["direction"] == "outbound" else "introduced by " + by} · {col["month"]}')
            if person["person"] in service_ids:
                out.append(f'<rect class="mk {person["direction"]}" '
                           f'x="{x - DOT:.1f}" y="{cy - DOT:.1f}" '
                           f'width="{DOT * 2:.1f}" height="{DOT * 2:.1f}" '
                           f'fill="{colour}"><title>{tip}</title></rect>')
            else:
                out.append(f'<circle class="mk {person["direction"]}" '
                           f'cx="{x:.1f}" cy="{cy:.1f}" r="{DOT}" '
                           f'fill="{colour}"><title>{tip}</title></circle>')
    return "".join(out), width


def _json(obj) -> str:
    """JSON for an inline <script>. `json.dumps` escapes neither `<` nor `/`,
    so mail-derived text could close the script element early.

    Named `_json`, not `_esc`, and deliberately: render_ring.py -- which this
    module imports from -- has an `_esc` that HTML-escapes and a `_json` that
    does this. Two functions with one name and opposite semantics, one import
    apart, meant a line moved between the files would silently swap escaping
    and still run.
    """
    return json.dumps(obj).replace("<", "\\u003c")


# Domains that say nothing about where somebody works. §4.4: a personal address
# carries no affiliation, and that gets said out loud rather than dressed up --
# printing "gmail.com" in a Where column states an employer that does not exist.
PERSONAL_DOMAINS = frozenset({
    "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com",
    "yahoo.com", "ymail.com", "icloud.com", "me.com", "mac.com", "aol.com",
    "protonmail.com", "proton.me", "pm.me", "msn.com", "fastmail.com",
    "hey.com", "gmx.com", "zoho.com", "comcast.net", "sbcglobal.net",
})


_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _month_year(iso: str) -> str:
    """`2019-03-14` -> `Mar 2019`. Anything unparseable comes back empty --
    a malformed date is not a date, and half of one is worse than none."""
    try:
        y, m = int(iso[0:4]), int(iso[5:7])
        return "%s %d" % (_MONTHS[m - 1], y)
    except (ValueError, IndexError):
        return ""


def _roster_rows(graph, people, principal: str, label_of: dict) -> tuple:
    """One row per person: who, where, how you know them, when you last spoke.

    Plugin MVP §4.4. Keyed by ADDRESS, not by human -- 19 people in the real
    corpus write from two or three addresses, and merging them on a display
    name is how two different John Smiths become one person. The merge is a
    review list, not an inference.

    Returns (rows, personal_count).
    """
    principal = (principal or "").lower()
    # Who introduced them, and when. `graph.origins` holds the EARLIEST dated
    # introduction per person, which is how the user came to know them; a later
    # re-introduction is not an origin.
    #
    # This used to walk `graph.chains` with setdefault, and chains iterate
    # sorted by introducer address -- so it kept whoever sorted first
    # alphabetically. That credited `invite@vimcal.com` over the person who
    # actually made the introduction, on two rows, and named the wrong
    # introducer on six of 287. A booking tool always appears *after* the
    # introduction it did not make, so ordering by date routes around it for
    # free.
    origins = getattr(graph, "origins", None) or {}
    connector_of = {who: pair[0] for who, pair in origins.items()}
    when_of = {who: pair[1] for who, pair in origins.items()}
    if not connector_of:
        # A graph built without origins (hand-assembled in a test, or an older
        # caller). Fall back rather than drop the column -- but say plainly
        # that this path cannot order by time.
        for c in getattr(graph, "chains", []) or []:
            connector_of.setdefault(c.introduced, c.introducer)

    rows, personal = [], 0
    for p in people or []:
        if p.address.lower() == principal:
            continue
        domain = p.address.partition("@")[2].lower()
        is_personal = domain in PERSONAL_DOMAINS
        if is_personal:
            personal += 1

        if p.intros_for_you:
            how = "introduced you to %d %s" % (
                p.intros_for_you, "person" if p.intros_for_you == 1 else "people")
        elif p.address in connector_of:
            who = connector_of[p.address]
            how = "%s introduced you" % label_of.get(who, who)
            # §4.4 shows the date beside it -- "Dana Whitford introduced you ·
            # Mar 2019". Only when it is known; never invented.
            # Guard on the FORMATTED value: a raw date is truthy even when it
            # is unparseable, which appended a separator with nothing after it.
            when = _month_year(when_of.get(p.address, ""))
            if when:
                how += " · %s" % when
        else:
            how = ""

        rows.append({
            "name": p.name or p.address,
            "addr": p.address,
            # "" rather than the domain for a personal address: the column is
            # blank because the answer is unknown, not because it is pending.
            "where": "" if is_personal else domain,
            "personal": is_personal,
            "how": how,
            # "" means NOT KNOWN. Bob reads one channel and cannot assert
            # absence (§4.6), so the page prints an em dash, never "never".
            "last": p.last_contact,
        })

    # Sorting is not ranking (§4.4). Oldest contact first, because "who have I
    # lost touch with" is the question -- and people with no known contact sort
    # LAST rather than masquerading as the stalest of all.
    rows.sort(key=lambda r: (r["last"] == "", r["last"], r["name"].lower()))
    return rows, personal


def render(
    graph: GraphData, out_path: Path,
    principal: str = "", people=None, intros=None,
) -> None:
    principal = (principal or "").lower()

    # The principal is in the DATA but not in the PICTURE. Everyone here was
    # introduced to them, so that edge is true of all and informative about
    # none — while a node joined to every other dominates the layout. The edge
    # worth seeing is Dana->Ben: who introduced you to whom.
    hidden = frozenset({principal}) if principal else frozenset()

    # A square among dots reads instantly as "not a person". Hiding them would
    # drop five true introductions from the picture; the edges are real, it is
    # only the impression that needed fixing.
    service_ids = {p.address for p in (people or []) if p.is_service}
    label_of = {n.id: n.label for n in graph.nodes}

    ring_markup, ring_style, ring_script = ring_pane(
        graph, principal=principal, people=people, board_html=_BOARD_HTML)

    board = [{"id": a, "name": label_of.get(a, a.partition("@")[0]), "n": n}
             for a, n in (graph.top_connectors or graph.super_connectors)[:10]
             if a not in hidden]

    rows = list(intros or [])
    buckets = month_buckets(rows)

    def _month_label(key: str) -> str:
        names = ("January", "February", "March", "April", "May", "June", "July",
                 "August", "September", "October", "November", "December")
        return f"{names[int(key[5:7]) - 1]} {key[:4]}"

    columns = arrival_columns(rows, principal)
    strip_svg, strip_w = _strip(columns, label_of, service_ids)
    strip_h = TOP + (max((len(c["people"]) for c in columns), default=1) or 1) * ROW_H + 30
    table = [{
        "d": r.date,
        "from": label_of.get(r.introducer, r.introducer),
        "to": [label_of.get(a, a) for a in r.introduced if a not in hidden],
        "dir": r.direction,
        "s": r.subject,
        # Only a link we generated ourselves. A thread_link is data from a file
        # and a URL is an attribute sink, so anything else is dropped rather
        # than trusted.
        "u": r.thread_link if r.thread_link.startswith("https://mail.google.com/") else "",
    } for r in sorted(rows, key=lambda r: r.date, reverse=True)]

    roster, personal_n = _roster_rows(graph, people, principal, label_of)
    if not roster:
        roster_note = "No roster yet — run `bob scan`."
    elif personal_n:
        roster_note = (
            "%d of %d use a personal address, so I can't tell where they work. "
            "A domain is where someone emailed from, not where they work now."
            % (personal_n, len(roster)))
    else:
        roster_note = ("A domain is where someone emailed from, "
                       "not where they work now.")
    if roster and not any(r["last"] for r in roster):
        roster_note += (" Last contact is blank for everyone — run "
                        "`bob roster` to fill it in.")

    s = graph.stats
    span = (f"{s.first_date} to {s.last_date} · {s.last_12mo} in the last 12 months"
            if s and s.first_date else "no introductions found")
    sc = (f"{len(graph.super_connectors)} people account for half of the "
          f"introductions made for you" if graph.super_connectors else
          "click anyone to see who they introduced you to")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(_TEMPLATE.substitute(
        sans=SANS, serif=SERIF, cream=CREAM, ink=INK, coral=CORAL, muted=MUTED,
        intros=s.intros if s else 0,
        people=(s.people - (1 if principal else 0)) if s else 0,
        span=_html.escape(span), sc=_html.escape(sc),
        incolor=IN_COLOR, outcolor=OUT_COLOR,
        ring_markup=ring_markup, ring_style=ring_style, ring_script=ring_script,
        board=_json(board), roster=_json(roster),
        rosternote=_html.escape(roster_note),
        bars=_bars(buckets), table=_json(table),
        stripsvg=strip_svg, stripw=strip_w, striph=strip_h,
        chartw=CHART_W, charth=CHART_H,
        months=len(buckets),
        active=sum(1 for b in buckets if b["total"]),
    ), encoding="utf-8")
