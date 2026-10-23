# MOAB

A call-prep agent for Chris (Spotify Backstage sales). It reads your real calls from Google Calendar, keeps its own records on this PC, and writes a brief for each call: who is on it, what changed since you last met, their Backstage situation, and how to open.

## Try it without installing

https://goofturtles.github.io/moab/?demo=1 shows MOAB with made-up sample calls. Nothing is connected and nothing leaves your browser.

## Run it with your own calendar

Each person runs their own copy on their own computer. Your calendar sign-in, Claude key, CRM keys and MOAB's notes are saved in the `.data/` folder next to `server.py`. That folder is git-ignored and never served, so none of it goes to GitHub or to anyone else using MOAB.

1. Install Python 3.11 or newer.
2. In this folder, run `pip install -r requirements.txt` (only needed for the Claude features).
3. Run `python server.py` (on a Mac: `python3 server.py`).
4. Open http://localhost:3576. `--port 3580` runs it on another port.

The first time, Home shows **Connect your calendar**. Setting up the Google sign-in once takes about ten minutes: follow [docs/GOOGLE-SETUP.md](docs/GOOGLE-SETUP.md). The Claude key is pasted in Settings and stays in `.data/`.

## Three modes

| Mode | When | Data |
|---|---|---|
| Live | Google Calendar is connected | Your calendar (next 14 days, events with at least one guest from outside your company) + MOAB records + public data |
| Connect | Nothing connected yet | No calls; Home shows the connect card |
| Demo | URL has `?demo=1` (the "Look around with sample data" link) | The made-up calls in `data/sample.js`, labelled "Sample" everywhere |

## Where the data comes from (live mode)

| Tag | What | Where it lives |
|---|---|---|
| Your calendar | Calls, guests, invite text, Meet codes | Google Calendar, read-only, cached for 60 seconds |
| Your calendar | Job-change and first-meeting alerts | Worked out from your past 6 months of meetings (same name, new company domain; no past meetings with a company) |
| MOAB records | Company status and notes, people's titles and notes, call notes, accepted after-call updates | `centralize/.data/records.json` on this PC |
| Public data | Backstage adopters list, releases, security notices, rival prices | GitHub and versions.backstage.io (saved copy in `data/snapshot.js`) |
| HubSpot | Company status (open deal stage, Customer, or New lead), employee count, deals, the last 5 notes (as history), guests' job titles | Your HubSpot, read with a private app token, cached 10 minutes |
| Gong | "Last call in Gong" on the brief and the company page: date, title, length, Gong's brief, key points, topics, trackers, a link to the call | Your Gong, read only, last 180 days, cached 10 minutes. Transcripts only when you turn on **Read Gong transcripts** (see below) |

Companies are named from the guests' email domain (`northwind-freight.com` becomes "Northwind Freight"). Saving a company's status on its page ties the domain to that name. Personal mail (gmail.com, outlook.com and so on) gives no company; the call is named after the event title.

Fill in what the calendar can't know: **Edit** next to a person in a brief (title, note) and **Edit** on a company page (status, notes). Accepted updates in **After the call** are saved to the records too.

`.data/` also holds the Google client (`google-client.json`) and your sign-in (`google-token.json`). It has its own `.gitignore` (`*`), the server never serves it, and nothing in it reaches the browser.

## HubSpot and Gong

Optional. Follow [docs/HUBSPOT-SETUP.md](docs/HUBSPOT-SETUP.md) and [docs/GONG-SETUP.md](docs/GONG-SETUP.md), then save the credentials with
`tks-spotify/.venv/Scripts/python.exe -I tks-spotify/centralize/tools/connect.py` (asks with no echo, writes `.data/hubspot.json` and `.data/gong.json`;
or set `HUBSPOT_TOKEN`, `GONG_ACCESS_KEY`, `GONG_ACCESS_SECRET`, `GONG_BASE_URL`). Restart the server. The Data page shows each connection,
which portal or workspace, the last sync and the last error.

- **HubSpot first**: a guest's job title comes from HubSpot; invitee research only runs for guests HubSpot has no title for. A title you
  type in MOAB still shows, and is offered to HubSpot after the call. When HubSpot sets a company's status, the company page's Edit keeps notes only.
