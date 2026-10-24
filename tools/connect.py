"""Save Overture's HubSpot, Gong and Granola credentials on this PC, without pasting them into a browser or a chat.

Run:  tks-spotify/.venv/Scripts/python.exe -I tks-spotify/centralize/tools/connect.py [hubspot|gong|granola]

It asks for each secret with no echo, then writes centralize/.data/hubspot.json, gong.json and/or granola.json
(.data is git-ignored and never served by server.py). It never prints a secret. Restart server.py afterwards.
Press Enter at a prompt to keep what is saved already, or type "-" to remove it.
"""
import getpass
import json
import os
import re
import secrets
import sys
import urllib.parse
from pathlib import Path

DATA = Path(os.environ.get("OVERTURE_DATA_DIR") or (Path(__file__).resolve().parent.parent / ".data"))


def load(name):
    try:
        j = json.loads((DATA / name).read_text(encoding="utf-8"))
        return j if isinstance(j, dict) else {}
    except (OSError, ValueError):
        return {}


def save(name, obj):
    DATA.mkdir(parents=True, exist_ok=True)
    if not (DATA / ".gitignore").exists():
        (DATA / ".gitignore").write_text("*\n", encoding="utf-8")
    path = DATA / name
    if not obj:
        path.unlink(missing_ok=True)
        print("  Removed " + str(path))
        return
    tmp = path.with_name(name + "." + secrets.token_hex(4) + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1), encoding="utf-8")
    os.replace(tmp, path)
    print("  Saved to " + str(path))


def ask_secret(label, have):
    while True:
        v = getpass.getpass("  " + label + (" (Enter keeps the saved one, - removes it): " if have else ": ")).strip()
        if not v or v == "-" or re.fullmatch(r"[\x21-\x7e]+", v):
            return None if not v else "" if v == "-" else v
        print("  That has spaces or invisible characters in it (they often come along when you copy). Paste it again.")


def gong_base_ok(url):
    p = urllib.parse.urlsplit(url)
    host = (p.hostname or "").lower()
    return p.scheme == "https" and "@" not in p.netloc and (host == "gong.io" or host.endswith(".gong.io"))


def hubspot():
    print("\nHubSpot: paste the private app's access token (docs/HUBSPOT-SETUP.md). Nothing shows while you paste.")
    j = load("hubspot.json")
    v = ask_secret("Access token", bool(j.get("token")))
    if v is not None:
        j["token"] = v
    save("hubspot.json", {k: x for k, x in j.items() if x})


def gong():
    print("\nGong: paste the access key and secret from Admin center > Settings > API (docs/GONG-SETUP.md). Nothing shows while you paste.")
    j = load("gong.json")
    for key, label in (("access_key", "Access key"), ("access_secret", "Access key secret")):
        v = ask_secret(label, bool(j.get(key)))
        if v is not None:
            j[key] = v
    cur = j.get("base_url") or "https://api.gong.io"
    while True:
        v = input("  API base URL [" + cur + "]: ").strip() or cur
        v = v.rstrip("/")
        if v.endswith("/v2"):
            v = v[:-3]
        if gong_base_ok(v):
            j["base_url"] = v
            break
        print("  That must be an https address on gong.io, like https://api.gong.io or https://us-12345.api.gong.io")
    if not (j.get("access_key") and j.get("access_secret")):
        j = {}
    save("gong.json", {k: x for k, x in j.items() if x})


def granola():
    print("\nGranola: paste your personal API key from Granola > Settings > API (docs/GRANOLA-SETUP.md). Nothing shows while you paste.")
    j = load("granola.json")
    v = ask_secret("API key", bool(j.get("api_key")))
    if v is not None:
        j["api_key"] = v
    save("granola.json", {k: x for k, x in j.items() if x})


def main(argv):
    which = argv[0].lower() if argv else ""
    if which not in ("", "hubspot", "gong", "granola"):
        print(__doc__)
        return 2
    print("Overture: connect HubSpot, Gong and Granola. Secrets are saved only in " + str(DATA))
    if which in ("", "hubspot"):
        hubspot()
    if which in ("", "gong"):
        gong()
    if which in ("", "granola"):
        granola()
    print("\nDone. Restart server.py, then open the Data page to check the connections.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except (KeyboardInterrupt, EOFError):
        print("\nStopped. Nothing else was changed.")
        sys.exit(1)
