// Overture settings (the Settings page): the defaults, where the current values come from, saving, and the appearance.
// Loaded before core.js on both pages (index.html and panel.html).
// Live: server.py sends every setting in data/live.js (MOAB_LIVE.appSettings) and saves them with PUT /api/settings.
// Connect (no calendar yet): the same endpoint, read with GET /api/settings. Demo (?demo=1): this browser only, never the server.
(function () {
  "use strict";
  // Must match server.py default_settings() (tools/test_live.py compares them).
  const DEFAULTS = /*defaults*/{"brief":{"sections":[{"id":"opener","on":true},{"id":"since","on":true},{"id":"lastTalk","on":true},{"id":"backstage","on":true},{"id":"todos","on":true},{"id":"people","on":true},{"id":"security","on":true},{"id":"rivals","on":true},{"id":"papers","on":true}],"length":"full","tone":"direct"},"priorities":{"targets":[],"rules":{"engineers":{"on":true,"min":200,"weight":2},"adopter":{"on":true,"weight":2},"deal":{"on":true,"weight":3},"alert":{"on":true,"weight":1},"customer":{"on":true,"weight":1}},"target":3,"hot":5,"warm":2,"sort":true},"panel":{"cards":[{"id":"opener","on":true},{"id":"points","on":true},{"id":"watch","on":true},{"id":"send","on":true},{"id":"people","on":true},{"id":"map","on":true},{"id":"notes","on":true}],"density":"full","listening":false},"followup":{"templates":{"intro":{"subject":"Good to meet you, {first_name}","body":"Hi {first_name},\n\nThanks for making time today. What I heard:\n{summary}\n\nNext step: {next_step}\n\nBest,\n{my_name}"},"discovery":{"subject":"{company} and Spotify: notes from {date}","body":"Hi {first_name},\n\nThanks for walking me through how {company} works today. My notes:\n{summary}\n\nNext step: {next_step}\n\nBest,\n{my_name}"},"demo":{"subject":"Your demo: what we covered","body":"Hi {first_name},\n\nThanks for joining the demo on {date}. What we covered:\n{summary}\n\nNext step: {next_step}\n\nBest,\n{my_name}"},"renewal":{"subject":"{company} renewal: next steps","body":"Hi {first_name},\n\nThanks for the renewal call today. What we agreed:\n{summary}\n\nNext step: {next_step}\n\nBest,\n{my_name}"},"other":{"subject":"Following up: {company}","body":"Hi {first_name},\n\nThanks for your time on {date}.\n{summary}\n\nNext step: {next_step}\n\nBest,\n{my_name}"}}},"mentions":{"autoLookup":true,"autoAdd":"single","mapRelations":["people","customer","vendor","partner","competitor","ownership","other"],"keepDays":90},"alerts":{"signals":{"jobChanges":true,"newInvitees":true,"mentioned":true,"security":true,"release":true,"hubspotStages":true},"security":"all","delivery":"instant","quiet":{"on":false,"from":"18:00","to":"08:00"}},"research":{"web":true,"hubspot":true,"gong":true,"gongTranscripts":false,"gongInAI":false,"transcriptsInAI":false,"aiShare":"notes","blocked":[],"meetily":false,"granola":false},"appearance":{"theme":"dark","accent":"green","density":"comfortable"}}/*end*/;
  const QS = new URLSearchParams(location.search);
  const MODE = QS.get("demo") === "1" ? "demo" : window.MOAB_LIVE ? "live" : "connect";
  const DEMO_KEY = "centralize:settings:demo", CACHE_KEY = "centralize:settings:cache";
  const LOOK_KEY = MODE === "demo" ? "centralize:appearance:demo" : "centralize:appearance"; // the demo keeps its own look
  const read = (k) => { try { return JSON.parse(localStorage.getItem(k)); } catch (e) { return null; } };
  const write = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* storage blocked: still works for this visit */ } };
  const clone = (o) => JSON.parse(JSON.stringify(o));

  // Lenient merge for values kept in this browser: anything with the wrong shape falls back to the default.
  function merge(def, val) {
    if (Array.isArray(def)) {
      if (!Array.isArray(val)) return clone(def);
      if (def.length && def[0] && typeof def[0] === "object" && "id" in def[0]) {  // an ordered list of {id, on}: every id once
        const ids = def.map((d) => d.id), seen = new Set();
        const out = val.filter((x) => x && ids.includes(x.id) && typeof x.on === "boolean" && !seen.has(x.id) && seen.add(x.id)).map((x) => ({ id: x.id, on: x.on }));
        def.forEach((d) => { if (!seen.has(d.id)) out.push(clone(d)); });
        return out;
      }
      return val.filter((x) => typeof x === "string").slice(0, 100);
    }
    if (def && typeof def === "object") {
      const out = {};
      Object.keys(def).forEach((k) => { out[k] = merge(def[k], val && typeof val === "object" ? val[k] : undefined); });
      return out;
    }
    return typeof val === typeof def ? val : def;
  }

  let current = merge(DEFAULTS, MODE === "live" ? window.MOAB_LIVE.appSettings : MODE === "demo" ? read(DEMO_KEY) : read(CACHE_KEY));
  const listeners = new Set();
  const emit = (group) => listeners.forEach((fn) => { try { fn(current, group); } catch (e) { /* one listener never breaks the rest */ } });

  // ---------- appearance: theme, accent, density on <html> (index.html and panel.html set them before the first paint) ----------
  function applyAppearance(a) {
    a = a || current.appearance;
    const root = document.documentElement;
    root.dataset.theme = a.theme;
    root.dataset.accent = a.accent;
    root.dataset.density = a.density;
    root.style.colorScheme = a.theme;
    write(LOOK_KEY, { theme: a.theme, accent: a.accent, density: a.density });
  }
  applyAppearance();

  // ---------- saving ----------
  // save("brief", {...whole or partial group}) -> resolves with every setting; rejects with a readable message.
  async function save(group, value) {
    const patch = { [group]: value };
    if (MODE === "demo") {
      const next = merge(DEFAULTS, Object.assign(clone(current), { [group]: Object.assign(clone(current[group]), value) }));
      if (group === "research") {  // the same rule as the server: "what may go to AI" and the transcripts switch are one choice
        const r = next.research;
        if ("transcriptsInAI" in value && !("aiShare" in value)) r.aiShare = r.transcriptsInAI ? "transcripts" : r.aiShare === "transcripts" ? "notes" : r.aiShare;
        else r.transcriptsInAI = r.aiShare === "transcripts";
      }
      current = next;
      write(DEMO_KEY, current);
    } else {
      let r;
      try {
        r = await fetch("/api/settings", { method: "PUT", headers: { "Content-Type": "application/json", "X-MOAB": "1" }, body: JSON.stringify(patch) });
      } catch (e) { throw new Error("Couldn't reach Overture's server. Is server.py running?"); }
      let j = {};
      try { j = await r.json(); } catch (e) { /* no body */ }
      if (!r.ok) throw new Error(j.error ? "Not saved: " + j.error : "Not saved (" + r.status + ")");
      current = merge(DEFAULTS, j.settings);
      write(CACHE_KEY, current);
    }
    if (group === "appearance") applyAppearance();
    emit(group);
    return current;
  }
  // Connect mode has no live.js settings: ask the server once (the cached copy shows meanwhile).
  const ready = MODE === "connect" ? fetch("/api/settings").then((r) => (r.ok ? r.json() : null)).then((j) => {
    if (!j || !j.settings) return;
    current = merge(DEFAULTS, j.settings);
    write(CACHE_KEY, current);
    applyAppearance();
    emit(null);
  }).catch(() => {}) : Promise.resolve();

  // Settings changed in another tab (or the panel): pick them up.
  addEventListener("storage", (e) => {
    if (e.key === LOOK_KEY && e.newValue) { try { const a = JSON.parse(e.newValue); current.appearance = merge(DEFAULTS.appearance, a); applyAppearance(); emit("appearance"); } catch (err) { /* ignore */ } }
    if (MODE === "demo" && e.key === DEMO_KEY) { current = merge(DEFAULTS, read(DEMO_KEY)); applyAppearance(); emit(null); }
  });

  window.MoabSettings = {
    MODE, DEFAULTS,
    get: () => current,
    defaults: () => clone(DEFAULTS),
    save, ready, applyAppearance,
    on: (fn) => { listeners.add(fn); return () => listeners.delete(fn); },
  };
})();
