# MOAB: Asana restyle spec

Status: spec for the builder. Covers the whole app (`index.html`, `base.css`, `styles.css`, `map.css` tokens only, `panel.css`) and the small markup changes in `app.js`, `panel.js`, `core.js` and `index.html` that the look needs.
Do not touch: `server.py`, `data/snapshot.js`, `_headers`, the edge routing and layout code in `map.js`.

Owner's ask: everything Asana style, built from Mobbin references. Accent stays Spotify-ish green `#13773a`. Asana's coral and Asana's blue are never used.

## 0. The eight moves (read this first)

1. **Dark L chrome.** A 48px dark top bar across the full width (brand left, pill search centre, Chris right) and a dark 240px sidebar under it, both `#2e2e30`. Content is flush white, no inset card, no rounded main. (R1, R5, R6)
2. **Full-bleed page headers.** List pages get Asana's header: coloured icon tile + 20px title + source tag + actions, hairline under it, content left-aligned below. (R5, R19, R20)
3. **Tables, not cards.** Calls and Companies become Asana list tables: 36px column header, 44px rows, vertical cell hairlines, coloured tags in cells, day groups as section headers with a caret. (R5, R19, R20, R23)
4. **Home is Asana Home.** Warm grey canvas, centred date + 32px regular greeting + a "my week" stats pill, then white 12px-radius widgets in a 2-column grid. (R1, R2, R3, R4)
5. **Task-pane detail.** The brief reads like Asana's task pane: 24px title, a property list (label column + values with tags and avatars), a bordered Fields table for history and papers, circle checkboxes for the to-do list, an AI-summary-style card for the opener. (R8, R9, R10, R13)
6. **Inbox two-pane.** Alerts become list left + detail pane right at 1240px and up. (R6, R24)
7. **Real faces.** Round photo avatars with white rings in stacks, initials on a soft tint as fallback. (R15, R16, R21)
8. **Soft multi-tint tags.** One tag palette (the map's avatar tints) for status, kind, severity and note type; the green accent only for the primary action, focus, selection, completion and "live". (R10, R19, R20)

## 1. References (Mobbin)

All Asana web unless marked. Open each with `https://mobbin.com/screens/<id>`.

| Code | App | Screen | Mobbin id |
|---|---|---|---|
| R1 | Asana | Home: greeting, My tasks widget, Customize home side panel, dark top bar + sidebar | a28d698c-7c94-4911-b915-109f260f565b |
| R2 | Asana | Home: date + "Good afternoon" + My week stats pill, half-width My tasks widget with project tags | a5ed698c-76eb-42e5-a67d-b42a46c194bc |
| R3 | Asana | Home: My recent projects + My goals widgets (progress bars, status dots) | c10b3360-7af2-4369-9c05-f103edddd3ce |
| R4 | Asana | Home: People + Goals widgets, widget "..." menus | a3d396ba-3f53-4ce6-98de-a05f7748b7f3 |
| R5 | Asana | My tasks: List view table, section header with caret, column headers, tags, due dates | 19c79bba-61d9-4d51-977a-5828e1efe4c9 |
| R6 | Asana | Inbox: Activity feed, day groups, notification cards, unread dots | c7bcaf87-9928-407c-823a-bc1491fe566d |
| R7 | Asana | Inbox: Archive empty state (centred title, one line, one button) | 193a0993-dd77-46f1-9a39-94211f27342d |
| R8 | Asana | Project list + task detail pane: property rows, Fields table, Priority tag | 95d319c8-e44a-48e0-bb32-83937d98ba96 |
| R9 | Asana | Task pane: description, subtasks with circle checks, comment composer | fabf1d06-c847-4771-b7aa-11e3aaf3d9d6 |
| R10 | Asana | Task pane: Priority/Status tags, list sections To do / Doing / Done | bfe4aa10-a69d-4bb4-976a-ca14365c9c59 |
| R11 | Asana | Toast bottom-left with green top bar, link and Undo | 9961fa58-cb22-40cc-9e41-2630481683c9 |
| R12 | Asana | Project overview: grey right status column, status report card, timeline | b0b12539-4b72-4c9c-9618-7169c9cc6d9b |
| R13 | Asana | Project overview: AI summary card, Project roles row, status buttons | de177dce-059a-4a3f-870f-1a500e38070f |
| R14 | Asana | Project dashboard: bordered number tiles | 3696afeb-c25f-4883-8666-06e5ae7d2d6f |
| R15 | Asana | Board view: white cards, tags, round photo avatars | 0a9f2bf5-409a-4af8-9493-531dd6868124 |
| R16 | Asana | Profile page: xl photo avatar, widgets, collaborators list | 1599a2ad-30eb-4f68-b489-9e3adc13785b |
| R17 | Asana | Settings dialog: title, tab row, photo, two-column fields | f283219a-803f-46b0-8d82-ca616d263851 |
| R18 | Asana | Settings dialog: textarea, grouped box, toggles, selects | 1979c0a1-c37a-4921-81b7-b864553ec27a |
| R19 | Asana | Portfolio list table: status pill with dot, progress, Priority tag, owner | 8090ad93-eeb8-4eb9-8a48-0288e8943fc2 |
| R20 | Asana | Project list table: Priority and Status tag columns, assignee avatars | 2f0846fd-871b-491c-a6f2-7d1f26e6de62 |
| R21 | Asana | Search dropdown: filter chips, Recents rows with icons and avatar stacks | c5378cb7-107c-4ff5-82fd-b4724ac229d4 |
| R22 | Asana | "Add child" modal: chips, search field, result list | 64507e78-589b-47f3-aba2-09ee0584d9f6 |
| R23 | Asana | Goals table: status, progress, time period, owner columns | 81f00b5e-3f3d-429b-bd3c-60288c086d28 |
| R24 | Asana | Team Members table + right member pane (two-pane) | e49f6252-d743-499b-9325-a0d4afb863b7 |
| R25 | Asana | "Remove member" confirm modal (header, body, right-aligned buttons) | f3c90d7e-9635-426d-8cd6-fcd680367362 |
| R26 | Asana | Admin Users table: avatar + name + email two-line cells | 1ffe79b9-8b5e-460c-b0c4-21fd04e2cf14 |
| R27 | Asana iOS | Home: greeting + stacked cards (phone layout) | 53b9bc89-e6fe-4844-8476-93e1ad99d0c5 |
| R28 | Asana iOS | Home: project card with stat tiles | 0181c618-16c6-4cfb-808e-fe2ba2207a4d |
| R29 | Attio | Company record: tabs + "Record details" side panel (property list) | f92e1b4f-fe5f-4382-a2c2-33c7abde5fc4 |
| R30 | Attio | Activity: "changed Stage → Meeting" attribute-change rows | d76ba56f-98c3-463f-9e1d-bbe4831ee47a |

Asana has no in-call side panel and no "what changed" record diff. Those two come from Attio (R29, R30), styled with Asana's tokens.

## 2. Tokens

Replace the `:root` block in `base.css` with this. Remove the `:root` line at the top of `styles.css` (its four sizes move here).

Warning: `--rail` keeps its old meaning, the light grey surface used by `.band`, `.tile-date`, `.p-note`, hovers and so on. It is NOT the sidebar colour. The dark sidebar and top bar use the new `--chrome*` tokens. Setting `--rail` dark would turn every grey surface dark.

```css
:root {
  /* Chrome: Asana's dark L, top bar + sidebar (R1, R5) */
  --chrome: #2e2e30;
  --chrome-hover: #3d3d3f;
  --chrome-active: #4a4a4d;
  --chrome-line: #444446;
  --chrome-field: #48484b;        /* search pill */
  --chrome-field-hover: #545457;
  --chrome-ink: #f5f4f3;          /* 12.9:1 on --chrome */
  --chrome-muted: #a8a6a7;        /* 5.4:1 on --chrome */
  --chrome-focus: #6fcf97;        /* 7.1:1 on --chrome; focus ring and "public" dot on dark */

  /* Surfaces */
  --bg: #ffffff;
  --canvas: #f6f5f4;              /* Home background */
  --rail: #f9f8f8;                /* legacy name = light grey surface */
  --surface-2: #f9f8f8;           /* table heads, asides, quote blocks */
  --hover: #f9f8f8;               /* row hover */
  --press: #f1f0ef;               /* button hover, active option, pressed */
  --chip: #efedec;                /* neutral tag */
  --selected: #edf6f0;            /* selected row (green tint, replaces Asana's blue #edf1fc) */
  --line: #edeae9;                /* hairlines */
  --line-2: #e0dcdb;              /* stronger dividers */
  --btn-line: #cfcbcb;            /* secondary button border */
  --field: #8c8a89;               /* input + checkbox border, 3.4:1 on white (WCAG 1.4.11) */
  --field-hover: #6d6e6f;
  --dot: #c9c6c5;

  /* Text */
  --ink: #1e1f21;                 /* 16.1:1 */
  --ink-2: #48494b;               /* 9.0:1 */
  --muted: #6d6e6f;               /* 5.1:1, also placeholders */
  --faint: #a2a0a2;               /* disabled and decorative only, never body text */

  /* Accent: the only brand colour */
  --accent: #13773a;              /* white text on it 5.6:1 */
  --accent-hover: #0f6630;
  --accent-press: #0c5527;
  --accent-bg: #eaf5ee;
  --accent-line: #b9dcc5;
  --danger: #b42318;
  --danger-bg: #fde0e0;

  /* Tag tints, bg + ink. Same values as TINTS in map.js so avatars, tags and the board agree. All inks >= 6:1 on their bg. */
  --tag-gray-bg: #efedec;   --tag-gray-ink: #48494b;
  --tag-green-bg: #d8f3e3;  --tag-green-ink: #166534;
  --tag-blue-bg: #dce8ff;   --tag-blue-ink: #1e40af;
  --tag-purple-bg: #ebe3ff; --tag-purple-ink: #5b21b6;
  --tag-orange-bg: #fde4da; --tag-orange-ink: #9a3412;
  --tag-yellow-bg: #fff1c9; --tag-yellow-ink: #854d0e;
  --tag-pink-bg: #ffdeed;   --tag-pink-ink: #9d174d;
  --tag-teal-bg: #d5f2f6;   --tag-teal-ink: #155e75;
  --tag-red-bg: #fde0e0;    --tag-red-ink: #a3201a;

  /* Elevation: neutral shadows only, never coloured */
  --scrim: rgba(30, 31, 33, 0.40);
  --shadow-card: 0 1px 2px rgba(30, 31, 33, 0.06);
  --shadow-raise: 0 1px 2px rgba(30, 31, 33, 0.06), 0 4px 12px rgba(30, 31, 33, 0.08);
  --shadow-pop: 0 0 0 1px rgba(30, 31, 33, 0.06), 0 6px 20px rgba(30, 31, 33, 0.14);
  --shadow-modal: 0 0 0 1px rgba(30, 31, 33, 0.06), 0 16px 48px rgba(30, 31, 33, 0.22);

  /* Radii */
  --r-sm: 4px;    /* tags, kbd, code */
  --r-md: 6px;    /* buttons, inputs, nav items, menu options, icon tiles 24-28 */
  --r-lg: 8px;    /* cards inside content, Fields table, inbox cards, board cards, icon tiles 32-40 */
  --r-xl: 12px;   /* home widgets, dialogs, the hero card, setup boxes */
  --r-full: 999px;/* avatars, status pills, search pill, chips */

  /* Layout */
  --appbar-h: 48px;
  --rail-w: 240px;
  --col: 720px;   /* reading column (brief, after, alert detail) */
  --page: 1280px; /* cap for list-page content, left-aligned */
  --home: 1040px; /* home widget grid */

  /* Motion */
  --ease: cubic-bezier(0.2, 0, 0, 1);
  --t-fast: 120ms;
  --t-med: 200ms;
}
```

Spacing scale (px): 4, 8, 12, 16, 20, 24, 32, 40, 48, 64. No other values except 1px hairlines, 2px rings and the 6px avatar overlap.

## 3. Type

Inter only, weights 400 / 500 / 600. Keep `font-feature-settings: "cv11", "ss01"`. Body changes from 15px to 14px (Asana's body size).

| Role | Size / line-height | Weight | Used by |
|---|---|---|---|
| Display | 32px / 1.3 (42px), letter-spacing -0.01em | 400 | Home greeting |
| Title L | 24px / 1.33 (32px), -0.01em | 600 | Brief and After `h1`, `.alert-h`, company `h1` |
| Title | 20px / 1.4 (28px) | 600 | `.page-title`, widget titles, dialog titles, `.map-side h2`, `.alerts-list-head h1` |
| Heading | 16px / 1.5 | 600 | `.sec-head h2`, `.band strong`, `.setup h2`, `.empty h3` |
| Lead | 18px / 1.55 | 500 | opener quote only |
| Body | 14px / 1.5 | 400 | text, rows, cells, nav, inputs |
| Body strong | 14px / 1.5 | 500 (row titles, links in tables) / 600 (person names) | |
| Small | 13px / 1.45 | 400 or 500 | meta lines, `.btn.sm`, `.back`, ghost buttons |
| Caption | 12px / 1.45 | 400 / 500 / 600 | table headers (500), tags (500), timestamps, `.cap` (600) |
| Micro | 11px / 1.45 | 500 / 600 | `kbd`, `.badge`, `.tile-date .m` |

Rules:
- Real text never below line-height 1.3. Line-height 1 to 1.2 is allowed only for digits and single glyphs (`.stat-n` 28px / 1.2, `.tile-date .d` 16px / 1.25, avatar initials 1.3).
- No uppercase labels, no letter-spaced caps. Asana uses sentence case everywhere.
- Numbers in tables, timers and stats use `font-variant-numeric: tabular-nums`.

## 4. Icons, focus, motion

Icons (Lucide, from `ic()`):
- Add `.ic { stroke-width: 1.75px; }` in `base.css`. The CSS property beats the `stroke-width="2"` attribute, so no JS change.
- Sizes: 16px default (nav, buttons md/lg, row icons, palette); 14px in `.btn.sm`, meta lines, `.back`, tags with icons; 12px inside status pills; 20px in empty states; 24px nowhere else.
- Icon colour: `--muted` by default; `--ink` on hover inside nav; `--accent` for done/ok states.

Focus:
- Light surfaces: `:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: var(--r-md); }`
- Dark chrome (`.appbar`, `.rail`): `outline-color: var(--chrome-focus)`.
- Inputs, selects, textareas, `.p-compose:focus-within`: no outline; `border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent);` (reads as a crisp 2px ring, no blur).
- Rows that are links (`.row`, `.pal-opt`): `outline-offset: -2px` so the ring stays inside the row.

Motion:
- Hover and press colour changes: `transition: background-color var(--t-fast) ease, border-color var(--t-fast) ease, color var(--t-fast) ease;`
- Drawer: enters from `translateX(32px); opacity: 0` to rest in `var(--t-med) var(--ease)`.
- `.dialog`, `.palette`: from `translateY(-4px); opacity: 0` to rest in 140ms ease-out.
- Toast: from `translateY(8px); opacity: 0` in 160ms ease-out.
- Phone rail: `transform 180ms var(--ease)`.
- Chevrons rotate 150ms. Progress width 200ms.
- `prefers-reduced-motion: reduce` turns every one of these off (keep the existing block, add the new ones).

## 5. Shared components (`base.css` unless noted)

### 5.1 Buttons (R5 "Add task", R12 "Update status", R25 footer)

| Class | Height / padding | Font | Default | Hover | Active |
|---|---|---|---|---|---|
| `.btn.primary` | 32px / 0 12px | 14px 500 | bg `--accent`, text #fff, no border | `--accent-hover` | `--accent-press` |
| `.btn.secondary` | 32px / 0 12px | 14px 500 | bg #fff, 1px `--btn-line`, text `--ink` | bg `--hover`, border `--field` | bg `--press` |
| `.btn.ghost` | 32px / 0 10px | 14px 500 | transparent, text `--ink-2` | bg `--press`, text `--ink` | bg `--line` |
| `.btn.sm` | 28px / 0 10px | 13px 500 | | | |
| `.btn.big` (= lg) | 40px / 0 16px | 15px 500 | | | |

- Radius `--r-md` (6px) on all. Gap 6px. Icons 16px (14px in `.sm`).
- `:disabled`: opacity 0.5, `cursor: not-allowed`, no hover change.
- `.icon-btn`: 32px square, radius `--r-md`, colour `--ink-2`, hover bg `--press`. In the dark chrome: colour `--chrome-ink`, hover `--chrome-hover`.
- `.link-btn`: colour `--accent`, 500, underline `rgba(19,119,58,0.35)` offset 3px, hover underline `currentColor`. Keep the underline: green on ink is under 3:1, so colour alone cannot mark a link.
- `.ghost-edit` (brief "Edit", "Map"): same as `.btn.ghost.sm`.
- `.more` (widget "All calls →"): 13px 500 `--ink-2`, height 28px, padding 0 8px, radius 6, hover bg `--press` + `--ink`.

### 5.2 Inputs (R17, R18)

Applies to `.input`, `.sheet input/textarea/select`, `.search-box input`, `.quick-check input`, `.notes-box`, `.p-pick select`, `#liveCall`.
- Height 36px (`.input.sm` and toolbar fields 32px), padding 0 12px, radius `--r-md`, border 1px `--field`, bg #fff, 14px.
- Textareas: padding 10px 12px, line-height 1.6; the drawer textarea keeps the mono stack at 13px.
- Hover border `--field-hover`. Focus per section 4. Placeholder `--muted`.
- Search fields with a leading icon: icon 16px at left 10px, centred vertically (`top: 50%; transform: translateY(-50%)`), padding-left 34px.
- `select`: `appearance: none`, `chevronDown` 16px at right 10px, padding-right 32px.
- Remove the inline style on `#liveCall` in `renderLive()` and give it `class="input sm"` with `width: auto`.

### 5.3 Checkboxes: Asana circle checks (R9, R2)

Applies to `.todo-item input`, `.todos input` (18px) and `.p-points input` (16px).
- `appearance: none; border-radius: 50%; border: 1.5px solid var(--muted); background: #fff;`
- The check mark (`::after`) is always visible: unchecked it is drawn in `--muted`; this is Asana's faint check.
- Hover: border and check `--accent`, bg `--accent-bg`.
- Checked: bg `--accent`, border `--accent`, check #fff.
- Checked label text: `--muted` + `text-decoration: line-through` (already wired by `:checked ~ span` / `+ span` selectors).

### 5.4 Tags (Asana custom-field tags; R10, R19, R20)

`.pill` is the tag base:
- `display: inline-flex; align-items: center; gap: 4px; height: 20px; padding: 0 6px; border-radius: var(--r-sm); font-size: 12px; font-weight: 500; line-height: 1.5; white-space: nowrap;`
- Default colours: `--tag-gray-bg` / `--tag-gray-ink`.
- Colour modifiers (new): `.tag-gray`, `.tag-green`, `.tag-blue`, `.tag-purple`, `.tag-orange`, `.tag-yellow`, `.tag-pink`, `.tag-teal`, `.tag-red`, each setting `background: var(--tag-X-bg); color: var(--tag-X-ink);`.
- `.pill.accent` = `.tag-green` but with `--accent-bg` / `--accent` (used for "Best fit" and "Up next").

Meaning map (add one helper in `core.js`, `C.tagFor(kind, value)`, returning the class):

| What | Value | Class |
|---|---|---|
| Company status | starts with "Customer" | `tag-green` |
| | starts with "Open deal" | `tag-blue` |
| | "New lead" | `tag-purple` |
| | "Prospect", past employer, anything else | `tag-gray` |
| Call kind (`kindOf(inv)`) | any | `tag-gray` |
| Severity | critical | `.pill.critical`: solid bg `--danger`, text #fff |
| | high | `tag-red` |
| | medium | `tag-orange` |
| | low | `tag-gray` |
| Alert kind | Security | `tag-red` |
| | Job change | `tag-purple` |
| | other (come-back) | `tag-teal` |
| After-call change kind | Next step | `tag-green` |
| | People | `tag-blue` |
| | Papers | `tag-yellow` |
| | Deal | `tag-purple` |
| | Reminder, other | `tag-gray` |
| Panel note kind | Note | `tag-gray` |
| | Question | `tag-blue` |
| | Objection | `tag-orange` |
| | Next step | `tag-green` |

Company status tags show only the part before the colon (`status.replace(/: .*/, "")`), as the companies table already does.

### 5.5 Status pills (Asana "● On track"; R19, R12)

New `.status-pill`: `height: 22px; padding: 0 8px 0 7px; border-radius: var(--r-full); gap: 6px; font-size: 12px; font-weight: 500; line-height: 1.5;` with a `::before` dot `8px` round in `currentColor`. Colours from the tag tints (`.status-pill.tag-green` etc.).

`.prep` (prep chip from `prepChip()`) becomes a status pill that shows an icon instead of the dot:
- `none` "Not prepped": `tag-gray`, icon `circleDashed` 12px.
- `run` "Working 4/9": `tag-blue`, spinner 12px.
- `done` "Brief ready": `tag-green`, icon `circleCheck` 12px.
- `err` "Stopped": `tag-red`, icon `circleAlert` 12px.
- Shape: height 22px, padding 0 8px 0 6px, radius `--r-full`, gap 4px, 12px 500.

`.state-word` (Data page) becomes a status pill: `.on` = `tag-green` ("Live from GitHub", "In use", "On"); otherwise `tag-gray`.

### 5.6 Source markers

`.src` stays as it is (7px dot + 12px `--muted` label): filled `--accent` = public, hollow `--muted` ring = sample, no dot = guess. Inside the dark chrome: label `--chrome-muted`, public dot `--chrome-focus`, sample ring `--chrome-muted`.

### 5.7 Avatars (R15, R16, R21, R26)

Sizes (new modifiers; `.avatar` with no size = md):

| Class | Size | Initials | Stack overlap | Ring when stacked |
|---|---|---|---|---|
| `.avatar.xs` | 20px | 9px 600 | -6px | 2px #fff |
| `.avatar.sm` | 24px | 10px 600 | -6px | 2px #fff |
| `.avatar` (md) | 32px | 12px 600 | -8px | 2px #fff |
| `.avatar.lg` | 40px | 14px 600 | -8px | 2px #fff |
| `.avatar.xl` | 64px | 22px 600 | n/a | none |

Markup (one helper in `core.js`, used everywhere an avatar appears):
```js
C.avatar = (person, size) => '<span class="avatar ' + (size || "") + '" aria-hidden="true" style="background:' + t[0] + ';color:' + t[1] + '">'
  + esc(initials(person.name))
  + (person.photo ? '<img src="' + esc(person.photo) + '" alt="" width="64" height="64" loading="lazy" decoding="async">' : "")
  + "</span>";   // t = C.tint(person.name)
```
CSS:
```css
.avatar { position: relative; border-radius: 50%; overflow: clip; display: inline-grid; place-items: center; flex: none; line-height: 1.3; }
.avatar img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; object-position: 50% 30%; display: block; }
.stack { display: inline-flex; isolation: isolate; }
.stack .avatar { box-shadow: 0 0 0 2px #fff; }
.stack .avatar + .avatar { margin-left: -6px; }          /* -8px for md and lg stacks */
.stack .avatar:nth-child(1) { z-index: 3; } .stack .avatar:nth-child(2) { z-index: 2; } .stack .avatar:nth-child(3) { z-index: 1; }
```
- The initials sit under the photo, so a missing file falls back to initials on its tint (an `alt=""` image that fails draws nothing).
- Use a box-shadow ring, not a border, so the avatar keeps its size. Remove `.stack .avatar { border: 2px solid #fff }`.
- Tint: move `TINTS` and `tint()` from `map.js` into `core.js` as `C.tint(name)` returning `[bg, ink]`; `map.js` calls `C.tint`. Same hash, same colours, so a person has the same colour on the board and in lists. That is the only change to `map.js` apart from the photo in 5.7 and 7.8.

Photos (the builder adds them):
- One real stock photo (Unsplash or Pexels licence, not AI-generated, not a public figure) per sample person: Priya Raman, Marcus Bell, Elena Cruz, Sam Okafor, Dana Li, Michael Tran, Ava Brooks.
- Save as `img/people/<first>-<last>.jpg`, 192 x 192 px square, face centred with headroom (eyes at about 40% from the top), plain background, JPEG quality 80, 10 to 20 KB each.
- Must be local files: the CSP in `_headers` is `img-src 'self' data:`, so hotlinked images will not load when hosted.
- Add `photo: "img/people/priya-raman.jpg"` (etc.) to each entry in `D.people` in `data/sample.js`, and list photographer, source URL and licence for each in `img/people/CREDITS.md`.
- Chris is a real person, so no stock face for him: his avatar is the letter "C" on `--accent` with white text, everywhere (top bar, video tile, map "You" node: change `.node.you .you-av` background from `--ink` to `--accent`).

Where avatars appear and at which size:

| Place | Code | Size |
|---|---|---|
| Call rows, hero "who" line | `avatarStack()` | sm 24, stacked |
| Calls table People column | `avatarStack()` | sm 24, stacked |
| Brief "On the call" property and start-page `.faces` | `startHead()`, `renderBrief()` | sm 24 |
| Brief "Who's on the call" | `renderBrief()` `.person` | lg 40 |
| Company people + "Used to work here" | `renderCompany()` | lg 40 |
| Palette People results | `palRender()` | xs 20 (replaces the `users` icon) |
| Map cards | `map.js` node markup | keep 36px / 28px compact, add the `<img>` |
| Mock call video tiles | `renderLive()` `.vtile` | 72px (custom, `.vtile .avatar`) |
| In-call panel people | `panel.js` `peoplePane()` | md 32 |
| Top bar (Chris) | `index.html` | sm 24 |

### 5.8 Company tiles and page icons (Asana project icons; R3, R5)

- Company tiles (`.co-tile-sm` 24px radius 6, `.co-head-tile` 40px radius 8, map `.co-tile` 24px radius 7): background and letter colour from `C.tint(companyName)`, letter 600 at 11px / 11px / 16px. No dark tiles (map frames included: `map.js` adds the tint style to its `.co-tile`).
- Page icon (new `.page-icon`): 28px square, radius `--r-md`, tag-tint background, icon 16px in the tint's ink. Per page: Calls `phone` blue, Alerts `bell` orange, Companies `building` purple, People map `network` teal, In-call panel `video` green, Data `database` gray.

### 5.9 Tabs (R5, R6, R12)

`.tabs [role=tab]` (call view) and `.p-tabs [role=tab]` (panel):
- 14px 500 (13px in the panel), colour `--muted`, padding 0, gap 20px (16px in the panel), full bar height, `border-bottom: 2px solid transparent; margin-bottom: -1px`.
- Hover: `--ink`. Selected: `--ink` + underline `--ink`. The panel's underline changes from accent to ink to match.

### 5.10 Rows and lists (R2, R5, R6)

- `.row`: min-height 44px (52px when two lines), padding 8px 12px, gap 12px, `border-top: 1px solid var(--line)`, hover bg `--hover`, selected (`aria-current="page"`) bg `--selected`.
- `.row-title` 14px 500 `--ink`; `.row-sub` 13px `--muted`.
- `.row .chev` stays hidden until hover/focus.
- `.icon-tile` (alert rows): 28px, radius `--r-md`, bg tag tint of the alert kind, icon 14px in the tint ink. No border.
- `.unread-dot`: 8px, `--accent`, placed at the far right of the row (Asana puts the unread dot at the right edge). In `.alert-row`, move it from the title start to just before `.row-right`.
- `.tile-date`: 40 x 44px, radius `--r-lg`, bg #fff, border 1px `--line`, month 11px 500 `--muted`, day 16px 600 `--ink`.

### 5.11 Tables (R5, R19, R20, R23, R26)

Shared rules for `.list` when it holds a `.thead` (Calls, Companies):
- No outer box: remove border, radius and the 24px top margin from `.list`. The table has `border-top: 1px solid var(--line)` and no side borders.
- `.thead`: height 36px, padding 0 12px, bg #fff, `border-bottom: 1px solid var(--line)`, 12px 500 `--muted`. Column labels are plain text, left-aligned; numbers right-aligned (`.num-cell`).
- Cells: every cell except the last gets `border-right: 1px solid var(--line)` and `padding: 0 12px`; the row has padding 0 (cells carry it). Row min-height 44px.
- Row hover bg `--hover`. The whole row stays one link via `.stretch::after`; inner links keep `.lift`.
- `.band` becomes an Asana section header: height 44px, padding 0 12px, no background, no bottom border, `chevronDown` 16px `--muted` (decorative, `aria-hidden`), then day in 16px 600 `--ink`, then the "Up next" `.pill.accent`, then relative day in 13px `--muted` pushed right. 16px space above every band except the first.
- `.list-foot`: 12px `--muted`, margin-top 12px.

### 5.12 Widgets and cards (R1 to R4, R13, R14)

- `.widget` (new, home): bg #fff, border 1px `--line`, radius `--r-xl`, `box-shadow: var(--shadow-card)`, overflow visible.
- `.widget-head` (new, replaces `.home-head` inside widgets): height 56px, padding 0 20px, flex, gap 12px; `h2` 20px 600; right side `.more`.
- Widget body rows: `.widget .rows { padding: 0 12px 8px; }` rows radius `--r-md`, `.widget .row:first-child { border-top: 0; }`.
- `.box` (setup boxes, "Before your calls"): same skin as `.widget`. `.box-head`: height 56px, padding 0 20px, `h2` 16px 600, `.done-count` 13px `--muted`.
- `.stats` number tiles (R14): grid of equal columns, gap 12px; each `.stat` is a card: border 1px `--line`, radius `--r-lg`, padding 16px, centred text; `.stat-label` 12px 500 `--muted`; `.stat-n` 28px / 1.2 600, tabular, margin 6px 0 4px; `.stat-sub` 12px `--muted`. Remove the left-border dividers and the first-child padding rules.

### 5.13 Fields table and property list (R8, R29)

`.kv` becomes Asana's Fields table (brief history and papers, company history and papers):
```css
.kv { display: grid; grid-template-columns: 160px minmax(0, 1fr); gap: 0; border: 1px solid var(--line); border-radius: var(--r-lg); overflow: clip; }
.kv dt { padding: 8px 12px; font-size: 13px; font-weight: 500; color: var(--muted); line-height: 1.5; border-right: 1px solid var(--line); }
.kv dd { padding: 8px 12px; font-size: 14px; line-height: 1.5; display: flex; gap: 8px; align-items: flex-start; }
.kv dt:not(:first-of-type), .kv dt:not(:first-of-type) + dd { border-top: 1px solid var(--line); }
```
`.kv.small` becomes the borderless property list (task pane top fields; start page "The agent will use", alert Details, Data estimates):
`grid-template-columns: 140px minmax(0, 1fr); gap: 0 16px; border: 0; border-radius: 0;` dt and dd `padding: 6px 0; border: 0;` dt 13px 500 `--muted`, dd 14px `--ink`.

New `.props` (brief header, see 7.3) uses the `.kv.small` rules with rows min-height 36px and `align-items: center`.

### 5.14 Dialogs (R17, R18, R25, R22)

Shared (`dialog`, `.sheet*`):
- `dialog`: border 0, bg #fff, `box-shadow: var(--shadow-modal)`; `::backdrop` `--scrim`.
- `.sheet-head`: min-height 56px, padding 0 12px 0 24px, border-bottom `--line`; `h2` 20px 600.
- `.sheet-body`: padding 24px.
- `.field-label`: 13px 500 `--ink-2`, margin 20px 0 6px (0 on first). `.help`: 13px `--muted`.
- `.sheet-foot`: padding 16px 24px, border-top `--line`, gap 8px, buttons right-aligned. Keep the DOM order Save then Cancel (Enter in a field submits with the first submit button, which must stay Save) and use `flex-direction: row-reverse; justify-content: flex-start;` so Save sits far right with Cancel to its left.
- `.sheet hr`: `--line`, margin 24px 0.

`#checkDialog.dialog`: width 560px, radius `--r-xl`, margin 96px auto auto, max-height calc(100vh - 128px). Results stats use the number tiles in 5.12.

### 5.15 Drawer (`#drawer`, Asana task pane; R8, R9)

- Fixed right, width 480px (100vw under 640px), full height (`100dvh`), radius 0, `border-left: 1px solid var(--line)`, `box-shadow: var(--shadow-modal)`.
- Head 56px with "Their Backstage" 20px 600 and close `icon-btn`. Body scrolls. Footer pinned (5.14).
- Enter animation per section 4.

### 5.16 Command palette (`#palette`; Asana search dropdown R21)

- Position like Asana's search: it opens where the top-bar search pill is. `width: min(640px, calc(100vw - 32px)); margin: 6px auto auto; border-radius: var(--r-lg); box-shadow: var(--shadow-pop);` backdrop `rgba(30,31,33,0.12)`.
- `.pal-input`: margin 8px, height 40px, padding 0 12px, radius `--r-md`, border 1px `--accent` + `box-shadow: 0 0 0 1px var(--accent)` (it always has focus), gap 8px; icon 16px `--muted`; input 14px; `kbd` "Esc" right.
- `#palList`: padding 0 8px 8px, max-height min(60vh, 440px).
- `.pal-group`: 12px 500 `--muted`, padding 12px 8px 4px.
- `.pal-opt`: min-height 36px, padding 0 8px, radius `--r-md`, gap 10px; icon 16px `--muted`; `.lbl` 14px `--ink`; `.sub` 12px `--muted`; selected bg `--press`; `.enter` icon shows on the selected row only.
- People results show `C.avatar(person, "xs")` in place of the `users` icon; company results show a 20px company tile (radius 5) in place of `building`.
- `.pal-foot`: height 32px, padding 0 12px, bg `--surface-2`, border-top `--line`, 12px `--muted`, radius 0 0 8px 8px.
- `.pal-empty`: 14px `--muted`, padding 24px, centred.

### 5.17 Toast (`#toast`; R11)

- Fixed `left: calc(var(--rail-w) + 16px); bottom: 16px;` max-width 360px; bg #fff; color `--ink`; border 1px `--line`; `border-top: 3px solid var(--accent)`; radius `--r-lg`; `box-shadow: var(--shadow-pop)`; padding 12px 12px 12px 16px; 13px / 1.45; gap 12px.
- Action button ("Open"): `.btn.secondary.sm` look. Close `.x`: 24px icon button, `--muted`, hover `--press`.

### 5.18 Empty states (R7)

`.empty`: max-width 360px, centred, padding 48px 16px. `.empty-tile`: 40px circle (radius 50%), bg `--surface-2`, icon 20px `--muted`; `.ok` variant bg `--accent-bg`, icon `--accent`; margin 0 auto 16px; no border. `h3` 16px 600; `p` 14px `--muted`, margin-top 4px; optional button margin-top 16px.
Inline empties (`.empty-note`, `.no-match`, `.empty-line`) stay as single muted lines at 14px (13px in the panel).

### 5.19 Small bits

- `kbd`: 11px 500, height 18px, padding 0 5px, radius `--r-sm`, border 1px `--line-2`, bg #fff, `--muted`. In the top bar: border `#6a6a6c`, bg transparent, `--chrome-muted`.
- `.badge` and `.nav .count.strong` (unread alerts): min-width 20px, height 18px, radius `--r-full`, bg `--accent`, #fff, 11px 600, tabular.
- `.progress`: 6px tall, radius `--r-full`, track `--line`, fill `--accent` (R3 goal bars).
- `code` (setup steps): 12.5px mono, bg `--surface-2`, border 1px `--line`, radius `--r-sm`, padding 1px 5px.

## 6. Shell

### 6.1 Top bar: `.appbar` becomes the global top bar at every width (R1)

Markup changes in `index.html`: move `.brand` and `#openPalette` out of `#rail` into the header, turn `.brand` into a link, add Chris's avatar. Keep every id.
```html
<header class="appbar">
  <button type="button" class="icon-btn" id="menuBtn" ...></button>          <!-- phone only -->
  <a class="brand" href="#/home"><span class="mark">...</span><span class="brand-name">MOAB</span><span class="pill">Demo</span></a>
  <span class="appbar-title" id="appbarTitle">Home</span>                    <!-- phone only -->
  <button type="button" id="openPalette" class="search-trigger"></button>      <!-- desktop -->
  <button type="button" class="icon-btn" id="appbarSearch" ...></button>       <!-- phone only -->
  <span class="appbar-me" aria-hidden="true" title="Chris (you)"><span class="avatar sm me">C</span></span>
</header>
```
Desktop (1000px and up):
- `position: sticky; top: 0; z-index: 10; height: var(--appbar-h); background: var(--chrome); display: grid; grid-template-columns: var(--rail-w) minmax(0, 1fr) var(--rail-w); align-items: center; padding: 0 12px 0 8px;` No bottom border (top bar and sidebar read as one L).
- `#menuBtn`, `#appbarTitle`, `#appbarSearch`: `display: none`.
- `.brand`: height 32px, padding 0 8px, radius `--r-md`, gap 8px, no underline, hover `--chrome-hover`. `.mark`: 24px, bg `#454547` (the white lines and green dot stay visible on the dark bar; no SVG change). `.brand-name`: 15px 600 `--chrome-ink`. Demo pill: bg `--chrome-active`, `--chrome-ink`, 11px 500.
- `#openPalette.search-trigger`: `justify-self: center; width: 100%; max-width: 560px; height: 32px; border: 0; border-radius: var(--r-full); background: var(--chrome-field); padding: 0 8px 0 12px; gap: 8px;` icon 16px and "Search" 14px in `--chrome-muted`; `kbd` at right. Hover `--chrome-field-hover`.
- `.appbar-me`: `justify-self: end`; `.avatar.me`: sm 24, bg `--accent`, #fff.

### 6.2 Sidebar `#rail` (R1, R5, R6)

- `.shell`: `grid-template-columns: var(--rail-w) minmax(0, 1fr); height: calc(100vh - var(--appbar-h));` `body` bg `--bg`.
- `.rail`: height 100%, bg `--chrome`, padding 12px 8px, colour `--chrome-ink`. Scrollbar thumb `#55555a`.
- `.nav a`: height 32px, padding 0 8px, radius `--r-md`, gap 10px, 14px 400 `--chrome-ink`; icon 16px `--chrome-muted`. Hover bg `--chrome-hover`, icon `--chrome-ink`. Current (`aria-current="page"`): bg `--chrome-active`, 500, icon `--chrome-ink`.
- `.rail-label` ("Records"): 13px 600 `--chrome-ink`, height 28px, padding 0 8px, margin-top 20px, flex centre.
- `.nav .count`: 12px `--chrome-muted`, tabular. `.count.strong`: the badge in 5.19. `.nav .status` (Data "Live"/"Saved"): 12px `--chrome-muted`.
- `.rail-foot`: border-top 1px `--chrome-line`, padding-top 8px, margin-top 8px. `.legend`: 12px, `.src` per 5.6 dark variant.
- Dead CSS: `.nav .initial`, `.nav .day`, `.prep-icon`, `.run-pill` are not rendered by `renderNav()`. Leave them, do not restyle them.

### 6.3 Main

- `.main`: no margin, no border, no radius, bg `--bg`, `height: 100%; overflow-y: auto; scroll-padding-top: 56px;` scrollbar thumb `--line-2`.
- Sticky detail bars (`.topbar`) stick at `top: 0` inside `.main` on desktop.
- Every in-page jump target (`.sec, .bill, .opener, .how, .props`) gets `scroll-margin-top: 64px` (48px bar + 16px) on desktop, so nothing lands under the sticky bar.

## 7. Pages

### 7.1 Page header for list pages (Calls, Companies, Data, In-call panel, Map; R5, R19, R24)

New markup, replacing `.title-row` + `.page-sub` at the top of `renderCallsPage`, `renderCompanies`, `renderData`, `renderLive`:
```html
<header class="page-head">
  <div class="page-head-row">
    <span class="page-icon tag-blue">{ic("phone")}</span>
    <h1 class="page-title" tabindex="-1">Calls</h1>
    {srcTag("Sample data")}
    <span class="grow"></span>
    {page actions, e.g. Companies' "Check any company" secondary sm}
  </div>
  <p class="page-sub">3 calls this week. Open one to prepare it and read its brief.</p>
</header>
```
- `.page`: `max-width: none; margin: 0; padding: 0 24px 96px;`. `.page > :not(.page-head) { max-width: calc(var(--page) - 48px); }`; `.page.narrow > :not(.page-head) { max-width: var(--col); }`; `.page.wide > :not(.page-head) { max-width: 1120px; }`.
- `.page-head`: `margin: 0 -24px 20px; padding: 20px 24px 16px; border-bottom: 1px solid var(--line);` (border spans the full content width).
- `.page-head-row`: flex, gap 10px, align centre, wrap. `.page-title` 20px / 1.4 600. `.page-sub` 14px `--muted`, margin-top 4px, max-width 720px.
- Remove inline `style="margin-top:..."` attributes in `renderAlerts`, `renderLive` and `renderData`; use 20px / 24px margins in CSS.

### 7.2 Home `#/home` (R1, R2, R3, R4; phone R27)

Layout:
- `.home`: `max-width: none; min-height: 100%; background: var(--canvas); padding: 32px 32px 96px;` (the canvas fills the whole scroll area).
- `.home-header`: centred text, max-width `--home`, margin 0 auto 24px. Eyebrow date 14px 500 `--ink-2`. Greeting `.page-title` here is Display: 32px / 1.3 400, margin-top 4px.
- New `.home-stats` (R2 "My week" pill), centred under the greeting, margin-top 16px: inline-flex, height 32px, radius `--r-full`, bg #fff, border 1px `--line`, padding 0 4px. Items `.hs-item`: padding 0 12px, gap 6px, 13px 500 `--ink-2`, icon 16px `--muted`, separated by a 1px x 16px `--line` rule. Items: `phone` "3 calls this week", `circleCheck` "1 brief ready" (count of `prepState === "done"`), `bell` "2 new alerts" (`unreadCount()`, or "No new alerts"). Plain text, not buttons.
- New `.home-grid` wraps everything below the header: `max-width: var(--home); margin: 0 auto; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px;`. Hero and "Before your calls" span both columns (`grid-column: 1 / -1`). "Later this week" and "Alerts" are half-width `.widget`s side by side. Remove `.home-block` margins inside the grid.

Hero `.hero` (the "Up next" widget):
- Skin per `.widget`. Padding 0.
- `.hero-top`: height 56px, padding 0 20px, border-bottom `--line`. `.up-next`: 20px 600 `--ink` "Up next", then its `span` "· Tue, Oct 20, tomorrow" 14px 400 `--muted`. Source tag at right.
- `.hero-body`: padding 20px 20px 0, grid `44px minmax(0, 1fr)`, gap 16px. `.hero-name` 18px / 1.4 600; `.pill.accent` "Best fit" beside it. `.meta` 13px `--muted`, margin-top 2px. `.who`: margin-top 10px, gap 8px, 13px `--ink-2`, sm 24 photo stack.
- `.hero-quote`: margin 16px 20px 0, bg `--surface-2`, radius `--r-lg`, padding 12px 16px, no left border. `.cap` 12px 600 `--muted`; text 14px `--ink-2`; `.opener-full` 16px / 1.5 500 `--ink`.
- `.hero-actions`: padding 16px 20px 20px, gap 8px. Primary 32px. `.hint` 12px `--muted`, pushed right.

"Before your calls" (`.home-block.box` from `beforeBox()`, R2 My tasks widget):
- `.box-head` per 5.12 with "Before your calls" 16px 600, "2 of 5 done" 13px `--muted`, source tag right.
- `.todo-item`: grid `18px minmax(0, 1fr) auto`, gap 10px, padding 10px 20px, border-top `--line` between items; circle checkbox; text 14px; `small` 12px `--muted` company name; right side tag (source or day `.pill`).
- `.no-list`: padding 10px 20px, 13px `--muted`, border-top `--line`.

"Later this week" and "Alerts" widgets:
- Markup: `<section class="widget"><div class="widget-head"><h2>Later this week</h2><span class="grow"></span><a class="more" href="#/calls">All calls {arrowRight}</a></div><div class="rows">...</div></section>`. Alerts head shows "2 new" 13px `--muted` before the link.
- `.call-row` in a half widget: grid `40px minmax(0, 1fr) auto auto 16px`, min-height 60px. `.bell`: 12px 500 `--muted` with 12px icon. Prep status pill per 5.5.
- `.alert-row`: grid `28px minmax(0, 1fr) auto`, min-height 52px; unread title 14px 500 `--ink`, read title 14px 400 `--ink-2`; reason 13px `--muted` one line; right: date 12px `--muted`, source dot, unread dot.

### 7.3 Calls `#/calls` (R5, R10, R20)

Page header per 7.1 (icon `phone` blue).
Table markup (replace the row template in `renderCallsPage`):
```html
<div class="list cl-list">
  <div class="thead cl-grid"><span>Time</span><span>Company</span><span>People</span><span>Prep</span></div>
  <div class="band">...</div>
  <div class="row cl-row cl-grid">
    <span class="cell cl-time"><b>10:00</b><small>45 min</small></span>
    <span class="cell cl-name"><a class="stretch" href="#/calls/northwind">Northwind Freight</a><span class="pill">Discovery call</span><span class="pill tag-blue">Open deal</span></span>
    <span class="cell cl-people">{avatarStack(inv)}</span>
    <span class="cell cl-prep">{prepChip(inv.id)}</span>
  </div>
</div>
```
- `.cl-grid`: `grid-template-columns: 104px minmax(0, 1fr) 128px 156px;` gap 0 (cells carry padding and the vertical hairlines per 5.11).
- `.cl-time b`: 14px 500 tabular; `small` 12px `--muted` on the same line, gap 6px (single-line row, height 44px).
- `.cl-name`: flex, gap 8px, align centre, min-width 0; link 14px 500 `--ink`, ellipsis; tags never shrink (`flex: none`) and the second tag hides first when space runs out (`.cl-name .pill + .pill` hidden under 1240px).
- Day bands per 5.11. "Up next" pill on the first band.
- `.list-foot` under the table.

### 7.4 Call view `#/calls/<id>` (R8, R9, R10, R13, R14)

Sticky bar `.topbar` (also used by company and alert detail):
- Height 48px, bg #fff, border-bottom `--line`, no radius, z-index 3. `.topbar-inner`: padding 0 16px 0 12px, gap 8px.
- `.back`: `.btn.ghost.sm` look, 13px 500 `--muted`, `chevronLeft` 14px, hover `--press` + `--ink`, margin-right 8px.
- `.tabs` per 5.9, full 48px height.
- Right: `#openInCall` `.btn.ghost.sm` with `panel` icon; `#runAgain` `.btn.secondary.sm` with `rotate` icon.

Reading column `.col`: max-width `--col` (720px), margin 0 auto, padding 32px 32px 96px.

Start state (`renderStart`, before a run):
- `header`: eyebrow 13px `--muted`; `h1` Title L; `.sub` 14px `--ink-2`, margin-top 4px.
- `.faces` (Collaborators row): flex wrap, gap 8px 16px, margin-top 16px; each `li` = sm 24 photo + name 14px `--ink-2`.
- `.start-block`: margin-top 28px; `.cap` 12px 600 `--muted`, margin-bottom 6px; `.start-note` 14px `--ink-2`.
- "The agent will use" = `.kv.small` property list with the Edit ghost button at right of its cap row.
- `#runBtn.btn.primary.big`: full width, 40px, margin-top 28px. `.cap.center` / `.wait-note` 12px `--muted` centred, margin-top 8px.
- `.checks-title` 13px 500, margin-top 28px; `.steps` per below.

Running state: same header; `.using` 13px `--muted`; `.checks-title` with spinner; `.leave-note` 12px `--muted`.

`.steps` / `.step`: grid `20px 236px minmax(0, 1fr)` (unchanged), padding 8px 0, border-top `--line` between steps. `.step-ic`: done = `check` 16px `--accent`; run = spinner `--ink-2`; fail = `x` `--danger`; skip = `minus` `--muted`; wait = 6px `--dot` dot. `.step-label` 14px 500 (wait: 400 `--muted`); `.step-detail` 13px `--muted`.

Brief (`renderBrief`), top to bottom:
1. `.brief-head`: title row with `h1` Title L + "Best fit" `.pill.accent`. Replace the `p.meta` line with a property list (new `.props`, R8 task pane fields):
   ```html
   <dl class="props">
     <dt>When</dt><dd>Tue Oct 20 · 10:00 to 10:45 ET</dd>
     <dt>Kind</dt><dd><span class="pill">Discovery call</span></dd>
     <dt>Status</dt><dd><span class="pill tag-blue">Open deal</span> <span class="muted">Portal</span></dd>
     <dt>Size</dt><dd>About 420 engineers</dd>
     <dt>On the call</dt><dd>{sm avatar + name, for each attendee}</dd>
   </dl>
   ```
   `.props`: `.kv.small` rules, 120px label column, rows min-height 36px, margin-top 16px. Omit rows whose value is missing.
2. `.how` (R8 Fields box, collapsible): margin-top 20px; border 1px `--line`, radius `--r-lg`, no top/bottom-only borders. `summary`: min-height 44px, padding 0 12px 0 14px, gap 8px; `circleCheck` 16px `--accent`; label 14px 500; `.how-meta` 13px `--muted`; chevron right, rotates 90deg open; hover bg `--hover`. Open: `.how .steps` padding 4px 14px 12px, border-top `--line`.
3. `.opener` (R13 AI summary card): margin-top 24px; border 1px `--line`, radius `--r-lg`, padding 16px 20px, `box-shadow: var(--shadow-card)`. `.cap` 12px 600 `--muted`. `blockquote`: no left border, padding 0, margin-top 6px, Lead 18px / 1.55 500 `--ink`.
4. `.recent` "Since you last spoke" (R6 activity): `.since li` grid `24px minmax(0, 1fr) auto`, gap 12px, padding 10px 0, border-top `--line` between; icon in a 24px circle bg `--surface-2`, icon 14px `--ink-2`; text 14px; `.when` 12px `--muted`.
5. `.bill` "Their upgrade bill" (R14): `.sec-cap` row with `.cap` 16px 600 `--ink` and source tag; `.stats` 4 number tiles (5.12); danger numbers `--danger`.
6. `#todo` "Before the call" (R9 subtasks): `.todos` has border-top `--line`; each `li`: flex, align centre, wrap, gap 10px, min-height 40px, padding 6px 4px, border-bottom `--line`; `label` flex 1 1 260px with the 18px circle check and 14px text; `.todo-link` 13px `--accent` link; source tag last.
7. `#people` "Who's on the call" (R13 project roles, R26): `.people` gap 0; `.person` grid `40px minmax(0, 1fr)`, gap 12px, padding 12px 0, border-top `--line` (none on the first); lg 40 photo; `.p-name strong` 14px 600 `--ink`, `span` 13px `--muted`; `.p-key` 14px `--ink-2`, margin-top 2px; `.p-meta`, `.p-quote` 13px `--muted`.
8. `#summarySlot` (Claude summary): same card skin as `.opener`, with `sparkle` 16px before the heading.
9. `.divider` "Details": margin-top 48px; label 14px 600 `--muted`; line `--line`.
10. `#invite`: `.muted-line` 13px; `.note-quote` = description block: bg `--surface-2`, radius `--r-lg`, padding 12px 16px, no left border, 14px `--ink-2`.
11. `#backstage`: paragraphs 14px / 1.6; `.fold summary` 13px 500 with chevron; `.notices li` grid `80px minmax(0, 1fr) auto`, padding 10px 0, border-top `--line`; severity tag per 5.4 (builder: always add the severity class, not only for critical/high); link 14px `--ink`, hover underline; date 12px `--muted`.
12. `#rivals`: `.rival + .rival` margin-top 20px; `.rival-name` 14px 600; source link 13px; `.say-cap` 12px 600 `--muted`, margin-top 10px.
13. `#history` "History and papers": `.kv` Fields table (5.13); ok icons `--accent`, warn icons `--muted`.
14. `#fit` "Which product fits": paragraphs 14px / 1.6; `.fit-other` 13px `--muted`.
15. `.footnote`: margin-top 48px, padding-top 16px, border-top `--line`, 12px `--muted`.

Section rhythm: `.sec` margin-top 40px; `.sec-head` margin-bottom 12px, `h2` Heading 16px 600, source tag and buttons at right (`align-self: center`).

After tab (`#panelAfter`, R9 comment composer, R30 attribute changes):
- `#afterHead`: `h1` Title L + `.meta` 13px `--muted`, margin-bottom 8px.
- `.notes-box`: per 5.2, min-height 168px, radius `--r-lg`. `.help` 13px `--muted`, margin 8px 0 16px.
- `.after-actions`: gap 8px. `#update` primary, `#importNotes` ghost with `panel` icon.
- `#results .sec-head`: title 16px 600, source tag, "Accept all" `.btn.secondary.sm` at right.
- `.changes li`: grid `120px minmax(0, 1fr) 200px`, gap 12px, padding 12px 0, border-top `--line`, align start. `.kind` becomes a tag (`<span class="pill tag-…">Next step</span>` per 5.4). Text 14px. `.actions`: Accept `.btn.secondary.sm` with check, Dismiss `.btn.ghost.sm`.
- Saved: `.done-note` = `.status-pill.tag-green` "Saved" with `check` 12px; Dismissed: `.status-pill.tag-gray` and the text `--muted` + line-through.
- `#tally` 13px `--muted`, margin-top 12px.

### 7.5 Alerts `#/alerts`, `#/alerts/<id>` (R6, R24, R7, R30)

One markup for both routes (replace the two branches in `renderAlerts`):
```html
<div class="alerts-split [has-detail]">
  <div class="alerts-list">
    <div class="alerts-list-head"><span class="page-icon tag-orange">{bell}</span><h1 class="page-title" tabindex="-1">Alerts</h1><span class="n">2 new</span></div>
    <p class="alerts-sub">Signals the agent picked up between calls.</p>
    <div class="rows">{alertRow…}</div>
  </div>
  <div class="alert-detail">
    <!-- with an alert: -->
    <div class="topbar detail-bar"><div class="topbar-inner"><a class="back" href="#/alerts">{chevronLeft}<span>Alerts</span></a></div></div>
    <div class="alert-detail-inner">…eyebrow, h2.alert-h, What changed, Why it matters, action, notices, Details, prov…</div>
    <!-- without one: -->
    <div class="empty"><div class="empty-tile">{bell}</div><h3>Pick an alert</h3><p>See what changed and why it matters for your next call.</p></div>
  </div>
</div>
```
Desktop (1240px and up):
- `.alerts-view`, `.alerts-split`: height 100%. `.alerts-split`: grid `400px minmax(0, 1fr)`.
- `.alerts-list`: border-right `--line`, overflow-y auto. Head: padding 20px 20px 4px, gap 10px; `h1` Title 20px; `.n` 13px `--muted`. `.alerts-sub` 13px `--muted`, padding 0 20px 12px, border-bottom `--line`.
- List rows: `.alert-row` as in 7.2, inset `margin: 0 8px; border-radius: var(--r-md); border-top: 0;` with a 1px `--line` separator drawn by `.alert-row + .alert-row { box-shadow: 0 -1px 0 var(--line); }`; selected (`aria-current`) bg `--selected`.
- `.alert-detail`: overflow-y auto, bg #fff. `.detail-bar .back` hidden (the list is visible). `.alert-detail-inner`: max-width 680px, padding 32px 40px 96px.
- No alert selected: the `.empty` block centred vertically (`.alert-detail { display: grid; place-items: center; }` only in that state).

Under 1240px: `.alerts-split` is a single column. `.has-detail .alerts-list { display: none; }`; `.alerts-split:not(.has-detail) .alert-detail { display: none; }`; the detail bar's back link shows.

Focus: `route()` focuses the first heading it finds, which is now the list's `h1`. When `app.alertId` is set, focus `.alert-h` instead.

Detail content:
- `.alert-eyebrow`: the alert kind as a tag (5.4) + date 13px `--muted`, gap 8px.
- `.alert-h`: Title L 24px, margin-top 8px.
- `.changed` "What changed" (R30 Attio diff, in an R8 Fields box): `h3` 13px 600 `--ink`, margin-bottom 8px; rows sit in a box (border 1px `--line`, radius `--r-lg`); `.changed-row`: grid `16px 180px minmax(0, 1fr)`, gap 12px, min-height 40px, padding 0 12px, border-top `--line` between; key 13px `--muted`; value 14px 500; `.old` `--muted` 400 with line-through, then "→".
- `.why`: `h3` as above; `p` 14px / 1.6 `--ink-2`.
- `.alert-action`: margin-top 20px, secondary button.
- Notices: as brief 7.4 item 11. Details: `.kv.small`. `.prov`: 12px `--muted`, border-top `--line`, padding-top 16px, margin-top 32px.

### 7.6 Companies `#/companies` (R19, R20, R23, R26)

- Page header per 7.1 (icon `building` purple). "Check any company" `.btn.secondary.sm` with `search` icon in the header actions.
- New toolbar row `.toolbar` above the table: height 48px, flex, align centre, gap 8px. `.search-box` moves into it, right-aligned, width 240px, its input 32px tall.
- Table per 5.11. `.co-grid`: `minmax(0, 1fr) 168px 120px 168px`. Name cell: 24px company tile + name 14px 500 link, ellipsis. Status cell: coloured tag (5.4). Engineers: right-aligned tabular 14px. Next call: date link 13px `--accent` (`.lift`), or `—` in `--faint`.
- `.no-match`: 14px `--muted`, padding 16px 12px.

### 7.7 Company page `#/companies/<slug>` (R12, R13, R29)

Markup (replace the body of `renderCompany`):
```html
<div class="topbar">…back "Companies"…</div>
<header class="co-head">
  <div class="title-row"><span class="co-head-tile">N</span><h1 tabindex="-1">Northwind Freight</h1><span class="pill tag-blue">Open deal</span></div>
  <p class="meta">About 420 engineers · Open deal: Portal</p>
  <div class="co-actions">…Run the agent / Open brief…</div>
</header>
<div class="co-layout">
  <div class="co-main">People, Used to work here, History, Backstage</div>
  <aside class="co-aside">Next call, Papers, Alerts</aside>
</div>
```
- `.co-head`: padding 24px 32px 20px, border-bottom `--line`. `h1` Title L. `.meta` 13px `--muted`, margin-top 4px. `.co-actions` margin-top 16px, gap 8px.
- `.co-layout` (1240px and up): grid `minmax(0, 1fr) 340px`, min-height calc(100% - header). `.co-main`: padding 24px 32px 96px, max-width 760px. `.co-aside` (R12 grey status column): bg `--surface-2`, border-left `--line`, padding 24px 20px.
- People and "Used to work here" (R13 Project roles): `.roles` (new) grid `repeat(auto-fill, minmax(240px, 1fr))`, gap 16px; each item: lg 40 photo + name 14px 600 + title 13px `--muted` + tenure 12px `--muted`. `.sub-label` 13px 600 `--ink`, margin 24px 0 12px.
- History, Papers: `.kv` Fields table.
- Aside blocks: each `section` has a 13px 600 `--ink` heading, margin-bottom 8px, 24px between blocks. "Next call" = the `callRow(inv)` inside a white `.widget` (radius `--r-lg`). Papers = `.kv.small` with ok/warn icons. Alerts = rows inside a white `.widget`.
- Under 1240px: one column, `.co-aside` after `.co-main`, border-left 0, border-top `--line`.

### 7.8 People map `#/map` (R15 for cards; keep the board)

Keep everything in `map.js` layout and edge routing and the current `map.css` look. Only these changes:
- Photos in person cards (`.node .avatar` gets the `<img>`; keep the 36px size and the existing 3px white ring).
- `C.tint` for avatars and company tiles (5.7, 5.8).
- `.node.you .you-av` background `--accent`.
- `.frame-chip` uses the company status tag colour (5.4) instead of always green.
Page frame (`styles.css`):
- `.map-top` = page header (7.1 look): padding 16px 24px, border-bottom `--line`, page icon `network` teal, title 20px. The view switcher `.seg` moves to the right.
- `.seg` becomes a chip row (R21 filter chips): no track background; `button` height 28px, padding 0 12px, radius `--r-full`, border 1px `--btn-line`, 13px 500 `--ink-2`, gap 6px between chips; hover bg `--hover`; pressed (`aria-pressed="true"`): bg `--accent-bg`, border `--accent`, colour `--accent`. Same chips on the In-call panel page.
- `.map-body`: padding 0, grid `minmax(0, 1fr) 360px`. Board: margin 16px, `height: calc(100% - 32px)`.
- `.map-side` (R24 member pane): bg #fff, border-left `--line`, padding 20px 24px, overflow-y auto. `h2` Title 20px; `.meta` 13px `--muted`. `.rel li`: padding 10px 0, border-top `--line`; name 14px 600; `p` 13px `--ink-2`. `.map-insight`: inbox card (R6): border 1px `--line`, radius `--r-lg`, padding 12px 16px, 14px `--ink-2`, gap 8px between cards. `.side-actions` gap 8px, margin-top 16px.
- Under 1240px: side panel under the board (existing), border-left 0, border-top `--line`.

### 7.9 In-call panel page `#/live`

- Page header per 7.1 (`.page.wide`, icon `video` green).
- Controls row (`.live-controls`, new class replacing the inline-styled `.title-row`): margin-top 0, flex, gap 8px, wrap. Skin switcher = `.seg` chips (7.8). Call select = `.input.sm` select. "Open the panel on its own" `.btn.ghost.sm`, pushed right.
- `.stage` keeps its Google Meet (`#202124`) and Zoom (`#1a1a1a`) colours: it mocks those apps, not Asana. Change only: `.vtile .avatar` 72px with the photo (Chris: "C" on `--accent`); `.vname` 12px #e8eaed; radius stays.
- `.live-note` 12px `--muted`.
- `.setup`: grid 2 columns, gap 16px, margin-top 32px. Each `.box`: widget skin (5.12), padding 20px 24px; `h2` 16px 600; `ol` 14px / 1.55 `--ink-2`, padding-left 20px, 6px between items; `code` per 5.19.

### 7.10 Data `#/data` (R14, R26, R17)

- Page header per 7.1 (`.page.narrow`, icon `database` gray). `.data-note` 13px `--muted`.
- `.stats.three`: number tiles (5.12), margin-top 20px (remove the inline style).
- Each source group is a table-like list (R26): `.list.src-list` keeps the boxed look here: border 1px `--line`, radius `--r-lg`, overflow clip. Rows: grid `32px minmax(0, 1fr) auto`, gap 12px, min-height 56px, padding 10px 16px, border-top `--line` between; `.src-tile` 32px radius `--r-lg`, bg `--surface-2`, no border, icon 16px `--ink-2`; name 14px 500; sub 13px `--muted`; state status pill (5.5).
- "How the estimates work": `.kv.small`.

## 8. In-call panel (`panel.html`, `panel.css`, `panel.js`; R8, R9, R29)

Asana has no meeting side panel; this is Asana's task pane squeezed to 320-420px, with Attio's record-details property list (R29).

- `body`: 14px, bg #fff. `#app`: max-width 480px, padding 0 0 24px.
- `.p-head`: min-height 52px, padding 8px 12px, gap 10px. `.mark.sm` 22px (keeps ink). `h1` 14px / 1.4 600; `p` 12px `--muted`; `.live-dot` 8px `--accent` with a 3px `--accent-bg` ring (solid, no blur); off = `--dot`. Maximize `icon-btn` 32px.
- `.p-note`: margin 0 12px 8px, bg `--surface-2`, radius `--r-md`, padding 8px 10px, 12px `--ink-2`.
- `.p-pick select`: per 5.2 small: 32px, radius `--r-md`, 13px 500, margin 0 12px 4px.
- `.p-tabs`: per 5.9 (13px, gap 16px, 36px tall, underline `--ink`), padding 0 12px, sticky top 0, bg #fff, border-bottom `--line`.
- `.p-pane`: padding 12px, gap 12px.
- `.p-props`: grid `84px minmax(0, 1fr)`, gap 6px 10px; dt 12px 500 `--muted`; dd 13px with tags (company status tag per 5.4, "Best fit" `.pill.accent`).
- `.p-card`: border 1px `--line`, radius `--r-lg`, padding 12px, bg #fff. `.p-card.flush` padding 8px. `.p-cap` 12px 600 `--ink`. `blockquote`: no left border, padding 0, 14px / 1.5 500 `--ink`.
- `.p-points`: 16px circle checks (5.3), gap 8px; `strong` 13px 600; `small` 12px `--muted`; checked item text `--muted` + line-through (replace the 0.55 opacity).
- `.p-watch`, `.p-plain`: 13px / 1.5 `--ink-2`, 8px apart.
- `.mini-map`: unchanged (280px).
- `.p-person-btn`: padding 8px 4px, radius `--r-md`, gap 10px, hover `--hover`; md 32 photo avatar; name 13px 600; `.joined` `check` 14px `--accent`; sub 12px `--muted`; tag right. `.p-person-more`: padding 0 4px 10px 46px, 13px.
- `.p-note-list li`: padding 8px 0, border-bottom `--line`; `.p-note-kind` becomes a tag coloured by kind (5.4); time 12px `--muted`; text 13px.
- `.p-compose` (R9 comment box): border 1px `--field`, radius `--r-lg`, padding 10px; focus-within per section 4. Textarea 13px / 1.5, no border. Kind chips (`.chip-radio span`): tag shape (height 22px, radius `--r-sm`, 12px 500), unselected `--tag-gray-*`; selected: that kind's tint + `box-shadow: inset 0 0 0 1.5px currentColor`. Add the kind's tag class to each `label.chip-radio` in `notesPane()`. Save `.btn.primary.sm`.
- `.p-private`: 12px `--muted`, `shield` 13px.
- 360px and below: `.p-props` label column 72px; `.p-tabs` gap 12px. At 320px nothing may scroll sideways: the select, cards and compose row are `width: 100%` / `min-width: 0`, chip row wraps.

## 9. Phone (390px) and narrow rules

Breakpoints stay where they are (1240, 1100, 999, 640, 360 in the panel).

1240px and below:
- Alerts single pane (7.5). Company page one column (7.7). Map side under the board. `.cl-name .pill + .pill` hidden. `.step` label column 200px (existing).

1100px and below:
- Tables drop their header row (`.thead { display: none; }`) and vertical cell lines (`.cell { border-right: 0; }`).
- Calls rows: `.cl-grid` becomes `64px minmax(0, 1fr)`; `.cl-time` spans two rows; `.cl-name` row 1; `.cl-prep` row 2 (column 2, padding-top 4px); `.cl-people` hidden. Row min-height 64px.
- Companies: `minmax(0, 1fr) auto` with `.hide-sm` hidden (existing).
- Home grid: one column (`.home-grid { grid-template-columns: 1fr; }`).

999px and below (phone and small tablet):
- `html, body { height: auto; }`, body scrolls (existing).
- `.appbar`: grid `40px minmax(0, 1fr) 40px`, height 48px, padding 0 4px, still `--chrome`. Shows `#menuBtn`, `#appbarTitle` (15px 600 `--chrome-ink`, centred, ellipsis), `#appbarSearch`. Hides `.brand`, `#openPalette`, `.appbar-me`. Icon buttons 40px.
- `.shell`: block. `.rail`: `position: fixed; inset: var(--appbar-h) auto 0 0; width: min(280px, 86vw);` dark, off-canvas (existing transform + visibility), z-index 20. `body.nav-open .scrim`: `inset: var(--appbar-h) 0 0 0`, so the menu button stays visible and clickable.
- `.main`: height auto, overflow visible.
- `.topbar` (detail bars): `top: var(--appbar-h)`. `.back span` hidden (icon only, keep `aria-label` via the existing sr text or add one).
- Jump targets: `scroll-margin-top: 112px` (48 top bar + 48 detail bar + 16). `html { scroll-padding-top: 64px; }` on list pages.
- Page padding: `.page` 0 16px 64px with `.page-head` margin 0 -16px 16px, padding 16px; `.home` 20px 16px 64px; `.col` 24px 16px 64px; `.alert-detail-inner` 24px 16px 64px; `.co-head` 20px 16px; `.co-main` 20px 16px 64px.
- Live stage one column, panel 560px tall; setup one column (existing).
- Toast: `left: 16px; right: 16px; bottom: calc(16px + env(safe-area-inset-bottom)); max-width: none;`.
- `kbd` hidden (existing).

640px and below (the 390px phone):
- Type: Display 26px / 1.3; Title L 22px / 1.35; Title 18px / 1.4; opener 17px / 1.55.
- Home: `.home-header` left-aligned (R27); `.home-stats` turns into separate chips: `flex-wrap: wrap; gap: 8px; height: auto; border: 0; background: none; padding: 0;` each `.hs-item` its own 28px pill (bg #fff, border `--line`, radius `--r-full`), separators hidden.
- Hero: `.hero-top` height auto, padding 14px 16px; body padding 16px 16px 0; quote margin 16px 16px 0; actions padding 16px; primary button full width 40px; `.hint` on its own line, left.
- `.stats` two columns (existing grid change; tiles keep their own borders, so remove the old border-left / border-top juggling rules at this width).
- `.props`, `.kv.small`: label column 104px. `.kv`: label column 112px.
- `.changes li` one column; actions row below text (existing).
- `.changed-row`: key and value stack in column 2 (existing).
- Calls: `.cl-name` tags wrap under the name (flex-wrap).
- Drawer 100vw; check dialog `width: calc(100vw - 16px); margin: 16px auto auto;` `.check-row` stacks (existing). Palette `width: calc(100vw - 16px); margin: 4px auto auto;`.
- `#openInCall` hidden (existing); `#runAgain` icon-only (hide its text in a `span`, keep `aria-label="Run again"`).
- Live tiles 2 columns (existing).

Nothing may scroll sideways at 390px or 320px on any page; nothing may sit under the top bar, a detail bar or the toast without a way to scroll it clear.

## 10. Do not

- No emoji anywhere (UI, tags, toasts, empty states, docs shown in the app).
- No gradients, no glows, no coloured shadows, no blur on rings. Shadows are the four neutral tokens only.
- No Asana coral, no Asana blue (`#4573d2`, `#edf1fc`): green `--accent` is the only brand colour; blue appears only inside the blue tag tint.
- No novelty or display fonts; Inter 400/500/600 only. No uppercase or letter-spaced labels.
- No clipped text: real text line-height at least 1.3; no fixed heights on text boxes; ellipsis only on single-line names in rows, cards and table cells (full text in `title`). Run the overflow probe from CLAUDE.md on every page at 1440, 1024, 390 and 320 px wide and in the in-call panel at 320 and 420 px: zero elements with computed `overflow: hidden` and `scrollHeight > clientHeight`.
- No cropped faces or logos: avatars use square sources with `object-fit: cover; object-position: 50% 30%`; company tiles are letters, not cropped images.
- No layout that hides content behind fixed or sticky bars (scroll margins in sections 6.3 and 9).
- No hotlinked images (CSP `img-src 'self' data:`); no stock photo for Chris.
- No new features: no sorting, filtering, collapsing sections, widget menus or account menu. Carets and chips that look interactive must either work or be decorative (`aria-hidden`, no hover state).
- Do not change `server.py`, `data/snapshot.js`, `_headers`, or the layout and edge-routing code in `map.js`.
- Do not use `--rail` for the dark sidebar.

## 11. Build order and checks

1. Tokens + type + `.ic` stroke in `base.css`; shared components (section 5). Check: no page breaks, contrast spot-check of `--muted` text and `--field` borders.
2. Shell: top bar markup move, dark rail, flush main (section 6). Check: Ctrl/Cmd K, "/", menu on phone, focus rings visible on dark.
3. `C.avatar`, `C.tint`, `C.tagFor` in `core.js`; photos + `CREDITS.md`; swap every avatar site in the table in 5.7. Check: each face loads from `img/people/`, initials show when a file is renamed away.
4. Page headers and tables: Calls, Companies, Data, Live (7.1, 7.3, 7.6, 7.9, 7.10).
5. Home (7.2). Then call view and brief (7.4). Then alerts two-pane (7.5), company page (7.7), map frame (7.8).
6. Dialogs, drawer, palette, toast (5.14 to 5.17).
7. In-call panel (section 8) in the `#/live` stage and on its own at 320 and 420 px.
8. Verify in the preview: every route at 1440 / 1024 / 390 / 320; the overflow probe; no horizontal scroll (`document.documentElement.scrollWidth <= innerWidth`); keyboard pass through rail, tabs, palette, drawer; a side-by-side screenshot of Home, Calls, a brief, Alerts and Companies next to R1, R5, R8, R6 and R19.
