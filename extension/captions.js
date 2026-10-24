// Overture on Google Meet: reads Meet's own live captions (only while you have CC turned on) and hands each finished line to Overture's
// side panel, which passes it to Overture on this PC to find the people and companies mentioned. Nothing is sent anywhere else and
// nothing is kept here: the lines live in the side panel until the call ends. It also says when you leave the call, so Overture can
// read the whole transcript once for After the call.
"use strict";
(() => {
  // One reader per Meet tab: a newer copy (the extension was reloaded mid-call) takes over and this one stops.
  const me = String(Date.now()) + Math.random().toString(36).slice(2, 8);
  document.documentElement.dataset.overtureCaptions = me;
  const POLL_MS = 1000;
  const UI_WORDS = new Set(["captions", "live captions", "english", "turn off captions", "turn on captions", "caption settings"]);
  const ICON = /^[a-z_]+$/;          // Material icon ligatures in Meet's text (arrow_downward, more_vert)
  const recent = [];                 // captions already sent, so one Meet shows again isn't sent twice
  const all = [];                    // the whole call's lines, sent once more when you leave (the side panel may have reloaded)
  let lastKey = "", stable = 0, emitted = null, inCall = false, missed = 0, ticks = 0;

  function captionsBox() {
    return document.querySelector('[role="region"][aria-label*="aption" i]') // "Captions"
      || document.querySelector('div[jsname="dsyhDe"]') || document.querySelector(".a4cQT");
  }
  const lineList = (el) => el.innerText.split("\n").map((s) => s.replace(/\s+/g, " ").trim())
    .filter((s) => s && s.length < 600 && !ICON.test(s) && !UI_WORDS.has(s.toLowerCase()));
  // Without speaker blocks, a name is guessed: a short capitalised line with no punctuation, above someone's words.
  const looksLikeName = (s) => s === "You" || (s.split(" ").length <= 4 && !/[.,!?;:"]/.test(s) && /^[A-ZÀ-ɏ]/.test(s));

  // Who said what. Meet shows each speaker as a block: their picture, their name, then their words. Use those blocks when they're
  // there (the name is exact, in any language); otherwise fall back to guessing names line by line.
  function captionsOf(box) {
    const isBlock = (el) => el.querySelector("img, svg") && lineList(el).length >= 2; // a photo, or an icon (dial-in callers)
    const blocks = [...box.querySelectorAll("div")].filter((el) => isBlock(el) && ![...el.children].some(isBlock));
    if (blocks.length) return blocks.map((b) => { const ls = lineList(b); return { speaker: ls[0], text: ls.slice(1).join(" ") }; });
    const ls = lineList(box), out = [];
    let who = "";
    ls.forEach((l, i) => { if (looksLikeName(l) && ls[i + 1] && !looksLikeName(ls[i + 1])) who = l; else out.push({ speaker: who, text: l }); });
    return out;
  }

  function send(type, extra) {
    try { chrome.runtime.sendMessage(Object.assign({ type }, extra || {})).catch(() => {}); } catch (e) { /* the extension was reloaded */ }
  }

  function finished(c, out) {
    // Meet keeps adding to what someone is still saying: send only what's new since it was last sent.
    let words = c.text;
    if (emitted && emitted.speaker === c.speaker && c.text.startsWith(emitted.text)) words = c.text.slice(emitted.text.length).trim();
    const key = c.speaker + "\u0000" + c.text;
    if (!words || recent.includes(key)) return;
    recent.push(key);
    if (recent.length > 300) recent.shift();
    emitted = c;
    const line = (c.speaker ? c.speaker + ": " : "") + words;
    out.push(line);
    all.push(line);
    if (all.length > 20000) all.shift();
  }

  function tick() {
    // Every 3 s: tell the side panel this reader is running and whether it can see Meet's captions (CC on), so it can say so.
    if (ticks++ % 3 === 0) send("overture-captions-status", { box: !!captionsBox() });
    const leave = document.querySelector('[aria-label*="Leave call" i]');
    if (leave) { inCall = true; missed = 0; }
    else if (inCall && ++missed >= 2) { // gone for 2 checks in a row (not a toolbar redraw): you left the call
      inCall = false;
      send("overture-call-ended", { lines: all.slice() }); // Overture reads the whole transcript for After the call
    }
    const box = captionsBox();
    if (!box) return;
    const caps = captionsOf(box), out = [];
    caps.forEach((c, i) => {
      if (i === caps.length - 1) { // the caption being spoken: finished once it hasn't changed for 2 seconds
        const key = c.speaker + "\u0000" + c.text;
        stable = key === lastKey ? stable + 1 : 0;
        lastKey = key;
        if (stable < 2) return;
      }
      finished(c, out);
    });
    if (out.length) send("overture-captions", { lines: out });
  }
  const timer = setInterval(() => {
    // replaced by a newer copy, or the extension was turned off: stop
    if (document.documentElement.dataset.overtureCaptions !== me || !(chrome.runtime && chrome.runtime.id)) { clearInterval(timer); return; }
    tick();
  }, POLL_MS);
})();
