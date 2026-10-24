// The side panel: Overture's in-call panel (http://localhost:3576/panel.html) in a frame, told which meeting this tab is in.
// Google Meet: meet.google.com/abc-defg-hij gives meet=abc-defg-hij. Zoom web client: app.zoom.us/wc/123456789/join (or
// zoom.us/wc/join/123456789, zoom.us/j/123456789) gives zoom=123456789. Overture matches that to your calendar's call.
// Nothing leaves this PC: the only address this page talks to or shows is Overture's own, on localhost (see the manifest's CSP).
"use strict";

const Overture = "http://localhost:3576";
const frame = document.getElementById("moab");
const off = document.getElementById("off");

function meetingParams(url) {
  let u;
  try { u = new URL(url); } catch (e) { return {}; }
  if (u.protocol !== "https:") return {};
  const host = u.hostname.toLowerCase();
  if (host === "meet.google.com") {
    const m = u.pathname.match(/^\/([a-z]{3}-[a-z]{4}-[a-z]{3})(?:\/|$)/i);
    return m ? { meet: m[1].toLowerCase() } : {};
  }
  if (host === "zoom.us" || host.endsWith(".zoom.us")) {
    const m = u.pathname.match(/\/(?:wc|j|s|w)\/(?:join\/)?(\d{9,11})(?:\/|$)/);
    return m ? { zoom: m[1] } : {};
  }
  return {};
}

function panelUrl(p) {
  const q = new URLSearchParams({ host: "ext" });
  if (p.meet) q.set("meet", p.meet);
  if (p.zoom) q.set("zoom", p.zoom);
  return Overture + "/panel.html?" + q.toString();
}

async function activeTabUrl() {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    return (tab && tab.url) || "";
  } catch (e) { return ""; }
}

async function moabUp() {
  try { return (await fetch(Overture + "/api/status", { cache: "no-store", credentials: "omit" })).ok; } catch (e) { return false; }
}

let shown = "";
async function refresh() {
  const up = await moabUp();
  off.hidden = up;
  frame.hidden = !up;
  if (!up) { shown = ""; return; }
  const p = meetingParams(await activeTabUrl());
  // Another tab that isn't a meeting (presenting, looking something up): keep the panel as it is, with the call's captions so far.
  if (shown && !p.meet && !p.zoom) return;
  const src = panelUrl(p);
  if (src !== shown) { shown = src; frame.src = src; } // a new meeting in this tab: the panel opens its call
}

// Google Meet's captions (captions.js in the Meet tab) go to the panel in the frame, only from the meeting the panel is showing.
if (chrome.runtime && chrome.runtime.onMessage) chrome.runtime.onMessage.addListener((msg, sender) => {
  if (!msg || !sender.tab || frame.hidden || !shown || !frame.contentWindow) return;
  const meet = meetingParams(sender.tab.url || "").meet;
  if (!meet || new URL(shown).searchParams.get("meet") !== meet) return;
  if (msg.type === "moab-captions" && Array.isArray(msg.lines)) {
    frame.contentWindow.postMessage({ type: "moab-captions", lines: msg.lines.slice(0, 50).map((l) => String(l).slice(0, 600)) }, Overture);
  } else if (msg.type === "moab-captions-status") {
    frame.contentWindow.postMessage({ type: "moab-captions-status", box: !!msg.box }, Overture);
  } else if (msg.type === "moab-call-ended") {
    const lines = Array.isArray(msg.lines) ? msg.lines.slice(-20000).map((l) => String(l).slice(0, 600)) : [];
    frame.contentWindow.postMessage({ type: "moab-call-ended", lines }, Overture);
  }
});

document.getElementById("retry").addEventListener("click", refresh);
chrome.tabs.onActivated.addListener(refresh);
chrome.tabs.onUpdated.addListener((tabId, info) => { if (info.url) refresh(); });
refresh();

// For tools/test_live.py's node check (no effect in Chrome).
if (typeof module !== "undefined") module.exports = { meetingParams, panelUrl };
