// Overture Settings page (#/settings and #/settings/<menu>): a list of menus on the left, the chosen menu's grouped rows on the right.
// Mobbin references: Quo "Preferences" (menu list + label/help/control rows with dividers), Snowflake "Preferences" (rows grouped
// in bordered cards under a heading), AirOps "Notification preferences" (a table of switches), Asana "Display" settings.
// Every change saves at once (text after a short pause) and the header says "Saved". settings.js does the storing.
(function () {
  "use strict";
  const C = window.C, S = window.MoabSettings;
  if (!C || !S) return;
  const { $, $$, esc, ic, plural, D, MODE } = C;
  const DEMO = MODE === "demo";

  Object.assign(C.ICONS, {
    logOut: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5"/><path d="M21 12H9"/>',
    mail: '<rect width="20" height="16" x="2" y="4" rx="2"/><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/>',
    palette: '<circle cx="13.5" cy="6.5" r=".5" fill="currentColor"/><circle cx="17.5" cy="10.5" r=".5" fill="currentColor"/><circle cx="8.5" cy="7.5" r=".5" fill="currentColor"/><circle cx="6.5" cy="12.5" r=".5" fill="currentColor"/><path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.926 0 1.648-.746 1.648-1.688 0-.437-.18-.835-.437-1.125-.29-.289-.438-.652-.438-1.125a1.64 1.64 0 0 1 1.668-1.668h1.996c3.051 0 5.555-2.503 5.555-5.554C21.965 6.012 17.461 2 12 2z"/>',
    grip: '<circle cx="9" cy="12" r="1"/><circle cx="9" cy="5" r="1"/><circle cx="9" cy="19" r="1"/><circle cx="15" cy="12" r="1"/><circle cx="15" cy="5" r="1"/><circle cx="15" cy="19" r="1"/>',
    arrowUp: '<path d="m5 12 7-7 7 7M12 19V5"/>',
    arrowDown: '<path d="M12 5v14M19 12l-7 7-7-7"/>',
    moon: '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2m-7.07-14.07 1.41 1.41m11.32 11.32 1.41 1.41M2 12h2m16 0h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/>',
    keyboard: '<path d="M10 8h.01M12 12h.01M14 8h.01M16 12h.01M18 8h.01M6 8h.01M7 16h10M8 12h.01"/><rect width="20" height="16" x="2" y="4" rx="2"/>',
  });

  const MENUS = [
    { id: "brief", label: "Brief builder", icon: "listChecks", sub: "What the call brief shows, in what order, and how the opener sounds.", words: ["brief", "sections", "order", "opener", "tone", "short", "full"] },
    { id: "priorities", label: "Account priorities", icon: "trend", sub: "Target accounts and the rules that make a company Hot, Warm or Cold.", words: ["priority", "priorities", "target", "hot", "warm", "cold", "score", "accounts"] },
    { id: "panel", label: "In-call panel", icon: "panel", sub: "Which tabs and cards the in-call panel shows, and its shortcuts.", words: ["panel", "in-call", "cards", "tabs", "compact", "listening", "shortcuts", "keyboard"] },
    { id: "followup", label: "Follow-up emails", icon: "mail", sub: "One email template per kind of call, filled in after the call.", words: ["email", "follow-up", "followup", "template", "mail"] },
    { id: "mentions", label: "Mentions and connections", icon: "network", sub: "Looking up people and companies mentioned on a call, and what the People map shows.", words: ["mentions", "connections", "map", "relations", "quotes", "look-up", "lookup"] },
    { id: "alerts", label: "Alert rules", icon: "bell", sub: "Which changes become alerts, and when they reach you.", words: ["alerts", "digest", "quiet", "security", "notifications", "release", "stage"] },
    { id: "research", label: "Research sources and privacy", icon: "shield", sub: "Where Overture may look things up, sites it never uses, and what may go to AI.", words: ["research", "privacy", "sources", "gong", "hubspot", "transcripts", "blocked", "ai", "web"] },
    { id: "appearance", label: "Appearance", icon: "palette", sub: "Light or dark, the accent colour, and how dense the pages are.", words: ["appearance", "theme", "dark", "light", "accent", "colour", "color", "density", "compact"] },
  ];
  const BRIEF_LABELS = { opener: ["Opener", "The line to open the call with."], since: ["Since you last spoke", "Alerts and the last thing that happened."], lastTalk: ["Last talk and Gong", "Your last call in Gong and the history in Overture's records."],
    backstage: ["Backstage and version", "Their upgrade bill and Backstage details."], todos: ["To-dos", "What to do or send before the call."], people: ["People", "Who is on the call, and what Overture found about them."],
    security: ["Security notices", "The worst open notices for their version."], rivals: ["Rivals", "Rival tools named in the invite, with prices."], papers: ["Papers", "NDA and security pack."] };
  const PANEL_LABELS = { opener: ["Opener", "Brief tab"], points: ["Talking points", "Brief tab"], watch: ["Watch for", "Brief tab"], send: ["Still to send", "Brief tab"],
    people: ["People", "People tab"], map: ["Mini map", "People tab"], notes: ["Notes", "Notes tab"] };
  const RULE_LABELS = { engineers: ["Engineers above a number", "Bigger engineering teams feel the Backstage upkeep most."], adopter: ["On the Backstage adopters list", "They already run Backstage."],
    deal: ["Open deal stage", "There is an open deal in HubSpot or Overture's records."], alert: ["Recent alert", "A job change or another alert on one of their calls."], customer: ["Customer", "Already a Spotify customer (HubSpot or Overture's records)."] };
  const SIGNAL_LABELS = { jobChanges: ["Job changes", "Someone you met before now has a new company address."], newInvitees: ["New invitees", "A new person on a call, or a first meeting with a company."],
    mentioned: ["People mentioned", "Someone named on a call, from a transcript or your notes."], security: ["Security notices", "New Backstage security advisories."],
    release: ["New Backstage release", "A release from the last 14 days."], hubspotStages: ["HubSpot stage changes", "A company's deal stage changed in HubSpot."] };
  const MAP_LABELS = { people: "People mentioned", customer: "Customers", vendor: "Vendors and suppliers", partner: "Partners", competitor: "Competitors",
    ownership: "Owners, investors and acquisitions", other: "Other links (uses their product, other, unknown)" };
  const CALL_TYPES = [["intro", "Intro"], ["discovery", "Discovery"], ["demo", "Demo"], ["renewal", "Renewal"], ["other", "Other"]];
  const FILL_INS = ["first_name", "company", "my_name", "next_step", "summary", "date"];
  const ACCENTS = [["indigo", "Indigo", "#4f46e5"], ["green", "Green", "#15803d"], ["blue", "Blue", "#2563eb"], ["pink", "Pink", "#db2777"], ["orange", "Orange", "#c2410c"]];
  const SHORTCUTS = [[["Ctrl K", "/"], "or", "Search and Ask Overture, anywhere in the app"], [["Left", "Right"], "", "Switch tabs in a brief and in the in-call panel"],
    [["J", "K"], "", "Next and previous alert (Alerts page)"], [["U"], "", "Mark an alert read or unread (Alerts page)"],
    [["Up", "Down"], "", "Move through search results and menus"], [["Esc"], "", "Close search, menus and dialogs"]];

  const page = { menu: "brief", type: "intro", status: "", timer: null, field: null };
  const draft = () => JSON.parse(JSON.stringify(S.get()));
  const app = () => window.MoabApp || { announce() {}, go(h) { location.hash = h; } };

  // ---------- building blocks ----------
  const helpId = (id) => id + "-help";
  const row = (id, label, help, control, opts) => '<div class="st-row' + (opts && opts.cls ? " " + opts.cls : "") + '"><div class="st-row-text">'
    + (opts && opts.group ? '<span class="st-label" id="' + id + '-lbl">' + esc(label) + "</span>" : '<label class="st-label" for="' + id + '">' + esc(label) + "</label>")
    + (help ? '<p class="st-help" id="' + helpId(id) + '">' + help + "</p>" : "") + '</div><div class="st-ctl">' + control + "</div></div>";
  const toggle = (id, on, key, disabled) => '<input type="checkbox" role="switch" class="st-switch" id="' + id + '" data-key="' + esc(key) + '"' + (on ? " checked" : "")
    + ' aria-describedby="' + helpId(id) + '"' + (disabled ? " disabled" : "") + ">";
  const select = (id, value, key, options) => '<select class="input sm st-select" id="' + id + '" data-key="' + esc(key) + '" aria-describedby="' + helpId(id) + '">'
    + options.map(([v, l]) => '<option value="' + esc(v) + '"' + (String(v) === String(value) ? " selected" : "") + ">" + esc(l) + "</option>").join("") + "</select>";
  const segmented = (id, value, key, options) => '<div class="st-seg" role="radiogroup" aria-labelledby="' + id + '-lbl" aria-describedby="' + helpId(id) + '">'
    + options.map(([v, l]) => '<label class="st-seg-opt"><input type="radio" name="' + id + '" value="' + esc(v) + '" data-key="' + esc(key) + '"' + (v === value ? " checked" : "") + "><span>" + esc(l) + "</span></label>").join("") + "</div>";
  const group = (title, body, note) => '<section class="st-group"><h3 class="st-group-h">' + esc(title) + "</h3>" + (note ? '<p class="st-group-note">' + note + "</p>" : "") + '<div class="st-card">' + body + "</div></section>";
  // A reorderable list of {id, on}: drag a row, or use the up and down buttons (keyboard).
  function orderList(listKey, items, labels, what) {
    return '<ol class="st-order" role="list" data-order="' + esc(listKey) + '" aria-label="' + esc(what) + '">' + items.map((it, i) => {
      const [label, help] = labels[it.id], id = "ord-" + listKey.replace(/\W/g, "") + "-" + it.id;
      return '<li class="st-order-item' + (it.on ? "" : " off") + '" draggable="true" data-id="' + esc(it.id) + '">'
        + '<span class="st-grip" aria-hidden="true">' + ic("grip") + "</span>"
        + '<input type="checkbox" class="st-check" id="' + id + '" data-order-on="' + esc(it.id) + '"' + (it.on ? " checked" : "") + ' aria-describedby="' + id + '-help">'
        + '<span class="st-order-text"><label for="' + id + '" class="st-order-label">' + esc(label) + '</label><span class="st-help" id="' + id + '-help">' + esc(help) + "</span></span>"
        + '<span class="st-order-pos" aria-hidden="true">' + (i + 1) + "</span>"
        + '<button type="button" class="icon-btn sm" data-move="up" aria-label="' + esc("Move " + label + " up") + '"' + (i === 0 ? " disabled" : "") + ">" + ic("arrowUp") + "</button>"
        + '<button type="button" class="icon-btn sm" data-move="down" aria-label="' + esc("Move " + label + " down") + '"' + (i === items.length - 1 ? " disabled" : "") + ">" + ic("arrowDown") + "</button></li>";
    }).join("") + "</ol>";
  }
  // A list you add to and remove from (target accounts, blocked sites).
  function chipList(key, items, placeholder, label, help) {
    const id = "add-" + key.replace(/\W/g, "");
    return '<div class="st-chips-wrap"><form class="st-add" data-add="' + esc(key) + '"><label class="sr-only" for="' + id + '">' + esc(label) + '</label>'
      + '<input class="input sm" id="' + id + '" maxlength="120" autocomplete="off" placeholder="' + esc(placeholder) + '" aria-describedby="' + id + '-help">'
      + '<button type="submit" class="btn secondary sm">' + ic("plus") + "Add</button></form>"
      + '<p class="st-help" id="' + id + '-help">' + help + "</p>"
      + (items.length ? '<ul class="st-chips" role="list">' + items.map((x) => '<li class="st-chip"><span>' + esc(x) + '</span><button type="button" class="st-chip-x" data-remove="' + esc(key) + '" data-value="' + esc(x) + '" aria-label="' + esc("Remove " + x) + '">' + ic("x") + "</button></li>").join("") + "</ul>"
        : '<p class="st-empty">None yet.</p>') + "</div>";
  }

  // ---------- the menus ----------
  const VIEWS = {
    brief(s) {
      const b = s.brief;
      return group("Sections", orderList("brief.sections", b.sections, BRIEF_LABELS, "Brief sections, in order"),
        "Tick the sections the brief shows. Drag them, or use the arrows, to change the order. The header, the summary and the details at the end always show.")
        + group("Style", row("bLength", "Length", "Short keeps each section to its core: fewer history lines, the top 3 notices, no details at the end.", segmented("bLength", b.length, "brief.length", [["full", "Full"], ["short", "Short"]]), { group: true })
          + row("bTone", "Opener tone", "How the opening line sounds. The in-call panel uses the same line.", segmented("bTone", b.tone, "brief.tone", [["direct", "Direct"], ["warm", "Warm"], ["curious", "Curious"]]), { group: true })
          + '<div class="st-preview"><p class="st-preview-cap">Example opener</p><blockquote id="tonePreview">' + esc(tonePreview(b.tone)) + "</blockquote></div>");
    },
    priorities(s) {
      const p = s.priorities, w = (v) => [0, 1, 2, 3, 4, 5].map((n) => [n, n === 0 ? "Off (0)" : "+" + n]);
      const rules = Object.keys(RULE_LABELS).map((k) => {
        const r = p.rules[k], [label, help] = RULE_LABELS[k], id = "r-" + k + "-w";
        const min = k === "engineers" ? '<label class="st-inline-l" for="r-engineers-min">At least</label><input type="number" class="input sm st-num" id="r-engineers-min" min="0" max="100000" step="10" value="' + r.min + '" data-key="priorities.rules.engineers.min" aria-describedby="' + helpId(id) + '">' : "";
        return row(id, label, esc(help), min + select(id, r.on ? r.weight : 0, "priorities.rules." + k + ".weight", w()), { cls: "st-rule" });
      }).join("");
      const preview = previewPriorities();
      return group("Target accounts", chipList("priorities.targets", p.targets, "Company name, e.g. Northwind Freight", "Add a target account",
        "Each target account adds " + '<select class="input xs st-inline" id="tWeight" data-key="priorities.target" aria-label="Points for a target account">' + [0, 1, 2, 3, 4, 5].map((n) => '<option value="' + n + '"' + (n === p.target ? " selected" : "") + ">" + n + "</option>").join("") + "</select> points."))
        + group("Scoring rules", rules, "Each rule that matches adds its points. Set a rule to Off to ignore it.")
        + group("Badges", row("pHot", "Hot at", "Points needed for Hot.", '<input type="number" class="input sm st-num" id="pHot" min="1" max="25" value="' + p.hot + '" data-key="priorities.hot" aria-describedby="pHot-help">')
          + row("pWarm", "Warm at", "Points needed for Warm (below Hot). Anything less is Cold.", '<input type="number" class="input sm st-num" id="pWarm" min="0" max="24" value="' + p.warm + '" data-key="priorities.warm" aria-describedby="pWarm-help">')
          + row("pSort", "Sort by priority", "Hot accounts first on Home's Coming up list and the Companies table. Calls has its own By priority view.", toggle("pSort", p.sort, "priorities.sort")))
        + group("Your accounts now", preview);
    },
    panel(s) {
      const p = s.panel;
      return group("Cards", orderList("panel.cards", p.cards, PANEL_LABELS, "In-call panel cards, in order"),
        "A tab shows when at least one of its cards is ticked. Cards keep this order inside their tab; At a glance always shows on the Brief tab.")
        + group("Layout", row("pDensity", "Density", "Compact uses tighter spacing and hides the reason under each talking point.", segmented("pDensity", p.density, "panel.density", [["full", "Full"], ["compact", "Compact"]]), { group: true })
          + row("pListen", "Live listening reminder", "Shows a line in the panel when Meetily is off. With Meetily on (Research sources), the panel says “Listening via Meetily” while its transcript comes in.", toggle("pListen", p.listening, "panel.listening")))
        + group("Keyboard shortcuts", '<dl class="st-keys">' + SHORTCUTS.map(([keys, join, v]) => "<dt>" + keys.map((x) => "<kbd>" + esc(x) + "</kbd>").join(join ? ' <span class="st-or">' + join + "</span> " : " ") + "</dt><dd>" + esc(v) + "</dd>").join("") + "</dl>");
    },
    followup(s) {
      const t = s.followup.templates[page.type], def = S.DEFAULTS.followup.templates[page.type];
      const same = t.subject === def.subject && t.body === def.body;
      return group("Template", '<div class="st-pad"><div class="st-seg st-types" role="radiogroup" aria-label="Kind of call">' + CALL_TYPES.map(([v, l]) => '<label class="st-seg-opt"><input type="radio" name="fuType" value="' + v + '" data-type="1"' + (v === page.type ? " checked" : "") + "><span>" + l + "</span></label>").join("") + "</div>"
          + '<label class="field-label" for="tplSubject">Subject</label><input class="input" id="tplSubject" maxlength="200" value="' + esc(t.subject) + '" data-tpl="subject">'
          + '<label class="field-label" for="tplBody">Message</label><textarea class="input st-tpl-body" id="tplBody" rows="11" maxlength="4000" data-tpl="body" aria-describedby="tplHelp">' + esc(t.body) + "</textarea>"
          + '<p class="st-help" id="tplHelp">Fill-ins (click one to put it where the cursor is):</p><div class="st-fills" role="group" aria-label="Fill-ins">'
          + FILL_INS.map((f) => '<button type="button" class="st-fill" data-fill="' + f + '">{' + f + "}</button>").join("") + "</div>"
          + '<div class="st-actions"><button type="button" class="btn ghost sm" data-tpl-reset' + (same ? " disabled" : "") + ">" + ic("rotate") + "Reset this template</button></div></div>",
        "Overture picks the template from the call's title (intro, discovery, demo, renewal, anything else is Other). In After the call, <b>Draft follow-up</b> fills it in; you copy it or open it in your mail app. Overture never sends email.")
        + group("Preview", '<div class="st-pad"><p class="st-help">' + esc(previewCallLabel()) + '</p><pre class="st-mail" id="tplPreview">' + esc(previewTemplate(t)) + "</pre></div>");
    },
    mentions(s) {
      const m = s.mentions;
      return group("Looking them up", row("mAuto", "Look up mentions automatically", "On: names and companies you type in the in-call panel's notes are read as you type and looked up. Off: nothing is sent while you type; use After the call instead.", toggle("mAuto", m.autoLookup, "mentions.autoLookup"))
          + row("mAdd", "Add to the People map", "Only clear matches: one sourced match that fits the name and team. Also likely ones: the most likely match goes on the map too, marked “Likely”.", segmented("mAdd", m.autoAdd, "mentions.autoAdd", [["single", "Only clear matches"], ["likely", "Also likely ones"]]), { group: true })
          + row("mKeep", "Keep quotes for", "The sentence each person or company came up in is dropped after this many days.", select("mKeep", m.keepDays, "mentions.keepDays", [[7, "7 days"], [30, "30 days"], [90, "90 days"], [180, "180 days"], [365, "1 year"]])))
        + group("Show on the People map", Object.keys(MAP_LABELS).map((k) => row("map-" + k, MAP_LABELS[k], "", '<input type="checkbox" class="st-check" id="map-' + k + '" data-set="mentions.mapRelations" value="' + k + '"' + (m.mapRelations.includes(k) ? " checked" : "") + ">", { cls: "st-row-tight" })).join(""),
          "Which kinds of mentioned connections the People map and the panel's mini map draw. Your calls and guests always show.");
    },
    alerts(s) {
      const a = s.alerts;
      return group("Signals", Object.keys(SIGNAL_LABELS).map((k) => row("sig-" + k, SIGNAL_LABELS[k][0], esc(SIGNAL_LABELS[k][1]), toggle("sig-" + k, a.signals[k], "alerts.signals." + k))).join(""), "Which changes create an alert.")
        + group("Security", row("aSec", "Security notices to alert on", "Only critical, high and critical, or every new notice in the last 30 days.", segmented("aSec", a.security, "alerts.security", [["critical", "Critical only"], ["high", "High and above"], ["all", "All"]]), { group: true }))
        + group("Delivery", row("aDel", "How alerts arrive", "Daily digest groups each day's alerts into one card on Home and one section on the Alerts page.", segmented("aDel", a.delivery, "alerts.delivery", [["instant", "Instant"], ["digest", "Daily digest"]]), { group: true })
          + row("aQuiet", "Quiet hours", "During these hours the Alerts badge and pop-ups wait. Alerts still arrive.", toggle("aQuiet", a.quiet.on, "alerts.quiet.on"))
          + row("aFrom", "Quiet from", "", '<input type="time" class="input sm st-time" id="aFrom" value="' + esc(a.quiet.from) + '" data-key="alerts.quiet.from"' + (a.quiet.on ? "" : " disabled") + ">", { cls: "st-row-tight" })
          + row("aTo", "Quiet until", "", '<input type="time" class="input sm st-time" id="aTo" value="' + esc(a.quiet.to) + '" data-key="alerts.quiet.to"' + (a.quiet.on ? "" : " disabled") + ">", { cls: "st-row-tight" }));
    },
    research(s) {
      const r = s.research, st = C.state;
      // The Claude key: typed here once, saved on this PC by the server, never shown again (only its last 4 characters).
      const keyBox = group("Claude API key", '<form class="st-pad st-key" id="claudeKeyForm" autocomplete="off">'
        + '<p class="st-key-state" id="claudeKeyState" role="status">' + (DEMO ? "Not available in the demo." : "Checking…") + "</p>"
        + '<div class="st-key-row"><label class="sr-only" for="claudeKey">Claude API key</label>'
        + '<input id="claudeKey" class="input sm" type="password" placeholder="sk-ant-…" autocomplete="off" data-1p-ignore data-lpignore="true" spellcheck="false" aria-describedby="claudeKeyState"' + (DEMO ? " disabled" : "") + ">"
        + '<button type="submit" class="btn primary sm"' + (DEMO ? " disabled" : "") + ">Save key</button>"
        + '<button type="button" class="btn ghost sm" id="claudeKeyRemove" hidden>Remove</button></div>'
        + '<p class="st-key-help">Get one at <a href="https://console.anthropic.com/settings/keys" target="_blank" rel="noopener noreferrer">console.anthropic.com</a> → API keys. '
        + "It turns on web lookups (new guests, people and companies mentioned) and Ask Overture answers. Overture saves it on this PC and only ever sends it to Anthropic.</p></form>");
      const conn = (x) => (x && x.configured ? "" : ' <span class="st-tag">Not connected</span>');
      return keyBox + group("Sources", row("srcWeb", "Web research", "Claude with web search looks up new guests and people mentioned on a call (name, role and company only; never an email address).", toggle("srcWeb", r.web, "research.web"))
          + row("srcHub", "HubSpot", "Company status, deals, notes and guests' job titles." + conn(st.hubspot), toggle("srcHub", r.hubspot, "research.hubspot"))
          + row("srcGong", "Gong", "The last call's summary, key points, topics and trackers." + conn(st.gong), toggle("srcGong", r.gong, "research.gong"))
          + row("gongTranscripts", "Read Gong transcripts", "Off: Overture never asks Gong for a transcript. On: After the call can read a call's transcript from Gong to find the people mentioned. Only who was mentioned and one sentence each are kept.", toggle("gongTranscripts", r.gongTranscripts, "research.gongTranscripts", !r.gong))
          + row("srcMeetily", "Meetily", "Live transcript from Meetily, read from its files on this PC while a call runs (<a href=\"#/guides/meetily\">setup guide</a>). Names and companies said go to the mentions as they come; the transcript is never kept or sent anywhere. Off by default." + (st.meetily && st.meetily.on && !st.meetily.found ? ' <span class="st-tag">Recordings folder not found</span>' : ""), toggle("srcMeetily", r.meetily, "research.meetily"))
          + row("srcGranola", "Granola", "After a call, Overture reads its Granola note and transcript (<a href=\"#/guides/granola\">setup guide</a>): the people and companies mentioned, and the note's summary under After the call. The transcript isn't kept. Off by default." + conn(st.granola), toggle("srcGranola", r.granola, "research.granola")))
        + group("What may go to AI", row("aiShare", "Claude may see", "Titles only: names, titles and companies. Plus call notes: also your call notes and the notes in Overture's records. Plus transcripts: also who was mentioned on a call and their sentence (this is the old “Use transcripts in AI answers” switch).",
            segmented("aiShare", r.aiShare, "research.aiShare", [["titles", "Titles only"], ["notes", "+ call notes"], ["transcripts", "+ transcripts"]]), { group: true })
          + row("transcriptsInAI", "Use transcripts in AI answers", "Off: nothing from a transcript goes to Claude. On: Ask Overture also sees who was mentioned on a call and the sentence they came up in.", toggle("transcriptsInAI", r.transcriptsInAI, "research.transcriptsInAI"))
          + row("gongInAI", "Use Gong notes in AI answers", "Off: Gong's summaries stay on this PC and never go to Claude. On: Claude also sees them in brief summaries and Ask Overture.", toggle("gongInAI", r.gongInAI, "research.gongInAI")))
        + group("Blocked sites", '<div class="st-pad">' + chipList("research.blocked", r.blocked, "e.g. people-site.com", "Block a site",
            "Web research never uses these sites, on top of the built-in list. Subdomains are blocked too.")
          + '<details class="st-fold"><summary>' + ic("chevron", "chev") + "Built-in list (" + BUILT_IN.length + " sites, can't be removed)</summary><p class=\"st-builtin\">" + BUILT_IN.map(esc).join(", ") + "</p></details></div>");
    },
    appearance(s) {
      const a = s.appearance;
      return group("Theme", row("apTheme", "Theme", "Applies at once, on every page and in the in-call panel.", segmented("apTheme", a.theme, "appearance.theme", [["light", "Light"], ["dark", "Dark"]]), { group: true })
          + row("apAccent", "Accent colour", "Buttons, links, focus rings and selected items.", '<div class="st-swatches" role="radiogroup" aria-labelledby="apAccent-lbl" aria-describedby="apAccent-help">'
            + ACCENTS.map(([v, l, hex]) => '<label class="st-swatch" title="' + l + '"><input type="radio" name="apAccent" value="' + v + '" data-key="appearance.accent"' + (v === a.accent ? " checked" : "") + '><span class="st-dot" style="--sw:' + hex + '" aria-hidden="true"></span><span class="st-swatch-l">' + l + "</span></label>").join("") + "</div>", { group: true })
          + row("apDensity", "Density", "Compact fits more on a screen: tighter rows and smaller gaps.", segmented("apDensity", a.density, "appearance.density", [["comfortable", "Comfortable"], ["compact", "Compact"]]), { group: true }));
    },
  };
  // Sites research never uses: a copy of server.py BLOCKED_DOMAINS, shown read-only (tools/test_live.py checks they match).
  const BUILT_IN = /*blocked*/["zoominfo.com", "rocketreach.co", "rocketreach.com", "contactout.com", "apollo.io", "lusha.com", "signalhire.com", "seamless.ai", "uplead.com", "hunter.io", "clearbit.com", "leadiq.com", "kaspr.io", "snov.io", "adapt.io", "datanyze.com", "lead411.com", "cognism.com", "salesintel.io", "spokeo.com", "whitepages.com", "beenverified.com", "truepeoplesearch.com", "fastpeoplesearch.com", "peoplefinders.com", "radaris.com", "intelius.com", "pipl.com", "peekyou.com", "mylife.com", "thatsthem.com", "instantcheckmate.com", "truthfinder.com", "usphonebook.com", "nuwber.com", "clustrmaps.com", "idcrawl.com", "peoplelooker.com", "familytreenow.com", "anywho.com", "zabasearch.com", "spytox.com", "voterrecords.com", "peoplesearchnow.com", "cyberbackgroundchecks.com", "fastbackgroundcheck.com", "searchpeoplefree.com", "ussearch.com", "peoplesmart.com", "411.com", "addresses.com", "socialcatfish.com", "peopledatalabs.com", "fullcontact.com", "wiza.co", "salesql.com", "aeroleads.com", "getprospect.com", "skrapp.io", "voilanorbert.com", "findthatlead.com", "anymailfinder.com", "swordfish.ai", "nymeria.io", "facebook.com", "instagram.com", "tiktok.com", "snapchat.com", "pinterest.com", "x.com", "twitter.com", "threads.net", "bsky.app", "reddit.com", "vk.com"]/*end*/;

  // ---------- previews ----------
  const tonePreview = (tone) => C.openingLine({ products: [{ name: "Xirp", score: 3, why: [] }], bill: null }, tone);
  function previewPriorities() {
    const names = Array.from(new Set(D.invites.map((i) => i.company).concat(Object.keys(D.companies))));
    if (!names.length) return '<p class="st-empty st-pad">No companies yet. Your calls and records show here with their badge.</p>';
    const rows = names.map((n) => ({ n, p: C.priority(n) })).sort((a, b) => b.p.score - a.p.score).slice(0, 8);
    return '<ul class="st-prio" role="list">' + rows.map(({ n, p }) => '<li><span class="st-prio-name">' + esc(n) + "</span>" + C.priorityBadge(n) + '<span class="st-help">' + esc(p.score + " points" + (p.why.length ? ": " + p.why.join(", ") : "")) + "</span></li>").join("") + "</ul>";
  }
  function previewCallLabel() {
    const inv = D.invites[0];
    return inv ? "Filled in with your next call (" + inv.company + "). Real values come from the call and your notes." : "Filled in with example values.";
  }
  function previewTemplate(t) {
    const inv = D.invites[0], firsts = inv ? inv.attendees.map((a) => a.name.split(" ")[0]) : ["Alex"];
    const vals = { first_name: firsts.length > 2 ? "all" : firsts.join(" and "), company: inv ? inv.company : "Acme", my_name: C.ME.name === "You" ? "[your name]" : C.ME.name,
      next_step: "Send the security pack by Friday", summary: "- They run Backstage themselves\n- Two people keep it upgraded", date: new Date().toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" }) };
    const fill = (x) => String(x).replace(/\{(first_name|company|my_name|next_step|summary|date)\}/g, (_, k) => vals[k]);
    return "Subject: " + fill(t.subject) + "\n\n" + fill(t.body);
  }

  // ---------- render ----------
  // Claude key box (research menu): state, save, remove. The key never comes back from the server.
  async function claudeKeyRefresh(msg) {
    const st = $("#claudeKeyState"); if (!st) return;
    try {
      const r = await fetch("/api/claude-key", { headers: { "X-MOAB": "1" } }), j = await r.json();
      st.textContent = (msg ? msg + " " : "") + (j.saved ? (j.source === "env" ? "Using the key from the ANTHROPIC_API_KEY setting (ends in " + j.last4 + ")." : "Key saved on this PC (ends in " + j.last4 + "). Web lookups are on.") : "No key yet. Web lookups and Ask Overture answers are off.");
      st.classList.toggle("ok", !!j.saved);
      // The box empties after a save so the key never sits on screen; show that it's saved instead of looking wiped.
      const inp = $("#claudeKey"); if (inp) inp.placeholder = j.saved ? "Saved, ends in " + j.last4 : "sk-ant-…";
      const rm = $("#claudeKeyRemove"); if (rm) rm.hidden = !(j.saved && j.source === "file");
    } catch (e) { st.textContent = "Overture's server isn't answering."; }
  }
  document.addEventListener("submit", async (e) => {
    if (e.target.id !== "claudeKeyForm") return;
    e.preventDefault();
    const input = $("#claudeKey"), key = input.value.trim();
    if (!key) { input.focus(); return; }
    try {
      input.value = "";  // never leave the key in the box, whatever the server answers
      const r = await fetch("/api/claude-key", { method: "PUT", headers: { "Content-Type": "application/json", "X-MOAB": "1" }, body: JSON.stringify({ key }) });
      const j = await r.json();
      if (!r.ok) { $("#claudeKeyState").textContent = j.error || "Couldn't save the key."; input.focus(); return; }
      claudeKeyRefresh("Saved.");
      C.state.claudeOn = true;
    } catch (err) { $("#claudeKeyState").textContent = "Couldn't save: Overture's server isn't answering."; }
  });
  document.addEventListener("click", async (e) => {
    if (!e.target.closest("#claudeKeyRemove")) return;
    if (!confirm("Remove the saved Claude key from this PC? Web lookups and Ask Overture answers turn off.")) return;
    await fetch("/api/claude-key/remove", { method: "POST", headers: { "X-MOAB": "1" } }).catch(() => {});
    C.state.claudeOn = false;
    claudeKeyRefresh("Removed.");
  });

  function render(menu) {
    const m = MENUS.find((x) => x.id === menu) || null;
    if (menu && !m) { app().go("#/settings", true); return "Settings"; }
    page.menu = m ? m.id : null;
    const sec = $('[data-view="settings"]'), s = S.get();
    // The open menu's name is the page's h1 (it gets focus on arrival); with no menu open, "Settings" is.
    const nav = '<nav class="st-nav" aria-label="Settings menus">' + (m ? '<p class="st-title">Settings</p>' : '<h1 class="page-title st-title" tabindex="-1">Settings</h1>')
      + '<p class="st-mode">' + (DEMO ? "Demo: saved in this browser only." : MODE === "live" ? "Saved in Overture's records on this PC." : "Saved on this PC.") + "</p>"
      + '<ul class="st-menu" role="list">' + MENUS.map((x) => '<li><a href="#/settings/' + x.id + '"' + (x.id === page.menu ? ' aria-current="page"' : "") + ">" + ic(x.icon) + '<span class="st-menu-l">' + esc(x.label) + "</span>" + ic("chevron", "chev") + "</a></li>").join("")
      + '<li><a href="#/guides">' + ic("note") + '<span class="st-menu-l">Setup guides</span>' + ic("chevron", "chev") + "</a></li></ul></nav>";
    const body = m ? '<div class="st-panel"><header class="st-head"><a class="back st-back" href="#/settings" aria-label="Back to Settings">' + ic("chevronLeft") + "<span>Settings</span></a>"
      + '<div class="st-head-row"><h1 class="st-h" tabindex="-1">' + esc(m.label) + '</h1><span class="st-saved" id="stSaved" role="status" aria-live="polite"></span></div>'
      + '<p class="st-sub">' + esc(m.sub) + "</p></header>" + '<div class="st-form">' + VIEWS[m.id](s) + "</div>"
      + '<div class="st-foot"><button type="button" class="btn ghost sm" data-reset-menu>' + ic("rotate") + "Reset " + esc(m.label.toLowerCase()) + " to defaults</button></div></div>"
      : '<div class="st-panel st-intro"><p class="st-sub">Pick a menu. Changes save as you make them.</p></div>';
    sec.innerHTML = '<div class="st' + (m ? " has-menu" : "") + '">' + nav + body + "</div>";
    if (page.menu === "research" && !DEMO) claudeKeyRefresh();
    sec.classList.toggle("st-picked", !!m);
    if (page.status) setSaved(page.status);
    return m ? m.label + " · Settings" : "Settings";
  }
  const groupOf = (key) => key.split(".")[0];
  function setSaved(text, err) {
    page.status = err ? "" : text;
    const el = $("#stSaved");
    if (!el) return;
    el.className = "st-saved" + (err ? " err" : /^Saved/.test(text) ? " ok" : "");
    el.innerHTML = text ? (/^Saved/.test(text) ? ic("check") : text === "Saving…" ? ic("loader", "spin") : "") + "<span>" + esc(text) + "</span>" : "";
    if (/^Saved/.test(text)) { clearTimeout(page.savedTimer); page.savedTimer = setTimeout(() => { page.status = ""; if ($("#stSaved")) $("#stSaved").innerHTML = ""; }, 4000); }
  }
  // Set a value inside a copy of the settings by its path ("alerts.quiet.on").
  function put(obj, key, value) {
    const parts = key.split("."), last = parts.pop();
    let o = obj;
    parts.forEach((p) => { o = o[p]; });
    o[last] = value;
  }
  let saveSeq = 0;
  async function commit(group, value, opts) {
    const seq = ++saveSeq;
    setSaved("Saving…");
    try {
      await S.save(group, value);
      if (seq === saveSeq) setSaved(DEMO ? "Saved in this browser" : "Saved");
      if (opts && opts.redraw) redraw(opts.focus);
      if (opts && opts.said) app().announce(opts.said);
      return true;
    } catch (e) {
      if (seq === saveSeq) setSaved(e.message, true);
      app().announce(e.message);
      redraw(opts && opts.focus); // show what is really saved
      return false;
    }
  }
  // Redraw the open menu and put focus back on the same control.
  function redraw(focusSel) {
    if (!page.menu) return;
    const act = document.activeElement, sel = focusSel || (act && act.id ? "#" + CSS.escape(act.id) : null);
    const y = $(".main").scrollTop;
    render(page.menu);
    $(".main").scrollTop = y;
    const el = sel && $(sel);
    if (el) el.focus({ preventScroll: true });
  }
  function valueOf(el) {
    if (el.type === "checkbox") return el.checked;
    if (el.type === "number" || el.tagName === "SELECT" && /^\d+$/.test(el.value)) return parseInt(el.value, 10);
    return el.value;
  }
  function changeKey(el) {
    const key = el.dataset.key, g = groupOf(key), d = draft();
    let v = valueOf(el);
    if (el.type === "number") {
      if (!Number.isFinite(v)) { setSaved("Type a number", true); return; }
      v = Math.max(+el.min || 0, Math.min(+el.max || 100000, v));
    }
    put(d, key, v);
    if ((key === "priorities.hot" || key === "priorities.warm") && d.priorities.warm >= d.priorities.hot) { setSaved("Warm must be below Hot", true); redraw("#" + el.id); return; }
    if (/^priorities\.rules\.\w+\.weight$/.test(key)) put(d, key.replace(/weight$/, "on"), v > 0);  // Off (0) turns the rule off
    const redrawNow = /^(alerts\.quiet\.on|research\.(aiShare|transcriptsInAI|gong))$/.test(key) || g === "priorities";
    commit(g, d[g], { redraw: redrawNow, focus: el.id ? "#" + CSS.escape(el.id) : null, said: el.type === "checkbox" ? (el.closest(".st-row") ? $(".st-label", el.closest(".st-row")).textContent + (v ? " on" : " off") : "") : "" });
    if (key === "brief.tone" && $("#tonePreview")) $("#tonePreview").textContent = tonePreview(v);
  }

  // ---------- events ----------
  const root = () => $('[data-view="settings"]');
  document.addEventListener("change", (e) => {
    if (!root() || !root().contains(e.target)) return;
    const el = e.target;
    if (el.dataset.key && el.type !== "text") return changeKey(el);
    if (el.dataset.type) { page.type = el.value; redraw('input[name="fuType"][value="' + page.type + '"]'); return; }
    if (el.dataset.set) {
      const key = el.dataset.set, g = groupOf(key), d = draft();
      const set = new Set(key.split(".").reduce((o, p) => o[p], d));
      if (el.checked) set.add(el.value); else set.delete(el.value);
      put(d, key, Array.from(set));
      commit(g, d[g], { said: el.labels && el.labels[0] ? el.labels[0].textContent + (el.checked ? " shown" : " hidden") : "" });
      return;
    }
    const on = el.dataset.orderOn;
    if (on) {
      const list = el.closest("[data-order]").dataset.order, g = groupOf(list), d = draft();
      list.split(".").reduce((o, p) => o[p], d).forEach((it) => { if (it.id === on) it.on = el.checked; });
      el.closest("li").classList.toggle("off", !el.checked);
      commit(g, d[g], { said: (el.labels[0] ? el.labels[0].textContent : on) + (el.checked ? " shown" : " hidden") });
    }
  });
  // Text: save after a short pause (template subject and body).
  document.addEventListener("input", (e) => {
    if (!root() || !root().contains(e.target)) return;
    const el = e.target;
    if (el.dataset.tpl) {
      const d = draft();
      d.followup.templates[page.type][el.dataset.tpl] = el.value;
      $("#tplPreview").textContent = previewTemplate(d.followup.templates[page.type]);
      clearTimeout(page.timer);
      setSaved("");
      page.timer = setTimeout(() => commit("followup", d.followup), 600);
    }
  });
  // Remember where the cursor was, so a fill-in goes there.
  document.addEventListener("focusin", (e) => { if (e.target.dataset && e.target.dataset.tpl) page.field = e.target; });
  document.addEventListener("click", (e) => {
    if (!root() || !root().contains(e.target)) return;
    const mv = e.target.closest("[data-move]");
    if (mv) {
      const li = mv.closest("li"), list = li.closest("[data-order]").dataset.order, g = groupOf(list), d = draft();
      const arr = list.split(".").reduce((o, p) => o[p], d), i = arr.findIndex((x) => x.id === li.dataset.id), j = i + (mv.dataset.move === "up" ? -1 : 1);
      if (j < 0 || j >= arr.length) return;
      [arr[i], arr[j]] = [arr[j], arr[i]];
      const label = li.querySelector(".st-order-label").textContent;
      const focus = '[data-order="' + list + '"] li[data-id="' + li.dataset.id + '"] [data-move="' + (j === 0 ? "down" : j === arr.length - 1 ? "up" : mv.dataset.move) + '"]';
      commit(g, d[g], { redraw: true, focus, said: label + " moved to position " + (j + 1) + " of " + arr.length });
      return;
    }
    const rm = e.target.closest("[data-remove]");
    if (rm) {
      const key = rm.dataset.remove, g = groupOf(key), d = draft();
      put(d, key, key.split(".").reduce((o, p) => o[p], d).filter((x) => x !== rm.dataset.value));
      commit(g, d[g], { redraw: true, focus: "#add-" + key.replace(/\W/g, ""), said: rm.dataset.value + " removed" });
      return;
    }
    const fill = e.target.closest("[data-fill]");
    if (fill) {
      const f = page.field && document.contains(page.field) ? page.field : $("#tplBody"), tag = "{" + fill.dataset.fill + "}";
      const a = f.selectionStart ?? f.value.length, b = f.selectionEnd ?? f.value.length;
      f.value = f.value.slice(0, a) + tag + f.value.slice(b);
      f.focus();
      f.setSelectionRange(a + tag.length, a + tag.length);
      f.dispatchEvent(new Event("input", { bubbles: true }));
      return;
    }
    if (e.target.closest("[data-tpl-reset]")) {
      const d = draft();
      d.followup.templates[page.type] = JSON.parse(JSON.stringify(S.DEFAULTS.followup.templates[page.type]));
      commit("followup", d.followup, { redraw: true, focus: "#tplSubject", said: "Template reset" });
      return;
    }
    if (e.target.closest("[data-reset-menu]")) {
      const groupName = page.menu, defs = S.defaults()[groupName];
      if (groupName === "research") {  // the three privacy switches go back to off
        Object.assign(defs, { gongTranscripts: false, gongInAI: false, transcriptsInAI: false });
      }
      commit(groupName, defs, { redraw: true, focus: "[data-reset-menu]", said: "Back to the defaults" });
    }
  });
  document.addEventListener("submit", (e) => {
    const f = e.target.closest("[data-add]");
    if (f && root() && root().contains(f)) {
      e.preventDefault();
      const input = $("input", f), v = input.value.trim(), key = f.dataset.add, g = groupOf(key), d = draft();
      if (!v) { input.focus(); return; }
      const cur = key.split(".").reduce((o, p) => o[p], d);
      if (cur.some((x) => x.toLowerCase() === v.toLowerCase())) { setSaved("Already on the list", true); input.select(); return; }
      put(d, key, cur.concat(v));
      commit(g, d[g], { redraw: true, focus: "#" + input.id, said: v + " added" });
      return;
    }

  });
  // Drag to reorder (the up and down buttons do the same from the keyboard).
  let dragged = null;
  document.addEventListener("dragstart", (e) => {
    const li = e.target.closest && e.target.closest(".st-order-item");
    if (!li) return;
    dragged = li;
    li.classList.add("dragging");
    e.dataTransfer.effectAllowed = "move";
    try { e.dataTransfer.setData("text/plain", li.dataset.id); } catch (err) { /* some browsers need data to start a drag */ }
  });
  document.addEventListener("dragover", (e) => {
    const over = dragged && e.target.closest && e.target.closest(".st-order-item");
    if (!over || over === dragged || over.parentElement !== dragged.parentElement) return;
    e.preventDefault();
    const r = over.getBoundingClientRect();
    over.parentElement.insertBefore(dragged, e.clientY > r.top + r.height / 2 ? over.nextSibling : over);
  });
  document.addEventListener("dragend", () => {
    if (!dragged) return;
    const ol = dragged.parentElement, list = ol.dataset.order, g = groupOf(list), d = draft();
    const ids = $$("li", ol).map((li) => li.dataset.id), arr = list.split(".").reduce((o, p) => o[p], d);
    const sorted = ids.map((id) => arr.find((x) => x.id === id));
    put(d, list, sorted);
    const label = dragged.querySelector(".st-order-label").textContent, pos = ids.indexOf(dragged.dataset.id) + 1;
    dragged.classList.remove("dragging");
    dragged = null;
    commit(g, d[g], { redraw: true, said: label + " moved to position " + pos + " of " + ids.length });
  });

  // ---------- the avatar menu (top bar): Settings, the theme, Data ----------
  function meMenuHtml() {
    const dark = S.get().appearance.theme === "dark";
    // Who is signed in (your Google account), and a way to sign out: it revokes Overture's Google access and deletes the saved sign-in.
    const g = (window.MOAB_STATUS || {}).google || {}, signedIn = !DEMO && g.connected;
    const who = signedIn ? '<div class="me-who" role="presentation"><span class="me-who-l">Signed in with Google</span><span class="me-who-e">' + esc(g.email || "your Google account") + "</span></div>" : "";
    const out = signedIn ? '<div class="me-sep" role="separator"></div><button type="button" role="menuitem" data-disconnect>' + ic("logOut") + "<span>Sign out</span></button>" : "";
    return who + '<a role="menuitem" href="#/settings">' + ic("settings") + "<span>Settings</span></a>"
      + '<button type="button" role="menuitemcheckbox" aria-checked="' + dark + '" data-me-theme>' + ic(dark ? "sun" : "moon") + "<span>Dark theme</span></button>"
      + '<a role="menuitem" href="#/settings/appearance">' + ic("palette") + "<span>Appearance</span></a>"
      + '<a role="menuitem" href="#/settings/panel">' + ic("keyboard") + "<span>Keyboard shortcuts</span></a>"
      + '<a role="menuitem" href="#/data">' + ic("database") + "<span>Data</span></a>" + out;
  }
  function openMe(focusFirst) {
    const menu = $("#meMenu"), btn = $("#meBtn");
    if (!menu || !btn) return;
    menu.innerHTML = meMenuHtml();
    menu.hidden = false;
    btn.setAttribute("aria-expanded", "true");
    if (focusFirst) $("[role^=menuitem]", menu).focus();
  }
  function closeMe(focusBtn) {
    const menu = $("#meMenu"), btn = $("#meBtn");
    if (!menu || menu.hidden) return;
    menu.hidden = true;
    btn.setAttribute("aria-expanded", "false");
    if (focusBtn) btn.focus();
  }
  document.addEventListener("click", (e) => {
    const btn = e.target.closest("#meBtn");
    if (btn) { if ($("#meMenu").hidden) openMe(e.detail === 0); else closeMe(); return; }
    const t = e.target.closest("[data-me-theme]");
    if (t) {
      const a = Object.assign({}, S.get().appearance, { theme: S.get().appearance.theme === "dark" ? "light" : "dark" });
      S.save("appearance", a).then(() => { $("#meMenu").innerHTML = meMenuHtml(); $("[data-me-theme]").focus(); app().announce(a.theme === "dark" ? "Dark theme" : "Light theme"); })
        .catch((err) => app().announce(err.message));
      return;
    }
    if (e.target.closest("#meMenu a")) { closeMe(); return; }
    if (!e.target.closest("#meMenu")) closeMe();
  });
  document.addEventListener("keydown", (e) => {
    const menu = $("#meMenu");
    if (!menu || menu.hidden) {
      if (e.target.id === "meBtn" && e.key === "ArrowDown") { e.preventDefault(); openMe(true); }
      return;
    }
    const items = $$("[role^=menuitem]", menu), i = items.indexOf(document.activeElement);
    if (e.key === "Escape") { e.preventDefault(); closeMe(true); }
    else if (e.key === "ArrowDown") { e.preventDefault(); items[(i + 1) % items.length].focus(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); items[(i - 1 + items.length) % items.length].focus(); }
    else if (e.key === "Home") { e.preventDefault(); items[0].focus(); }
    else if (e.key === "End") { e.preventDefault(); items[items.length - 1].focus(); }
    else if (e.key === "Tab") closeMe();
  });

  window.MoabSettingsPage = { MENUS, render };
})();
