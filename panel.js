// Overture in-call panel: one document that runs as a Google Meet add-on side panel, a Zoom App, or a plain preview.
// Mobbin references: Google Meet side panels, Zoom AI Companion (docked panel), Dialpad and Fireflies live assist,
// Tana talking points, Lightfield joined-check participants, Unify "Key questions", Hotjar quick notes, Apollo insights
// tabs, Otter AI chat tabs (full list with links at the top of live.css and panel.css).
// SDK facts were checked against Google's Meet add-ons docs and Zoom's Apps SDK docs (see docs/IN-CALL.md).
(function () {
  "use strict";
  const { D, $, $$, esc, ic, plural, splitWhen, fmtDate, store, tenure, avatar, tagFor, coTile } = window.C;
  const CFG = window.CENTRALIZE_CONFIG || {};
  const qs = new URLSearchParams(location.search);
  // Meet first: Zoom's SDK assumes any iframe is the Zoom web client and would just wait inside Meet.
  // host=ext: Overture's Chrome extension side panel, which passes the tab's Meet code (meet=) or Zoom meeting number (zoom=).
  const HOST = qs.has("meet_sdk") ? "meet" : qs.get("host") === "ext" ? "ext" : (qs.get("host") === "zoom" || /ZoomApps/i.test(navigator.userAgent)) ? "zoom" : "preview";
  const SKIN = qs.get("skin") || (HOST === "zoom" || (HOST === "ext" && qs.has("zoom")) ? "zoom" : "meet");
  // Inside a host (Meet, Zoom, Chrome's side panel, or the mock call on the app's In-call page) the host's frame already shows Overture's logo and name.
  const FRAMED = HOST !== "preview" || qs.get("host") === "panel";
  const HOST_NAME = (HOST === "zoom" || SKIN === "zoom") ? "Zoom" : "Google Meet";
  // The call for the extension's meeting code: Meet codes come as "abc-defg-hij" (any case, dashes or not), Zoom as digits.
  const codeKey = (c) => String(c || "").toLowerCase().replace(/[^a-z0-9]/g, "");
  function extMatch() {
    const meet = codeKey(qs.get("meet")), zoom = String(qs.get("zoom") || "").replace(/\D/g, "");
    // a recurring meeting reuses its code: take the occurrence closest to now (today's, even once it runs late)
    const nearest = (list) => list.sort((a, b) => Math.abs(Date.parse(a.start) - Date.now()) - Math.abs(Date.parse(b.start) - Date.now()))[0] || null;
    if (meet) return nearest(D.invites.filter((i) => codeKey(i.meetingCode) === meet));
    if (zoom) return nearest(D.invites.filter((i) => String(i.zoomId || "") === zoom));
    return null;
  }
  document.documentElement.dataset.host = HOST;
  document.documentElement.dataset.framed = String(FRAMED);
  document.documentElement.dataset.skin = SKIN;

  // Settings > In-call panel: which cards show, in what order, compact or full, and the live-listening reminder.
  const TAB_CARDS = { brief: ["opener", "points", "watch", "send"], people: ["people", "map"], notes: ["notes"] };
  const panelPrefs = () => (window.OvertureSettings ? window.OvertureSettings.get().panel : null);
  const cardOn = (id) => { const p = panelPrefs(), c = p && p.cards.find((x) => x.id === id); return !c || c.on; };
  const inOrder = (ids) => { const p = panelPrefs(); if (!p) return ids; const o = p.cards.map((c) => c.id); return ids.slice().sort((a, b) => o.indexOf(a) - o.indexOf(b)); };
  const tabsShown = () => ["brief", "people", "notes"].filter((t) => t === "brief" || TAB_CARDS[t].some(cardOn)); // Brief always has At a glance
  const autoLookup = () => !window.OvertureSettings || window.OvertureSettings.get().mentions.autoLookup !== false;

  // view: a guest's or a company's profile opened inside the current tab ({ kind: "person", email } or { kind: "org", name }), else null.
  const state = { callId: window.C.inviteById(qs.get("call")) ? qs.get("call") : D.invites.length ? D.invites[0].id : null, ctx: null, tab: "brief", inCall: null, startedAt: Date.now(), hostNote: "", ticks: new Set(), open: null, view: null };
  if (HOST === "ext") {
    const m = extMatch();
    if (m) state.callId = state.captionsCall = m.id; // captions are only read for a call this meeting matched, or one you pick
    state.hostNote = m ? "Matched this " + HOST_NAME + " call to " + m.company + "."
      : (qs.get("meet") || qs.get("zoom")) ? "Pick the call below. This meeting isn't on your calendar." : "Open a Google Meet or Zoom web call in this tab, or pick a call below.";
  }
  const announce = (t) => { const el = $("#announce"); el.textContent = ""; setTimeout(() => { el.textContent = t; }, 50); };

  // ---------- host SDKs (only loaded inside Meet or Zoom; every failure falls back to the call picker) ----------
  const load = (src) => new Promise((ok, no) => { const s = document.createElement("script"); s.src = src; s.onload = ok; s.onerror = () => no(new Error("Could not load " + src)); document.head.append(s); });
  const within = (p, ms) => Promise.race([p, new Promise((_, no) => setTimeout(() => no(new Error("timed out")), ms))]);

  async function connectMeet() {
    if (!CFG.meetCloudProjectNumber) { state.hostNote = "Running in Google Meet. Add your Cloud project number in panel.html to read the meeting code."; return; }
    await load("https://www.gstatic.com/meetjs/addons/1.1.0/meet.addons.js");
    const session = await window.meet.addon.createAddonSession({ cloudProjectNumber: String(CFG.meetCloudProjectNumber) });
    const client = await session.createSidePanelClient();
    const info = await client.getMeetingInfo();
    // Meet codes come as "abc-defg-hij" in the calendar and may come without dashes or in capitals from the SDK.
    const code = (c) => String(c || "").toLowerCase().replace(/[^a-z0-9]/g, "");
    const match = code(info.meetingCode) ? D.invites.find((i) => code(i.meetingCode) === code(info.meetingCode)) : null;
    if (match) state.callId = match.id;
    state.hostNote = match ? "Matched this Meet call to " + match.company + "." : "Pick the call below. This meeting code isn't on your calendar.";
  }

  async function connectZoom() {
    await load("https://appssdk.zoom.us/sdk.min.js");
    const zoomSdk = window.zoomSdk;
    const cfg = await within(zoomSdk.config({
      version: "0.16",
      capabilities: ["getRunningContext", "getMeetingContext", "getMeetingParticipants", "getUserContext", "onParticipantChange", "expandApp", "openUrl"],
      timeout: 4000,
    }), 5000);
    if (cfg.runningContext !== "inMeeting") { state.hostNote = "Open Overture from inside a Zoom meeting to match the call."; return; }
    try { // host or co-host only
      const ctx = await zoomSdk.getMeetingContext();
      const match = D.invites.find((i) => (ctx.meetingTopic || "").toLowerCase().includes(i.company.toLowerCase()));
      if (match) state.callId = match.id;
    } catch (e) { /* attendees can't read the topic */ }
    const markParticipants = async () => {
      try {
        const { participants } = await zoomSdk.getMeetingParticipants();
        state.inCall = new Set(participants.map((p) => (p.screenName || "").toLowerCase()));
        if (state.ctx) render();
      } catch (e) { state.inCall = null; }
    };
    await markParticipants();
    try { zoomSdk.onParticipantChange(markParticipants); } catch (e) { /* not allowed for attendees */ }
    state.hostNote = "Connected to this Zoom meeting.";
  }

  // ---------- data ----------
  async function prepare() {
    const inv = window.C.inviteById(state.callId);
    if (!inv) { state.ctx = null; return; }
    const saved = store.get("inputs:" + inv.id);
    const inputs = saved || { versionFile: inv.versionFile || "", since: inv.backstageSince || null };
    state.ctx = await window.C.runChecks(inv, inputs, null, 0);
    state.ticks = new Set(store.get("ticks:" + inv.id) || []);
  }

  // ---------- render ----------
  const LOGO = '<svg class="logo sm" viewBox="0 0 48 48" aria-hidden="true"><defs><mask id="overtureCut"><rect width="48" height="48" fill="#fff"/><circle cx="38.5" cy="9.5" r="8" fill="#000"/></mask></defs><path d="M24 5c11 0 19 4.2 19 17.5S36 43 24 43 5 35.8 5 22.5 13 5 24 5z" fill="#1ED760" mask="url(#overtureCut)"/><g class="logo-eyes" fill="#000"><rect x="15.5" y="18" width="5.5" height="11" rx="2.75"/><rect x="27" y="18" width="5.5" height="11" rx="2.75"/></g><circle class="logo-dot" cx="38.5" cy="9.5" r="5" fill="#22C55E"/></svg>';
  function header() {
    const inv = window.C.inviteById(state.callId);
    const live = HOST !== "preview" || FRAMED;
    const count = { brief: 0, people: state.ctx ? state.ctx.people.length + mnCount() : 0, notes: (store.get("notes:" + state.callId) || []).length };
    return '<header class="p-head">' + (FRAMED ? "" : LOGO)
      + '<div class="p-title"><h1>' + esc(inv.company) + '</h1><p class="p-meta"><span class="live-dot' + (live ? "" : " off") + '" aria-hidden="true"></span>'
      + esc(live ? "Live in " + HOST_NAME : "Preview") + ' · <span id="timer" class="num">0:00</span></p></div>'
      + '<a class="icon-btn p-open" href="index.html' + (window.C.MODE === "demo" ? "?demo=1" : "") + '#/calls/' + esc(inv.id) + '" target="_blank" rel="noopener" aria-label="Open the full brief in a new tab" title="Open the full brief">' + ic("maximize") + "</a></header>"
      + (state.hostNote ? '<p class="p-note">' + esc(state.hostNote) + "</p>" : "")
      + '<label class="p-pick"><span class="sr-only">Call</span><select id="callPick">' + D.invites.map((i) => '<option value="' + esc(i.id) + '"' + (i.id === state.callId ? " selected" : "") + ">" + esc(i.company + " · " + splitWhen(i.when).day + " " + splitWhen(i.when).start) + "</option>").join("") + "</select>" + ic("chevronDown") + "</label>"
      + listenLine()
      + '<div class="p-tabs" role="tablist" aria-label="Panel">'
      + tabsShown().map((t) => '<button type="button" role="tab" id="tab-' + t + '" aria-controls="pane" aria-selected="' + (state.tab === t) + '" tabindex="' + (state.tab === t ? 0 : -1) + '" data-tab="' + t + '">'
        + { brief: "Brief", people: "People", notes: "Notes" }[t] + (count[t] ? '<span class="p-count num">' + count[t] + "</span>" : "") + "</button>").join("") + "</div>";
  }

  // Meetily (Settings > Research sources, off by default): Overture's server reads its live transcript on this PC.
  // "Listening via Meetily" while its lines arrive for this call; GET /api/meetily is asked every 3 s while it is on.
  const meetilyOn = () => LIVE_MODE && !!(window.OvertureSettings && window.OvertureSettings.get().research.meetily);
  const mt = { st: null, timer: null, lines: -1 };
  function listenLine() {
    const cap = captionsLine(); // Google Meet's captions come first: they need nothing else installed
    if (cap) return cap;
    const s = mt.st;
    if (meetilyOn() && s) {
      if (s.listening) return '<p class="p-listen on"><span class="live-dot" aria-hidden="true"></span>Listening via Meetily' + (s.lines ? ' · <span class="num">' + esc(plural(s.lines, "line")) + "</span>" : "") + "</p>";
      if (s.recording && s.callId === state.callId) return '<p class="p-listen"><span class="live-dot off" aria-hidden="true"></span>Meetily is recording. No new words for a moment.</p>';
      if (s.recording) return '<p class="p-listen"><span class="live-dot off" aria-hidden="true"></span>Meetily is recording another call. <button type="button" class="link-btn" data-mt-pick>Use it for this call</button></p>';
      return '<p class="p-listen"><span class="live-dot off" aria-hidden="true"></span>' + (s.found ? "Meetily is on. Start recording in Meetily and Overture reads along." : "Meetily is on, but Overture can't find its recordings folder. See the Meetily guide in Overture: Settings > Setup guides.") + "</p>";
    }
    return panelPrefs() && panelPrefs().listening && !meetilyOn() ? '<p class="p-listen"><span class="live-dot off" aria-hidden="true"></span>Live listening needs Meetily: turn it on in Settings, Research sources.</p>' : "";
  }
  async function meetilyPoll() {
    clearTimeout(mt.timer);
    mt.timer = null;
    if (!meetilyOn()) { if (mt.st) { mt.st = null; refreshListen(); } return; }
    try {
      const r = await window.C.fetchTimeout("/api/meetily?callId=" + encodeURIComponent(state.callId || ""), 5000);
      const j = r.ok ? await r.json() : null;
      const before = JSON.stringify(mt.st);
      mt.st = j;
      if (j && j.callId === state.callId && j.lines !== mt.lines) { mt.lines = j.lines; loadMentions().then(refreshMentions); }
      if (before !== JSON.stringify(j)) refreshListen();
    } catch (e) { /* the panel works without it; ask again */ }
    mt.timer = setTimeout(meetilyPoll, 3000);
  }
  function refreshListen() {
    const old = $(".p-listen"), html = listenLine();
    if (old && html) old.outerHTML = html;
    else if (old) old.remove();
    else if (html && $(".p-pick")) $(".p-pick").insertAdjacentHTML("afterend", html);
  }
  async function meetilyPick() {
    if (!meetilyOn() || !state.callId) return;
    try { mt.st = await window.C.postJson("/api/meetily/pick", { callId: state.callId }, 8000); mt.lines = -1; refreshListen(); announce("Meetily's transcript now goes to this call."); }
    catch (e) { announce(e.message); }
  }

  // A section: 13px title, optional things on the right (a tally, a source marker, a link).
  const sec = (title, right, body) => '<section class="p-sec"><div class="p-sec-head"><h2>' + esc(title) + "</h2>" + (right || "") + "</div>" + body + "</section>";

  function briefPane() {
    const ctx = state.ctx, c = ctx.company, b = ctx.bill, top = ctx.products[0];
    const alerts = window.C.alertsFor(ctx.invite.id);
    const last = c && c.history.length ? c.history[c.history.length - 1] : null;
    const points = ctx.todos.map((t) => t.text);
    // Questions to ask on the call, built from what the agent found.
    const asks = [];
    if (b) asks.push({ q: "Who on your team keeps Backstage upgraded today?", why: plural(b.behind, "release") + " behind suggests it has no owner." });
    ctx.people.filter((p) => p.facts.lead).forEach((p) => asks.push({ q: "Ask " + p.name.split(" ")[0] + ": " + (p.facts.lead.src === "pub" ? "how did you use Backstage before?" : "what worked at " + p.previous + "?"), why: p.facts.lead.text }));
    if (top.name === "Xirp" && top.score > 0) asks.push({ q: "How do your AI agents find who owns a service?", why: "They use AI coding agents every day." });
    if (top.name === "Confidence" && top.score > 0) asks.push({ q: "Who signs off before a test result ships?", why: "They run A/B tests on checkout." });
    // What Overture's research says to bring up: each guest's profile, then the company's (five at most, so the list stays short).
    const orgP = window.C.orgInfo(ctx.invite.company).profile;
    window.CP.forCallItems(ctx.people).map((x) => ({ q: x.b.text, why: "From " + x.name.split(" ")[0] + "'s profile" }))
      .concat(orgP ? orgP.forCall.map((b) => ({ q: b.text, why: "From " + (orgP.name || ctx.invite.company) + "'s profile" })) : []).slice(0, 5).forEach((a) => asks.push(a));
    const done = asks.filter((a, i) => state.ticks.has("ask:" + i)).length;
    // The opener first by default: it's the line Chris says in the first ten seconds. The order and the cards come from Settings.
    const card = {};
    card.opener = '<section class="p-opener"><h2 class="p-label">Open with</h2><blockquote>' + esc(ctx.opener) + "</blockquote></section>";
    let h = "";
    if (asks.length) {
      h += sec("Talking points", '<span class="p-tally num" id="tickCount">' + done + " of " + asks.length + '</span><span class="grow"></span><span class="src guess">Agent\'s guess</span>',
        '<ul class="p-points" role="list">' + asks.map((a, i) => { const id = "ask:" + i; return '<li><label><input type="checkbox" data-tick="' + id + '"' + (state.ticks.has(id) ? " checked" : "") + '><span><strong>' + esc(a.q) + "</strong><small>" + esc(a.why) + "</small></span></label></li>"; }).join("") + "</ul>");
    }
    card.points = h;
    h = "";
    const glance = sec("At a glance", "", '<dl class="p-props">'
      + "<dt>Company</dt><dd>" + (orgP || window.C.orgInfo(ctx.invite.company).status
        ? '<button type="button" class="link-btn pp-org-link" data-pp-org="' + esc(ctx.invite.company) + '">' + esc(orgP && orgP.name ? orgP.name : ctx.invite.company) + "</button>"
        : esc(ctx.invite.company)) + (c ? ' <span class="pill ' + tagFor("status", c.status) + '">' + esc(c.status) + "</span>" : "") + "</dd>"
      + (top.score > 0 ? '<dt>Best fit</dt><dd><span class="pill accent">' + esc(top.name) + "</span></dd>" : "")
      + (last ? "<dt>Last talk</dt><dd>" + esc(fmtDate(last.date) + ": " + last.text) + "</dd>" : "")
      + (b ? "<dt>Backstage</dt><dd>" + esc(b.from + " · " + plural(b.behind, "release") + " behind · " + plural(b.serious, "serious notice")) + "</dd>" : "")
      + "</dl>");
    if (alerts.length) {
      h += sec("Watch for", "", '<ul class="p-watch" role="list">' + alerts.slice(0, 2).map((a) => '<li><span class="pill ' + tagFor("alert", a.kind) + '">' + esc(a.kind) + "</span><span>" + esc(a.text) + "</span></li>").join("") + "</ul>");
    }
    card.watch = h;
    card.send = points.length ? sec("Still to send", "", '<ul class="p-plain" role="list">' + points.map((t) => "<li>" + esc(t) + "</li>").join("") + "</ul>") : "";
    // At a glance sits before Watch for (or last when Watch for is hidden).
    const order = inOrder(TAB_CARDS.brief).filter(cardOn);
    const at = order.indexOf("watch");
    if (at < 0) order.push("glance"); else order.splice(at, 0, "glance");
    card.glance = glance;
    return order.map((id) => card[id]).join("");
  }

  function peoplePane() {
    const ctx = state.ctx;
    const here = (p) => state.inCall ? state.inCall.has(p.name.toLowerCase()) : null;
    const row = (p) => {
      const f = p.facts;
      const tag = f.lead ? f.lead.text.replace(/^Came from (.+?), .*/, "ex-$1") : f.isNew ? "New in job" : "";
      // A guest opens their profile inside the panel (the same sections as the app's person page, folded for this width).
      return '<li class="p-person"><button type="button" class="p-person-btn" data-person="' + esc(p.email) + '" aria-label="' + esc("Open " + p.name + "'s profile") + '">'
        + avatar(p, "md") + "<span class=\"p-person-text\"><span class=\"p-person-name\">" + esc(p.name)
        + (here(p) ? ' <span class="joined">' + ic("check") + '<span class="sr-only">in the call</span></span>' : "") + '</span><span class="p-person-sub">'
        + esc(p.title === "Title unknown" && p.research && p.research.status === "pending" ? "Researching…"
          : p.title + (p.research && p.research.status === "done" && window.C.RELATION[p.research.relationship] ? " · " + window.C.RELATION[p.research.relationship] : "")) + "</span></span>"
        + (tag ? '<span class="pill">' + esc(tag) + "</span>" : "") + ic("chevron", "pp-row-chev") + "</button>"
        + "</li>";
    };
    const theirs = ctx.people.filter((p) => here(p) !== false), missing = ctx.people.filter((p) => here(p) === false);
    const card = {};
    card.people = sec("Their side", '<span class="grow"></span><span class="src ' + (window.C.MODE === "demo" ? "sample" : "yours") + '">' + esc(window.C.SRC.records) + "</span>", '<ul class="p-people" role="list">' + theirs.map(row).join("") + "</ul>")
      + (missing.length ? sec("Invited, not here yet", "", '<ul class="p-people" role="list">' + missing.map(row).join("") + "</ul>") : "")
      + mentionsSec();
    card.map = sec("Who connects to whom", '<span class="grow"></span><a class="link-btn" href="index.html' + (window.C.MODE === "demo" ? "?demo=1" : "") + '#/map" target="_blank" rel="noopener">Open map' + window.C.NEW_TAB + "</a>", '<div id="miniMap" class="mini-map"></div>');
    return inOrder(TAB_CARDS.people).filter(cardOn).map((id) => card[id]).join("");
  }

  function notesPane() {
    const notes = store.get("notes:" + state.callId) || [];
    return '<section class="p-notes"><ul class="p-note-list" role="list">' + (notes.length ? notes.map((n) => '<li><span class="p-note-kind pill ' + tagFor("note", n.kind) + '">' + esc(n.kind) + '</span><span class="num muted-line">' + esc(n.at) + "</span><p>" + esc(n.text) + "</p></li>").join("")
      : '<li class="empty-line">No notes yet. They go to "After the call" in the full app.</li>') + "</ul>"
      + '<form id="noteForm" class="p-compose"><label for="noteText" class="sr-only">Note</label><textarea id="noteText" rows="3" placeholder="Type a note">' + esc(live.draft) + "</textarea>"
      + '<div class="p-compose-row"><div class="chips" role="radiogroup" aria-label="Kind">'
      + ["Note", "Question", "Objection", "Next step"].map((k, i) => '<label class="chip-radio ' + tagFor("note", k) + '"><input type="radio" name="kind" value="' + k + '"' + (i === 0 ? " checked" : "") + "><span>" + k + "</span></label>").join("")
      + '</div><button type="submit" class="btn primary sm">Save</button></div></form><p class="p-private">Only you can see this panel.</p></section>';
  }

  // ---------- mentioned on the call: people and companies, found while the call runs ----------
  // Live: GET /api/mentions for this call, asked again every 1.8 s while something is being looked up (or a company waits for
  // the speaker to say how it relates). Notes you type are read as you type (POST /api/mentions/live, only the new text, 500 ms
  // after you stop). Demo: the sample transcript's results, tagged Sample; nothing is sent.
  const LIVE_MODE = window.C.MODE === "live";
  const MN_TAG = { pending: ["Looking up…", "tag-blue"], found: ["Found", "tag-green"], known: ["Found", "tag-green"], pick: ["Likely, not confirmed", "tag-orange"],
    notfound: ["Not found", "tag-gray"], error: ["Couldn't look up", "tag-red"], nokey: ["Not looked up", "tag-gray"] };
  const ORG_TAG = { waiting: ["Listening…", "tag-blue"], pending: ["Looking up…", "tag-blue"], said: ["Said on the call", "tag-purple"], found: ["Found on the web", "tag-teal"],
    unknown: ["Relation unknown", "tag-gray"], error: ["Couldn't look up", "tag-red"], nokey: ["Not looked up", "tag-gray"] };
  const mn = { callId: null, items: [], orgs: [], timer: null };
  const cap = (t) => String(t || "").charAt(0).toUpperCase() + String(t || "").slice(1);
  const mnCount = () => (mn.callId === state.callId ? mn.items.length + mn.orgs.length : 0);
  const mnPending = () => mn.items.some((x) => x.status === "pending") || mn.orgs.some((x) => x.status === "pending" || x.status === "waiting");

  async function loadMentions() {
    const id = state.callId;
    if (window.C.MODE === "demo") {
      const sm = D.mentionSample;
      Object.assign(mn, { callId: id, items: sm && sm.callId === id ? sm.items : [], orgs: sm && sm.callId === id ? sm.orgs || [] : [] });
      return;
    }
    if (!LIVE_MODE || !id) return;
    try {
      const r = await window.C.fetchTimeout("/api/mentions?callId=" + encodeURIComponent(id), 8000);
      if (r.ok) applyMentions(id, await r.json()); else mnPoll();
    } catch (e) { mnPoll(); } // the panel works without them; ask again in a moment while something is still being looked up
  }
  // The app around this panel (the panel runs in its own frame there) and any open People map refetch a call when its connections change.
  const mnBus = "BroadcastChannel" in window ? new BroadcastChannel("overture-mentions") : null;
  function applyMentions(id, j) {
    if (id !== state.callId || !j) return;
    const before = JSON.stringify([mn.callId, mn.items, mn.orgs]);
    Object.assign(mn, { callId: id, items: j.items || [], orgs: j.orgs || [] });
    const graph = window.C.mergeConnections(id, j.graph);
    if (graph && mnBus) mnBus.postMessage({ callId: id });
    if (graph || before !== JSON.stringify([mn.callId, mn.items, mn.orgs])) refreshMentions();
    mnPoll();
  }
  function mnPoll() {
    if (!LIVE_MODE || mn.timer || !mnPending()) return;
    mn.timer = setTimeout(async () => { mn.timer = null; await loadMentions(); }, 1800);
  }
  // On the People tab, redraw it (and its mini map). Elsewhere, only the tab's count changes, so a note being typed is never touched.
  function refreshMentions() {
    if (state.tab === "people" && !state.view) { const y = window.scrollY; render(); window.scrollTo(0, y); return; }
    const tab = $("#tab-people");
    if (!tab || !state.ctx) return;
    const n = state.ctx.people.length + mnCount();
    let c = $(".p-count", tab);
    if (!c) { c = document.createElement("span"); c.className = "p-count num"; tab.appendChild(c); }
    c.textContent = String(n);
  }
  function mnRow(it) {
    const p = it.person, c0 = it.status === "pick" && it.candidates && it.candidates[0];
    const t = it.autoFound && !it.confirmed && it.status === "found" ? ["Found automatically", "tag-green"] : MN_TAG[it.status] || MN_TAG.notfound;
    const name = p ? p.name : c0 ? c0.name : it.name || cap(it.role) || "Someone";
    const sub = [p ? p.title : c0 ? c0.title : it.role ? cap(it.role) : "", it.said && it.said.label].filter(Boolean).join(" · ");
    const acts = [];
    if (LIVE_MODE) {
      if (it.autoFound && !it.confirmed) acts.push('<button type="button" class="link-btn" data-mn-act="confirm">Confirm</button><button type="button" class="link-btn" data-mn-act="none">Not them</button>');
      if (c0) acts.push('<button type="button" class="link-btn" data-mn-act="pick" data-mn-index="0">' + esc("Pick " + c0.name) + "</button>");
      acts.push(mnConnBtn(it));
    }
    return '<li class="p-mn" data-mn="' + esc(it.id) + '">' + avatar({ name }, "md") + '<div class="p-mn-text"><p class="p-person-name">' + esc(name)
      + '<span class="pill ' + t[1] + '">' + (it.status === "pending" ? ic("loader", "spin") : "") + esc(t[0]) + "</span></p>"
      + (sub ? '<p class="p-person-sub">' + esc(sub) + "</p>" : "")
      + (it.quote && it.quote.text ? '<p class="p-mn-quote">“' + esc(it.quote.text) + "”</p>" : "")
      + (it.explain && (["found", "known", "pick"].includes(it.status) || it.said) ? window.C.explainFold(it.explain, { noMention: true }) : "")
      + (acts.join("") ? '<p class="p-mn-acts">' + acts.join("") + "</p>" : "") + "</div></li>";
  }
  function orgRow(o) {
    const t = ORG_TAG[o.status] || ORG_TAG.unknown, r = o.relation;
    const quoted = o.quote && o.quote.text && r && r.said && o.quote.text.includes(r.said.replace(/…/g, ""));  // said in the same sentence: shown once
    const sub = r && r.type !== "unknown" ? cap(r.label) + (r.source === "said" && r.said && !quoted ? ": “" + r.said + "”" : "") : "";
    return '<li class="p-mn" data-mn="' + esc(o.id) + '">' + coTile(o.name, "co-tile p-mn-co") + '<div class="p-mn-text"><p class="p-person-name">' + esc(o.name)
      + '<span class="pill ' + t[1] + '">' + (o.status === "pending" || o.status === "waiting" ? ic("loader", "spin") : "") + esc(t[0]) + "</span></p>"
      + (sub ? '<p class="p-person-sub">' + esc(sub) + "</p>" : "")
      + (o.quote && o.quote.text ? '<p class="p-mn-quote">“' + esc(o.quote.text) + "”</p>" : "")
      + (o.explain && r && r.type !== "unknown" ? window.C.explainFold(o.explain, { noMention: true }) : "")
      + (LIVE_MODE && mnConnBtn(o) ? '<p class="p-mn-acts">' + mnConnBtn(o) + "</p>" : "") + "</div></li>";
  }
  const mnConnBtn = (x) => (x.removed ? '<button type="button" class="link-btn" data-mn-act="restore">Add back to the map</button>'
    : x.connected ? '<button type="button" class="link-btn" data-mn-act="remove">Remove from the map</button>' : "");
  function mentionsSec() {
    if (mn.callId !== state.callId || (!mn.items.length && !mn.orgs.length)) {
      return LIVE_MODE ? sec("Mentioned on the call", "", '<p class="p-hint">' + (autoLookup() ? "Type a name or a company in Notes and Overture finds who or what it is while the call runs."
        : "Automatic look-up is off (Settings, Mentions and connections). Find mentions in After the call instead.") + "</p>") : "";
    }
    const right = '<span class="grow"></span>' + (window.C.MODE === "demo" ? '<span class="src sample">Sample</span>' : "")
      + '<a class="link-btn" href="index.html' + (window.C.MODE === "demo" ? "?demo=1" : "") + "#/calls/" + encodeURIComponent(state.callId) + '/after" target="_blank" rel="noopener">All' + window.C.NEW_TAB + "</a>";
    return sec("Mentioned on the call", right, '<ul class="p-people p-mns" role="list">' + mn.items.map(mnRow).join("") + mn.orgs.map(orgRow).join("") + "</ul>");
  }
  async function mnAct(btn) {
    const row = btn.closest("[data-mn]"), id = state.callId;
    if (!row || btn.disabled || !LIVE_MODE) return;
    btn.disabled = true;
    const action = btn.dataset.mnAct, body = { callId: id, id: row.dataset.mn, action };
    if (action === "pick") body.index = +btn.dataset.mnIndex || 0;
    try {
      applyMentions(id, await window.C.postJson("/api/mentions/pick", body, 15000));
      announce({ confirm: "Confirmed.", none: "Marked as not them.", pick: "Picked. Added to the map.", remove: "Removed from the map.", restore: "Back on the map." }[action] || "Done.");
    } catch (e) { btn.disabled = false; announce(e.message); }
  }

  // Notes, read as you type: only the new text goes to Overture's own server (500 ms after you stop typing); saving the note finishes it.
  // The server reads finished sentences as they come; a 1.5 s pause reads the rest, and saving the note ends it. Whatever the note
  // no longer says ("John Sm" once it reads "John Smith") is taken back, so the draft is kept when the panel redraws (draft).
  const live = { seg: "", sent: "", timer: null, idle: null, busy: false, next: null, paused: "", draft: "", source: "live" };
  const newSeg = () => (Math.random().toString(36).slice(2, 10) + Date.now().toString(36)).replace(/[^a-z0-9]/g, "").slice(0, 32);
  // st: whose text this is: `live` (your note) or `cc` (Google Meet's captions); each keeps its own place in the text.
  async function sendLive(text, final, pause, st) {
    st = st || live;
    if (!LIVE_MODE || !state.callId || text.length > 8000 || !autoLookup()) return; // Settings > Mentions: automatic look-up can be off
    // While one send runs: a finishing send waits in its own list and goes first, so a later send can never replace it.
    if (st.busy) { if (final) { (st.fins = st.fins || []).push(text); st.next = null; } else st.next = [text, final, pause]; return; }
    if (!st.seg) { st.seg = newSeg(); st.sent = ""; }
    let off = 0;
    while (off < st.sent.length && off < text.length && st.sent[off] === text[off]) off++;
    const part = text.slice(off);
    if (!part && !final && !(pause && st.paused !== text)) return;
    if (pause) st.paused = text;
    st.busy = true;
    const id = state.callId, seg = st.seg;
    try {
      const j = await window.C.postJson("/api/mentions/live", { callId: id, segment: seg, offset: off, text: part.slice(0, 4000), final: !!final, pause: !!pause,
        source: st.source }, 15000);
      st.sent = final ? "" : text;
      if (final && st.seg === seg) st.seg = "";
      applyMentions(id, j);
      if (j.found && id === state.callId) announce(plural(j.found, "new mention") + (st === live ? " found in your note." : " heard on the call."));
    } catch (e) {
      // the server lost the note (it restarted): send it all again, once
      if (e.message === "resend" && off) { st.seg = ""; st.sent = ""; st.paused = ""; if (!st.next) st.next = [text, final, pause]; }
      // a finishing send that failed still ends its part here: the next text starts a new part, never overwriting the old one
      else if (final && st.seg === seg) { st.seg = ""; st.sent = ""; st.paused = ""; }
    }
    st.busy = false;
    if (st.fins && st.fins.length) { sendLive(st.fins.shift(), true, false, st); return; }
    if (st.next) { const [t, f, p] = st.next; st.next = null; sendLive(t, f, p, st); }
  }

  // ---------- Google Meet's captions: Overture's Chrome extension reads them while CC is on ----------
  // Each finished line ("Name: words") is read for people and companies as it comes, like a note you type. When you leave the
  // call (or it's past its end time), the whole caption transcript is read once more for After the call. The transcript stays in
  // this panel: Overture's server keeps only who and what was mentioned, with one sentence each.
  const cc = { seg: "", sent: "", busy: false, next: null, paused: "", source: "captions", lines: [], segStart: 0, idle: null, lastAt: 0, posted: false };
  const ccText = () => cc.lines.slice(cc.segStart).join("\n");
  window.addEventListener("message", (e) => {
    // Only the extension's side panel frames this page (the server's frame-ancestors says so), and it is our parent.
    if (e.source !== window.parent || !/^chrome-extension:\/\//.test(e.origin) || !e.data || !LIVE_MODE) return;
    if (e.data.type === "overture-captions" && Array.isArray(e.data.lines)) captionLines(e.data.lines);
    if (e.data.type === "overture-call-ended") captionsDone("left", e.data.lines);
    if (e.data.type === "overture-captions-status") { // the Meet tab's reader checks in every 3 s: running, and whether CC is on
      const was = cc.box;
      cc.box = !!e.data.box; cc.seenAt = Date.now();
      if (was !== cc.box) refreshListen();
    }
  });
  // Captions count only for the call this meeting matched, or one you picked: never for whichever call the list shows first.
  const captionsOn = () => !!state.callId && state.captionsCall === state.callId;
  function captionLines(lines) {
    const add = lines.filter((l) => typeof l === "string" && l.trim()).map((l) => l.trim().slice(0, 600)).slice(0, 50);
    if (!add.length || !captionsOn()) return;
    const before = ccText();
    if (before && before.length + add.join("\n").length > 6000) { sendLive(before, true, false, cc); cc.segStart = cc.lines.length; } // a new part every ~6,000 letters
    cc.lines.push(...add);
    if (cc.lines.length > 20000) { const cut = cc.lines.length - 20000; cc.lines.splice(0, cut); cc.segStart = Math.max(0, cc.segStart - cut); }
    cc.lastAt = Date.now();
    cc.posted = false;
    sendLive(ccText(), false, false, cc);
    clearTimeout(cc.idle);
    cc.idle = setTimeout(() => sendLive(ccText(), false, true, cc), 1500); // a pause reads the last sentence too
    const num = $(".p-listen .num");
    if (num && $(".p-listen.on")) num.textContent = plural(cc.lines.length, "line"); // just the count: keyboard focus on the button stays put
    else refreshListen();
  }
  // The call is over: read the whole caption transcript once, the same way an uploaded transcript is read. The Meet tab's own
  // copy (sent when you leave) wins when it's longer: this panel may have reloaded during the call.
  async function captionsDone(why, all) {
    const tab = Array.isArray(all) ? all.filter((l) => typeof l === "string" && l.trim()).map((l) => l.trim().slice(0, 600)) : [];
    const lines = tab.length > cc.lines.length ? tab : cc.lines;
    if (cc.posted || !lines.length || !captionsOn() || !LIVE_MODE) return;
    cc.posted = true;
    clearTimeout(cc.idle);
    const id = state.callId;
    if (cc.lines.length) sendLive(ccText(), true, false, cc);
    try {
      const j = await window.C.postJson("/api/mentions", { callId: id, text: lines.join("\n").slice(0, 900000), source: "captions" }, 60000);
      applyMentions(id, j);
      announce((why === "left" ? "Call ended. " : "") + "Overture read the whole caption transcript for After the call.");
    } catch (e) { cc.posted = false; announce("Couldn't read the call's captions: " + e.message); }
    refreshListen();
  }
  // Past the call's end time and no captions for 2 minutes: treat it as over (in case leaving the call wasn't seen).
  setInterval(() => {
    const inv = state.callId && window.C.inviteById(state.callId);
    if (inv && inv.end && cc.lines.length && !cc.posted && Date.now() > Date.parse(inv.end) && Date.now() - cc.lastAt > 120000) captionsDone("time");
  }, 30000);
  function captionsLine() {
    if (!LIVE_MODE) return "";
    if (qs.get("meet") && !captionsOn()) return '<p class="p-listen"><span class="live-dot off" aria-hidden="true"></span>Pick this meeting\'s call above so Overture can read its captions.</p>';
    if (!cc.lines.length) {
      if (!qs.get("meet")) return "";
      const off = (t) => '<p class="p-listen"><span class="live-dot off" aria-hidden="true"></span>' + t + "</p>";
      if (!cc.seenAt || Date.now() - cc.seenAt > 15000) return off(/* nothing from the reader for 15 s: it isn't running */ "Overture's caption reader isn't running in this Meet tab yet. Reload the Meet tab once (or the Overture extension), then turn on CC.");
      if (!cc.box) return off("Turn on captions (CC) in Meet and Overture finds who and what is mentioned. Let everyone know you're taking AI notes.");
      return '<p class="p-listen on"><span class="live-dot" aria-hidden="true"></span>Captions are on. Waiting for someone to speak…</p>';
    }
    return '<p class="p-listen on"><span class="live-dot" aria-hidden="true"></span>Reading Meet captions · <span class="num">' + esc(plural(cc.lines.length, "line")) + "</span>"
      + (cc.posted ? " · read for After the call" : ' · <button type="button" class="link-btn" data-cc-done>Call over? Find everyone mentioned</button>') + "</p>";
  }
  document.addEventListener("click", (e) => { if (e.target.closest("[data-cc-done]")) captionsDone("button"); });
  document.addEventListener("input", (e) => {
    if (e.target.id !== "noteText" || !LIVE_MODE) return;
    live.draft = e.target.value;
    clearTimeout(live.timer);
    clearTimeout(live.idle);
    const now = () => ($("#noteText") || {}).value;
    live.timer = setTimeout(() => { const t = now(); if (typeof t === "string") sendLive(t, false, false); }, 500);
    live.idle = setTimeout(() => { const t = now(); if (typeof t === "string" && t.trim()) sendLive(t, false, true); }, 1500);
  });

  // ---------- a guest's or a company's profile, opened inside the panel (the side of the meeting) ----------
  const panelLinks = { panel: true };
  // What a guest's row used to unfold: the agent's key fact, your note, time in the job, and the research buttons.
  function personTop(p) {
    const f = p.facts;
    return (f.lead ? '<p class="pp-key"><strong>' + esc(f.lead.text) + "</strong> " + esc(p.note || f.lead.tail) + "</p>" : p.note ? '<p class="pp-key">' + esc(p.note) + "</p>" : "")
      + (p.startedAt ? '<p class="muted-line">' + esc(tenure(p.startedAt)) + "</p>" : "")
      + (f.quote ? '<p class="muted-line">Public adopters list: “' + esc(f.quote) + "”</p>" : "")
      + window.C.researchHtml(p, { actions: true, editHref: "index.html" + (window.C.MODE === "demo" ? "?demo=1" : "") + "#/calls/" + encodeURIComponent(state.callId) });
  }
  function viewPane() {
    const v = state.view, back = state.tab === "people" ? "People" : "Brief";
    if (v.kind === "person") {
      const p = state.ctx.people.find((x) => x.email === v.email);
      return window.CP.panelPerson(v.email, Object.assign({ back, top: p ? personTop(p) : "" }, panelLinks));
    }
    const block = window.CP.orgBlock(v.name, Object.assign({ fold: true, idp: "ppo", headTag: "h2" }, panelLinks));
    return '<div class="pp"><button type="button" class="pp-back" data-pp-back>' + ic("chevronLeft") + back + "</button>"
      + (block || '<p class="pf-state">' + ic("circleAlert") + "<span>Overture has no public profile for " + esc(v.name) + " yet.</span></p>") + "</div>";
  }
  function openView(v) {
    state.view = v;
    render();
    window.scrollTo(0, 0);
    const b = $(".pp-back");
    if (b) b.focus();
    announce(v.kind === "person" ? "Showing " + window.CP.who(v.email).name + "'s profile." : "Showing " + v.name + ".");
  }
  function closeView() {
    const v = state.view;
    state.view = null;
    render();
    const back = v && (v.kind === "person" ? $('[data-person="' + CSS.escape(v.email) + '"]') : $("[data-pp-org]"));
    if (back) back.focus();
  }

  let mini = null;
  function render() {
    if (!state.ctx) {
      $("#app").innerHTML = '<header class="p-head">' + (FRAMED ? "" : LOGO) + '<div class="p-title"><h1>Overture</h1><p class="p-meta">No calls yet</p></div></header>'
        + (state.hostNote ? '<p class="p-note">' + esc(state.hostNote) + "</p>" : "")
        + '<p class="p-empty">' + (window.C.MODE === "connect" ? 'Connect your Google Calendar in the <a href="index.html#/home" target="_blank" rel="noopener">Overture app' + window.C.NEW_TAB + "</a> to see your calls here." : "No calls with outside guests in the next 14 days.") + "</p>";
      return;
    }
    const panes = { brief: briefPane, people: peoplePane, notes: notesPane };
    if (!tabsShown().includes(state.tab)) state.tab = "brief";
    document.documentElement.dataset.panelDensity = panelPrefs() ? panelPrefs().density : "full";
    $("#app").innerHTML = header() + '<div id="pane" role="tabpanel" aria-labelledby="tab-' + state.tab + '" class="p-pane">' + (state.view ? viewPane() : panes[state.tab]()) + "</div>";
    if (mini) { mini.destroy(); mini = null; }
    if (state.tab === "people" && !state.view && window.CMap && $("#miniMap")) mini = window.CMap.mount($("#miniMap"), { mode: "stack", callId: state.callId, compact: true });
  }

  function setTab(t, focus) {
    state.tab = t;
    state.view = null;
    render();
    if (focus) $("#tab-" + t).focus();
  }

  // Research results (found automatically) and the Confirm / Look up again buttons. domains: companies whose research changed.
  function refreshPeople(emails, domains) {
    if (!state.ctx) return;
    let hit = false;
    state.ctx.people.forEach((p) => {
      if (!emails.includes(p.email)) return;
      const d = D.people[p.email] || {};
      Object.assign(p, { research: d.research, title: d.title || p.title, known: d.known === undefined ? p.known : d.known });
      p.facts = window.C.personFacts(p);
      hit = true;
    });
    const v = state.view, orgHit = (domains || []).includes(window.C.orgDomain(state.ctx.invite.company));
    const redraw = v ? (v.kind === "person" ? emails.includes(v.email) || orgHit : orgHit) : (hit && state.tab === "people") || (orgHit && state.tab === "brief");
    if (redraw) { const y = window.scrollY; render(); window.scrollTo(0, y); }
  }
  async function researchAction(btn) {
    const confirm = btn.hasAttribute("data-rs-confirm"), email = confirm ? btn.dataset.rsConfirm : btn.dataset.rsAgain;
    if (btn.disabled) return;
    btn.disabled = true;
    try {
      if (confirm) await window.C.confirmResearch(email); else await window.C.lookUpAgain(email);
    } catch (err) { btn.disabled = false; announce(err.message); return; }
    refreshPeople([email]);
    const back = $('[data-person="' + CSS.escape(email) + '"]');
    if (back) back.focus();
    announce(confirm ? (window.C.MODE === "demo" ? "Confirmed (sample data, this panel only)." : "Confirmed. Saved to Overture's records.") : "Looking them up.");
  }

  // ---------- events ----------
  document.addEventListener("click", (e) => {
    const t = e.target.closest("[data-tab]");
    if (t) { setTab(t.dataset.tab); return; }
    const rs = e.target.closest("[data-rs-confirm], [data-rs-again]");
    if (rs) { researchAction(rs); return; }
    const ma = e.target.closest("[data-mn-act]");
    if (ma) { mnAct(ma); return; }
    if (e.target.closest("[data-mt-pick]")) { meetilyPick(); return; }
    // Profiles inside the panel: a guest, a company, the way back, and a connection's card.
    if (e.target.closest("[data-pp-back]")) { closeView(); return; }
    const pp = e.target.closest("[data-pp-person]");
    if (pp) { const em = window.C.emailForKey(pp.dataset.ppPerson); if (em) openView({ kind: "person", email: em }); return; }
    const po = e.target.closest("[data-pp-org]");
    if (po) { openView({ kind: "org", name: po.dataset.ppOrg }); return; }
    const row = e.target.closest(".pm-row[data-pm]");
    if (row && state.view && state.view.kind === "person") { window.CP.toggleRow(row, window.CP.graph(state.view.email), panelLinks); return; }
    const p = e.target.closest("[data-person]");
    if (p) openView({ kind: "person", email: p.dataset.person });
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && state.view && !e.target.closest("textarea, input, select")) { closeView(); return; }
    const tab = e.target.closest("[role=tab]");
    if (!tab || (e.key !== "ArrowLeft" && e.key !== "ArrowRight")) return;
    const order = tabsShown();
    const i = order.indexOf(state.tab) + (e.key === "ArrowRight" ? 1 : -1);
    setTab(order[(i + order.length) % order.length], true);
  });
  document.addEventListener("change", async (e) => {
    if (e.target.id === "callPick") {
      clearTimeout(live.timer); clearTimeout(live.idle);
      if (live.seg && (live.draft.trim() || live.sent)) sendLive(live.draft.trim() ? live.draft : live.sent, true, false); // the old call's note is done: the server drops its text now
      state.callId = state.captionsCall = e.target.value; state.open = null; state.view = null;
      Object.assign(live, { seg: "", sent: "", next: null, fins: [], paused: "", draft: "" }); // nothing queued for the old call may go to the new one
      await prepare(); await loadMentions(); render(); announce("Showing " + window.C.inviteById(state.callId).company + ".");
      if (mt.st && mt.st.recording) meetilyPick(); // the call picked here is the one Meetily is recording
      return;
    }
    const tick = e.target.closest("[data-tick]");
    if (tick) {
      if (tick.checked) state.ticks.add(tick.dataset.tick); else state.ticks.delete(tick.dataset.tick);
      store.set("ticks:" + state.callId, [...state.ticks]);
      const tally = $("#tickCount"); if (tally) tally.textContent = $$("[data-tick]:checked").length + " of " + $$("[data-tick]").length;
    }
  });
  document.addEventListener("submit", (e) => {
    if (e.target.id !== "noteForm") return;
    e.preventDefault();
    const text = $("#noteText").value.trim();
    if (!text) return;
    const kind = ($('input[name="kind"]:checked') || {}).value || "Note";
    const secs = Math.floor((Date.now() - state.startedAt) / 1000);
    const notes = store.get("notes:" + state.callId) || [];
    notes.push({ kind, text, at: Math.floor(secs / 60) + ":" + String(secs % 60).padStart(2, "0") });
    store.set("notes:" + state.callId, notes);
    clearTimeout(live.timer);
    clearTimeout(live.idle);
    live.draft = "";
    sendLive(text, true, false); // the note is done: anything still waiting for an explanation is decided now
    render();
    $("#noteText").focus();
    announce("Note saved.");
  });
  setInterval(() => {
    const el = $("#timer");
    if (!el) return;
    const s = Math.floor((Date.now() - state.startedAt) / 1000);
    el.textContent = Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
  }, 1000);

  async function start() {
    await prepare();
    await loadMentions();
    render(); // show something at once; the host connection only adds to it
    window.C.watchResearch(() => (state.view && state.view.kind === "person" ? [state.view.email] : state.ctx && state.tab === "people" ? state.ctx.people.map((p) => p.email) : []),
      refreshPeople, () => (state.ctx ? [state.ctx.invite.company] : []));
    meetilyPoll();
    try {
      if (HOST === "meet") await within(connectMeet(), 9000); // Meet expects a session within about 10 s
      else if (HOST === "zoom") await connectZoom();
      if (HOST !== "preview") { await prepare(); await loadMentions(); render(); }
    } catch (e) {
      state.hostNote = "Couldn't read the meeting (" + e.message + "). Pick the call below.";
      render();
    }
  }
  // Settings changed (here, in the app, or in another tab): the panel follows at once.
  if (window.OvertureSettings) window.OvertureSettings.on(() => { if (state.ctx) { state.ctx.opener = window.C.openingLine(state.ctx); render(); } meetilyPoll(); });
  document.addEventListener("DOMContentLoaded", start);
})();
