# Connect Overture to HubSpot

Overture reads HubSpot with a private app access token that you create. It takes about five minutes.
The token stays in `centralize/.data/hubspot.json` on this PC. It never reaches the browser, the logs or Claude.

## What Overture does with it

- **Reads**, for each call on your calendar: the company with the guests' email domain, its deals (name, stage, amount, close date),
  the guests as contacts (name, job title), and the company's last five notes. Answers are kept for 10 minutes.
- **Writes** only when you press **Save to HubSpot** in a call's **After the call** tab: one note with your call notes on the company,
  linked to the call's contacts and the open deal, plus any job title changes you ticked. The page shows exactly what will be written first.

## 1. Create the private app

1. In HubSpot, open **Development** (top bar) > **Legacy apps** > **Create legacy app** > **Private**.
   In older accounts it is **Settings** (gear) > **Integrations** > **Private Apps** > **Create a private app**.
   You need to be a Super Admin.
2. **Basic info**: name `Overture`.
3. **Scopes**: press **Add new scope** and tick these:
   - `crm.objects.companies.read`: find the company by its website domain
   - `crm.objects.deals.read`: the company's deals and their stages
   - `crm.objects.contacts.read`: the guests' names and job titles
   - `crm.objects.contacts.write`: change a job title you accepted; attach the note to the contacts
   - `crm.objects.companies.write`: attach the note to the company
   - `crm.objects.deals.write`: attach the note to the open deal

   Notes have no scope of their own in HubSpot's scope list; reading and writing them goes through the scopes of the records
   they sit on. This is **untested against a real account**: if reading notes is refused, Overture still shows the company and its
   deals, just without notes. If the Data page says "missing a scope" after a note is written, add the scope it names in HubSpot
   and save the app.
   Overture also asks for the account's details (portal id) to show which portal it is connected to. If the token can't see them,
   the Data page just says "Connected" without the portal.
4. Press **Create app** and confirm. Open the app's **Auth** tab, press **Show token** and **Copy**.

## 2. Save the token on this PC

In a terminal (not in the browser, not in a chat):

```
tks-spotify/.venv/Scripts/python.exe -I tks-spotify/centralize/tools/connect.py hubspot
```

Paste the token at the prompt (nothing shows while you paste) and press Enter.
Instead of the file you can set the environment variable `HUBSPOT_TOKEN` before starting the server.

## 3. Restart and check

Restart `server.py`. Its first line says `HubSpot set up`. Open Overture's **Data** page: the HubSpot row says
"Connected to portal ..." with the last sync time, or the last error.

## Notes

- Rate limits: a private app gets 100 to 190 requests per 10 seconds and the search endpoints 5 per second. Overture waits once and
  retries when HubSpot says 429, and pauses for a minute after any failure. The calendar and the rest of the page keep working.
- To disconnect: delete `centralize/.data/hubspot.json` (or run `connect.py hubspot` and type `-`), and delete or rotate the token in HubSpot.
- Untested against a real account: the deal pipeline stages list, the associations v4 read for deals, the notes search by company
  (`associations.company`, newest first), and the note association type ids
  (190 company, 202 contact, 214 deal, from HubSpot's associations docs). They are all built from HubSpot's public docs and tested
  against a fake HubSpot. Try one Save to HubSpot on a test company first.
