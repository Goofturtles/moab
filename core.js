// Overture core: data, checks and the agent itself, shared by the full app (app.js) and the in-call panel (panel.js).
// Real public data: Backstage adopters list, Backstage releases, Backstage security notices (data/snapshot.js).
// Three modes: "live" (server.py's data/live.js built window.OVERTURE_LIVE from your Google Calendar and Overture's records),
// "demo" (?demo=1, the made-up data in data/sample.js, clearly labelled) and "connect" (nothing connected yet: no calls).
(function () {
  "use strict";

  const SNAP = window.SNAPSHOT;
  const QS = new URLSearchParams(location.search);
  const MODE = QS.get("demo") === "1" ? "demo" : window.OVERTURE_LIVE ? "live" : "connect";
  const etToday = () => new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
  const D = MODE === "demo" ? window.SAMPLE : MODE === "live" ? window.OVERTURE_LIVE
    : { today: etToday(), invites: [], people: {}, companies: {}, papers: {}, currentSecurityPack: "", relationships: [], watch: [], me: null };
  ["people", "companies", "papers"].forEach((k) => { if (!D[k]) D[k] = {}; });
  ["invites", "relationships", "watch", "mentioned"].forEach((k) => { if (!D[k]) D[k] = []; });
  // A company row may arrive carrying only what Overture found on the web (its profile): give it the fields every page reads.
  Object.values(D.companies).forEach((c) => { if (c && typeof c === "object") { if (typeof c.status !== "string" || !c.status) c.status = "Prospect"; if (!Array.isArray(c.history)) c.history = []; } });
  if (!D.orgs || typeof D.orgs !== "object") D.orgs = {}; // GET /api/research's orgs[domain] = { status, note, profile }
  // Honest source tags: made-up data says so in demo mode; real data names where it came from.
  const SRC = MODE === "demo" ? { calendar: "Sample data", records: "Sample data", recordsList: "Sample records" }
    : { calendar: "Your calendar", records: "Overture records", recordsList: "Overture records" };
  // Who "you" are: Chris in the demo, the Google account's name when live.
  const meName = MODE === "demo" ? "Chris" : String((D.me && D.me.name) || "").trim();
  const ME = { name: meName || "You", first: meName ? meName.split(/\s+/)[0] : "", initial: (meName || "You").charAt(0).toUpperCase(), email: String((D.me && D.me.email) || "") };

  // ---------- small helpers ----------
  const $ = (sel, el) => (el || document).querySelector(sel);
  const $$ = (sel, el) => Array.from((el || document).querySelectorAll(sel));
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const plural = (n, one, many) => n + " " + (n === 1 ? one : many || one + "s");
  const initials = (name) => name.split(" ").map((w) => w[0]).join("").slice(0, 2).toUpperCase();
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const fmtDate = (s) => {
    const p = String(s).split("-").map(Number);
    return p.length === 3 ? MONTHS[p[1] - 1] + " " + p[2] + ", " + p[0] : MONTHS[p[1] - 1] + " " + p[0];
  };
  // "Tue Oct 20, 10:00 to 10:45 ET" -> parts.
  const splitWhen = (when) => {
    const m = String(when).match(/^(\w+) (\w+) (\d+), (.+)$/);
    return m ? { day: m[1], month: m[2], date: m[3], time: m[4], start: m[4].replace(/ to \S+/, "") } : { day: "", month: "", date: "", time: String(when), start: String(when) };
  };
  const NEW_TAB = '<span class="sr-only"> (opens in a new tab)</span>';
  // Storage can be blocked (private windows, the Meet iframe's partitioned storage): never let it break the page.
  const store = {
    get(k) { try { return JSON.parse(localStorage.getItem("centralize:" + k)); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem("centralize:" + k, JSON.stringify(v)); } catch (e) { /* ignore */ } },
  };

  // Lucide icon paths (ISC licence), drawn inline so the page has one icon family and no extra requests.
  const ICONS = {
    check: '<path d="M20 6 9 17l-5-5"/>',
    loader: '<path d="M21 12a9 9 0 1 1-6.219-8.56"/>',
    x: '<path d="M18 6 6 18M6 6l12 12"/>',
    minus: '<path d="M5 12h14"/>',
    plus: '<path d="M5 12h14M12 5v14"/>',
    link: '<path d="M15 3h6v6M10 14 21 3M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
    circleCheck: '<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>',
    circleAlert: '<circle cx="12" cy="12" r="10"/><path d="M12 8v4M12 16h.01"/>',
    search: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    bell: '<path d="M10.268 21a2 2 0 0 0 3.464 0"/><path d="M3.262 15.326A1 1 0 0 0 4 17h16a1 1 0 0 0 .74-1.673C19.41 13.956 18 12.499 18 8A6 6 0 0 0 6 8c0 4.499-1.411 5.956-2.738 7.326"/>',
    briefcase: '<path d="M16 20V4a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/><rect width="20" height="14" x="2" y="6" rx="2"/>',
    trend: '<path d="M22 7 13.5 15.5 8.5 10.5 2 17"/><path d="M16 7h6v6"/>',
    shield: '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/>',
    pencil: '<path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/><path d="m15 5 4 4"/>',
    rotate: '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>',
    chevron: '<path d="m9 18 6-6-6-6"/>',
    chevronDown: '<path d="m6 9 6 6 6-6"/>',
    play: '<path d="M6 3 20 12 6 21Z"/>',
    clock: '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
    home: '<path d="M15 21v-8a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1v8"/><path d="M3 10a2 2 0 0 1 .709-1.528l7-5.999a2 2 0 0 1 2.582 0l7 5.999A2 2 0 0 1 21 10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    calendar: '<path d="M8 2v4M16 2v4"/><rect width="18" height="18" x="3" y="4" rx="2"/><path d="M3 10h18"/>',
    network: '<rect x="16" y="16" width="6" height="6" rx="1"/><rect x="2" y="16" width="6" height="6" rx="1"/><rect x="9" y="2" width="6" height="6" rx="1"/><path d="M5 16v-3a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1v3M12 12V8"/>',
    building: '<rect width="16" height="20" x="4" y="2" rx="2"/><path d="M9 22v-4h6v4M8 6h.01M16 6h.01M12 6h.01M12 10h.01M12 14h.01M16 10h.01M16 14h.01M8 10h.01M8 14h.01"/>',
    settings: '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/>',
    video: '<path d="m16 13 5.223 3.482a.5.5 0 0 0 .777-.416V7.87a.5.5 0 0 0-.752-.432L16 10.5"/><rect x="2" y="6" width="14" height="12" rx="2"/>',
    panel: '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M15 3v18"/>',
    users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>',
    note: '<path d="M15 12H3M17 18H3M21 6H3"/>',
    arrowRight: '<path d="M5 12h14M12 5l7 7-7 7"/>',
    sparkle: '<path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0z"/>',
    command: '<path d="M15 6v12a3 3 0 1 0 3-3H6a3 3 0 1 0 3 3V6a3 3 0 1 0-3 3h12a3 3 0 1 0-3-3"/>',
    maximize: '<path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/>',
    fit: '<path d="M8 3H5a2 2 0 0 0-2 2v3M21 8V5a2 2 0 0 0-2-2h-3M3 16v3a2 2 0 0 0 2 2h3M16 21h3a2 2 0 0 0 2-2v-3"/>',
    handshake: '<path d="m11 17 2 2a1 1 0 1 0 3-3"/><path d="m14 14 2.5 2.5a1 1 0 1 0 3-3l-3.88-3.88a3 3 0 0 0-4.24 0l-.88.88a1 1 0 1 1-3-3l2.81-2.81a5.79 5.79 0 0 1 7.06-.87l.47.28a2 2 0 0 0 1.42.25L21 4"/><path d="m21 3 1 11h-2M3 3 2 14l6.5 6.5a1 1 0 1 0 3-3M3 4h8"/>',
  };
  // Each icon also gets "ic-<name>", so motion.css can animate it while its parent is hovered or focused.
  const ic = (name, cls) => '<svg class="ic ic-' + name + " " + (cls || "") + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + ICONS[name] + "</svg>";

  // ---------- faces, tints and tags (Asana-style) ----------
  // Soft tints, fixed per name, so a person or company has the same colour on the board, in lists and in tags.
  const TINTS = [["#d3f1ee", "#0b4541"], ["#dae6fa", "#103a6b"], ["#f9dbe8", "#67124a"], ["#ebdff9", "#3b1784"], ["#fbe3cc", "#642b04"], ["#d6eedf", "#0d4a2a"], ["#fad9dc", "#731212"], ["#e3e1fb", "#2e2783"]]; // same hues and order as SOLIDS
  function tint(name) {
    let h = 0;
    for (const ch of String(name)) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
    return TINTS[h % TINTS.length];
  }
  const emailByName = {};
  D.invites.forEach((i) => i.attendees.forEach((a) => { emailByName[a.name.toLowerCase()] = a.email; }));
  // You never get a stock face, only a dark monogram (Chris in the demo, your Google name when live).
  const isMe = (name) => {
    const n = String(name).trim().toLowerCase();
    return MODE === "demo" ? /^(you|chris)\b/.test(n) : n === "you" || n.startsWith("you ") || (!!meName && n === meName.toLowerCase());
  };
  function photoFor(p) {
    if (p.photo) return p.photo;
    const email = p.email || emailByName[String(p.name || "").toLowerCase()];
    return email && D.people[email] ? D.people[email].photo || "" : "";
  }
  // One avatar for everywhere: initials on a soft tint, the photo on top; if the photo fails, the initials show.
  function avatar(who, size) {
    const p = typeof who === "string" ? { name: who } : who || {};
    const name = String(p.name || p.label || "");
    const cls = "avatar" + (size ? " " + size : "");
    if (isMe(name)) return '<span class="' + cls + ' me" aria-hidden="true"><span class="avatar-ini">' + esc(ME.initial) + "</span></span>";
    const t = tint(name), photo = photoFor(p);
    return '<span class="' + cls + '" aria-hidden="true" style="background:' + t[0] + ";color:" + t[1] + '"><span class="avatar-ini">' + esc(initials(name)) + "</span>"
      + (photo ? '<img src="' + esc(photo) + '" alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer" onerror="this.remove()">' : "") + "</span>";
  }
  // Company letter tile on the company's tint (cls picks the size: co-tile-sm, co-head-tile, co-tile).
  // Asana project colours (aqua, blue, pink, purple, orange, green, red, indigo), fixed per company.
  const SOLIDS = ["#14a39a", "#3b7ddd", "#d6457f", "#9a55d6", "#e0710b", "#3f9466", "#d93a4e", "#6b61e3"];
  function solid(name) { let h = 0; for (const ch of String(name)) h = (h * 31 + ch.charCodeAt(0)) >>> 0; return SOLIDS[h % SOLIDS.length]; }
  const coTile = (name, cls) => '<span class="' + (cls || "co-tile-sm") + '" aria-hidden="true" style="background:' + solid(name) + ';color:#fff">' + esc(String(name).charAt(0).toUpperCase()) + "</span>";
  // Tag colour for a value: company status, severity, alert kind, after-call change kind, panel note kind.
  function tagFor(kind, v) {
    v = String(v || "");
    if (kind === "status") return /^Customer/.test(v) ? "tag-green" : /^Open deal/.test(v) ? "tag-blue" : /^New lead/.test(v) ? "tag-purple" : "tag-gray";
    if (kind === "severity") return { critical: "critical", high: "tag-red", medium: "tag-orange" }[v] || "tag-gray";
    if (kind === "alert") return v === "Security" ? "tag-red" : v === "Job change" ? "tag-purple" : "tag-teal";
    if (kind === "change") return { "Next step": "tag-green", People: "tag-blue", Papers: "tag-yellow", Deal: "tag-purple" }[v] || "tag-gray";
    if (kind === "note") return { Question: "tag-blue", Objection: "tag-orange", "Next step": "tag-green" }[v] || "tag-gray";
    return "tag-gray";
  }

  // Chris's own numbers (Oct 17): "maybe an hour a week in the beginning. Now five years later, 13, 15, 20 hours a week."
  const CHRIS = { startHours: 1, lowAt5: 13, highAt5: 20 };
  const ASSUME = { daysPerRelease: 1.5, daysPerSerious: 0.5 };
  const STATUS0 = window.OVERTURE_STATUS || null; // what data/live.js said about the server, if it answered
  const state = { adopters: SNAP.adopters, latest: SNAP.latestRelease, liveData: false, claudeOn: !!(STATUS0 && STATUS0.ai && STATUS0.ai.claude),
    server: !!STATUS0, google: STATUS0 ? STATUS0.google : { configured: false, connected: false, email: "" }, device: "checking",
    hubspot: (STATUS0 && STATUS0.hubspot) || { configured: false, connected: false }, gong: (STATUS0 && STATUS0.gong) || { configured: false, connected: false },
    granola: (STATUS0 && STATUS0.granola) || { configured: false, connected: false }, meetily: (STATUS0 && STATUS0.meetily) || { on: false, found: false },
    gongInAI: !!(MODE === "live" && D.settings && D.settings.gongInAI === true),
    gongTranscripts: !!(MODE === "live" && D.settings && D.settings.gongTranscripts === true),
    transcriptsInAI: !!(MODE === "live" && D.settings && D.settings.transcriptsInAI === true) };
  // ?live=0 keeps the saved public data, so a rehearsed demo shows the same numbers.
  const LIVE = new URLSearchParams(location.search).get("live") !== "0";
  // The Settings page's values (settings.js); null only if settings.js didn't load.
  const prefs = () => (window.OvertureSettings ? window.OvertureSettings.get() : null);

  // ---------- versions ----------
  const cleanVer = (v) => String(v == null ? "" : v).trim().replace(/^v/i, "");
  function parseVer(v) {
    const m = String(v || "").trim().match(/^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$/);
    return m ? [+m[1], +m[2], +m[3], m[4] || ""] : null;
  }
  function cmpVer(a, b) {
    for (let i = 0; i < 3; i++) if (a[i] !== b[i]) return a[i] - b[i];
    if (a[3] === b[3]) return 0;
    if (!a[3]) return 1;
    if (!b[3]) return -1;
    return a[3] < b[3] ? -1 : 1;
  }
  function satisfies(version, range) {
    const v = parseVer(version);
    if (!v || !range) return false;
    return range.split(",").every((part) => {
      const m = part.trim().match(/^(<=|>=|<|>|=)?\s*(\S+)$/);
      const r = m && parseVer(m[2]);
      if (!r) return false;
      const c = cmpVer(v, r);
      switch (m[1] || "=") {
        case "<": return c < 0;
        case "<=": return c <= 0;
        case ">": return c > 0;
        case ">=": return c >= 0;
        default: return c === 0;
      }
    });
  }

  // ---------- adopters list ----------
  const norm = (s) => String(s || "").toLowerCase().replace(/&/g, " and ")
    .replace(/\b(inc|ltd|llc|gmbh|plc|corp|corporation|limited)\b\.?/g, "")
    .replace(/[^a-z0-9]+/g, " ").trim();
  const SUFFIX = /\b(se|ag|group|nv|bv|sa|ab|co|company|holdings)\b/g;
  // Exact name first, then without company suffixes, then "every typed word is in the name" (so "Zalando" finds "Zalando SE").
  function findAdopter(name) {
    const n = norm(name);
    if (!n) return null;
    const bare = (s) => norm(s).replace(SUFFIX, " ").replace(/\s+/g, " ").trim();
    const words = bare(name).split(" ").filter(Boolean);
    const list = state.adopters;
    return list.find((a) => norm(a.org) === n)
      || list.find((a) => bare(a.org) === bare(name))
      || (words.length ? list.find((a) => {
        const o = " " + bare(a.org) + " ";
        return o.startsWith(" " + words[0] + " ") && words.every((w) => o.includes(" " + w + " "));
      }) : null)
      || null;
  }
  function parseAdopters(md) {
    const clean = (c) => c.replace(/\[([^\]]+)\]\([^)]*\)/g, "$1").replace(/<[^>]+>/g, "").replace(/\s+/g, " ").trim();
    const rows = [];
    md.split("\n").forEach((line) => {
      if (!line.startsWith("|") || /^\|[\s:|-]+\|?$/.test(line.trim())) return;
      const cells = line.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
      if (cells.length < 3 || cells[0].toLowerCase() === "organization") return;
      const org = clean(cells[0]);
      if (org) rows.push({ org, use: clean(cells[2]).slice(0, 400) });
    });
    return rows;
  }

  // ---------- network (always with a timeout, always with a fallback) ----------
  async function fetchTimeout(url, ms, opts) {
    const ctl = new AbortController();
    const t = setTimeout(() => ctl.abort(), ms);
    try { return await fetch(url, Object.assign({ signal: ctl.signal }, opts || {})); } finally { clearTimeout(t); }
  }
  async function refreshLive() {
    if (!LIVE) return;
    try {
      const [rel, adm] = await Promise.all([
        fetchTimeout("https://api.github.com/repos/backstage/backstage/releases/latest", 6000),
        fetchTimeout("https://raw.githubusercontent.com/backstage/backstage/master/ADOPTERS.md", 6000),
      ]);
      if (rel.ok) {
        const j = await rel.json();
        const v = parseVer(j.tag_name);
        if (v && cmpVer(v, parseVer(SNAP.latestRelease.version)) >= 0) state.latest = { version: j.tag_name.replace(/^v/, ""), date: j.published_at.slice(0, 10) };
      }
      if (adm.ok) {
        const list = parseAdopters(await adm.text());
        if (list.length > 50) state.adopters = list;
      }
      state.liveData = rel.ok && adm.ok;
    } catch (e) { state.liveData = false; }
  }
  // Resolves once we know whether the local server has a Claude key (false on any failure, including file://).
  const claudeChecked = (async () => {
    try {
      const r = await fetchTimeout("/api/status", 3000);
      const j = r.ok ? await r.json() : {};
      state.claudeOn = j.claude === true;
      if (j.google) { state.google = j.google; state.server = true; }
      if (j.hubspot) state.hubspot = j.hubspot;
      if (j.gong) state.gong = j.gong;
      if (j.granola) state.granola = j.granola;
      if (j.meetily) state.meetily = j.meetily;
    } catch (e) { state.claudeOn = false; }
  })();

  // ---------- Overture's own records (server.py keeps them in .data/records.json) ----------
  async function saveRecord(kind, body, method) {
    let r;
    try {
      r = await fetchTimeout("/api/records/" + kind, 10000, { method: method || "PUT", headers: { "Content-Type": "application/json", "X-OVERTURE": "1" }, body: JSON.stringify(body) });
    } catch (e) { throw new Error("Couldn't reach Overture's server. Is server.py running?"); }
    let j = {};
    try { j = await r.json(); } catch (e) { /* no body */ }
    if (!r.ok) throw new Error(j.error ? "Not saved: " + j.error : "Not saved (" + r.status + ")");
    return j.saved;
  }

  // ---------- Ask Overture: Claude (server key) -> on-device AI (Chrome's Prompt API) -> null (the page falls back to rules) ----------
  async function deviceAvailability() {
    const LM = globalThis.LanguageModel;
    if (!LM || typeof LM.availability !== "function") return "unavailable";
    try { return String(await LM.availability()); } catch (e) { return "unavailable"; }
  }
  const deviceChecked = deviceAvailability().then((a) => { state.device = a; return a; });
  const ASK_SYS = "You are Overture, a call-prep assistant for a salesperson. Answer using only the facts in the JSON. "
    + "If the facts don't answer the question, say so in one line. Plain text, at most three short sentences.";
  // A small, plain summary of what Overture knows, for the on-device model (its context window is small).
  function askFacts(callId) {
    const call = callId ? inviteById(callId) : null;
    const person = (a) => { const p = D.people[a.email] || {}; return [a.name, p.title, p.note].filter(Boolean).join(", "); };
    const facts = {
      today: D.today, data: MODE === "demo" ? "made-up sample data" : "the user's calendar and Overture's records",
      thisCall: call ? { title: call.title, when: call.when, company: call.company, invite: String(call.notes || "").slice(0, 600), people: call.attendees.map(person) } : null,
      calls: D.invites.slice(0, 12).map((i) => ({ title: i.title, company: i.company, when: i.when, people: i.attendees.map(person) })),
      companies: Object.entries(D.companies).slice(0, 20).map(([n, c]) => ({ name: n, status: c.status, engineers: c.engineers || null, notes: String(c.notes || "").slice(0, 300) })),
      alerts: D.watch.slice(0, 8).map((w) => w.title + ": " + w.text),
      latestBackstage: state.latest.version,
    };
    return JSON.stringify(facts).slice(0, 7000);
  }
  async function askAI(question, callId) {
    if (MODE === "live" && state.claudeOn) {
      try {
        const r = await fetchTimeout("/api/ask", 25000, { method: "POST", headers: { "Content-Type": "application/json", "X-OVERTURE": "1" }, body: JSON.stringify(callId ? { question, callId } : { question }) });
        const j = await r.json();
        if (r.ok && j.text) return { text: j.text, source: "claude" };
      } catch (e) { /* fall through to the device */ }
    }
    if ((await deviceChecked) === "available") {
      let s = null;
      try {
        s = await globalThis.LanguageModel.create({ initialPrompts: [{ role: "system", content: ASK_SYS }] });
        const out = await Promise.race([s.prompt("Facts (JSON):\n" + askFacts(callId) + "\n\nQuestion: " + question), wait(30000).then(() => "")]);
        if (String(out || "").trim()) return { text: String(out).trim(), source: "device" };
      } catch (e) { /* fall through to rules */ } finally { try { if (s && s.destroy) s.destroy(); } catch (e) { /* ignore */ } }
    }
    return null;
  }

  // ---------- the checks ----------
  function readVersionFile(text) {
    if (!text || !text.trim()) return null;
    let j;
    try { j = JSON.parse(text); } catch (e) {
      const m = text.match(/(\d+\.\d+\.\d+)/);
      return m ? { version: m[1], packages: null } : null;
    }
    if (!j || typeof j !== "object") return null;
    const deps = Object.assign({}, j.dependencies || {}, j.devDependencies || {});
    const pk = {};
    Object.keys(deps).forEach((k) => {
      // A range like ^1.2.0 is read as its lowest version, so this can over-count a little.
      if (k.startsWith("@backstage/")) pk[k] = String(deps[k]).replace(/^[\^~>=<\s]+/, "");
    });
    // A package.json "version" is their app's own version, not the Backstage release, so it is ignored here.
    if (Object.keys(pk).length) return { version: null, packages: pk };
    if (j.name || j.dependencies || j.devDependencies || j.peerDependencies) return null; // a package.json with no Backstage in it
    const v = cleanVer(j.version);
    return parseVer(v) ? { version: v, packages: null } : null;
  }

  async function packagesFor(version) {
    version = cleanVer(version);
    if (SNAP.manifests[version]) return SNAP.manifests[version];
    let r;
    try {
      r = await fetchTimeout("https://versions.backstage.io/v1/releases/" + encodeURIComponent(version) + "/manifest.json", 8000);
    } catch (e) { throw new Error("Couldn't reach versions.backstage.io to look up " + version); }
    if (!r.ok) throw new Error("Backstage has no release called " + version);
    const j = await r.json();
    const pk = {};
    (j.packages || []).forEach((p) => { pk[p.name] = p.version; });
    return pk;
  }

  // "Serious" means critical + high everywhere.
  function upgradeBill(packages, fromVersion, since) {
    const latest = state.latest;
    const from = parseVer(fromVersion);
    const to = parseVer(latest.version);
    const behind = from && to && from[0] === to[0] ? Math.max(0, to[1] - from[1]) : null;
    const open = [];
    SNAP.advisories.forEach((a) => {
      const hits = a.vulns.filter((v) => packages[v.pkg] && satisfies(packages[v.pkg], v.range));
      if (hits.length) open.push(Object.assign({}, a, { hits }));
    });
    const sev = { critical: 0, high: 0, medium: 0, low: 0 };
    open.forEach((a) => { sev[a.severity] = (sev[a.severity] || 0) + 1; });
    const serious = sev.critical + sev.high;
    const order = { critical: 0, high: 1, medium: 2, low: 3 };
    open.sort((a, b) => (order[a.severity] ?? 4) - (order[b.severity] ?? 4) || (a.published < b.published ? 1 : -1));
    const days = behind == null ? null : Math.round(behind * ASSUME.daysPerRelease + serious * ASSUME.daysPerSerious);
    const years = since ? Math.max(0, +D.today.slice(0, 4) - since) : null;
    const hours = years == null ? null : years < 1 ? { years, low: CHRIS.startHours, high: CHRIS.startHours } : {
      years,
      low: Math.round(Math.min(CHRIS.lowAt5, CHRIS.startHours + ((CHRIS.lowAt5 - CHRIS.startHours) * years) / 5)),
      high: Math.round(Math.min(CHRIS.highAt5, CHRIS.startHours + ((CHRIS.highAt5 - CHRIS.startHours) * years) / 5)),
    };
    return { behind, open, sev, serious, days, hours, years, from: fromVersion || null, to: latest.version, toDate: latest.date };
  }

  function monthsSince(ym) {
    const [y, m] = ym.split("-").map(Number);
    const [ty, tm] = D.today.split("-").map(Number);
    return (ty - y) * 12 + (tm - m);
  }
  function tenure(ym) {
    if (!ym) return "Start date unknown";
    const n = monthsSince(ym);
    if (n < 1) return "Joined this month";
    if (n < 12) return plural(n, "month") + " in the job";
    return plural(Math.floor(n / 12), "year") + " in the job";
  }

  // What the agent found about one person. lead = the one fact that matters most.
  function personFacts(p) {
    let lead = null;
    let quote = null;
    if (p.previous) {
      const ad = findAdopter(p.previous);
      const prev = D.companies[p.previous];
      if (ad) { lead = { text: "Came from " + ad.org + ", which uses Backstage.", tail: "They may already know it.", src: "pub" }; quote = ad.use; }
      else if (prev && prev.customer) lead = { text: "Came from " + p.previous + ", a Spotify customer.", tail: "Ask how they used it there.", src: "sample" };
      else if (prev && /open deal/i.test(prev.status || "")) lead = { text: "Came from " + p.previous + ", where you have an open deal.", tail: "They may still know your contacts there.", src: "sample" };
    }
    const isNew = !!(p.startedAt && monthsSince(p.startedAt) < 6);
    return { lead, quote, isNew, unknown: !p.known };
  }

  const RIVALS = [
    { key: /\bport\b/i, name: "Port", sayBack: true,
      facts: ["Publishes its prices: free up to 15 seats, $30 a seat a month up to 50 seats, $40 up to 200 seats."],
      todo: "Be ready for Port: $30 a seat a month up to 50 seats.",
      source: { label: "port.io/pricing", url: "https://www.port.io/pricing" } },
    { key: /roadie/i, name: "Roadie", sayBack: true,
      facts: ["Sells hosted Backstage at $24 per developer a month for 50 to 150 developers."],
      todo: "Be ready for Roadie: $24 per developer a month.",
      source: { label: "roadie.io/pricing", url: "https://roadie.io/pricing/" } },
    { key: /launchdarkly/i, name: "LaunchDarkly", sayBack: false,
      facts: ["A feature-flag tool they use today. Ask what they pay for it and what they can't measure with it."],
      todo: null, source: null },
  ];
  const PORTAL_POINTS = "Portal is built on Backstage, so what they built moves over, and Spotify's own team does the move. That also makes it the most extensible option.";

  function guessProduct(ctx) {
    const text = (ctx.invite.title + " " + ctx.invite.notes).toLowerCase();
    const portal = { name: "Portal", score: 0, why: [] };
    const conf = { name: "Confidence", score: 0, why: [] };
    const xirp = { name: "Xirp", score: 0, why: [] };
    if (ctx.runsBackstage) { portal.score += 3; portal.why.push("They already run Backstage themselves."); }
    if (ctx.companyAdopter) { portal.score += 1; portal.why.push("They are on the public Backstage adopters list."); }
    if (/upgrade|maintain|backstage/.test(text)) { portal.score += 1; portal.why.push("The invite talks about keeping Backstage running."); }
    if (/a\/b|experiment|feature flag|launchdarkly|optimizely|statsig/.test(text)) { conf.score += 3; conf.why.push("They run experiments and use feature flags."); }
    if (/claude|codex|copilot|cursor|ai agent|agents|ai coding/.test(text)) { xirp.score += 3; xirp.why.push("Their engineers already use AI coding agents every day."); }
    return [portal, conf, xirp].sort((a, b) => b.score - a.score);
  }

  // Papers: status for "History and papers", action (if any) for "Before the call".
  function paperStatus(name) {
    if (MODE !== "demo" && !D.papers[name]) return []; // Overture doesn't track papers yet: say nothing rather than guess
    const p = D.papers[name] || {};
    const out = [];
    if (!p.nda || !p.nda.signed) out.push({ key: "NDA", ok: false, text: "Not signed yet.", todo: "Send an NDA before sharing the roadmap." });
    else out.push({ key: "NDA", ok: true, text: "Signed " + fmtDate(p.nda.date) + " in " + p.nda.where + "." });
    const cur = D.currentSecurityPack;
    if (!p.securityPack) out.push({ key: "Security pack", ok: false, text: "None sent yet.", todo: "Send security pack " + cur + "." });
    else if (p.securityPack.sent === cur) out.push({ key: "Security pack", ok: true, text: cur + " sent " + fmtDate(p.securityPack.sentOn) + ". This is the current one." });
    else out.push({ key: "Security pack", ok: false, text: p.securityPack.sent + " sent " + fmtDate(p.securityPack.sentOn) + ". The current one is " + cur + ".",
      todo: "Send security pack " + cur + ". They only have " + p.securityPack.sent + " (sent " + fmtDate(p.securityPack.sentOn) + ")." });
    return out;
  }

  const inviteById = (id) => D.invites.find((i) => i.id === id);
  const alertsFor = (id) => D.watch.filter((w) => w.callId === id && alertOn(w.kind));

  // Every alert the agent raised: the sample job-change / come-back alerts plus real new security notices.
  // Settings > Alert rules picks which signals make alerts and how serious a security notice must be.
  const ALERT_SIGNAL = { "Job change": "jobChanges", "New person": "newInvitees", "First meeting": "newInvitees", "Stage change": "hubspotStages", Mentioned: "mentioned", Security: "security", "New release": "release" };
  const alertOn = (kind) => { const p = prefs(), sig = ALERT_SIGNAL[kind]; return !p || !sig || p.alerts.signals[sig] !== false; };
  const shortDate = (iso) => { const n = String(iso).split("-").map(Number); return MONTHS[n[1] - 1] + " " + n[2]; };
  function allAlerts() {
    const today = Date.parse(D.today), level = prefs() ? prefs().alerts.security : "all";
    const recent = SNAP.advisories.filter((a) => today - Date.parse(a.published) <= 30 * 864e5);
    const serious = recent.filter((a) => a.severity === "high" || a.severity === "critical").length;
    const icon = { "Job change": "briefcase", "First meeting": "handshake", "New person": "users", Mentioned: "users", "Stage change": "trend" };
    const items = D.watch.filter((w) => alertOn(w.kind)).map((w, i) => ({ id: "w" + i, icon: icon[w.kind] || "trend", kind: w.kind, title: w.title,
      date: w.date, text: w.text, src: w.kind === "New person" ? SRC.records : w.kind === "Stage change" ? "HubSpot" : SRC.calendar, callId: w.callId || null, person: w.person || "" }));
    // People mentioned on a call (Overture's saved connections; the sample's in the demo).
    if (alertOn("Mentioned")) {
      (D.mentioned || []).filter((m) => m.type === "person" && inviteById(m.callId)).slice(0, 6).forEach((m) => {
        const inv = inviteById(m.callId);
        items.push({ id: "m-" + m.id, icon: "users", kind: "Mentioned", title: "Mentioned on the " + inv.company + " call: " + m.label, date: shortDate(D.today),
          text: m.label + (m.sub ? ", " + String(m.sub).replace(/^Mentioned · /, "") : "") + ", came up on the call. Overture added them to the People map.",
          src: SRC.records, callId: inv.id, person: m.label });
      });
    }
    const shown = level === "critical" ? recent.filter((a) => a.severity === "critical") : level === "high" ? recent.filter((a) => a.severity === "high" || a.severity === "critical") : recent;
    if (shown.length && alertOn("Security")) {
      const what = level === "critical" ? "new critical security notice" : level === "high" ? "new high or critical security notice" : "new security notice";
      items.push({ id: "security", icon: "shield", kind: "Security", title: plural(shown.length, what) + " in 30 days",
        date: shortDate(shown[0].published), src: "Public data", callId: null,
        text: (level === "all" ? serious + " of them are high or critical. " : "") + "Every company on an older Backstage is exposed, which is a good reason to call them." });
    }
    // A Backstage release from the last 14 days: everyone on an older version just fell one further behind.
    const rel = state.latest;
    if (alertOn("New release") && rel && rel.date && today - Date.parse(rel.date) <= 14 * 864e5 && today >= Date.parse(rel.date)) {
      items.push({ id: "release", icon: "tag", kind: "New release", title: "Backstage " + rel.version + " is out", date: shortDate(rel.date), src: "Public data", callId: null,
        text: "Backstage " + rel.version + " came out on " + fmtDate(rel.date) + ". Every team on an older version is now one more release behind." });
    }
    return items;
  }

  // ---------- account priorities (Settings > Account priorities): a Hot / Warm / Cold badge and a sort order ----------
  function priority(company) {
    const p = prefs();
    if (!p) return { score: 0, level: "cold", why: [] };
    const pr = p.priorities, r = pr.rules, c = D.companies[company] || {}, why = [];
    let score = 0;
    const add = (hit, w, text) => { if (hit && w > 0) { score += w; why.push(text); } };
    add(pr.targets.some((t) => norm(t) === norm(company)), pr.target, "Target account");
    add(r.engineers.on && +(c.engineers || 0) >= r.engineers.min, r.engineers.weight, "At least " + r.engineers.min + " engineers");
    add(r.adopter.on && !!findAdopter(company), r.adopter.weight, "On the Backstage adopters list");
    add(r.deal.on && /^Open deal/.test(c.status || ""), r.deal.weight, "Open deal");
    add(r.alert.on && D.watch.some((w) => alertOn(w.kind) && inviteById(w.callId) && inviteById(w.callId).company === company), r.alert.weight, "Recent alert");
    add(r.customer.on && (!!c.customer || /^Customer/.test(c.status || "")), r.customer.weight, "Customer");
    return { score, level: score >= pr.hot ? "hot" : score >= pr.warm ? "warm" : "cold", why };
  }
  const PRIO = { hot: ["Hot", "tag-red"], warm: ["Warm", "tag-orange"], cold: ["Cold", "tag-blue"] };
  function priorityBadge(company) {
    const pr = priority(company), [label, tag] = PRIO[pr.level];
    const why = pr.why.length ? pr.why.join(", ") : "No priority rules match";
    return '<span class="pill prio ' + tag + '" title="' + esc(label + ": " + why + " (score " + pr.score + ")") + '">' + label + '<span class="sr-only"> priority: ' + esc(why) + "</span></span>";
  }
  // Sort by priority (hot first) when that setting is on; ties keep their order.
  function byPriority(list, companyOf) {
    const p = prefs();
    if (!p || !p.priorities.sort) return list.slice();
    return list.map((x, i) => ({ x, i, s: priority(companyOf(x)).score })).sort((a, b) => b.s - a.s || a.i - b.i).map((o) => o.x);
  }

  // ---------- the agent ----------
  const STEP_DEFS = [
    ["invite", "Read the calendar invite", "invite"],
    ["people", "Look up everyone invited", "people"],
    ["adopters", "Check the public adopters list", "backstage"],
    ["upgrade", "Work out their upgrade bill", "bill"],
    ["history", "Check Spotify's history with them", "history"],
    ["papers", "Check the signed papers", "history"],
    ["rivals", "Check for rivals", "rivals"],
    ["product", "Guess which product fits", "fit"],
    ["write", "Write the brief", null],
  ];

  // Runs the nine checks for one call. onStep(states) repaints after each change; pace = ms per step for the visible run.
  async function runChecks(invite, inputs, onStep, pace) {
    const ctx = { invite: Object.assign({}, invite, { versionFile: inputs.versionFile, backstageSince: inputs.since }), people: [], states: {}, done: false };
    const states = ctx.states;
    const paint = () => { if (onStep) onStep(states); };
    const step = async (sid, fn) => {
      states[sid] = { state: "run" }; paint();
      if (pace) await wait(pace);
      try {
        const r = await fn();
        states[sid] = r && r.skip ? { state: "skip", detail: r.skip } : { state: "done", detail: r };
      } catch (e) { states[sid] = { state: "fail", detail: esc(e.message) }; }
      paint();
    };
    await step("invite", () => esc(plural(ctx.invite.attendees.length, "person", "people") + " from " + invite.company + "."));
    await step("people", () => {
      ctx.people = ctx.invite.attendees.map((a) => {
        const rec = D.people[a.email] || {};
        return Object.assign({ name: a.name, email: a.email, title: "Title unknown", startedAt: null, previous: "", known: false, note: "" }, rec, { title: rec.title || "Title unknown" });
      });
      ctx.people.forEach((p) => { p.facts = personFacts(p); });
      const flagged = ctx.people.filter((p) => p.facts.lead || p.facts.isNew || personInfo(p.email).profile).length;
      return esc(flagged + " of " + ctx.people.length + " have something worth knowing.");
    });
    await step("adopters", () => {
      ctx.companyAdopter = findAdopter(invite.company);
      return esc(ctx.companyAdopter ? "They are on the list." : "Not on the list of " + state.adopters.length + " companies.");
    });
    await step("upgrade", async () => {
      const vf = readVersionFile(ctx.invite.versionFile);
      if (!vf) { ctx.runsBackstage = false; return { skip: "No backstage.json, so nothing to check." }; }
      ctx.runsBackstage = true;
      ctx.version = vf.version;
      try { ctx.packages = vf.packages || (await packagesFor(vf.version)); } catch (e) { ctx.billError = e.message; throw e; }
      ctx.bill = upgradeBill(ctx.packages, ctx.version, ctx.invite.backstageSince);
      const b = ctx.bill;
      return esc((b.behind != null ? plural(b.behind, "release") + " behind, " : "") + plural(b.serious, "serious notice") + " open.");
    });
    await step("history", () => {
      ctx.company = D.companies[invite.company] || null;
      return esc(ctx.company ? ctx.company.status + "." : "No history with Spotify.");
    });
    await step("papers", () => {
      ctx.papers = paperStatus(invite.company);
      if (!ctx.papers.length) return { skip: "No papers in Overture's records." };
      const missing = ctx.papers.filter((p) => !p.ok).length;
      return esc(missing ? plural(missing, "thing") + " to sort out." : "All in order.");
    });
    await step("rivals", () => {
      ctx.rivals = RIVALS.filter((r) => r.key.test(ctx.invite.notes));
      return ctx.rivals.length ? esc("Mentioned: " + ctx.rivals.map((r) => r.name).join(", ") + ".") : { skip: "None mentioned." };
    });
    await step("product", () => {
      ctx.products = guessProduct(ctx);
      return esc(ctx.products[0].score > 0 ? "Most likely " + ctx.products[0].name + "." : "No clear fit yet.");
    });
    await step("write", async () => {
      ctx.opener = openingLine(ctx);
      ctx.todos = todoList(ctx);
      await claudeChecked;
      return state.claudeOn ? "Written with built-in rules. Claude is adding a summary." : "Written with built-in rules.";
    });
    ctx.done = true;
    return ctx;
  }

  // The opener: one fact and one question, said in the tone picked in Settings > Brief builder (direct, warm or curious).
  function openingLine(ctx, tone) {
    tone = tone || (prefs() ? prefs().brief.tone : "direct");
    const top = ctx.products[0];
    const b = ctx.bill;
    let fact = "", ask = "What made you take this call now?";
    if (b && b.behind != null) {
      const h = b.hours;
      fact = "You've been running Backstage yourselves" + (h && h.years >= 1 ? " for about " + plural(h.years, "year") : "")
        + ", and you're " + plural(b.behind, "release") + " behind with " + plural(b.serious, "serious security notice") + " open.";
      if (h && h.years >= 1) { fact += " Teams that have run it that long often spend " + h.low + " to " + h.high + " hours a week just keeping it running."; ask = "What would your team ship with that time back?"; }
      else ask = "What would it take your team to catch up?";
    } else if (top.name === "Xirp" && top.score > 0) { fact = "Your engineers already use AI coding agents every day."; ask = "How do those agents know who owns what, and what was decided before?"; }
    else if (top.name === "Confidence" && top.score > 0) { fact = "You already run A/B tests."; ask = "How do you decide when a test result is real, and who has to sign off before you ship it?"; }
    const low = (s) => s.charAt(0).toLowerCase() + s.slice(1);
    if (tone === "warm") return "Thanks for making the time today. " + (fact ? "From what I've read, " + low(fact) + " " : "") + ask;
    if (tone === "curious") return fact ? ask + " I ask because " + low(fact) : "I'm curious: " + low(ask);
    return (fact ? fact + " " : "") + ask;
  }

  // Real to-dos only (papers to send, rivals to be ready for). Who the guests are is Overture's job: its research saves itself.
  function todoList(ctx) {
    const out = ctx.papers.filter((p) => p.todo).map((p) => ({ text: p.todo }));
    ctx.rivals.filter((r) => r.todo).forEach((r) => out.push({ text: r.todo, link: { href: "#rivals", label: "Rival notes" }, src: "Public price" }));
    return out;
  }

  function factsFor(ctx) {
    const b = ctx.bill;
    return {
      call: { title: ctx.invite.title, when: ctx.invite.when, company: ctx.invite.company, notes: ctx.invite.notes },
      people: ctx.people.map((p) => {
        const pr = personInfo(p.email).profile;
        return Object.assign({ name: p.name, title: p.title, tenure: tenure(p.startedAt), previous: p.previous, note: p.note,
          keyFact: p.facts.lead ? p.facts.lead.text + " [" + p.facts.lead.src + "]" : null, newInJob: p.facts.isNew, inSpotifyRecords: !p.facts.unknown },
          pr ? { profile: profileFacts(pr) } : {});
      }),
      company: ctx.company ? Object.assign({ source: TAG.records }, ctx.company, { profile: undefined }) : null,
      companyProfile: orgFacts(orgInfo(ctx.invite.company).profile),
      sinceLastCall: alertsFor(ctx.invite.id).map((w) => w.text + " [" + TAG.calendar + "]"),
      backstage: b ? {
        source: "public", version: b.from, latest: b.to, releasesBehind: b.behind, seriousNotices: b.serious,
        noticesBySeverity: b.sev, hoursPerWeekRange: b.hours,
        worstNotices: b.open.slice(0, 3).map((a) => a.severity + ": " + a.summary),
      } : null,
      onAdoptersList: ctx.companyAdopter ? ctx.companyAdopter.use : false,
      papers: ctx.papers.map((p) => p.key + ": " + p.text + " [" + TAG.records + "]"),
      toDoBeforeCall: ctx.todos.map((t) => t.text),
      rivals: ctx.rivals.map((r) => r.name + ": " + r.facts.join(" ")),
      productGuess: ctx.products.map((p) => ({ product: p.name, score: p.score, why: p.why })),
      // Gong's notes only go to Claude when "Use Gong notes in AI answers" is on (the server drops them otherwise too).
      ...(state.gongInAI && gongFor(ctx.invite.company) ? { gong: gongFor(ctx.invite.company) } : {}),
    };
  }

  const TAG = MODE === "demo" ? { calendar: "sample", records: "sample" } : { calendar: "user's calendar", records: "Overture records" };
  // Claude's optional summary. Returns { text } or { error }.
  async function askClaude(ctx) {
    try {
      const r = await fetchTimeout("/api/brief", 25000, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(factsFor(ctx)),
      });
      const j = await r.json();
      return r.ok && j.text ? { text: j.text } : { error: j.error || "Claude did not answer" };
    } catch (e) { return { error: "Claude did not answer in time" }; }
  }

  // ---------- HubSpot and Gong (live mode; server.py fetches them, the page only shows them) ----------
  // Everything from HubSpot and Gong is escaped; the only link is Gong's own, and it must be http or https.
  const gongFor = (company) => (MODE === "live" && D.gong && D.gong[company]) || null;
  const duration = (s) => { const m = Math.round((+s || 0) / 60); return m >= 60 ? Math.floor(m / 60) + " h " + (m % 60 ? (m % 60) + " min" : "") : m + " min"; };
  function gongHtml(g) {
    if (!g) return "";
    const href = safeHref(g.url);
    const meta = [g.date ? fmtDate(g.date) : "", g.duration ? duration(g.duration).trim() : "", g.count > 1 ? plural(g.count, "call") + " in 180 days" : ""].filter(Boolean);
    let h = '<div class="gong-call"><p class="gong-title"><strong>' + esc(g.title) + "</strong></p>"
      + (meta.length ? '<p class="gong-meta">' + esc(meta.join(" · ")) + "</p>" : "");
    if (g.brief) h += '<p class="gong-brief">' + esc(g.brief) + "</p>";
    if (g.keyPoints && g.keyPoints.length) h += '<p class="gong-cap">Key points</p><ul class="gong-points" role="list">' + g.keyPoints.map((k) => "<li>" + esc(k) + "</li>").join("") + "</ul>";
    if (g.topics && g.topics.length) h += '<p class="gong-cap">Topics</p><p class="gong-tags">' + g.topics.map((t) => '<span class="pill tag-gray">' + esc(t) + "</span>").join("") + "</p>";
    if (g.trackers && g.trackers.length) h += '<p class="gong-cap">Trackers</p><p class="gong-tags">' + g.trackers.map((t) => '<span class="pill tag-purple">' + esc(t.name) + (t.count > 1 ? " × " + esc(t.count) : "") + "</span>").join("") + "</p>";
    if (!g.brief && !(g.keyPoints || []).length) h += '<p class="gong-meta">Gong has no summary for this call yet.</p>';
    if (href) h += '<p class="gong-open"><a href="' + esc(href) + '" target="_blank" rel="noopener noreferrer">Open the call in Gong' + ic("link", "ext") + NEW_TAB + "</a></p>";
    return h + "</div>";
  }
  const money = (n) => (n == null || n === "" ? "" : Number(n).toLocaleString("en-US", { maximumFractionDigits: 0 }) + (D.currency ? " " + D.currency : ""));
  async function postJson(url, body, timeout) {
    let r;
    try {
      r = await fetchTimeout(url, timeout || 30000, { method: "POST", headers: { "Content-Type": "application/json", "X-OVERTURE": "1" }, body: JSON.stringify(body) });
    } catch (e) { throw new Error("Couldn't reach Overture's server. Is server.py running?"); }
    let j = {};
    try { j = await r.json(); } catch (e) { /* no body */ }
    if (!r.ok) throw new Error(j.error || "Overture's server answered " + r.status);
    return j;
  }
  // What "Save to HubSpot" would write (nothing is written), then the write itself, only on the button press.
  // planId ties the write to the preview you saw: if HubSpot changed since, the server says so (409) and writes nothing.
  const hubspotPlan = (callId, note, titles) => postJson("/api/hubspot/save", { callId, note, titles });
  const hubspotSave = (callId, note, titles, planId) => postJson("/api/hubspot/save", { callId, note, titles, planId, confirm: true });

  // ---------- invitee research (server.py looks new guests up in the background) ----------
  // Everything here came from the web or the calendar: it is escaped, and links must be http or https.
  const RELATION = { employee: "Employee", contractor: "Contractor or agency", partner: "Partner", investor: "Investor or board", customer: "Customer", other: "Other" };
  const safeHref = (u) => { try { const x = new URL(String(u)); return x.protocol === "https:" || x.protocol === "http:" ? x.href : ""; } catch (e) { return ""; } };
  // opts: { edit: show the Edit button that opens the person form, editHref: link to that form instead, actions: show buttons }
  function researchHtml(p, opts) {
    const r = p && p.research;
    if (!r || (MODE !== "live" && MODE !== "demo")) return "";
    opts = opts || {};
    const local = r.local || {};
    let h = "";
    // No name on the invite: say so, and say when the name Overture used came from their work email.
    if ((r.nameFrom === "email" || r.nameFrom === "event") && r.nameUsed) h += '<p class="rs-note">No name on the invite. Using the name from ' + (r.nameFrom === "event" ? "the event description" : "their email") + ": <strong>" + esc(r.nameUsed) + "</strong>.</p>";
    if (r.status === "notfound") h += '<p class="rs-line"><span class="pill tag-gray">Can\'t find this person</span></p>';
    if (r.status === "pending") h += '<p class="rs-line rs-wait">' + ic("search") + "<span>Researching…</span></p>";
    else if (r.status === "done") {
      const facts = [RELATION[r.relationship], r.team, r.seniority ? r.seniority.charAt(0).toUpperCase() + r.seniority.slice(1) : "", r.tenure ? r.tenure + " there" : ""].filter(Boolean);
      const auto = r.found === "auto";
      h += '<p class="rs-line">' + (auto ? '<span class="pill tag-teal">Found automatically</span>' : "") + (MODE === "demo" ? '<span class="src sample">Sample</span>' : "")
        + "<span>" + esc(facts.length ? facts.join(" · ") : "Relationship unknown") + "</span></p>";
      // With a profile, its numbered sources sit under each fact instead.
      const prof = cleanProfile(r.profile, false);
      const links = prof && !prof.empty ? [] : (r.sources || []).map((s) => ({ href: safeHref(s.url), label: s.label })).filter((s) => s.href);
      if (links.length) h += '<p class="rs-src">' + (links.length > 1 ? "Sources: " : "Source: ") + links.map((s) => '<a href="' + esc(s.href) + '" target="_blank" rel="noopener noreferrer">' + esc(s.label || new URL(s.href).hostname) + ic("link", "ext") + NEW_TAB + "</a>").join(" · ") + "</p>";
      if (auto && opts.actions) {
        const edit = opts.edit ? '<button type="button" class="btn ghost sm" data-edit-person="' + esc(p.email) + '" aria-label="' + esc("Edit " + p.name + "'s title and note") + '">' + ic("pencil") + "Edit</button>"
          : opts.editHref ? '<a class="btn ghost sm" href="' + esc(opts.editHref) + '" target="_blank" rel="noopener">' + ic("pencil") + "Edit" + NEW_TAB + "</a>" : "";
        h += '<p class="rs-actions"><button type="button" class="btn secondary sm" data-rs-confirm="' + esc(p.email) + '" aria-label="' + esc("Confirm what Overture found about " + p.name) + '">' + ic("check") + "Confirm</button>" + edit + "</p>";
      }
    } else if (r.note) {
      // The pill above already says "Can't find this person", so the note starts at the reason.
      const note = r.status === "notfound" ? r.note.replace(/^Can't find this person: /, "").replace(/^./, (c) => c.toUpperCase()) : r.note;
      h += '<p class="rs-note">' + esc(note) + (opts.actions && MODE === "live" && (r.status === "unknown" || r.status === "error" || r.status === "later")
        ? ' <button type="button" class="link-btn" data-rs-again="' + esc(p.email) + '">' + (r.status === "error" ? "Try again" : r.status === "later" ? "Look up now" : "Look up again") + "</button>" : "") + "</p>";
    }
    const bits = [local.company ? local.company + " (from their email)" : "", local.adopter ? "On the Backstage adopters list" : "",
      local.company ? (local.metBefore ? "Met before, last on " + local.lastMet : "First meeting with them") : ""].filter(Boolean);
    if (bits.length) h += '<p class="rs-local">' + esc(bits.join(" · ")) + "</p>";
    return h ? '<div class="rs">' + h + "</div>" : "";
  }
  async function confirmResearch(email) {
    const p = D.people[email];
    if (!p || !p.research) return;
    if (MODE === "live") await saveRecord("person", { email, confirm: true });
    p.research = Object.assign({}, p.research, { found: "confirmed" });
    p.known = true;
  }
  async function lookUpAgain(email) {
    let r;
    try {
      r = await fetchTimeout("/api/research", 10000, { method: "POST", headers: { "Content-Type": "application/json", "X-OVERTURE": "1" }, body: JSON.stringify({ email }) });
    } catch (e) { throw new Error("Couldn't reach Overture's server. Is server.py running?"); }
    let j = {};
    try { j = await r.json(); } catch (e) { /* no body */ }
    if (!r.ok) throw new Error(j.error === "no-key" ? "Add a Claude key to look people up." : j.error || "Couldn't start the lookup (" + r.status + ")");
    if (D.people[email] && D.people[email].research) D.people[email].research = Object.assign({}, D.people[email].research, { status: "pending", note: "" });
  }
  // Once soon after the page opens (for the company profiles, which live.js may not carry yet), then every 5 s while a guest
  // or a company on screen is still "Researching…", ask the server what it found. onChange(emails, domains) repaints.
  // visibleOrgs (optional) gives the company names on screen.
  function watchResearch(visibleEmails, onChange, visibleOrgs) {
    if (MODE !== "live") return;
    let first = true;
    const pending = () => visibleEmails().some((e) => D.people[e] && D.people[e].research && D.people[e].research.status === "pending")
      || (visibleOrgs ? visibleOrgs() : []).some((n) => orgInfo(n).status === "pending");
    const tick = async () => {
      if (document.visibilityState === "visible" && (first || pending())) {
        try {
          const r = await fetchTimeout("/api/research", 8000);
          const j = r.ok ? await r.json() : {};
          const changed = [], domains = [];
          Object.entries(j.people || {}).forEach(([email, res]) => {
            const p = D.people[email];
            if (!p || !res || JSON.stringify(p.research) === JSON.stringify(res)) return;
            p.research = res;
            if (res.title) p.title = res.title;
            changed.push(email);
          });
          Object.entries(j.orgs && typeof j.orgs === "object" ? j.orgs : {}).forEach(([dom, o]) => {
            if (!o || typeof o !== "object" || JSON.stringify(D.orgs[dom]) === JSON.stringify(o)) return;
            D.orgs[dom] = o;
            domains.push(dom);
          });
          if (r.ok) first = false;
          if (changed.length || domains.length) onChange(changed, domains);
        } catch (e) { /* try again on the next tick */ }
      }
      setTimeout(tick, 5000);
    };
    setTimeout(tick, 1500);
  }

  // ---------- profiles: what Overture's research found about a guest and their company ----------
  // A guest: D.people[email].research.profile (server.py's records.people[email].profile). A company: GET /api/research's
  // orgs[domain].profile, or D.companies[name].profile from live.js (server.py's records.orgs[domain].profile).
  // Cleaned again here, whatever the server sent: only http(s) sources count, and a bullet left with no source is dropped,
  // so every line on screen cites a page Overture really read. Sources are renumbered 1, 2, 3… in their own order.
  const pstr = (v, n) => String(v == null ? "" : v).replace(/\s+/g, " ").trim().slice(0, n || 600);
  const PCACHE = new WeakMap();
  function cleanProfile(raw, org) {
    if (!raw || typeof raw !== "object") return null;
    if (PCACHE.has(raw)) return PCACHE.get(raw);
    const valid = [], vmap = {};
    (Array.isArray(raw.sources) ? raw.sources : []).forEach((s, i) => {
      const href = safeHref(s && s.url);
      if (!href) return;
      const host = new URL(href).hostname.replace(/^www\./, "");
      vmap[i] = valid.length;
      valid.push({ href, label: pstr(s.label, 140) || host, host });
    });
    const src = (list) => Array.from(new Set((Array.isArray(list) ? list : []).filter((i) => Number.isInteger(i) && vmap[i] !== undefined).map((i) => vmap[i])));
    const objs = (list) => (Array.isArray(list) ? list : []).filter((b) => b && typeof b === "object");
    const items = (list, max, extra) => objs(list).map((b) => Object.assign({ text: pstr(b.text), src: src(b.src) }, extra ? extra(b) : {}))
      .filter((b) => b.text && b.src.length).slice(0, max);
    const sum = raw.summary && typeof raw.summary === "object" ? { text: pstr(raw.summary.text), src: src(raw.summary.src) } : null;
    const p = { name: pstr(raw.name, 140), summary: sum && sum.text && sum.src.length ? sum : null, forCall: items(raw.forCall, 4),
      at: pstr(raw.at, 40), confidence: raw.confidence === "high" || raw.confidence === "medium" ? raw.confidence : "" };
    if (org) {
      Object.assign(p, { domain: pstr(raw.domain, 120), what: items(raw.what, 6), news: items(raw.news, 5, (b) => ({ when: pstr(b.when, 40) })), tech: items(raw.tech, 6),
        facts: objs(raw.facts).map((f) => ({ label: pstr(f.label, 60), value: pstr(f.value, 300), src: src(f.src) })).filter((f) => f.label && f.value && f.src.length).slice(0, 8) });
    } else {
      Object.assign(p, { now: items(raw.now, 6), education: items(raw.education, 3), work: items(raw.work, 6),
        past: objs(raw.past).map((r) => ({ role: pstr(r.role, 140), org: pstr(r.org, 140), when: pstr(r.when, 40), src: src(r.src), points: items(r.points, 4) }))
          .filter((r) => (r.role || r.org) && (r.src.length || r.points.length)).slice(0, 8),
        // Who a public page names with them at work (shown on their past-to-present timeline), each with its source.
        people: objs(raw.people).map((x) => ({ name: pstr(x.name, 80), role: pstr(x.role, 120), org: pstr(x.org, 120), how: pstr(x.how), when: pstr(x.when, 40), src: src(x.src) }))
          .filter((x) => x.name && x.how && x.src.length).slice(0, 10) });
    }
    const all = (org ? [p.facts, p.what, p.news, p.tech, p.forCall] : [p.now, p.education, p.work, p.forCall, p.past, p.people].concat(p.past.map((r) => r.points)))
      .flat().concat(p.summary ? [p.summary] : []);
    const used = Array.from(new Set(all.flatMap((b) => b.src))).sort((a, b) => a - b), renum = {};
    used.forEach((v, i) => { renum[v] = i; });
    all.forEach((b) => { b.src = b.src.map((v) => renum[v]).sort((a, b) => a - b); });
    p.sources = used.map((v) => valid[v]);
    p.empty = !all.length;
    PCACHE.set(raw, p);
    return p;
  }
  // One guest: their records row, their research (status, note) and their cleaned profile (null when there is nothing sourced).
  function personInfo(email) {
    const rec = D.people[email] || {}, r = rec.research && typeof rec.research === "object" ? rec.research : null;
    const prof = r ? cleanProfile(r.profile, false) : null;
    return { email, rec, research: r, status: r ? String(r.status || "") : "", note: r ? pstr(r.note, 300) : "", profile: prof && !prof.empty ? prof : null };
  }
  // A company by the name the calls use ("Tks"): its email domain, research status and cleaned profile.
  function orgDomain(name) {
    const c = D.companies[name] || {};
    if (c.domain) return String(c.domain);
    if (D.companyDomains && D.companyDomains[name]) return String(D.companyDomains[name]);
    const inv = D.invites.find((i) => i.company === name && i.domain);
    return inv ? String(inv.domain) : "";
  }
  function orgInfo(name) {
    const domain = orgDomain(name), o = (domain && D.orgs[domain]) || null, c = D.companies[name] || {};
    const prof = cleanProfile((o && o.profile) || c.profile, true), has = !!(prof && !prof.empty);
    const status = o && o.status === "pending" ? "pending" : has ? "done" : o ? String(o.status || "") : "";
    return { name, domain, status, note: o ? pstr(o.note, 300) : "", profile: has ? prof : null };
  }
  // What Claude gets for the written brief: the profile's text only (the sources stay on the page).
  const pTexts = (list) => (list || []).map((b) => b.text);
  const profileFacts = (pr) => (pr ? { source: MODE === "demo" ? "sample" : "Overture's web research", summary: pr.summary ? pr.summary.text : "", now: pTexts(pr.now),
    past: pr.past.slice(0, 3).map((r) => ({ role: r.role, org: r.org, when: r.when, points: pTexts(r.points) })), forCall: pTexts(pr.forCall) } : null);
  const orgFacts = (pr) => (pr ? { source: MODE === "demo" ? "sample" : "Overture's web research", name: pr.name, summary: pr.summary ? pr.summary.text : "",
    facts: pr.facts.map((f) => f.label + ": " + f.value), what: pTexts(pr.what), forCall: pTexts(pr.forCall) } : null);
  // A short opaque id for a person's page (#/people/<key>), so an email address never goes into a URL.
  function personKey(email) {
    const s = String(email || "").trim().toLowerCase();
    let a = 0x811c9dc5, b = 0x9747b28c;
    for (let i = 0; i < s.length; i++) {
      const c = s.charCodeAt(i);
      a = Math.imul(a ^ c, 0x01000193) >>> 0;
      b = Math.imul(b ^ c, 0x5bd1e995) >>> 0;
      b = (b ^ (b >>> 15)) >>> 0;
    }
    return (a.toString(36) + b.toString(36)).slice(0, 12);
  }
  function emailForKey(key) {
    const all = new Set(Object.keys(D.people));
    D.invites.forEach((i) => i.attendees.forEach((a) => all.add(a.email)));
    for (const e of all) if (personKey(e) === key) return e;
    return null;
  }

  // ---------- after the call ----------
  function afterCall(ctx, text) {
    const changes = [];
    const known = ctx.people.map((p) => p.name.toLowerCase());
    const skip = /^(Spotify|Portal|Confidence|Xirp|Backstage|Claude|Code)\b/;
    const names = Array.from(new Set(text.match(/\b[A-Z][a-z]+ [A-Z][a-z]+\b/g) || []))
      .filter((n) => !known.includes(n.toLowerCase()) && !skip.test(n));
    names.forEach((n) => changes.push({ kind: "People", text: n + " was mentioned on the call." }));
    if (/pilot|trial/i.test(text)) changes.push({ kind: "Next step", text: "A pilot came up. Agree the pass or fail rules and who signs off before it starts." });
    const papers = D.papers[ctx.invite.company] || {};
    if (/security/i.test(text)) {
      const cur = D.currentSecurityPack;
      changes.push({ kind: "Papers", text: !cur ? "Security review asked for. Send your current security pack."
        : papers.securityPack && papers.securityPack.sent === cur
        ? "Security review asked for. The current pack (" + cur + ") is already with them."
        : "Security review asked for. Send security pack " + cur + "." });
    }
    if (/\bnda\b/i.test(text) && !(papers.nda && papers.nda.signed)) changes.push({ kind: "Papers", text: MODE === "demo" ? "No NDA yet. Send one before the next call." : "An NDA came up. Check it is signed before the next call." });
    if (/budget is approved|budget approved/i.test(text)) changes.push({ kind: "Deal", text: "Budget is approved. Ask who signs and by when." });
    if (/pric/i.test(text)) changes.push({ kind: "Next step", text: "Pricing came up. Prepare a quote." });
    if (/follow up|next week/i.test(text)) changes.push({ kind: "Reminder", text: "Follow-up set for next week." });
    return changes;
  }

  // ---------- relationship graph (for the people map) ----------
  // Nodes: you, prospect companies, the people at them, and the places they came from. Edges carry a kind and a short label.
  function relationshipGraph() {
    const nodes = [{ id: "you", type: "you", label: "You", sub: MODE === "demo" ? "Chris · Spotify" : ME.name === "You" ? "You" : ME.name, src: "sample" }];
    const edges = [];
    const company = (name) => {
      const id = "co:" + name;
      if (!nodes.some((n) => n.id === id)) {
        const c = D.companies[name] || null;
        const ad = findAdopter(name);
        const prospect = D.invites.find((i) => i.company === name);
        nodes.push({ id, type: prospect ? "prospect" : "past", label: ad ? ad.org : name, callId: prospect ? prospect.id : null,
          status: c ? c.status.replace(/: .*/, "") + (c.customer ? "" : "") : ad ? "Backstage adopter" : "",
          customer: !!(c && c.customer), adopter: !!ad, src: c ? "sample" : ad ? "pub" : "sample", engineers: c ? c.engineers : null });
      }
      return id;
    };
    D.invites.forEach((inv) => {
      const co = company(inv.company);
      inv.attendees.forEach((a) => {
        const p = D.people[a.email] || {};
        const id = "p:" + a.email;
        nodes.push({ id, type: "person", label: a.name, sub: p.title || "Title unknown", company: co, callId: inv.id, startedAt: p.startedAt, src: "sample", note: p.note || "", previous: p.previous || "" });
        if (p.previous) {
          const prevId = company(p.previous);
          const prev = nodes.find((n) => n.id === prevId);
          const warm = prev.customer || prev.adopter;
          edges.push({ a: id, b: prevId, kind: warm ? "warm" : "moved", label: "ex-" + prev.label,
            why: a.name + " worked at " + prev.label + (prev.customer ? ", a Spotify customer." : prev.adopter ? ", which uses Backstage." : "."), src: prev.adopter ? "pub" : "sample" });
        }
      });
    });
    // People and companies mentioned on a call (live: Overture's saved connections; demo: the sample's), marked as mentioned on that call.
    // Settings > Mentions & connections picks which kinds show (people, customers, vendors, partners, competitors, ownership, other).
    const allow = prefs() ? new Set(prefs().mentions.mapRelations) : null, hiddenIds = new Set();
    const relGroup = (t) => (["customer", "vendor", "partner", "competitor"].includes(t) ? t : ["parent", "subsidiary", "investor", "acquired", "acquirer"].includes(t) ? "ownership" : "other");
    (D.mentioned || []).forEach((m) => {
      if (allow && !allow.has(m.type === "company" ? relGroup(m.relation) : "people")) { hiddenIds.add(m.type === "company" ? "co:" + m.label : m.id); return; }
      if (m.type === "company") {
        const cid = company(m.label), n = nodes.find((x) => x.id === cid);
        if (n.type === "past") { n.mentioned = m.callId; if (!n.status) n.status = "Mentioned on a call"; if (n.src !== "pub") n.src = "call"; }
        return;
      }
      if (nodes.some((x) => x.id === m.id)) return;
      nodes.push({ id: m.id, type: "person", label: m.label, sub: "Mentioned · " + (m.sub || "on the call"), company: company(m.company), callId: m.callId,
        src: "call", mentioned: m.callId, auto: !!m.auto, note: "", previous: "" });
    });
    (D.relationships || []).forEach((r) => { if (!(r.kind === "mentioned" && hiddenIds.has(r.b))) edges.push(Object.assign({ src: "sample" }, r)); });
    // People who share a past employer worked together: draw that line too, it is the non-obvious one.
    const byPrev = {};
    edges.filter((e) => e.label && e.label.startsWith("ex-")).forEach((e) => { (byPrev[e.b] = byPrev[e.b] || []).push(e.a); });
    Object.entries(byPrev).forEach(([co, ids]) => {
      for (let i = 0; i < ids.length; i++) for (let j = i + 1; j < ids.length; j++) {
        const A = nodes.find((n) => n.id === ids[i]); const B = nodes.find((n) => n.id === ids[j]);
        if (A.company !== B.company) edges.push({ a: ids[i], b: ids[j], kind: "together", label: "worked together",
          why: A.label + " and " + B.label + " both worked at " + nodes.find((n) => n.id === co).label + ", and now sit at two different prospects.", src: "sample" });
      }
    });
    const have = new Set(nodes.map((n) => n.id));
    return { nodes, edges: edges.filter((e) => have.has(e.a) && have.has(e.b)) }; // a removed or unknown end never breaks the map
  }
  // A call's connections changed (GET /api/mentions sends its "graph"): swap that call's mentioned nodes and edges, keep the rest.
  function mergeConnections(callId, graph) {
    if (!graph || !callId) return false;
    const before = JSON.stringify([(D.mentioned || []).filter((m) => m.callId === callId), D.relationships.filter((r) => r.callId === callId)]);
    D.mentioned = (D.mentioned || []).filter((m) => m.callId !== callId).concat(graph.mentioned || []);
    D.relationships = D.relationships.filter((r) => r.callId !== callId).concat(graph.relationships || []);
    return before !== JSON.stringify([graph.mentioned || [], graph.relationships || []]);
  }

  // ---------- click-to-explain: the card behind a connection or a mention ----------
  // x is server.py's explain_view (the demo's sample carries the same shape). Every sentence on the card cites one of the
  // numbered sources under it (the server drops a sentence whose sources were dropped); with no sentence, only the relation
  // type shows. Quotes from the web are at most 25 words; "Said on the call" is the call's own words.
  const XP_HOW = { "Said on the call": "tag-purple", "Found on the web": "tag-teal", "Likely, not confirmed": "tag-orange", "Known to Overture": "tag-green" };
  const xpCap = (t) => String(t || "").charAt(0).toUpperCase() + String(t || "").slice(1);
  const xpDay = (s) => {
    const m = String(s || "").match(/^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?/);
    if (!m) return "";
    return m[3] ? MONTHS[+m[2] - 1] + " " + +m[3] + ", " + m[1] : m[2] ? MONTHS[+m[2] - 1] + " " + m[1] : m[1];
  };
  function explainHtml(x, opts) {
    if (!x) return "";
    opts = opts || {};
    // A sentence cites sources by their place in x.evidence; one with no safe link is left out, so num[] keeps each citation on its own source.
    const ev = [], num = {};
    (x.evidence || []).forEach((s, i) => { const href = safeHref(s && s.url); if (href) { ev.push(Object.assign({}, s, { href })); num[i] = ev.length; } });
    const refs = (list) => (list || []).filter((i) => num[i]).map((i) => '<sup class="xp-ref"><span class="sr-only">source </span>' + num[i] + "</sup>").join("");
    const type = x.kind === "company" ? (x.typeLabel || "Relation unknown") : (x.typeLabel || (x.title ? "Works there" : "Mentioned on the call"));
    let h = '<div class="xp-card">';
    h += '<p class="xp-type"><span class="pill ' + (x.kind === "company" ? "tag-blue" : "tag-gray") + '">' + esc(type) + "</span>"
      + (x.kind === "company" && x.label && x.label !== "mentioned" && x.label.toLowerCase() !== type.toLowerCase() ?'<span class="xp-label">' + esc(xpCap(x.label)) + "</span>" : x.title ? '<span class="xp-label">' + esc(x.title) + "</span>" : "")
      + (x.found && XP_HOW[x.found.how] ? '<span class="pill ' + XP_HOW[x.found.how] + '">' + esc(x.found.how) + "</span>" : "")
      + (MODE === "demo" ? '<span class="src sample">Sample</span>' : "") + "</p>";
    // What the company is (a sourced definition), above how it's connected.
    if (x.about && x.about.text && refs(x.about.sources)) h += '<p class="xp-h">What it is</p><p class="xp-about">' + esc(x.about.text) + refs(x.about.sources) + "</p>";
    const what = (x.explanation || []).filter((s) => s && s.text && refs(s.sources));
    if (what.length) h += (x.about && x.about.text ? '<p class="xp-h">How it connects</p>' : "") + '<div class="xp-what">' + what.map((s) => "<p>" + esc(s.text) + refs(s.sources) + "</p>").join("") + "</div>";
    if (x.since && x.since.text && refs(x.since.sources)) h += '<p class="xp-since">' + ic("clock") + "<span>Since " + esc(String(x.since.text).replace(/^since\s+/i, "")) + refs(x.since.sources) + "</span></p>";
    if (x.said && x.said.text) {
      h += '<p class="xp-h">Said on the call</p><blockquote class="xp-quote"><span>“' + esc(x.said.text) + "”</span>"
        + (x.said.speaker || x.said.time ? '<span class="xp-who">' + esc([x.said.speaker, x.said.time].filter(Boolean).join(", ")) + "</span>" : "") + "</blockquote>";
    }
    if (x.mention && x.mention.text && !opts.noMention && !(x.said && x.said.text && x.mention.text.includes(x.said.text.replace(/…/g, "")))) {
      h += '<p class="xp-h">Where it came up</p><blockquote class="xp-quote"><span>“' + esc(x.mention.text) + "”</span>"
        + (x.mention.speaker || x.mention.time ? '<span class="xp-who">' + esc([x.mention.speaker, x.mention.time].filter(Boolean).join(", ")) + "</span>" : "") + "</blockquote>";
    }
    if (ev.length) {
      h += '<p class="xp-h">' + (ev.length > 1 ? "Sources" : "Source") + '</p><ol class="xp-ev" role="list">' + ev.map((s, i) => "<li>"
        + '<span class="xp-n" aria-hidden="true">' + (i + 1) + "</span><div>"
        + (s.quote ? '<p class="xp-evq">“' + esc(s.quote) + "”</p>" : "")
        + '<p class="xp-evs"><a href="' + esc(s.href) + '" target="_blank" rel="noopener noreferrer">' + esc(s.label || new URL(s.href).hostname) + ic("link", "ext") + NEW_TAB + "</a>"
        + (s.date ? '<span class="xp-date">' + esc(xpDay(s.date)) + "</span>" : "") + "</p></div></li>").join("") + "</ol>";
    }
    const f = x.found || {}, meta = [];
    if (f.call) meta.push("On the " + f.call + " call" + (f.time ? " at " + f.time : ""));
    if (f.via) meta.push("from " + f.via);
    if (f.at && xpDay(f.at)) meta.push("found " + xpDay(f.at));
    if (x.confidence) meta.push(xpCap(x.confidence) + " confidence");
    if (meta.length) h += '<p class="xp-meta">' + esc(xpCap(meta.join(" · "))) + "</p>";
    return h + "</div>";
  }
  // A fold that opens the card: used in After the call, the in-call panel's People tab and the People map's side panel.
  const explainFold = (x, opts) => (x ? '<details class="xp"' + (opts && opts.open ? " open" : "") + '><summary>' + ic("chevron", "xp-chev") + esc((opts && opts.summary) || "How they're connected") + "</summary>" + explainHtml(x, opts) + "</details>" : "");
  // The explain object for a map line: the server's, or (demo) the sample mention it came from.
  function explainFor(e) {
    if (!e) return null;
    if (e.explain) return e.explain;
    const sm = D.mentionSample;
    if (!sm || !e.mentionId) return null;
    const x = (sm.items || []).concat(sm.orgs || []).find((y) => y.id === e.mentionId);
    return x ? x.explain || null : null;
  }

  window.C = {
    explainHtml, explainFold, explainFor,
    SNAP, D, MODE, SRC, ME, state, LIVE, saveRecord, askAI, deviceChecked, CHRIS, ASSUME, STEP_DEFS, RIVALS, PORTAL_POINTS, MONTHS, NEW_TAB, ICONS,
    $, $$, esc, wait, plural, initials, fmtDate, splitWhen, ic, store, tint, solid, avatar, coTile, tagFor,
    cleanVer, parseVer, findAdopter, refreshLive, claudeChecked, fetchTimeout,
    readVersionFile, packagesFor, upgradeBill, tenure, personFacts, paperStatus, guessProduct,
    inviteById, alertsFor, allAlerts, alertOn, priority, priorityBadge, byPriority, prefs, runChecks, openingLine, todoList, factsFor, askClaude, afterCall, relationshipGraph, mergeConnections,
    researchHtml, confirmResearch, lookUpAgain, watchResearch, RELATION,
    cleanProfile, personInfo, orgInfo, orgDomain, personKey, emailForKey,
    gongFor, gongHtml, money, safeHref, hubspotPlan, hubspotSave, postJson,
  };
})();
