# Connect MOAB to your Google Calendar

MOAB reads your calendar with a Google OAuth client that you own. Making one takes about ten minutes and is free.
MOAB only asks for read-only calendar access. The client secret and your sign-in stay in `centralize/.data/` on this PC.

1. Open https://console.cloud.google.com and create a project (top bar, project picker, **New project**). Any name works, for example `MOAB`.
2. In that project, open **APIs & Services > Library**, search for **Google Calendar API** and press **Enable**.
3. Open **APIs & Services > OAuth consent screen** (in newer consoles: **Google Auth Platform > Branding / Audience**):
   - App name `MOAB`, your email as the support and developer contact.
   - User type / audience: **External**.
   - Publishing status: leave it in **Testing**.
   - Under **Test users**, add the Google account whose calendar MOAB should read.
   - Scopes: nothing to add here; MOAB asks for `openid`, `email`, `profile` and `calendar.readonly` when you connect.
4. Open **APIs & Services > Credentials > Create credentials > OAuth client ID**:
   - Application type: **Web application**, name `MOAB on this PC`.
   - **Authorized redirect URIs**: add exactly `http://localhost:3576/auth/google/callback`
     (if you run the server on another port with `--port`, use that port instead).
   - Press **Create**.
5. In the dialog that opens, press **Download JSON**. Save the file as
   `tks-spotify/centralize/.data/google-client.json` (make the `.data` folder if it isn't there yet).
   Instead of the file you can set the environment variables `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`.
6. Restart the server: `tks-spotify/.venv/Scripts/python.exe tks-spotify/centralize/server.py`.
   The first line it prints should say `Google Calendar set up, not connected`.
7. Open http://localhost:3576, press **Connect Google Calendar**, pick the test user's account and allow access
   (tick the calendar box if Google shows one). You land back on MOAB's Home with your calls.

Notes
- Google shows "Google hasn't verified this app" while the app is in Testing. That is expected for your own client: press **Continue**.
- In Testing, Google ends the sign-in after 7 days. MOAB then shows the Connect button again; press it to reconnect.
- If Google refuses to sign in inside an embedded preview window, open http://localhost:3576 in Chrome instead.
- To disconnect: **Data** page > **Disconnect**. That revokes MOAB's access at Google and deletes the saved sign-in.
  You can also remove access at https://myaccount.google.com/permissions.
