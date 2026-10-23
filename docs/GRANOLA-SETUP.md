# Granola: notes and transcript after the call

With Granola on, a few minutes after a call ends MOAB reads its Granola note and transcript, finds the people and companies said on
the call, and shows **From Granola** (the note's title, a link to it and Granola's summary) in **After the call**.

## What it needs

- Granola's API: a **personal API key** (Granola on a Business or Enterprise plan; on Enterprise an admin turns on API access first).
- Docs checked Oct 21, 2026: https://docs.granola.ai/introduction and https://docs.granola.ai/api-reference/openapi.json

## Set it up

1. In Granola: Settings > API (or Settings > Connectors > API keys), create a personal API key.
2. Save it on this PC (asks with no echo, writes `centralize/.data/granola.json`):
   `tks-spotify/.venv/Scripts/python.exe -I tks-spotify/centralize/tools/connect.py granola`
   (or set `GRANOLA_API_KEY` before starting the server). Restart `server.py`.
3. In MOAB: **Settings > Research sources and privacy > Granola**: on.

## What MOAB does with it

- Every 5 minutes it looks at calls that ended between 5 minutes and a day ago. For each, it lists your notes created around the
  call (`GET /v1/notes?created_after&created_before`), opens each without its transcript (`GET /v1/notes/{id}`) and takes the
  one whose calendar event is that call (same event id, or the same start time with a shared guest or title). Only that note's
  transcript is fetched (`?include=transcript`, or the paged `/transcript` endpoint for long ones); other meetings' never are.
  No note yet: it looks again in 30 minutes. **Read Granola's note** in After the call does the same at once.
- The transcript is read in memory and dropped. `records.json` keeps the note's title, link and summary (under `granola`) and,
  as for any transcript, each mention with its sentence. The summary goes with the sentences after **Keep quotes for** in
  Settings > Mentions and connections.
- Mentions are looked up on the web like an uploaded transcript (name, role words, company name and website only). The read
  MOAB does by itself follows **Look up mentions automatically**: with it off, they are listed but not looked up until you press
  **Look up on the web** (**Read Granola's note** is your own action, so it still looks them up).
- The key is only ever sent to `https://public-api.granola.ai`, never shown, logged or sent to the browser. Redirects aren't followed.

**Untested against a real Granola account.** Built from Granola's API reference and tested against a fake server. Unconfirmed:
whether `calendar_event_id` is the Google Calendar event id (MOAB falls back to the start time and guests), and how long Granola
takes to finish a note.
