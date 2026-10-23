// People map: a calm board of who connects to whom.
// Look: Asana's connected-work canvas (dot grid, white shadowed cards, ring avatars, square lines with round bends and end dots,
// the selected path in the accent). Also Cofounder (fade on select), Jira (line labels, popover), Deel (zoom bar), Felt (legend).
(function () {
  "use strict";
  const { esc, ic, $ } = window.C;
  const NS = "http://www.w3.org/2000/svg";
  const EASE = "cubic-bezier(0.2, 0, 0, 1)";
  const reduced = () => !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);

  // Draw a line in along its own path (stroke-dashoffset), from its start or, with `reverse`, from its end.
  // Dashed lines get their 4/5 dash pattern spelled out first, so the dashes stay put as the line grows.
  function draw(path, delay, dur, reverse) {
    const L = path.getTotalLength ? path.getTotalLength() : 0;
    if (!L || !path.animate) return null;
    const arr = [];
    let P = 0;
    if (path.classList.contains("together")) { while (P < L) { if (arr.length) { arr.push(5); P += 5; } arr.push(4); P += 4; } }
    else { arr.push(L + 2); P = L + 2; }
    arr.push(L + 8);
    path.style.strokeDasharray = arr.join(" ");
    const a = path.animate([{ strokeDashoffset: (reverse ? -(L + 2) : P + 2) + "px" }, { strokeDashoffset: "0px" }],
      { duration: dur, delay, easing: "cubic-bezier(0.4, 0, 0.2, 1)", fill: "backwards" });
    a.onfinish = a.oncancel = () => { path.style.strokeDasharray = ""; };
    return a;
  }

  const SIZE = { person: [240, 60], past: [216, 52], you: [256, 44] };
  const FRAME = { w: 276, head: 56, pad: 18, gapY: 14, gapX: 120, colGap: 150 };
  // Narrow in-call panel: smaller cards in two columns, so text stays readable at panel width.
  const SIZE_C = { person: [172, 50], past: [186, 44], you: [128, 38] };
  const FRAME_C = { head: 44, pad: 12, gapY: 10, colGap: 44 };
  let S = SIZE, F = FRAME;

  // One call, stacked: the company frame with its people on the left, whoever each person connects to on the right.
  function stackLayout(graph, callId) {
    const pos = {};
    const co = graph.nodes.find((n) => n.type === "prospect" && n.callId === callId);
    const people = graph.nodes.filter((n) => n.type === "person" && n.company === co.id);
    const keep = new Set(people.map((p) => p.id));
    const xA = S.person[0] / 2, xB = S.person[0] + F.colGap;
    let y = F.head + F.pad, lastB = -Infinity;
    const placeB = (id, wantY) => {
      const s = S[(graph.nodes.find((n) => n.id === id) || {}).type] || S.past, h = s[1];
      const yy = Math.max(wantY, lastB + 22 + h / 2);
      pos[id] = { x: xB + s[0] / 2, y: yy };
      lastB = yy + h / 2;
      keep.add(id);
    };
    // "You" goes on the row of the first person you know, so every line runs straight across.
    people.forEach((p) => {
      const cy = y + S.person[1] / 2;
      pos[p.id] = { x: xA, y: cy };
      graph.edges.forEach((e) => {
        const other = e.a === p.id ? e.b : e.b === p.id ? e.a : null;
        if (!other || keep.has(other)) return;
        placeB(other, cy);
      });
      y += S.person[1] + F.gapY;
    });
    // Companies (and whoever said them) mentioned on this call join the right-hand column too.
    graph.edges.filter((e) => e.callId === callId).forEach((e) => [e.a, e.b].forEach((id) => { if (!keep.has(id)) placeB(id, F.head + F.pad); }));
    const frame = { id: co.id, node: co, members: people.map((p) => p.id) };
    return { pos, frames: [frame], keep };
  }

  function boardLayout(graph) {
    const pos = {};
    const frames = [];
    const prospects = graph.nodes.filter((n) => n.type === "prospect");
    const people = graph.nodes.filter((n) => n.type === "person");
    let x = 0;
    prospects.forEach((co) => {
      const inside = people.filter((p) => p.company === co.id);
      const h = FRAME.head + inside.length * (SIZE.person[1] + FRAME.gapY) - FRAME.gapY + FRAME.pad * 2;
      frames.push({ id: co.id, node: co, x, y: 140, w: FRAME.w, h, members: inside.map((p) => p.id) });
      inside.forEach((p, i) => { pos[p.id] = { x: x + FRAME.pad + SIZE.person[0] / 2, y: 140 + FRAME.head + FRAME.pad + i * (SIZE.person[1] + FRAME.gapY) + SIZE.person[1] / 2 }; });
      x += FRAME.w + FRAME.gapX;
    });
    const width = x - FRAME.gapX;
    const bottom = Math.max(...frames.map((f) => f.y + f.h));
    pos.you = { x: width / 2, y: 40 };
    // Past employers sit under the people who came from them, spread so they never overlap.
    const pasts = graph.nodes.filter((n) => n.type === "past").map((n) => {
      const linked = graph.edges.filter((e) => (e.a === n.id || e.b === n.id) && (pos[e.a] || pos[e.b]) && e.a !== "you" && e.b !== "you")
        .map((e) => pos[e.a === n.id ? e.b : e.a]).filter(Boolean);
      return { n, x: linked.length ? linked.reduce((s, p) => s + p.x, 0) / linked.length : width / 2 };
    }).sort((a, b) => a.x - b.x);
    const minGap = SIZE.past[0] + 40;
    pasts.forEach((p, i) => { if (i && p.x - pasts[i - 1].x < minGap) p.x = pasts[i - 1].x + minGap; });
    pasts.forEach((p) => { pos[p.n.id] = { x: p.x, y: bottom + 130 }; });
    return { pos, frames };
  }

  function boxOf(n, p) {
    const s = S[n.type] || S.past;
    return { x: p.x - s[0] / 2, y: p.y - s[1] / 2, w: s[0], h: s[1], cx: p.x, cy: p.y };
  }
  // Square lines with round bends (Asana): tidy the corner points, then round each corner.
  function clean(pts) {
    const out = [];
    pts.forEach((p) => { const q = out[out.length - 1]; if (!q || Math.abs(q.x - p.x) > 0.5 || Math.abs(q.y - p.y) > 0.5) out.push({ x: p.x, y: p.y }); });
    for (let i = out.length - 2; i > 0; i--) {
      const a = out[i - 1], b = out[i], c = out[i + 1];
      if ((Math.abs(a.x - b.x) < 0.5 && Math.abs(b.x - c.x) < 0.5) || (Math.abs(a.y - b.y) < 0.5 && Math.abs(b.y - c.y) < 0.5)) out.splice(i, 1);
    }
    return out;
  }
  function roundPath(raw, R) {
    const pts = clean(raw);
    let d = "M" + pts[0].x + " " + pts[0].y, best = -1, mid = pts[0];
    for (let i = 1; i < pts.length; i++) {
      const a = pts[i - 1], b = pts[i], len = Math.hypot(b.x - a.x, b.y - a.y);
      if (len > best) { best = len; mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }; }
      if (i === pts.length - 1) { d += " L" + b.x + " " + b.y; break; }
      const c = pts[i + 1], len2 = Math.hypot(c.x - b.x, c.y - b.y);
      const r = Math.min(R, len / 2, len2 / 2);
      d += " L" + (b.x - ((b.x - a.x) / len) * r) + " " + (b.y - ((b.y - a.y) / len) * r)
        + " Q" + b.x + " " + b.y + " " + (b.x + ((c.x - b.x) / len2) * r) + " " + (b.y + ((c.y - b.y) / len2) * r);
    }
    return { d, mid, ends: [pts[0], pts[pts.length - 1]] };
  }
  // Two side exits: meet in the middle if they face each other, else loop round the outside.
  function sideRoute(A, B, lane) {
    if (A.nx === -B.nx && A.nx * (B.x - A.x) > 0) { const mx = (A.x + B.x) / 2 + (lane || 0); return [A, { x: mx, y: A.y }, { x: mx, y: B.y }, B]; }
    const x = A.nx > 0 ? Math.max(A.x, B.x) + 28 : Math.min(A.x, B.x) - 28;
    return [A, { x, y: A.y }, { x, y: B.y }, B];
  }
  // Avatars, company tiles and tag colours come from core.js (C.avatar, C.coTile, C.tagFor), so the board matches the lists.

  const KIND_LABEL = { warm: "Warm: helps you", moved: "Past job or past talk", together: "Worked together", mentioned: "Mentioned on a call" };

  function mount(root, opts) {
    opts = Object.assign({ mode: "board", callId: null, compact: false, onOpenCall: null, onRemove: null }, opts || {});
    const graph = window.C.relationshipGraph();
    const byId = Object.fromEntries(graph.nodes.map((n) => [n.id, n]));
    S = opts.compact ? SIZE_C : SIZE;
    F = opts.compact ? FRAME_C : FRAME;
    const lay = opts.mode === "stack" ? stackLayout(graph, opts.callId) : boardLayout(graph);
    let selected = null;
    // Motion state: what the last render showed, which card the pointer or keyboard is on.
    let shownSel = null, firstRender = true, hoverId = null, ptrHover = null, keyHover = null, easeT = 0;
    const view = { x: 0, y: 0, k: 1 };

    root.classList.add("board");
    if (opts.compact) root.classList.add("compact");
    root.innerHTML = '<div class="board-viewport" tabindex="-1"><div class="world"><svg class="edges" aria-hidden="true"></svg><div class="nodes"></div></div></div>'
      + '<div class="board-zoom" role="group" aria-label="Zoom">'
      + '<button type="button" class="icon-btn" data-z="out" aria-label="Zoom out">' + ic("minus") + "</button>"
      + '<span class="zoom-val" aria-live="off">100%</span>'
      + '<button type="button" class="icon-btn" data-z="in" aria-label="Zoom in">' + ic("plus") + "</button>"
      + '<button type="button" class="icon-btn" data-z="fit" aria-label="Fit to screen">' + ic("fit") + "</button></div>"
      + (opts.compact ? "" : '<div class="board-legend" aria-label="Legend">'
        + '<p><span class="lk warm"></span>Warm: helps you</p><p><span class="lk moved"></span>Past job or past talk</p><p><span class="lk together"></span>Worked together</p>'
        + '<p><span class="lk mentioned"></span>Mentioned on a call</p>'
        + '<p class="legend-src"><span class="src public">Public</span>' + (window.C.MODE === "demo" ? '<span class="src sample">Sample</span>' : '<span class="src yours">Yours</span>') + "</p></div>")
      + '<div class="board-focus" hidden><span></span><button type="button" class="link-btn" data-clear>Clear</button></div>'
      + '<div class="edge-pop" role="dialog" aria-label="Relationship" hidden></div>';
    const vp = $(".board-viewport", root), world = $(".world", root), svg = $(".edges", root), nodesEl = $(".nodes", root);

    const visible = (id) => !lay.keep || lay.keep.has(id);
    const shown = graph.nodes.filter((n) => visible(n.id) && lay.pos[n.id]);
    const shownEdges = graph.edges.filter((e) => visible(e.a) && visible(e.b) && lay.pos[e.a] && lay.pos[e.b]);

    function nodeHtml(n) {
      const p = lay.pos[n.id], b = boxOf(n, p);
      const style = 'style="left:' + b.x + "px;top:" + b.y + "px;width:" + b.w + "px;min-height:" + b.h + 'px"';
      const links = graph.edges.filter((e) => e.a === n.id || e.b === n.id).length;
      const label = n.label + (n.sub ? ", " + n.sub : "") + (n.status ? ", " + n.status : "") + ". " + links + " links.";
      if (n.type === "person") {
        return '<button type="button" class="node person' + (n.mentioned ? " mentioned" : "") + '" data-id="' + esc(n.id) + '" ' + style + ' aria-label="' + esc(label) + '" title="' + esc(n.label + (n.sub ? ' · ' + n.sub : '')) + '">'
          + window.C.avatar({ name: n.label, email: n.id.slice(2) }) + '<span class="node-text"><span class="node-name">' + esc(n.label) + '</span><span class="node-sub">' + esc(n.sub) + "</span></span></button>";
      }
      if (n.type === "you") return '<button type="button" class="node you" data-id="you" ' + style + ' aria-label="' + esc("You (" + n.sub + ")") + '" title="' + esc("You · " + n.sub) + '">' + '<span class="avatar you-av" aria-hidden="true"><span class="avatar-ini">' + esc(window.C.ME.initial) + '</span></span><span class="node-text"><span class="node-name">You</span><span class="node-sub">' + esc(n.sub) + "</span></span>" + (opts.compact ? "" : '<span class="you-tag">Your network</span>') + '</button>';
      const tile = window.C.coTile(n.label, "co-tile");
      return '<button type="button" class="node past' + (n.src === "pub" ? " pub" : "") + (n.mentioned ? " mentioned" : "") + '" data-id="' + esc(n.id) + '" ' + style + ' aria-label="' + esc(label) + '" title="' + esc(n.label + (n.sub ? ' · ' + n.sub : '')) + '">' + tile
        + '<span class="node-text"><span class="node-name">' + esc(n.label) + '</span><span class="node-sub"><span class="src ' + (n.src === "pub" ? "public" : window.C.MODE === "demo" ? "sample" : "yours") + '">' + esc(n.status || "Past employer") + "</span></span></span></button>";
    }

    function frameHtml(f) {
      const n = f.node;
      return '<div class="frame" data-frame="' + esc(f.id) + '" style="left:' + f.x + "px;top:" + f.y + "px;width:" + f.w + "px;height:" + f.h + 'px">'
        + '<button type="button" class="frame-head" data-id="' + esc(n.id) + '" aria-label="' + esc(n.label + ", " + (n.status || "") + ", " + f.members.length + " people") + '">'
        + window.C.coTile(n.label, "co-tile") + '<span class="frame-name">' + esc(n.label) + "</span>"
        + (n.status ? '<span class="frame-chip ' + window.C.tagFor("status", n.status) + '">' + esc(n.status) + "</span>" : "") + "</button></div>";
    }

    const frameOf = Object.fromEntries(lay.frames.flatMap((f) => f.members.map((m) => [m, f])));
    // Board routing: people leave their card from the side into the gutter between company frames;
    // "You" (above) and past employers (below) join through a channel just above or below the frames.
    function router() {
      const sideAnchor = (b, toX) => (toX < b.cx - 2 ? { x: b.x, y: b.cy, nx: -1 } : { x: b.x + b.w, y: b.cy, nx: 1 });
      if (opts.mode === "stack") {
        // Each right-hand card gets its own vertical lane, so lines run side by side instead of on top of each other.
        const right = shown.filter((n) => !frameOf[n.id]).sort((a, b) => lay.pos[a.id].y - lay.pos[b.id].y).map((n) => n.id);
        const lane = (id) => (right.indexOf(id) - (right.length - 1) / 2) * (opts.compact ? 6 : 10);
        return (e) => {
          const A = boxOf(byId[e.a], lay.pos[e.a]), B = boxOf(byId[e.b], lay.pos[e.b]);
          const same = Math.abs(A.cx - B.cx) < 4;
          return sideRoute(same ? { x: A.x + A.w, y: A.cy, nx: 1 } : sideAnchor(A, B.cx), same ? { x: B.x + B.w, y: B.cy, nx: 1 } : sideAnchor(B, A.cx), lane(frameOf[e.a] ? e.b : e.a));
        };
      }
      const fs = lay.frames.slice().sort((a, b) => a.x - b.x), GUT = 30;
      const top = Math.min(...fs.map((f) => f.y)), bottom = Math.max(...fs.map((f) => f.y + f.h));
      const yT = top - 36, yB = bottom + 36;
      const gutters = fs.map((f, i) => (i ? (fs[i - 1].x + fs[i - 1].w + f.x) / 2 : f.x - GUT)).concat([fs[fs.length - 1].x + fs[fs.length - 1].w + GUT]);
      const port = (id, other) => {
        const b = boxOf(byId[id], lay.pos[id]), f = frameOf[id];
        if (f) {
          const right = other.cx >= f.x + f.w / 2, i = fs.indexOf(f) + (right ? 1 : 0);
          return { a: { x: right ? b.x + b.w : b.x, y: b.cy }, p: { x: gutters[i], y: b.cy }, k: "g" };
        }
        if (b.cy < top) return { a: { x: b.cx, y: b.y + b.h }, p: { x: b.cx, y: yT }, k: "t" };
        return { a: { x: b.cx, y: b.y }, p: { x: b.cx, y: yB }, k: "b" };
      };
      const link = (P, kp, Q, kq) => {
        if (kp === kq) return kp === "g" && P.x !== Q.x ? [P, { x: P.x, y: yB }, { x: Q.x, y: yB }, Q] : [P, Q];
        if (kp === "g") return [P, { x: P.x, y: kq === "t" ? yT : yB }, Q];
        if (kq === "g") return [P, { x: Q.x, y: kp === "t" ? yT : yB }, Q];
        const want = (P.x + Q.x) / 2, gx = gutters.reduce((g, x) => (Math.abs(x - want) < Math.abs(g - want) ? x : g), gutters[0]);
        return [P, { x: gx, y: P.y }, { x: gx, y: Q.y }, Q];
      };
      return (e) => {
        const A = boxOf(byId[e.a], lay.pos[e.a]), B = boxOf(byId[e.b], lay.pos[e.b]);
        const pa = port(e.a, B), pb = port(e.b, A);
        return [pa.a].concat(link(pa.p, pa.k, pb.p, pb.k), [pb.a]);
      };
    }

    function render() {
      lay.frames.forEach((f) => {
        // Frames grow to fit their people wherever they were dragged.
        const boxes = f.members.map((id) => boxOf(byId[id], lay.pos[id]));
        const minX = Math.min(...boxes.map((b) => b.x)) - F.pad, maxX = Math.max(...boxes.map((b) => b.x + b.w)) + F.pad;
        const minY = Math.min(...boxes.map((b) => b.y)) - F.pad - F.head, maxY = Math.max(...boxes.map((b) => b.y + b.h)) + F.pad;
        Object.assign(f, { x: minX, y: minY, w: maxX - minX, h: maxY - minY });
      });
      // A selection change animates (fades, ring, label pop, accent line drawing out); drags and first paint do not.
      const prevSel = shownSel, animSel = selected !== shownSel && !firstRender && !reduced();
      const changed = selected !== shownSel;
      shownSel = selected;
      const litFor = (sel) => (sel ? new Set([sel, ...graph.edges.filter((e) => e.a === sel || e.b === sel).map((e) => (e.a === sel ? e.b : e.a))]) : null);
      const lit = litFor(selected), prevLit = litFor(prevSel);
      const edgeOn = (e) => !selected || e.a === selected || e.b === selected;
      const wasOn = (e) => !prevSel || e.a === prevSel || e.b === prevSel;
      const route = router();
      const paths = [], dots = [], labels = [];
      // Labels show only for the selected card, so the board stays quiet.
      const showLabels = !opts.compact && selected;
      shownEdges.forEach((e, i) => {
        const c = roundPath(route(e), opts.compact ? 10 : 14);
        const on = edgeOn(e), cls = (on ? "" : " dim") + (selected && on ? " lit" : "");
        const fade = animSel && on !== wasOn(e) ? (on ? " fade-in" : " fade-out") : "";
        // While the accent line draws out of the selected card, the grey line stays underneath it.
        if (animSel && selected && on) paths.push('<path class="edge ' + e.kind + '" d="' + c.d + '"/>');
        paths.push('<path class="edge ' + e.kind + cls + fade + '" data-e="' + i + '" d="' + c.d + '"/>');
        c.ends.forEach((p) => dots.push('<circle class="edot' + cls + fade + (animSel && selected && on ? " pop" : "") + '" data-e="' + i + '" cx="' + p.x + '" cy="' + p.y + '" r="' + (opts.compact ? 3 : 3.5) + '"/>'));
        if (e.label && showLabels && on) labels.push({ i, e, x: c.mid.x, y: c.mid.y });
      });
      // Nudge labels that would sit on top of each other.
      labels.sort((a, b) => a.y - b.y || a.x - b.x).forEach((l, k, arr) => {
        for (let j = 0; j < k; j++) if (Math.abs(arr[j].x - l.x) < 130 && Math.abs(arr[j].y - l.y) < 28) l.y = arr[j].y + 28;
      });
      // Lit lines draw last so the selected path sits on top.
      const xs = shown.map((n) => lay.pos[n.id].x), x0 = Math.min(...xs) - 200, x1 = Math.max(...xs) + 200;
      const grad = '<defs><linearGradient id="mapGrad" gradientUnits="userSpaceOnUse" x1="' + x0 + '" y1="0" x2="' + x1 + '" y2="0"><stop offset="0" stop-color="#1ed760"/><stop offset="0.55" stop-color="#d05cc0"/><stop offset="1" stop-color="#1fdf64"/></linearGradient></defs>';
      svg.innerHTML = grad + paths.filter((x) => !x.includes(" lit")).concat(paths.filter((x) => x.includes(" lit"))).join("") + dots.join("");
      nodesEl.innerHTML = lay.frames.map(frameHtml).join("")
        + labels.map((l, k) => '<button type="button" class="edge-label ' + l.e.kind + (animSel ? " pop" : "") + '" data-edge="' + l.i + '" style="left:' + l.x + "px;top:" + l.y + "px;--i:" + k + '">' + esc(l.e.label) + "</button>").join("")
        + shown.map(nodeHtml).join("");
      nodesEl.querySelectorAll(".node, .frame").forEach((el) => {
        const id = el.dataset.id || el.dataset.frame;
        const dimBy = (L) => !!(L && !L.has(id) && !(el.classList.contains("frame") && byId[id] && [...L].some((x) => byId[x] && byId[x].company === id)));
        const dim = dimBy(lit);
        el.classList.toggle("dim", dim);
        el.classList.toggle("selected", id === selected);
        if (animSel && dim !== dimBy(prevLit)) el.classList.add(dim ? "to-dim" : "to-lit");
        if (animSel && id === selected) el.classList.add("sel-pop");
      });
      nodesEl.querySelectorAll(".edge-label").forEach((el) => { el.edge = shownEdges[+el.dataset.edge]; });
      const focus = $(".board-focus", root);
      focus.hidden = !selected;
      if (selected) $("span", focus).textContent = "Showing " + byId[selected].label + "'s links";
      // Only tell the side panel when the selection changes, so dragging a card does not rebuild (and re-announce) it.
      if (opts.onSelect && (changed || firstRender)) opts.onSelect(selected ? details(selected) : null);
      if (firstRender) { firstRender = false; if (!opts.compact && !reduced()) intro(); }
      else if (animSel && selected) {
        svg.querySelectorAll(".edge.lit[data-e]").forEach((p) => draw(p, 0, 420, shownEdges[+p.dataset.e].b === selected));
      }
      paintHover();
    }

    // First paint, once per board: cards rise in row by row from the top, then each line draws from the card that
    // arrived first to the other, and its end dots land as the line reaches them.
    function intro() {
      const at = {};
      const items = lay.frames.map((f) => ({ id: f.id, x: f.x, y: f.y, el: nodesEl.querySelector('.frame[data-frame="' + CSS.escape(f.id) + '"]') }))
        .concat(shown.map((n) => ({ id: n.id, x: lay.pos[n.id].x, y: lay.pos[n.id].y, el: nodesEl.querySelector('.node[data-id="' + CSS.escape(n.id) + '"]') })));
      items.sort((a, b) => a.y - b.y || a.x - b.x).forEach((it, k) => {
        const t = Math.min(k * 40, 560);
        at[it.id] = t;
        if (it.el && it.el.animate) it.el.animate([{ opacity: 0, transform: "translateY(8px) scale(0.97)" }, { opacity: 1, transform: "none" }],
          { duration: 440, delay: t, easing: EASE, fill: "backwards" });
      });
      const DUR = 560;
      svg.querySelectorAll(".edge[data-e]").forEach((p) => {
        const i = +p.dataset.e, e = shownEdges[i], ta = at[e.a] || 0, tb = at[e.b] || 0;
        const start = Math.max(ta, tb) + 160, back = tb < ta;
        draw(p, start, DUR, back);
        svg.querySelectorAll('.edot[data-e="' + i + '"]').forEach((d, j) => {
          const first = back ? j === 1 : j === 0;
          if (d.animate) d.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 180, delay: first ? start : start + DUR - 80, easing: "ease-out", fill: "backwards" });
        });
      });
    }

    // Hover (or keyboard focus) on a card: its lines darken and a small dot travels along each one, away from the card,
    // for as long as the card stays hovered. Nothing moves at rest.
    function paintHover() {
      svg.querySelectorAll(".flows").forEach((g) => g.remove());
      svg.querySelectorAll(".edge.hot").forEach((p) => p.classList.remove("hot"));
      nodesEl.querySelectorAll(".node.hovering").forEach((n) => n.classList.remove("hovering"));
      if (!hoverId || root.classList.contains("dragging")) return;
      const card = nodesEl.querySelector('.node[data-id="' + CSS.escape(hoverId) + '"]');
      if (card) card.classList.add("hovering");
      const g = document.createElementNS(NS, "g");
      g.setAttribute("class", "flows");
      g.setAttribute("transform", "translate(3000 3000)");
      const firstDot = svg.querySelector(".edot");
      svg.querySelectorAll(".edge[data-e]").forEach((p) => {
        const e = shownEdges[+p.dataset.e];
        if (e.a !== hoverId && e.b !== hoverId) return;
        p.classList.add("hot");
        svg.insertBefore(p, firstDot); // lines in use sit on top of the rest
        if (reduced()) return;
        const dur = Math.max(1.1, Math.min(2.6, p.getTotalLength() / 170)).toFixed(2) + "s";
        const dot = document.createElementNS(NS, "circle");
        dot.setAttribute("class", "flow");
        dot.setAttribute("r", opts.compact ? "2.5" : "3");
        const m = document.createElementNS(NS, "animateMotion");
        [["path", p.getAttribute("d")], ["dur", dur], ["repeatCount", "indefinite"], ["calcMode", "linear"],
          ["keyPoints", e.b === hoverId ? "1;0" : "0;1"], ["keyTimes", "0;1"], ["begin", "indefinite"]].forEach(([k, v]) => m.setAttribute(k, v));
        const o = document.createElementNS(NS, "animate");
        [["attributeName", "opacity"], ["values", "0;1;1;0"], ["keyTimes", "0;0.12;0.82;1"], ["dur", dur], ["repeatCount", "indefinite"], ["begin", "indefinite"]].forEach(([k, v]) => o.setAttribute(k, v));
        dot.appendChild(m);
        dot.appendChild(o);
        g.appendChild(dot);
      });
      if (!g.firstChild) return;
      svg.appendChild(g);
      g.querySelectorAll("animateMotion, animate").forEach((a) => { try { a.beginElement(); } catch (_) { /* SMIL missing: the line still lights */ } });
    }
    // Whichever moved last, the pointer or the keyboard, decides which card previews its lines.
    let keyLast = false;
    function syncHover() {
      const id = keyLast ? keyHover || ptrHover : ptrHover || keyHover;
      if (id !== hoverId) { hoverId = id; paintHover(); }
    }

    // Everything the side panel needs to explain one node in plain words.
    function details(id) {
      const n = byId[id];
      const rels = graph.edges.filter((e) => e.a === id || e.b === id).map((e) => {
        const other = byId[e.a === id ? e.b : e.a];
        return { other: other.label, otherId: other.id, kind: e.kind, label: e.label, why: e.why || "", src: e.src,
          connId: e.connId || "", mentionId: e.mentionId || "", callId: e.callId || "", sources: e.sources || [],
          explain: e.kind === "mentioned" ? window.C.explainFor(e) : null };
      });
      if (n.type === "person") rels.unshift({ other: byId[n.company].label, otherId: n.company, kind: "works", label: "works at", why: n.label + " is " + n.sub + " at " + byId[n.company].label + ".", src: "sample" });
      return { node: n, rels, callId: n.callId || (n.company && byId[n.company].callId) || null };
    }

    function apply() {
      world.style.transform = "translate(" + view.x + "px," + view.y + "px) scale(" + view.k + ")";
      const zv = $(".zoom-val", root);
      if (zv) zv.textContent = Math.round(view.k * 100) + "%"; // gone when the board was destroyed before a queued fit ran
    }
    function fit() {
      const xs = [], ys = [];
      shown.forEach((n) => { const b = boxOf(n, lay.pos[n.id]); xs.push(b.x, b.x + b.w); ys.push(b.y, b.y + b.h); });
      lay.frames.forEach((f) => { xs.push(f.x, f.x + f.w); ys.push(f.y, f.y + f.h); });
      const pad = opts.compact ? 12 : 40;
      const minX = Math.min(...xs) - pad, maxX = Math.max(...xs) + pad, minY = Math.min(...ys) - pad, maxY = Math.max(...ys) + pad;
      // Keep the floating zoom bar (bottom) clear of the content.
      const bar = opts.compact ? 44 : 64, head = opts.compact ? 0 : 44;
      const W = vp.clientWidth || 800, H = Math.max(120, (vp.clientHeight || 500) - bar - head);
      view.k = Math.max(0.35, Math.min(1.1, Math.min(W / (maxX - minX), H / (maxY - minY))));
      view.x = (W - (maxX - minX) * view.k) / 2 - minX * view.k;
      view.y = head + (H - (maxY - minY) * view.k) / 2 - minY * view.k;
      apply();
    }
    // The zoom bar's buttons glide to the new view; wheel, pinch and drag stay direct.
    function easeNext() {
      if (reduced()) return;
      root.classList.add("easing");
      clearTimeout(easeT);
      easeT = setTimeout(() => root.classList.remove("easing"), 380);
    }
    function zoomAt(f, cx, cy) {
      const k = Math.max(0.3, Math.min(2.2, view.k * f));
      view.x = cx - ((cx - view.x) * k) / view.k;
      view.y = cy - ((cy - view.y) * k) / view.k;
      view.k = k;
      apply();
    }

    function select(id) {
      selected = id && id !== selected ? id : id === selected ? null : null;
      $(".edge-pop", root).hidden = true;
      render();
    }

    // ----- pointer: pan the canvas, drag nodes and frames, click to select -----
    let drag = null;
    vp.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      root.classList.remove("easing");
      const nodeEl = e.target.closest(".node"), frameEl = e.target.closest(".frame-head");
      const r = vp.getBoundingClientRect();
      drag = { sx: e.clientX, sy: e.clientY, moved: false, vx: view.x, vy: view.y, rect: r,
        id: nodeEl ? nodeEl.dataset.id : null, frame: frameEl ? frameEl.closest(".frame").dataset.frame : null, start: {} };
      if (drag.id) drag.start[drag.id] = Object.assign({}, lay.pos[drag.id]);
      if (drag.frame) lay.frames.find((f) => f.id === drag.frame).members.forEach((m) => { drag.start[m] = Object.assign({}, lay.pos[m]); });
      if (!drag.id && !drag.frame && e.target.closest(".edge-label, .board-zoom, .board-legend, .board-focus, .edge-pop")) { drag = null; return; }
      vp.setPointerCapture(e.pointerId);
    });
    vp.addEventListener("pointermove", (e) => {
      if (!drag) return;
      const dx = e.clientX - drag.sx, dy = e.clientY - drag.sy;
      if (!drag.moved && Math.hypot(dx, dy) < 4) return;
      drag.moved = true;
      root.classList.add("dragging");
      const ids = Object.keys(drag.start);
      if (ids.length) {
        ids.forEach((id) => { lay.pos[id] = { x: drag.start[id].x + dx / view.k, y: drag.start[id].y + dy / view.k, a: drag.start[id].a }; });
        render();
      } else { view.x = drag.vx + dx; view.y = drag.vy + dy; apply(); }
    });
    // Two clicks on the same person card without moving it: open their past-to-present timeline (opts.onOpen), and keep it
    // selected instead of the second click unselecting it. A drag in between never counts.
    let lastTap = {};
    vp.addEventListener("pointerup", (e) => {
      if (!drag) return;
      const d = drag; drag = null;
      root.classList.remove("dragging");
      if (d.moved) { lastTap = {}; paintHover(); return; }
      if (d.id && opts.onOpen && d.id.startsWith("p:") && lastTap.id === d.id && e.timeStamp - lastTap.t < 500) { lastTap = {}; opts.onOpen(d.id.slice(2)); return; }
      lastTap = { id: d.id, t: e.timeStamp };
      if (d.id) select(d.id);
      else if (d.frame) select(d.frame);
      else if (!e.target.closest(".edge-label")) { selected = null; $(".edge-pop", root).hidden = true; render(); }
    });
    vp.addEventListener("pointerover", (e) => {
      if (e.pointerType === "touch") return;
      const n = e.target.closest(".node");
      ptrHover = n ? n.dataset.id : null;
      keyLast = false;
      syncHover();
    });
    vp.addEventListener("pointerleave", () => { ptrHover = null; syncHover(); });
    // Keyboard users get the same preview of a card's lines while it has focus.
    root.addEventListener("focusin", (e) => {
      const n = e.target.closest(".node");
      if (n && n.matches(":focus-visible")) { keyHover = n.dataset.id; keyLast = true; syncHover(); }
    });
    root.addEventListener("focusout", (e) => { if (e.target.closest(".node")) { keyHover = null; syncHover(); } });
    vp.addEventListener("wheel", (e) => {
      e.preventDefault();
      root.classList.remove("easing");
      const r = vp.getBoundingClientRect();
      if (e.ctrlKey || e.metaKey) zoomAt(Math.exp(-e.deltaY / 300), e.clientX - r.left, e.clientY - r.top);
      else { view.x -= e.deltaX; view.y -= e.deltaY; apply(); }
    }, { passive: false });
    // Keyboard: nodes are buttons, so Enter/Space select them.
    root.addEventListener("click", (e) => {
      const z = e.target.closest("[data-z]");
      if (z) { easeNext(); const W = vp.clientWidth / 2, H = vp.clientHeight / 2; if (z.dataset.z === "fit") fit(); else zoomAt(z.dataset.z === "in" ? 1.2 : 1 / 1.2, W, H); return; }
      if (e.target.closest("[data-clear]")) { select(null); return; }
      const rm = e.target.closest("[data-remove-conn]");
      if (rm) { const ed = $(".edge-pop", root).edge; $(".edge-pop", root).hidden = true; if (ed && opts.onRemove) opts.onRemove(ed); return; }
      const lab = e.target.closest(".edge-label");
      if (lab && lab.edge) {
        const ed = lab.edge, pop = $(".edge-pop", root), xp = ed.kind === "mentioned" ? window.C.explainFor(ed) : null;
        // A line found on the web or said on a call explains itself: what it is, the sources and quotes, where it came up.
        pop.classList.toggle("xp-pop", !!xp);
        pop.innerHTML = '<p class="pop-ends"><strong>' + esc(byId[ed.a].label) + "</strong> · " + esc(ed.label) + " · <strong>" + esc(byId[ed.b].label) + "</strong></p>"
          + (xp ? window.C.explainHtml(xp) : (ed.why ? "<p>" + esc(ed.why) + "</p>" : "")
            + ((ed.sources || []).length ? '<p class="pop-src">' + ed.sources.map((s) => { const h = window.C.safeHref(s.url); return h ? '<a href="' + esc(h) + '" target="_blank" rel="noopener noreferrer">' + esc(s.label || new URL(h).hostname) + window.C.NEW_TAB + "</a>" : ""; }).join(" · ") + "</p>" : "")
            + '<p class="src ' + (ed.src === "pub" ? "public" : window.C.MODE === "demo" ? "sample" : "yours") + '">' + (ed.src === "pub" ? "Public data" : ed.kind === "mentioned" ? esc(window.C.MODE === "demo" ? "Sample data" : ed.source || "Said on the call") : esc(window.C.SRC.records)) + "</p>")
          + (ed.kind === "mentioned" && ed.mentionId && opts.onRemove ? '<p><button type="button" class="link-btn" data-remove-conn>Remove this connection</button></p>' : "");
        pop.edge = ed;
        const r = lab.getBoundingClientRect(), rr = root.getBoundingClientRect();
        pop.style.left = Math.min(rr.width - 300, Math.max(12, r.left - rr.left - 120)) + "px";
        pop.style.top = (r.bottom - rr.top + 8) + "px";
        pop.hidden = false;
        // A tall card (an explanation with its sources) moves up so it stays inside the board; it scrolls if it is taller still.
        const ph = pop.offsetHeight;
        if (r.bottom - rr.top + 8 + ph > rr.height - 12) pop.style.top = Math.max(12, rr.height - 12 - ph) + "px";
        return;
      }
      if (e.detail === 0) { // keyboard activation of a node
        const n = e.target.closest(".node, .frame-head");
        if (n) {
          const id = n.dataset.id;
          select(id);
          const again = root.querySelector('[data-id="' + CSS.escape(id) + '"]');
          if (again) again.focus();
        }
      }
    });
    root.addEventListener("keydown", (e) => { if (e.key === "Escape") { select(null); } });

    render();
    requestAnimationFrame(fit);
    const ro = new ResizeObserver(() => fit());
    ro.observe(vp);
    return { fit, select, destroy() { ro.disconnect(); root.innerHTML = ""; }, details };
  }

  window.CMap = { mount, KIND_LABEL };
})();