- **Save to HubSpot** (After the call tab): shows exactly what it will write (one note with your call notes on the company, linked to the
  call's contacts and the open deal, plus the title changes you tick) and writes only when you press the button. Nothing is ever written on its own.
- **Gong stays here**: Gong's summaries are not sent to Claude unless you turn on **Use Gong notes in AI answers** in Settings > Research sources and privacy (off by default; saved in the records).
- Credentials never reach the browser, `live.js`, any response or the log. Redirects are not followed, and the Gong key is only sent to https addresses on gong.io.
- One failing source never breaks the page: MOAB waits once on a 429, then pauses that source for a minute and shows the error on the Data page.
- Company names still come from the guests' email domain (or your records), not from HubSpot's name for the company.

Untested against a real account: everything HubSpot and Gong. Built from HubSpot's developer docs and Gong's public help pages and tested
against fake servers; the docs list the parts that couldn't be confirmed (pipeline stages, associations v4, note scopes, Gong's content field names).
Try one Save to HubSpot on a test company first.

## Who is this new person? (automatic invitee research)

When a call has a guest MOAB hasn't looked up, a background worker on the server finds who they are, one person at a time. With a Claude key it uses Claude with web search to find their current title, team, seniority, roughly how long they have been at the company, and their relationship to it (employee, contractor or agency, partner, investor or board, other, unknown), with one to three public sources. The brief's "Who's on the call" and the in-call panel's People tab show it with a **Found automatically** tag, the source links, and **Confirm** / **Edit**. A new person also gets an alert: "New on the Acme call: Name, Title".

The rules, enforced in `server.py` (and tested):
- Claude gets only the guest's display name, the company name and the company's domain. Never their email address or any part of it. Guests with no full name on the invite are not looked up.
- People-search and contact-data sites (ZoomInfo, RocketReach, Apollo, Spokeo and others) are blocked in the search tool, and any source on them is dropped. Work information only: no personal contact details, family, age, photos or personal social media.
- A field is kept only when a source backs it. Anything unsourced, unsure or unreadable becomes "unknown", never a guess.
- Guests on personal mail (gmail.com, outlook.com and so on) and your own colleagues are never looked up on the web.
- Once looked up, nobody is looked up again for 30 days unless you press **Look up again**. What you type or confirm is never overwritten.

Without a key MOAB shows local facts only (company from the email domain, whether that company is on the public Backstage adopters list, whether you have met them before) and the note "Add a Claude key to look up titles automatically". Results live in `.data/records.json` under `people`. In demo mode, Elena Cruz shows a made-up example, tagged Sample.

## Who did they mention? (people mentioned on the call)

