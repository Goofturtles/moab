// Overture app: a hash-routed shell around the agent (core.js), the people map (map.js) and the in-call panel (panel.html).
// Pages: #/home, #/calls, #/calls/<id>[/after], #/alerts[/<id>], #/companies[/<slug>], #/map, #/live, #/data, #/settings[/<menu>] (settings-page.js).
(function () {
  "use strict";
  const C = window.C;
  const { D, SNAP, MODE, SRC, ME, $, $$, esc, ic, plural, fmtDate, splitWhen, store, NEW_TAB, MONTHS, avatar, coTile, tagFor } = C;
  const LIVE_MODE = MODE === "live", DEMO = MODE === "demo";
  // Where your data is kept: this PC, or (the shared site) your own account, which nobody else who signs in can see.
  const savedWhere = () => (window.MOAB_STATUS && window.MOAB_STATUS.hosted ? "in your own account, which other people who sign in can't see" : "on this PC");

  Object.assign(C.ICONS, {
    menu: '<path d="M4 12h16M4 6h16M4 18h16"/>',
    phone: '<path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"/>',
    chevronLeft: '<path d="m15 18-6-6 6-6"/>',
    circleDashed: '<path d="M10.1 2.182a10 10 0 0 1 3.8 0M13.9 21.818a10 10 0 0 1-3.8 0M17.609 3.721a10 10 0 0 1 2.69 2.7M2.182 13.9a10 10 0 0 1 0-3.8M20.279 17.609a10 10 0 0 1-2.7 2.69M21.818 10.1a10 10 0 0 1 0 3.8M3.721 6.391a10 10 0 0 1 2.7-2.69M6.391 20.279a10 10 0 0 1-2.69-2.7"/>',
    listChecks: '<path d="m3 17 2 2 4-4M3 7l2 2 4-4M13 6h8M13 12h8M13 18h8"/>',
    database: '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5V19A9 3 0 0 0 21 19V5"/><path d="M3 12A9 3 0 0 0 21 12"/>',
    receipt: '<path d="M4 2v20l2-1 2 1 2-1 2 1 2-1 2 1 2-1 2 1V2l-2 1-2-1-2 1-2-1-2 1-2-1-2 1Z"/><path d="M16 8h-6a2 2 0 1 0 0 4h4a2 2 0 1 1 0 4H8M12 17.5v-11"/>',
    tag: '<path d="M12.586 2.586A2 2 0 0 0 11.172 2H4a2 2 0 0 0-2 2v7.172a2 2 0 0 0 .586 1.414l8.704 8.704a2.426 2.426 0 0 0 3.42 0l6.58-6.58a2.426 2.426 0 0 0 0-3.42z"/><circle cx="7.5" cy="7.5" r=".5" fill="currentColor"/>',
    list: '<path d="M3 12h.01M3 18h.01M3 6h.01M8 12h13M8 18h13M8 6h13"/>',
    cornerDownLeft: '<path d="M20 4v7a4 4 0 0 1-4 4H4"/><path d="m9 10-5 5 5 5"/>',
    mic: '<path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2M12 19v3"/>',
  });

  // ---------- state ----------
  const firstId = D.invites.length ? D.invites[0].id : null;
  const app = { view: null, callId: firstId, alertId: null, slug: null, mapView: "all", liveCall: firstId, liveSkin: "meet", started: false };
  const runs = {};   // per call id, kept for the session: { ctx, states, ticks, tab, notes, changes, claude, error }
  const inputs = {}; // per call id: { versionFile, since } — also saved for the in-call panel
  let runningId = null;
  const readAlerts = new Set();
  let mapInstance = null;
  let personMap = null; // the connection map on a person's page (profile.js)
  D.invites.forEach((inv) => { inputs[inv.id] = store.get("inputs:" + inv.id) || { versionFile: inv.versionFile || "", since: inv.backstageSince || null }; });

  const inviteById = C.inviteById;
  const slug = (s) => String(s).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  const announce = (t) => { const el = $("#announce"); el.textContent = ""; setTimeout(() => { el.textContent = t; }, 50); };
  const isOnCall = (id) => app.view === "call" && app.callId === id;
  const companyNames = () => Array.from(new Set(D.invites.map((i) => i.company).concat(Object.keys(D.companies))));
  const companyBySlug = (s) => companyNames().find((n) => slug(n) === s) || null;
  const callForCompany = (name) => D.invites.find((i) => i.company === name) || null;
  const today = () => { const [y, m, d] = D.today.split("-").map(Number); return new Date(y, m - 1, d); };
  // Live invites carry their start (ET, ISO), so a call in January is read as next year's.
  const callDate = (inv) => { const w = splitWhen(inv.when); return new Date(+String(inv.start || D.today).slice(0, 4), MONTHS.indexOf(w.month), +w.date); };
  const daysUntil = (inv) => Math.round((callDate(inv) - today()) / 864e5);
  const relDay = (n) => (n === 0 ? "today" : n === 1 ? "tomorrow" : n < 0 ? plural(-n, "day") + " ago" : "in " + plural(n, "day"));
  const longDay = (inv) => callDate(inv).toLocaleDateString("en-US", { weekday: "long", month: "short", day: "numeric" });

  // Alerts with stable ids for links: job change / come back are sample, the security wave is public.
  function alerts() {
    return C.allAlerts().map((a) => Object.assign({}, a, { id: a.id === "security" ? "security-notices" : slug(a.title) }));
  }
  const unreadCount = () => alerts().filter((a) => !readAlerts.has(a.id)).length;
  // Settings > Alert rules: "daily digest" groups a day's alerts into one; quiet hours hold the badge and pop-ups back.
  const digestOn = () => !!(C.prefs() && C.prefs().alerts.delivery === "digest");
  function quietUntil() {
    const q = C.prefs() && C.prefs().alerts.quiet;
    if (!q || !q.on) return "";
    const mins = (t) => +t.slice(0, 2) * 60 + +t.slice(3), now = new Date(), n = now.getHours() * 60 + now.getMinutes(), a = mins(q.from), b = mins(q.to);
    return (a <= b ? n >= a && n < b : n >= a || n < b) ? q.to : "";
  }
  // The number on the Alerts badge: unread alerts, or unread digests (one per day) in digest mode.
  const badgeCount = () => (digestOn() ? new Set(alerts().filter((a) => !readAlerts.has(a.id)).map((a) => a.date)).size : unreadCount());

  // ---------- small shared bits ----------
  const srcKind = (label) => (/^Public/.test(label) ? "public" : /^Sample/.test(label) ? "sample" : /^(Your calendar|Your transcript|Overture records|HubSpot|Gong)/.test(label) ? "yours" : "guess");
  function srcTag(label) {
    return '<span class="src ' + srcKind(label) + '">' + esc(label) + "</span>";
  }
  const srcDot = (label) => '<span class="src ' + (srcKind(label) === "guess" ? "sample" : srcKind(label)) + '" title="' + esc(label) + '"><span class="sr-only">' + esc(label) + "</span></span>";
  function prepState(id) {
    if (runningId === id) return "run";
    const r = runs[id];
    if (!r) return "none";
    if (r.error) return "err";
    return r.ctx && r.ctx.done ? "done" : "none";
  }
  function prepChip(id) {
    const s = prepState(id);
    const r = runs[id];
    const n = r && r.states ? Object.values(r.states).filter((x) => x.state !== "run").length : 0;
    const body = { none: ic("circleDashed") + "Not prepped", run: ic("loader", "spin") + "Working " + n + "/" + C.STEP_DEFS.length, done: ic("circleCheck") + "Brief ready", err: ic("circleAlert") + "Stopped" }[s];
    const tag = { none: "tag-gray", run: "tag-blue", done: "tag-green", err: "tag-red" }[s];
    return '<span class="prep ' + s + " " + tag + '" data-prep="' + esc(id) + '">' + body + "</span>";
  }
  const patchPrep = (id) => $$('[data-prep="' + id + '"]').forEach((el) => { el.outerHTML = prepChip(id); });
  const dateTile = (inv) => { const w = splitWhen(inv.when); return '<span class="tile-date" aria-hidden="true"><span class="m">' + esc(w.month) + '</span><span class="d">' + esc(w.date) + "</span></span>"; };
  const avatarStack = (inv, size) => '<span class="stack" aria-hidden="true" title="' + esc(inv.attendees.map((a) => a.name).join(", ")) + '">' + inv.attendees.slice(0, 3).map((a) => avatar(a, size || "sm")).join("") + "</span>";
  const fromHubspot = (c, field) => !!(c && c.src && c.src[field] === "HubSpot");
  const dealsHtml = (deals) => '<ul class="deals" role="list">' + deals.slice(0, 4).map((d) => '<li><span class="deal-name">' + esc(d.name) + "</span>"
    + '<span class="deal-meta">' + esc([d.stage, C.money(d.amount), d.closeDate ? (d.closed ? "closed " : "closes ") + fmtDate(d.closeDate) : ""].filter(Boolean).join(" · ")) + "</span></li>").join("") + "</ul>";
  const statusTag = (status) => '<span class="pill ' + tagFor("status", status) + '">' + esc(String(status).replace(/: .*/, "")) + "</span>";
  // List-page header: title, source tag, actions, then one line under it. icon and tint are kept for callers but no longer drawn (no decorative tile).
  const pageHead = (icon, tint, title, src, sub, actions) => '<header class="page-head"><div class="page-head-row">'
    + '<h1 class="page-title" tabindex="-1">' + esc(title) + "</h1>" + (src ? srcTag(src) : "") + '<span class="grow"></span>' + (actions || "") + "</div>"
    + (sub ? '<p class="page-sub">' + sub + "</p>" : "") + "</header>";
  const names = (inv) => { const n = inv.attendees.map((a) => a.name); return n.length > 1 ? n.slice(0, -1).join(", ") + " and " + n[n.length - 1] : n[0]; };
  const kindOf = (inv) => inv.title.split(":")[0];

  // ---------- toast (only for "brief ready" while you are elsewhere) ----------
  let toastTimer = null;
  function toast(text, actionLabel, href) {
    const el = $("#toast");
    el.innerHTML = '<span class="toast-text">' + esc(text) + "</span>" + (actionLabel ? '<button type="button" class="btn secondary sm" data-toast-go="' + esc(href) + '">' + esc(actionLabel) + "</button>" : "")
      + '<button type="button" class="x" data-toast-close aria-label="Dismiss">' + ic("x") + "</button>";
    el.hidden = false;
    clearTimeout(toastTimer);
    const arm = () => { toastTimer = setTimeout(() => { el.hidden = true; }, 5000); };
    el.onmouseenter = el.onfocusin = () => clearTimeout(toastTimer);
    el.onmouseleave = el.onfocusout = arm;
    arm();
  }

  // ---------- rail ----------
  function renderNav() {
    const cur = app.view;
    const link = (href, icon, label, right, active) => '<li><a href="' + href + '"' + (active ? ' aria-current="page"' : "") + ">" + ic(icon) + '<span class="label">' + esc(label) + "</span>" + (right || "") + "</a></li>";
    const callsRight = runningId ? '<span class="count">' + ic("loader", "spin") + '<span class="sr-only">agent working</span></span>' : '<span class="count">' + D.invites.length + "</span>";
    const unread = quietUntil() ? 0 : badgeCount();
    $("#navMain").innerHTML = link("#/home", "home", "Home", "", cur === "home")
      + link("#/calls", "phone", "Calls", callsRight, cur === "calls" || cur === "call")
      + link("#/alerts", "bell", "Alerts", unread ? '<span class="count strong">' + unread + '<span class="sr-only"> unread</span></span>' : "", cur === "alerts")
      + link("#/live", "video", "In call", "", cur === "live");
    $("#navRecords").innerHTML = link("#/companies", "building", "Companies", '<span class="count">' + companyNames().length + "</span>", cur === "companies" || cur === "company")
      + link("#/map", "network", "People", '<span class="count">' + Object.keys(D.people).length + "</span>", cur === "map" || cur === "people");
    // Asana's sidebar projects: this week's calls, each with its company colour.
    $("#navWeekLabel").hidden = !D.invites.length;
    $("#navWeek").innerHTML = D.invites.map((i) => '<li><a href="#/calls/' + i.id + '" title="' + esc(i.company + ", " + splitWhen(i.when).day) + '"' + (cur === "call" && app.callId === i.id ? ' aria-current="page"' : "")
      + '><span class="sq" aria-hidden="true" style="background:' + C.solid(i.company) + '">' + esc(i.company.charAt(0)) + '</span><span class="label">' + esc(i.company) + '</span><span class="count">' + esc(splitWhen(i.when).day.slice(0, 3)) + "</span></a></li>").join("");
    $("#navFoot").innerHTML = link("#/settings", "settings", "Settings", "", cur === "settings" || cur === "guides")
      + link("#/data", "database", "Data", '<span class="status">' + (C.state.liveData ? "Live" : "Saved") + "</span>", cur === "data");
  }

  // ---------- router ----------
  const TITLES = { home: "Home", calls: "Calls", alerts: "Alerts", companies: "Companies", map: "People map", people: "Person", live: "In-call panel", data: "Data", settings: "Settings" };
  function parse() {
    const h = location.hash;
    if (!h.startsWith("#/")) return null;
    const p = h.slice(2).split("/").filter(Boolean);
    if (!p.length || p[0] === "home") return { view: "home" };
    if (p[0] === "calls") return p[1] && inviteById(p[1]) ? { view: "call", callId: p[1], tab: p[2] === "after" ? "after" : "brief" } : { view: "calls" };
    if (p[0] === "alerts") return { view: "alerts", alertId: p[1] || null };
    if (p[0] === "companies") return p[1] ? { view: "company", slug: p[1] } : { view: "companies" };
    if (p[0] === "people") return p[1] ? { view: "people", key: p[1] } : { view: "map" }; // #/people/<key>: one guest's profile (the key is never their email)
    if (p[0] === "settings") return { view: "settings", menu: p[1] || null };
    if (p[0] === "guides") return { view: "guides", guide: p[1] || null }; // setup guides drawn from docs/*.md
    if (["map", "live", "data"].includes(p[0])) return { view: p[0] };
    return { view: "home", bad: true };
  }
  function go(hash, replace) {
    if (replace) { history.replaceState(null, "", hash); route(); }
    else location.hash = hash;
  }
  function route() {
    const r = parse();
    if (!r) { if (!location.hash || location.hash === "#") go("#/home", true); return; } // in-page anchors are handled by data-jump
    if (r.bad) { go("#/home", true); return; }
    // Leaving a page closes its dialogs, so the drawer can never edit a call that is no longer on screen.
    ["#palette", "#drawer", "#checkDialog", "#tlDialog"].forEach((s) => { if ($(s).open) $(s).close("cancel"); });
    closeNav();
    editingPerson = null;
    editingCompany = null;
    if (mapInstance && r.view !== "map") { mapInstance.destroy(); mapInstance = null; }
    if (personMap) { personMap.destroy(); personMap = null; }
    app.view = r.view;
    app.personKey = r.key || null;
    if (r.callId) app.callId = r.callId;
    app.alertId = r.alertId || null;
    app.slug = r.slug || null;
    $$("[data-view]").forEach((s) => { s.hidden = s.dataset.view !== r.view; });
    document.body.dataset.page = r.view; // not data-view: that attribute marks the page sections
    if ($("#palette").open) $("#palette").close();
    // Each page arrives with a short rise; later re-renders on the same page stay still.
    const shown = $('[data-view="' + r.view + '"]');
    shown.classList.remove("enter"); void shown.offsetWidth; shown.classList.add("enter");
    clearTimeout(app.enterTimer); app.enterTimer = setTimeout(() => shown.classList.remove("enter"), 900);
    let title = TITLES[r.view] || "";
    if (r.view === "home") renderHome();
    else if (r.view === "calls") renderCallsPage();
    else if (r.view === "call") {
      const run = runs[r.callId], inv = inviteById(r.callId);
      // #/calls/<id>/after, or a call that already ended: After the call (running the agent first when it hasn't run)
      const wantAfter = r.tab === "after" || (inv.ended && !(run && run.ctx && run.ctx.done));
      if (wantAfter && !(run && run.ctx && run.ctx.done)) openAfter(r.callId);
      if (run && run.ctx && run.ctx.done) run.tab = r.tab === "after" ? "after" : "brief"; // a run still going keeps where it lands
      renderCallView(); title = inv.company;
    }
    else if (r.view === "alerts") { renderAlerts(); const a = alerts().find((x) => x.id === app.alertId); if (a) title = a.title; }
    else if (r.view === "companies") renderCompanies();
    else if (r.view === "company") { const name = companyBySlug(app.slug); if (!name) { go("#/companies", true); return; } renderCompany(name); title = name; }
    else if (r.view === "map") renderMap();
    else if (r.view === "people") { const email = C.emailForKey(app.personKey); if (!email) { go("#/map", true); return; } title = renderPerson(email); }
    else if (r.view === "live") renderLive();
    else if (r.view === "data") renderData();
    else if (r.view === "settings" && window.MoabSettingsPage) title = window.MoabSettingsPage.render(r.menu) || title;
    else if (r.view === "guides" && window.MoabGuides) title = window.MoabGuides.show(r.guide, $('[data-view="guides"]'));
    renderNav();
    placeSearchInput();
    document.title = (title ? title + " · " : "") + "Overture";
    $("#appbarTitle").textContent = title || "Overture";
    $(".main").scrollTop = 0;
    window.scrollTo(0, 0);
    if (app.started) {
      const h = (r.view === "alerts" && app.alertId && $(".alert-h")) || $('[data-view="' + r.view + '"] h1, [data-view="' + r.view + '"] .page-title, [data-view="' + r.view + '"] h2[tabindex]');
      if (h) h.focus({ preventScroll: true });
    }
    app.started = true;
  }

  // ---------- home ----------
  function greeting() { const h = new Date().getHours(); return (h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening") + (ME.first ? ", " + ME.first : ""); }
  // The greeting as HTML: the name gets the gradient (Asana's headline type).
  function greetingHtml() { const g = greeting(), i = g.indexOf(", "); return i < 0 ? esc(g) : esc(g.slice(0, i + 2)) + '<span>' + esc(g.slice(i + 2)) + "</span>"; }

  // First run (no calendar yet). Mobbin refs: Notion Calendar's "Connect your calendar" card (two logos, one line, one button),
  // Calendly's provider row (tile, name, account line, Connect on the right), Tana's quiet "Skip for now" link under it,
  // Clockwise's plain explanation of what it reads. Refs at the top of home.css.
  function connectCard() {
    const st = C.state, err = window.MOAB_LIVE_ERROR;
    const bot = ($(".brand .logo") || { outerHTML: "" }).outerHTML.replace(/moabCut/g, "moabCutConnect");
    let action, note = "";
    if (!st.server) {
      action = '<span class="btn primary" aria-disabled="true">Connect Google Calendar</span>';
      note = "Overture's server isn't answering, or an older copy is running. Restart <code>server.py</code>, then reload this page.";
    } else if (!st.google.configured) {
      action = '<span class="btn primary" aria-disabled="true">Connect Google Calendar</span>';
      note = 'Google sign-in isn\'t set up on this PC yet. <a href="#/guides/google">Set it up in a few steps</a>' + ", then restart <code>server.py</code>.";
    } else {
      action = '<a class="btn primary" href="/auth/google">' + (st.google.connected ? "Connect again" : "Connect Google Calendar") + "</a>";
      if (err) note = "Google Calendar didn't answer: " + esc(err) + ' <a href="#/home" data-reload="1">Try again</a>';
    }
    return '<section class="widget span-2 connect" aria-labelledby="connectH"><div class="connect-art" aria-hidden="true">' + bot
      + '<span class="connect-swap">' + ic("arrowRight") + '</span><span class="connect-cal">' + ic("calendar") + "</span></div>"
      + '<h2 id="connectH" class="connect-title">Connect your calendar</h2>'
      + '<p class="connect-sub">Overture reads your upcoming calls and preps each one: who is on it, what changed since you last met, and how to open.</p>'
      + '<div class="connect-provider"><span class="connect-tile" aria-hidden="true">' + ic("calendar") + '</span><span class="connect-pt"><span class="connect-name">Google Calendar</span>'
      + '<span class="connect-acct">' + esc(st.google.email || "Read-only · the next 14 days") + "</span></span>" + action + "</div>"
      + (note ? '<p class="connect-note" role="status">' + note + "</p>" : "")
      + '<p class="connect-privacy">' + ic("shield") + "<span>Read-only calendar access. Your calls, notes and records stay " + savedWhere() + ".</span></p>"
      + '<a class="connect-skip" href="?demo=1#/home">Look around with sample data</a></section>';
  }
  function noCallsCard() {
    return '<section class="widget span-2 empty-calls" aria-labelledby="noCallsH"><h2 id="noCallsH">No calls in the next 14 days</h2>'
      + "<p>Overture preps events on your Google Calendar that have at least one guest from outside your company. New invites show up here within a minute.</p>"
      + '<a class="btn secondary" href="https://calendar.google.com" target="_blank" rel="noopener">Open Google Calendar' + NEW_TAB + "</a></section>";
  }

  // Up next: when, who (faces), what the invite says, and whether the brief is ready (Mobbin refs at the top of home.css).
  // The phone on the right is this call: it buzzes only while the card is hovered or has focus.
  function heroCard(inv) {
    const run = runs[inv.id], s = prepState(inv.id), w = splitWhen(inv.when), c = D.companies[inv.company];
    const top = run && run.ctx && run.ctx.done ? run.ctx.products[0] : null;
    const m = w.time.match(/(\d+):(\d+) to (\d+):(\d+)/);
    const mins = m ? (((+m[3] * 60 + +m[4]) - (+m[1] * 60 + +m[2])) + 1440) % 1440 : 0; // a call can cross midnight ET
    const heads = alerts().filter((a) => a.callId === inv.id && a.kind !== "Mentioned"); // people mentioned stay on the Alerts page
    const people = inv.attendees.map((a) => {
      const role = (D.people[a.email] || {}).title;
      return '<li class="up-person">' + avatar(a, "md") + '<span class="up-person-txt"><span class="up-person-name">' + esc(a.name) + "</span>"
        + (role ? '<span class="up-person-role">' + esc(role) + "</span>" : "") + "</span></li>";
    }).join("");
    let quote, note, actions;
    if (s === "done") {
      quote = '<p class="cap">Open the call with</p><p class="up-opener">' + esc(run.ctx.opener) + "</p>";
      note = top && top.score > 0 ? "Best fit: " + esc(top.name) : "";
      actions = '<a class="btn ghost" href="#/live">In-call panel</a><a class="btn ghost" href="#/calls/' + inv.id + '/after">After the call</a>'
        + '<a class="btn primary" href="#/calls/' + inv.id + '">Open brief</a>';
    } else {
      quote = '<p class="cap">From the invite</p><p>' + esc(inv.notes || "No description in the invite.") + "</p>";
      note = s === "run" ? "" : s === "err" ? "The agent stopped before it finished." : C.STEP_DEFS.length + " checks, a few seconds";
      actions = s === "run" ? '<a class="btn secondary" href="#/calls/' + inv.id + '">Watch it work</a>'
        : '<a class="btn ghost" href="#/calls/' + inv.id + '">Open call</a>'
          + '<button type="button" class="btn primary" data-run="' + inv.id + '"' + (runningId ? " disabled" : "") + ">" + (s === "err" ? "Try again" : "Run the agent") + "</button>";
    }
    return '<article class="widget hero up" aria-labelledby="heroName"><div class="up-main">'
      + '<p class="up-when"><span class="up-label">Up next</span><span class="up-day">' + esc(longDay(inv)) + " · " + esc(relDay(daysUntil(inv))) + '</span><span class="grow"></span>' + srcTag(SRC.calendar) + "</p>"
      + '<div class="up-title"><h2 class="up-name" id="heroName">' + esc(inv.company) + "</h2>" + (c ? statusTag(c.status) : "") + C.priorityBadge(inv.company) + "</div>"
      + '<p class="up-meta">' + esc([w.time, mins ? mins + " min" : "", kindOf(inv)].filter(Boolean).join(" · ")) + "</p>"
      + '<ul class="up-people" role="list" aria-label="On the call">' + people + "</ul>"
      + (heads.length ? '<p class="up-heads">' + heads.map((a) => '<a href="#/alerts/' + esc(a.id) + '">' + esc(a.title) + "</a>").join("") + "</p>" : "")
      + '<div class="up-quote">' + quote + "</div></div>"
      + '<div class="up-foot"><div class="up-ready">' + prepChip(inv.id) + (note ? '<span class="up-note">' + note + "</span>" : "") + "</div>"
      + '<div class="up-actions">' + actions + "</div></div></article>";
  }

  function beforeBox() {
    const items = [];
    D.invites.filter((inv) => !inv.ended).forEach((inv) => {
      const r = runs[inv.id];
      if (r && r.ctx && r.ctx.done) r.ctx.todos.forEach((t) => items.push({ inv, t, done: r.ticks.has(t.text) }));
    });
    if (!items.length) return "";
    const done = items.filter((i) => i.done).length;
    const waiting = D.invites.filter((inv) => !inv.ended && !(runs[inv.id] && runs[inv.id].ctx && runs[inv.id].ctx.done));
    return '<section class="home-block widget span-2 h-todos" aria-labelledby="beforeH"><div class="widget-head"><h2 id="beforeH">Before your calls</h2><span class="widget-count done-count">' + done + " of " + items.length + " done</span>"
      + '<span class="grow"></span>' + srcTag(SRC.records) + "</div>"
      + items.map((i) => '<label class="todo-item"><input type="checkbox" data-call="' + esc(i.inv.id) + '" data-todo="' + esc(i.t.text) + '"' + (i.done ? " checked" : "") + '><span class="t">' + esc(i.t.text)
        + "<small>" + esc(i.inv.company + " · " + splitWhen(i.inv.when).day) + "</small></span>" + (i.t.src ? srcTag(i.t.src) : "<span></span>") + "</label>").join("")
      + waiting.map((inv) => '<p class="no-list">' + esc(inv.company) + ': no list yet. <a href="#/calls/' + inv.id + '">Open call</a></p>').join("") + "</section>";
  }

  function callRow(inv) {
    const w = splitWhen(inv.when), c = D.companies[inv.company], nA = C.alertsFor(inv.id).length;
    return '<a class="row call-row" href="#/calls/' + inv.id + '">' + dateTile(inv)
      + '<span class="one-line"><span class="row-title">' + esc(inv.company) + '</span><br><span class="row-sub">' + esc([w.start, kindOf(inv), c ? c.status : ""].filter(Boolean).join(" · ")) + "</span></span>"
      + avatarStack(inv, "xs")
      + (nA ? '<span class="bell">' + ic("bell") + nA + '<span class="sr-only"> ' + (nA === 1 ? "alert" : "alerts") + "</span></span>" : "<span></span>")
      + prepChip(inv.id) + ic("chevron", "chev") + "</a>";
  }

  function alertRow(a) {
    const unread = !readAlerts.has(a.id);
    const reason = a.kind === "Security" ? a.text.split(".")[0] : a.kind + " · " + a.text.split(".")[0];
    return '<a class="row alert-row' + (unread ? " unread" : "") + '" href="#/alerts/' + esc(a.id) + '"' + (app.alertId === a.id ? ' aria-current="page"' : "") + ">"
      + '<span class="icon-tile ' + tagFor("alert", a.kind) + '">' + ic(a.icon) + '</span><span class="one-line"><span class="alert-title">' + (unread ? '<span class="sr-only">Unread: </span>' : "") + esc(a.title) + '</span><span class="row-sub alert-reason">' + esc(reason) + "</span></span>"
      + '<span class="row-right">' + esc(a.date) + srcDot(a.src) + (unread ? '<span class="unread-dot" aria-hidden="true"></span>' : "") + "</span></a>";
  }

  // Home's own rows (Rox's Today list, Linear's inbox): no chevrons, bells or kind icons; counts and kinds are words.
  function laterRow(inv) {
    const w = splitWhen(inv.when), nA = C.alertsFor(inv.id).length;
    return '<a class="row h-call" href="#/calls/' + inv.id + '">' + dateTile(inv)
      + '<span class="h-txt"><span class="row-title">' + esc(inv.company) + '</span><span class="row-sub">' + esc([w.start, kindOf(inv)].join(" · ")) + (nA ? " · " + plural(nA, "alert") : "") + "</span></span>"
      + avatarStack(inv, "sm") + C.priorityBadge(inv.company) + prepChip(inv.id) + "</a>";
  }
  function homeAlertRow(a) {
    const unread = !readAlerts.has(a.id);
    const reason = a.kind === "Security" ? a.text.split(".")[0] : a.kind + " · " + a.text.split(".")[0];
    return '<a class="row h-alert' + (unread ? " unread" : "") + '" href="#/alerts/' + esc(a.id) + '"><span class="h-dot" aria-hidden="true"></span>'
      + '<span class="h-txt"><span class="row-title">' + (unread ? '<span class="sr-only">Unread: </span>' : "") + esc(a.title) + '</span><span class="row-sub">' + esc(reason) + "</span></span>"
      + '<span class="row-right">' + esc(a.date) + srcDot(a.src) + "</span></a>";
  }

  // Home's alert rows, or in digest mode one card per day with the alerts grouped by kind.
  function homeAlertsBody(list) {
    const quiet = quietUntil(), note = quiet ? '<p class="quiet-note">' + ic("bell") + "<span>Quiet hours until " + esc(quiet) + ". Alerts still arrive; the badge waits.</span></p>" : "";
    if (!digestOn()) return note + '<div class="rows">' + list.map(homeAlertRow).join("") + "</div>";
    const days = [];
    list.forEach((a) => { let d = days.find((x) => x.date === a.date); if (!d) days.push(d = { date: a.date, items: [] }); d.items.push(a); });
    days.sort((x, y) => ibTime(y.items[0]) - ibTime(x.items[0]));
    return note + '<div class="rows">' + days.slice(0, 3).map((d) => {
      const kinds = {}, unread = d.items.filter((a) => !readAlerts.has(a.id)).length;
      d.items.forEach((a) => { kinds[a.kind] = (kinds[a.kind] || 0) + 1; });
      return '<a class="row h-alert digest' + (unread ? " unread" : "") + '" href="#/alerts/' + esc(d.items[0].id) + '"><span class="h-dot" aria-hidden="true"></span>'
        + '<span class="h-txt"><span class="row-title">' + (unread ? '<span class="sr-only">Unread: </span>' : "") + "Daily digest · " + esc(d.date) + "</span>"
        + '<span class="row-sub">' + esc(Object.entries(kinds).map(([k, n]) => n + " " + k.toLowerCase()).join(" · ")) + "</span></span>"
        + '<span class="row-right">' + plural(d.items.length, "alert") + "</span></a>";
    }).join("") + "</div>";
  }

  function renderHome() {
    const [next, ...later] = D.invites.filter((i) => !i.ended); // calls that just ended stay listed (After the call), not here
    const sec = $('[data-view="home"]');
    if (!next) return renderHomeEmpty(sec);
    const keep = document.activeElement && sec.contains(document.activeElement) ? document.activeElement.dataset.todo || document.activeElement.getAttribute("href") : null;
    const ready = D.invites.filter((i) => !i.ended && prepState(i.id) === "done").length, unread = unreadCount();
    // Shopify, Tana and Perplexity put one big ask/search box under the greeting, with quick actions under it (Mobbin).
    const bot = ($(".brand .logo") || { outerHTML: "" }).outerHTML.replace(/moabCut/g, "moabCutAsk");
    const chip = (attrs, label, n) => '<li><button type="button" class="home-chip" ' + attrs + ">" + label + (n != null ? '<b>' + n + "</b>" : "") + "</button></li>";
    const nextReady = prepState(next.id) === "done";
    sec.innerHTML = '<div class="home-hero">' + heroWeb(next, later) + '<header class="home-header"><p class="eyebrow">' + esc(today().toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" })) + "</p>"
      + '<h1 class="page-title" tabindex="-1">' + greetingHtml() + "</h1>"
      + '<div class="home-ask search-field" id="homeAsk" role="search">' + bot + "<kbd>/</kbd></div>"
      + '<ul class="home-chips" role="list" aria-label="Quick actions">'
      + chip('data-go="#/calls/' + next.id + '"', nextReady ? "Open the " + esc(next.company) + " brief" : "Prep " + esc(next.company), null)
      + chip('data-go="#/calls"', DEMO ? "Calls this week" : "Upcoming calls", D.invites.filter((i) => !i.ended).length)
      + chip('data-go="#/alerts"', "New alerts", unread)
      + chip('data-check="1"', "Check a company", null) + "</ul></header></div>"
      + '<div class="home-grid">' + heroCard(next)
      + beforeBox()
      + '<section class="home-block widget" aria-labelledby="laterH"><div class="widget-head"><h2 id="laterH">' + (DEMO ? "Later this week" : "Coming up") + '</h2><span class="grow"></span><a class="more" href="#/calls">All calls</a></div>'
      + '<div class="rows">' + (later.length ? C.byPriority(later, (i) => i.company).map(laterRow).join("") : '<p class="rows-empty">No other calls in the next 14 days.</p>') + "</div></section>"
      + '<section class="home-block widget" aria-labelledby="alertsH"><div class="widget-head"><h2 id="alertsH">Alerts</h2><span class="widget-count">' + (unread ? unread + " new" : "All read") + '</span><span class="grow"></span><a class="more" href="#/alerts">View all</a></div>'
      + homeAlertsBody(alerts()) + "</section></div>";
    if (keep) { const el = sec.querySelector('[data-todo="' + CSS.escape(keep) + '"], [href="' + CSS.escape(keep) + '"]'); if (el) el.focus({ preventScroll: true }); }
    placeSearchInput();
    requestAnimationFrame(drawHeroLines);
  }

  // The hero's cards (Asana's sign-in page): what Overture is connecting right now, from the real data. Decorative copies of
  // things shown below, so they are hidden from screen readers and skipped by Tab.
  function heroWeb(next, later) {
    const w = splitWhen(next.when), list = alerts(), a = list.find((x) => !readAlerts.has(x.id)) || list[0];
    const co = later[0] ? later[0].company : null, cc = co ? D.companies[co] || {} : {};
    const ready = D.invites.filter((i) => !i.ended && prepState(i.id) === "done").length, total = D.invites.filter((i) => !i.ended).length;
    const first = (n) => esc(String(n).split(" ")[0]);
    const who = (inv) => inv.attendees.length ? first(inv.attendees[0].name) + (inv.attendees.length > 1 ? " +" + (inv.attendees.length - 1) : "") : "";
    const label = (tone, text) => '<span class="hw-label ' + tone + '"><i aria-hidden="true"></i>' + esc(text) + "</span>";
    const card = (cls, href, top, main, foot) => '<a class="hw-card ' + cls + '" href="' + href + '" tabindex="-1"><span class="hw-top">' + top + '</span><span class="hw-main">' + main + '</span><span class="hw-foot">' + foot + "</span></a>";
    const text = (t, sub) => '<span class="hw-txt"><span class="hw-t">' + t + "</span>" + (sub ? '<span class="hw-s">' + sub + "</span>" : "") + "</span>";
    let alertCard = "";
    if (a) {
      const name = a.kind === "Job change" ? a.title.split(" moved")[0] : "";
      const face = name ? D.invites.flatMap((i) => i.attendees).find((p) => p.name === name) : null;
      alertCard = card("hw-b", "#/alerts/" + a.id, label(a.kind === "Security" ? "tone-red" : a.kind === "Job change" ? "tone-pink" : "tone-teal", a.kind) + '<span class="hw-meta">' + esc(a.date) + "</span>",
        (face ? avatar(face, "lg") : coTile(a.title, "co-tile-md")) + text(esc(a.title), ""),
        '<span class="hw-note">' + esc(a.text.split(". ")[0]) + ".</span>");
    }
    // A ring for how many briefs are ready, drawn in the hero gradient.
    const pct = total ? ready / total : 0, C2 = 2 * Math.PI * 17;
    const ring = '<svg class="hw-ring" viewBox="0 0 40 40" aria-hidden="true"><defs><linearGradient id="hwRing" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#1ed760"/><stop offset="1" stop-color="#ee6b9a"/></linearGradient></defs>'
      + '<circle cx="20" cy="20" r="17" class="hw-ring-track"/><circle cx="20" cy="20" r="17" class="hw-ring-fill" stroke-dasharray="' + (C2 * pct).toFixed(1) + " " + C2.toFixed(1) + '"/>'
      + '<text x="20" y="24" text-anchor="middle">' + ready + "/" + total + "</text></svg>";
    return '<div class="hero-web" aria-hidden="true"><svg class="hw-lines"></svg>'
      + '<a class="hw-cluster" href="#/calls/' + next.id + '" tabindex="-1">' + next.attendees.slice(0, 3).map((p) => avatar(p, "lg")).join("") + "</a>"
      + card("hw-a", "#/calls/" + next.id, label("tone-indigo", "Up next") + '<span class="hw-meta">' + esc(relDay(daysUntil(next))) + "</span>",
        coTile(next.company, "co-tile-md") + text(esc(next.company), esc(w.day + " · " + w.start.replace(/ ET$/, "") + " ET")),
        avatarStack(next, "xs") + '<span class="hw-note">' + who(next) + " · " + esc(kindOf(next)) + "</span>")
      + alertCard
      + (co ? card("hw-c", "#/companies/" + slug(co), label("tone-purple", String(cc.status || "Prospect").replace(/: .*/, "")) + (cc.engineers ? '<span class="hw-meta">' + cc.engineers + " engineers</span>" : ""),
        coTile(co, "co-tile-md") + text(esc(co), esc(splitWhen(later[0].when).day + " · " + kindOf(later[0]))),
        avatarStack(later[0], "xs") + '<span class="hw-note">' + plural(later[0].attendees.length, "person", "people") + " on the call</span>") : "")
      + card("hw-d", "#/calls", label("tone-green", "Your week") + '<span class="hw-meta">' + plural(total, "call") + "</span>",
        ring + text(ready ? plural(ready, "brief") + " ready" : "Nothing prepped yet", ready === total ? "You're set for the week" : plural(total - ready, "call") + " left to prep"),
        '<span class="hw-squares">' + D.invites.filter((i) => !i.ended).map((i) => '<span style="background:' + C.solid(i.company) + '">' + esc(i.company.charAt(0)) + "</span>").join("") + '</span><span class="hw-note">' + D.invites.map((i) => esc(splitWhen(i.when).day.slice(0, 3))).join(" · ") + "</span>")
      + "</div>";
  }
  // The same hero before any calls exist: what Overture already knows from public data, and the one step left.
  function heroWebPublic() {
    const sec = alerts().find((a) => a.kind === "Security"), latest = C.state.latest, n = C.state.adopters.length;
    const tile = (bg, icon) => '<span class="co-tile-md" style="background:' + bg + ';color:#fff">' + ic(icon) + "</span>";
    const label = (tone, text) => '<span class="hw-label ' + tone + '"><i aria-hidden="true"></i>' + esc(text) + "</span>";
    const card = (cls, href, top, main, foot) => '<a class="hw-card ' + cls + '" href="' + href + '" tabindex="-1"><span class="hw-top">' + top + '</span><span class="hw-main">' + main + '</span><span class="hw-foot"><span class="hw-note">' + foot + "</span></span></a>";
    const text = (t, sub) => '<span class="hw-txt"><span class="hw-t">' + t + '</span><span class="hw-s">' + sub + "</span></span>";
    const dot = (bg, icon) => '<span class="avatar lg hw-ic" style="background:' + bg + ';color:#fff">' + icon + "</span>";
    const bot = ($(".brand .logo") || { outerHTML: "" }).outerHTML.replace(/moabCut/g, "moabCutHero");
    return '<div class="hero-web" aria-hidden="true"><svg class="hw-lines"></svg>'
      + '<a class="hw-cluster" href="#/data" tabindex="-1">' + dot("#fff", bot) + dot("#3b7ddd", ic("calendar")) + dot("#d93a4e", ic("shield")) + "</a>"
      + (LIVE_MODE
        ? card("hw-a", "#/calls", label("tone-indigo", "Calendar") + '<span class="hw-meta">Connected</span>', tile("#3b7ddd", "calendar") + text("No outside calls", "in the next 14 days"), "New calls show up here, prepped")
        : card("hw-a", "#/home", label("tone-indigo", "Step 1") + '<span class="hw-meta">2 minutes</span>', tile("#3b7ddd", "calendar") + text("Connect your calendar", "Read-only · next 14 days"), "Your calls appear here, ready to prep"))
      + (sec ? card("hw-b", "#/alerts/" + sec.id, label("tone-red", "Security") + '<span class="hw-meta">' + esc(sec.date) + "</span>", tile("#d93a4e", "shield") + text(esc(sec.title), "GitHub security advisories"), esc(sec.text.split(". ")[0]) + ".") : "")
      + card("hw-c", "#/data", label("tone-teal", "Latest release") + '<span class="hw-meta">' + esc(fmtDate(latest.date)) + "</span>", tile("#14a39a", "tag") + text("Backstage " + esc(latest.version), "versions.backstage.io"), "Teams on older versions fall behind on fixes")
      + card("hw-d", "#/data", label("tone-green", "Public data") + '<span class="hw-meta">ADOPTERS.md</span>', tile("#3f9466", "list") + text(n.toLocaleString("en-US") + " adopters", "on the Backstage adopters list"), "Ask Overture to check any company against it")
      + "</div>";
  }
  // Square lines with round bends and end dots between the hero cards (the same drawing as the people map).
  function drawHeroLines() {
    const web = $(".hero-web"), svg = web && $(".hw-lines", web);
    if (!svg || !web.offsetParent || getComputedStyle(web).display === "none") return;
    const o = web.getBoundingClientRect(), box = (sel) => {
      const el = $(sel, web); if (!el) return null;
      // Cards are tilted: use their untilted layout box so the line ends sit on the card edges. The face cluster isn't tilted.
      if (sel === ".hw-cluster") { const r = el.getBoundingClientRect(); return { l: r.left - o.left, r: r.right - o.left, t: r.top - o.top, b: r.bottom - o.top, cx: r.left - o.left + r.width / 2, cy: r.top - o.top + r.height / 2 }; }
      const l = el.offsetLeft, t = el.offsetTop, w = el.offsetWidth, h = el.offsetHeight;
      return { l, r: l + w, t, b: t + h, cx: l + w / 2, cy: t + h / 2 };
    };
    const A = box(".hw-a"), B = box(".hw-b"), C = box(".hw-c"), D2 = box(".hw-d"), K = box(".hw-cluster");
    const path = (pts) => {
      let d = "M" + pts[0][0] + " " + pts[0][1];
      for (let i = 1; i < pts.length; i++) {
        const [x0, y0] = pts[i - 1], [x1, y1] = pts[i], nxt = pts[i + 1];
        if (!nxt) { d += " L" + x1 + " " + y1; break; }
        const r = Math.min(30, Math.hypot(x1 - x0, y1 - y0) / 2, Math.hypot(nxt[0] - x1, nxt[1] - y1) / 2);
        const ux = Math.sign(x1 - x0), uy = Math.sign(y1 - y0), vx = Math.sign(nxt[0] - x1), vy = Math.sign(nxt[1] - y1);
        d += " L" + (x1 - ux * r) + " " + (y1 - uy * r) + " Q" + x1 + " " + y1 + " " + (x1 + vx * r) + " " + (y1 + vy * r);
      }
      return d;
    };
    const lines = [], dots = [];
    const flows = [];
    const add = (cls, pts) => {
      const d = path(pts), n = lines.length;
      lines.push('<path class="hw-line ' + cls + '" pathLength="100" style="--i:' + n + '" d="' + d + '"/>');
      flows.push('<path class="hw-flow ' + cls + '" pathLength="100" style="--i:' + n + '" d="' + d + '"/>');
      [pts[0], pts[pts.length - 1]].forEach((p) => dots.push('<circle style="--i:' + n + '" cx="' + p[0] + '" cy="' + p[1] + '" r="3.5"/>'));
    };
    if (A && K) { const mx = (A.r + K.l) / 2; add("hw-pink", [[A.r, A.cy], [mx, A.cy], [mx, K.cy], [K.l, K.cy]]); }
    if (K && B) add("hw-pink", [[K.r, K.cy], [B.cx, K.cy], [B.cx, B.t]]);
    if (A && C) { const my = A.b + (C.t - A.b) / 2; add("hw-grey", [[A.cx, A.b], [A.cx, my], [C.cx, my], [C.cx, C.t]]); }
    if (B && D2) { const my = B.b + (D2.t - B.b) / 2; add("hw-grey", [[B.cx, B.b], [B.cx, my], [D2.cx, my], [D2.cx, D2.t]]); }
    const W = Math.round(o.width), H = Math.round(o.height);
    const defs = '<defs><linearGradient id="hwPink" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="' + W + '" y2="0"><stop offset="0" stop-color="#1ed760"/><stop offset="0.5" stop-color="#1db954"/><stop offset="1" stop-color="#1fdf64"/></linearGradient>'
      + '<linearGradient id="hwSoft" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="0" y2="' + H + '"><stop offset="0" stop-color="#c9c5f7"/><stop offset="1" stop-color="#e3c6dc"/></linearGradient></defs>';
    svg.innerHTML = defs + lines.join("") + '<g class="hw-flows">' + flows.join("") + '</g><g class="hw-dots">' + dots.join("") + "</g>";
    // Draw in only when the page was just opened, not on every re-render or resize.
    svg.classList.toggle("draw", $('[data-view="home"]').classList.contains("enter"));
  }
  addEventListener("resize", () => { if (app.view === "home") drawHeroLines(); });
  // Home with no calls: the connect card (nothing connected) or an empty state (connected, quiet fortnight), plus public alerts.
  const G_LOGO = '<svg class="auth-logo" viewBox="0 0 48 48" aria-hidden="true"><path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z"/><path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 3l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z"/><path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-7.9l-6.5 5C9.5 39.6 16.2 44 24 44z"/><path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.4-.4-3.5z"/></svg>', MS_LOGO = '<svg class="auth-logo" viewBox="0 0 21 21" aria-hidden="true"><rect x="1" y="1" width="9" height="9" fill="#F25022"/><rect x="11" y="1" width="9" height="9" fill="#7FBA00"/><rect x="1" y="11" width="9" height="9" fill="#00A4EF"/><rect x="11" y="11" width="9" height="9" fill="#FFB900"/></svg>';
  // Before a calendar is connected, Home's hero is a sign-in, laid out like Asana's: a big headline, the two
  // providers side by side, "or", an email and Continue. Google is the one that works today; Outlook is marked as coming.
  function connectHero() {
    const st = C.state, ok = st.server && st.google.configured;
    const note = !st.server ? "Overture's server isn't answering, or an older copy is running. Restart <code>server.py</code>, then reload."
      : !st.google.configured ? 'Google sign-in isn\'t set up on this PC yet. <a href="#/guides/google">Set it up in a few steps</a>' + ", then restart <code>server.py</code>." : "";
    return '<p class="eyebrow">' + esc(today().toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" })) + "</p>"
      + '<h1 class="page-title hero-big" tabindex="-1">Every call,<br>prepped by Overture</h1>'
      + '<p class="hero-sub">Connect your calendar and Overture gets you ready for each one.</p>'
      + '<div class="auth-row">' + (ok ? '<a class="auth-btn" href="/auth/google">' + G_LOGO + "<span>Google</span></a>" : '<span class="auth-btn" aria-disabled="true">' + G_LOGO + "<span>Google</span></span>")
      + '<span class="auth-btn" aria-disabled="true" title="Outlook calendar is coming soon">' + MS_LOGO + "<span>Microsoft</span></span></div>"
      + '<div class="auth-or"><span>or</span></div>'
      + '<form class="auth-email" action="/auth/google" method="get"><label class="sr-only" for="authEmail">Work email</label>'
      + '<input id="authEmail" name="login_hint" type="email" placeholder="name@company.com" autocomplete="email"' + (ok ? "" : " disabled") + ">"
      + '<button type="submit" class="auth-go"' + (ok ? "" : " disabled") + ">Continue</button></form>"
      + (note ? '<p class="auth-note" role="status">' + note + "</p>" : "")
      + '<p class="auth-legal">Read-only calendar access. Your calls, notes and records stay ' + savedWhere() + '. <a href="?demo=1#/home">Look around with sample data</a></p>';
  }
  function renderHomeEmpty(sec) {
    const bot = ($(".brand .logo") || { outerHTML: "" }).outerHTML.replace(/moabCut/g, "moabCutAsk");
    const list = alerts(), unread = unreadCount();
    sec.innerHTML = '<div class="home-hero' + (LIVE_MODE ? "" : " hero-xl") + '">' + heroWebPublic() + '<header class="home-header">'
      + (LIVE_MODE ? '<p class="eyebrow">' + esc(today().toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" })) + "</p>"
        + '<h1 class="page-title" tabindex="-1">' + greetingHtml() + "</h1>"
        + '<div class="home-ask search-field" id="homeAsk" role="search">' + bot + "<kbd>/</kbd></div>" : connectHero()) + "</header></div>"
      + '<div class="home-grid">' + (LIVE_MODE ? noCallsCard() : "")
      + (list.length ? '<section class="home-block widget span-2" aria-labelledby="alertsH"><div class="widget-head"><h2 id="alertsH">Alerts</h2><span class="widget-count">' + (unread ? unread + " new" : "All read") + '</span><span class="grow"></span><a class="more" href="#/alerts">View all</a></div>'
        + homeAlertsBody(list) + "</section>" : "") + "</div>";
    placeSearchInput();
    requestAnimationFrame(drawHeroLines);
  }

  // ---------- calls page: a week calendar (Mobbin references at the top of calendar.css) ----------
  // Week grid when the page is 1000px or wider, an agenda by day below that (calendar.css switches them). Times are ET, like the invites.
  const CAL = { week: 0, hour: 120, start: 9, end: 17, view: "week" }; // week offset from the demo's week, px per hour, visible hours, week | priority
  function etHours() {
    const p = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "numeric", hourCycle: "h23" }).formatToParts(new Date());
    const part = (t) => +(p.find((x) => x.type === t) || { value: 0 }).value;
    return part("hour") + part("minute") / 60;
  }
  const clock = (h) => { const m = Math.round(h * 60); return Math.floor(m / 60) + ":" + String(m % 60).padStart(2, "0"); };
  function callSpan(inv) {
    const m = splitWhen(inv.when).time.match(/(\d+):(\d+) to (\d+):(\d+)/);
    if (!m) return { from: 9, to: 10 };
    const from = +m[1] + +m[2] / 60, to = +m[3] + +m[4] / 60;
    return { from, to: to < from ? 24 : to }; // crosses midnight ET: run the block to the end of its day
  }
  function weekDays() {
    const s = today();
    s.setDate(s.getDate() - s.getDay() + 7 * CAL.week);
    return Array.from({ length: 7 }, (_, i) => new Date(s.getFullYear(), s.getMonth(), s.getDate() + i));
  }
  function weekLabel(a, b) {
    const md = (d) => d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
    if (a.getFullYear() !== b.getFullYear()) return md(a) + ", " + a.getFullYear() + " – " + md(b) + ", " + b.getFullYear();
    if (a.getMonth() !== b.getMonth()) return md(a) + " – " + md(b) + ", " + b.getFullYear();
    return a.toLocaleDateString("en-US", { month: "long" }) + " " + a.getDate() + " – " + b.getDate() + ", " + b.getFullYear();
  }
  // One call: a block in the week grid, a card in the agenda. Company, time, call type, faces and prep state.
  function calEvent(inv, cls, style) {
    const t = C.tint(inv.company), [from, to] = splitWhen(inv.when).time.replace(/ ET$/, "").split(" to ");
    const time = esc(from) + (to ? '<span class="ev-end"> – ' + esc(to) + "</span>" : ""); // short blocks hide the end time
    return '<a class="' + cls + '" href="#/calls/' + inv.id + '" title="' + esc(inv.title) + '" style="--ev-bg:' + t[0] + ";--ev-ink:" + t[1] + ";" + (style || "") + '"><span class="ev-in">'
      + '<span class="sr-only">' + esc(longDay(inv)) + ", </span>"
      + '<span class="ev-co">' + esc(inv.company) + '</span><span class="sr-only">, </span>'
      + '<span class="ev-meta"><span class="ev-when">' + ic("phone", "ev-phone") + time + '</span><span class="sr-only">, </span><span class="ev-kind">' + esc(kindOf(inv)) + "</span></span>"
      + '<span class="sr-only">, with ' + esc(names(inv)) + ". </span>"
      + avatarStack(inv, "xs") + prepChip(inv.id) + "</span></a>";
  }
  function renderCallsPage() {
    const sec = $('[data-view="calls"]'), H = CAL.hour;
    const days = weekDays(), t0 = today().toDateString();
    const byDay = days.map((d) => D.invites.filter((inv) => callDate(inv).toDateString() === d.toDateString()).sort((a, b) => callSpan(a).from - callSpan(b).from));
    const all = byDay.flat(), ti = days.findIndex((d) => d.toDateString() === t0), now = etHours();
    // Office hours 9 to 17, stretched to fit this week's calls and, in the current week, the time now.
    let start = 9, end = 17;
    all.forEach((inv) => { const s = callSpan(inv); start = Math.min(start, Math.floor(s.from)); end = Math.max(end, Math.ceil(s.to)); });
    if (ti >= 0) { start = Math.min(start, Math.max(0, Math.floor(now - 0.5))); end = Math.max(end, Math.min(24, Math.ceil(now + 0.5))); }
    Object.assign(CAL, { start, end });
    const nowY = Math.round((now - start) * H), dow = (d) => d.toLocaleDateString("en-US", { weekday: "short" });
    // Weekend days without calls are condensed (Outlook's work week, with the weekend still in view), so weekday blocks have room.
    const tracks = days.map((d, i) => (d.getDay() % 6 === 0 && !byDay[i].length ? "minmax(0, 0.6fr)" : "minmax(0, 1fr)")).join(" ");
    const long = (d) => d.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" });

    let gutter = "", lines = "";
    for (let h = start; h < end; h++) {
      const y = (h - start) * H;
      if (!(ti >= 0 && nowY + 10 > y + 4 && nowY - 10 < y + 20)) gutter += '<span class="cal-hl" style="top:' + y + 'px">' + h + ":00</span>";
      lines += (h > start ? '<span class="cal-hr" style="top:' + y + 'px"></span>' : "") + '<span class="cal-half" style="top:' + (y + H / 2) + 'px"></span>';
    }
    if (ti >= 0) {
      gutter += '<span class="cal-now-t" style="top:' + nowY + 'px">' + clock(now) + "</span>";
      lines += '<span class="cal-now-all" style="top:' + nowY + 'px"></span>';
    }
    const head = days.map((d, i) => '<div class="cal-dh' + (i === ti ? " is-today" : "") + '"><span class="cal-dow">' + dow(d) + '</span><span class="cal-dnum">' + d.getDate() + "</span>"
      + (i === ti ? '<span class="sr-only">, today</span>' : "") + "</div>").join("");
    const cols = days.map((d, i) => '<div class="cal-col' + (i === ti ? " is-today" : d.getDay() % 6 === 0 ? " is-off" : "") + '">'
      + byDay[i].map((inv) => { const s = callSpan(inv); return calEvent(inv, "cal-ev", "top:" + Math.round((s.from - start) * H) + "px;height:" + Math.round((s.to - s.from) * H) + "px"); }).join("")
      + (i === ti ? '<span class="cal-now" style="top:' + nowY + 'px" aria-hidden="true"></span>' : "") + "</div>").join("");
    const agenda = days.map((d, i) => '<section class="ag-day' + (i === ti ? " is-today" : "") + '"><h2 class="sr-only">' + esc(long(d)) + (i === ti ? ", today" : "") + "</h2>"
      + '<div class="ag-date" aria-hidden="true"><span class="cal-dow">' + dow(d) + '</span><span class="cal-dnum">' + d.getDate() + "</span></div>"
      + '<div class="ag-list">' + (byDay[i].length ? byDay[i].map((inv) => calEvent(inv, "ag-ev")).join("") : '<p class="ag-none">' + (i === ti ? "No calls today" : "No calls") + "</p>") + "</div></section>").join("");

    const viewSeg = '<div class="seg cal-views" role="group" aria-label="Show">' + [["week", "Week"], ["priority", "By priority"]].map(([k, l]) => '<button type="button" data-cal-view="' + k + '" aria-pressed="' + (CAL.view === k) + '">' + l + "</button>").join("") + "</div>";
    if (CAL.view === "priority") {
      // Every upcoming call, hottest account first (Settings > Account priorities), each with its badge and why.
      const list = D.invites.map((inv, i) => ({ inv, i, p: C.priority(inv.company) })).sort((a, b) => b.p.score - a.p.score || a.i - b.i);
      sec.innerHTML = '<header class="page-head cal-top"><div class="page-head-row"><h1 class="page-title" tabindex="-1">Calls</h1>' + srcTag(SRC.calendar) + viewSeg
        + '<span class="grow"></span><p class="cal-sum">' + plural(list.length, "call") + ' · <a href="#/settings/priorities">Priority rules</a></p></div></header>'
        + (list.length ? '<ol class="prio-list" role="list">' + list.map(({ inv, p }) => '<li class="prio-item">' + calEvent(inv, "ag-ev")
          + '<p class="prio-why">' + C.priorityBadge(inv.company) + "<span>" + esc(p.why.length ? p.why.join(" · ") : "No priority rules match") + "</span></p></li>").join("") + "</ol>"
          : '<p class="list-foot">No calls to rank yet.</p>');
      sec.onclick = (e) => { const v = e.target.closest("[data-cal-view]"); if (v) { CAL.view = v.dataset.calView; renderCallsPage(); $('[data-cal-view="' + CAL.view + '"]', sec).focus(); } };
      return;
    }
    sec.innerHTML = '<header class="page-head cal-top"><div class="page-head-row"><h1 class="page-title" tabindex="-1">Calls</h1>' + srcTag(SRC.calendar) + viewSeg
      + '<div class="cal-nav"><button type="button" class="btn secondary sm" data-cal="today">Today</button>'
      + '<button type="button" class="icon-btn" data-cal="prev" aria-label="Previous week">' + ic("chevronLeft") + "</button>"
      + '<button type="button" class="icon-btn" data-cal="next" aria-label="Next week">' + ic("chevron") + "</button>"
      + '<h2 class="cal-range">' + esc(weekLabel(days[0], days[6])) + "</h2></div>"
      + '<span class="grow"></span><p class="cal-sum">' + (all.length ? plural(all.length, "call") + " this week" : "No calls this week") + " · Times in ET</p></div></header>"
      + '<div class="cal" style="--cols:' + tracks + '"><div class="cal-head"><span class="cal-tz" aria-hidden="true">ET</span>' + head + "</div>"
      + '<div class="cal-body"><div class="cal-gutter" aria-hidden="true">' + gutter + "</div>"
      + '<div class="cal-days" style="height:' + (end - start) * H + 'px"><div class="cal-lines" aria-hidden="true">' + lines + "</div>" + cols + "</div></div></div>"
      + '<div class="agenda">' + agenda + "</div>"
      + '<p class="list-foot">' + (DEMO ? "Past calls and call recordings aren't part of this demo." : LIVE_MODE ? "From your Google Calendar: the next 14 days, events with at least one guest from outside your company." : 'No calendar connected yet. <a href="#/home">Connect Google Calendar</a>') + "</p>";
    sec.onclick = (e) => {
      const v = e.target.closest("[data-cal-view]");
      if (v) { CAL.view = v.dataset.calView; renderCallsPage(); $('[data-cal-view="' + CAL.view + '"]', sec).focus(); return; }
      const b = e.target.closest("[data-cal]");
      if (!b) return;
      CAL.week = b.dataset.cal === "today" ? 0 : CAL.week + (b.dataset.cal === "next" ? 1 : -1);
      renderCallsPage();
      $('[data-cal="' + b.dataset.cal + '"]', sec).focus();
      const n = $$(".cal-ev", sec).length;
      announce($(".cal-range", sec).textContent + ". " + (n ? plural(n, "call") : "No calls") + ".");
    };
  }
  // The now-line keeps time while the page is open (skipped while the pointer or keyboard is on the calendar).
  setInterval(() => {
    const sec = $('[data-view="calls"]'), a = document.activeElement;
    if (app.view !== "calls" || CAL.week !== 0 || CAL.view !== "week" || sec.querySelector(":hover")) return;
    const onTitle = a && a.matches("h1.page-title") && sec.contains(a);
    if (sec.contains(a) && !onTitle) return;
    renderCallsPage();
    if (onTitle) $("h1", sec).focus({ preventScroll: true });
  }, 60000);

  // ---------- call page (the brief, unchanged from the judged redesign) ----------
  const STATE_WORD = { wait: "Waiting", run: "Working", done: "Done", skip: "Skipped", fail: "Failed" };
  function stepsHtml(states, withLinks) {
    const mark = { done: ic("check"), skip: ic("minus"), run: ic("loader", "spin"), fail: ic("x"), wait: '<span class="dot"></span>' };
    return '<ol class="steps" role="list">' + C.STEP_DEFS.map(([id, label, target]) => {
      const s = (states || {})[id] || { state: "wait" };
      const linked = withLinks && target && s.state === "done" && document.getElementById(target);
      return '<li class="step ' + s.state + '"><span class="step-ic">' + mark[s.state] + "</span>"
        + '<span class="step-label"><span class="sr-only">' + STATE_WORD[s.state] + ": </span>"
        + (linked ? '<a href="#' + target + '" data-jump="' + target + '">' + esc(label) + "</a>" : esc(label)) + "</span>"
        + '<span class="step-detail">' + (s.detail || "") + "</span></li>";
    }).join("") + "</ol>";
  }

  // After the call needs the agent's brief (who was on the call, for suggested updates). Asking for After the call on a call the
  // agent hasn't run for runs it first and lands there; a call that already ended opens there too.
  const afterNext = new Set();
  function openAfter(id) {
    if (runs[id] && runs[id].ctx && runs[id].ctx.done) return false;
    if (runningId === id) { runs[id].tab = "after"; return true; } // already running: land on After the call when it's done
    if (runningId) { announce("Wait for the " + inviteById(runningId).company + " brief to finish."); return true; }
    afterNext.add(id);
    runAgent(id);
    return true;
  }
  async function runAgent(id) {
    if (runningId) return;
    runningId = id;
    const inv = inviteById(id);
    const prev = runs[id];
    const run = runs[id] = { ctx: null, states: {}, ticks: prev ? prev.ticks : new Set(), tab: afterNext.delete(id) ? "after" : "brief",
      notes: prev ? prev.notes : inv.afterNotes || "", changes: prev ? prev.changes : null, claude: null, error: null };
    renderNav();
    patchPrep(id);
    if (isOnCall(id)) { renderCallView(); const h0 = $("#panelBrief h1"); if (h0) h0.focus({ preventScroll: true }); }
    if (app.view === "home") renderHome();
    announce("Preparing the brief for " + inv.company + ". " + C.STEP_DEFS.length + " checks.");
    try {
      run.ctx = await C.runChecks(inv, inputs[id], (st) => {
        run.states = st;
        if (isOnCall(id)) { const el = $("#liveSteps"); if (el) el.innerHTML = stepsHtml(st, false); }
        patchPrep(id);
      }, 360);
      run.states = run.ctx.states;
      await C.wait(400); // let the finished list sit for a moment before it folds away
    } catch (e) { run.error = e.message || String(e); }
    finally { runningId = null; }
    if (!run.error && C.state.claudeOn) run.claude = "pending";
    renderNav();
    patchPrep(id);
    if (isOnCall(id)) {
      renderCallView();
      $(".main").scrollTop = 0;
      window.scrollTo(0, 0);
      const h = run.tab === "after" ? $("#afterHead h1") : $("#panelBrief h1"); // the panel that is showing
      if (h) h.focus({ preventScroll: true });
    } else {
      if (app.view === "home") renderHome();
      if (!run.error && !quietUntil()) toast("Brief ready for " + inv.company + ".", "Open", "#/calls/" + id);
    }
    announce(run.error ? "The agent stopped: " + run.error : "Brief ready for " + inv.company + ".");
    if (run.claude === "pending") askClaude(id);
  }

  async function askClaude(id) {
    const run = runs[id];
    const res = await C.askClaude(run.ctx);
    if (runs[id] !== run) return; // a newer run replaced this one while Claude was writing
    if (res.text) { run.ctx.claudeText = res.text; run.claude = "done"; }
    else { run.claude = "failed"; run.ctx.claudeError = res.error; }
    run.ctx.states.write.detail = run.claude === "done" ? "Written with built-in rules. Claude wrote the summary." : "Written with built-in rules (" + esc(run.ctx.claudeError) + ").";
    if (isOnCall(id) && !runningId && $("#summarySlot")) {
      $("#summarySlot").innerHTML = summaryHtml(run);
      $("#howMeta").textContent = howMeta(run);
      $("#howSteps").innerHTML = stepsHtml(run.ctx.states, true);
      if (run.claude === "done") announce("Claude added a summary.");
    }
  }

  function startHead(inv) {
    const w = splitWhen(inv.when);
    return '<header><p class="eyebrow">' + esc(w.day + " " + w.month + " " + w.date + " · " + w.time) + "</p>"
      + '<h1 tabindex="-1">' + esc(inv.company) + (inv.ended ? ' <span class="pill tag-gray">Ended</span>' : "") + '</h1><p class="sub">' + esc(inv.title) + "</p>"
      + '<ul class="faces" aria-label="Invited">' + inv.attendees.map((a) => "<li>" + avatar(a, "sm") + esc(a.name) + "</li>").join("") + "</ul></header>";
  }
  function inputsText(id) {
    const vf = C.readVersionFile(inputs[id].versionFile);
    return {
      file: vf ? (vf.version ? vf.version + " (backstage.json)" : "package.json with " + plural(Object.keys(vf.packages).length, "Backstage package")) : "None given",
      since: inputs[id].since || "Not given",
      line: vf ? "Using " + (vf.version || "their package.json") + (inputs[id].since ? " · since " + inputs[id].since : "") : "No backstage.json given",
    };
  }
  function renderStart(inv) {
    const t = inputsText(inv.id);
    const busy = runningId && runningId !== inv.id;
    $("#panelBrief").innerHTML = '<div class="start">' + startHead(inv)
      + '<div class="start-block"><h2 class="cap">From the invite</h2><p class="start-note">' + esc(inv.notes) + "</p></div>"
      + '<div class="start-block"><div class="uses-head"><h2 class="cap">The agent will use</h2><button type="button" class="ghost-edit" data-open="drawer">' + ic("pencil") + "Edit</button></div>"
      + '<dl class="kv small"><dt>Backstage file</dt><dd>' + esc(t.file) + "</dd><dt>Running it since</dt><dd>" + esc(t.since) + "</dd>"
      + "<dt>Estimates</dt><dd>" + esc(C.ASSUME.daysPerRelease + " days per release behind, " + C.ASSUME.daysPerSerious + " per serious notice") + "</dd></dl></div>"
      + '<button type="button" id="runBtn" class="btn primary big"' + (busy ? " disabled" : "") + ">" + ic("play", "fill") + "Run the agent</button>"
      + (busy ? '<p class="wait-note">Wait for the ' + esc(inviteById(runningId).company) + " brief to finish.</p>" : '<p class="cap center">Takes a few seconds.</p>')
      + '<p class="checks-title">It checks ' + C.STEP_DEFS.length + ' things</p><div id="liveSteps">' + stepsHtml({}, false) + "</div></div>";
  }
  function renderRunning(run) {
    const inv = inviteById(app.callId);
    $("#panelBrief").innerHTML = '<div class="start">' + startHead(inv)
      + '<p class="using">' + esc(inputsText(inv.id).line) + "</p>"
      + '<p class="checks-title">' + ic("loader", "spin") + 'Preparing the brief <span class="muted">· ' + C.STEP_DEFS.length + " checks</span></p>"
      + '<div id="liveSteps">' + stepsHtml(run.states, false) + "</div>"
      + '<p class="leave-note">You can leave this page. Overture will tell you when it\'s ready.</p></div>';
  }
  function renderError(run) {
    const inv = inviteById(app.callId);
    $("#panelBrief").innerHTML = '<div class="start">' + startHead(inv) + '<p class="err">The agent stopped: ' + esc(run.error) + "</p>"
      + '<button type="button" id="runBtn" class="btn primary big">' + ic("rotate") + "Try again</button></div>";
  }
  function howMeta(run) {
    const s = run.ctx.states;
    const failed = C.STEP_DEFS.filter(([id]) => s[id] && s[id].state === "fail").length;
    const writer = run.claude === "done" ? "Claude wrote the summary" : run.claude === "pending" ? "Claude is adding a summary"
      : run.claude === "failed" ? "Built-in rules wrote it (Claude did not answer)" : "Built-in rules wrote it";
    return C.STEP_DEFS.length + " checks" + (failed ? " · " + plural(failed, "check") + " failed" : "") + " · " + writer;
  }
  function summaryHtml(run) {
    if (run.claude === "pending") return '<p class="claude-wait">' + ic("loader", "spin") + "Claude is writing a summary…</p>";
    if (run.claude !== "done") return "";
    return '<section class="sec summary-card">' + secHead(ic("sparkle") + "Summary", "Written by Claude") + '<div class="prose"><p>' + esc(run.ctx.claudeText).replace(/\n{2,}/g, "</p><p>").replace(/\n/g, "<br>") + "</p></div></section>";
  }
  const secHead = (title, src, extra) => '<div class="sec-head"><h2>' + title + "</h2>" + (src ? srcTag(src) : "") + (extra || "") + "</div>";
  function stat(label, n, sub, opts) {
    opts = opts || {};
    return '<div class="stat"' + (opts.id ? ' id="' + opts.id + '"' : "") + '><div class="stat-label">' + esc(label) + "</div>"
      + '<div class="stat-n' + (opts.danger ? " danger" : "") + '">' + esc(n) + '</div><div class="stat-sub">' + sub + "</div></div>";
  }
  const hoursText = (h) => (h ? (h.low === h.high ? String(h.low) : h.low + "–" + h.high) : "?");
  function hoursSub(h) {
    if (!h) return "Start year not given";
    const tip = "Chris (Spotify Backstage seller), Oct 17: about " + C.CHRIS.startHours + " hour a week at first, " + C.CHRIS.lowAt5 + " to " + C.CHRIS.highAt5 + " after five years.";
    return '<span title="' + esc(tip) + '">' + (h.years < 1 ? "First year · " : "") + "Chris's estimate</span>";
  }
  const ESTIMATE_SUB = '<span class="est-word">Estimate</span> · <button type="button" class="link-btn" data-open="drawer" data-focus="assumeRelease">How?</button>';

  // The brief's sections, in the order and with the ones picked in Settings > Brief builder ("short" trims each one to its core).
  function renderBrief(run) {
    const ctx = run.ctx, inv = ctx.invite, b = ctx.bill, c = ctx.company, top = ctx.products[0], w = splitWhen(inv.when);
    const bp = C.prefs() ? C.prefs().brief : { sections: [], length: "full" }, short = bp.length === "short";
    const org = C.orgInfo(inv.company); // what Overture's research found about the company (profile.js draws it)
    const detail = c && /: /.test(c.status) ? '<span class="muted">' + esc(c.status.replace(/^[^:]*: /, "")) + "</span>" : "";
    let html = '<header class="brief-head"><div class="title-row"><h1 tabindex="-1">' + esc(inv.company) + "</h1>" + (inv.ended ? '<span class="pill tag-gray">Ended</span>' : "")
      + (top.score > 0 ? '<span class="pill accent">Best fit: ' + esc(top.name) + "</span>" : "") + C.priorityBadge(inv.company) + "</div>"
      + '<dl class="props"><dt>When</dt><dd>' + esc(w.day + " " + w.month + " " + w.date + " · " + w.time) + "</dd>"
      + '<dt>Kind</dt><dd><span class="pill">' + esc(kindOf(inv)) + "</span></dd>"
      + (org.profile ? '<dt>Company</dt><dd><a href="#company" data-jump="company">' + esc(org.profile.name || inv.company) + "</a>" + (org.domain ? '<span class="muted">' + esc(org.domain) + "</span>" : "") + "</dd>" : "")
      + (c ? "<dt>Status</dt><dd>" + statusTag(c.status) + detail + (fromHubspot(c, "status") ? srcTag("HubSpot") : "") + "</dd>" : "")
      + (c && c.engineers ? "<dt>Size</dt><dd>About " + esc(c.engineers) + " engineers</dd>"
        : c && c.employees ? "<dt>Size</dt><dd>About " + esc(Number(c.employees).toLocaleString("en-US")) + " employees" + srcTag("HubSpot") + "</dd>" : "")
      + (c && c.deals && c.deals.length ? "<dt>Deals</dt><dd>" + dealsHtml(c.deals) + "</dd>" : "")
      + (c && c.notes && !short ? "<dt>Notes</dt><dd>" + esc(c.notes) + "</dd>" : "")
      + "<dt>On the call</dt><dd>" + inv.attendees.map((a) => '<a class="who-chip" href="#/people/' + esc(C.personKey(a.email)) + '">' + avatar(a, "sm") + esc(a.name) + "</a>").join("") + "</dd></dl></header>";
    html += '<details class="how" id="how"><summary>' + ic("circleCheck", "ok") + '<span>How the agent built this</span><span class="how-meta" id="howMeta">' + esc(howMeta(run)) + "</span>"
      + ic("chevron", "chev") + '</summary><div id="howSteps"></div></details>';
    const edit = '<button type="button" class="ghost-edit" data-open="drawer">' + ic("pencil") + "Edit</button>";
    const SECTIONS = {
      opener: () => '<section class="opener" id="opener"><div class="sec-cap"><h2 class="cap">Open the call with</h2></div><blockquote>' + esc(ctx.opener) + "</blockquote></section>",
      since: () => {
        const al = C.alertsFor(inv.id), last = c && c.history.length ? c.history[c.history.length - 1] : null;
        if (!last && !al.length) return "";
        return '<section class="sec recent" id="lastSpoke">' + secHead(al.length ? (last ? "Since you last spoke" : "What's new") : "Last time", SRC.records) + '<ul class="since" role="list">'
          + (last ? "<li>" + ic("clock") + "<span>" + (al.length ? "Last time: " : "") + esc(last.text) + '</span><span class="when">' + esc(last.date ? fmtDate(last.date) : "") + "</span></li>" : "")
          + al.map((a) => "<li>" + ic(a.kind === "Job change" ? "briefcase" : a.kind === "First meeting" ? "handshake" : a.kind === "New person" ? "users" : "trend") + "<span>" + esc(a.text) + '</span><span class="when">' + esc(a.date) + "</span></li>").join("") + "</ul></section>";
      },
      lastTalk: () => {
        const gong = C.gongFor(inv.company), hist = c && c.history.length ? (short ? c.history.slice(-2) : c.history) : [];
        const h = gong ? '<section class="sec" id="gong">' + secHead("Last call in Gong", "Gong")
          + (short ? '<div class="gong-call"><p class="gong-title"><strong>' + esc(gong.title) + "</strong></p>" + (gong.brief ? '<p class="gong-brief">' + esc(gong.brief) + "</p>" : "") + "</div>" : C.gongHtml(gong)) + "</section>" : "";
        if (gong && !hist.length) return h;
        return h + '<section class="sec" id="history">' + secHead("Last talks", SRC.records) + '<dl class="kv">'
          + (hist.length ? hist.map((x) => "<dt>" + esc(x.date ? fmtDate(x.date) : "No date") + "</dt><dd>" + ic("clock", "warn") + "<span>" + esc(x.text) + "</span>" + (x.src ? srcTag(x.src) : "") + "</dd>").join("")
            : "<dt>History</dt><dd>" + ic("clock", "warn") + "<span>Nothing yet. This is the first talk.</span></dd>")
          + "</dl></section>";
      },
      backstage: () => {
        let h = b ? '<section class="bill" id="bill"><div class="sec-cap"><h2 class="cap">Their upgrade bill</h2>' + srcTag("Public data + estimates") + '</div><div class="stats">'
          + stat("Releases behind", b.behind == null ? "?" : b.behind, esc((b.from || "?") + " → " + b.to))
          + stat("Serious notices", b.serious, esc(b.sev.critical + " critical, " + b.sev.high + " high"), { danger: b.sev.critical > 0 })
          + stat("Days to catch up", b.days == null ? "?" : b.days, ESTIMATE_SUB, { id: "statDays" })
          + stat("Hours a week", hoursText(b.hours), hoursSub(b.hours)) + "</div></section>" : "";
        if (short && b) return h;
        h += '<section class="sec" id="backstage">' + secHead("Their Backstage", "Public data", edit);
        if (b) {
          h += '<p class="muted-line">From ' + (ctx.version ? "backstage.json: " + esc(ctx.version) : "package.json") + (inv.backstageSince ? " · Running it since " + esc(inv.backstageSince) : "") + "</p>"
            + "<p>" + plural(b.open.length, "security notice") + " open in all: " + b.sev.critical + " critical, " + b.sev.high + " high, " + (b.open.length - b.serious) + " medium or low. Latest Backstage is " + esc(b.to) + " (" + esc(fmtDate(b.toDate)) + ").</p>";
        } else if (ctx.billError) {
          h += "<p>Couldn't check their Backstage version: " + esc(ctx.billError) + '. <button type="button" class="link-btn" data-open="drawer">Edit it</button></p>';
        } else h += '<p>No backstage.json yet. <button type="button" class="link-btn" data-open="drawer">Add it</button></p>';
        return h + "<p>" + (ctx.companyAdopter ? "On the public adopters list: “" + esc(ctx.companyAdopter.use) + "”" : "Not on the public adopters list (" + C.state.adopters.length + " companies). Many users never add themselves.") + "</p></section>";
      },
      security: () => {
        if (!b || !b.open.length) return "";
        const worst = b.open.slice(0, short ? 3 : 5);
        return '<section class="sec" id="security">' + secHead("Their worst security notices", "Public data") + '<ul class="notices" role="list">'
          + worst.map((a) => '<li><span class="pill ' + tagFor("severity", a.severity) + '">' + esc(a.severity) + "</span>"
            + '<a href="' + esc(a.url) + '" target="_blank" rel="noopener">' + esc(a.summary.replace(/^Backstage:\s*/i, "")) + ic("link", "ext") + NEW_TAB + "</a>"
            + '<span class="muted-line muted-date">' + esc(fmtDate(a.published)) + "</span></li>").join("") + "</ul>"
          + (b.open.length > worst.length ? '<p class="muted-line">' + plural(b.open.length - worst.length, "more notice") + " open.</p>" : "") + "</section>";
      },
      // Real to-dos (papers, rivals), then what each guest's profile says to bring up. Hidden when there is neither.
      todos: () => {
        const bring = window.CP.forCallHtml(ctx.people, profileLinks);
        if (!ctx.todos.length && !bring) return "";
        return '<section class="sec" id="todo">' + secHead(ctx.todos.length ? "Before the call" : "Bring up on the call", ctx.todos.length ? SRC.records : DEMO ? "Sample data" : "Found by Overture")
          + (ctx.todos.length ? '<ul class="todos" role="list">' + ctx.todos.map((t) => '<li><label><input type="checkbox" data-call="' + esc(inv.id) + '" data-todo="' + esc(t.text) + '"' + (run.ticks.has(t.text) ? " checked" : "") + "><span>" + esc(t.text) + "</span></label>"
            + (t.link ? '<a class="todo-link" href="' + t.link.href + '" data-jump="' + t.link.href.slice(1) + '">' + esc(t.link.label) + "</a>" : "") + (t.src ? srcTag(t.src) : "") + "</li>").join("") + "</ul>" : "")
          + (bring ? (ctx.todos.length ? '<h3 class="pf-sub-h">Bring up on the call</h3>' : "") + bring : "") + "</section>";
      },
      // The company as Overture's research found it (or "Researching…"), then each guest with their compact profile.
      people: () => {
        const about = window.CP.orgBlock(inv.company, Object.assign({ heading: false, idp: "bco", level: 2 }, profileLinks));
        const aboutSec = about ? '<section class="sec pf-org-sec" id="company">' + secHead("About " + esc(org.profile && org.profile.name ? org.profile.name : inv.company), "",
          companyBySlug(slug(inv.company)) ? '<a class="ghost-edit" href="#/companies/' + slug(inv.company) + '">' + ic("building") + "Company</a>" : "") + about + "</section>" : "";
        return aboutSec + '<section class="sec" id="people">' + secHead("Who's on the call", SRC.records, '<a class="ghost-edit" href="#/map">' + ic("network") + "Map</a>") + '<ul class="people" role="list">' + ctx.people.map((p) => {
          if (editingPerson === p.email) return personForm(p);
          const f = p.facts, found = !!C.personInfo(p.email).profile;
          const key = f.lead ? "<strong>" + esc(f.lead.text) + "</strong> " + esc(p.note || f.lead.tail) : esc(p.note || (f.unknown && !found ? (DEMO ? "Not in Spotify's records yet." : "Not in Overture's records yet.") : ""));
          const bits = [C.tenure(p.startedAt) + (f.isNew ? ", and new leaders often want change" : "")];
          if (f.unknown && !found && (f.lead || p.note)) bits.push(DEMO ? "Not in Spotify's records yet" : "Not in Overture's records yet");
          const auto = !!(p.research && p.research.status === "done" && p.research.found === "auto");
          const pedit = LIVE_MODE && !auto ? '<button type="button" class="ghost-edit p-edit" data-edit-person="' + esc(p.email) + '" aria-label="' + esc("Edit " + p.name + "'s title and note") + '">' + ic("pencil") + "Edit</button>" : "";
          return '<li class="person">' + avatar(p, "lg") + "<div>"
            + '<p class="p-name"><a class="pf-name-link" href="#/people/' + esc(C.personKey(p.email)) + '"><strong>' + esc(p.name) + "</strong></a> <span>· " + esc(p.title) + "</span>" + (p.titleSrc === "HubSpot" ? srcTag("HubSpot") : "") + pedit + "</p>"
            + (key ? '<p class="p-key">' + key + "</p>" : "") + (short ? "" : '<p class="p-meta">' + esc(bits.join(" · ")) + "</p>")
            + (short ? "" : window.CP.briefPerson(p.email, profileLinks))
            + C.researchHtml(p, { actions: true, edit: true })
            + (f.quote && !short ? '<p class="p-quote">From the public adopters list: “' + esc(f.quote) + "”</p>" : "") + "</div></li>";
        }).join("") + "</ul></section>";
      },
      rivals: () => (ctx.rivals.length ? '<section class="sec" id="rivals">' + secHead("Rivals", ctx.rivals.some((r) => r.source) ? "Public data" : "Agent's notes") + ctx.rivals.map((r) => '<div class="rival">'
        + '<p class="rival-name">' + esc(r.name) + (r.source ? ' · <a href="' + esc(r.source.url) + '" target="_blank" rel="noopener">' + esc(r.source.label) + ic("link", "ext") + NEW_TAB + "</a>" : "") + "</p>"
        + r.facts.map((f) => "<p>" + esc(f) + "</p>").join("")
        + (r.sayBack && !short ? '<p class="say-cap">What to say back (Chris, Oct 17)</p><p>' + esc(C.PORTAL_POINTS) + "</p>" : "") + "</div>").join("") + "</section>" : ""),
      papers: () => {
        const list = short ? ctx.papers.filter((p) => !p.ok) : ctx.papers;
        return list.length ? '<section class="sec" id="papers">' + secHead("Papers", SRC.records) + '<dl class="kv">'
          + list.map((p) => "<dt>" + esc(p.key) + "</dt><dd>" + ic(p.ok ? "circleCheck" : "circleAlert", p.ok ? "ok" : "warn") + "<span>" + esc(p.text) + "</span></dd>").join("") + "</dl></section>" : "";
      },
    };
    const order = bp.sections && bp.sections.length ? bp.sections : Object.keys(SECTIONS).map((id) => ({ id, on: true }));
    order.forEach((s) => { if (s.on && SECTIONS[s.id]) html += SECTIONS[s.id](); });
    html += '<div id="summarySlot">' + summaryHtml(run) + "</div>";
    if (!short) {
      html += '<div class="divider"><span>Details</span></div>';
      html += '<section class="sec" id="invite">' + secHead("From the invite", SRC.calendar) + '<p class="muted-line">' + esc(inv.title + " · " + plural(inv.attendees.length, "person", "people")) + "</p>"
        + (inv.notes ? '<blockquote class="note-quote">' + esc(inv.notes) + "</blockquote>" : '<p class="muted-line">The invite has no description.</p>') + "</section>";
      const others = ctx.products.slice(1), maybe = others.filter((p) => p.score > 0), none = others.filter((p) => p.score === 0);
      html += '<section class="sec" id="fit">' + secHead("Which product fits", "Agent's guess")
        + (top.score > 0 ? "<p><strong>" + esc(top.name) + ".</strong> " + esc(top.why.join(" ")) + "</p>" : "<p>No clear fit yet.</p>")
        + maybe.map((p) => "<p>Also possible: <strong>" + esc(p.name) + ".</strong> " + esc(p.why.join(" ")) + "</p>").join("")
        + (none.length ? '<p class="muted-line fit-other">' + esc(none.map((p) => p.name).join(" and ")) + ": no signs yet.</p>" : "") + "</section>";
    }
    const hidden = order.filter((s) => !s.on).length;
    const trimmed = [short ? "Short brief" : "", hidden ? plural(hidden, "section") + " hidden" : ""].filter(Boolean).join(", ");
    html += '<p class="footnote">' + (trimmed ? esc(trimmed) + '. <a href="#/settings/brief">Change it in Settings</a>. ' : "")
      + (DEMO ? "Sample data (people, companies, history, papers, alerts and call notes) is made up for this demo and stands in for Spotify's own records. Public data (Backstage versions, security notices, the adopters list and rival prices) is real."
      : "The call and its guests come from your Google Calendar. Titles, notes, status and history come from Overture's records on this PC; edit them here or on the company page. Public data (Backstage versions, security notices, the adopters list and rival prices) is real.") + "</p>";
    $("#panelBrief").innerHTML = html;
    $("#howSteps").innerHTML = stepsHtml(ctx.states, true);
  }

  // ---------- filling in what the calendar can't know (live mode: saved to Overture's records on this PC) ----------
  let editingPerson = null, editingCompany = null;
  function personForm(p) {
    return '<li class="person editing">' + avatar(p, "lg") + '<form class="rec-form" data-person-form="' + esc(p.email) + '" aria-label="' + esc("Edit " + p.name) + '">'
      + '<p class="p-name"><strong>' + esc(p.name) + '</strong> <span>· ' + esc(p.email) + "</span></p>"
      + '<label class="field-label" for="pfTitle">Title</label><input id="pfTitle" class="input" name="title" maxlength="120" autocomplete="off" value="' + esc(p.title === "Title unknown" ? "" : p.title) + '" placeholder="e.g. VP, Platform Engineering">'
      + '<label class="field-label" for="pfNote">Note</label><textarea id="pfNote" class="input" name="note" rows="3" maxlength="2000" placeholder="What you know about them">' + esc(p.note || "") + "</textarea>"
      + '<div class="rec-actions"><button type="submit" class="btn primary sm">Save</button><button type="button" class="btn ghost sm" data-cancel-edit="person">Cancel</button><span class="rec-err" role="alert"></span></div></form></li>';
  }
  async function savePerson(form) {
    const email = form.dataset.personForm, title = $('[name="title"]', form).value.trim(), note = $('[name="note"]', form).value.trim();
    const btn = $('button[type="submit"]', form);
    btn.disabled = true;
    if (!DEMO) { try { await C.saveRecord("person", { email, title, note }); } catch (err) { btn.disabled = false; $(".rec-err", form).textContent = err.message; return; } }
    D.people[email] = Object.assign(D.people[email] || {}, { title, note, known: true });
    Object.values(runs).forEach((r) => {
      if (!r.ctx || !r.ctx.people) return;
      r.ctx.people.forEach((p) => { if (p.email === email) { Object.assign(p, { title: title || "Title unknown", note, known: true }); p.facts = C.personFacts(p); } });
      if (r.ctx.done) r.ctx.todos = C.todoList(r.ctx);
    });
    editingPerson = null;
    const run = runs[app.callId];
    if (run && run.ctx && run.ctx.done) renderBrief(run);
    const b = $('[data-edit-person="' + CSS.escape(email) + '"]');
    if (b) b.focus();
    announce(DEMO ? "Sample data: changed on this page only." : "Saved to Overture's records.");
    if (hubspotOn() && hsCalls[app.callId]) refreshHubspotPlan(app.callId); // a new title can be offered to HubSpot
  }
  // Research results (found automatically) reach every open brief: the call's people are copies made when the agent ran.
  // domains: companies whose research changed (GET /api/research's orgs); the page showing one of them redraws too.
  function refreshPeople(emails, domains) {
    domains = domains || [];
    const orgHit = (name) => !!name && domains.includes(C.orgDomain(name));
    if (app.view === "people") {
      const email = C.emailForKey(app.personKey), w = email ? window.CP.who(email) : null;
      if (w && (emails.includes(email) || orgHit(w.company))) { const y = $(".main").scrollTop; renderPerson(email); $(".main").scrollTop = y; }
    }
    if (app.view === "company" && orgHit(companyBySlug(app.slug)) && !editingCompany) renderCompany(companyBySlug(app.slug));
    const cur = runs[app.callId];
    if (app.view === "call" && !editingPerson && cur && cur.ctx && cur.ctx.done && orgHit(cur.ctx.invite.company) && !cur.ctx.people.some((p) => emails.includes(p.email))) renderBrief(cur);
    Object.values(runs).forEach((r) => {
      if (!r.ctx || !r.ctx.people) return;
      r.ctx.people.forEach((p) => {
        if (!emails.includes(p.email)) return;
        const d = D.people[p.email] || {};
        Object.assign(p, { research: d.research, title: d.title || p.title, known: d.known === undefined ? p.known : d.known });
        p.facts = C.personFacts(p);
      });
      if (r.ctx.done) r.ctx.todos = C.todoList(r.ctx);
    });
    const run = runs[app.callId];
    if (app.view === "call" && !editingPerson && run && run.ctx && run.ctx.done && run.ctx.people.some((p) => emails.includes(p.email))) renderBrief(run);
  }
  async function researchAction(btn, kind) {
    const email = btn.dataset[kind === "confirm" ? "rsConfirm" : "rsAgain"];
    btn.disabled = true;
    try {
      if (kind === "confirm") await C.confirmResearch(email); else await C.lookUpAgain(email);
    } catch (err) { btn.disabled = false; announce(err.message); toast(err.message); return; }
    refreshPeople([email]);
    const again = $(kind === "confirm" ? '[data-rs-confirm="' + CSS.escape(email) + '"]' : '[data-rs-again="' + CSS.escape(email) + '"]');
    const b = again || $('[data-edit-person="' + CSS.escape(email) + '"]');
    if (b) b.focus();
    announce(kind === "confirm" ? (DEMO ? "Confirmed (sample data, this page only)." : "Confirmed. Saved to Overture's records.") : "Looking them up.");
  }
  const STATUS_OPTIONS = ["New lead", "Open deal: Portal", "Open deal: Confidence", "Open deal: Xirp", "Customer: Portal", "Not a fit yet"];
  function companyForm(name) {
    const c = D.companies[name] || {};
    return '<section class="co-panel-sec" aria-labelledby="coDetH"><div class="co-panel-head"><h2 id="coDetH">Edit details</h2>' + srcTag(SRC.records) + "</div>"
      + '<form class="rec-form" data-company-form="' + esc(name) + '">'
      + (fromHubspot(c, "status") ? '<p class="help">Status comes from HubSpot (' + esc(c.status) + '). Change it there.</p>'
        : '<label class="field-label" for="cfStatus">Status</label>'
        + '<input id="cfStatus" class="input" name="status" list="cfStatusList" maxlength="80" autocomplete="off" value="' + esc(c.status && c.status !== "Prospect" ? c.status : "") + '" placeholder="e.g. Open deal: Portal" aria-describedby="cfHelp">'
        + '<datalist id="cfStatusList">' + STATUS_OPTIONS.map((o) => '<option value="' + esc(o) + '">').join("") + "</datalist>"
        + '<p class="help" id="cfHelp">Start with Customer, Open deal or New lead and the tag takes that colour.</p>')
      + '<label class="field-label" for="cfNotes">Notes</label><textarea id="cfNotes" class="input" name="notes" rows="4" maxlength="4000" placeholder="What Overture should know about them">' + esc(c.notes || "") + "</textarea>"
      + '<div class="rec-actions"><button type="submit" class="btn primary sm">Save</button><button type="button" class="btn ghost sm" data-cancel-edit="company">Cancel</button><span class="rec-err" role="alert"></span></div></form></section>';
  }
  async function saveCompany(form) {
    const name = form.dataset.companyForm, old = D.companies[name] || {}, statusIn = $('[name="status"]', form); // no status field when HubSpot sets it
    const status = statusIn ? statusIn.value.trim() : old.status, notes = $('[name="notes"]', form).value.trim();
    const domain = old.domain || (D.companyDomains || {})[name] || "";
    const btn = $('button[type="submit"]', form);
    btn.disabled = true;
    const body = statusIn ? { name, status, notes, customer: /^Customer/.test(status) } : { name, notes };
    if (domain) body.domain = domain;
    try { await C.saveRecord("company", body); } catch (err) { btn.disabled = false; $(".rec-err", form).textContent = err.message; return; }
    D.companies[name] = Object.assign({ engineers: null, history: [] }, old, { status: status || "Prospect", notes, customer: /^Customer/.test(status || ""), domain });
    Object.values(runs).forEach((r) => { if (r.ctx && r.ctx.invite.company === name) r.ctx.company = D.companies[name]; });
    editingCompany = null;
    renderCompany(name);
    renderNav();
    const b = $("[data-edit-company]");
    if (b) b.focus();
    announce("Saved to Overture's records.");
  }
  // Accepted after-call updates go to Overture's records (live mode) and show up in the company's history at once.
  async function syncChanges(run, accept, undo) {
    if (!LIVE_MODE || (!accept.length && !undo.length)) return true;
    const inv = run.ctx.invite, pick = (c) => ({ kind: c.kind, text: c.text });
    try {
      await C.saveRecord("apply", { callId: inv.id, company: inv.company, accept: accept.map(pick), undo: undo.map(pick) }, "POST");
    } catch (e) { toast(e.message); return false; }
    const co = D.companies[inv.company] = D.companies[inv.company] || { engineers: null, status: "Prospect", history: [], customer: false, notes: "", domain: (D.companyDomains || {})[inv.company] || "" };
    const line = (c) => c.kind + ": " + c.text;
    const gone = new Set(undo.map(line));
    co.history = co.history.filter((h) => !gone.has(h.text));
    accept.forEach((c) => { if (!co.history.some((h) => h.text === line(c))) co.history.push({ date: D.today, text: line(c) }); });
    if (!run.ctx.company) run.ctx.company = co;
    return true;
  }
  let notesTimer = null;
  function saveNotesSoon(id, text) {
    const inv = inviteById(id);
    if (inv) inv.afterNotes = text;
    if (!LIVE_MODE) return;
    clearTimeout(notesTimer);
    $("#notesSaved").textContent = "";
    notesTimer = setTimeout(async () => {
      try { await C.saveRecord("call-notes", { callId: id, text }); if (app.callId === id) $("#notesSaved").textContent = "Saved"; }
      catch (e) { if (app.callId === id) $("#notesSaved").textContent = e.message; }
    }, 800);
  }

  // ---------- Save to HubSpot (after the call, live mode): shows exactly what it will write, writes only on the button ----------
  const hsCalls = {}; // per call id: { titles: Set of accepted emails, plan, planNote, error, loading, busy, seq, result }
  let hsTimer = null;
  const hubspotOn = () => LIVE_MODE && !!(C.state.hubspot && C.state.hubspot.configured);
  const hsState = (id) => hsCalls[id] || (hsCalls[id] = { titles: new Set(), plan: null, planNote: "", error: "", loading: false, busy: false, seq: 0, result: null });
  async function refreshHubspotPlan(id) {
    if (!hubspotOn()) return;
    const st = hsState(id), seq = ++st.seq, note = (runs[id] && runs[id].notes) || "";
    st.loading = true;
    renderHubspot(id);
    try {
      const j = await C.hubspotPlan(id, note, Array.from(st.titles));
      if (seq !== st.seq) return;
      st.plan = j.plan; st.planNote = note; st.error = "";
    } catch (e) {
      if (seq !== st.seq) return;
      st.plan = null; st.error = e.message;
    }
    st.loading = false;
    renderHubspot(id);
  }
  function hubspotSoon(id) {
    if (!hubspotOn()) return;
    const st = hsState(id);
    st.seq++; st.loading = true; // the shown plan is out of date until the new one arrives: Save waits for it
    renderHubspot(id);
    clearTimeout(hsTimer);
    hsTimer = setTimeout(() => refreshHubspotPlan(id), 800);
  }
  function renderHubspot(id) {
    const el = $("#hsSave");
    if (!el || app.callId !== id) return;
    el.hidden = !hubspotOn();
    if (el.hidden) return;
    const st = hsState(id), p = st.plan, focusId = document.activeElement && document.activeElement.closest("#hsSave") ? document.activeElement.id : "";
    let h = '<div class="sec-head"><h2 id="hsSaveH">Save to HubSpot</h2>' + srcTag("HubSpot") + "</div>";
    if (!p) {
      h += st.error ? '<p class="muted-line">' + esc(st.error) + ' <button type="button" class="link-btn" data-hs-retry>Try again</button></p>'
        : '<p class="busy hs-busy">' + ic("loader", "spin") + "Checking HubSpot…</p>";
    } else {
      const items = p.contacts.map((x) => x.name).concat(p.deal ? ["the deal " + p.deal.name + (p.deal.stage ? " (" + p.deal.stage + ")" : "")] : []);
      const linked = items.length > 1 ? [items.slice(0, -1).join(", ") + " and " + items[items.length - 1]] : items;
      h += '<p class="help hs-lead">Nothing goes to HubSpot until you press Save to HubSpot. This is exactly what it writes:</p><ul class="hs-plan" role="list">';
      h += p.note ? '<li><p class="hs-what">' + ic("note") + "<span>A note on <strong>" + esc(p.company) + "</strong>" + (linked.length ? ", linked to " + esc(linked.join(" and ")) : "") + "</span></p>"
        + '<blockquote class="note-quote hs-note">' + esc(p.preview || p.note) + "</blockquote></li>"
        : '<li><p class="hs-what muted-line">' + ic("note") + "<span>No note: write your call notes above first.</span></p></li>";
      p.candidates.forEach((x) => {
        const on = p.titleChanges.some((t) => t.email === x.email), cid = "hsT-" + x.email.replace(/[^a-z0-9]/gi, "-");
        h += '<li><label class="hs-title" for="' + esc(cid) + '"><input type="checkbox" id="' + esc(cid) + '" data-hs-title="' + esc(x.email) + '"' + (on ? " checked" : "") + ">"
          + "<span>" + (x.from ? "Change " + "<strong>" + esc(x.name) + "</strong>'s job title from “" + esc(x.from) + "” to “" + esc(x.to) + "”"
            : "Add <strong>" + esc(x.name) + "</strong>'s job title: “" + esc(x.to) + "”") + '<span class="hs-why"> · ' + esc(x.why) + "</span></span></label></li>";
      });
      h += "</ul>";
      const savedOn = p.savedBefore ? esc(new Date(p.savedBefore).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })) : "";
      if (p.savedBefore) h += '<p class="help">' + (p.savedUnsure ? "A save on " + savedOn + " got no answer from HubSpot, so the note may be there already. Check the company in HubSpot before saving again."
        : "Saved to HubSpot on " + savedOn + ". Saving again adds another note.") + "</p>";
    }
    const nothing = !p || (!p.note && !p.titleChanges.length);
    h += '<div class="after-actions hs-actions"><button type="button" class="btn primary" id="hsSaveBtn"' + (nothing || st.loading || st.busy ? " disabled" : "") + ">"
      + (st.busy ? ic("loader", "spin") + "Saving…" : st.loading && p ? "Updating…" : "Save to HubSpot") + "</button>"
      + '<span class="hs-result' + (st.result ? (st.result.ok ? " ok" : " bad") : "") + '" role="status">' + (st.result ? (st.result.ok ? ic("check") : "") + esc(st.result.text) : "") + "</span></div>";
    el.innerHTML = h;
    if (focusId && document.getElementById(focusId)) document.getElementById(focusId).focus();
  }
  async function saveHubspot(id) {
    const st = hsState(id), p = st.plan;
    if (!p || st.loading || st.busy) return;
    st.busy = true; st.result = null;
    renderHubspot(id);
    try {
      const j = await C.hubspotSave(id, st.planNote, p.titleChanges.map((t) => t.email), p.planId);
      const what = [j.note ? "the note" : "", j.titles.length ? plural(j.titles.length, "title change") : ""].filter(Boolean).join(" and ");
      st.result = { ok: !j.problems.length, text: "Saved to HubSpot: " + (what || "nothing new") + "." + (j.problems.length ? " " + j.problems.join(" ") : "") };
      st.titles.clear();
      announce(st.result.text);
    } catch (e) {
      st.result = { ok: false, text: e.message };
      announce(e.message);
    }
    st.busy = false;
    renderHubspot(id);
    refreshHubspotPlan(id); // after a failure too: HubSpot may have changed, or a save may have half happened

    const b = $("#hsSaveBtn");
    if (b) b.focus();
  }

  // ---------- Mentioned on the call (after the call): people who were talked about, not the guests ----------
  // The transcript is read on this PC by Overture's server (rules) and, when Chrome has it, by Chrome's on-device AI here in the browser.
  // Overture keeps only who was mentioned and the sentence they came up in. Web lookups send only a name, role words and the company.
  const mnCalls = {}; // per call id: { items, loading, error, busy, notice, paste, sample, hs: { [mention id]: { plan, error, busy, done } } }
  const mnState = (id) => mnCalls[id] || (mnCalls[id] = { items: null, orgs: [], loading: false, error: "", busy: false, notice: "", paste: false, sample: false, hs: {}, change: {}, granola: null });
  const MN_MAX_BYTES = 1000000;
  const MN_EXTS = [".vtt", ".srt", ".txt"];
  const MN_STATUS = { pending: ["Looking up…", "tag-blue"], found: ["Found", "tag-green"], known: ["Found", "tag-green"], pick: ["Pick one", "tag-orange"],
    notfound: ["Not found", "tag-gray"], error: ["Couldn't look up", "tag-red"], nokey: ["Not looked up", "tag-gray"] };
  // A company mentioned on the call: how it relates to the call's company. "waiting": the speaker may still explain it (live notes).
  const ORG_STATUS = { waiting: ["Listening for how they relate…", "tag-blue"], pending: ["Looking up how they relate…", "tag-blue"], said: ["Said on the call", "tag-purple"],
    found: ["Found on the web", "tag-teal"], unknown: ["Relation unknown", "tag-gray"], error: ["Couldn't look up", "tag-red"], nokey: ["Not looked up", "tag-gray"] };
  const MN_SYS = "You read part of a sales call transcript and list the people who are talked about by name: not the speakers. "
    + "Answer with a JSON array only, like [{\"name\": \"Maria Gomez\", \"role\": \"security team\"}]. "
    + "name is exactly as written (a full name or a first name). role is the role or team said with them, or empty. "
    + "Leave out products, companies and places. If nobody is mentioned, answer [].";
  const mnCount = (id) => { const st = mnCalls[id]; return st && st.items ? st.items.length + (st.orgs || []).length : +((D.mentions || {})[id] || 0); };
  // New connections from GET /api/mentions go straight onto the People map (and the map redraws if it's open).
  function mnGraph(id, j) {
    if (j && j.graph && C.mergeConnections(id, j.graph) && app.view === "map" && mapInstance) mountMap();
  }
  // The in-call panel runs in its own frame (and maybe another tab): when it finds or changes a connection it says so here,
  // and this page fetches that call's mentions, so the People map and After the call show it without a reload.
  if (LIVE_MODE && "BroadcastChannel" in window) {
    new BroadcastChannel("moab-mentions").onmessage = (e) => { const id = e.data && e.data.callId; if (typeof id === "string" && inviteById(id)) loadMentions(id); };
  }
  const gongTranscriptsOn = () => LIVE_MODE && !!(C.state.gong && C.state.gong.configured) && C.state.gongTranscripts;
  // Granola (Settings > Research sources, off by default, and a key saved with tools/connect.py granola): its note after the call.
  const granolaOn = () => LIVE_MODE && !!(C.state.granola && C.state.granola.configured) && !!(C.prefs() && C.prefs().research.granola);
  const mnCap = (s) => String(s || "").charAt(0).toUpperCase() + String(s || "").slice(1);

  function renderAfterCount(id) {
    const el = $("#afterCount");
    if (!el) return;
    const n = mnCount(id);
    el.hidden = !n;
    el.innerHTML = n ? esc(n) + '<span class="sr-only"> ' + (n === 1 ? "person" : "people") + " mentioned</span>" : "";
  }
  async function loadMentions(id) {
    if (!LIVE_MODE) return;
    const st = mnState(id);
    st.loading = true;
    renderMentions(id);
    try {
      let r;
      try { r = await C.fetchTimeout("/api/mentions?callId=" + encodeURIComponent(id), 10000); } catch (e) { throw new Error("Couldn't reach Overture's server. Is server.py running?"); }
      let j = {};
      try { j = await r.json(); } catch (e) { /* no body */ }
      if (!r.ok) throw new Error(j.error || "Overture's server answered " + r.status);
      st.items = j.items || [];
      st.orgs = j.orgs || [];
      st.granola = j.granola || null;
      st.error = "";
      mnGraph(id, j);
    } catch (e) { st.error = e.message; }
    st.loading = false;
    renderMentions(id);
    renderAfterCount(id);
    mnWatch();
  }
  // Chrome's on-device AI (only when this browser has it) reads the transcript on this PC and suggests names the rules could miss.
  // Its suggestions go only to Overture's own server, which keeps a name only when it is really in the transcript.
  async function deviceHints(text) {
    if ((await C.deviceChecked) !== "available" || !text) return [];
    const hints = [];
    for (let i = 0; i < Math.min(text.length, 30000); i += 6000) {
      let s = null;
      try {
        s = await globalThis.LanguageModel.create({ initialPrompts: [{ role: "system", content: MN_SYS }] });
        const out = await Promise.race([s.prompt("Transcript part:\n" + text.slice(i, i + 6000)), C.wait(20000).then(() => "")]);
        const m = String(out || "").match(/\[[\s\S]*\]/);
        if (m) JSON.parse(m[0]).forEach((h) => { if (h && typeof h.name === "string" && h.name.trim()) hints.push({ name: h.name.trim().slice(0, 100), role: typeof h.role === "string" ? h.role.trim().slice(0, 80) : "" }); });
      } catch (e) { /* the rules on the server still run */ } finally { try { if (s && s.destroy) s.destroy(); } catch (e) { /* ignore */ } }
    }
    return hints.slice(0, 50);
  }
  async function findMentions(id, payload, label) {
    const st = mnState(id);
    if (st.busy) return;
    st.busy = true; st.error = ""; st.notice = "";
    renderMentions(id);
    try {
      if (payload.text) payload.hints = await deviceHints(payload.text);
      const j = payload.source === "granola" ? await C.postJson("/api/granola/fetch", { callId: id }, 90000)
        : await C.postJson("/api/mentions", Object.assign({ callId: id }, payload), 90000);
      st.items = j.items || [];
      st.orgs = j.orgs || [];
      st.granola = j.granola || st.granola;
      mnGraph(id, j);
      st.notice = j.found ? plural(j.found, "new mention") + " in " + label + ": people and companies go on the People map as they're found." : "Nobody new mentioned in " + label + ".";
      st.paste = false;
    } catch (e) { st.error = e.message; }
    st.busy = false;
    renderMentions(id);
    renderAfterCount(id);
    announce(st.error || st.notice);
    mnWatch();
  }
  function useSample(id) {
    const st = mnState(id), sm = D.mentionSample;
    st.sample = true; st.error = ""; st.paste = false;
    if (!sm || sm.callId !== id) { st.items = []; st.notice = "The sample transcript is on the Northwind Freight call."; renderMentions(id); renderAfterCount(id); return; }
    st.items = JSON.parse(JSON.stringify(sm.items));
    st.orgs = JSON.parse(JSON.stringify(sm.orgs || []));
    // Show the web lookups the way they run live: "Looking up…", then found a moment later (up to 3 at once).
    const later = st.items.filter((x) => x.status === "found" && x.person && x.person.from === "Web").map((x) => [x, { status: "found", person: x.person }])
      .concat(st.orgs.filter((o) => o.status === "found").map((o) => [o, { status: "found", relation: o.relation }]));
    later.forEach(([x]) => Object.assign(x, x.kind === "company" ? { status: "pending", relation: null } : { status: "pending", person: null }));
    st.notice = "Sample transcript (" + sm.file + "): " + plural(st.items.length, "person", "people") + " and " + plural(st.orgs.length, "company", "companies")
      + " mentioned. Nothing is sent to the server in the demo.";
    renderMentions(id); renderAfterCount(id); announce(st.notice);
    later.forEach(([x, done], i) => setTimeout(() => { if (x.status === "pending") { Object.assign(x, done); renderMentions(id); } }, 900 + i * 500));
  }
  async function mentionsFromFile(id, file) {
    const st = mnState(id);
    if (!file) return;
    const ext = (String(file.name).toLowerCase().match(/\.[a-z0-9]+$/) || [""])[0];
    st.notice = "";
    if (!MN_EXTS.includes(ext)) { st.error = "Use a .vtt, .srt or .txt transcript from Zoom or Google Meet."; renderMentions(id); announce(st.error); return; }
    if (file.size > MN_MAX_BYTES) { st.error = "That transcript is over 1 MB. Save it as text without the video and try again."; renderMentions(id); announce(st.error); return; }
    if (DEMO) { useSample(id); return; }
    let text = "";
    try { text = await file.text(); } catch (e) { st.error = "Couldn't read that file."; renderMentions(id); return; }
    if (/\u0000/.test(text)) { st.error = "That file isn't text. Use the .vtt, .srt or .txt transcript."; renderMentions(id); announce(st.error); return; }
    await findMentions(id, { text, filename: file.name, source: "upload" }, file.name);
  }
  function mentionsFromNotes(id) {
    const panel = (store.get("notes:" + id) || []).map((n) => ({ speaker: "Your note", time: "", text: String(n.text || "").slice(0, 4000) }));
    const typed = String($("#afterNotes").value || "").split(/\n+/).filter((t) => t.trim()).slice(0, 2000).map((t) => ({ speaker: "Your notes", time: "", text: t.slice(0, 4000) }));
    const lines = panel.concat(typed).filter((l) => l.text.trim());
    const st = mnState(id);
    if (!lines.length) { st.error = "No call notes yet: type them above, or in the in-call panel's Notes tab."; renderMentions(id); announce(st.error); return; }
    if (DEMO) { useSample(id); return; }
    findMentions(id, { lines, source: "notes" }, "your call notes");
  }
  async function mnAction(id, mid, action, index) {
    const st = mnState(id);
    const it = (st.items || []).find((x) => x.id === mid);
    if (!it && !(st.orgs || []).some((x) => x.id === mid)) return;
    const org = !it && (st.orgs || []).find((x) => x.id === mid);
    if (st.sample && (it || org)) { // demo: this page only
      const x = it || org;
      if (action === "remove" || action === "restore") {
        Object.assign(x, { removed: action === "remove", connected: action !== "remove" });
        st.gone = st.gone || {};
        if (action === "remove") { st.gone[mid] = D.relationships.filter((r) => r.mentionId === mid); D.relationships = D.relationships.filter((r) => r.mentionId !== mid); }
        else { D.relationships = D.relationships.concat(st.gone[mid] || []); delete st.gone[mid]; }
      }
      if (org) { renderMentions(id); announce("Sample data: changed on this page only."); mnFocus(mid); return; }
      if (action === "again") Object.assign(it, { status: "notfound", person: null, autoFound: false, connected: false, note: "In the demo nothing is looked up on the web." });
      if (action === "pick" && it.candidates[index]) Object.assign(it, { status: "found", person: it.candidates[index], candidates: [], confirmed: true, likely: false, connected: true });
      if (action === "confirm") it.confirmed = true;
      if (action === "add") Object.assign(it, { added: true, confirmed: true });
      if (action === "none") Object.assign(it, { status: "notfound", person: null, candidates: [], autoFound: false, connected: false, note: "You said none of these." });
      delete st.change[mid];
      renderMentions(id);
      announce("Sample data: changed on this page only.");
      mnFocus(mid);
      return;
    }
    try {
      const j = await C.postJson("/api/mentions/pick", Object.assign({ callId: id, id: mid, action }, action === "pick" ? { index } : {}), 15000);
      st.items = j.items || st.items;
      st.orgs = j.orgs || st.orgs;
      delete st.change[mid];
      mnGraph(id, j);
      announce({ pick: "Picked. Added to the People map.", confirm: "Confirmed.", add: "Added to Overture's records.", none: "Marked as not found.", again: "Looking it up.",
        remove: "Removed from the People map.", restore: "Back on the People map." }[action]);
    } catch (e) { toast(e.message === "no-key" ? "Add a Claude key to look people up." : e.message); }
    renderMentions(id);
    mnFocus(mid);
    mnWatch();
  }
  function mnFocus(mid) {
    const row = $('[data-mn-item="' + CSS.escape(mid) + '"]');
    const b = row && (row.querySelector(".mn-actions button") || row.querySelector("[data-mn-act]"));
    if (b) b.focus(); else if (row) { row.setAttribute("tabindex", "-1"); row.focus(); }
  }
  async function mnHubspot(id, mid, confirm) {
    const st = mnState(id), h = st.hs[mid] || (st.hs[mid] = { plan: null, error: "", busy: false, done: "" });
    if (h.busy) return;
    h.busy = true; h.error = "";
    renderMentions(id);
    try {
      if (!confirm) {
        h.plan = (await C.postJson("/api/mentions/hubspot", { callId: id, id: mid }, 20000)).plan;
      } else {
        await C.postJson("/api/mentions/hubspot", { callId: id, id: mid, confirm: true, planId: h.plan.planId }, 20000);
        h.plan = null; h.done = "Saved to HubSpot as a contact.";
        announce(h.done);
        await loadMentions(id);
      }
    } catch (e) { h.error = e.message; announce(e.message); }
    h.busy = false;
    renderMentions(id);
    const b = $('[data-mn-item="' + CSS.escape(mid) + '"] [data-mn-hs-save], [data-mn-item="' + CSS.escape(mid) + '"] [data-mn-hs]');
    if (b) b.focus();
  }
  // While a mention is "Looking up…" (or a company waits for an explanation), ask the server every 1.8 s (GET /api/research carries
  // their statuses and starts a company's web lookup once its 30 seconds are up), and refetch when one changes.
  let mnTimer = null;
  const MN_POLL = 1800;
  function mnWatch() {
    if (!LIVE_MODE || mnTimer) return;
    const pending = () => app.view === "call" && mnCalls[app.callId] && ((mnCalls[app.callId].items || []).some((x) => x.status === "pending")
      || (mnCalls[app.callId].orgs || []).some((x) => x.status === "pending" || x.status === "waiting"));
    const tick = async () => {
      mnTimer = null;
      if (!pending()) return;
      if (document.visibilityState === "visible") {
        try {
          const r = await C.fetchTimeout("/api/research", 8000);
          const j = r.ok ? await r.json() : {};
          const id = app.callId, now = (j.mentions || {})[id] || {}, st = mnCalls[id];
          if (st && st.items && st.items.concat(st.orgs || []).some((x) => now[x.id] && now[x.id] !== x.status)) await loadMentions(id);
        } catch (e) { /* try again next tick */ }
      }
      if (pending() && !mnTimer) mnTimer = setTimeout(tick, MN_POLL);
    };
    if (pending()) mnTimer = setTimeout(tick, MN_POLL);
  }

  function mnSources(list) {
    const links = (list || []).map((s) => ({ href: C.safeHref(s.url), label: s.label })).filter((s) => s.href);
    return links.length ? '<p class="rs-src mn-src">' + (links.length > 1 ? "Sources: " : "Source: ") + links.map((s) => '<a href="' + esc(s.href) + '" target="_blank" rel="noopener noreferrer">'
      + esc(s.label || new URL(s.href).hostname) + ic("link", "ext") + NEW_TAB + "</a>").join(" · ") + "</p>" : "";
  }
  function mnFacts(p) {
    const facts = [C.RELATION[p.relationship], p.team, p.seniority ? mnCap(p.seniority) : "", p.tenure ? p.tenure + " there" : "",
      p.confidence ? mnCap(p.confidence) + " confidence" : ""].filter(Boolean);
    const met = p.met && p.met.known ? (p.met.last ? "You've met them (last " + p.met.last + ")" : "You haven't met them") : "";
    return (facts.length ? '<p class="mn-facts">' + esc(facts.join(" · ")) + "</p>" : "") + (met ? '<p class="mn-met">' + esc(met) + "</p>" : "")
      + (p.why ? '<p class="mn-why">' + esc(p.why) + "</p>" : "");
  }
  function mnFromTag(p) {
    if (!p || !p.from) return "";
    if (p.from === "Web") return '<span class="pill tag-teal">Found on the web</span>' + (DEMO ? '<span class="src sample">Sample</span>' : "");
    return srcTag(DEMO ? "Sample data" : p.from);
  }
  function mnItem(id, it) {
    const s = MN_STATUS[it.status] || MN_STATUS.notfound, p = it.person, st = mnState(id), h = st.hs[it.id];
    const shown = p && p.name ? p.name : it.name || mnCap(it.role) || "Someone";
    const said = it.name && it.role ? it.name + " (" + it.role + ")" : it.name || (it.role ? "“" + it.role + "”" : "");
    let x = '<li class="mn-item" data-mn-item="' + esc(it.id) + '">' + avatar({ name: p && p.name ? p.name : it.name || "?" }, "lg") + '<div class="mn-body">';
    x += '<p class="mn-name"><strong>' + esc(shown) + "</strong>" + (p && p.title ? "<span>· " + esc(p.title) + "</span>" : "")
      + '<span class="pill ' + s[1] + '">' + (it.status === "pending" ? ic("loader", "spin") : it.status === "found" || it.status === "known" ? ic("check") : "")
      + esc(it.autoFound && !it.confirmed && it.status === "found" ? "Found automatically" : s[0]) + "</span>"
      + mnFromTag(p) + (it.confirmed ? '<span class="pill tag-gray">Confirmed</span>' : "") + "</p>";
    if (said && (!p || !p.name || p.name.toLowerCase() !== it.name.toLowerCase())) x += '<p class="mn-said-as">Mentioned as ' + esc(said) + (it.count > 1 ? ", " + plural(it.count, "time") : "") + "</p>";
    const q = it.quote || {};
    if (q.text) x += '<blockquote class="note-quote mn-quote"><span>“' + esc(q.text) + "”</span>" + (q.speaker || q.time ? '<span class="mn-who">' + esc([q.speaker, q.time].filter(Boolean).join(", ")) + "</span>" : "") + "</blockquote>";
    if (it.said) x += mnSaid(it.said.label, it.said.said);
    if (p) x += mnFacts(p) + mnSources(p.sources);
    if (it.status === "pick" && it.candidates.length) {
      const likely = it.likely && it.candidates[0] && it.candidates[0].from === "Web";
      x += '<p class="mn-cap">' + esc(likely ? (it.candidates.length > 1 ? "Most likely first. Nothing goes on the People map until you pick." : "One possible match. Nothing goes on the People map until you pick.")
        : it.note || "Who did they mean? Overture won't pick for you.") + '</p><ul class="mn-cands" role="list">' + it.candidates.map((c, i) => '<li class="mn-cand' + (likely && !i ? " likely" : "") + '">'
        + '<p class="mn-name"><strong>' + esc(c.name) + "</strong>" + (c.title ? "<span>· " + esc(c.title) + "</span>" : "")
        + (likely && !i ? '<span class="pill tag-orange">Likely, not confirmed</span>' : "") + mnFromTag(c) + "</p>"
        + mnFacts(c) + mnSources(c.sources)
        + '<p class="mn-actions"><button type="button" class="btn secondary sm" data-mn-act="pick" data-mn-index="' + i + '" aria-label="' + esc("Pick " + c.name) + '">' + ic("check") + "Pick</button></p></li>").join("")
        + '</ul><p class="mn-actions"><button type="button" class="btn ghost sm" data-mn-act="none">None of these</button></p>';
    } else if (it.note && !p) x += '<p class="rs-note">' + esc(it.note) + "</p>";
    const acts = [];
    if ((it.status === "found" || it.status === "known") && p) {
      if (!it.confirmed) acts.push('<button type="button" class="btn secondary sm" data-mn-act="confirm">' + ic("check") + "Confirm</button>");
      if (it.autoFound && !it.confirmed) acts.push('<button type="button" class="btn ghost sm" data-mn-change aria-expanded="' + !!st.change[it.id] + '">' + ic("pencil") + "Change</button>");
      if (!it.added && p.from !== "Overture records") acts.push('<button type="button" class="btn ghost sm" data-mn-act="add">' + ic("plus") + "Add to Overture records</button>");
      if (hubspotOn() && p.from !== "HubSpot" && !it.hubspot && !(h && h.plan)) acts.push('<button type="button" class="btn ghost sm" data-mn-hs' + (h && h.busy ? " disabled" : "") + ">" + (h && h.busy ? ic("loader", "spin") : "") + "Save to HubSpot</button>");
      if (it.status === "found" && !st.sample && !it.autoFound) acts.push('<button type="button" class="btn ghost sm" data-mn-act="none">Not them</button>');
    }
    if (LIVE_MODE && C.state.claudeOn && (it.status === "notfound" || it.status === "error" || it.status === "nokey")) acts.push('<button type="button" class="btn ghost sm" data-mn-act="again">' + ic("rotate") + (it.status === "error" ? "Try again" : "Look up on the web") + "</button>");
    if (acts.length) x += '<p class="mn-actions">' + acts.join("") + "</p>";
    if (it.autoFound && st.change[it.id]) x += '<div class="mn-change"><p class="help">Overture picked this because it was the only sourced match for the name and team said on the call.</p>'
      + '<p class="mn-actions"><button type="button" class="btn ghost sm" data-mn-act="none">Not them</button>'
      + (LIVE_MODE && C.state.claudeOn ? '<button type="button" class="btn ghost sm" data-mn-act="again">' + ic("rotate") + "Look up again</button>" : "") + "</p></div>";
    if (it.explain && (["found", "known", "pick"].includes(it.status) || it.said)) x += C.explainFold(it.explain, { noMention: true });
    x += mnConn(it);
    if (it.added) x += '<p class="mn-done">' + ic("check") + (DEMO ? "Added (sample data, this page only)." : "In Overture's records: Overture knows them on the next transcript.") + "</p>";
    if (it.hubspot) x += '<p class="mn-done">' + ic("check") + (it.hubspot === "unknown" ? "A save to HubSpot got no answer: check HubSpot before saving again." : "Saved to HubSpot as a contact.") + "</p>";
    if (h && (h.plan || h.error)) {
      x += '<div class="mn-hs">' + (h.plan ? '<p class="help hs-lead">Nothing goes to HubSpot until you press Save. This is exactly what it writes:</p><ul class="hs-plan" role="list"><li><p class="hs-what">' + ic("users")
        + "<span>A new contact: first name <strong>" + esc(h.plan.firstname) + "</strong>, last name <strong>" + esc(h.plan.lastname) + "</strong>"
        + (h.plan.jobtitle ? ", job title “" + esc(h.plan.jobtitle) + "”" : "") + (h.plan.company ? ", linked to the company <strong>" + esc(h.plan.company) + "</strong>" : ", not linked to a company (HubSpot has none for this call)") + ".</span></p></li></ul>"
        + '<p class="help">No email address or phone number is written.</p><p class="mn-actions"><button type="button" class="btn primary sm" data-mn-hs-save' + (h.busy ? " disabled" : "") + ">"
        + (h.busy ? ic("loader", "spin") + "Saving…" : "Save to HubSpot") + '</button><button type="button" class="btn ghost sm" data-mn-hs-cancel>Cancel</button></p>' : "")
        + (h.error ? '<p class="hs-result bad" role="alert">' + esc(h.error) + "</p>" : "") + "</div>";
    }
    return x + "</div></li>";
  }
  // What the call itself said about them right after ("he owns the roadmap", "they're our vendor for logging").
  function mnSaid(label, said) {
    return '<p class="mn-rel"><span class="pill tag-purple">Said on the call</span><span>' + esc(label) + "</span></p>"
      + (said ? '<p class="mn-why">“' + esc(said) + "”</p>" : "");
  }
  // On the People map, with a way to take a wrong connection off (and put it back).
  function mnConn(x) {
    if (x.removed) return '<p class="mn-conn">' + ic("network") + '<span>Removed from the People map.</span><button type="button" class="link-btn" data-mn-act="restore">Add back</button></p>';
    if (!x.connected) return "";
    return '<p class="mn-conn">' + ic("network") + "<span>" + (DEMO ? "On the People map (sample)." : "On the People map.") + '</span><a class="link-btn" href="#/map">Open map</a>'
      + '<button type="button" class="link-btn" data-mn-act="remove">Remove</button></p>';
  }
  function orgItem(id, o) {
    const s = ORG_STATUS[o.status] || ORG_STATUS.unknown, r = o.relation;
    let x = '<li class="mn-item" data-mn-item="' + esc(o.id) + '">' + coTile(o.name, "co-tile mn-co") + '<div class="mn-body">';
    x += '<p class="mn-name"><strong>' + esc(o.name) + "</strong>" + (r && r.type !== "unknown" ? "<span>· " + esc(mnCap(r.label)) + "</span>" : "")
      + '<span class="pill ' + s[1] + '">' + (o.status === "pending" || o.status === "waiting" ? ic("loader", "spin") : "") + esc(s[0]) + "</span>"
      + (DEMO ? '<span class="src sample">Sample</span>' : "") + "</p>";
    const q = o.quote || {};
    if (q.text) x += '<blockquote class="note-quote mn-quote"><span>“' + esc(q.text) + "”</span>" + (q.speaker || q.time ? '<span class="mn-who">' + esc([q.speaker, q.time].filter(Boolean).join(", ")) + "</span>" : "") + "</blockquote>";
    if (r && r.source === "said" && r.said && !(q.text && q.text.includes(r.said.replace(/…/g, "")))) x += '<p class="mn-why">“' + esc(r.said) + "”</p>"; // the header already names the relation
    else if (r && r.type !== "unknown") x += '<p class="mn-facts">' + esc([r.detail && r.detail !== "former" ? "For " + r.detail : "", r.confidence ? mnCap(r.confidence) + " confidence" : ""].filter(Boolean).join(" · ")) + "</p>" + mnSources(r.sources);
    if (o.note) x += '<p class="rs-note">' + esc(o.note) + "</p>";
    if (LIVE_MODE && C.state.claudeOn && (o.status === "unknown" || o.status === "error" || o.status === "nokey")) x += '<p class="mn-actions"><button type="button" class="btn ghost sm" data-mn-act="again">' + ic("rotate") + (o.status === "error" ? "Try again" : "Look up on the web") + "</button></p>";
    if (o.explain && r && r.type !== "unknown") x += C.explainFold(o.explain, { noMention: true });
    return x + mnConn(o) + "</div></li>";
  }
  // "From Granola": the note Overture read after the call (its title, a link and Granola's summary). The transcript itself isn't kept.
  function granolaHtml(g) {
    const href = C.safeHref(g.url);
    return '<div class="mn-granola"><p class="mn-name"><strong>From Granola</strong>' + srcTag("Granola") + "</p>"
      + '<p class="mn-facts">' + esc([g.title, g.found ? plural(g.found, "new mention") : "", g.at ? "read " + fmtDate(String(g.at).slice(0, 10)) : ""].filter(Boolean).join(" · ")) + "</p>"
      + (href ? '<p class="mn-src"><a href="' + esc(href) + '" target="_blank" rel="noopener noreferrer">Open in Granola' + ic("link", "ext") + NEW_TAB + "</a></p>" : "")
      + (g.summary ? '<details class="fold mn-sample"><summary>' + ic("chevron", "chev") + "Granola's summary</summary><pre class=\"mn-pre\">" + esc(g.summary) + "</pre></details>" : "") + "</div>";
  }
  function renderMentions(id) {
    const el = $("#mentions");
    if (!el || app.callId !== id) return;
    const st = mnState(id), a = document.activeElement, focusSel = a && a.closest("#mentions") && a.id ? "#" + a.id : "";
    let h = '<div class="sec-head"><h2 id="mnH">Mentioned on the call</h2>' + srcTag(DEMO ? "Sample data" : "Your transcript") + "</div>";
    h += '<p class="help mn-lead">Drop a Zoom or Google Meet transcript (.vtt, .srt or .txt), paste one, or use your call notes (notes typed in the in-call panel are read while you type). Overture finds the people and companies that were talked about, who they are and how they relate, and adds them to the People map. The transcript stays on this PC: Overture keeps only who was mentioned and the sentence they came up in.</p>';
    h += '<div class="mn-drop" data-mn-drop><input type="file" id="mnFile" class="sr-only" accept=".vtt,.srt,.txt,text/vtt,text/plain"' + (st.busy ? " disabled" : "") + ">"
      + '<label for="mnFile" class="btn secondary sm">' + ic("note") + "Choose a transcript</label><span class=\"mn-drop-text\">or drop it here</span></div>";
    h += '<p class="mn-actions mn-sources">'
      + '<button type="button" class="btn ghost sm" id="mnPasteBtn" aria-expanded="' + st.paste + '"' + (st.busy ? " disabled" : "") + ">" + ic("pencil") + "Paste a transcript</button>"
      + '<button type="button" class="btn ghost sm" id="mnNotesBtn"' + (st.busy ? " disabled" : "") + ">" + ic("panel") + "Use my call notes</button>"
      + (gongTranscriptsOn() ? '<button type="button" class="btn ghost sm" id="mnGongBtn"' + (st.busy ? " disabled" : "") + ">" + ic("phone") + "Read Gong's transcript</button>" : "")
      + (granolaOn() ? '<button type="button" class="btn ghost sm" id="mnGranolaBtn"' + (st.busy ? " disabled" : "") + ">" + ic("note") + (st.granola && st.granola.status === "done" ? "Read Granola's note again" : "Read Granola's note") + "</button>" : "")
      + (DEMO ? '<button type="button" class="btn ghost sm" id="mnSampleBtn">' + ic("play") + "Try the sample transcript</button>" : "") + "</p>";
    if (st.paste) h += '<div class="mn-paste"><label class="field-label" for="mnPaste">Transcript</label><textarea id="mnPaste" class="notes-box mn-paste-box" rows="6" maxlength="1000000" placeholder="Paste the transcript here"></textarea>'
      + '<p class="mn-actions"><button type="button" class="btn primary sm" id="mnPasteGo"' + (st.busy ? " disabled" : "") + '>Find people</button><button type="button" class="btn ghost sm" id="mnPasteCancel">Cancel</button></p></div>';
    if (st.busy) h += '<p class="busy hs-busy">' + ic("loader", "spin") + "Reading the transcript…</p>";
    if (st.error) h += '<p class="hs-result bad mn-msg" role="alert">' + esc(st.error) + "</p>";
    else if (st.notice) h += '<p class="mn-msg muted-line" role="status">' + esc(st.notice) + "</p>";
    if (st.loading && !st.items) h += '<p class="busy hs-busy">' + ic("loader", "spin") + "Loading…</p>";
    if (st.granola && st.granola.status === "done") h += granolaHtml(st.granola);
    const items = st.items || [], orgs = st.orgs || [];
    if (items.length && orgs.length) h += '<h3 class="sub-label mn-sub">People</h3>';
    if (items.length) h += '<ul class="mn-list" role="list">' + items.map((it) => mnItem(id, it)).join("") + "</ul>";
    if (orgs.length) h += '<h3 class="sub-label mn-sub">Companies</h3><ul class="mn-list" role="list">' + orgs.map((o) => orgItem(id, o)).join("") + "</ul>";
    if (DEMO && st.sample) h += '<details class="fold mn-sample"><summary>' + ic("chevron", "chev") + "Show the sample transcript</summary><pre class=\"mn-pre\">" + esc(D.mentionSample.transcript) + "</pre></details>";
    el.innerHTML = h;
    if (focusSel && $(focusSel)) $(focusSel).focus();
  }

  function renderAfter(run) {
    const inv = run.ctx.invite;
    $("#afterHead").innerHTML = '<div class="title-row"><h1 tabindex="-1">' + esc(inv.company) + '</h1></div><p class="meta">After the call · ' + esc(inv.title) + "</p>";
    $("#afterNotes").value = run.notes;
    const panelNotes = store.get("notes:" + inv.id) || [];
    $("#importNotes").hidden = !panelNotes.length;
    $("#importNotes").innerHTML = ic("panel") + "Bring in " + plural(panelNotes.length, "note") + " from the in-call panel";
    renderChanges(run);
    renderMentions(inv.id);
    const mns = mnState(inv.id);
    if (LIVE_MODE && !mns.loading) loadMentions(inv.id); // every visit: the in-call panel may have found more since
    renderHubspot(inv.id);
    renderFollowup(inv.id);
    const hs = hsState(inv.id);
    if (hubspotOn() && !hs.plan && !hs.loading && !hs.error) refreshHubspotPlan(inv.id);
  }
  function renderChanges(run) {
    const list = run.changes;
    $("#results").hidden = !list;
    if (!list) return;
    $("#resultsTitle").textContent = list.length ? plural(list.length, "suggested update") : "No updates";
    $("#acceptAll").hidden = !list.some((c) => !c.state);
    $("#changes").innerHTML = list.length ? list.map((c, i) => '<li data-i="' + i + '"' + (c.state ? ' class="' + c.state + '"' : "") + '><span class="kind"><span class="pill ' + tagFor("change", c.kind) + '">' + esc(c.kind) + "</span></span><p>" + esc(c.text) + '</p><div class="actions">'
      + (c.state === "saved" ? '<span class="done-note status-pill no-dot tag-green" tabindex="-1">' + ic("check") + 'Saved</span><button type="button" class="btn ghost sm" data-act="undo">Undo</button>'
        : c.state === "dismissed" ? '<span class="done-note off status-pill tag-gray" tabindex="-1">Dismissed</span><button type="button" class="btn ghost sm" data-act="undo">Undo</button>'
        : '<button type="button" class="btn secondary sm" data-act="accept">' + ic("check") + 'Accept</button><button type="button" class="btn ghost sm" data-act="dismiss">Dismiss</button>')
      + "</div></li>").join("") : '<li><p class="muted-line">Nothing new in these notes.</p></li>';
    const saved = list.filter((c) => c.state === "saved").length, dismissed = list.filter((c) => c.state === "dismissed").length;
    $("#tally").textContent = saved || dismissed ? [saved ? saved + " saved to " + SRC.recordsList : "", dismissed ? dismissed + " dismissed" : ""].filter(Boolean).join(" · ") : "";
  }

  function showTab(tab) {
    const brief = tab === "brief";
    $("#tabBrief").setAttribute("aria-selected", String(brief));
    $("#tabAfter").setAttribute("aria-selected", String(!brief));
    $("#tabBrief").tabIndex = brief ? 0 : -1;
    $("#tabAfter").tabIndex = brief ? -1 : 0;
    $("#panelBrief").hidden = !brief;
    $("#panelAfter").hidden = brief;
  }
  function renderCallView() {
    const id = app.callId, run = runs[id], inv = inviteById(id);
    const done = !!(run && run.ctx && run.ctx.done && !run.error && runningId !== id);
    $("#backLink").innerHTML = ic("chevronLeft") + "<span>Calls</span>";
    $("#backLink").setAttribute("aria-label", "Back to calls");
    $("#callTabs").hidden = runningId === id; // always there: After the call works before the agent has run (it runs it)
    renderAfterCount(id);
    $("#runAgain").hidden = !done;
    $("#runAgain").disabled = !!runningId;
    $("#openInCall").href = "#/live";
    $("#openInCall").dataset.call = id;
    $("#openInCall").innerHTML = ic("panel") + "In-call panel";
    if (!done) showTab("brief");
    if (!run) return renderStart(inv);
    if (runningId === id) return renderRunning(run);
    if (run.error) return renderError(run);
    renderBrief(run);
    renderAfter(run);
    showTab(run.tab);
  }
  function setTab(tab) {
    const run = runs[app.callId];
    if (tab === "after" && openAfter(app.callId)) return; // runs the agent first, then shows After the call
    if (!run || !run.ctx || !run.ctx.done) return;
    run.tab = tab;
    history.replaceState(null, "", "#/calls/" + app.callId + (tab === "after" ? "/after" : ""));
    showTab(tab);
    (tab === "brief" ? $("#tabBrief") : $("#tabAfter")).focus();
    $(".main").scrollTop = 0;
    window.scrollTo(0, 0);
  }

  // ---------- follow-up email (Settings > Follow-up email templates): filled from the call and its notes. Overture never sends it. ----------
  const fuState = {}; // per call id: { type, to, subject, body, said }
  const FU_TYPES = { intro: "intro", discovery: "discovery", demo: "demo", renewal: "renewal", other: "follow-up" };
  function callType(inv) {
    const t = (inv.title + " " + kindOf(inv)).toLowerCase();
    return /renew/.test(t) ? "renewal" : /\bdemo/.test(t) ? "demo" : /discover/.test(t) ? "discovery" : /\bintro/.test(t) ? "intro" : "other";
  }
  // The fill-ins: {first_name} {company} {my_name} {next_step} {summary} {date}. Anything Overture can't fill stays as [add ...] for you.
  function followupDraft(id) {
    const run = runs[id], inv = inviteById(id), type = callType(inv), tpl = C.prefs().followup.templates[type];
    // One bullet per sentence of the notes (and per in-call note).
    const notes = String((run && run.notes) || inv.afterNotes || "").split(/\n+|(?<=[.!?])\s+(?=[A-Z])/).map((x) => x.trim().replace(/^[-*•]\s*/, "")).filter(Boolean);
    const panel = store.get("notes:" + id) || [];
    const lines = notes.concat(panel.filter((n) => n.kind !== "Next step").map((n) => n.text)).filter((l) => !/^(note|question|objection|next step):\s*$/i.test(l));
    const fromPanel = (panel.find((n) => n.kind === "Next step") || {}).text;
    const fromUpdates = run && run.changes ? (run.changes.find((c) => c.kind === "Next step" && c.state !== "dismissed") || {}).text : "";
    const fromNotes = lines.find((l) => /^next steps?\b|\bnext (call|week|meeting)\b|follow[- ]up/i.test(l));
    const firsts = inv.attendees.map((a) => a.name.split(" ")[0]).filter(Boolean);
    const vals = {
      first_name: firsts.length > 2 ? "all" : firsts.join(" and ") || "there", company: inv.company, my_name: ME.name === "You" ? "[your name]" : ME.name,
      next_step: String(fromPanel || fromNotes || fromUpdates || "[add the next step]").replace(/^next steps?:\s*/i, ""),
      summary: lines.length ? lines.slice(0, 6).map((l) => "- " + l).join("\n") : "[add what you talked about]",
      date: today().toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" }),
    };
    const fill = (t) => String(t).replace(/\{(first_name|company|my_name|next_step|summary|date)\}/g, (_, k) => vals[k]);
    return { type, to: inv.attendees.map((a) => a.email).filter(Boolean), subject: fill(tpl.subject), body: fill(tpl.body), said: "" };
  }
  const mailtoHref = (d) => "mailto:" + d.to.map((a) => encodeURIComponent(a).replace(/%40/g, "@")).join(",") + "?subject=" + encodeURIComponent(d.subject) + "&body=" + encodeURIComponent(d.body);
  function renderFollowup(id) {
    const el = $("#followUp"), inv = inviteById(id), d = fuState[id];
    if (!el || !inv) return;
    const kind = FU_TYPES[callType(inv)];
    let h = '<div class="sec-head"><h2 id="fuH">Follow-up email</h2><span class="grow"></span><a class="ghost-edit" href="#/settings/followup">' + ic("pencil") + "Templates</a></div>";
    if (!d) {
      h += '<p class="help fu-help">Fills in your ' + esc(kind) + " template from this call and your notes. Overture never sends it: copy it, or open it in your mail app.</p>"
        + '<div class="after-actions"><button type="button" class="btn secondary" data-fu="draft">' + ic("pencil") + "Draft follow-up</button></div>";
    } else {
      h += '<div class="fu-form"><label class="field-label" for="fuTo">To</label><input id="fuTo" class="input" value="' + esc(d.to.join(", ")) + '" readonly aria-describedby="fuToHelp">'
        + '<p class="help" id="fuToHelp">The guests on the invite.</p>'
        + '<label class="field-label" for="fuSubject">Subject</label><input id="fuSubject" class="input" maxlength="200" value="' + esc(d.subject) + '">'
        + '<label class="field-label" for="fuBody">Message</label><textarea id="fuBody" class="input fu-body" rows="12">' + esc(d.body) + "</textarea>"
        + '<div class="after-actions fu-actions"><button type="button" class="btn primary" data-fu="copy">' + ic("check") + "Copy</button>"
        + '<a class="btn secondary" id="fuMail" href="' + esc(mailtoHref(d)) + '">' + ic("link") + "Open in mail app</a>"
        + '<button type="button" class="btn ghost" data-fu="redraft">' + ic("rotate") + "Fill in again</button>"
        + '<span class="fu-said" role="status">' + esc(d.said) + "</span></div></div>";
    }
    el.innerHTML = h;
  }
  async function copyText(text) {
    try { await navigator.clipboard.writeText(text); return true; } catch (e) { /* older browsers and blocked clipboards: the textarea way */ }
    const t = document.createElement("textarea");
    t.value = text; t.setAttribute("readonly", ""); t.style.position = "fixed"; t.style.opacity = "0";
    document.body.appendChild(t); t.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
    t.remove();
    return ok;
  }
  $("#followUp").addEventListener("click", async (e) => {
    const b = e.target.closest("[data-fu]"), id = app.callId;
    if (!b) return;
    if (b.dataset.fu === "draft" || b.dataset.fu === "redraft") {
      fuState[id] = followupDraft(id);
      renderFollowup(id);
      $("#fuSubject").focus();
      announce("Follow-up drafted from the " + FU_TYPES[fuState[id].type] + " template. Nothing has been sent.");
      return;
    }
    if (b.dataset.fu === "copy") {
      const d = fuState[id], ok = await copyText("Subject: " + d.subject + "\n\n" + d.body);
      d.said = ok ? "Copied" : "Couldn't copy. Select the text and copy it.";
      $(".fu-said").textContent = d.said;
      setTimeout(() => { if (fuState[id] === d && d.said === "Copied") { d.said = ""; const s = $(".fu-said"); if (s) s.textContent = ""; } }, 2500);
    }
  });
  $("#followUp").addEventListener("input", (e) => {
    const d = fuState[app.callId];
    if (!d) return;
    if (e.target.id === "fuSubject") d.subject = e.target.value;
    if (e.target.id === "fuBody") d.body = e.target.value;
    const m = $("#fuMail");
    if (m) m.href = mailtoHref(d);
  });

  // ---------- alerts: an inbox (list left, reading pane right; on phones the list, then the alert). Refs at the top of inbox.css. ----------
  Object.assign(C.ICONS, {
    chevronUp: '<path d="m18 15-6-6-6 6"/>',
    bellDot: '<path d="M10.268 21a2 2 0 0 0 3.464 0"/><path d="M13.916 2.314A6 6 0 0 0 6 8c0 4.499-1.411 5.956-2.74 7.327A1 1 0 0 0 4 17h16a1 1 0 0 0 .74-1.673 9 9 0 0 1-.585-.665"/><circle cx="18" cy="8" r="3"/>',
  });
  const IB_WIDE = "(min-width: 1100px)"; // two panes from here up; keep in step with inbox.css
  const ib = { filter: "all" };          // list filter: "all" | "unread"
  const ibTime = (a) => { const [m, d] = String(a.date).split(" "); return new Date(+D.today.slice(0, 4), MONTHS.indexOf(m), +d).getTime(); };
  const ibSorted = () => alerts().sort((x, y) => ibTime(y) - ibTime(x)); // newest first, like any inbox
  // The open alert stays in the Unread view after it is read, so it never vanishes from under you.
  const ibVisible = (list) => (ib.filter === "unread" ? (list || ibSorted()).filter((x) => !readAlerts.has(x.id) || x.id === app.alertId) : list || ibSorted());

  function alertChanges(a) {
    // Alerts from Settings > Alert rules' other signals: a new Backstage release, people mentioned on a call, HubSpot stage changes.
    if (a.kind === "New release") return { rows: [["Latest Backstage", null, C.state.latest.version], ["Released", null, fmtDate(C.state.latest.date)]] };
    if (a.kind === "Mentioned") { const mi = a.callId ? inviteById(a.callId) : null; return { rows: [["Who", null, a.person || "Someone"], ["Mentioned on", null, mi ? mi.company + " call" : "a call"]], person: a.person }; }
    if (a.kind === "Stage change") return { rows: [["HubSpot stage", null, a.title.replace(/^.* moved to /, "")]] };
    if (a.kind === "Security") {
      const recent = SNAP.advisories.filter((x) => Date.parse(D.today) - Date.parse(x.published) <= 30 * 864e5);
      const serious = recent.filter((x) => x.severity === "high" || x.severity === "critical");
      return { rows: [["New notices, last 30 days", null, String(recent.length)], ["High or critical", null, String(serious.length)], ["Newest", null, fmtDate(recent[0].published)]], worst: serious.slice(0, 5) };
    }
    const inv = inviteById(a.callId);
    if (a.kind === "Job change") {
      const name = a.title.split(" moved")[0];
      const att = D.invites.flatMap((i) => i.attendees).find((x) => x.name === name);
      const p = att ? D.people[att.email] : null;
      return { rows: [["Company", p ? p.previous || null : null, inv.company], ["Title", null, p && p.title ? p.title : "Unknown"]], person: name, also: p ? p.previous : null };
    }
    if (a.kind === "First meeting") return { rows: [["Past meetings with them", null, "None in your calendar"], ["Invited", null, plural(inv.attendees.length, "person", "people")]] };
    if (a.kind === "New person") {
      const att = inv.attendees.find((x) => x.name === a.person), p = att ? D.people[att.email] || {} : {}, r = p.research || {};
      const rel = { employee: "Employee", contractor: "Contractor or agency", partner: "Partner", investor: "Investor or board", other: "Other" }[r.relationship];
      return { rows: [["Title", null, p.title || "Unknown"], ["Relationship", null, rel || "Unknown"], ["Found", null, r.found === "confirmed" ? "Automatically, then confirmed" : "Automatically"]], person: a.person };
    }
    const cb = (D.companies[inv.company] || {}).comeBack;
    const hist = (D.companies[inv.company] || {}).history || [];
    const rows = [];
    if (cb) rows.push(["Engineers", String(cb.then), String(cb.now)], ["Open engineering jobs", null, String(cb.openJobs)]);
    if (hist.length) rows.push(["Last talk", null, fmtDate(hist[hist.length - 1].date) + ": " + hist[hist.length - 1].text]);
    return { rows };
  }
  // Who an alert is "from": the person's face for people alerts, the company's letter tile otherwise.
  function ibFrom(a) {
    const inv = a.callId ? inviteById(a.callId) : null;
    if (a.kind === "Job change") { const name = a.title.split(" moved")[0]; return { name, sub: "Job change · now at " + inv.company, face: (lg) => avatar(name, lg ? "lg" : "md") }; }
    if (a.kind === "New person" && a.person) return { name: a.person, sub: "New on the call · " + inv.company, face: (lg) => avatar(a.person, lg ? "lg" : "md") };
    if (a.kind === "Mentioned" && a.person) return { name: a.person, sub: "Mentioned on a call" + (inv ? " · " + inv.company : ""), face: (lg) => avatar(a.person, lg ? "lg" : "md") };
    if (a.kind === "New release") return { name: "Backstage", sub: "New release · GitHub", face: (lg) => coTile("Backstage", "ib-tile" + (lg ? " lg" : "")) };
    if (a.kind === "Stage change" && !inv) { const co = a.title.split(" moved to ")[0]; return { name: co, sub: "Stage change · HubSpot", face: (lg) => coTile(co, "ib-tile" + (lg ? " lg" : "")) }; }
    const name = inv ? inv.company : "Backstage";
    return { name, sub: inv ? a.kind + (DEMO ? " · hiring feed" : " · your calendar") : "Security · GitHub advisories", face: (lg) => coTile(name, "ib-tile" + (lg ? " lg" : "")) };
  }
  function ibReadBtn(a, where) {
    const unread = !readAlerts.has(a.id), label = unread ? "Mark read" : "Mark unread";
    if (where === "pane") return '<button type="button" class="btn ghost sm" data-ib-read="' + esc(a.id) + '" data-k="pr" aria-keyshortcuts="U">' + label + '<kbd aria-hidden="true">U</kbd></button>';
    return '<button type="button" class="ib-act" data-ib-read="' + esc(a.id) + '" data-k="r-' + esc(a.id) + '" aria-label="' + label + ": " + esc(a.title) + '" title="' + label + '">' + ic(unread ? "bell" : "bellDot", "ib-bell") + "</button>";
  }
  function inboxRow(a) {
    const unread = !readAlerts.has(a.id), open = a.id === app.alertId, inv = a.callId ? inviteById(a.callId) : null;
    const next = inv ? '<a class="ib-act" href="#/calls/' + inv.id + '" data-k="n-' + esc(a.id) + '" aria-label="Open the ' + esc(inv.company) + ' call" title="Open the ' + esc(inv.company) + ' call">' + ic("phone", "ib-ring") + "</a>"
      : '<button type="button" class="ib-act" data-open="check" data-focus="anyVersion" data-k="n-' + esc(a.id) + '" aria-label="Check a Backstage version" title="Check a Backstage version">' + ic("search") + "</button>";
    return '<li class="ib-row' + (unread ? " unread" : "") + (open ? " is-open" : "") + '"><span class="ib-dot" aria-hidden="true"></span>' + ibFrom(a).face()
      + '<span class="ib-text"><a class="ib-link" href="#/alerts/' + esc(a.id) + '" data-k="l-' + esc(a.id) + '"' + (open ? ' aria-current="page"' : "") + ">" + (unread ? '<span class="sr-only">Unread: </span>' : "") + esc(a.title) + "</a>"
      + '<span class="ib-prev"><span class="ib-kind">' + esc(a.kind) + "</span> · " + esc(a.text) + "</span></span>"
      + '<span class="ib-side"><span class="ib-date">' + esc(a.date) + '</span><span class="ib-acts">' + ibReadBtn(a, "row") + next + "</span></span></li>";
  }
  function ibDigest(vis) {
    const days = [];
    vis.forEach((a) => { let d = days.find((x) => x.date === a.date); if (!d) days.push(d = { date: a.date, items: [] }); d.items.push(a); });
    return days.map((d, i) => '<section class="ib-digest" aria-labelledby="ibd-' + i + '"><h2 class="ib-digest-h" id="ibd-' + i + '">Daily digest · ' + esc(d.date)
      + '<span class="ib-n">' + d.items.length + '</span></h2><ul class="ib-rows" role="list">' + d.items.map(inboxRow).join("") + "</ul></section>").join("");
  }
  function ibListPane(list, vis) {
    const unread = list.filter((a) => !readAlerts.has(a.id)).length;
    const seg = (key, label, n) => '<button type="button" class="ib-seg-btn" data-ib-filter="' + key + '" data-k="f-' + key + '" aria-pressed="' + (ib.filter === key) + '">' + label + '<span class="ib-n">' + n + "</span></button>";
    return '<div class="ib-list"><div class="ib-head"><div class="ib-head-row"><h1 class="page-title" tabindex="-1" data-k="h1">Alerts</h1><span class="grow"></span>'
      + (unread ? '<button type="button" class="btn ghost sm" data-ib-all data-k="all">Mark all read</button>' : "") + "</div>"
      + '<p class="ib-sub">What changed between your calls.</p>'
      + '<div class="ib-seg" role="group" aria-label="Show">' + seg("all", "All", list.length) + seg("unread", "Unread", unread) + "</div></div>"
      + (vis.length && digestOn() ? ibDigest(vis)
        : vis.length ? '<ul class="ib-rows" role="list" aria-label="Alerts, newest first">' + vis.map(inboxRow).join("") + "</ul>"
        : '<div class="ib-empty"><h2>You\'re all caught up</h2><p>No unread alerts. New ones land here between calls.</p><button type="button" class="btn secondary sm" data-ib-filter="all">Show all alerts</button></div>')
      + '<p class="ib-keys" aria-hidden="true"><kbd>J</kbd><kbd>K</kbd><span>next, previous</span><span class="ib-sep"></span><kbd>U</kbd><span>read, unread</span></p></div>';
  }
  function ibPane(a, vis) {
    const ch = alertChanges(a), f = ibFrom(a), inv = a.callId ? inviteById(a.callId) : null;
    const i = vis.findIndex((x) => x.id === a.id), prev = vis[i - 1], next = vis[i + 1];
    const step = (to, icon, label, key, k) => '<button type="button" class="icon-btn" data-k="' + k + '"' + (to ? ' data-ib-step="' + esc(to.id) + '"' : " disabled") + ' aria-label="' + label + '" title="' + label + " (" + key + ')" aria-keyshortcuts="' + key + '">' + ic(icon) + "</button>";
    const age = relDay(Math.round((ibTime(a) - today().getTime()) / 864e5));
    const w = inv ? splitWhen(inv.when) : null;
    const nextCall = inv ? "<p>Your " + esc(inv.company) + " call is " + esc(longDay(inv)) + " at " + esc(w.start) + ", " + esc(relDay(daysUntil(inv))) + ".</p>" : "";
    const guest = inv && a.kind === "New person" ? inv.attendees.find((x) => x.name === a.person) : null;
    const actions = inv ? '<a class="btn primary" href="#/calls/' + inv.id + '">' + ic("phone", "ib-ring") + "Open the " + esc(inv.company) + " call</a>"
        + (guest ? '<a class="btn secondary" href="#/people/' + esc(C.personKey(guest.email)) + '">Open ' + esc(guest.name.split(" ")[0]) + "'s profile</a>" : "")
        + '<a class="btn secondary" href="#/companies/' + slug(inv.company) + '">Open ' + esc(inv.company) + "</a>"
      : '<button type="button" class="btn primary" data-open="check" data-focus="anyVersion">Check a Backstage version</button>';
    return '<article class="ib-read" aria-labelledby="ibTitle"><div class="ib-bar">'
      + '<a class="back" href="#/alerts" aria-label="Back to alerts">' + ic("chevronLeft") + "<span>Alerts</span></a>"
      + step(prev, "chevronUp", "Previous alert", "K", "s-prev") + step(next, "chevronDown", "Next alert", "J", "s-next")
      + '<span class="ib-pos">' + (i + 1) + " of " + vis.length + '</span><span class="grow"></span>' + ibReadBtn(a, "pane") + "</div>"
      + '<div class="ib-body"><h2 class="alert-h" id="ibTitle" tabindex="-1" data-k="h">' + esc(a.title) + "</h2>"
      + '<p class="ib-labels"><span class="pill ' + tagFor("alert", a.kind) + '">' + esc(a.kind) + "</span>" + srcTag(a.src) + "</p>"
      + '<div class="ib-msg"><div class="ib-from">' + f.face(true) + '<div class="ib-from-who"><p class="ib-from-name">' + esc(f.name) + '</p><p class="ib-from-sub">' + esc(f.sub) + "</p></div>"
      + '<p class="ib-when">' + esc(a.date) + " · " + esc(age) + "</p></div>"
      + '<div class="ib-msg-body"><section><h3>What changed</h3><div class="ib-diff">' + ch.rows.map(([k, old, v]) => '<div class="ib-diff-row"><span class="k">' + esc(k) + '</span><span class="v">'
        + (old ? '<span class="old">' + esc(old) + '</span><span class="arrow" aria-hidden="true">→</span><span class="sr-only"> changed to </span>' : "") + esc(v) + "</span></div>").join("") + "</div></section>"
      + '<section class="ib-why"><h3>' + (inv ? "Why it matters for your next call" : "Why it matters") + "</h3><p>" + esc(a.text) + "</p>" + nextCall + "</section></div>"
      + '<div class="ib-msg-foot">' + actions + "</div></div>"
      + (ch.worst ? '<section class="sec"><div class="sec-head"><h2>Newest serious notices</h2>' + srcTag("Public data") + '</div><ul class="notices" role="list">' + ch.worst.map((x) => '<li><span class="pill ' + tagFor("severity", x.severity) + '">' + esc(x.severity) + '</span><a href="' + esc(x.url) + '" target="_blank" rel="noopener">' + esc(x.summary.replace(/^Backstage:\s*/i, "")) + ic("link", "ext") + NEW_TAB + '</a><span class="muted-line muted-date">' + esc(fmtDate(x.published)) + "</span></li>").join("") + "</ul></section>" : "")
      + (inv ? '<section class="sec"><div class="sec-head"><h2>Details</h2></div><dl class="kv small">'
        + '<dt>Company</dt><dd><a href="#/companies/' + slug(inv.company) + '">' + esc(inv.company) + "</a></dd>"
        + (ch.also ? '<dt>Also affects</dt><dd><a href="#/companies/' + slug(ch.also) + '">' + esc(ch.also) + "</a></dd>" : "")
        + '<dt>Call</dt><dd><a href="#/calls/' + inv.id + '">' + esc(w.day + " " + w.month + " " + w.date + " · " + w.start) + "</a></dd></dl></section>" : "")
      + '<p class="ib-prov">' + (a.kind === "New release" ? "From Backstage's releases on GitHub." : a.kind === "Stage change" ? "From your HubSpot: the deal stage changed since Overture last looked."
        : a.kind === "Mentioned" ? "From the people mentioned on the call (your transcript or notes). Overture looks them up and cites its sources on the call page."
        : a.src === "Public data" ? "From GitHub's public security advisories for Backstage. Saved copy from " + esc(fmtDate(SNAP.takenOn)) + "." : DEMO ? "Sample alert, made up for this demo. It stands in for a job-change and hiring feed."
        : a.kind === "New person" ? "Overture looked this guest up on its own, from their name and company only, using public work sources. Every fact on their profile names its source."
        : "Worked out by Overture from your Google Calendar: this invite compared with your past meetings.") + "</p></div></article>";
  }
  // Draws both panes. Focus survives the redraw: the same control (data-k) gets it back, else the list heading.
  function drawAlerts(want) {
    const sec = $('[data-view="alerts"]'), list = ibSorted(), a = list.find((x) => x.id === app.alertId) || null, vis = ibVisible(list);
    const act = document.activeElement, had = !!act && act !== sec && sec.contains(act), keep = had ? act.dataset.k : null;
    sec.innerHTML = '<div class="ib' + (a ? " has-detail" : "") + '">' + ibListPane(list, vis) + (a ? ibPane(a, vis) : "") + "</div>";
    const el = (want && sec.querySelector(want)) || (keep && sec.querySelector('[data-k="' + keep + '"]')) || (had ? sec.querySelector("h1") : null);
    if (el) el.focus({ preventScroll: true });
  }
  function renderAlerts() {
    const list = ibSorted();
    let a = list.find((x) => x.id === app.alertId);
    if (a) readAlerts.add(a.id); // opening an alert reads it
    else if (list.length && matchMedia(IB_WIDE).matches) {
      // Wide screens open the newest unread alert instead of an empty pane; it stays unread until you open or mark it.
      a = list.find((x) => !readAlerts.has(x.id)) || list[0];
      app.alertId = a.id;
      history.replaceState(null, "", "#/alerts/" + a.id);
    }
    drawAlerts();
  }
  function ibToggle(id) {
    if (readAlerts.has(id)) readAlerts.delete(id); else readAlerts.add(id);
    drawAlerts();
    renderNav();
    announce("Marked " + (readAlerts.has(id) ? "read" : "unread"));
  }
  $('[data-view="alerts"]').addEventListener("click", (e) => {
    const r = e.target.closest("[data-ib-read]");
    if (r) { ibToggle(r.dataset.ibRead); return; }
    const f = e.target.closest("[data-ib-filter]");
    if (f) { ib.filter = f.dataset.ibFilter; drawAlerts('[data-k="f-' + ib.filter + '"]'); return; }
    if (e.target.closest("[data-ib-all]")) { alerts().forEach((a) => readAlerts.add(a.id)); drawAlerts(); renderNav(); announce("All alerts marked read"); return; }
    const s = e.target.closest("[data-ib-step]");
    if (s) go("#/alerts/" + s.dataset.ibStep);
  });
  // Mail keys: J next, K previous, U read or unread. Only on this page, never while typing or in a dialog.
  document.addEventListener("keydown", (e) => {
    if (app.view !== "alerts" || e.ctrlKey || e.metaKey || e.altKey || e.target.closest("input, textarea, select, [contenteditable]") || document.querySelector("dialog[open]")) return;
    const k = e.key.toLowerCase();
    if (k === "j" || k === "k") {
      const vis = ibVisible(), i = vis.findIndex((x) => x.id === app.alertId), to = vis[i < 0 ? 0 : i + (k === "j" ? 1 : -1)];
      if (to && to.id !== app.alertId) { e.preventDefault(); go("#/alerts/" + to.id); }
    } else if (k === "u" && app.alertId) { e.preventDefault(); ibToggle(app.alertId); }
  });

  // ---------- companies (Attio-style list and record page; refs at the top of companies.css) ----------
  let coView = "all"; // the list's status view: all | customer | deal | lead
  const CO_VIEWS = [["all", "All"], ["customer", "Customers"], ["deal", "Open deals"], ["lead", "New leads"]];
  const coStatus = (n) => (D.companies[n] ? D.companies[n].status : "Prospect");
  const coKind = (s) => (/^Customer/.test(s) ? "customer" : /^Open deal/.test(s) ? "deal" : /^New lead/.test(s) ? "lead" : "other");
  // "Open deal: Portal" -> ["Open deal", "Portal"]: the tag, then what the deal or customer is about.
  // "Customer since 2025: Portal and Confidence" -> ["Customer", "Portal and Confidence", "2025"], so the tag stays short.
  const coStatusParts = (s) => {
    const i = String(s).indexOf(": "), head = i < 0 ? String(s) : s.slice(0, i), m = head.match(/^(.*) since (\d{4})$/);
    return [m ? m[1] : head, i < 0 ? "" : s.slice(i + 2), m ? m[2] : ""];
  };
  const coCount = (k) => companyNames().filter((n) => k === "all" || coKind(coStatus(n)) === k).length;
  const coNum = (n) => Number(n).toLocaleString("en-US");
  const coCallDay = (inv) => { const w = splitWhen(inv.when); return w.day + " " + w.month + " " + w.date; };
  const coCompanyLink = (n) => (companyBySlug(slug(n)) ? '<a href="#/companies/' + slug(n) + '">' + esc(n) + "</a>" : esc(n));
  const coFaces = (people, size) => '<span class="stack co-faces" aria-hidden="true">' + people.slice(0, 3).map((p) => avatar(p, size || "sm")).join("") + "</span>";
  // People on this company's calls, and people (on any call) who used to work here.
  function coPeople(name) {
    const withRecord = (a, extra) => Object.assign({ name: a.name, email: a.email }, D.people[a.email] || {}, extra || {});
    const staff = D.invites.filter((i) => i.company === name).flatMap((i) => i.attendees.map((a) => withRecord(a)));
    const alumni = D.invites.flatMap((i) => i.attendees.map((a) => withRecord(a, { now: i.company }))).filter((p) => p.previous === name);
    return { staff, alumni };
  }
  // Backstage signal: on the public adopters list, and the version from the backstage.json added for the call.
  function coBackstage(name) {
    const inv = callForCompany(name), ad = C.findAdopter(name);
    const vf = inv ? C.readVersionFile(inputs[inv.id].versionFile) : null;
    const ver = vf && vf.version ? vf.version : null;
    const from = ver ? C.parseVer(ver) : null, to = C.parseVer(C.state.latest.version);
    const behind = from && to && from[0] === to[0] ? Math.max(0, to[1] - from[1]) : null;
    return { ad, ver, behind, file: !!vf, since: inv ? inputs[inv.id].since : null };
  }

  function coRow(n) {
    const status = coStatus(n), [tag, detail] = coStatusParts(status), c = D.companies[n], inv = callForCompany(n);
    const { staff, alumni } = coPeople(n), bs = coBackstage(n), ppl = staff.length ? staff : alumni;
    const people = ppl.length
      ? coFaces(ppl) + '<span class="co-sub">' + (staff.length ? plural(staff.length, "person", "people") : plural(alumni.length, "ex-employee")) + '</span><span class="sr-only">: ' + esc(ppl.map((p) => p.name).join(", ")) + "</span>"
      : '<span class="co-none">None yet</span>';
    const eng = c && c.engineers ? (c.comeBack ? '<span class="co-sub">was ' + c.comeBack.then + "</span>" : "") + '<span class="co-num">' + coNum(c.engineers) + "</span>"
      : c && c.employees ? '<span class="co-sub">employees</span><span class="co-num">' + coNum(c.employees) + "</span>" : '<span class="co-none">—</span>';
    const signal = bs.ver ? '<span class="pill tag-gray co-ver">' + esc(bs.ver) + "</span>" + (bs.behind != null ? '<span class="co-sub">' + bs.behind + " behind</span>" : "")
      : bs.ad ? '<span class="pill tag-green">Adopter</span>' : bs.file ? '<span class="co-sub">Version file added</span>' : '<span class="co-none">Not listed</span>';
    const call = inv ? '<a class="lift co-call" href="#/calls/' + inv.id + '"><span class="sr-only">Next call: </span>' + ic("phone", "co-phone ic-phone") + '<span class="co-call-day">' + esc(coCallDay(inv)) + '</span><span class="co-sub">' + esc(splitWhen(inv.when).start.replace(/ ET$/, "")) + "</span></a>"
      : '<span class="co-none">No call booked</span>';
    return '<div class="co-tr" role="row"><span class="co-td co-name" role="cell">' + coTile(n) + '<a class="stretch" href="#/companies/' + slug(n) + '">' + esc(n) + "</a>" + C.priorityBadge(n) + "</span>"
      + '<span class="co-td co-status" role="cell"><span class="pill ' + tagFor("status", status) + '">' + esc(tag) + "</span>" + (detail ? '<span class="co-sub">' + esc(detail) + "</span>" : "") + "</span>"
      + '<span class="co-td co-eng" role="cell">' + eng + "</span>"
      + '<span class="co-td co-ppl" role="cell">' + people + "</span>"
      + '<span class="co-td co-bs" role="cell">' + signal + "</span>"
      + '<span class="co-td co-next" role="cell">' + call + "</span></div>";
  }
  // Rows for the current view and search, plus Attio's footer row (count and total engineers).
  function companyRows(filter) {
    const q = (filter || "").toLowerCase();
    const list = C.byPriority(companyNames().filter((n) => (coView === "all" || coKind(coStatus(n)) === coView) && (!q || n.toLowerCase().includes(q))), (n) => n);
    if (!list.length) {
      return '<div class="co-tr co-empty" role="row"><span class="co-td" role="cell">' + (filter
        ? "No company called “" + esc(filter) + "” " + (coView === "all" ? "in the records" : "in this view") + '. <button type="button" class="link-btn" data-check-name="' + esc(filter) + '">Check it against the adopters list</button>'
        : "No companies in this view.") + "</span></div>";
    }
    const total = list.reduce((s, n) => s + ((D.companies[n] || {}).engineers || 0), 0);
    return list.map(coRow).join("")
      + '<div class="co-tr co-foot" role="row"><span class="co-td" role="cell">' + plural(list.length, "company", "companies") + '</span><span class="co-td co-gap" role="cell"></span>'
      + '<span class="co-td co-eng" role="cell"><span class="co-sub">Total</span><span class="co-num">' + coNum(total) + '</span></span><span class="co-td co-gap" role="cell"></span><span class="co-td co-gap co-bs" role="cell"></span><span class="co-td co-gap" role="cell"></span></div>';
  }
  // Asana dashboard number cards: one colour each, the number big, what it means underneath (Mobbin: Asana reporting dashboard).
  function coStats() {
    const names = companyNames();
    const eng = names.reduce((n, c) => n + (+(D.companies[c] || {}).engineers || 0), 0);
    const known = Object.keys(D.people).length;
    const card = (cls, n, label, sub) => '<li class="co-stat ' + cls + '"><span class="co-stat-n">' + n + '</span><span class="co-stat-l">' + label + '</span><span class="co-stat-s">' + sub + "</span></li>";
    return '<ul class="co-stats" role="list" aria-label="Summary">'
      + card("cs-blue", coCount("deal"), "Open deals", "Portal in play")
      + card("cs-purple", coCount("lead"), "New leads", "First calls this week")
      + card("cs-green", coCount("customer"), "Customers", "Already on Spotify")
      + card("cs-orange", eng.toLocaleString("en-US"), "Engineers", "Across these companies")
      + card("cs-pink", known, "People you know", "From calls and past jobs") + "</ul>";
  }
  function renderCompanies() {
    const sec = $('[data-view="companies"]');
    const heads = [["Company", ""], ["Status", ""], ["Engineers", " co-eng"], ["People", ""], ["Backstage", " co-bs"], ["Next call", ""]];
    sec.innerHTML = '<header class="page-head co-page-head"><div class="page-head-row"><h1 class="page-title" tabindex="-1">Companies</h1>' + srcTag(SRC.records)
      + '<span class="grow"></span><button type="button" class="btn secondary sm" data-open="check">Check any company</button></div>'
      + '<p class="page-sub">' + (DEMO ? "Spotify's records for the companies you're meeting, and the people you already know there." : "The companies on your calendar and in Overture's records, and the people you know there.") + "</p></header>"
      + coStats()
      + '<div class="co-bar"><div class="co-views" role="group" aria-label="Show">'
      + CO_VIEWS.filter(([k]) => k === "all" || coCount(k)).map(([k, l]) => '<button type="button" class="co-view" data-co-view="' + k + '" aria-pressed="' + (coView === k) + '">' + l + '<span class="co-view-n">' + coCount(k) + "</span></button>").join("")
      + '</div><span class="grow"></span><div class="co-search">' + ic("search") + '<label for="coSearch" class="sr-only">Search companies</label><input id="coSearch" class="input sm" type="search" placeholder="Search companies" autocomplete="off"></div></div>'
      + '<div class="co-table" role="table" aria-label="Companies"><div class="co-tr co-th" role="row">' + heads.map(([h, cls]) => '<span class="co-td' + cls + '" role="columnheader">' + h + "</span>").join("") + "</div>"
      + '<div id="coRows" role="rowgroup">' + companyRows("") + "</div></div>"
      + '<p class="list-foot">' + (DEMO ? "Made-up companies stand in for HubSpot records. Past employers come from the people you meet; the adopters list is public."
        : "Companies are named from your guests' email domains. Open one to set its status and notes; the adopters list is public.") + "</p>";
    $(".co-views", sec).addEventListener("click", (e) => {
      const b = e.target.closest("[data-co-view]");
      if (!b) return;
      coView = b.dataset.coView;
      $$("[data-co-view]", sec).forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      $("#coRows").innerHTML = companyRows($("#coSearch").value.trim());
    });
  }

  // Everything that happened with a company, newest first: alerts, Spotify's notes, papers, people joining and leaving.
  function coEvents(name, staff, alumni, bs) {
    const year = D.today.slice(0, 4), ev = [], moved = new Set();
    const alertDay = (d) => { const [m, day] = d.split(" "); return year + "-" + String(MONTHS.indexOf(m) + 1).padStart(2, "0") + "-" + String(+day).padStart(2, "0"); };
    alerts().filter((a) => (a.callId && inviteById(a.callId).company === name) || (a.kind === "Job change" && alertChanges(a).also === name)).forEach((a) => {
      const who = a.kind === "Job change" ? a.title.split(" moved")[0] : null;
      if (who) moved.add(who);
      ev.push({ when: alertDay(a.date), kind: a.kind, tint: tagFor("alert", a.kind), person: who, text: '<a href="#/alerts/' + esc(a.id) + '">' + esc(a.title) + "</a>", sub: a.text.split(". ")[0] + "." });
    });
    const sec = bs.ver && bs.behind ? alerts().find((a) => a.kind === "Security") : null;
    if (sec) ev.push({ when: alertDay(sec.date), kind: "Security", tint: "tag-red", text: '<a href="#/alerts/' + esc(sec.id) + '">' + esc(sec.title) + "</a>", sub: "They run Backstage " + bs.ver + ", so some of these may reach them." });
    ((D.companies[name] || {}).history || []).filter((h) => h.date).forEach((h) => ev.push({ when: h.date, kind: h.src === "HubSpot" ? "HubSpot note" : "Note", tint: h.src === "HubSpot" ? "tag-orange" : "tag-gray", text: esc(h.text) }));
    const pp = D.papers[name];
    if (pp && pp.nda && pp.nda.signed) ev.push({ when: pp.nda.date, kind: "Papers", tint: "tag-yellow", text: "NDA signed in " + esc(pp.nda.where) });
    if (pp && pp.securityPack) ev.push({ when: pp.securityPack.sentOn, kind: "Papers", tint: "tag-yellow", text: "Security pack " + esc(pp.securityPack.sent) + " sent" });
    staff.filter((p) => p.startedAt && !moved.has(p.name)).forEach((p) => ev.push({ when: p.startedAt, kind: "People", tint: "tag-blue", person: p,
      text: "<strong>" + esc(p.name) + "</strong> joined as " + esc(p.title) + (p.previous ? ", from " + coCompanyLink(p.previous) : "") }));
    alumni.filter((p) => p.startedAt && !moved.has(p.name)).forEach((p) => ev.push({ when: p.startedAt, kind: "People", tint: "tag-blue", person: p,
      text: "<strong>" + esc(p.name) + "</strong> left to join " + coCompanyLink(p.now) }));
    return ev.sort((a, b) => (a.when < b.when ? 1 : a.when > b.when ? -1 : 0));
  }
  function coTimeline(ev) {
    if (!ev.length) return '<p class="muted-line">Nothing recorded with this company yet.</p>';
    let html = "", yr = null;
    ev.forEach((e) => {
      const y = e.when.slice(0, 4);
      if (y !== yr) { html += (yr ? "</ol>" : "") + '<h3 class="co-year">' + y + '</h3><ol class="co-tl" role="list">'; yr = y; }
      const node = e.person ? avatar(e.person, "xs") : '<span class="co-dot ' + e.tint + '" aria-hidden="true"></span>';
      html += '<li class="co-ev"><span class="co-ev-node">' + node + '</span><div class="co-ev-body"><p class="co-ev-text">' + e.text + "</p>"
        + (e.sub ? '<p class="co-ev-sub">' + esc(e.sub) + "</p>" : "")
        + '<p class="co-ev-meta"><span class="pill ' + e.tint + '">' + esc(e.kind) + '</span><span class="co-ev-date">' + esc(fmtDate(e.when)) + "</span></p></div></li>";
    });
    return html + "</ol>";
  }
  const coPerson = (p, sub, side, note) => '<li class="co-person">' + avatar(p, "md") + '<div class="co-person-text"><p class="co-person-name">'
    + (p.email ? '<a class="pf-name-link" href="#/people/' + esc(C.personKey(p.email)) + '">' + esc(p.name) + "</a>" : esc(p.name)) + '</p><p class="co-person-sub">' + sub + "</p>"
    + (note ? '<p class="co-person-note">' + note + "</p>" : "") + '</div><div class="co-person-side">' + side + "</div></li>";
  const coProp = (k, v) => "<dt>" + k + "</dt><dd>" + v + "</dd>";

  function renderCompany(name) {
    const c = D.companies[name], inv = callForCompany(name), status = coStatus(name), [tag, detail, since] = coStatusParts(status);
    const { staff, alumni } = coPeople(name), bs = coBackstage(name), run = inv ? runs[inv.id] : null;
    const meta = [c && c.engineers ? coNum(c.engineers) + " engineers" : c && c.employees ? coNum(c.employees) + " employees" : "", detail, since ? tag + " since " + since : "", bs.ver ? "Backstage " + bs.ver : bs.ad ? "Backstage adopter" : "", c ? "" : DEMO ? "Not in Spotify's records" : "Not in Overture's records yet"].filter(Boolean);
    const actions = (inv ? (run && run.ctx && run.ctx.done ? '<a class="btn primary" href="#/calls/' + inv.id + '">Open brief</a>'
      : '<button type="button" class="btn primary" data-run="' + inv.id + '"' + (runningId ? " disabled" : "") + ">Run the agent</button>") : "")
      + '<a class="btn secondary" href="#/map">People map</a>';
    let main = "";
    if (inv) {
      const w = splitWhen(inv.when);
      main += '<section class="co-sec" aria-labelledby="coNextH"><div class="sec-head"><h2 id="coNextH">Next call</h2>' + srcTag(SRC.calendar) + "</div>"
        + '<div class="co-focus"><span class="co-focus-ic" aria-hidden="true">' + ic("phone", "co-phone ic-phone") + "</span>"
        + '<div class="co-focus-main"><a class="stretch co-focus-title" href="#/calls/' + inv.id + '">' + esc(inv.title) + "</a>"
        + '<p class="co-focus-meta">' + esc(w.day + " " + w.month + " " + w.date + " · " + w.time + " · " + relDay(daysUntil(inv))) + "</p>"
        + '<p class="co-focus-who">' + coFaces(inv.attendees, "xs") + "<span>" + esc(names(inv)) + "</span></p></div>"
        + '<div class="co-focus-side">' + prepChip(inv.id) + "</div></div></section>";
    }
    // What Overture's research found about the company (profile.js): its real name, summary, key facts, news and sources.
    const about = window.CP.orgBlock(name, Object.assign({ idp: "co", level: 2 }, profileLinks));
    if (about) main += '<section class="co-sec pf-org-sec" aria-label="' + esc("About " + name) + '">' + about + "</section>";
    const gong = C.gongFor(name);
    if (gong) main += '<section class="co-sec" aria-labelledby="coGongH"><div class="sec-head"><h2 id="coGongH">Last call in Gong</h2>' + srcTag("Gong") + "</div>" + C.gongHtml(gong) + "</section>";
    if (staff.length || alumni.length) {
      main += '<section class="co-sec" aria-labelledby="coPeopleH"><div class="sec-head"><h2 id="coPeopleH">People</h2>' + srcTag(SRC.records) + "</div>";
      if (staff.length) {
        main += '<ul class="co-people" role="list">' + staff.map((p) => {
          const ad = p.previous ? C.findAdopter(p.previous) : null;
          const note = [p.note ? esc(p.note) : "", p.previous ? "Came from " + coCompanyLink(p.previous) + (ad ? ", which uses Backstage." : ".") : ""].filter(Boolean).join(" ");
          return coPerson(p, esc(p.title || "Title unknown"), '<span class="co-person-tenure">' + esc(C.tenure(p.startedAt)) + "</span>" + (p.known === false ? '<span class="pill tag-blue">New contact</span>' : ""), note);
        }).join("") + "</ul>";
      }
      if (alumni.length) {
        main += '<h3 class="co-subhead">Used to work here</h3><ul class="co-people" role="list">' + alumni.map((p) => coPerson(p, "Now " + esc(p.title) + " at " + coCompanyLink(p.now),
          p.startedAt ? '<span class="co-person-tenure">Moved ' + esc(fmtDate(p.startedAt)) + "</span>" : "", [p.previousRole ? "Was " + esc(p.previousRole) + " here." : "", p.note ? esc(p.note) : ""].filter(Boolean).join(" "))).join("") + "</ul>";
      }
      main += "</section>";
    }
    main += '<section class="co-sec" aria-labelledby="coTimeH"><div class="sec-head"><h2 id="coTimeH">Timeline</h2>' + srcTag(SRC.records) + "</div>" + coTimeline(coEvents(name, staff, alumni, bs)) + "</section>";

    const pp = D.papers[name];
    const editBtn = LIVE_MODE ? '<button type="button" class="ghost-edit" data-edit-company="' + esc(name) + '">' + ic("pencil") + "Edit</button>" : "";
    let side = editingCompany === name ? companyForm(name) : '<section class="co-panel-sec" aria-labelledby="coDetH"><div class="co-panel-head"><h2 id="coDetH">Details</h2>' + srcTag(SRC.records) + editBtn + '</div><dl class="co-props">'
      + coProp("Status", '<span class="pill ' + tagFor("status", status) + '">' + esc(tag) + "</span>" + (since ? '<span class="co-sub">since ' + esc(since) + "</span>" : "") + (fromHubspot(c, "status") ? srcTag("HubSpot") : ""))
      + (detail ? coProp(/^Customer/.test(status) ? "Uses" : fromHubspot(c, "status") ? "Stage" : "Deal for", esc(detail)) : "")
      + (c && !c.engineers && c.employees ? coProp("Employees", '<span class="co-num">' + coNum(c.employees) + "</span>" + srcTag("HubSpot")) : "")
      + (c && !c.engineers && c.employees ? "" : coProp("Engineers", c && c.engineers ? '<span class="co-num">' + coNum(c.engineers) + "</span>" + (c.comeBack ? '<span class="co-sub">was ' + c.comeBack.then + " in January</span>" : "") : '<span class="co-none">Unknown</span>'))
      + (c && c.comeBack ? coProp("Open eng. jobs", '<span class="co-num">' + c.comeBack.openJobs + "</span>") : "")
      + coProp("People", staff.length ? coFaces(staff, "xs") + "<span>" + plural(staff.length, "person", "people") + "</span>" : alumni.length ? coFaces(alumni, "xs") + "<span>" + plural(alumni.length, "ex-employee") + "</span>" : '<span class="co-none">None yet</span>')
      + coProp("Next call", inv ? '<a href="#/calls/' + inv.id + '">' + esc(coCallDay(inv) + ", " + splitWhen(inv.when).start) + "</a>" : '<span class="co-none">None booked</span>')
      + "</dl>" + (c && c.notes ? '<p class="co-panel-note co-notes">' + esc(c.notes) + "</p>" : "") + "</section>";
    if (c && c.deals && c.deals.length) side += '<section class="co-panel-sec" aria-labelledby="coDealH"><div class="co-panel-head"><h2 id="coDealH">Deals</h2>' + srcTag("HubSpot") + "</div>" + dealsHtml(c.deals) + "</section>";
    if (pp) {
      const nda = pp.nda && pp.nda.signed ? '<span class="pill tag-green">Signed</span><span class="co-sub">' + esc(fmtDate(pp.nda.date) + ", " + pp.nda.where) + "</span>" : '<span class="pill tag-orange">Not signed</span>';
      const sp = pp.securityPack, cur = D.currentSecurityPack;
      const pack = !sp ? '<span class="pill tag-orange">None sent</span>'
        : sp.sent === cur ? '<span class="pill tag-green">' + esc(cur) + ' current</span><span class="co-sub">sent ' + esc(fmtDate(sp.sentOn)) + "</span>"
        : '<span class="pill tag-orange">' + esc(sp.sent) + ' is old</span><span class="co-sub">current is ' + esc(cur) + "</span>";
      side += '<section class="co-panel-sec" aria-labelledby="coPapH"><div class="co-panel-head"><h2 id="coPapH">Papers</h2>' + srcTag(SRC.records) + '</div><dl class="co-props">' + coProp("NDA", nda) + coProp("Security pack", pack) + "</dl></section>";
    }
    side += '<section class="co-panel-sec" aria-labelledby="coBsH"><div class="co-panel-head"><h2 id="coBsH">Backstage</h2>' + srcTag("Public data") + '</div><dl class="co-props">'
      + coProp("Adopters list", bs.ad ? '<span class="pill tag-green">Listed</span>' : '<span class="co-none">Not listed</span>')
      + coProp("Version", bs.ver ? '<span class="pill tag-gray co-ver">' + esc(bs.ver) + '</span><span class="co-sub">from their backstage.json</span>' : '<span class="co-none">Unknown</span>')
      + (bs.behind != null ? coProp("Behind", '<span class="co-num">' + plural(bs.behind, "release") + '</span><span class="co-sub">latest ' + esc(C.state.latest.version) + "</span>") : "")
      + (bs.since ? coProp("Running since", '<span class="co-num">' + esc(bs.since) + "</span>") : "")
      + '</dl><p class="co-panel-note">' + (bs.ad ? "On the public adopters list: “" + esc(bs.ad.use) + "”" : "Not on the public adopters list (" + C.state.adopters.length + " companies). Many users never add themselves.") + "</p></section>";

    $('[data-view="company"]').innerHTML = '<div class="topbar"><div class="topbar-inner"><nav class="co-crumbs" aria-label="Breadcrumb"><a href="#/companies">Companies</a><span class="co-crumb-sep" aria-hidden="true">/</span><span class="co-crumb-here" aria-current="page">' + esc(name) + "</span></nav></div></div>"
      + '<div class="co-record"><header class="co-rhead">' + coTile(name, "co-head-tile") + '<div class="co-rhead-text"><div class="co-rtitle"><h1 tabindex="-1">' + esc(name) + "</h1>" + (c ? '<span class="pill ' + tagFor("status", status) + '">' + esc(tag) + "</span>" : "") + "</div>"
      + (meta.length ? '<p class="co-rmeta">' + meta.map((m) => "<span>" + esc(m) + "</span>").join("") + "</p>" : "") + '</div><div class="co-ractions">' + actions + "</div></header>"
      + '<div class="co-rbody"><div class="co-rmain">' + main + '</div><aside class="co-panel" aria-label="' + esc(name) + ' details">' + side + "</aside></div></div>";
  }

  // ---------- a person's page (#/people/<key>): profile.js draws it, this wires its connection map ----------
  const profileLinks = { companyHref: (name) => (companyBySlug(slug(name)) ? "#/companies/" + slug(name) : "") };
  function renderPerson(email) {
    const CP = window.CP, g = CP.graph(email);
    const conn = g.nodes.length > 1 ? '<section class="pf-sec" aria-labelledby="pf-conn"><h2 class="pf-h" id="pf-conn">Connections</h2>' + CP.mapHtml(g) + "</section>" : "";
    $('[data-view="people"]').innerHTML = CP.pageHtml(email, Object.assign({ canAgain: LIVE_MODE, connections: conn }, profileLinks));
    if (personMap) personMap.destroy();
    personMap = conn ? CP.mountMap($('[data-view="people"] [data-pm-root]'), g, Object.assign({ page: true }, profileLinks)) : null;
    return CP.who(email).name;
  }

  // ---------- people map ----------
  function insights() {
    const g = C.relationshipGraph(), byId = Object.fromEntries(g.nodes.map((n) => [n.id, n]));
    const out = [];
    g.edges.filter((e) => e.kind === "together").forEach((e) => out.push(e.why));
    g.edges.filter((e) => e.a === "you" && e.kind === "warm" && byId[e.b].type === "person").forEach((e) => out.push(e.why));
    g.edges.filter((e) => e.src === "pub").forEach((e) => out.push(e.why + " (public adopters list)"));
    return out;
  }
  function mapSide(d) {
    if (!d) {
      return '<h2 tabindex="-1" id="mapSideH">How to read it</h2><div class="map-hint"><p>Click a person or company to see every link. Double-click a person to see their past to present. Click a label on a line to see why it exists. Drag cards to move them; scroll or use the zoom bar to move around.</p></div>'
        + '<h3 class="sub-label">What the agent noticed</h3>' + insights().map((t) => '<p class="map-insight">' + esc(t) + "</p>").join("");
    }
    const n = d.node;
    const kindWord = { warm: "Warm link", moved: "Past job or talk", together: "Worked together", works: "Works there", mentioned: "Mentioned on a call" };
    // What Overture found about this guest or company (profile.js), above the list of links.
    const guest = n.type === "person" && n.id.startsWith("p:") ? n.id.slice(2) : "";
    const found = guest ? window.CP.briefPerson(guest, profileLinks) || C.researchHtml(Object.assign({ name: n.label, email: guest }, D.people[guest] || {}))
      : n.type === "prospect" || n.type === "past" ? window.CP.orgMini(n.label, profileLinks) : "";
    return '<h2 tabindex="-1" id="mapSideH">' + esc(n.label) + '</h2><p class="meta">' + esc([n.sub, n.status].filter(Boolean).join(" · ")) + "</p>"
      + found
      + '<ul class="rel" role="list">' + d.rels.map((r) => '<li><div class="rel-top"><span class="rel-kind ' + esc(r.kind) + '" aria-hidden="true"></span><strong>' + esc(r.other) + '</strong><span class="src ' + (r.src === "pub" ? "public" : DEMO ? "sample" : "yours") + '"><span class="sr-only">' + (r.src === "pub" ? "Public data" : SRC.records) + "</span></span></div>"
        + "<p>" + esc((kindWord[r.kind] || "") + (r.label && r.kind !== "works" ? " · " + r.label : "") + (r.why ? ". " + r.why : "")) + "</p>"
        + (r.kind === "mentioned" && r.explain ? C.explainFold(r.explain, { open: true }) : "")
        + (r.kind === "mentioned" && r.mentionId ? '<p><button type="button" class="link-btn" data-conn-remove="' + esc(r.connId) + '">Remove this connection</button></p>' : "") + "</li>").join("") + "</ul>"
      + '<div class="side-actions">' + (guest ? '<a class="btn secondary sm" href="#/people/' + esc(C.personKey(guest)) + '">' + ic("arrowRight") + "Open profile</a>"
        + '<button type="button" class="btn ghost sm" data-open-tl="' + esc(C.personKey(guest)) + '">' + ic("clock") + "Past to present</button>" : "")
      + (d.callId ? '<a class="btn ' + (guest ? "ghost" : "secondary") + ' sm" href="#/calls/' + d.callId + '">' + (guest ? "" : ic("arrowRight")) + "Open the call</a>" : "")
      + ((n.type === "prospect" || n.type === "past") && companyBySlug(slug(n.label)) ? '<a class="btn ghost sm" href="#/companies/' + slug(n.label) + '">Open company</a>' : "")
      + (n.type === "person" ? '<a class="btn ghost sm" href="#/companies/' + slug(inviteById(n.callId).company) + '">Their company</a>' : "") + "</div>";
  }
  function renderMap() {
    const sec = $('[data-view="map"]');
    const views = [["all", "All calls"]].concat(D.invites.map((i) => [i.id, i.company]));
    sec.innerHTML = '<div class="map-top"><span class="page-icon tag-teal" aria-hidden="true">' + ic("network") + '</span><h1 class="page-title" tabindex="-1">People map</h1>' + srcTag(SRC.records)
      + '<span class="grow"></span><div class="seg" role="group" aria-label="Show">' + views.map(([id, l]) => '<button type="button" data-mapview="' + esc(id) + '" aria-pressed="' + (app.mapView === id) + '">' + esc(l) + "</button>").join("") + "</div></div>"
      + '<div class="map-body"><div id="board" class="board" aria-label="Relationship map"></div><aside class="map-side" id="mapSide" aria-live="polite"></aside></div>';
    if (!D.invites.length) {
      $("#board").innerHTML = '<div class="map-empty"><h2>No one to map yet</h2><p>' + (LIVE_MODE ? "The map fills in from the guests on your next 14 days of calls." : 'Connect your Google Calendar and the map fills in from the guests on your calls. <a href="#/home">Connect</a>') + "</p></div>";
      $("#mapSide").innerHTML = '<h2 tabindex="-1" id="mapSideH">How to read it</h2><div class="map-hint"><p>Each call\'s company, its people, and where they worked before, with the links between them.</p></div>';
      return;
    }
    $("#mapSide").innerHTML = mapSide(null);
    mountMap();
    if (LIVE_MODE) refreshMapConnections();
  }
  // Every call's saved connections, fetched again when the map opens (the in-call panel may have added some since this page loaded).
  async function refreshMapConnections() {
    const changed = await Promise.all(D.invites.map((i) => C.fetchTimeout("/api/mentions?callId=" + encodeURIComponent(i.id), 8000)
      .then((r) => (r.ok ? r.json() : null)).then((j) => !!(j && C.mergeConnections(i.id, j.graph))).catch(() => false)));
    if (changed.some(Boolean) && app.view === "map" && mapInstance) mountMap();
  }
  function mountMap() {
    if (mapInstance) { mapInstance.destroy(); mapInstance = null; }
    const opts = app.mapView === "all" ? { mode: "board" } : { mode: "stack", callId: app.mapView };
    opts.onSelect = (d) => { $("#mapSide").innerHTML = mapSide(d); };
    opts.onRemove = removeConnection;
    opts.onOpen = openTimeline; // double-click a person: their past to present
    mapInstance = window.CMap.mount($("#board"), opts);
  }
  // One guest's past to present (profile.js), in a dialog over the page. Opened by double-clicking them on the People map, or
  // by any [data-open-tl] button (the map's side card, the person page).
  function openTimeline(email) {
    const dlg = $("#tlDialog");
    if (!dlg || !email || !D.people[email]) return;
    dlg.onpointerdown = (e) => { dlg.dataset.downOut = e.target === dlg ? "1" : "0"; }; // where a click started, for the backdrop check
    dlg.innerHTML = window.CP.timelineHtml(email, profileLinks);
    window.CP.mountTimeline(dlg, email, profileLinks);
    if (!dlg.open) dlg.showModal();
    window.CP.showLatest(dlg);
    $("#tlTitle").focus();
  }
  // A wrong connection on the map: take it off (live: saved in Overture's records, and never added again; demo: this page only).
  async function removeConnection(edge) {
    if (!edge || !edge.mentionId) return;
    if (DEMO) {
      D.relationships = D.relationships.filter((r) => r.connId !== edge.connId);
      D.mentioned = D.mentioned.filter((m) => D.relationships.some((r) => r.b === m.id || r.a === m.id));
      const st = mnCalls[edge.callId];
      const x = st && (st.items || []).concat(st.orgs || []).find((y) => y.id === edge.mentionId);
      if (x) Object.assign(x, { removed: true, connected: false });
    } else {
      try {
        const j = await C.postJson("/api/mentions/pick", { callId: edge.callId, id: edge.mentionId, action: "remove" }, 15000);
        C.mergeConnections(edge.callId, j.graph);
        const st = mnCalls[edge.callId];
        if (st) { st.items = j.items || st.items; st.orgs = j.orgs || st.orgs; }
      } catch (e) { toast(e.message); return; }
    }
    if (app.view === "map") { $("#mapSide").innerHTML = mapSide(null); mountMap(); }
    announce(DEMO ? "Sample data: removed on this page only." : "Removed from the People map.");
  }

  // ---------- in-call panel page ----------
  // A believable Google Meet or Zoom call with the real panel (panel.html) open in its side panel. Mobbin refs: top of live.css.
  // Call-control glyphs (Lucide, ISC) that core.js doesn't carry; the mock controls are decorative and only move while hovered.
  const LV_PATHS = {
    mic: '<rect x="9" y="2" width="6" height="13" rx="3"/><path d="M19 10v2a7 7 0 0 1-14 0v-2M12 19v3"/>',
    present: '<rect width="20" height="14" x="2" y="3" rx="2"/><path d="m9 10 3-3 3 3M12 13V7M12 17v4M8 21h8"/>',
    more: '<circle cx="12" cy="5" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="12" cy="19" r="1"/>',
    leave: '<path d="M13.832 16.568a1 1 0 0 0 1.213-.303l.355-.465A2 2 0 0 1 17 15h3a2 2 0 0 1 2 2v3a2 2 0 0 1-2 2A18 18 0 0 1 2 4a2 2 0 0 1 2-2h3a2 2 0 0 1 2 2v3a2 2 0 0 1-.8 1.6l-.468.351a1 1 0 0 0-.292 1.233 14 14 0 0 0 6.392 6.384"/>',
    apps: '<path d="M8.3 10a.7.7 0 0 1-.626-1.079L11.4 3a.7.7 0 0 1 1.198-.043L16.3 8.9a.7.7 0 0 1-.572 1.1Z"/><rect x="3" y="14" width="7" height="7" rx="1"/><circle cx="17.5" cy="17.5" r="3.5"/>',
  };
  const lvIc = (name) => '<svg class="ic ic-' + name + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + (LV_PATHS[name] || C.ICONS[name]) + "</svg>";
  // One call tile: the photo fills it like a camera feed (asked at 720px so it stays sharp); Chris has his camera off.
  const lvTile = (who, label, cls) => '<div class="lv-tile' + (cls ? " " + cls : "") + '">'
    + (cls === "is-self" ? avatar(ME.name) : avatar(who).replace(/w=\d+(&amp;|&)h=\d+/, "w=720$1h=720"))
    + '<span class="lv-voice"><i></i><i></i><i></i></span><span class="lv-name">' + esc(label) + "</span></div>";
  const lvClock = (when) => { const m = splitWhen(when).start.match(/(\d+):(\d+)/); if (!m) return ""; const h = +m[1]; return ((h % 12) || 12) + ":" + m[2] + (h < 12 ? " AM" : " PM"); };
  function renderLive() {
    const inv = inviteById(app.liveCall), skin = app.liveSkin, zoom = skin === "zoom", hostName = zoom ? "Zoom" : "Google Meet";
    if (!inv) {
      $('[data-view="live"]').innerHTML = pageHead("video", "tag-green", "In-call panel", "", "During a call, Overture sits in the side panel of Google Meet or Zoom: the opener, talking points, who is who, and private notes.")
        + '<div class="empty-calls widget"><h2>No call to show yet</h2><p>' + (LIVE_MODE ? "When a call with an outside guest is on your calendar in the next 14 days, its panel shows here." : 'Connect your Google Calendar to see the panel for your next call. <a href="#/home">Connect</a>') + "</p></div>";
      return;
    }
    const src = "panel.html?host=panel&skin=" + skin + "&call=" + inv.id + (C.LIVE ? "" : "&live=0") + (DEMO ? "&demo=1" : "");
    const n = inv.attendees.length + 1;
    const tiles = inv.attendees.map((a, i) => lvTile(a, a.name, i === 0 ? "is-speaking" : "")).join("") + lvTile(ME.name, zoom ? (ME.first || "Me") + " (me)" : "You", "is-self");
    const btn = (icon, label, cls) => '<span class="lv-btn' + (cls ? " " + cls : "") + '">' + lvIc(icon) + (cls && cls.includes("has-count") ? '<span class="lv-count num">' + n + "</span>" : "") + (zoom ? '<span class="lv-lbl">' + label + "</span>" : "") + "</span>";
    const dock = zoom
      ? '<div class="lv-group">' + btn("mic", "Mute") + btn("video", "Stop video") + "</div>"
        + '<div class="lv-group">' + btn("users", "Participants", "has-count") + btn("present", "Share") + btn("apps", "Apps", "is-on") + btn("more", "More") + "</div>"
        + '<div class="lv-group end"><span class="lv-end">End</span></div>'
      : '<div class="lv-meta"><span class="num">' + esc(lvClock(inv.when)) + '</span><span class="lv-sep"></span><span class="lv-code">' + esc(inv.meetingCode || "") + "</span></div>"
        + '<div class="lv-group">' + btn("mic") + btn("video") + btn("present") + btn("more") + '<span class="lv-btn lv-leave">' + lvIc("leave") + "</span></div>"
        + '<div class="lv-group end">' + btn("users", "", "has-count") + btn("apps", "", "is-on") + "</div>";
    const who = inv.attendees.map((a) => a.name).join(", ");
    $('[data-view="live"]').innerHTML = pageHead("video", "tag-green", "In-call panel", SRC.calendar, 'During the call, Overture sits in the side panel of Google Meet or Zoom: the opener, talking points, who is who, and private notes that flow into "After the call". Only you can see it.')
      + '<div class="lv-bar"><div class="seg" role="group" aria-label="Call app">' + [["meet", "Google Meet"], ["zoom", "Zoom"]].map(([k, l]) => '<button type="button" data-skin="' + k + '" aria-pressed="' + (skin === k) + '">' + l + "</button>").join("") + "</div>"
      + '<label class="sr-only" for="liveCall">Call</label><select id="liveCall" class="input sm">' + D.invites.map((i) => '<option value="' + i.id + '"' + (i.id === inv.id ? " selected" : "") + ">" + esc(i.company) + "</option>").join("") + "</select>"
      + '<span class="grow"></span><a class="lv-solo" href="' + src.replace("host=panel", "host=preview") + '" target="_blank" rel="noopener">Open the panel on its own' + NEW_TAB + "</a></div>"
      + '<section class="lv-call" data-app="' + skin + '" aria-label="' + esc("Mock " + hostName + " call with " + inv.company + ": " + who + " and you, with Overture open in the side panel") + '">'
      + (zoom ? '<div class="lv-top" aria-hidden="true"><span class="lv-topic">' + esc(inv.title) + '</span><span class="lv-view">Gallery view</span></div>' : "")
      + '<div class="lv-main"><div class="lv-grid" data-n="' + n + '" aria-hidden="true">' + tiles + "</div>"
      + '<div class="lv-side"><div class="lv-side-head" aria-hidden="true"><img src="logo.svg" alt="" width="22" height="22"><span class="lv-side-title">Overture</span>' + lvIc("x") + "</div>"
      + '<iframe title="Overture in-call panel" src="' + esc(src) + '"></iframe></div></div>'
      + '<div class="lv-dock" aria-hidden="true">' + dock + "</div></section>"
      + '<p class="lv-note">A mock ' + hostName + (DEMO ? " screen with stock photos for the made-up people." : " screen: your guests show as initials.") + ' The side panel is the real one (panel.html): in a real call it runs as a Google Meet add-on or a Zoom App, reads the meeting code or topic to pick the call, and falls back to a call picker.</p>'
      + '<section class="lv-setup" aria-labelledby="lvSetup"><h2 id="lvSetup">Put it in a real call</h2><p class="lv-setup-sub">Installing it needs your own Google Cloud and Zoom developer accounts.</p><div class="lv-setup-grid">'
      + '<div class="lv-steps"><h3>Google Meet add-on</h3><ol>'
      + "<li>Host Overture on HTTPS (GitHub Pages works for Meet).</li><li>In a Google Cloud project, turn on the <b>Google Workspace Marketplace SDK</b> and add an HTTP deployment with <code>sidePanelUrl</code> set to <code>…/panel.html</code>.</li>"
      + "<li>Put the project number in <code>panel.html</code> (<code>meetCloudProjectNumber</code>).</li><li>Install the test deployment, start a call, open <b>Activities</b>, pick Overture.</li></ol></div>"
      + '<div class="lv-steps"><h3>Zoom App</h3><ol><li>Host on HTTPS with the four security headers Zoom requires (see <code>_headers</code>). GitHub Pages does not send them.</li>'
      + "<li>Create a <b>General app</b> in the Zoom App Marketplace. Set the Home URL to <code>…/panel.html?host=zoom</code> and add the host and <code>appssdk.zoom.us</code> to the domain allow list.</li>"
      + "<li>Add the in-meeting APIs (meeting context, participants) and the <code>zoomapp:inmeeting</code> scope.</li><li>Use Local Test → Add App Now, then open it from <b>Apps</b> in a meeting.</li></ol></div></div>"
      + '<p class="list-foot">Full steps: <a href="#/guides/extension">Put Overture beside Google Meet and Zoom</a> · <a href="#/guides/in-call">Install as a Meet add-on or Zoom App (developers)</a> ·<a href="#/guides">All setup guides</a></p></section>';
  }

  // ---------- data page ----------
  function renderData() {
    const recent = SNAP.advisories.length;
    const sev = SNAP.advisories.reduce((s, a) => { s[a.severity] = (s[a.severity] || 0) + 1; return s; }, {});
    const live = C.state.liveData, st = C.state, g = st.google || {};
    const row = (icon, name, detail, state, on, action) => '<div class="row"><span class="src-tile">' + ic(icon) + '</span><span class="src-text"><span class="row-title">' + name + '</span><span class="row-sub">' + detail + "</span></span>"
      + (action ? '<span class="src-act">' + action + "</span>" : "") + '<span class="state-word status-pill ' + (on ? "on tag-green" : "tag-gray") + '">' + esc(state) + "</span></div>";
    const saved = "Saved " + fmtDate(SNAP.takenOn);
    // Connections: where Overture's real data comes from, and who answers questions.
    let cal;
    if (!st.server) cal = row("calendar", "Google Calendar", "Overture's server isn't answering, or an older copy is running. Restart <code>server.py</code>, then reload.", "Offline", false);
    else if (!g.configured) cal = row("calendar", "Google Calendar", 'Sign-in isn\'t set up on this PC yet. <a href="#/guides/google">Set it up</a>' + ", then restart <code>server.py</code>.", "Not set up", false);
    else if (g.connected) cal = row("calendar", "Google Calendar", "Connected as " + esc(g.email || "your Google account") + " · read-only, the next 14 days"
      + (window.MOAB_LIVE_ERROR ? ". Last try failed: " + esc(window.MOAB_LIVE_ERROR) : ""), "Connected", !window.MOAB_LIVE_ERROR, '<button type="button" class="btn ghost sm" data-disconnect>Disconnect</button>');
    else cal = row("calendar", "Google Calendar", "Not connected. Overture only asks to read your calendar.", "Not connected", false, '<a class="btn secondary sm" href="/auth/google">Connect</a>');
    const syncTime = (iso) => (iso ? new Date(iso).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "");
    const crmRow = (key, icon, label, what, doc) => {
      const x = st[key] || {}, how = '<a href="' + doc + '">How to connect</a>';
      if (!st.server) return row(icon, label, "Overture's server isn't answering. Restart <code>server.py</code>, then reload.", "Offline", false);
      if (!x.configured) return row(icon, label, "Not connected. " + what + " " + how + ".", "Not set up", false);
      const who = key === "hubspot" ? (x.portal ? "Connected to " + esc(x.portal) : "Connected") : (x.workspace ? "Connected to " + esc(x.workspace) : "Connected");
      return row(icon, label, (x.connected ? who : "Set up, not checked yet") + (x.lastSync ? " · last sync " + esc(syncTime(x.lastSync)) : "")
        + (x.lastError ? '. <span class="err-text">Last error: ' + esc(x.lastError) + "</span>" : "") + ". " + what + " " + how + ".",
        x.lastError ? "Error" : x.connected ? "Connected" : "Set up", x.connected && !x.lastError);
    };
    const hubspotRow = crmRow("hubspot", "building", "HubSpot", "Reads companies, deals, contacts and notes. Writes only when you press Save to HubSpot after a call.", "#/guides/hubspot");
    const gongRow = crmRow("gong", "phone", "Gong", "Reads the last call's summary, key points, topics and trackers. Reads a call's transcript only when you turn that on in Settings.", "#/guides/gong");
    // The privacy switches (Gong transcripts, transcripts and Gong notes in AI answers) live in Settings > Research sources & privacy now.
    const rp = C.prefs() ? C.prefs().research : {}, onOff = (v) => (v ? "on" : "off");
    const privacyRow = '<div class="row"><span class="src-tile">' + ic("shield") + '</span><span class="src-text"><span class="row-title">Research sources and privacy</span>'
      + '<span class="row-sub">Read Gong transcripts: ' + onOff(rp.gongTranscripts) + " · Transcripts in AI answers: " + onOff(rp.transcriptsInAI) + " · Gong notes in AI answers: " + onOff(rp.gongInAI)
      + '</span></span><span class="src-act"><a class="btn secondary sm" href="#/settings/research">Change in Settings</a></span></div>';
    const dev = st.device === "available" ? [true, "Chrome's built-in AI is ready."]
      : /download/.test(st.device) ? [false, "Chrome can run a small AI model on this PC once it has downloaded it."]
      : [false, "needs Chrome with built-in AI (the Prompt API)."];
    const aiNow = st.claudeOn ? "Claude answers questions and writes brief summaries." : dev[0] ? "On-device AI answers questions in the search box." : "Built-in rules answer from Overture's records.";
    const recCount = Object.keys(D.companies).length, ppl = Object.values(D.people).filter((p) => p.known).length;
    $('[data-view="data"]').innerHTML = pageHead("database", "tag-gray", "Data", "", DEMO ? "What's real, what's made up, and who writes the brief." : "Where Overture's data comes from, and who answers.")
      + (DEMO ? '<p class="data-note">This is the demo with made-up calls. It runs as if today is ' + esc(today().toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric", year: "numeric" })) + ', so the calls stay upcoming. <a href="' + esc(location.pathname) + '#/home">Leave the demo</a></p>' : "")
      + '<section class="sec">' + secHead("Connections", "") + '<div class="list src-list">' + cal + (DEMO ? "" : hubspotRow + gongRow + privacyRow)
      + row("sparkle", "AI", esc(aiNow) + " Claude: " + (st.claudeOn ? "key found on the server." : "no key (set ANTHROPIC_API_KEY before starting server.py).") + " On-device: " + esc(dev[1]),
        st.claudeOn ? "Claude" : dev[0] ? "On device" : "Rules only", st.claudeOn || dev[0])
      + row("database", "Overture records", "Stored on this PC in <code>centralize/.data/records.json</code>"
        + (DEMO ? "" : " · " + plural(recCount, "company", "companies") + ", " + plural(ppl, "person", "people") + " with notes"), st.server ? "On this PC" : "Offline", st.server)
      + "</div></section>"
      + '<div class="stats three data-stats">' + stat("Adopters list", C.state.adopters.length, "companies") + stat("Security notices", recent, esc((sev.critical || 0) + " critical, " + (sev.high || 0) + " high")) + stat("Latest Backstage", C.state.latest.version, esc(fmtDate(C.state.latest.date))) + "</div>"
      + '<section class="sec">' + secHead("Public data", "Public data") + '<div class="list src-list">'
      + row("list", "Backstage adopters list", esc(C.state.adopters.length + " companies · ADOPTERS.md on GitHub"), live ? "Live from GitHub" : saved, live)
      + row("tag", "Backstage releases", esc("Latest " + C.state.latest.version + " · package lists from versions.backstage.io"), live ? "Live from GitHub" : saved, live)
      + row("shield", "Security notices", esc(recent + " notices · GitHub security advisories"), saved, false)
      + row("receipt", "Rival prices", 'From <a href="https://www.port.io/pricing" target="_blank" rel="noopener">port.io/pricing' + NEW_TAB + '</a> and <a href="https://roadie.io/pricing/" target="_blank" rel="noopener">roadie.io/pricing' + NEW_TAB + "</a>", "Public pages", false)
      + "</div></section>"
      + (DEMO ? '<section class="sec">' + secHead("Sample data", "Sample data") + '<div class="list src-list">'
        + row("calendar", plural(D.invites.length, "call"), "Stands in for the calendar", "Made up")
        + row("users", plural(Object.keys(D.people).length, "person", "people"), "Stands in for HubSpot and LinkedIn Sales Navigator", "Made up")
        + row("building", plural(Object.keys(D.companies).length, "company", "companies"), "Stands in for HubSpot", "Made up")
        + row("receipt", "Papers", "Stands in for Google Drive and DocuSign", "Made up")
        + row("bell", plural(D.watch.length, "alert"), "Stands in for a job-change and hiring feed", "Made up")
        + row("note", "Call notes", "Stands in for call recordings (Gong)", "Made up")
        + "</div></section>"
        : '<section class="sec">' + secHead("Your data", "Overture records") + '<div class="list src-list">'
        + row("calendar", plural(D.invites.length, "call"), "From your Google Calendar: the next 14 days, events with at least one guest from outside your company", LIVE_MODE ? "Your calendar" : "Not connected", LIVE_MODE)
        + row("users", plural(Object.keys(D.people).length, "person", "people"), "Guests on those calls. Add titles and notes from any brief.", "Overture records", LIVE_MODE)
        + row("building", plural(recCount, "company", "companies"), "Status and notes you set on a company page, plus accepted after-call updates", "Overture records", LIVE_MODE)
        + row("bell", plural(D.watch.length, "alert"), "Job changes and first meetings, worked out from your past meetings", LIVE_MODE ? "Your calendar" : "Not connected", LIVE_MODE)
        + "</div></section>")
      + '<section class="sec">' + secHead("Who writes the brief", "") + '<div class="list src-list">'
      + row("listChecks", "Built-in rules", "Write every brief.", "In use", true)
      + row("sparkle", "Claude (Anthropic)", "Adds a short summary to each brief." + (C.state.claudeOn ? "" : " Set ANTHROPIC_API_KEY before starting server.py to turn it on."), C.state.claudeOn ? "On" : "Off", C.state.claudeOn)
      + "</div></section>"
      + '<section class="sec">' + secHead("How the estimates work", "Agent's guess") + '<dl class="kv small"><dt>Days to catch up</dt><dd>' + esc(C.ASSUME.daysPerRelease + " × releases behind + " + C.ASSUME.daysPerSerious + " × each serious notice") + "</dd>"
      + "<dt>Hours a week</dt><dd>Chris's numbers: about " + C.CHRIS.startHours + " hour a week at first, " + C.CHRIS.lowAt5 + " to " + C.CHRIS.highAt5 + " after five years.</dd></dl>"
      + '<p class="data-note">Change the day values from any brief: Days to catch up › How?</p></section>';
  }

  // ---------- check any company ----------
  let checkSeq = 0;
  async function checkAny() {
    const seq = ++checkSeq;
    const name = $("#anyName").value.trim(), ver = C.cleanVer($("#anyVersion").value), out = $("#anyResult");
    if (!name && !ver) { out.innerHTML = '<p class="muted-line">Type a company name, a Backstage version, or both.</p>'; return; }
    out.innerHTML = '<p class="busy">' + ic("loader", "spin") + "Checking…</p>";
    let html = "";
    if (name) {
      const ad = C.findAdopter(name);
      html += "<p>" + (ad ? "<strong>" + esc(ad.org) + "</strong> is on the public adopters list: “" + esc(ad.use) + "”" : "<strong>" + esc(name) + "</strong> is not on the public adopters list (" + C.state.adopters.length + " companies). Many users never add themselves.") + "</p>";
    }
    if (ver) {
      if (!C.parseVer(ver)) html += '<p class="muted-line">That doesn\'t look like a Backstage version. Try something like 1.30.0.</p>';
      else {
        try {
          const b = C.upgradeBill(await C.packagesFor(ver), ver, null);
          html += "<p>Backstage " + esc(ver) + ':</p><div class="stats three">' + stat("Releases behind", b.behind == null ? "?" : b.behind, esc("Latest is " + b.to))
            + stat("Serious notices", b.serious, esc(b.sev.critical + " critical, " + b.sev.high + " high"), { danger: b.sev.critical > 0 }) + stat("Days to catch up", b.days == null ? "?" : b.days, "Estimate") + "</div>";
        } catch (e) { html += '<p class="muted-line">' + esc(e.message) + ".</p>"; }
      }
    }
    if (seq === checkSeq) out.innerHTML = html;
  }
  function openCheck(opts) {
    $("#anyName").value = opts && opts.name != null ? opts.name : "";
    $("#anyVersion").value = opts && opts.version != null ? opts.version : "";
    $("#anyResult").innerHTML = "";
    openDialog("#checkDialog", opts && opts.opener);
    (opts && opts.focus ? $("#" + opts.focus) : $("#anyName")).focus();
    if (opts && (opts.name || opts.version)) checkAny();
  }

  // ---------- drawer ----------
  let drawerOrig = null;
  function openDrawer(focusId) {
    const inp = inputs[app.callId];
    $("#versionFile").value = inp.versionFile;
    $("#since").value = inp.since || "";
    $("#assumeRelease").value = C.ASSUME.daysPerRelease;
    $("#assumeSerious").value = C.ASSUME.daysPerSerious;
    $("#estimateHelp").textContent = "Days to catch up = days per release behind × releases behind, plus extra days for each critical or high notice. Hours a week uses Chris's own numbers: about "
      + C.CHRIS.startHours + " hour a week at the start, " + C.CHRIS.lowAt5 + " to " + C.CHRIS.highAt5 + " after five years.";
    drawerOrig = { versionFile: inp.versionFile, since: inp.since || "" };
    $("#drawerSave").textContent = "Save";
    openDialog("#drawer");
    if (focusId) $("#" + focusId).focus();
  }
  const inputsChanged = () => $("#versionFile").value !== drawerOrig.versionFile || String($("#since").value) !== String(drawerOrig.since);
  function applyDrawer() {
    const num = (sel, cur) => { const v = parseFloat($(sel).value); return Number.isFinite(v) ? Math.max(0, v) : cur; };
    const est = { r: num("#assumeRelease", C.ASSUME.daysPerRelease), s: num("#assumeSerious", C.ASSUME.daysPerSerious) };
    const estChanged = est.r !== C.ASSUME.daysPerRelease || est.s !== C.ASSUME.daysPerSerious;
    C.ASSUME.daysPerRelease = est.r;
    C.ASSUME.daysPerSerious = est.s;
    const id = app.callId, changed = inputsChanged();
    if (changed) { inputs[id] = { versionFile: $("#versionFile").value, since: parseInt($("#since").value, 10) || null }; store.set("inputs:" + id, inputs[id]); }
    // Only the days depend on these settings; keep each brief's own release count so its numbers stay consistent.
    if (estChanged) Object.values(runs).forEach((r) => { const b = r.ctx && r.ctx.bill; if (b) b.days = b.behind == null ? null : Math.round(b.behind * est.r + b.serious * est.s); });
    const run = runs[id];
    if (changed && run && run.ctx && run.ctx.done && !runningId) { openers["#drawer"] = null; $("#drawer").close(); runAgent(id); return; }
    if (!run || !run.ctx) { renderStart(inviteById(id)); openers["#drawer"] = $("#panelBrief h1"); return; }
    const cell = $("#statDays");
    if (estChanged && run.ctx.bill && cell) {
      const days = run.ctx.bill.days == null ? "?" : String(run.ctx.bill.days);
      $(".stat-n", cell).textContent = days;
      const word = $(".est-word", cell);
      word.textContent = "Updated"; word.classList.add("updated");
      setTimeout(() => { word.textContent = "Estimate"; word.classList.remove("updated"); }, 2000);
      if (days !== "?") announce("Days to catch up is now " + days + ".");
    }
  }

  // ---------- dialogs: each one remembers its own opener ----------
  const openers = {};
  function openDialog(sel, opener) {
    openers[sel] = opener || document.activeElement;
    $(sel).showModal();
  }
  function restoreFocus(sel) {
    const el = openers[sel];
    openers[sel] = null;
    if (el && document.contains(el) && !document.querySelector("dialog[open]")) el.focus();
  }

  // ---------- command palette (search and Ask Overture) ----------
  // It opens over the top-bar search field (Asana): the field turns into the palette input in place, results drop below.
  let palItems = [], palActive = 0, palAuto = true, askSeq = 0;
  const isQuestion = (q) => /\?\s*$/.test(q) || /^(who|what|when|where|why|how|which|is|are|was|were|do|does|did|can|could|should|will|would|tell|show|list|summari[sz]e|give)\b/i.test(q.trim());

  // Ask Overture: Claude (key on the server) -> on-device AI -> Overture's own records. The answer always says which one answered.
  const ASK_FROM = { claude: "Answered by Claude", device: "Answered on this device", rules: "From Overture's records" };
  const STOP = new Set(["the", "and", "for", "with", "what", "who", "whom", "when", "where", "which", "how", "why", "is", "are", "was", "does", "did", "about", "tell", "me", "my", "our", "their", "they", "them", "next", "call", "calls", "meeting", "this", "that", "from", "know", "should", "say", "ask", "any", "have", "has", "can", "you", "your", "there", "show", "give", "list"]);
  function rulesAnswer(q) {
    const ql = q.toLowerCase(), links = [], lines = [];
    const words = ql.split(/[^a-z0-9.@-]+/).filter((w) => w.length >= 3 && !STOP.has(w));
    const people = [], seen = new Set();
    D.invites.forEach((i) => i.attendees.forEach((a) => {
      const n = a.name.toLowerCase(), first = n.split(" ")[0];
      if (seen.has(a.email)) return;
      if (ql.includes(n) || (first.length >= 3 && words.includes(first))) { seen.add(a.email); people.push({ a, inv: i }); }
    }));
    people.slice(0, 3).forEach(({ a, inv }) => {
      const p = D.people[a.email] || {};
      lines.push(a.name + (p.title ? ", " + p.title : "") + ", is on your " + inv.company + " call (" + splitWhen(inv.when).day + " " + splitWhen(inv.when).start + ")." + (p.note ? " " + p.note : p.title ? "" : " No title or note in Overture's records yet."));
      links.push({ label: "Open the " + inv.company + " call", href: "#/calls/" + inv.id });
    });
    const cos = companyNames().filter((n) => ql.includes(n.toLowerCase()) || words.some((w) => n.toLowerCase().split(/\s+/).includes(w)));
    cos.slice(0, 2).forEach((n) => {
      const c = D.companies[n], inv = callForCompany(n);
      lines.push(n + ": " + (c ? c.status : "not in Overture's records yet") + "." + (c && c.notes ? " " + c.notes : "") + (inv ? " Next call " + splitWhen(inv.when).day + " " + splitWhen(inv.when).start + "." : " No call booked."));
      links.push({ label: "Open " + n, href: "#/companies/" + slug(n) });
    });
    if (!lines.length && /\bnext\b|\bupcoming\b|\btoday\b|\btomorrow\b/.test(ql)) {
      const inv = D.invites.find((i) => !i.ended) || D.invites[0];
      if (inv) { lines.push("Your next call is " + inv.company + ", " + longDay(inv) + " at " + splitWhen(inv.when).start + ", with " + names(inv) + "."); links.push({ label: "Open the call", href: "#/calls/" + inv.id }); }
      else lines.push(MODE === "connect" ? "No calendar is connected yet, so Overture has no calls to look at." : "You have no calls with outside guests in the next 14 days.");
    }
    if (!lines.length) lines.push("Overture couldn't answer that from its records. Try a person's or company's name, or ask about your next call.");
    return { text: lines.join("\n"), source: "rules", links: links.slice(0, 3) };
  }
  async function palAsk(q) {
    const seq = ++askSeq, box = $("#palAnswer");
    box.hidden = false;
    box.innerHTML = '<p class="pa-q">' + ic("sparkle") + "<span>" + esc(q) + '</span></p><p class="pa-busy">' + ic("loader", "spin") + "Thinking…</p>";
    const callId = app.view === "call" ? app.callId : null;
    let res = null;
    try { res = await C.askAI(q, callId); } catch (e) { res = null; }
    if (!res) res = rulesAnswer(q);
    if (seq !== askSeq || !$("#palette").open) return;
    box.innerHTML = '<p class="pa-q">' + ic("sparkle") + "<span>" + esc(q) + "</span></p>"
      + '<div class="pa-text">' + esc(res.text).replace(/\n/g, "<br>") + "</div>"
      + '<p class="pa-foot"><span class="pa-src">' + esc(ASK_FROM[res.source]) + "</span>"
      + (res.links || []).map((l) => '<a class="btn ghost sm" href="' + esc(l.href) + '" data-pal-link>' + esc(l.label) + "</a>").join("") + "</p>";
    announce(ASK_FROM[res.source] + ". " + res.text);
  }
  const palWhen = (i) => { const w = splitWhen(i.when); return w.day + " " + w.start; };
  // Bold the part of a label that matches the query (Asana, Linear).
  function palMark(label, ql) {
    const s = String(label), k = ql ? s.toLowerCase().indexOf(ql) : -1;
    return k < 0 ? esc(s) : esc(s.slice(0, k)) + "<mark>" + esc(s.slice(k, k + ql.length)) + "</mark>" + esc(s.slice(k + ql.length));
  }
  function palBuild(q) {
    q = q.trim();
    const ql = q.toLowerCase();
    const has = (s) => !ql || String(s).toLowerCase().includes(ql);
    const groups = [];
    if (q.length >= 2) groups.push(["Ask Overture", [{ icon: "sparkle", label: "Ask Overture: " + q, sub: "", ask: q }]]);
    const calls = D.invites.filter((i) => has(i.company) || has(i.title) || (ql && i.attendees.some((a) => has(a.name))))
      .map((i) => ({ icon: "phone", label: i.company, sub: palWhen(i) + " · " + kindOf(i), inv: i, href: "#/calls/" + i.id }));
    if (calls.length) groups.push([q ? "Calls" : "Upcoming calls", calls]);
    const ppl = [], seen = new Set();
    D.invites.forEach((i) => i.attendees.forEach((a) => {
      if (!has(a.name) || seen.has(a.name)) return;
      seen.add(a.name);
      ppl.push({ face: a, label: a.name, sub: [(D.people[a.email] || {}).title, i.company].filter(Boolean).join(" · "), href: "#/companies/" + slug(i.company) });
    }));
    if (ppl.length) groups.push(["People", q ? ppl : ppl.slice(0, 3)]);
    if (q) {
      const cos = companyNames().filter(has).map((n) => ({ tile: n, label: n, sub: String((D.companies[n] || {}).status || "").replace(/: .*/, ""), href: "#/companies/" + slug(n) }));
      if (cos.length) groups.push(["Companies", cos]);
    }
    const pages = [["Home", "#/home", "home"], ["Calls", "#/calls", "phone"], ["Alerts", "#/alerts", "bell"], ["In-call panel", "#/live", "video"], ["Companies", "#/companies", "building"], ["People map", "#/map", "network"], ["Data", "#/data", "database"], ["Settings", "#/settings", "settings"]]
      .filter(([l]) => has(l)).map(([l, h, icon]) => ({ icon, label: l, sub: "", href: h }));
    if (q && pages.length) groups.push(["Pages", pages]);
    // "Settings: Brief builder" and so on, one per menu (also found by words on that menu, e.g. "dark", "tone", "email").
    const sets = (window.MoabSettingsPage ? window.MoabSettingsPage.MENUS : []).filter((m) => q && (has("Settings: " + m.label) || m.words.some((x) => x.includes(ql))))
      .map((m) => ({ icon: "settings", label: "Settings: " + m.label, sub: m.sub, href: "#/settings/" + m.id }));
    if (sets.length) groups.push(["Settings", sets]);
    if (q.length >= 2) {
      const ads = C.state.adopters.filter((a) => a.org.toLowerCase().includes(ql)).slice(0, 3).map((a) => ({ icon: "list", label: a.org, sub: "On the public adopters list", pub: true, run: (op) => openCheck({ name: a.org, opener: op }) }));
      if (ads.length) groups.push(["Adopters list", ads]);
    }
    const checks = [];
    if (q.length >= 2 && !C.parseVer(C.cleanVer(q)) && !companyNames().some((n) => n.toLowerCase() === ql)) checks.push({ icon: "search", label: "Check “" + q + "” against the adopters list", sub: "", run: (op) => openCheck({ name: q, opener: op }) });
    if (C.parseVer(C.cleanVer(q))) checks.push({ icon: "tag", label: "Check Backstage " + C.cleanVer(q), sub: "Releases behind, security notices", run: (op) => openCheck({ version: C.cleanVer(q), opener: op }) });
    if (!q) checks.push({ icon: "search", label: "Check a company…", sub: "Is it on the adopters list", run: (op) => openCheck({ opener: op }) }, { icon: "tag", label: "Check a Backstage version…", sub: "Releases behind, security notices", run: (op) => openCheck({ focus: "anyVersion", opener: op }) });
    if (checks.length) groups.push(["Check", checks]);
    return groups;
  }
  // Asana's search dropdown: filter chips under the field, recent items when nothing is typed (Mobbin: Asana search).
  const PAL_FILTERS = [["all", "All"], ["calls", "Calls"], ["people", "People"], ["companies", "Companies"], ["public", "Adopters"]];
  const PAL_GROUPS = { calls: ["Calls", "Upcoming calls"], people: ["People"], companies: ["Companies"], public: ["Adopters list", "Check"] };
  let palFilter = "all";
  function palRecents() { return (C.store.get("recents") || []).slice(0, 4).map((r) => Object.assign({ icon: "clock" }, r)); }
  function palRemember(it) {
    if (!it.href) return;
    const keep = { label: it.label, sub: it.sub || "", href: it.href };
    if (it.face) keep.face = { name: it.face.name, email: it.face.email };
    if (it.tile) keep.tile = it.tile;
    C.store.set("recents", [keep].concat((C.store.get("recents") || []).filter((r) => r.href !== it.href)).slice(0, 6));
  }
  function palRender() {
    const q = $("#palInput").value.trim(), ql = q.toLowerCase();
    let groups = palBuild(q);
    if (palFilter === "companies" && !q) groups = [["Companies", companyNames().map((n) => ({ tile: n, label: n, sub: String((D.companies[n] || {}).status || "").replace(/: .*/, ""), href: "#/companies/" + slug(n) }))]].concat(groups);
    if (palFilter !== "all") groups = groups.filter(([g]) => PAL_GROUPS[palFilter].includes(g));
    else if (!q && palRecents().length) groups = [["Recent", palRecents()]].concat(groups);
    $("#palFilters").innerHTML = PAL_FILTERS.map(([k, l]) => '<button type="button" class="pal-chip" data-filter="' + k + '" aria-pressed="' + (palFilter === k) + '">' + l + "</button>").join("");
    palItems = groups.flatMap(([, items]) => items);
    // While typing, a question highlights "Ask Overture"; a name highlights the first search result.
    if (palAuto) palActive = palItems.length > 1 && palItems[0].ask && !isQuestion(q) ? 1 : 0;
    palActive = Math.min(palActive, Math.max(0, palItems.length - 1));
    let i = 0;
    $("#palList").innerHTML = groups.length ? groups.map(([g, items], gi) => '<div class="pal-sec" role="group" aria-labelledby="palg-' + gi + '"><div class="pal-group" id="palg-' + gi + '">' + esc(g) + "</div>" + items.map((it) => {
      const n = i++;
      const lead = it.face ? avatar(it.face, "sm") : it.tile ? coTile(it.tile, "co-tile-sm") : ic(it.icon);
      const meta = it.inv ? avatarStack(it.inv, "xs") : it.pub ? srcDot("Public data") : "";
      return '<div class="pal-opt" role="option" id="pal-' + n + '" data-i="' + n + '" aria-selected="false"><span class="pal-lead">' + lead + "</span>"
        + '<span class="pal-text"><span class="lbl">' + palMark(it.label, ql) + "</span>" + (it.sub ? '<span class="sub">' + esc(it.sub) + "</span>" : "") + "</span>"
        + (meta ? '<span class="pal-meta">' + meta + "</span>" : "") + '<span class="pal-go" aria-hidden="true">' + ic("cornerDownLeft") + "</span></div>";
    }).join("") + "</div>").join("")
      : '<div class="pal-empty"><p class="pal-empty-t">No results for “' + esc(q) + '”</p><p class="pal-empty-s">Try a company, a person, or a Backstage version like 1.30.0.</p></div>';
    $("#palCount").textContent = plural(palItems.length, "result");
    palSetActive(palActive, true);
  }
  // Moves the highlight without rebuilding the list, so hovering never restarts the row's icon motion.
  function palSetActive(n, scroll) {
    palActive = n;
    $$("#palList .pal-opt").forEach((o) => o.setAttribute("aria-selected", String(+o.dataset.i === n)));
    const act = $("#pal-" + n);
    if (!act) { $("#palInput").removeAttribute("aria-activedescendant"); return; }
    $("#palInput").setAttribute("aria-activedescendant", act.id);
    if (!scroll) return;
    if (n === 0) { $("#palList").scrollTop = 0; return; }
    const label = act.previousElementSibling;
    if (label && label.classList.contains("pal-group")) label.scrollIntoView({ block: "nearest" });
    act.scrollIntoView({ block: "nearest" });
  }
  // Line the palette up with the search field so its input sits where the field was. Phones have no field: the CSS centres it.
  // The search input lives in a field on the page (Home's ask box on Home, the top bar elsewhere). Typing happens right
  // there; the results drop down under it. Phones without a visible field get the input inside the panel instead.
  let PAL_IN = null;
  function searchField() {
    const f = (app.view === "home" && $("#homeAsk")) || $("#openPalette");
    return f && f.getBoundingClientRect().width ? f : null;
  }
  function placeSearchInput() {
    if (!PAL_IN) return;
    const f = (app.view === "home" && $("#homeAsk")) || $("#openPalette");
    if (!f || PAL_IN.parentElement === f) return;
    f.insertBefore(PAL_IN, $("kbd", f));
    PAL_IN.placeholder = f.id === "homeAsk" ? "Ask Overture or search calls, people, companies" : "Search calls, people, companies";
  }
  function palPlace() {
    const field = searchField(), pal = $("#palette");
    pal.classList.toggle("anchored", !!field);
    if (!field) return;
    const r = field.getBoundingClientRect(), w = Math.min(Math.max(r.width, 520), innerWidth - 32);
    pal.style.setProperty("--pal-w", w + "px");
    pal.style.setProperty("--pal-x", Math.round(Math.max(16, Math.min(r.left + r.width / 2 - w / 2, innerWidth - 16 - w))) + "px");
    pal.style.setProperty("--pal-y", Math.round(r.bottom + 6) + "px");
  }
  addEventListener("resize", () => { if ($("#palette").open) palPlace(); });
  function palOpen(anchor, text) {
    if ($("#palette").open) { PAL_IN.focus(); return; }
    palFilter = "all";
    if (typeof text === "string") PAL_IN.value = text;
    const inline = !!searchField();
    if (!inline) $("#palette .pal-input").insertBefore(PAL_IN, $("#palette .pal-esc"));
    palActive = 0;
    palAuto = true;
    askSeq++;
    $("#palAnswer").hidden = true;
    $("#palAnswer").innerHTML = "";
    $("#palette").classList.remove("kb");
    palRender();
    palPlace();
    openers["#palette"] = null;
    $("#palette").classList.toggle("inline", inline);
    if (inline) $("#palette").show(); else openDialog("#palette");
    PAL_IN.setAttribute("aria-expanded", "true");
    $("#palList").scrollTop = 0;
    PAL_IN.focus();
  }
  function palChoose(i) {
    const it = palItems[i];
    if (!it) return;
    if (it.ask) { palAsk(it.ask); return; }
    const opener = openers["#palette"];
    openers["#palette"] = null;
    $("#palette").close();
    palRemember(it);
    if (it.href) go(it.href);
    else if (it.run) it.run(opener);
  }

  // The privacy switches (now in Settings > Research sources & privacy) also live in C.state, which the brief, Ask Overture and
  // "Read Gong's transcript" read: keep them in step with the saved settings.
  function syncPrivacyState(s) {
    if (!LIVE_MODE || !s) return;
    ["gongInAI", "gongTranscripts", "transcriptsInAI"].forEach((k) => { C.state[k] = s.research[k] === true; if (D.settings) D.settings[k] = C.state[k]; });
  }

  async function disconnectGoogle() {
    const email = ((window.MOAB_STATUS || {}).google || {}).email;
    if (!confirm("Sign out" + (email ? " of " + email : "") + "? Overture stops reading your calendar until you sign in again. Your saved research and notes stay " + savedWhere() + ".")) return;
    try {
      const r = await C.fetchTimeout("/auth/google/disconnect", 15000, { method: "POST", headers: { "X-MOAB": "1" } });
      if (!r.ok) throw new Error();
    } catch (e) { toast("Couldn't disconnect. Is server.py running?"); return; }
    location.href = location.pathname + "#/home";
    location.reload();
  }

  // ---------- phone nav ----------
  function openNav() { document.body.classList.add("nav-open"); $("#scrim").hidden = false; $("#menuBtn").setAttribute("aria-expanded", "true"); $(".main").inert = true; const a = $("#rail a"); if (a) a.focus(); }
  function closeNav() {
    if (!document.body.classList.contains("nav-open")) return;
    document.body.classList.remove("nav-open"); $("#scrim").hidden = true; $("#menuBtn").setAttribute("aria-expanded", "false"); $(".main").inert = false; $("#menuBtn").focus();
  }

  // ---------- wiring ----------
  function init() {
    $$("[data-icon]").forEach((b) => { b.innerHTML = ic(b.dataset.icon); });
    const mac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
    $("#openPalette").innerHTML = ic("search") + '<kbd class="st-kbd">' + (mac ? "⌘K" : "Ctrl K") + "</kbd>";
    PAL_IN = $("#palInput");
    PAL_IN.setAttribute("aria-expanded", "false");
    placeSearchInput();
    $("#runAgain").innerHTML = ic("rotate") + "<span>Run again</span>";
    $("#runAgain").setAttribute("aria-label", "Run again");
    $("#since").max = D.today.slice(0, 4);
    // Honest labels: the Demo pill and "Sample" legend only in the demo; everywhere else, where the data came from.
    if (!DEMO) {
      $("#demoPill").hidden = true;
      $("#legend").innerHTML = '<span class="src public">Public = public data</span><span class="src yours">Yours = calendar + records</span>';
    }
    $(".appbar-me .avatar-ini").textContent = ME.initial;
    $("#appbarMe").title = DEMO ? "Chris (you)" : ME.email ? ME.name + " (" + ME.email + ")" : "No calendar connected";
    $("#meLabel").textContent = DEMO ? "Signed in as Chris" : ME.email ? "Signed in as " + ME.name : "No calendar connected";
    $$("[data-src]").forEach((el) => { const l = SRC[el.dataset.src]; el.textContent = l; el.className = "src " + srcKind(l); });


    window.addEventListener("hashchange", route);
    document.addEventListener("click", (e) => {
      const tlOpen = e.target.closest("[data-open-tl]");
      if (tlOpen) { openTimeline(C.emailForKey(tlOpen.dataset.openTl)); return; }
      const tlDlg = $("#tlDialog");
      if (tlDlg && tlDlg.open) {
        // The X, or a click that started and ended on the dim backdrop (not a text selection dragged out of the dialog).
        if (e.target.closest("[data-tl-close]") || (e.target === tlDlg && tlDlg.dataset.downOut === "1")) { tlDlg.close(); return; }
        // A link to a page (Full profile, a guest, Open brief): close first, so even a link to the page you're on takes you there.
        if (e.target.closest('#tlDialog a[href^="#/"]')) tlDlg.close();
      }
      const jump = e.target.closest("[data-jump]");
      if (jump) { e.preventDefault(); const t = document.getElementById(jump.dataset.jump); if (t) { t.scrollIntoView({ behavior: "smooth", block: "start" }); t.setAttribute("tabindex", "-1"); t.focus({ preventScroll: true }); } return; }
      const run = e.target.closest("[data-run]");
      if (run && !run.disabled) { const id = run.dataset.run; go("#/calls/" + id); runAgent(id); return; }
      if (e.target.closest("#runBtn")) { runAgent(app.callId); return; }
      const open = e.target.closest("[data-open]");
      if (open) {
        if (open.dataset.open === "drawer") openDrawer(open.dataset.focus);
        if (open.dataset.open === "check") openCheck({ focus: open.dataset.focus, opener: open });
        return;
      }
      const cn = e.target.closest("[data-check-name]");
      if (cn) { openCheck({ name: cn.dataset.checkName, opener: cn }); return; }
      const mv = e.target.closest("[data-mapview]");
      if (mv) { app.mapView = mv.dataset.mapview; $$("[data-mapview]").forEach((b) => b.setAttribute("aria-pressed", String(b === mv))); $("#mapSide").innerHTML = mapSide(null); mountMap(); return; }
      const sk = e.target.closest("[data-skin]");
      if (sk && app.view === "live") { app.liveSkin = sk.dataset.skin; renderLive(); $('[data-skin="' + app.liveSkin + '"]').focus(); return; }
      const tg = e.target.closest("[data-toast-go]");
      if (tg) { $("#toast").hidden = true; go(tg.dataset.toastGo); return; }
      if (e.target.closest("[data-toast-close]")) { $("#toast").hidden = true; return; }
      if (e.target.closest("#openInCall")) { app.liveCall = app.callId; }
      const rc = e.target.closest("[data-rs-confirm]");
      if (rc && !rc.disabled) { researchAction(rc, "confirm"); return; }
      const ra = e.target.closest("[data-rs-again]");
      if (ra && !ra.disabled) { researchAction(ra, "again"); return; }
      const ep = e.target.closest("[data-edit-person]");
      if (ep) { editingPerson = ep.dataset.editPerson; renderBrief(runs[app.callId]); const f = $("#pfTitle"); if (f) f.focus(); return; }
      const ec = e.target.closest("[data-edit-company]");
      if (ec) { editingCompany = ec.dataset.editCompany; renderCompany(editingCompany); const f = $("#cfStatus") || $("#cfNotes"); if (f) f.focus(); return; }
      const cx = e.target.closest("[data-cancel-edit]");
      if (cx) {
        if (cx.dataset.cancelEdit === "person") { const em = editingPerson; editingPerson = null; renderBrief(runs[app.callId]); const b = $('[data-edit-person="' + CSS.escape(em || "") + '"]'); if (b) b.focus(); }
        else { const n = editingCompany; editingCompany = null; renderCompany(n); const b = $("[data-edit-company]"); if (b) b.focus(); }
        return;
      }
      if (e.target.closest("[data-disconnect]")) { disconnectGoogle(); return; }
      if (e.target.closest("#hsSaveBtn")) { saveHubspot(app.callId); return; }
      const mna = e.target.closest("[data-mn-act]");
      if (mna && !mna.disabled) { const row = mna.closest("[data-mn-item]"); mna.disabled = true; mnAction(app.callId, row.dataset.mnItem, mna.dataset.mnAct, +(mna.dataset.mnIndex || 0)); return; }
      const mch = e.target.closest("[data-mn-change]");
      if (mch) { const mid = mch.closest("[data-mn-item]").dataset.mnItem, st = mnState(app.callId); st.change[mid] = !st.change[mid]; renderMentions(app.callId); const b = $('[data-mn-item="' + CSS.escape(mid) + '"] [data-mn-change]'); if (b) b.focus(); return; }
      const crm = e.target.closest("[data-conn-remove]");
      if (crm && mapInstance) {
        const ed = C.relationshipGraph().edges.find((x) => x.connId === crm.dataset.connRemove);
        if (ed) removeConnection(ed);
        return;
      }
      const mnh = e.target.closest("[data-mn-hs], [data-mn-hs-save]");
      if (mnh && !mnh.disabled) { mnHubspot(app.callId, mnh.closest("[data-mn-item]").dataset.mnItem, mnh.hasAttribute("data-mn-hs-save")); return; }
      const mnc = e.target.closest("[data-mn-hs-cancel]");
      if (mnc) { const mid = mnc.closest("[data-mn-item]").dataset.mnItem; delete mnState(app.callId).hs[mid]; renderMentions(app.callId); mnFocus(mid); return; }
      if (e.target.closest("#mnPasteBtn")) { const st = mnState(app.callId); st.paste = !st.paste; renderMentions(app.callId); const f = $(st.paste ? "#mnPaste" : "#mnPasteBtn"); if (f) f.focus(); return; }
      if (e.target.closest("#mnPasteCancel")) { mnState(app.callId).paste = false; renderMentions(app.callId); $("#mnPasteBtn").focus(); return; }
      if (e.target.closest("#mnPasteGo")) {
        const text = $("#mnPaste").value;
        if (!text.trim()) { $("#mnPaste").focus(); return; }
        if (DEMO) useSample(app.callId); else findMentions(app.callId, { text, source: "paste" }, "the pasted transcript");
        return;
      }
      if (e.target.closest("#mnNotesBtn")) { mentionsFromNotes(app.callId); return; }
      if (e.target.closest("#mnGongBtn")) { findMentions(app.callId, { source: "gong" }, "Gong's transcript"); return; }
      if (e.target.closest("#mnGranolaBtn")) { findMentions(app.callId, { source: "granola" }, "Granola's transcript"); return; }
      if (e.target.closest("#mnSampleBtn")) { useSample(app.callId); return; }
      if (e.target.closest("[data-hs-retry]")) { hsState(app.callId).error = ""; refreshHubspotPlan(app.callId); return; }
      if (e.target.closest("[data-reload]")) { e.preventDefault(); location.reload(); return; }
      if (e.target.closest("#rail a") && document.body.classList.contains("nav-open")) closeNav();
    });
    document.addEventListener("change", (e) => {
      const box = e.target.closest("input[data-todo]");
      if (box) {
        const run = runs[box.dataset.call];
        if (run) { if (box.checked) run.ticks.add(box.dataset.todo); else run.ticks.delete(box.dataset.todo); }
        if (app.view === "home") { const dc = $(".done-count"); if (dc) { const all = $$('[data-view="home"] input[data-todo]'); dc.textContent = all.filter((x) => x.checked).length + " of " + all.length + " done"; } }
        return;
      }
      if (e.target.id === "liveCall") { app.liveCall = e.target.value; renderLive(); $("#liveCall").focus(); }
      const ht = e.target.closest("input[data-hs-title]");
      if (ht) { const st = hsState(app.callId); if (ht.checked) st.titles.add(ht.dataset.hsTitle); else st.titles.delete(ht.dataset.hsTitle); refreshHubspotPlan(app.callId); return; }
      if (e.target.id === "mnFile") { const f = e.target.files && e.target.files[0]; e.target.value = ""; mentionsFromFile(app.callId, f); }
    });
    ["dragenter", "dragover"].forEach((t) => document.addEventListener(t, (e) => {
      const z = e.target.closest && e.target.closest("[data-mn-drop]");
      if (!z) return;
      e.preventDefault();
      z.classList.add("drag");
    }));
    document.addEventListener("dragleave", (e) => { const z = e.target.closest && e.target.closest("[data-mn-drop]"); if (z && !z.contains(e.relatedTarget)) z.classList.remove("drag"); });
    document.addEventListener("drop", (e) => {
      const z = e.target.closest && e.target.closest("[data-mn-drop]");
      if (!z) return;
      e.preventDefault();
      z.classList.remove("drag");
      const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      if (f && !mnState(app.callId).busy) mentionsFromFile(app.callId, f);
    });
    document.addEventListener("input", (e) => {
      if (e.target.id === "coSearch") $("#coRows").innerHTML = companyRows(e.target.value.trim());
      if (e.target.id === "palInput") { palActive = 0; palAuto = true; askSeq++; $("#palAnswer").hidden = true; $("#palette").classList.remove("kb"); palRender(); }
      if (e.target.id === "afterNotes") { const run = runs[app.callId]; if (run) run.notes = e.target.value; saveNotesSoon(app.callId, e.target.value); hubspotSoon(app.callId); }
    });
    document.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); palOpen(); return; }
      if (e.key === "/" && !e.target.closest("input, textarea, select, [contenteditable]") && !document.querySelector("dialog[open]")) { e.preventDefault(); palOpen(); return; }
      if (e.key === "Escape" && document.body.classList.contains("nav-open")) { closeNav(); return; }
      if ($("#palette").open && e.target.id === "palInput" && e.key === "Escape" && $("#palette").classList.contains("inline")) { e.preventDefault(); $("#palette").close(); return; }
      if (!$("#palette").open && e.target.id === "palInput" && (e.key === "ArrowDown" || e.key === "Enter")) palOpen();
      if ($("#palette").open && e.target.id === "palInput") {
        if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); palAuto = false; if (palItems.length) { $("#palette").classList.add("kb"); palSetActive((palActive + (e.key === "ArrowDown" ? 1 : -1) + palItems.length) % palItems.length, true); } }
        if (e.key === "Enter") { e.preventDefault(); palChoose(palActive); }
      }
      const tab = e.target.closest(".tabs [role=tab]");
      if (tab && (e.key === "ArrowLeft" || e.key === "ArrowRight")) { e.preventDefault(); setTab($("#tabBrief").getAttribute("aria-selected") === "true" ? "after" : "brief"); }
    });
    $("#palList").addEventListener("mousemove", (e) => { const o = e.target.closest(".pal-opt"); $("#palette").classList.remove("kb"); if (o && +o.dataset.i !== palActive) { palAuto = false; palSetActive(+o.dataset.i); } });
    $("#palAnswer").addEventListener("click", (e) => {
      const a = e.target.closest("[data-pal-link]");
      if (!a) return;
      e.preventDefault();
      openers["#palette"] = null;
      $("#palette").close();
      go(a.getAttribute("href"));
    });
    document.addEventListener("submit", (e) => {
      const pf = e.target.closest("[data-person-form]");
      if (pf) { e.preventDefault(); savePerson(pf); return; }
      const cf = e.target.closest("[data-company-form]");
      if (cf) { e.preventDefault(); saveCompany(cf); }
    });
    $("#palList").addEventListener("click", (e) => { const o = e.target.closest(".pal-opt"); if (o) palChoose(+o.dataset.i); });
    $("#palFilters").addEventListener("click", (e) => {
      const b = e.target.closest("[data-filter]");
      if (!b) return;
      palFilter = b.dataset.filter; palActive = 0; palRender(); $("#palInput").focus();
    });
    // Clicking anywhere in a search field puts the cursor in it; focusing it shows the results under it.
    document.addEventListener("mousedown", (e) => {
      const f = e.target.closest(".search-field");
      if (f && e.target !== PAL_IN) { e.preventDefault(); PAL_IN.focus(); }
      if ($("#palette").open && $("#palette").classList.contains("inline") && !e.target.closest("#palette, .search-field")) $("#palette").close();
    });
    PAL_IN.addEventListener("focus", () => { if (!$("#palette").open) palOpen(); });
    $("#palette").addEventListener("close", () => {
      PAL_IN.setAttribute("aria-expanded", "false");
      if ($("#palette").classList.contains("inline")) return;
      placeSearchInput(); // the phone panel hands the input back to the page
    });
    $("#railSearch").addEventListener("click", () => palOpen());
    $("#palette").addEventListener("mousedown", (e) => { if (e.target === $("#palette")) $("#palette").close(); });
    $("#askBtn").addEventListener("click", () => palOpen());
    if (/Mac|iPhone|iPad/.test(navigator.platform)) $("#railSearch .rs-kbd").textContent = "⌘K";
    // Home's ask bar and quick actions.
    $('[data-view="home"]').addEventListener("click", (e) => {
      if (e.target.closest("#homeAsk")) { palOpen($("#homeAsk")); return; }
      const g = e.target.closest("[data-go]");
      if (g) { go(g.dataset.go); return; }
      if (e.target.closest("[data-check]")) openCheck({ opener: e.target.closest("[data-check]") });
    });
    $("#appbarSearch").addEventListener("click", palOpen);
    $("#menuBtn").addEventListener("click", () => (document.body.classList.contains("nav-open") ? closeNav() : openNav()));
    $("#scrim").addEventListener("click", closeNav);
    $("#runAgain").addEventListener("click", () => runAgent(app.callId));
    $("#tabBrief").addEventListener("click", () => setTab("brief"));
    $("#tabAfter").addEventListener("click", () => setTab("after"));
    $("#update").addEventListener("click", () => {
      const run = runs[app.callId];
      if (!run) return;
      run.changes = C.afterCall(run.ctx, $("#afterNotes").value).map((c) => Object.assign(c, { state: null }));
      renderChanges(run);
      announce(run.changes.length ? plural(run.changes.length, "update") + " suggested." : "Nothing new in these notes.");
    });
    $("#importNotes").addEventListener("click", () => {
      const run = runs[app.callId];
      const notes = store.get("notes:" + app.callId) || [];
      const text = notes.map((n) => n.kind + ": " + n.text).join("\n");
      $("#afterNotes").value = ($("#afterNotes").value.trim() ? $("#afterNotes").value.trim() + "\n" : "") + text;
      if (run) run.notes = $("#afterNotes").value;
      saveNotesSoon(app.callId, $("#afterNotes").value);
      hubspotSoon(app.callId);
      announce(plural(notes.length, "note") + " added.");
    });
    $("#acceptAll").addEventListener("click", async () => {
      const run = runs[app.callId];
      const fresh = run.changes.filter((c) => !c.state);
      if (!(await syncChanges(run, fresh, []))) return;
      fresh.forEach((c) => { c.state = "saved"; });
      renderChanges(run);
      announce("All updates accepted.");
      $("#resultsTitle").setAttribute("tabindex", "-1");
      $("#resultsTitle").focus();
    });
    $("#changes").addEventListener("click", async (e) => {
      const b = e.target.closest("button[data-act]"), run = runs[app.callId];
      if (!b || !run) return;
      const i = +b.closest("li").dataset.i, ch = run.changes[i];
      if (b.dataset.act === "accept" && !(await syncChanges(run, [ch], []))) return;
      if (b.dataset.act === "undo" && ch.state === "saved" && !(await syncChanges(run, [], [ch]))) return;
      ch.state = b.dataset.act === "accept" ? "saved" : b.dataset.act === "dismiss" ? "dismissed" : null;
      renderChanges(run);
      const li = $('#changes li[data-i="' + i + '"]');
      const target = li && (run.changes[i].state ? $(".done-note", li) : $('button[data-act="accept"]', li));
      if (target) target.focus();
    });
    $("#checkClose").addEventListener("click", () => $("#checkDialog").close());
    $("#checkForm").addEventListener("submit", (e) => { e.preventDefault(); checkAny(); });
    $("#drawerClose").addEventListener("click", () => $("#drawer").close("cancel"));
    $("#drawer form").addEventListener("submit", (e) => { if (e.submitter && e.submitter.value === "save") applyDrawer(); });
    $("#drawer").addEventListener("input", () => { const run = runs[app.callId]; $("#drawerSave").textContent = inputsChanged() && run && run.ctx && run.ctx.done && !runningId ? "Save and rerun" : "Save"; });
    ["#checkDialog", "#drawer", "#palette"].forEach((sel) => {
      let downOnBackdrop = false;
      $(sel).addEventListener("pointerdown", (e) => { downOnBackdrop = e.target === e.currentTarget; });
      $(sel).addEventListener("click", (e) => { if (downOnBackdrop && e.target === e.currentTarget) e.currentTarget.close("cancel"); });
      $(sel).addEventListener("close", () => restoreFocus(sel));
    });

    // Settings (settings-page.js) reach the rest of the app through this; a change from another tab redraws the page.
    window.MoabApp = { go, announce, toast };
    if (window.MoabSettings) {
      window.MoabSettings.on((s, group) => {
        syncPrivacyState(s);
        if (!group || group === "brief") Object.values(runs).forEach((r) => { if (r.ctx && r.ctx.done) r.ctx.opener = C.openingLine(r.ctx); });
        renderNav();
        if (app.view !== "settings") route();
      });
    }
    route();
    C.watchResearch(() => {
      if (app.view === "people") { const e = C.emailForKey(app.personKey); return e ? [e] : []; }
      const r = runs[app.callId]; return app.view === "call" && r && r.ctx && r.ctx.done ? r.ctx.people.map((p) => p.email) : [];
    }, refreshPeople, () => {
      if (app.view === "call") return [inviteById(app.callId).company];
      if (app.view === "company") return [companyBySlug(app.slug)];
      if (app.view === "people") { const e = C.emailForKey(app.personKey); return e ? [window.CP.who(e).company] : []; }
      return [];
    });
    C.refreshLive().then(() => { renderNav(); if (app.view === "data") renderData(); });
    C.claudeChecked.then(() => { if (app.view === "data") renderData(); if (app.view === "home" && !D.invites.length) renderHome(); });
    C.deviceChecked.then(() => { if (app.view === "data") renderData(); });
  }
  document.addEventListener("DOMContentLoaded", init);
})();
