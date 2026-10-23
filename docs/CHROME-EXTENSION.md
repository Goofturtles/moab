# MOAB in Chrome's side panel (Google Meet and Zoom web calls)

`extension/` is a small Chrome extension (Manifest V3). On a Google Meet tab, or a Zoom call in the browser, the MOAB button opens
MOAB's in-call panel in Chrome's side panel, already on the right call: it reads the meeting code from the tab's address
(`meet.google.com/abc-defg-hij`, `app.zoom.us/wc/123456789/join`) and MOAB matches it to your calendar (Meet code, or the Zoom
meeting number in the invite). If it can't, the panel shows the call picker.

## Load it (developer mode, once)

1. Start MOAB: `tks-spotify/.venv/Scripts/python.exe tks-spotify/centralize/server.py` (it must run on port 3576).
2. In Chrome open `chrome://extensions`, turn on **Developer mode** (top right).
3. **Load unpacked** and pick the folder `tks-spotify/centralize/extension`.
4. Pin it: puzzle icon in the toolbar > the pin next to **MOAB in-call panel**.
5. Join a Meet or Zoom web call and press the MOAB button. (On other sites the side panel stays off.)

The extension's id is `geemcgoloailklihnpghgindneohhccc` on every PC (the manifest's `key` fixes it). MOAB's server only lets
its own pages and this extension show the in-call panel in a frame (`Content-Security-Policy: frame-ancestors 'self'
chrome-extension://geemcgoloailklihnpghgindneohhccc`). If you change the key or load a copy with another id, add that id to
`MOAB_EXTENSION_IDS` (comma-separated) before starting the server.

## What it may do

- Permissions: `sidePanel` only. Host access: `https://meet.google.com/*`, `https://*.zoom.us/*` (to read those tabs' addresses)
  and `http://localhost:3576/*` (MOAB on this PC). No `tabs`, no `scripting`, no content scripts: it never reads the meeting page.
- It sends nothing anywhere. The side panel page can only talk to and show `http://localhost:3576` (its own Content Security Policy).
- Because the extension has host access to MOAB, Chrome gives the framed panel MOAB's normal storage, so notes typed in the side
  panel show up in the app's After the call.

## Not tested in a real Chrome profile

Built against Chrome's `chrome.sidePanel` docs (Chrome 116+) and checked by `tools/test_live.py` (manifest, permissions, the
frame allow-list, the meeting-code parsing). Load it once and open a Meet call to confirm. Zoom's web-client addresses vary by
account; if the panel doesn't pick the call, pick it in the panel.