**After the call** has a **Mentioned on the call** section (and the tab shows a count). Drop or paste a Zoom or Google Meet transcript
(.vtt, .srt or .txt, up to 1 MB), press **Use my call notes** (the in-call panel's notes and the notes box), or, with **Read Gong transcripts**
on (Settings > Research sources and privacy, off by default), **Read Gong's transcript**. MOAB lists each person who was talked about, with the sentence they came up in,
who said it and when.

- **Found here, not elsewhere**: the server finds the mentions with plain rules: names MOAB already knows at that company (your calendar,
  MOAB records, HubSpot contacts on the company's email domain, people you added from earlier calls), new full names ("Maria Gomez"),
  a first name with a role or team ("Maria from security", "Dana who runs procurement") and roles alone ("our new CTO", "the VP of Platform").
  It skips the call's guests, you, and products and companies (Backstage, Portal, Spotify...), and "our CTO" from you (that's Spotify's).
  If Chrome has its built-in AI, the page also asks it for names on this PC; the server keeps a suggestion only if the name is really in the transcript.
- **The transcript isn't kept**: it is read in memory and dropped. `records.json` keeps, per call, only each mention and one sentence (speaker and time).
- **Looking them up**: people MOAB knows show at once. Anyone else goes to the same background worker as invitee research (Claude with web search,
  the same blocked people-search sites, sourced-or-unknown). Claude gets only the name or first name, the role or team words, the company name and
  its domain: never the transcript or the sentence. A full name with one clear match shows **Found**; a first name or a role shows up to 3
  candidates (title, sources, why they fit) and you **Pick**, unless exactly one sourced match fits the name and the team said with
  it (then **Found automatically**, see below). Nothing solid shows **Not found**.
- **Actions**: Confirm, Pick, None of these, Look up on the web, **Add to MOAB records** (MOAB then knows them on the next transcript) and
  **Save to HubSpot** as a contact (HubSpot connected only; shows exactly what it writes: first and last name, job title, link to the company;
  never an email or phone number; writes only on the button; refuses if HubSpot already has a contact with that name).
- **Use transcripts in AI answers** (Settings > Research sources and privacy, off by default): only when on, Ask MOAB also sees who was mentioned on the call and their sentence.
- Demo (`?demo=1`, Northwind call): **Try the sample transcript** shows two made-up mentions (one already known, one found on the web with
  example.com-style sources), tagged Sample. Nothing is sent to the server.

### As it happens: references, companies and connections

- **While the call runs**: in the in-call panel, what you type in Notes is read as you type (only the new text, about half a second
  after you stop; a sentence still being typed waits for its full stop, a 1.5 s pause, or saving). Whatever the note no longer
  says ("John Sm" once it reads "John Smith", "John from product" once it reads "product management") is taken back off the
  list and the map, unless you confirmed, picked or removed it. The People tab shows what it finds and asks again every 1.8 s
  while something is being looked up. The note's text is held in the server's memory while you type it and dropped when you
  save it, switch calls, or after 10 minutes without a change; only each mention and its sentence are kept.
- **People**: a first name with a team even with words between them ("talk with John about that from product managing" is John,
  product management), full names, roles alone, and what comes right after ("he owns the roadmap", "she runs procurement").
  One sourced web match for a full name, or for a first name with the team said with it and a source on the company's own
  website, is **Found automatically** (with **Change**); several, a role with no name ("our new CTO"), or one that doesn't
  clearly fit, show the most likely first as **Likely, not confirmed**, and nothing goes on the map until you pick.
- **Companies**: names MOAB knows (the Backstage adopters list, well-known vendors, MOAB records, your calendar's companies,
  HubSpot companies it has read), names after a cue ("switched from", "moving to", "partnered with", "acquired by", "over at"...),
  names ending in Inc, Labs, Systems, AI and so on, and "X's pricing / product". Never the call's own company, Spotify, its
  products, places, days or codenames ("Project Falcon").
- **How they relate**: MOAB first reads the mention's sentence, the next two, and that speaker's next turn ("they're our vendor
  for logging", "we switched from them", "they acquired us", "a partner", "competitor", "customer of ours"). If that explains it,
  it's used at once (**Said on the call**, with the words). If not (the transcript moved on, the note was saved, 2 more sentences,
  or 30 seconds while typing), the web lookup starts at once: Claude gets only the two company names and websites and answers
  customer, vendor, partner, competitor, parent, subsidiary, investor, acquired, acquirer, uses their product, other or unknown,
  with sources (sourced or unknown).
- **Speed**: up to 3 lookups at once (things said on a call go before invitee research), web search at most 3 times, effort low,
  20 seconds per lookup, cached for 7 days by (name, role, company) and by (company, company).
- **Connections**: found people (with their company and what was said about them) and every mentioned company (with its relation)
  are saved in `records.json` under `connections` (source, mention time, call id) and drawn on the People map and the panel's mini
  map at once, marked as mentioned on that call. **Remove** takes a wrong one off (on the map, the panel or After the call) and it
  never comes back on its own; **Add back** undoes it.
- Demo: the sample transcript now also has John (found automatically), Brightwave Systems (explained on the call) and Harborline
  Labs (found on the web, example.com-style sources), and the demo People map shows them. Nothing is sent to the server.

Untested against a real account: Gong's transcript endpoint (`POST /v2/calls/transcript`, speaker names from `/v2/calls/extensive` parties,
needs the `api:calls:read:transcript` scope on the Gong key), HubSpot's `hs_email_domain` contact search, and creating a contact with a company
association (type 279). Try one of each on a test record first.

## Settings

The gear in the left rail (above Data), the avatar menu, or search ("Settings: Brief builder", "dark", "email"...) opens `#/settings`;
each menu has its own address (`#/settings/brief`, `/priorities`, `/panel`, `/followup`, `/mentions`, `/alerts`, `/research`, `/appearance`).
Every change saves at once and the header says **Saved**. Live and connect mode keep them in `.data/records.json` (`settings`); the demo keeps
them in this browser only. Restart `server.py` after updating, or the page can't save them.

| Menu | What it changes |
|---|---|
| Brief builder | Which brief sections show and in what order (opener, since you last spoke, last talk and Gong, Backstage, to-dos, people, security notices, rivals, papers); full or short; opener tone (direct, warm, curious), used by the brief and the in-call panel |
| Account priorities | Target accounts and scoring rules with points (engineers above N, on the adopters list, open deal, recent alert, customer) give a Hot / Warm / Cold badge; Home's "Coming up" and Companies sort by it; Calls has a **By priority** view |
| In-call panel | Which cards show and their order (a tab hides when all its cards are off), compact or full, a live-listening reminder (while Meetily is off), the keyboard shortcuts |
| Follow-up emails | A template per call type (intro, discovery, demo, renewal, other) with `{first_name} {company} {my_name} {next_step} {summary} {date}`. **Draft follow-up** in After the call fills it from the call and your notes; **Copy** or **Open in mail app**. MOAB never sends email |
| Mentions and connections | Automatic look-up (off: notes as you type are refused by the server, and names heard through Meetily or read from Granola by MOAB itself after the call are listed but not looked up until you press **Look up on the web**, even ones already waiting to be looked up; transcripts you add after the call, and **Read Granola's note**, still are), which kinds of mentioned connections the People map draws, the auto-add rule (only clear matches, or also the most likely match, marked "Likely" on the map) and how long the call's sentences are kept (older ones are dropped, also before the People map loads and as soon as you lower it, and Granola's summary with them; the mention, its relation and web sources stay) |
| Alert rules | Which signals make alerts (job changes, new invitees, people mentioned, security notices, new Backstage release, HubSpot stage changes), the security level, instant or a daily digest (one card per day on Home, one section per day on Alerts), quiet hours (the badge and pop-ups wait) |
| Research sources and privacy | Web research (off also stops lookups of people and companies mentioned on a call; queued ones, guests' too, are dropped unsent), HubSpot, Gong, Meetily and Granola (both off by default) on or off, the three former Data-page switches, what may go to Claude (titles only / + call notes / + transcripts), extra blocked sites on top of the built-in list |
| Appearance | Light or dark, accent colour (indigo, green, blue, pink, orange), comfortable or compact; set before the first paint |

## How they're connected (click to explain)

Every connection or mention found on the web or said on a call opens a card: on the People map (click the line's label, or the
person or company), in After the call and in the in-call panel's People tab (**How they're connected**). It shows the relation type,
one to three plain sentences on what the connection is (what, for which team or product, since when), each numbered to its source,
short quotes from those sources (25 words at most) with links and dates, what was said on the call, where and when it was found, and
the confidence. Claude's answer must cite a source for every sentence; a sentence whose sources were dropped (blocked, or never in
the search results, or a site you block later) is dropped too, so with nothing left the card shows only the relation type. A quote
shows only when the web search's own citations of that page hold those words, and the date is the one the search gave for the
page, never only Claude's word. Results saved before this still show.

## Live and after-call sources, and the Chrome side panel

- **Meetily** (free, local, live): with it on, the server reads Meetily's `transcripts.json` on this PC every 2 seconds while it
  records, feeds new lines to the same mentions pipeline as notes typed during the call, and the panel says **Listening via Meetily**.
  Read-only, local files only, nothing sent anywhere. Setup and details: [docs/MEETILY-SETUP.md](docs/MEETILY-SETUP.md).
- **Granola** (after the call): personal API key via `tools/connect.py granola` (or `GRANOLA_API_KEY`); with it on, MOAB reads the
  note and transcript of calls that ended 5 minutes to a day ago (or on **Read Granola's note**) and shows **From Granola** in After the
  call. The transcript isn't kept. [docs/GRANOLA-SETUP.md](docs/GRANOLA-SETUP.md).
- **Chrome extension** (`extension/`, load unpacked): opens the in-call panel in Chrome's side panel on Google Meet and Zoom web calls,
  on the call matching the tab's meeting code. The server lets only its own pages and this extension frame the panel.
  [docs/CHROME-EXTENSION.md](docs/CHROME-EXTENSION.md). Icons: `tools/make_icons.py` draws them from the logo.

Untested against the real thing: Meetily (built from its source code), Granola's API (built from its API reference) and the extension
in a real Chrome profile. All three are covered by fakes in the tests.

## AI

- **Claude**: set `ANTHROPIC_API_KEY` before starting the server. Claude adds a summary to each brief and answers questions in the search box (Ask MOAB). The key stays on the server.
- **On this device**: with no key, Ask MOAB uses Chrome's built-in AI (Prompt API) when the browser has it.
- **Rules**: otherwise MOAB answers from its own records.

Every answer says which one answered. The brief itself is always written by built-in rules.

## Endpoints (server.py)

| Endpoint | What |
|---|---|
| `GET /api/status` | `{claude, google: {configured, connected, email}, ai: {claude}, hubspot: {configured, connected, portal, lastSync, lastError}, gong: {configured, connected, workspace, lastSync, lastError}}` |
| `GET /data/live.js` | `window.MOAB_LIVE = {...}` (same shape as `data/sample.js`) or `null` |
| `GET /auth/google`, `GET /auth/google/callback`, `POST /auth/google/disconnect` | Google sign-in (PKCE, single-use state), and revoke |
| `GET /api/records`, `PUT /api/records/company`, `PUT /api/records/person`, `PUT /api/records/call-notes`, `POST /api/records/apply` | MOAB records. Writes need the `X-MOAB: 1` header and this page's own Origin |
| `GET /api/research`, `POST /api/research {email}` | Invitee research status per guest (pending, done, unknown, skipped, error); ask for one guest to be looked up again. Same guards as the records |
| `GET /api/settings`, `PUT /api/settings {group: {...}}` | Every setting (`settings`, with `defaults`); save one or more groups, partial groups merge. Each value is checked (unknown keys, wrong types, out-of-range numbers and lists that are too long get a 400), at most 64 KB (413). Same guards as the records |
| `PUT /api/records/settings {gongInAI, gongTranscripts, transcriptsInAI}` | The Data-page settings (each off by default; send one or more). Same guards as the records |
| `POST /api/mentions {callId, text, filename, lines, hints, source}` | Read a transcript (text up to 1 MB, .vtt/.srt/.txt, text only; or lines; or `source: "gong"`), find the mentions here, queue web lookups. Returns the call's mentions. Same guards; 413 over the size limit |
| `GET /api/mentions?callId=` | The people (`items`: pending, found, known, pick, notfound, error, nokey) and companies (`orgs`: waiting, pending, said, found, unknown, error, nokey) mentioned on one call, and its connections (`graph`). `GET /api/research` also lists their statuses under `mentions` |
| `POST /api/mentions/live {callId, segment, offset, text, final, pause}` | The new part of a note typed in the in-call panel (text up to 4,000 characters, the whole note up to 8,000). Same guards. Returns the call's mentions; 409 `resend` if the server lost the note |
| `POST /api/mentions/pick {callId, id, action, index}` | People: `pick` (with `index`), `confirm`, `none`, `again` (look up on the web), `add` (to MOAB records), `remove` / `restore` (the map connection). Companies: `again`, `remove`, `restore` |
| `POST /api/mentions/hubspot {callId, id, confirm, planId}` | Save one mentioned person to HubSpot as a contact: without `confirm` only the preview, with `confirm: true` and its `planId` the write |
| `POST /api/hubspot/save {callId, note, titles, confirm, planId}` | Without `confirm`: what would be written (nothing is), with its `planId`. With `confirm: true` and that `planId`: write it (409 if HubSpot changed since the preview). Same guards as the records |
| `GET /api/meetily?callId=`, `POST /api/meetily/pick {callId}` | Whether MOAB is listening through Meetily and for which call (no transcript text); pick the call Meetily's recording belongs to. Same guards |
| `POST /api/granola/fetch {callId}` | Read Granola's note for one call now (only with Granola on and a key saved). Same guards. `GET /api/mentions` carries it as `granola`, and every mention as `explain` |
| `POST /api/ask`, `POST /api/brief` | Claude, only when a key is set. Gong content is dropped unless the setting is on |

## Tests

```
tks-spotify/.venv/Scripts/python.exe -I tks-spotify/centralize/tools/test_live.py
```

Fake data only, no network: event mapping, company naming, job changes, live.js escaping, OAuth state and PKCE, records validation, the write guard, invitee research (with a fake Claude: no email in the request, blocked sites, personal mail skipped, unsourced answers become unknown, your fields never overwritten, the 30-day rule, the alert, and the endpoint guards), and HubSpot and Gong with fake HTTP (request bodies and auth headers, mapping into the live data, HubSpot-first titles, 401/403/404/429/timeouts, redirects not followed, secrets never in a response, log line or live.js, the save guard and that nothing is written without confirm, Gong kept from Claude unless the setting is on, note escaping, and `connect.py`), and people mentioned on the call (VTT/SRT/TXT parsing; known names, new full names, first name + role, roles; guests, you and products skipped; nothing sent to Claude until the worker runs and then only name, role, company and domain; ambiguous answers never auto-picked; blocked and unsourced candidates dropped; only quotes saved, never the transcript; Gong transcripts only with the setting on; transcripts kept from Ask MOAB unless that setting is on; the route guards and size limits; HubSpot contacts written only on confirm), and references and connections (the John example with words between name and team,
company cues and skips, a follow-up used with no lookup, no follow-up queued at once, at most 3 lookups at once with call mentions first,
one match found automatically vs several "Likely, not confirmed", connections in the live data and removed ones staying removed, only
names/roles/company names/domains sent, codenames, and live notes read as you type), and settings (the page's defaults and blocked list match the
server's, every kind of bad value refused and nothing saved, partial groups merged and kept, the former Data-page switches, the route guards and the
64 KB limit, alert rules dropping job changes and new invitees, HubSpot stage changes, "titles only" keeping notes from Claude, your blocked sites in
the search tool, HubSpot off sending no HubSpot request, and web research off refusing a lookup), the mentions settings (automatic
look-up off, only clear vs likely matches on the map, old quotes dropped, web research off stopping people and company lookups even
once queued), explanations (only sourced sentences kept, quotes cut to 25 words, dates checked, old results still render), Meetily
(fake recording folders: off by default, live lines fed to the running call, matching by time or the picked call, finished and crashed
recordings ignored, only your calendar requested), Granola (fake API: Bearer key only to public-api.granola.ai, the matching note, a
paged long transcript, once per call, the key never shown) and the Chrome extension (permissions and hosts, the fixed id in the frame
allow-list, the meeting codes read from tab addresses).

## Demo mode notes

http://localhost:3576/?demo=1 shows the made-up calls. Add `&live=0` so the public numbers never change mid-demo (it skips the live GitHub refresh). Re-run the snapshot tool on the morning of a demo:
`tks-spotify/.venv/Scripts/python.exe -I tks-spotify/centralize/tools/make_snapshot.py`

## Design references (Mobbin)

Two-part layout: a grey call rail and one reading column. Lightfield and Attio (shell), Sana AI and Calendly (call list), Microsoft Copilot and Skiff (calm reading column), WRITER (the folded "How the agent built this" line), Elicit, StackAI and Profound (live checklist), Rox (number row), Aboard (key/value rows), Calendly recap (after-call updates), GitLab and Surfshark (severity), Homerun (alerts). Connect card: Notion Calendar, Calendly, Tana and Clockwise (links at the bottom of home.css).

Not yet tested: a real Google sign-in and a real Claude call, including a real invitee lookup with web search (no Google client or API key on this PC yet). Do one of each before relying on them. Web search must be allowed for your organization in the Claude Console, and each lookup is billed (a few searches per new guest).
