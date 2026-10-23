// MOAB's in-call panel in Chrome's side panel, on Google Meet and Zoom web-client tabs only.
// This extension sends nothing anywhere: the side panel shows MOAB from this PC (http://localhost:3576), nothing else.
// Without the "tabs" permission Chrome only tells us the address of tabs on the sites in host_permissions, which is all we need.
"use strict";

const MEETING_SITES = [/^https:\/\/meet\.google\.com\//, /^https:\/\/([a-z0-9-]+\.)*zoom\.us\//];
const isMeeting = (url) => typeof url === "string" && MEETING_SITES.some((re) => re.test(url));

// The toolbar button opens the panel (where it is turned on: meeting tabs).
chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});

async function setFor(tabId, url) {
  try {
    await chrome.sidePanel.setOptions(isMeeting(url) ? { tabId, path: "sidepanel.html", enabled: true } : { tabId, enabled: false });
  } catch (e) { /* the tab closed meanwhile */ }
}

chrome.tabs.onUpdated.addListener((tabId, info, tab) => {
  if (info.url || info.status === "complete") setFor(tabId, tab.url);
});
chrome.tabs.onActivated.addListener(async ({ tabId }) => {
  try { const tab = await chrome.tabs.get(tabId); setFor(tabId, tab.url); } catch (e) { /* gone */ }
});
chrome.runtime.onInstalled.addListener(async () => {
  try { (await chrome.tabs.query({})).forEach((t) => setFor(t.id, t.url)); } catch (e) { /* nothing to do */ }
  // Installed or reloaded mid-call: Chrome only adds captions.js to Meet tabs that load from now on, so add it to the Meet tabs
  // already open too (the copy from before the reload switches itself off).
  try {
    const meets = (await chrome.tabs.query({})).filter((t) => /^https:\/\/meet\.google\.com\//.test(t.url || ""));
    await Promise.all(meets.map((t) => chrome.scripting.executeScript({ target: { tabId: t.id }, files: ["captions.js"] }).catch(() => {})));
  } catch (e) { /* no Meet tab open */ }
});
