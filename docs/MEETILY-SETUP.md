# Meetily: live transcript while the call runs

[Meetily](https://github.com/Zackriya-Solutions/meetily) is a free, MIT-licensed meeting recorder that transcribes on your own PC
(Whisper or Parakeet, no cloud). With it on, MOAB reads the transcript as it is written and finds the people and companies said on
the call while it runs, the same way it reads the notes you type in the in-call panel.

## What MOAB reads, and what it doesn't

Meetily is a Tauri desktop app. Its live transcript only travels inside the app (Tauri events to its own window), it has no local
web API for it, and its SQLite database (`%APPDATA%\Meetily\meeting_minutes.sqlite`) only gets the transcript when you stop
recording. What it does write while it records, after every new or corrected segment, is a JSON file next to the recording:

```
%USERPROFILE%\Music\meetily-recordings\<meeting name>_<YYYY-MM-DD_HH-MM>\
    metadata.json      {"meeting_name": ..., "created_at": ..., "status": "recording" | "completed", ...}
    transcripts.json   {"segments": [{"text": ..., "display_time": "[02:15]", "sequence_id": 7, ...}], "last_updated": ...}
```

It writes `transcripts.json` to a temp file first and then renames it, so a read never sees half a file. (No Music folder: it uses
`Documents\meetily-recordings` instead.) This is from Meetily's source code (`frontend/src-tauri/src/audio/recording_saver.rs`,
`audio_processing.rs`, `recording_preferences.rs`; release v0.4.1).

So MOAB reads **only those two files**, every 2 seconds while Meetily is on in Settings:

- It never opens Meetily's database, never talks to Meetily (or anything else) over the network for this, and never touches audio.
- The transcript stays in the server's memory while the call runs and is dropped when Meetily stops recording. `records.json` keeps
  only each mention and the sentence it came up in (and drops those after "Keep quotes for" in Settings > Mentions and connections).
- Web lookups get only a name, role or team words, and company names and websites, as for notes. With **Look up mentions
  automatically** off, names and companies are still listed but not looked up until you press **Look up on the web**.

**Untested against a real Meetily install.** Built from Meetily's source code and tested with fake recording folders. If a future
Meetily version moves the files, set `MEETILY_RECORDINGS_DIR` (below) or tell me.

## Set it up (once, about 10 minutes)

1. Download the latest Windows installer from Meetily's releases: https://github.com/Zackriya-Solutions/meetily/releases
   (`meetily_<version>_x64-setup.exe`; it needs a CPU with AVX2). Run it.
2. Open Meetily, let it download a transcription model (Parakeet is the default; any works), and allow the microphone.
   In Meetily's settings, recording **system audio** lets it hear the other people on the call, not only you.
3. Leave the recordings folder where it is (`Music\meetily-recordings`). If you moved it, start MOAB with
   `set MEETILY_RECORDINGS_DIR=D:\path\to\meetily-recordings` first.
4. In MOAB: **Settings > Research sources and privacy > Meetily**: on.

## During a call

1. Start recording in Meetily when the call starts.
2. MOAB matches the recording to your calendar: the call that runs when Meetily starts (from 15 minutes before it to its end).
   If two calls overlap, or the call isn't in your calendar, pick it in the in-call panel and press **Use it for this call**.
   The pick holds for that recording only: the next recording is matched by time again.
3. The in-call panel shows **Listening via Meetily** while lines arrive. People and companies said on the call show in its People
   tab and on the People map, with **How they're connected**.
4. Stop recording in Meetily when the call ends. MOAB reads the last lines once more and lets the transcript go.

## Turning it off

Settings > Research sources and privacy > Meetily: off. MOAB stops reading at once and forgets the lines it held.
