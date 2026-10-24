// Overture profiles: who a guest is at work and what their company does, as Overture's own research found it (core.js cleans it:
// C.personInfo, C.orgInfo). Drawn the same way on the person page (#/people/<key>), in the brief, on the company page, on the
// People map's side panel and in the in-call panel. Every bullet carries numbered source chips that open the page it came from.
// Layout references (Mobbin, web): Attio record page (header, then a main column and a Details side panel)
//   https://mobbin.com/screens/f6750bef-6bce-435c-8460-3c55f32f1254
// LinkedIn profile (name, role at company, Experience as a list with a company tile per role)
//   https://mobbin.com/screens/f8153155-60d7-4545-a4b5-0f2d14dfc34b
// Microsoft Copilot References (a numbered source list with the site under each title)
//   https://mobbin.com/screens/e631b279-cfc4-4c1c-85c9-f06c838b8df2
// Everything from the web or the calendar is escaped here; links must be http or https (C.cleanProfile already checked).
(function () {
  "use strict";
  const C = window.C;
  const { D, MODE, esc, ic, avatar, coTile, splitWhen, MONTHS, NEW_TAB, RELATION } = C;
  const DEMO = MODE === "demo";
  if (!C.ICONS.chevronLeft) C.ICONS.chevronLeft = '<path d="m15 18-6-6 6-6"/>';

  // ---------- small helpers ----------
  const day = (iso) => { const m = String(iso || "").match(/^(\d{4})-(\d{2})-(\d{2})/); return m ? MONTHS[+m[2] - 1] + " " + +m[3] + ", " + m[1] : ""; };
  const cap = (s) => String(s || "").charAt(0).toUpperCase() + String(s || "").slice(1);
  const first = (name) => String(name || "").split(/\s+/)[0] || "them";
  // Company names compared loosely: "TKS", "Tks" and "tks.world" are one company; "(…)" and legal suffixes don't count.
  const orgKey = (s) => String(s || "").toLowerCase().replace(/\(.*?\)/g, " ").replace(/\.[a-z]{2,}$/, "")
    .replace(/\b(the|inc|ltd|llc|gmbh|plc|corp|corporation|limited|co)\b\.?/g, " ").replace(/[^a-z0-9]+/g, "");
  const callsWith = (email) => D.invites.filter((i) => i.attendees.some((a) => a.email === email));
  const srcTag = () => '<span class="src ' + (DEMO ? "sample" : "public") + '">' + (DEMO ? "Sample" : "Found by Overture") + "</span>";

  // Who a guest is, from the calendar, Overture's records and the research.
  function who(email) {
    const info = C.personInfo(email), rec = info.rec, r = info.research || {}, calls = callsWith(email);
    const att = calls.length ? calls[0].attendees.find((a) => a.email === email) : null;
    const name = (att && att.name) || (info.profile && info.profile.name) || r.nameUsed || "Guest";
    const title = rec.title && rec.title !== "Title unknown" ? rec.title : r.title || "";
    const company = calls.length ? calls[0].company : (r.local && r.local.company) || "";
    const org = company ? C.orgInfo(company) : null;
    return { email, info, name, title, company, org, companyLabel: org && org.profile && org.profile.name ? org.profile.name : company, calls };
  }

  // A link to a person, a company or a call. The app uses its routes; the in-call panel opens people and companies inside
  // itself (opts.panel) and calls in the full app in a new tab. opts.companyHref(name) says whether the app has that company.
  function ctl(opts, kind, val, label, cls) {
    cls = cls || "";
    if (kind === "person") {
      return opts.panel ? '<button type="button" class="link-btn ' + cls + '" data-pp-person="' + esc(C.personKey(val)) + '">' + label + "</button>"
        : '<a class="' + cls + '" href="#/people/' + esc(C.personKey(val)) + '">' + label + "</a>";
    }
    if (kind === "company") {
      if (opts.panel) return '<button type="button" class="link-btn ' + cls + '" data-pp-org="' + esc(val) + '">' + label + "</button>";
      const href = opts.companyHref ? opts.companyHref(val) : "";
      return href ? '<a class="' + cls + '" href="' + esc(href) + '">' + label + "</a>" : label;
    }
    if (kind === "call") {
      return opts.panel ? '<a class="' + cls + '" href="index.html' + (DEMO ? "?demo=1" : "") + "#/calls/" + esc(encodeURIComponent(val)) + '" target="_blank" rel="noopener">' + label + NEW_TAB + "</a>"
        : '<a class="' + cls + '" href="#/calls/' + esc(encodeURIComponent(val)) + '">' + label + "</a>";
    }
    return label;
  }

  // ---------- the parts every profile is made of ----------
  // [1] [2]: each opens its source in a new tab.
  function cites(src, sources) {
    const chips = (src || []).filter((i) => sources[i]).map((i) => {
      const s = sources[i];
      return '<a class="pf-cite" href="' + esc(s.href) + '" target="_blank" rel="noopener noreferrer" title="' + esc(s.label + " · " + s.host) + '">'
        + '<span class="sr-only">Source </span>' + (i + 1) + '<span class="sr-only">: ' + esc(s.label) + " (opens in a new tab)</span></a>";
    });
    return chips.length ? '<span class="pf-cites">' + chips.join("") + "</span>" : "";
  }
  function bullets(list, sources, cls) {
    if (!list || !list.length) return "";
    return '<ul class="pf-list' + (cls ? " " + cls : "") + '" role="list">' + list.map((b) => "<li>" + (b.when ? '<span class="pf-date">' + esc(b.when) + "</span>" : "")
      + '<span class="pf-txt">' + esc(b.text) + cites(b.src, sources) + "</span></li>").join("") + "</ul>";
  }
  const lead = (s, sources) => (s ? '<p class="pf-lead">' + esc(s.text) + cites(s.src, sources) + "</p>" : "");
  function timeline(past, sources) {
    if (!past.length) return "";
    return '<ol class="pf-tl" role="list">' + past.map((r) => '<li class="pf-tl-item">' + coTile(r.org || r.role, "pf-tl-tile")
      + '<div class="pf-tl-body"><p class="pf-tl-role">' + esc(r.role || r.org) + cites(r.src, sources) + "</p>"
      + ((r.role && r.org) || r.when ? '<p class="pf-tl-meta">' + esc([r.role ? r.org : "", r.when].filter(Boolean).join(" · ")) + "</p>" : "")
      + bullets(r.points, sources, "pf-list-sm") + "</div></li>").join("") + "</ol>";
  }
  function factsGrid(facts, sources) {
    if (!facts.length) return "";
    return '<dl class="pf-facts">' + facts.map((f) => '<div class="pf-fact"><dt>' + esc(f.label) + "</dt><dd>" + esc(f.value) + cites(f.src, sources) + "</dd></div>").join("") + "</dl>";
  }
  function sourcesList(sources) {
    if (!sources.length) return "";
    return '<ol class="pf-srcs" role="list">' + sources.map((s, i) => '<li><span class="pf-n" aria-hidden="true">' + (i + 1) + "</span>"
      + '<span class="pf-src-t"><a href="' + esc(s.href) + '" target="_blank" rel="noopener noreferrer"><span class="sr-only">Source ' + (i + 1) + ": </span>" + esc(s.label) + ic("link", "ext") + NEW_TAB + "</a>"
      + '<span class="pf-host">' + esc(s.host) + "</span></span></li>").join("") + "</ol>";
  }
  // A section: an h2/h3 with its body on a page; a fold (<details>) in the narrow in-call panel.
  function section(opts, id, title, body, count) {
    if (!body) return "";
    if (opts.fold) {
      const open = (opts.open || []).includes(id);
      return '<details class="pf-fold"' + (open ? " open" : "") + '><summary><span class="pf-fold-t">' + esc(title) + "</span>"
        + (count ? '<span class="pf-count num">' + count + "</span>" : "") + ic("chevronDown", "pf-chev") + '</summary><div class="pf-fold-body">' + body + "</div></details>";
    }
    const hid = (opts.idp || "pf") + "-" + id, h = "h" + (opts.level || 2);
    return '<section class="' + (opts.cls || "pf-sec") + '" aria-labelledby="' + hid + '"><' + h + ' class="pf-h" id="' + hid + '">' + esc(title) + "</" + h + ">" + body + "</section>";
  }
  // "Researching…", or what Overture found when there was nothing to show. Never a to-do for the user.
  function stateHtml(status, note, name, org) {
    if (status === "pending") {
      return '<p class="pf-state" role="status">' + ic("search") + "<span><strong>Researching…</strong> Overture is reading public sources about "
        + esc(org ? name : first(name) + "'s work") + ". This fills in as soon as it is done.</span></p>";
    }
    if (["unknown", "error", "skipped", "notfound", "done", "later"].includes(status)) {
      const text = note || (status === "done" || status === "unknown" ? "Overture searched the web and found no public work information about " + (org ? "this company" : "them") + "." : "");
      return text ? '<p class="pf-state">' + ic("circleAlert") + "<span>" + esc(text) + "</span></p>" : "";
    }
    return "";
  }
  function metaHtml(prof, research, extra) {
    const bits = [];
    if (prof) {
      bits.push(srcTag());
      const at = day(prof.at || (research && research.foundAt));
      if (at) bits.push("<span>" + esc(at) + "</span>");
      if (prof.confidence) bits.push("<span>" + esc(cap(prof.confidence)) + " confidence</span>");
      bits.push("<span>" + esc(prof.sources.length + (prof.sources.length === 1 ? " source" : " sources")) + "</span>");
    }
    (extra || []).forEach((x) => bits.push("<span>" + esc(x) + "</span>"));
    return bits.length ? '<p class="pf-meta">' + bits.join('<span class="pf-sep" aria-hidden="true">·</span>') + "</p>" : "";
  }

  // ---------- a person ----------
  // The sections in their fixed order. opts: { fold, open: [ids], idp, level, noSources, extra: { connections: html } }
  function personSections(email, opts) {
    opts = opts || {};
    const w = who(email), pr = w.info.profile;
    if (!pr) return "";
    const S = pr.sources;
    return section(opts, "summary", "Summary", lead(pr.summary, S))
      + section(opts, "now", "Now", bullets(pr.now, S), pr.now.length)
      + section(opts, "past", "Past work", timeline(pr.past, S), pr.past.length)
      + section(opts, "education", "Education", bullets(pr.education, S), pr.education.length)
      + section(opts, "work", "Notable work", bullets(pr.work, S), pr.work.length)
      + section(opts, "forcall", "For this call", bullets(pr.forCall, S, "pf-forcall"), pr.forCall.length)
      + (opts.extra && opts.extra.connections ? opts.extra.connections : "")
      + (opts.noSources ? "" : section(opts, "sources", "Sources", sourcesList(S), S.length));
  }

  // The compact version for a row in the brief's "Who's on the call": a sentence, two "now" lines, the last three jobs.
  function briefPerson(email, opts) {
    opts = opts || {};
    const w = who(email), pr = w.info.profile;
    if (!pr) return "";
    const S = pr.sources;
    const past = pr.past.slice(0, 3).map((r) => '<li><span class="pf-txt"><strong>' + esc(r.role || r.org) + "</strong>" + esc(r.role && r.org ? ", " + r.org : "")
      + (r.when ? '<span class="pf-when"> · ' + esc(r.when) + "</span>" : "") + cites(r.src.length ? r.src : (r.points[0] || {}).src, S) + "</span></li>").join("");
    return '<div class="pf-mini">' + lead(pr.summary, S)
      + (pr.now.length ? '<p class="pf-mini-h">Now</p>' + bullets(pr.now.slice(0, 2), S, "pf-list-sm") : "")
      + (past ? '<p class="pf-mini-h">Before</p><ul class="pf-list pf-list-sm" role="list">' + past + "</ul>" : "")
      + '<p class="pf-mini-open">' + ctl(opts, "person", email, "Full profile" + ic("chevron"), "pf-open") + "</p></div>";
  }

  // "Bring up on the call": each guest's forCall lines, with whose they are.
  function forCallItems(people) {
    const out = [];
    (people || []).forEach((p) => {
      const pr = C.personInfo(p.email).profile;
      if (pr) pr.forCall.forEach((b) => out.push({ email: p.email, name: p.name, b, sources: pr.sources }));
    });
    return out;
  }
  function forCallHtml(people, opts) {
    const items = forCallItems(people);
    if (!items.length) return "";
    return '<ul class="pf-list pf-forcall" role="list">' + items.map((x) => '<li><span class="pf-txt">' + ctl(opts || {}, "person", x.email, avatar({ name: x.name, email: x.email }, "xs") + esc(first(x.name)), "pf-who")
      + " " + esc(x.b.text) + cites(x.b.src, x.sources) + "</span></li>").join("") + "</ul>";
  }

  // What Overture's calendar and records already know: the calls with you, who else is on them, and how you know them.
  function withYou(email, opts) {
    const w = who(email), r = w.info.research || {}, local = r.local || {}, rec = w.info.rec;
    let h = "";
    if (w.calls.length) {
      h += '<ul class="pf-calls" role="list">' + w.calls.map((inv) => {
        const s = splitWhen(inv.when);
        return "<li>" + ctl(opts, "call", inv.id, '<span class="pf-date-tile" aria-hidden="true"><span class="m">' + esc(s.month) + '</span><span class="d">' + esc(s.date) + "</span></span>"
          + '<span class="pf-call-text"><span class="pf-call-t">' + esc(inv.title) + '</span><span class="pf-call-s">' + esc(s.day + " · " + s.time) + "</span></span>", "pf-call") + "</li>";
      }).join("") + "</ul>";
      const others = [];
      w.calls.forEach((inv) => inv.attendees.forEach((a) => { if (a.email !== email && !others.some((o) => o.email === a.email)) others.push(a); }));
      if (others.length) {
        h += '<p class="pf-side-sub">Also on ' + (w.calls.length > 1 ? "these calls" : "this call") + '</p><ul class="pf-faces" role="list">' + others.map((a) => {
          const t = who(a.email).title;
          return "<li>" + avatar(a, "sm") + '<span class="pf-face-t">' + ctl(opts, "person", a.email, esc(a.name), "pf-face-name") + (t ? '<span class="pf-face-s">' + esc(t) + "</span>" : "") + "</span></li>";
        }).join("") + "</ul>";
      }
    }
    // How you know them (Overture's records or the sample's): a warm line from "you" on the People map.
    const ties = (D.relationships || []).filter((e) => e.a === "you" && e.b === "p:" + email && e.why);
    const known = [local.metBefore ? "Met before, last on " + local.lastMet : local.company ? "First meeting with them" : "", rec.note ? rec.note : ""].filter(Boolean);
    if (ties.length || known.length) {
      h += '<ul class="pf-list pf-list-sm pf-ties" role="list">' + ties.map((e) => '<li><span class="pf-txt"><strong>' + esc(cap(e.label)) + ".</strong> " + esc(e.why) + "</span></li>").join("")
        + known.map((t) => '<li><span class="pf-txt">' + esc(t) + "</span></li>").join("") + "</ul>";
    }
    return h;
  }
  function glance(email, opts) {
    const w = who(email), r = w.info.research || {};
    const rows = [["Company", w.company ? ctl(opts, "company", w.company, esc(w.companyLabel)) : ""], ["Title", esc(w.title)], ["Relationship", esc(RELATION[r.relationship] || "")],
      ["Team", esc(r.team || "")], ["Seniority", esc(cap(r.seniority || ""))], ["Time there", esc(r.tenure || "")]].filter((x) => x[1]);
    return rows.length ? '<dl class="pf-props">' + rows.map(([k, v]) => "<dt>" + k + "</dt><dd>" + v + "</dd>").join("") + "</dl>" : "";
  }

  // The whole person page for the app. opts: { companyHref, canAgain, connections: html of the map section }
  function pageHtml(email, opts) {
    opts = opts || {};
    const w = who(email), info = w.info, pr = info.profile, r = info.research || {};
    const rel = RELATION[r.relationship];
    const role = [w.title ? esc(w.title) : "", w.company ? ctl(opts, "company", w.company, esc(w.companyLabel)) : ""].filter(Boolean).join('<span class="pf-at"> at </span>');
    const actions = (w.calls.length ? ctl(opts, "call", w.calls[0].id, ic("arrowRight") + "Open brief", "btn secondary sm") : "")
      + '<button type="button" class="btn ghost sm" data-open-tl="' + esc(C.personKey(email)) + '">' + ic("clock") + "Past to present</button>"
      + (opts.canAgain && ["done", "unknown", "error", "later"].includes(info.status) ? '<button type="button" class="btn ghost sm" data-rs-again="' + esc(email) + '">' + ic("rotate") + (info.status === "later" ? "Look up now" : "Look up again") + "</button>" : "");
    let h = '<div class="topbar"><div class="topbar-inner"><nav class="co-crumbs" aria-label="Breadcrumb"><a href="#/map">People</a><span class="co-crumb-sep" aria-hidden="true">/</span>'
      + '<span class="co-crumb-here" aria-current="page">' + esc(w.name) + "</span></nav></div></div>";
    h += '<div class="pf-page"><header class="pf-head">' + avatar({ name: w.name, email }, "xl")
      + '<div class="pf-head-text"><div class="pf-title-row"><h1 tabindex="-1">' + esc(w.name) + "</h1>"
      + (rel ? '<span class="pill tag-blue">' + esc(rel) + "</span>" : "") + (r.found === "confirmed" ? '<span class="pill tag-green">Confirmed</span>' : "") + "</div>"
      + (role ? '<p class="pf-role">' + role + "</p>" : "") + metaHtml(pr, r) + "</div>"
      + (actions ? '<div class="pf-actions">' + actions + "</div>" : "") + "</header>";
    const state = pr ? (info.status === "pending" ? stateHtml("pending", "", w.name) : "") : stateHtml(info.status, info.note, w.name);
    const none = !pr && !state ? '<p class="pf-state">' + ic("circleAlert") + "<span>Overture has no public work profile for " + esc(first(w.name)) + " yet. What your calendar and records know is under With you.</span></p>" : "";
    const main = (pr ? askBox(email, "pfask") : "") + state + none + (pr ? personSections(email, { idp: "pf", extra: { connections: opts.connections || "" } }) : opts.connections || "");
    const sideOpts = { idp: "pfs", level: 2, cls: "pf-side-sec" };
    const side = section(sideOpts, "with", "With you", withYou(email, opts)) + section(sideOpts, "glance", "At a glance", glance(email, opts));
    h += '<div class="pf-body"><div class="pf-main">' + main + "</div>"
      + (side ? '<aside class="pf-side" aria-label="' + esc(w.name + ": with you") + '">' + side + "</aside>" : "") + "</div>";
    if (DEMO) h += '<p class="pf-foot">Sample data: this person, their profile and its sources are made up for the demo.</p>';
    return h + "</div>";
  }

  // The in-call panel's view of one guest: the same sections as folds, connections as a list, a way back.
  function panelPerson(email, opts) {
    opts = Object.assign({ panel: true }, opts || {});
    const w = who(email), info = w.info, pr = info.profile, r = info.research || {};
    const g = graph(email), conn = g.nodes.length > 1 ? listHtml(g, opts) : "";
    let h = '<div class="pp"><button type="button" class="pp-back" data-pp-back>' + ic("chevronLeft") + (opts.back || "People") + "</button>"
      + '<header class="pp-head">' + avatar({ name: w.name, email }, "lg") + '<div class="pp-head-t"><h2 class="pp-name" tabindex="-1">' + esc(w.name) + "</h2>"
      + ([w.title, w.companyLabel].filter(Boolean).length ? '<p class="pp-sub">' + esc([w.title, w.companyLabel].filter(Boolean).join(" · ")) + "</p>" : "")
      + (RELATION[r.relationship] ? '<p class="pp-pills"><span class="pill tag-blue">' + esc(RELATION[r.relationship]) + "</span></p>" : "") + "</div></header>"
      + metaHtml(pr, r) + (opts.top || "") + (pr ? askBox(email, "ppask") : "");
    h += pr ? (info.status === "pending" ? stateHtml("pending", "", w.name) : "") : stateHtml(info.status, info.note, w.name);
    const fold = { fold: true, open: ["summary", "now", "past", "forcall"] };
    h += pr ? personSections(email, Object.assign({}, fold, { extra: { connections: section(fold, "conn", "Connections", conn, g.nodes.length - 1) } }))
      : section(fold, "conn", "Connections", conn, g.nodes.length - 1);
    h += '<p class="pp-open"><a href="index.html' + (DEMO ? "?demo=1" : "") + "#/people/" + esc(C.personKey(email)) + '" target="_blank" rel="noopener">Open the full profile' + ic("link", "ext") + NEW_TAB + "</a></p>";
    return h + "</div>";
  }

  // ---------- a company ----------
  // opts: { fold, open, idp, level (of the sub-headings), heading: true to draw its own heading row, headTag, companyHref, panel }
  function orgSections(name, opts) {
    opts = opts || {};
    const info = C.orgInfo(name), pr = info.profile;
    if (!pr) return "";
    const S = pr.sources;
    return section(opts, "osummary", "Summary", lead(pr.summary, S))
      + section(opts, "facts", "Key facts", factsGrid(pr.facts, S), pr.facts.length)
      + section(opts, "what", "What they do", bullets(pr.what, S), pr.what.length)
      + section(opts, "news", "Recent news", bullets(pr.news, S), pr.news.length)
      + section(opts, "tech", "Tech and Backstage fit", bullets(pr.tech, S), pr.tech.length)
      + section(opts, "oforcall", "For this call", bullets(pr.forCall, S, "pf-forcall"), pr.forCall.length)
      + section(opts, "osources", "Sources", sourcesList(S), S.length);
  }
  // A whole company block: heading (the real name Overture found), how it was found, then the sections. "" when there is nothing.
  function orgBlock(name, opts) {
    opts = opts || {};
    const info = C.orgInfo(name), pr = info.profile;
    const state = pr ? (info.status === "pending" ? stateHtml("pending", "", name, true) : "") : stateHtml(info.status, info.note, name, true);
    if (!pr && !state) return "";
    const title = pr && pr.name ? pr.name : name;
    const extra = pr && info.domain ? [info.domain] : [];
    const sub = Object.assign({ idp: opts.idp || "org", level: (opts.level || 2) + 1 }, opts.fold ? { fold: true, open: ["osummary", "facts", "what", "oforcall"] } : {});
    return '<div class="pf-org">' + (opts.heading === false ? metaHtml(pr, null, extra)
      : '<div class="pf-org-head">' + coTile(title, "pf-org-tile") + '<div class="pf-org-head-t"><' + (opts.headTag || "h2") + ' class="pf-org-name">' + esc((opts.prefix || "") + title) + "</" + (opts.headTag || "h2") + ">"
        + metaHtml(pr, null, extra) + "</div></div>")
      + state + orgSections(name, sub) + "</div>";
  }

  // The short version for a side panel: how it was found, the summary, four facts, three lines on what they do.
  function orgMini(name, opts) {
    opts = opts || {};
    const info = C.orgInfo(name), pr = info.profile;
    if (!pr) return stateHtml(info.status, info.note, name, true);
    const href = opts.panel || (opts.companyHref && opts.companyHref(name));
    return '<div class="pf-mini">' + (pr.name && orgKey(pr.name) !== orgKey(name) ? '<p class="pm-card-name">' + esc(pr.name) + "</p>" : "") + metaHtml(pr, null)
      + lead(pr.summary, pr.sources) + factsGrid(pr.facts.slice(0, 4), pr.sources)
      + (pr.what.length ? '<p class="pf-mini-h">What they do</p>' + bullets(pr.what.slice(0, 3), pr.sources, "pf-list-sm") : "")
      + (href ? '<p class="pf-mini-open">' + ctl(opts, "company", name, "Open company" + ic("chevron"), "pf-open") + "</p>" : "") + "</div>";
  }

  // ---------- the person's own connection map ----------
  // Columns: where they work and worked | them | your calls with them and what was mentioned with them | who else is on those calls.
  const COLS = [["work", "Work"], ["self", "Person"], ["calls", "Calls and mentions"], ["people", "Also on the calls"]];
  function graph(email) {
    const w = who(email), pr = w.info.profile, nodes = [], edges = [], byId = {};
    const add = (n) => { if (!byId[n.id]) { byId[n.id] = n; nodes.push(n); } return byId[n.id]; };
    const link = (a, b, kind) => { if (!edges.some((e) => e.a === a && e.b === b)) edges.push({ a, b, kind }); };
    add({ id: "self", col: "self", type: "self", email, label: w.name, sub: w.title || w.companyLabel || "" });
    const same = new Set();
    if (w.company) {
      [w.company, w.companyLabel, w.org && w.org.domain].forEach((x) => { if (orgKey(x)) same.add(orgKey(x)); });
      add({ id: "co", col: "work", type: "company", name: w.company, label: w.companyLabel, sub: "Works here now", roles: [] });
      link("self", "co", "works");
    }
    (pr ? pr.past : []).forEach((r) => {
      if (!r.org) return;
      const k = orgKey(r.org);
      if (byId.co && same.has(k)) { byId.co.roles.push(r); return; } // an earlier role at the same company
      const n = add({ id: "past:" + k, col: "work", type: "past", label: r.org, roles: [], sub: "" });
      n.roles.push(r);
      n.sub = (n.roles[0].role || "Past employer") + (n.roles[0].when ? " · " + n.roles[0].when : "");
      link("self", n.id, "past");
    });
    const prev = w.info.rec.previous;
    if (prev && !same.has(orgKey(prev)) && !byId["past:" + orgKey(prev)]) {
      add({ id: "past:" + orgKey(prev), col: "work", type: "past", label: prev, roles: [], fromRecords: true, sub: "Past employer" + (w.info.rec.previousRole ? " · " + w.info.rec.previousRole : "") });
      link("self", "past:" + orgKey(prev), "past");
    }
    w.calls.forEach((inv) => {
      const s = splitWhen(inv.when), id = "call:" + inv.id;
      // The tile shows the date; the card says what kind of call it is ("Intro", "Discovery call") and when it starts.
      add({ id, col: "calls", type: "call", inv, label: inv.title.split(":")[0] || inv.title, sub: s.day + " · " + s.start });
      link("self", id, "call");
      inv.attendees.forEach((a) => {
        if (a.email === email) return;
        add({ id: "p:" + a.email, col: "people", type: "guest", email: a.email, label: a.name, sub: who(a.email).title || inv.company });
        link(id, "p:" + a.email, "guest");
      });
    });
    // People and companies mentioned on a call that connect to them (Settings > Mentions decides which kinds show).
    const rg = C.relationshipGraph(), rgBy = Object.fromEntries(rg.nodes.map((n) => [n.id, n])), pid = "p:" + email;
    rg.edges.filter((e) => e.kind === "mentioned" && (e.a === pid || e.b === pid)).forEach((e) => {
      const o = rgBy[e.a === pid ? e.b : e.a];
      if (!o) return;
      const id = "m:" + o.id;
      add({ id, col: "calls", type: o.type === "person" ? "mentioned" : "mentionedCo", label: o.label, sub: "Mentioned · " + (e.label || "on a call"), edge: e, node: o });
      link("self", id, "mentioned");
    });
    return { email, nodes, edges, byId, who: w };
  }

  function nodeLead(n) {
    if (n.type === "self" || n.type === "guest" || n.type === "mentioned") return avatar({ name: n.label, email: n.email }, "md");
    if (n.type === "call") { const s = splitWhen(n.inv.when); return '<span class="pm-date" aria-hidden="true"><span class="m">' + esc(s.month) + '</span><span class="d">' + esc(s.date) + "</span></span>"; }
    return coTile(n.label, "pm-tile");
  }
  const TYPE_WORD = { self: "Person", company: "Works here", past: "Past employer", call: "Call with you", guest: "Also on the call", mentioned: "Mentioned with them", mentionedCo: "Mentioned with them" };
  const TYPE_TAG = { self: "tag-purple", company: "tag-blue", past: "tag-gray", call: "tag-green", guest: "tag-teal", mentioned: "tag-orange", mentionedCo: "tag-orange" };
  function nodeHtml(n) {
    return '<button type="button" class="pm-node pm-' + n.type + '" data-pm="' + esc(n.id) + '" aria-pressed="false" title="' + esc(n.label + (n.sub ? " · " + n.sub : "")) + '">'
      + nodeLead(n) + '<span class="pm-text"><span class="sr-only">' + esc(TYPE_WORD[n.type]) + ': </span><span class="pm-name">' + esc(n.label) + "</span>"
      + (n.sub ? '<span class="pm-sub">' + esc(n.sub) + "</span>" : "") + "</span></button>";
  }
  function mapHtml(g) {
    const cols = COLS.filter(([c]) => g.nodes.some((n) => n.col === c));
    return '<div class="pm" data-pm-root><div class="pm-canvas"><svg class="pm-lines" aria-hidden="true"></svg><div class="pm-cols" style="--cols:' + cols.length + '">'
      + cols.map(([c, label]) => '<div class="pm-col pm-col-' + c + '"><p class="pm-col-h">' + esc(c === "self" ? first(g.who.name) : label) + '</p><div class="pm-col-nodes">'
        + g.nodes.filter((n) => n.col === c).map(nodeHtml).join("") + "</div></div>").join("")
      + '</div></div><div class="pm-card" aria-live="polite">' + hintHtml(g) + "</div></div>";
  }
  const hintHtml = (g) => '<p class="pm-hint">' + ic("network") + "<span>Select any card to see what Overture knows about it: " + esc(first(g.who.name)) + "'s companies, your calls with them and the people on those calls.</span></p>";
  // The in-call panel's version: the same nodes as a grouped list; each row opens its card under it.
  function listHtml(g, opts) {
    return '<div class="pm-list" data-pm-list>' + COLS.filter(([c]) => c !== "self" && g.nodes.some((n) => n.col === c)).map(([c, label]) => '<p class="pm-col-h">' + esc(label) + '</p><ul role="list">'
      + g.nodes.filter((n) => n.col === c).map((n) => '<li><button type="button" class="pm-row" data-pm="' + esc(n.id) + '" aria-expanded="false">' + nodeLead(n)
        + '<span class="pm-text"><span class="pm-name">' + esc(n.label) + "</span>" + (n.sub ? '<span class="pm-sub">' + esc(n.sub) + "</span>" : "") + "</span>" + ic("chevronDown", "pf-chev") + "</button>"
        + '<div class="pm-row-card" hidden></div></li>').join("") + "</ul>").join("") + "</div>";
  }

  // What a clicked card says. opts as for ctl(); opts.page: the person whose page this is (no "Open profile" to itself).
  function nodeCard(g, id, opts) {
    opts = opts || {};
    const n = g.byId[id];
    if (!n) return "";
    let body = "", acts = "";
    if (n.type === "self" || n.type === "guest") {
      const w = n.type === "self" ? g.who : who(n.email), pr = w.info.profile;
      body = (w.title || w.companyLabel ? '<p class="pm-card-sub">' + esc([w.title, w.companyLabel].filter(Boolean).join(" · ")) + "</p>" : "")
        + (pr ? lead(pr.summary, pr.sources) + bullets(pr.now.slice(0, 3), pr.sources, "pf-list-sm") : stateHtml(w.info.status, w.info.note, w.name));
      if (!(n.type === "self" && opts.page)) acts = ctl(opts, "person", w.email, "Open profile" + ic("chevron"), opts.panel ? "pm-act" : "btn secondary sm");
    } else if (n.type === "company") {
      const info = C.orgInfo(n.name), pr = info.profile;
      if (pr) {
        body = lead(pr.summary, pr.sources) + factsGrid(pr.facts.slice(0, 4), pr.sources)
          + (pr.what.length ? '<p class="pf-mini-h">What they do</p>' + bullets(pr.what.slice(0, 3), pr.sources, "pf-list-sm") : "");
      } else {
        const c = D.companies[n.name];
        body = stateHtml(info.status, info.note, n.label, true) + (c && c.status ? '<p class="pm-card-sub">' + esc(c.status) + (c.engineers ? " · about " + esc(c.engineers) + " engineers" : "") + "</p>" : "");
      }
      if (n.roles.length) body += '<p class="pf-mini-h">Earlier roles here</p>' + timeline(n.roles, g.who.info.profile.sources);
      if (opts.panel || (opts.companyHref && opts.companyHref(n.name))) acts = ctl(opts, "company", n.name, "Open company" + ic("chevron"), opts.panel ? "pm-act" : "btn secondary sm");
    } else if (n.type === "past") {
      body = n.roles.length ? timeline(n.roles, g.who.info.profile.sources)
        : '<p class="pm-card-sub">' + esc(first(g.who.name) + " worked here" + (g.who.info.rec.previousRole ? " as " + g.who.info.rec.previousRole : "") + ".") + "</p>"
          + '<p class="pf-note-src">From ' + esc(DEMO ? "the sample records" : "Overture's records") + ".</p>";
      const pc = D.companies[n.label];
      if (pc && pc.status) body += '<p class="pm-card-sub">' + esc("With Spotify: " + pc.status) + "</p>";
    } else if (n.type === "call") {
      const inv = n.inv, s = splitWhen(inv.when);
      body = '<p class="pm-card-sub">' + esc(s.day + " " + s.month + " " + s.date + " · " + s.time) + "</p>"
        + '<p class="pf-mini-h">On the call</p><ul class="pf-faces" role="list">' + inv.attendees.map((a) => "<li>" + avatar(a, "xs") + '<span class="pf-face-t">'
          + (a.email === g.email ? '<span class="pf-face-name">' + esc(a.name) + "</span>" : ctl(opts, "person", a.email, esc(a.name), "pf-face-name")) + "</span></li>").join("") + "</ul>";
      acts = ctl(opts, "call", inv.id, "Open brief" + ic("chevron"), opts.panel ? "pm-act" : "btn secondary sm");
    } else {
      const x = C.explainFor(n.edge);
      body = x ? C.explainHtml(x) : '<p class="pm-card-sub">' + esc(n.edge.why || n.sub) + "</p>";
    }
    return '<div class="pm-card-head"><span class="pill ' + TYPE_TAG[n.type] + '">' + esc(TYPE_WORD[n.type]) + '</span><p class="pm-card-name">' + esc(n.label) + "</p></div>"
      + body + (acts ? '<p class="pm-card-acts">' + acts + "</p>" : "");
  }

  // Square lines with round bends from card to card (the People map's look), redrawn whenever the box changes size.
  function bend(pts, R) {
    let d = "M" + pts[0][0] + " " + pts[0][1];
    for (let i = 1; i < pts.length; i++) {
      const a = pts[i - 1], b = pts[i];
      if (i === pts.length - 1) { d += " L" + b[0] + " " + b[1]; break; }
      const c = pts[i + 1], l1 = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1, l2 = Math.hypot(c[0] - b[0], c[1] - b[1]) || 1, r = Math.min(R, l1 / 2, l2 / 2);
      d += " L" + (b[0] - ((b[0] - a[0]) / l1) * r) + " " + (b[1] - ((b[1] - a[1]) / l1) * r) + " Q" + b[0] + " " + b[1] + " " + (b[0] + ((c[0] - b[0]) / l2) * r) + " " + (b[1] + ((c[1] - b[1]) / l2) * r);
    }
    return d;
  }
  function route(A, B) {
    if (B.left >= A.right - 1) { const m = (A.right + B.left) / 2; return [[A.right, A.cy], [m, A.cy], [m, B.cy], [B.left, B.cy]]; }
    if (B.right <= A.left + 1) { const m = (A.left + B.right) / 2; return [[A.left, A.cy], [m, A.cy], [m, B.cy], [B.right, B.cy]]; }
    if (B.top >= A.bottom - 1) { const m = (A.bottom + B.top) / 2; return [[A.cx, A.bottom], [A.cx, m], [B.cx, m], [B.cx, B.top]]; }
    const m = (A.top + B.bottom) / 2;
    return [[A.cx, A.top], [A.cx, m], [B.cx, m], [B.cx, B.bottom]];
  }
  // Mounts the interactive map made by mapHtml(). opts: link options plus page (the person whose page this is).
  function mountMap(root, g, opts) {
    if (!root) return { destroy() {} };
    const canvas = root.querySelector(".pm-canvas"), svg = root.querySelector(".pm-lines"), card = root.querySelector(".pm-card");
    let sel = null, hot = null;
    const box = (id) => {
      const el = root.querySelector('[data-pm="' + CSS.escape(id) + '"]');
      if (!el) return null;
      const r = el.getBoundingClientRect(), c = canvas.getBoundingClientRect();
      const left = r.left - c.left, top = r.top - c.top;
      return { left, top, right: left + r.width, bottom: top + r.height, cx: left + r.width / 2, cy: top + r.height / 2 };
    };
    function draw() {
      const W = canvas.clientWidth, H = canvas.clientHeight;
      if (!W || !H) return;
      svg.setAttribute("viewBox", "0 0 " + W + " " + H);
      const focus = hot || sel;
      svg.innerHTML = g.edges.map((e) => {
        const A = box(e.a), B = box(e.b);
        if (!A || !B) return "";
        const pts = route(A, B), on = focus && (e.a === focus || e.b === focus), cls = focus ? (on ? " lit" : " dim") : "";
        return '<path class="pm-line ' + e.kind + cls + '" d="' + bend(pts, 10) + '"/>'
          + [pts[0], pts[pts.length - 1]].map((p) => '<circle class="pm-dot' + cls + '" cx="' + p[0] + '" cy="' + p[1] + '" r="3"/>').join("");
      }).join("");
    }
    function select(id) {
      sel = id === sel ? null : id;
      root.querySelectorAll(".pm-node").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.pm === sel)));
      card.innerHTML = sel ? nodeCard(g, sel, opts) : hintHtml(g);
      card.classList.toggle("on", !!sel);
      draw();
      if (sel && card.getBoundingClientRect().bottom > window.innerHeight) card.scrollIntoView({ block: "nearest", behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    }
    const onClick = (e) => { const b = e.target.closest(".pm-node"); if (b && root.contains(b)) select(b.dataset.pm); };
    const onOver = (e) => { const b = e.target.closest(".pm-node"); const id = b ? b.dataset.pm : null; if (id !== hot) { hot = id; draw(); } };
    const onLeave = () => { if (hot) { hot = null; draw(); } };
    root.addEventListener("click", onClick);
    canvas.addEventListener("pointerover", onOver);
    canvas.addEventListener("pointerleave", onLeave);
    canvas.addEventListener("focusin", onOver);
    canvas.addEventListener("focusout", onLeave);
    const ro = new ResizeObserver(draw);
    ro.observe(canvas);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(draw);
    draw();
    return { select, draw, destroy() { ro.disconnect(); root.removeEventListener("click", onClick); } };
  }
  // The panel's list: a row opens (or closes) its card under it.
  function toggleRow(btn, g, opts) {
    const li = btn.closest("li"), slot = li && li.querySelector(".pm-row-card");
    if (!slot) return;
    const open = btn.getAttribute("aria-expanded") !== "true";
    btn.setAttribute("aria-expanded", String(open));
    slot.hidden = !open;
    slot.innerHTML = open ? nodeCard(g, btn.dataset.pm, opts) : "";
  }

  // ---------- ask about this person: a quick answer from Overture's saved research, with its sources ----------
  function askBox(email, idp) {
    const w = who(email), id = (idp || "ask") + "-" + C.personKey(email);
    return '<div class="pf-ask"><form class="pf-ask-form" data-ask-person="' + esc(C.personKey(email)) + '"><label class="sr-only" for="' + id + '">Ask about ' + esc(w.name) + "</label>"
      + ic("sparkle", "pf-ask-ic") + '<input id="' + id + '" class="pf-ask-in" type="text" maxlength="500" autocomplete="off" placeholder="' + esc("Ask about " + first(w.name) + ": past jobs, who they work with, what to bring up…") + '">'
      + '<button type="submit" class="btn primary sm">Ask</button></form><div class="pf-ask-out" aria-live="polite"></div></div>';
  }
  // [2] in an answer becomes the same numbered source chip the profile uses.
  function answerHtml(text, sources) {
    const list = (sources || []).map((s) => { const href = C.safeHref(s.url); return href ? { href, label: s.label || "", host: new URL(href).hostname.replace(/^www\./, "") } : null; });
    // [2], [1, 3] or [1-3]: one chip per source number
    return esc(text).replace(/\[(\d{1,2}(?:\s*[,–-]\s*\d{1,2})*)\]/g, (m, d) => {
      const nums = [];
      d.split(/\s*,\s*/).forEach((part) => { const r = part.split(/\s*[–-]\s*/).map(Number); for (let n = r[0]; n <= (r[1] || r[0]) && nums.length < 9; n++) nums.push(n - 1); });
      return cites(nums.filter((i) => list[i]), list);
    });
  }
  document.addEventListener("submit", async (e) => {
    const f = e.target.closest("[data-ask-person]");
    if (!f) return;
    e.preventDefault();
    const input = f.querySelector("input"), q = input.value.trim(), out = f.parentElement.querySelector(".pf-ask-out"), btn = f.querySelector("button");
    if (!q) { input.focus(); return; }
    if (DEMO) { out.innerHTML = '<p class="pf-ask-note">In the demo, questions need Overture running with your Claude key.</p>'; return; }
    const person = C.emailForKey(f.dataset.askPerson);
    if (!person) { out.innerHTML = '<p class="pf-ask-note">Overture lost track of who this is. Reload the page and ask again.</p>'; return; }
    btn.disabled = true;
    out.innerHTML = '<p class="pf-ask-note">Thinking…</p>'; // the box is already aria-live
    try {
      const j = await C.postJson("/api/ask", { question: q, person }, 45000); // the server may retry Claude once
      out.innerHTML = '<p class="pf-ask-q">' + esc(q) + '</p><p class="pf-ask-a">' + answerHtml(j.text || "", j.sources) + "</p>";
    } catch (err) {
      out.innerHTML = '<p class="pf-ask-note" role="alert">' + esc(/no-key/.test(err.message) ? "Add your Claude key in Settings to ask questions." : err.message) + "</p>";
    } finally { btn.disabled = false; }
  });

  // ---------- past to present: one person's career as a timeline, with who they're connected to at each stop ----------
  // Stops run oldest to newest: past jobs (the profile lists them newest first), their job now, then each call with you.
  // People a public page names with them (profile.people) hang under the stop whose company they share; the rest are listed after.
  // Other guests on a call hang under that call.
  // Same company: equal names ("TKS" = "Tks"), or one name's whole words start the other's ("TKS" and "TKS NYC"). Never part of a
  // word, so "Box" isn't "Dropbox" and "Meta" isn't "Metabase".
  const orgWords = (s) => String(s || "").toLowerCase().replace(/\(.*?\)/g, " ").replace(/\.[a-z]{2,}$/, "").split(/[^a-z0-9]+/)
    .filter((w) => w && !/^(the|inc|ltd|llc|gmbh|plc|corp|corporation|limited|co)$/.test(w));
  const sameOrg = (a, b) => {
    if (orgKey(a) && orgKey(a) === orgKey(b)) return true;
    const x = orgWords(a), y = orgWords(b), [s, l] = x.length <= y.length ? [x, y] : [y, x];
    return s.length > 0 && s.every((w, i) => w === l[i]);
  };
  function careerStops(email) {
    const w = who(email), pr = w.info.profile;
    const stops = (pr ? pr.past.slice().reverse() : []).map((r, i) => ({ id: "s" + i, kind: "past", role: r.role, org: r.org, when: r.when, src: r.src, points: r.points, people: [] }));
    stops.push({ id: "now", kind: "now", role: w.title, org: w.companyLabel || w.company, company: w.company, when: "Now", src: [], points: pr ? pr.now : [], people: [] });
    w.calls.forEach((c, i) => stops.push({ id: "c" + i, kind: "call", call: c, when: String(c.when).split(" · ")[0], people: [],
      guests: c.attendees.filter((a) => a.email !== email) }));
    const loose = [];
    (pr && pr.people ? pr.people : []).forEach((p, i) => {
      const at = p.org ? stops.find((s) => s.kind !== "call" && (sameOrg(p.org, s.org) || (s.kind === "now" && sameOrg(p.org, s.company)))) : null;
      (at ? at.people : loose).push(Object.assign({ id: "p" + i }, p));
    });
    return { w, pr, stops, loose };
  }
  const tlBtn = (id, cls, inner, label) => '<button type="button" class="' + cls + '" data-tl-item="' + id + '" aria-pressed="false" aria-label="' + esc(label) + '">' + inner + "</button>";
  function tlPersonChip(p) {
    return "<li>" + tlBtn(p.id, "tl-person", avatar({ name: p.name, email: "" }, "xs") + '<span class="tl-person-t"><span class="tl-person-n">' + esc(p.name) + "</span>"
      + (p.role ? '<span class="tl-person-r">' + esc(p.role) + "</span>" : "") + "</span>", p.name + (p.role ? ", " + p.role : "") + ": how they're connected") + "</li>";
  }
  function tlGuestChip(a, opts) {
    return '<li><span class="tl-person tl-guest">' + avatar(a, "xs") + '<span class="tl-person-t"><span class="tl-person-n">' + ctl(opts, "person", a.email, esc(a.name)) + "</span>"
      + '<span class="tl-person-r">On the call</span></span></span></li>';
  }
  function tlStop(s, opts) {
    let card;
    if (s.kind === "call") {
      card = tlBtn(s.id, "tl-card tl-card-call", '<span class="tl-ic" aria-hidden="true">' + ic("calendar") + '</span><span class="tl-card-t"><span class="tl-role">Call with you</span><span class="tl-org">'
        + esc(s.call.title) + "</span></span>", "Call with you: " + s.call.title + ", " + s.call.when);
    } else {
      const title = s.role || s.org || "Role not public", sub = s.role ? s.org : "";
      card = tlBtn(s.id, "tl-card" + (s.kind === "now" ? " tl-card-now" : ""), coTile(s.org || title, "tl-tile") + '<span class="tl-card-t"><span class="tl-role">' + esc(title) + "</span>"
        + (sub ? '<span class="tl-org">' + esc(sub) + "</span>" : "") + "</span>", [title, sub, s.when].filter(Boolean).join(", "));
    }
    const conn = s.people.map(tlPersonChip).join("") + (s.guests || []).map((a) => tlGuestChip(a, opts)).join("");
    return '<li class="tl-stop tl-' + s.kind + '"><p class="tl-when" title="' + esc(s.when || "Date not public") + '">' + esc(s.when || "Date not public") + '</p><span class="tl-dot" aria-hidden="true"></span>' + card
      + (conn ? '<ul class="tl-conn" role="list" aria-label="' + esc("Connected here") + '">' + conn + "</ul>" : "") + "</li>";
  }
  // The details for one stop or person, shown under the timeline when it's picked.
  function tlDetail(model, id, opts) {
    const { w, pr, stops, loose } = model, sources = pr ? pr.sources : [];
    const s = stops.find((x) => x.id === id);
    const p = s ? null : stops.flatMap((x) => x.people).concat(loose).find((x) => x.id === id);
    if (p) {
      return '<p class="tl-d-kicker">Connected with ' + esc(first(w.name)) + "</p><h3 class=\"tl-d-h\">" + esc(p.name) + "</h3>"
        + ([p.role, p.org].filter(Boolean).length ? '<p class="tl-d-sub">' + esc([p.role, p.org].filter(Boolean).join(" · ")) + "</p>" : "")
        + '<p class="tl-d-p">' + esc(p.how) + (p.when ? " (" + esc(p.when) + ")" : "") + cites(p.src, sources) + "</p>"
        + '<p class="tl-d-note">From public pages that name them together. Overture keeps work ties only.</p>';
    }
    if (!s) return "";
    if (s.kind === "call") {
      return '<p class="tl-d-kicker">' + esc(s.call.when) + '</p><h3 class="tl-d-h">' + esc(s.call.title) + "</h3>"
        + '<p class="tl-d-sub">' + esc(plural(s.call.attendees.length, "guest")) + " · " + esc(s.call.company) + "</p>"
        + '<p class="tl-d-acts">' + ctl(opts, "call", s.call.id, ic("arrowRight") + "Open brief", "btn secondary sm") + "</p>";
    }
    const head = '<p class="tl-d-kicker">' + esc(s.when || "Date not public") + '</p><h3 class="tl-d-h">' + esc(s.role || s.org || "Role not public") + "</h3>"
      + (s.role && s.org || s.src.length ? '<p class="tl-d-sub">' + (s.role && s.org ? (s.kind === "now" && s.company ? ctl(opts, "company", s.company, esc(s.org)) : esc(s.org)) : "")
        + cites(s.src, sources) + "</p>" : "");
    const body = s.points.length ? bullets(s.points, sources, "pf-list-sm") : '<p class="tl-d-note">No public details about this role.</p>';
    const org = s.kind === "now" && s.company ? orgMini(s.company, opts) : "";
    return head + body + (org ? '<div class="tl-d-org"><p class="tl-d-kicker">About ' + esc(s.org) + "</p>" + org + "</div>" : "");
  }
  const plural = (n, word) => n + " " + word + (n === 1 ? "" : "s");
  function timelineHtml(email, opts) {
    opts = opts || {};
    const model = careerStops(email), { w, pr, stops, loose } = model;
    const state = pr ? "" : stateHtml(w.info.status, w.info.note, w.name);
    return '<div class="tl"><header class="tl-head">' + avatar({ name: w.name, email }, "lg")
      + '<div class="tl-head-t"><p class="tl-kicker">Past to present</p><h2 class="tl-title" id="tlTitle" tabindex="-1">' + esc(w.name) + "</h2>"
      + ([w.title, w.companyLabel].filter(Boolean).length ? '<p class="tl-sub">' + esc([w.title, w.companyLabel].filter(Boolean).join(" at ")) + "</p>" : "") + "</div>"
      + '<div class="tl-head-acts">' + ctl(opts, "person", email, "Full profile", "btn ghost sm") + '<button type="button" class="icon-btn tl-close" data-tl-close aria-label="Close">' + ic("x") + "</button></div></header>"
      + state + '<div class="tl-scroll" tabindex="0" role="region" aria-label="' + esc(w.name + "'s career, oldest first") + '"><ol class="tl-track" role="list">'
      + stops.map((s) => tlStop(s, opts)).join("") + "</ol></div>"
      + (loose.length ? '<div class="tl-loose"><p class="tl-d-kicker">Also connected through work</p><ul class="tl-conn tl-conn-row" role="list">' + loose.map(tlPersonChip).join("") + "</ul></div>" : "")
      + (pr ? '<div class="tl-ask">' + askBox(email, "tlask") + "</div>" : "")
      + '<p class="sr-only" role="status" data-tl-said></p><div class="tl-detail">' + tlDetail(model, "now", opts) + "</div>"
      + (pr && pr.sources.length ? '<details class="tl-srcs"><summary>' + esc(plural(pr.sources.length, "source")) + "</summary>" + sourcesList(pr.sources) + "</details>" : "")
      + (DEMO ? '<p class="pf-foot">Sample data: made up for the demo.</p>' : "") + "</div>";
  }
  // Clicks inside a drawn timeline: pick a stop or a person to see its details.
  function mountTimeline(root, email, opts) {
    const model = careerStops(email);
    const pick = (id, say) => {
      root.querySelectorAll("[data-tl-item]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.tlItem === id)));
      const d = root.querySelector(".tl-detail");
      d.innerHTML = tlDetail(model, id, opts || {});
      // Say only what is shown, not the whole panel; the details are right after the timeline for anyone reading on.
      if (say) { const h = d.querySelector(".tl-d-h"); root.querySelector("[data-tl-said]").textContent = h ? "Showing " + h.textContent + " below." : ""; }
    };
    pick("now");
    root.onclick = (e) => { const b = e.target.closest("[data-tl-item]"); if (b) pick(b.dataset.tlItem, true); }; // one handler, even when reopened
  }
  // Once the timeline is on screen: scroll the track so the newest stops (now, and your calls) are in view.
  function showLatest(root) {
    const sc = root.querySelector(".tl-scroll");
    if (sc && sc.scrollWidth > sc.clientWidth + 1) sc.scrollLeft = sc.scrollWidth; // only when it doesn't all fit
  }

  window.CP = { who, ctl, cites, bullets, personSections, briefPerson, forCallItems, forCallHtml, withYou, pageHtml, panelPerson,
    orgSections, orgBlock, orgMini, graph, mapHtml, listHtml, nodeCard, mountMap, toggleRow, stateHtml, metaHtml, orgKey, timelineHtml, mountTimeline, showLatest };
})();
