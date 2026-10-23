# Running MOAB inside Google Meet and Zoom

The in-call panel is `panel.html`: one page, fluid from 320px wide. It works on its own (preview), as a Google Meet add-on side panel, and as a Zoom App. It never shares its screen with the other people on the call.

How it decides where it runs (`panel.js`):
1. URL has `meet_sdk` → Google Meet. Loads `https://www.gstatic.com/meetjs/addons/1.1.0/meet.addons.js`, calls `meet.addon.createAddonSession({ cloudProjectNumber })`, then `createSidePanelClient()` and `getMeetingInfo()` to match the meeting code to a call.
2. URL has `host=zoom` (or the Zoom user agent) → Zoom. Loads `https://appssdk.zoom.us/sdk.min.js`, calls `zoomSdk.config(...)`, then `getMeetingContext()` (topic → company) and `getMeetingParticipants()` (who joined). Both need host or co-host.
3. Otherwise → preview. If anything fails, it shows a call picker instead.

## Google Meet
1. Host the folder on HTTPS (GitHub Pages works for Meet).
2. Google Cloud project: enable **Google Workspace Marketplace SDK** and **Google Workspace add-ons API**. Note the project number.
3. Marketplace SDK → HTTP deployments → new deployment with this manifest (replace HOST):
   ```json
   {"addOns":{"common":{"name":"MOAB","logoUrl":"https://HOST/icon.png"},
    "meet":{"web":{"sidePanelUrl":"https://HOST/centralize/panel.html","supportsScreenSharing":false,
    "addOnOrigins":["https://HOST"],"logoUrl":"https://HOST/icon.png"}}}}
   ```
4. Put the project number in `panel.html` → `meetCloudProjectNumber`.
5. Install the test deployment, start a call, open **Activities**, pick MOAB.
Limits: the SDK gives only the meeting code (no names); participant names need the Meet REST API with OAuth. Adult, non-supervised Google accounts only.

## Zoom
1. Host on HTTPS with the four headers Zoom checks (`_headers` in this folder does it on Netlify or Cloudflare Pages). GitHub Pages does not send them.
2. Zoom App Marketplace → Build an app → **General app**. Home URL: `https://HOST/centralize/panel.html?host=zoom`. Domain allow list: HOST, `appssdk.zoom.us`, `fonts.googleapis.com`, `fonts.gstatic.com`.
3. Zoom App SDK APIs: getRunningContext, getMeetingContext, getMeetingParticipants, getUserContext, onParticipantChange, expandApp, openUrl. Scope `zoomapp:inmeeting`.
4. Local Test → Add App Now, then open it from **Apps** inside a meeting.
Limits: topic and participants need host or co-host; desktop client by default.

Sources: developers.google.com/workspace/meet/add-ons, developers.zoom.us/docs/zoom-apps (checked Oct 18, 2026).
