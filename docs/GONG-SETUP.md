# Connect Overture to Gong

Overture reads Gong with an API access key and secret. You need to be a Gong **Tech admin** to make one. It takes about three minutes.
The key and secret stay in `centralize/.data/gong.json` on this PC. They never reach the browser or the logs.

## What Overture does with it (read only)

- Lists your Gong calls from the last 180 days and finds the latest one with anyone from the company's email domain.
- For that call it reads Gong's own summary: the brief, key points, topics and trackers (for example competitor mentions), and the link to open it in Gong.
- It never asks for transcripts and never writes to Gong. Answers are kept for 10 minutes.
- Gong's summaries are **not** sent to Claude or anywhere else unless you turn on **Use Gong notes in AI answers** on the Data page (off by default).

## 1. Create the key

1. In Gong, open **Admin center** (left sidebar) > **Settings** tab > **API** (under **Ecosystem**).
2. Press **+ Get API key**. Name it `Overture`.
   - **TTL (days)**: leave empty, or set an expiry and make a new key when it runs out.
   - **Trusted IPs**: leave empty, or add this PC's public IP address. With a list set, Gong refuses (403) any other address.
3. Press **Get API key** and copy the **access key** and the **secret**. Gong shows the secret only once.
4. Note your **API base URL** if the API page shows one (it looks like `https://us-12345.api.gong.io`).
   If it doesn't, use `https://api.gong.io`. Overture only sends the key to https addresses on gong.io.

## 2. Save it on this PC

In a terminal (not in the browser, not in a chat):

```
tks-spotify/.venv/Scripts/python.exe -I tks-spotify/centralize/tools/connect.py gong
```

Paste the access key and the secret (nothing shows while you paste), then type the base URL or press Enter for the default.
Instead of the file you can set `GONG_ACCESS_KEY`, `GONG_ACCESS_SECRET` and `GONG_BASE_URL` before starting the server.

## 3. Restart and check

Restart `server.py`. Its first line says `Gong set up`. Open Overture's **Data** page: the Gong row says "Connected to" your
workspace with the last sync time, or the last error.

## Notes

- Rate limits: 3 requests a second and 10,000 a day. Overture uses a handful per page load at most (cached 10 minutes), waits once
  and retries when Gong says 429, and pauses for a minute after any failure. The rest of the page keeps working.
- Overture reads at most 10 pages of calls (up to 1,000 calls), newest first: the last 14 days, then 45, 90 and 180 days back.
  Gong documents no sort order, so asking in windows is what keeps the latest call in view. A very busy workspace may have older
  matches it doesn't see, never newer ones.
- Private calls (marked private in Gong) are skipped. Gong hides them from most people, and Overture reads with a company-wide key.
- Untested against a real account: the field names in Gong's call content (`brief`, `keyPoints`, `topics`, `trackers`) and the call
  link (`metaData.url`). Gong's full API reference sits behind a sign-in, so these come from Gong's public help pages and
  open-source Gong clients, and are tested against a fake Gong.
- To disconnect: delete `centralize/.data/gong.json` (or run `connect.py gong` and type `-` for both), and delete the key in Gong.
