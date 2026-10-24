"""Serve Overture on http://localhost:3576 with real calls from Google Calendar, its own records store, and optional Claude.

Run from anywhere:  tks-spotify/.venv/Scripts/python.exe tks-spotify/centralize/server.py [--port 3576]

- Google Calendar: put the OAuth client JSON from Google Cloud at .data/google-client.json (or set GOOGLE_CLIENT_ID and
  GOOGLE_CLIENT_SECRET), restart, then press "Connect Google Calendar" in the app. See docs/GOOGLE-SETUP.md.
- Records (company status, people's titles and notes, call notes, after-call updates) live in .data/records.json.
- Claude is optional: set ANTHROPIC_API_KEY first. Without it the page uses on-device AI or its built-in rules.
- With Claude, new guests on your calls and their companies are researched in the background (work profile, past work, company
  facts, with public sources). Only their name, company and company domain are sent; see "invitee research" below for the rules.
- HubSpot and Gong are optional: run tools/connect.py once (docs/HUBSPOT-SETUP.md, docs/GONG-SETUP.md). Overture reads companies,
  deals, contacts and notes from HubSpot and the last call's summary from Gong, and writes to HubSpot only when you press
  "Save to HubSpot" after a call.
Secrets and tokens stay in .data/ (git-ignored) and are never logged or sent to the browser.
"""
import base64
import contextlib
import contextvars
import hashlib
import hmac
import http.cookies
import json
import os
import re
import secrets
import sys
import threading
import time as _time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, time, timedelta, timezone
from functools import partial
from html import escape as html_escape
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA_ROOT = Path(os.environ.get("MOAB_DATA_DIR") or (HERE / ".data"))
# The shared site (MOAB_PUBLIC_URL, or the RENDER_EXTERNAL_URL Render sets): everyone signs in with Google and each account has
# its own folder, .data/users/<account>, so one person's calendar, keys and notes are never another's. Unset: Overture on your own PC.
PUBLIC_URL = (os.environ.get("MOAB_PUBLIC_URL") or os.environ.get("RENDER_EXTERNAL_URL") or "").rstrip("/")
HOSTED = bool(PUBLIC_URL)
_USER = contextvars.ContextVar("moab_user", default=None)  # the signed-in account this request or lookup is for


class NoUser(Exception):
    """Something reached for an account's data with no account signed in (on the shared site that is never allowed)."""


def own_env(name):
    """A key from this server's environment, for MOAB on your own PC only: on the shared site an environment key would be
    every account's, so each account saves its own instead."""
    return None if HOSTED else os.environ.get(name)


def current_user():
    uid = _USER.get()
    if HOSTED and not uid:
        raise NoUser()
    return uid or ""


@contextlib.contextmanager
def as_user(uid):
    tok = _USER.set(uid)
    try:
        yield
    finally:
        _USER.reset(tok)


class _UserDir:
    """DATA_DIR: .data on your own PC; .data/users/<account> on the shared site, for the account signed in right now."""
    def _p(self):
        uid = current_user()
        return DATA_ROOT / "users" / uid if uid else DATA_ROOT

    def __truediv__(self, name):
        return self._p() / name

    def __fspath__(self):
        return str(self._p())

    def __str__(self):
        return str(self._p())

    def __getattr__(self, name):
        return getattr(self._p(), name)


class PerUser:
    """A cache or state dict (or set) kept once per account on the shared site; just once on your own PC."""
    def __init__(self, make):
        self._make, self._by = make, {}

    def _d(self):
        uid = current_user()
        d = self._by.get(uid)
        return d if d is not None else self._by.setdefault(uid, self._make())

    def users(self):
        return list(self._by)

    def __getattr__(self, name):
        return getattr(self._d(), name)

    def __getitem__(self, k):
        return self._d()[k]

    def __setitem__(self, k, v):
        self._d()[k] = v

    def __delitem__(self, k):
        del self._d()[k]

    def __contains__(self, k):
        return k in self._d()

    def __iter__(self):
        return iter(self._d())

    def __len__(self):
        return len(self._d())

    def __bool__(self):
        return bool(self._d())


DATA_DIR = _UserDir()
PORT = 3576
MODEL = "claude-opus-5-5"
SCOPES = "openid email profile https://www.googleapis.com/auth/calendar.readonly"
CAL_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
DAYS_AHEAD = 14
DAYS_BACK = 180      # past meetings are only read to spot job changes and first meetings
CACHE_SECONDS = 60
STATE_TTL = 600      # OAuth state lives 10 minutes and is used once
PERSONAL_DOMAINS = {
    "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com", "msn.com", "icloud.com", "me.com",
    "mac.com", "yahoo.com", "ymail.com", "aol.com", "proton.me", "protonmail.com", "gmx.com", "hey.com",
}
# Home internet providers and other personal mail: a guest on one is a private person, never their "company".
ISP_DOMAINS = {
    "rogers.com", "sympatico.ca", "bell.net", "shaw.ca", "telus.net", "videotron.ca", "cogeco.ca", "eastlink.ca", "comcast.net",
    "verizon.net", "att.net", "sbcglobal.net", "cox.net", "charter.net", "btinternet.com", "sky.com", "virginmedia.com", "orange.fr",
    "free.fr", "wanadoo.fr", "laposte.net", "t-online.de", "web.de", "mail.ru", "qq.com", "163.com", "126.com", "naver.com", "pm.me",
    "duck.com", "privaterelay.appleid.com", "rocketmail.com", "fastmail.com", "zoho.com", "tutanota.com", "tuta.io",
}
# Webmail brands that run the same service under many country domains (hotmail.ca, yahoo.co.uk, gmx.de ...).
WEBMAIL_BRANDS = {"gmail", "googlemail", "yahoo", "ymail", "hotmail", "outlook", "live", "msn", "aol", "gmx", "yandex", "icloud",
                  "proton", "protonmail", "mail"}
PUBLIC_SUFFIXES = {
    "com", "net", "org", "me", "ca", "us", "uk", "co.uk", "org.uk", "ie", "de", "at", "ch", "fr", "be", "nl", "lu", "it", "es", "pt",
    "se", "no", "dk", "fi", "is", "pl", "cz", "sk", "hu", "ro", "bg", "gr", "tr", "ru", "ua", "by", "kz", "ee", "lv", "lt", "si", "hr",
    "rs", "il", "ae", "in", "co.in", "jp", "co.jp", "ne.jp", "kr", "co.kr", "cn", "com.cn", "hk", "com.hk", "tw", "com.tw", "sg",
    "com.sg", "my", "com.my", "ph", "com.ph", "id", "co.id", "th", "co.th", "vn", "com.vn", "au", "com.au", "nz", "co.nz", "za", "co.za",
    "br", "com.br", "mx", "com.mx", "ar", "com.ar", "cl", "co", "com.co", "pe", "com.pe", "eu",
}


def personal_domain(d):
    """True for personal mail: the big webmail domains in any country, and home internet providers."""
    d = str(d or "").strip().lower()
    if d in PERSONAL_DOMAINS or d in ISP_DOMAINS:
        return True
    brand, _, rest = d.partition(".")
    return brand in WEBMAIL_BRANDS and rest in PUBLIC_SUFFIXES
UPDATE_KINDS = {"People", "Next step", "Papers", "Deal", "Reminder"}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

SYSTEM = (
    "You write a short call brief for Chris, an account executive who sells Spotify's Backstage products "
    "(Portal, Confidence and Xirp). You get the facts as JSON. Each fact says where it came from: public data, "
    "sample data, the user's own calendar, Overture's records, or Overture's own web research (each people[].profile and "
    "company.profile, built from public pages Overture searched and read). "
    "Use only these facts. Do not add numbers, names or claims that are not in them. "
    "Write in plain, short words that a busy salesperson can read in one minute. No headings, no metaphors. "
    "Plain text only: no markdown, no bullets, no bold. "
    "Write 4 to 6 short lines: who the company is and what it does, who the people are at work (their current role and the "
    "past work that matters), what changed since last time, their Backstage situation, who matters on the call and why, "
    "and last, what to bring up on the call. "
    "Overture has already done the research and saved it to its records. So never tell the reader to look anything up, search, "
    "research, check, verify or confirm anything, or add anything to Overture's records, and never call a fact automatic or unconfirmed. "
    "Leave out any to-do in the facts that asks for that. If Overture found nothing about someone or something, say plainly that "
    "Overture searched and found nothing public about it. End with what to bring up on the call, never a chore to do before it."
)
ASK_SYSTEM = (
    "You are Overture, a call-prep assistant for a salesperson who sells Spotify's Backstage products. "
    "Answer the question using only the facts in the JSON you get (their calendar, Overture's records, Overture's own web research and "
    "public Backstage data). "
    "If the facts do not answer it, say so in one line and say what Overture couldn't find (Overture has already searched its records and "
    "the web). Never tell them to look something up or to add it to Overture's records. "
    "Plain text only, no markdown, at most four short sentences."
)


def port():
    return PORT


def allowed_hosts():
    return {f"127.0.0.1:{PORT}", f"localhost:{PORT}"} | ({urllib.parse.urlsplit(PUBLIC_URL).netloc} if HOSTED else set())


def allowed_origins():
    return {f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"} | ({PUBLIC_URL} if HOSTED else set())


def redirect_uri():
    return (PUBLIC_URL if HOSTED else f"http://localhost:{PORT}") + "/auth/google/callback"


# ---------------------------------------------------------------- files ----------------------------------------------------------------

def ensure_data_dir():
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    ignore = DATA_ROOT / ".gitignore"
    if not ignore.exists():
        ignore.write_text("*\n", encoding="utf-8")


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def save_json(path, obj):
    """Write atomically: a temp file next to the target, then one rename."""
    ensure_data_dir()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + secrets.token_hex(4) + ".tmp")
    text = json.dumps(obj, indent=1, ensure_ascii=False)
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    db_saved(path, text)


def remove_file(path):
    """Delete a saved file (and the shared site's copy of it). Already gone is fine."""
    try:
        Path(path).unlink()
    except OSError:
        pass
    db_deleted(path)


# The shared site's disk is wiped whenever Render puts it to sleep, so there every file saved under .data is also kept in
# Postgres (DATABASE_URL) and written back when the server starts. Reads stay on the disk. Unset (your own PC): disk only.
DB = {"conn": None}
DB_LOCK = threading.Lock()


def db_on():
    return bool(os.environ.get("DATABASE_URL"))


def _db_key(path):
    return Path(path).resolve().relative_to(DATA_ROOT.resolve()).as_posix()


def _db_run(sql, args=(), must=False):
    """Run one statement. A failure is logged and skipped, or raised when must (the restore at start)."""
    with DB_LOCK:
        for attempt in (1, 2):  # once more on a fresh connection: Render's Postgres drops idle ones
            try:
                if DB["conn"] is None or DB["conn"].closed:
                    import psycopg
                    DB["conn"] = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True, connect_timeout=5)
                    DB["conn"].execute("CREATE TABLE IF NOT EXISTS moab_files (path text PRIMARY KEY, body text NOT NULL, "
                                       "saved_at timestamptz NOT NULL DEFAULT now())")
                cur = DB["conn"].execute(sql, args)
                return cur.fetchall() if cur.description else []
            except Exception as e:
                DB["conn"] = None
                if attempt == 2:
                    if must:
                        raise
                    where = (args[0] if args else "")
                    print(f"[db] {type(e).__name__}: {sql.split()[0]} {where} did not reach Postgres; it is lost when the server "
                          "sleeps unless it is saved again", flush=True)
                    return []


def db_saved(path, text):
    if db_on():
        _db_run("INSERT INTO moab_files (path, body) VALUES (%s, %s) ON CONFLICT (path) DO UPDATE SET body = EXCLUDED.body, "
                "saved_at = now()", (_db_key(path), text))


def db_deleted(path):
    if db_on():
        _db_run("DELETE FROM moab_files WHERE path = %s", (_db_key(path),))


def db_restore():
    """At start: write every saved file back under .data (never outside it). Returns how many."""
    if not db_on():
        return 0
    root, n = DATA_ROOT.resolve(), 0
    for rel, body in _db_run("SELECT path, body FROM moab_files", must=True):  # unreachable: raise, never start empty
        dest = (root / rel).resolve()
        if root not in dest.parents:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(body, encoding="utf-8")
        n += 1
    return n


def token_path():
    return DATA_DIR / "google-token.json"


def records_path():
    return DATA_DIR / "records.json"


# ---------------------------------------------------------------- Google client config ----------------------------------------------------------------

def google_client():
    """(client_id, client_secret) from the environment or .data/google-client.json, else None."""
    cid, secret = os.environ.get("GOOGLE_CLIENT_ID"), os.environ.get("GOOGLE_CLIENT_SECRET")
    if cid and secret:
        return cid, secret
    j = load_json(DATA_ROOT / "google-client.json", None)  # the app's, not an account's
    if isinstance(j, dict):
        block = j.get("web") or j.get("installed") or {}
        if block.get("client_id") and block.get("client_secret"):
            return block["client_id"], block["client_secret"]
    return None


CLAUDE_KEY_RE = re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,300}")


def claude_key_path():
    return DATA_DIR / "anthropic.json"


def saved_claude_key():
    try:
        k = json.loads(claude_key_path().read_text(encoding="utf-8")).get("key", "")
        return k if isinstance(k, str) and CLAUDE_KEY_RE.fullmatch(k) else ""
    except Exception:
        return ""


def claude_key():
    return os.environ.get("ANTHROPIC_API_KEY") or saved_claude_key()


def claude_key_state():
    """What Settings may show: where the key comes from and its last 4 characters. Never the key."""
    env, saved = os.environ.get("ANTHROPIC_API_KEY"), saved_claude_key()
    k = env or saved
    return {"saved": bool(k), "source": "env" if env else ("file" if saved else ""), "last4": k[-4:] if k else ""}


def claude_on():
    return bool(claude_key() or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


# ---------------------------------------------------------------- HTTP to Google (swappable in tests) ----------------------------------------------------------------

class GoogleError(Exception):
    def __init__(self, message, status=0, reason=""):
        super().__init__(message)
        self.status = status
        self.reason = reason


def _http(method, url, form=None, headers=None, timeout=15):
    """Returns (status, parsed JSON or {}). Never raises for HTTP status codes."""
    data = urllib.parse.urlencode(form).encode() if form is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=dict(headers or {}))
    if data is not None:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            status = resp.status
    except urllib.error.HTTPError as e:
        body, status = e.read(), e.code
    except (urllib.error.URLError, OSError) as e:
        raise GoogleError("could not reach Google (" + type(e).__name__ + ")") from None
    try:
        return status, (json.loads(body) if body else {})
    except ValueError:
        return status, {}


HTTP = _http


# ---------------------------------------------------------------- OAuth: state, PKCE, tokens ----------------------------------------------------------------

PENDING = {}            # state -> (code_verifier, expires_at)
PENDING_LOCK = threading.Lock()
TOKEN_LOCK = threading.Lock()


def pkce_pair():
    verifier = secrets.token_urlsafe(64)  # 86 characters, inside the 43 to 128 that PKCE allows
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    return verifier, challenge


def new_auth_request(client_id, now=None):
    """Returns (consent URL, state). The state and its PKCE verifier are kept here, never in the browser."""
    now = _time.time() if now is None else now
    state = secrets.token_urlsafe(24)
    verifier, challenge = pkce_pair()
    with PENDING_LOCK:
        for k in [k for k, (_, exp) in PENDING.items() if exp <= now]:
            del PENDING[k]
        while len(PENDING) >= (2000 if HOSTED else 50):  # never grows without bound
            PENDING.pop(next(iter(PENDING)))
        PENDING[state] = (verifier, now + STATE_TTL)
    q = {
        "client_id": client_id, "redirect_uri": redirect_uri(), "response_type": "code", "scope": SCOPES,
        "access_type": "offline", "prompt": "consent", "include_granted_scopes": "true",
        "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
    }
    return AUTH_URL + "?" + urllib.parse.urlencode(q), state


def take_state(state, now=None):
    """The verifier for a state, once. None if unknown, used or expired."""
    now = _time.time() if now is None else now
    if not isinstance(state, str) or not state:
        return None
    with PENDING_LOCK:
        item = PENDING.pop(state, None)
    if not item or item[1] <= now:
        return None
    return item[0]


def exchange_code(code, verifier):
    client = google_client()
    if not client:
        raise GoogleError("Google sign-in isn't set up on this PC yet")
    status, j = HTTP("POST", TOKEN_URL, form={
        "code": code, "client_id": client[0], "client_secret": client[1], "redirect_uri": redirect_uri(),
        "grant_type": "authorization_code", "code_verifier": verifier,
    })
    if status != 200 or not j.get("access_token"):
        raise GoogleError("Google did not accept the sign-in (" + str(j.get("error") or status) + ")", status, j.get("error", ""))
    granted = set(str(j.get("scope", "")).split())
    if CAL_SCOPE not in granted:
        raise GoogleError("Overture needs to see your calendar. Connect again and tick the calendar box on Google's screen.", 400, "scope")
    status, me = HTTP("GET", USERINFO_URL, headers={"Authorization": "Bearer " + j["access_token"]})
    me = me if status == 200 else {}
    tok = {
        "access_token": j["access_token"], "refresh_token": j.get("refresh_token", ""),
        "expires_at": int(_time.time()) + int(j.get("expires_in", 3600)), "scope": j.get("scope", ""),
        "email": str(me.get("email", "")), "name": str(me.get("name", "")),
    }
    if HOSTED and not account_allowed(tok["email"]):
        raise GoogleError("This Google account can't use this Overture. Ask the person who runs it to add you.", 403, "not_allowed")
    with as_user(account_id(tok["email"])) if HOSTED else contextlib.nullcontext():
        old = load_json(token_path(), {})
        if not tok["refresh_token"] and old.get("refresh_token"):  # Google only sends it on first consent
            tok["refresh_token"] = old["refresh_token"]
        with TOKEN_LOCK:
            save_json(token_path(), tok)
        clear_cache()
    return tok


# ---------------------------------------------------------------- accounts (the shared site) ----------------------------------------------------------------

SESSION_COOKIE = "overture_session"
OAUTH_COOKIE = "overture_signin"  # the sign-in this browser started (its OAuth state), checked when Google sends it back
SESSION_DAYS = 30
SESSIONS_LOCK = threading.Lock()
SIGNED_OUT = "signed-out"  # where a signed-out visitor's status is read: no account id looks like this


def account_id(email):
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()[:24]


def account_allowed(email):
    """MOAB_ALLOWED (emails or @domains, comma-separated) limits who may sign in. Unset: anyone Google lets through (while the
    Google app is in Testing, only its test users)."""
    allow = [a.strip().lower() for a in os.environ.get("MOAB_ALLOWED", "").split(",") if a.strip()]
    e = email.strip().lower()
    return bool(e) and (not allow or e in allow or any(a.startswith("@") and e.endswith(a) for a in allow))


def sessions_path():
    return DATA_ROOT / "sessions.json"


def _sid_key(sid):
    return hashlib.sha256(sid.encode("utf-8")).hexdigest()  # only a hash is saved, so the saved file can't sign anyone in


def new_session(email, now=None):
    now = _time.time() if now is None else now
    sid = secrets.token_urlsafe(32)
    with SESSIONS_LOCK:
        s = {k: v for k, v in load_json(sessions_path(), {}).items() if isinstance(v, dict) and v.get("exp", 0) > now}
        s[_sid_key(sid)] = {"uid": account_id(email), "email": email, "exp": now + SESSION_DAYS * 86400}
        save_json(sessions_path(), s)
    return sid


def _cookie_value(headers, name):
    c = http.cookies.SimpleCookie()
    try:
        c.load(headers.get("Cookie") or "")
    except http.cookies.CookieError:
        return ""
    m = c.get(name)
    return m.value if m else ""


def _cookie_sid(headers):
    return _cookie_value(headers, SESSION_COOKIE)


def session_user(headers, now=None):
    """The account this browser is signed in as, or None."""
    sid = _cookie_sid(headers)
    if not sid:
        return None
    v = load_json(sessions_path(), {}).get(_sid_key(sid))  # no lock: saves replace the file in one step
    now = _time.time() if now is None else now
    ok = isinstance(v, dict) and v.get("exp", 0) > now and isinstance(v.get("uid"), str) and account_allowed(str(v.get("email", "")))
    return v["uid"] if ok else None


def end_sessions(uid):
    """Sign an account out everywhere (every browser and device)."""
    with SESSIONS_LOCK:
        s = load_json(sessions_path(), {})
        keep = {k: v for k, v in s.items() if not (isinstance(v, dict) and v.get("uid") == uid)}
        if len(keep) != len(s):
            save_json(sessions_path(), keep)


def session_cookie(sid, days=SESSION_DAYS):
    return f"{SESSION_COOKIE}={sid}; Path=/; Max-Age={days * 86400}; HttpOnly; Secure; SameSite=Lax"


def token_info():
    tok = load_json(token_path(), None)
    return tok if isinstance(tok, dict) and (tok.get("refresh_token") or tok.get("access_token")) else None


class NotConnected(Exception):
    pass


def access_token(force_refresh=False):
    with TOKEN_LOCK:
        tok = token_info()
        if not tok:
            raise NotConnected()
        if not force_refresh and tok.get("access_token") and tok.get("expires_at", 0) - 60 > _time.time():
            return tok["access_token"]
        client = google_client()
        if not client or not tok.get("refresh_token"):
            raise GoogleError("the Google sign-in expired. Connect again.", 401, "expired")
        status, j = HTTP("POST", TOKEN_URL, form={
            "client_id": client[0], "client_secret": client[1], "refresh_token": tok["refresh_token"], "grant_type": "refresh_token",
        })
        if status != 200 or not j.get("access_token"):
            if j.get("error") == "invalid_grant":  # revoked or expired for good: forget it
                remove_file(token_path())
                raise GoogleError("Google ended the connection. Connect again.", 401, "invalid_grant")
            raise GoogleError("could not refresh the Google sign-in (" + str(j.get("error") or status) + ")", status)
        tok["access_token"] = j["access_token"]
        tok["expires_at"] = int(_time.time()) + int(j.get("expires_in", 3600))
        save_json(token_path(), tok)
        return tok["access_token"]


def disconnect():
    tok = token_info()
    if tok:
        t = tok.get("refresh_token") or tok.get("access_token")
        try:
            HTTP("POST", REVOKE_URL, form={"token": t})
        except GoogleError:
            pass  # still forget it locally
    remove_file(token_path())
    clear_cache()


# ---------------------------------------------------------------- calendar ----------------------------------------------------------------

CACHE = PerUser(lambda: {"at": 0.0, "events": None})
CACHE_LOCK = threading.Lock()


def clear_cache():
    with CACHE_LOCK:
        CACHE["at"], CACHE["events"] = 0.0, None


def fetch_events(now=None):
    """Primary calendar from DAYS_BACK ago to DAYS_AHEAD ahead, cached for a minute."""
    now = now or datetime.now(timezone.utc)
    with CACHE_LOCK:
        if CACHE["events"] is not None and _time.time() - CACHE["at"] < CACHE_SECONDS:
            return CACHE["events"]
    base = {
        "timeMin": (now - timedelta(days=DAYS_BACK)).isoformat(), "timeMax": (now + timedelta(days=DAYS_AHEAD)).isoformat(),
        "singleEvents": "true", "orderBy": "startTime", "maxResults": "2500",
        "fields": "items(id,status,summary,description,start,end,attendees,hangoutLink,conferenceData(conferenceId,conferenceSolution/key/type)),nextPageToken",
    }
    events, page = [], None
    for _ in range(4):
        q = dict(base, **({"pageToken": page} if page else {}))
        url = EVENTS_URL + "?" + urllib.parse.urlencode(q)
        status, j = HTTP("GET", url, headers={"Authorization": "Bearer " + access_token()})
        if status == 401:
            status, j = HTTP("GET", url, headers={"Authorization": "Bearer " + access_token(force_refresh=True)})
        if status != 200:
            err = (j.get("error") or {}) if isinstance(j, dict) else {}
            reasons = " ".join(str(e.get("reason", "")) for e in err.get("errors", []) if isinstance(e, dict))
            if "accessNotConfigured" in reasons or "SERVICE_DISABLED" in json.dumps(err):
                raise GoogleError("the Google Calendar API is off in your Google Cloud project. Turn it on (Settings > Setup guides > Connect Google Calendar, step 2).", status)
            if status == 401:
                raise GoogleError("Google said the sign-in expired. Connect again.", 401)
            raise GoogleError("Google Calendar answered " + str(status), status)
        events += j.get("items", [])
        page = j.get("nextPageToken")
        if not page:
            break
    with CACHE_LOCK:
        CACHE["at"], CACHE["events"] = _time.time(), events
    return events


# ---------------------------------------------------------------- time in New York (no tzdata on this PC) ----------------------------------------------------------------

def _nth_sunday(year, month, n):
    d = date(year, month, 1)
    return d + timedelta(days=(6 - d.weekday()) % 7 + 7 * (n - 1))


def et_offset(utc_dt):
    """US Eastern: daylight time from 2:00 on the 2nd Sunday of March to 2:00 on the 1st Sunday of November."""
    y = utc_dt.year
    start = datetime.combine(_nth_sunday(y, 3, 2), time(7), tzinfo=timezone.utc)
    end = datetime.combine(_nth_sunday(y, 11, 1), time(6), tzinfo=timezone.utc)
    return timedelta(hours=-4) if start <= utc_dt < end else timedelta(hours=-5)


def to_et(dt):
    u = dt.astimezone(timezone.utc)
    return u.astimezone(timezone(et_offset(u)))


def parse_dt(s):
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else None


def hm(dt):
    return f"{dt.hour}:{dt.minute:02d}"


def when_string(start, end):
    """Same format as data/sample.js: "Tue Oct 20, 10:00 to 10:45 ET"."""
    s, e = to_et(start), to_et(end)
    return f"{DAYS[s.weekday()]} {MONTHS[s.month - 1]} {s.day}, {hm(s)} to {hm(e)} ET"


def short_day(d):
    return f"{MONTHS[d.month - 1]} {d.day}"


# ---------------------------------------------------------------- events -> Overture data ----------------------------------------------------------------

def domain_of(email):
    email = str(email or "").strip().lower()
    return email.rsplit("@", 1)[1] if "@" in email else ""


def name_from_email(email):
    local = str(email).split("@")[0]
    parts = [p for p in re.split(r"[._\-+]+", local) if p and not p.isdigit()]
    return " ".join(p.capitalize() for p in parts) or str(email)


RESERVED_TLDS = {"example", "test", "invalid", "localhost"}
RESERVED_DOMAINS = {"example.com", "example.org", "example.net"}


def name_from_work_email(email):
    """'priya.raman@acme.com' -> 'Priya Raman' when the address is plainly first.last; '' otherwise (jsmith@, info@)."""
    local = str(email or "").split("@")[0].lower()
    m = re.fullmatch(r"([a-z]{2,})[._-]([a-z]{2,})", local)
    if not m or local in ROLE_BOXES:
        return ""
    return m.group(1).capitalize() + " " + m.group(2).capitalize()


NAME_STOP = {"will", "and", "from", "to", "the", "is", "at", "for", "on", "with", "about", "re", "call", "meeting", "review", "intro", "sync", "here", "there",
             "today", "tomorrow", "team", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "january", "february",
             "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"}
# A surname: a capital, then letters with at least one lowercase one ("Kim", "McDonald", "O'Brien"; not "CEO" or "TKS").
SURNAME = r"([A-Z](?=[A-Za-z'’-]*[a-z])[A-Za-z'’-]{1,30})"


def name_from_event(email, inv):
    """No name on the invite: find '<first name> Lastname' in the event's own title or description, where the first name is
    the one in their email (shea@acme.com + 'Call with Shea Kim' -> 'Shea Kim'). The event's own text is on the user's calendar,
    usually written by whoever set up the call; the page always says the name came from the event description."""
    first = re.split(r"[._\-+]", str(email or "").split("@")[0].lower())[0]
    if not re.fullmatch(r"[a-z]{2,30}", first) or first in ROLE_BOXES:
        return ""
    text = "\n".join([str(inv.get("title") or ""), str(inv.get("notes") or "")])[:4000]
    for m in re.finditer(r"(?i:\b" + re.escape(first) + r")[ \t]+" + SURNAME + r"(?:[ \t]+" + SURNAME + r")?\b", text):
        words = []
        for w in (w for w in m.groups() if w):  # "Shea Kim's team" / "Shea Kim's Backstage demo" -> Shea Kim: a possessive ends the name
            words.append(re.sub(r"['’]s$", "", w))
            if words[-1] != w:
                break
        while words and words[-1].lower() in NAME_STOP:
            words.pop()
        if words and words[0].lower() not in NAME_STOP:
            return first.capitalize() + " " + " ".join(words)
    return ""


def fake_domain(d):
    """Domains reserved for examples (RFC 2606): nobody real works there."""
    d = str(d or "").lower()
    return d in RESERVED_DOMAINS or d.rsplit(".", 1)[-1] in RESERVED_TLDS


def name_from_domain(domain):
    labels = [x for x in str(domain).lower().split(".") if x]
    if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in {"co", "com", "org", "net", "ac", "gov", "edu", "ltd", "plc"}:
        base = labels[-3]
    elif len(labels) >= 2:
        base = labels[-2]
    else:
        base = labels[0] if labels else ""
    return " ".join(w.capitalize() for w in re.split(r"[-_]+", base) if w)


def domain_map(records):
    return {str(c.get("domain")).lower(): name for name, c in records.get("companies", {}).items() if isinstance(c, dict) and c.get("domain")}


def records_company(domain, records):
    """The records store's name for a domain (or a parent domain), else None."""
    domain = str(domain).lower()
    if not domain or domain in PERSONAL_DOMAINS:
        return None
    dm = domain_map(records)
    d = domain
    while d.count(".") >= 1:
        if d in dm:
            return dm[d]
        d = d.split(".", 1)[1]
    return None


def company_for_domain(domain, records):
    """The records store's name for a domain (or a parent domain), else a name made from the domain. None for personal mail."""
    domain = str(domain).lower()
    if not domain or domain in PERSONAL_DOMAINS:
        return None
    return records_company(domain, records) or name_from_domain(domain) or None


def plain_text(desc, limit=2000):
    """Google descriptions can hold HTML: keep the words only."""
    import html as _h
    t = str(desc or "")
    t = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>", "\n", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = _h.unescape(t)
    t = "\n".join(" ".join(line.split()) for line in t.splitlines())
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    return t[:limit]


ZOOM_ID_RE = re.compile(r"(?i)\bhttps?://(?:[a-z0-9-]+\.)*zoom\.us/(?:j|w|s|wc(?:/join)?)/(\d{9,11})\b")


def zoom_id(ev):
    """The Zoom meeting number from the invite (its location, description or conference data), or ""."""
    conf = ev.get("conferenceData") or {}
    texts = [str(ev.get("location") or ""), str(ev.get("description") or "")]
    texts += [str(e.get("uri") or "") for e in conf.get("entryPoints") or [] if isinstance(e, dict)]
    for t in texts:
        m = ZOOM_ID_RE.search(t)
        if m:
            return m.group(1)
    return ""


def meeting_code(ev):
    link = str(ev.get("hangoutLink") or "")
    m = re.search(r"meet\.google\.com/([a-z0-9-]+)", link)
    if m:
        return m.group(1)
    conf = ev.get("conferenceData") or {}
    key = (((conf.get("conferenceSolution") or {}).get("key") or {}).get("type"))
    if key == "hangoutsMeet" and conf.get("conferenceId"):
        return str(conf["conferenceId"])
    return ""


def safe_id(s):
    return re.sub(r"[^A-Za-z0-9_-]", "", str(s))[:200] or "event"


def norm_name(n):
    return " ".join(str(n).lower().split())


ROLE_BOXES = {"info", "sales", "hello", "team", "support", "contact", "admin", "noreply", "no-reply", "office", "hr",
              "billing", "marketing", "partners"}


def personish(p):
    """A full name on someone's own address. First names alone and shared mailboxes (info@) collide across companies."""
    return len(norm_name(p["name"]).split()) >= 2 and p["email"].split("@")[0] not in ROLE_BOXES


def _event_times(ev):
    st, en = (ev.get("start") or {}), (ev.get("end") or {})
    if "dateTime" not in st:  # all-day
        return None, None
    s, e = parse_dt(st.get("dateTime")), parse_dt(en.get("dateTime"))
    if not s:
        return None, None
    return s, (e or s + timedelta(minutes=30))


def _others(ev, me_email):
    """Attendees who are not the user and not a room."""
    out = []
    for a in ev.get("attendees") or []:
        email = str(a.get("email", "")).strip().lower()
        if not email or a.get("self") or email == me_email or a.get("resource") or email.endswith("calendar.google.com"):
            continue
        # No name on the invite: the full name written in the event itself ("Call with Shea Kim") beats the email's first word.
        named = str(a.get("displayName") or "").strip() or name_from_event(email, {"title": ev.get("summary"), "notes": plain_text(ev.get("description"))})
        out.append({"name": named or name_from_email(email), "email": email})
    return out


def _declined(ev, me_email):
    for a in ev.get("attendees") or []:
        if (a.get("self") or str(a.get("email", "")).lower() == me_email) and a.get("responseStatus") == "declined":
            return True
    return False


def event_to_invite(ev, me_email, records):
    """One calendar event -> one Overture invite, or None when it isn't a call Overture should prep."""
    me_email = str(me_email or "").lower()
    if ev.get("status") == "cancelled" or _declined(ev, me_email):
        return None
    start, end = _event_times(ev)
    if not start:
        return None
    people = _others(ev, me_email)
    if not people:
        return None
    mine = domain_of(me_email)
    if mine and mine not in PERSONAL_DOMAINS and all(domain_of(p["email"]) == mine for p in people):
        return None  # internal meeting: only your own colleagues
    counts = {}
    for p in people:
        d = domain_of(p["email"])
        if d and d not in PERSONAL_DOMAINS and d != mine:
            counts[d] = counts.get(d, 0) + 1
    title = " ".join(str(ev.get("summary") or "").split())[:200] or "Untitled call"
    domain = max(counts, key=lambda d: (counts[d], -list(counts).index(d))) if counts else ""
    company = (company_for_domain(domain, records) if domain else None) or title[:80]
    s_et, e_et = to_et(start), to_et(end)
    cid = safe_id(ev.get("id"))
    return {
        "id": cid, "title": title, "company": company, "domain": domain,
        "when": when_string(start, end), "start": s_et.isoformat(), "end": e_et.isoformat(),
        "attendees": people, "notes": plain_text(ev.get("description")), "meetingCode": meeting_code(ev), "zoomId": zoom_id(ev),
        "versionFile": "", "backstageSince": None,
        "afterNotes": str(((records.get("callNotes") or {}).get(cid) or {}).get("text", "")),
    }


def past_signals(events, me_email, records, now):
    """From meetings that already happened: who was last seen where, and which company domains you have met."""
    me_email = str(me_email or "").lower()
    by_name, domains = {}, set()
    for ev in events:
        if ev.get("status") == "cancelled":
            continue
        start, end = _event_times(ev)
        if not start or end > now:
            continue
        for p in _others(ev, me_email):
            d = domain_of(p["email"])
            if not d or d in PERSONAL_DOMAINS:
                continue
            domains.add(d)
            if not personish(p):
                continue
            prev = by_name.get(norm_name(p["name"]))
            if not prev or prev["at"] <= start:
                by_name[norm_name(p["name"])] = {"domain": d, "at": start, "email": p["email"]}
    return by_name, domains


def same_org(d1, d2, records):
    return d1 == d2 or company_for_domain(d1, records) == company_for_domain(d2, records)


RECENT_HOURS = 48  # a call stays on the list this long after it ends, marked ended, so After the call still works


def upcoming_invites(events, me_email, records, now):
    """The calls Overture preps: the next DAYS_AHEAD days, plus calls that ended in the last RECENT_HOURS (ended: true), with
    ids made unique."""
    invites = []
    for ev in events:
        start, end = _event_times(ev)
        if not start or end <= now - timedelta(hours=RECENT_HOURS) or start > now + timedelta(days=DAYS_AHEAD):
            continue
        inv = event_to_invite(ev, me_email, records)
        if inv:
            inv["ended"] = end <= now
            invites.append(inv)
    invites.sort(key=lambda i: (bool(i.get("ended")), i["start"]))  # upcoming first, then the ones that just ended
    seen_ids = set()
    for inv in invites:  # recurring events can repeat an id across copies; keep ids unique for links
        base, n = inv["id"], 2
        while inv["id"] in seen_ids:
            inv["id"], n = base + "-" + str(n), n + 1
        seen_ids.add(inv["id"])
    return invites


def build_live(events, me, records, now=None, meta_out=None, crm=None):
    """Calendar events + records -> the same shape as window.SAMPLE in data/sample.js.
    meta_out (a dict), when given, gets what invitee research needs per guest (see queue_research).
    crm (from crm_fetch), when given, adds HubSpot companies, deals, notes and titles, and Gong's last calls."""
    now = now or datetime.now(timezone.utc)
    me = me or {}
    me_email = str(me.get("email", "")).lower()
    today_et = to_et(now).date()
    invites = upcoming_invites(events, me_email, records, now)
    crm = crm or {}
    hs_cos, hs_people = crm.get("companies") or {}, crm.get("contacts") or {}

    rec_people = records.get("people") or {}
    rec_cos = records.get("companies") or {}
    by_name, met_domains = past_signals(events, me_email, records, now)

    people, watch, flagged = {}, [], set()
    for inv in invites:
        for a in inv["attendees"]:
            r = rec_people.get(a["email"]) or {}
            p = {"photo": "", "title": str(r.get("title", "")), "startedAt": str(r.get("startedAt", "")), "previous": str(r.get("previous", "")),
                 "previousRole": "", "known": user_known(r), "note": str(r.get("note", ""))}
            hs = hs_people.get(a["email"])
            if hs:  # HubSpot's title first; a title you typed in Overture still shows (and can be sent to HubSpot after the call)
                p["known"], p["hubspot"] = True, True
                if hs.get("title") and not user_has_title(r):
                    p["title"], p["titleSrc"] = hs["title"], "HubSpot"
                elif p["title"]:
                    p["titleSrc"] = "Overture records"
            d = domain_of(a["email"])
            seen = by_name.get(norm_name(a["name"]))
            if personish(a) and seen and d and d not in PERSONAL_DOMAINS and not same_org(seen["domain"], d, records) and a["email"] not in flagged:
                old = company_for_domain(seen["domain"], records) or seen["domain"]
                new = company_for_domain(d, records) or d
                if not p["previous"]:
                    p["previous"] = old
                flagged.add(a["email"])
                last = to_et(seen["at"]).date()
                watch.append({"date": short_day(today_et), "kind": "Job change", "callId": inv["id"], "title": a["name"] + " moved to " + new,
                              "text": a["name"] + " was at " + old + " when you last met (" + short_day(last) + ", " + str(last.year) + "). "
                              + "This invite uses a " + new + " address, so they have likely moved. Ask what changed."})
            people.setdefault(a["email"], p)

    # Invitee research: what the background worker needs, the local facts it always shows, and a "New on the call" alert
    # for each guest it looked up in the last 30 days.
    # Names research may send: the latest calendar display name, else a full name in the event's own text, else a plain
    # first.last work address (never the address itself; the page says where the name came from).
    last_met, display, display_at = {}, {}, {}
    for ev in events:
        start, end = _event_times(ev)
        at = start or datetime.min.replace(tzinfo=timezone.utc)
        for a in ev.get("attendees") or []:
            dn, em = str(a.get("displayName") or "").strip(), str(a.get("email", "")).strip().lower()
            if dn and (em not in display_at or display_at[em] <= at):
                display[em], display_at[em] = dn, at
        if ev.get("status") == "cancelled" or not start or end > now:
            continue
        for a in _others(ev, me_email):
            if a["email"] not in last_met or last_met[a["email"]] < start:
                last_met[a["email"]] = start
    mine = domain_of(me_email)
    meta = {} if meta_out is None else meta_out
    alerted = set()
    for inv in invites:
        for a in inv["attendees"]:
            email, d = a["email"], domain_of(a["email"])
            if email in meta:
                continue
            co = company_for_domain(d, records) or ""
            met = last_met.get(email)
            # No name on the invite: the event's own text or a plain first.last work address still gives one, and the page says where it came from.
            from_event = "" if display.get(email) else name_from_event(email, inv)
            from_email = "" if display.get(email) or from_event else name_from_work_email(email)
            meta[email] = {
                "name": display.get(email, "") or from_event or from_email, "company": co, "domain": d, "callId": inv["id"],
                "start": inv.get("start", ""),  # their soonest call: deep research waits until it is DEEP_DAYS_AHEAD days away
                "named": bool(display.get(email) or from_event or from_email),
                "nameFrom": "invite" if display.get(email) else ("event" if from_event else ("email" if from_email else "")),
                "internal": bool(mine and mine not in PERSONAL_DOMAINS and same_org(d, mine, records)),
                "crm": bool((hs_people.get(email) or {}).get("title")),  # HubSpot has their title: no web lookup
                "local": {"company": co, "adopter": bool(co and adopter_for(co)), "metBefore": bool(met),
                          "lastMet": (short_day(to_et(met).date()) + ", " + str(to_et(met).year)) if met else ""},
            }
            r = rec_people.get(email) or {}
            found_at = parse_dt(r.get("foundAt"))
            if r.get("lookup") in ("done", "unknown") and found_at and now - found_at <= timedelta(days=RESEARCH_DAYS) and email not in alerted:
                alerted.add(email)
                title = str(r.get("title") or "")
                rel = RELATIONSHIPS.get(str(r.get("relationship") or ""), "")
                facts = ", ".join(x for x in (title, rel, str(r.get("team") or "")) if x)
                summary = ((profile_view(r.get("profile"), "person") or {}).get("summary") or {}).get("text", "")
                text = (" ".join(x for x in ("Overture looked them up" + (": " + facts if facts else "") + ".", summary) if x)
                        if r.get("lookup") == "done" else searched_note(r, "work information about them") + " Ask what they do on the call.")
                watch.append({"date": short_day(to_et(found_at).date()), "kind": "New person", "callId": inv["id"], "person": a["name"],
                              "title": "New on the " + inv["company"] + " call: " + a["name"] + ", " + (title or "role unknown"), "text": text})

    first_done = set()
    for inv in invites:
        d, co = inv["domain"], inv["company"]
        if not d or co in first_done or co in rec_cos:
            continue
        if not any(same_org(d, md, records) for md in met_domains):
            first_done.add(co)
            org = (records.get("orgs") or {}).get(d) or {}
            about = ((profile_view(org.get("profile"), "org") or {}).get("summary") or {}).get("text", "")
            if not about and org.get("lookup") == "unknown":
                about = searched_note(org, "information about this company")
            watch.append({"date": short_day(today_et), "kind": "First meeting", "callId": inv["id"], "title": "First meeting with " + co,
                          "text": "Nobody from " + co + " is in your calendar for the last " + str(DAYS_BACK // 30) + " months, so this looks like your first talk."
                          + (" " + about if about else "")})

    prefs = effective_settings(records)
    watch = apply_alert_rules(watch, prefs)  # Settings > Alert rules: job changes, new invitees

    updates = records.get("updates") or {}
    companies = {}
    with_history ={u.get("company") for items in updates.values() if isinstance(items, list) for u in items if isinstance(u, dict)}
    all_cos = dict(rec_cos)
    for name in with_history:  # accepted after-call updates make a company part of Overture's records too
        if name and name not in all_cos:
            all_cos[name] = {}
    for name, c in all_cos.items():
        if not isinstance(c, dict):
            continue
        hist = []
        for cid, items in updates.items():
            for u in items if isinstance(items, list) else []:
                if u.get("company") == name:
                    hist.append({"date": str(u.get("at", ""))[:10], "text": u.get("kind", "") + ": " + u.get("text", "")})
        hist.sort(key=lambda h: h["date"])
        status = str(c.get("status") or "Prospect")
        companies[name] = {"engineers": c.get("engineers"), "status": status, "history": hist,
                           "customer": bool(c.get("customer")) or status.startswith("Customer"),
                           "notes": str(c.get("notes", "")), "domain": str(c.get("domain", ""))}
    company_domains = {}
    for inv in invites:
        if inv["domain"]:
            company_domains.setdefault(inv["company"], inv["domain"])
    for name, domain in company_domains.items():
        info = hs_cos.get(domain)
        if info:
            apply_hubspot_company(companies, name, domain, info)

    live = {
        "today": today_et.isoformat(), "me": {"email": me_email, "name": str(me.get("name", ""))},
        "invites": invites, "people": people, "companies": companies, "companyDomains": company_domains,
        "papers": {}, "currentSecurityPack": "", "relationships": [], "mentioned": [], "watch": watch,
        "settings": {"gongInAI": gong_in_ai(records), "gongTranscripts": setting_on(records, "gongTranscripts"),
                     "transcriptsInAI": setting_on(records, "transcriptsInAI")},
        "appSettings": prefs,  # everything on the Settings page (settings.js reads it)
        "mentions":{cid: len(m.get("items") or []) + len(m.get("orgs") or []) for cid, m in (records.get("mentions") or {}).items()
                     if isinstance(m, dict) and (m.get("items") or m.get("orgs")) and cid in {i["id"] for i in invites}},
    }
    # People and companies mentioned on these calls, as map nodes and labelled edges (see "connections" further down)
    live["mentioned"], live["relationships"] = connections_graph(records, {i["id"] for i in invites}, set(people))
    if crm.get("gong"):
        live["gong"] = crm["gong"]
    if crm.get("currency"):
        live["currency"] = crm["currency"]
    research_fill(live, records, meta)
    return live


def script_json(obj):
    """JSON that is safe to place inside a <script>."""
    return json.dumps(obj, ensure_ascii=True).replace("</", "<\\/")


def status_body():
    tok = token_info()
    return {
        "hosted": HOSTED,  # the shared site: the page says your data stays in your account, not on this PC
        "claude": claude_on(),  # kept for older pages
        "google": {"configured": bool(google_client()), "connected": bool(tok), "email": (tok or {}).get("email", "")},
        "ai": {"claude": claude_on()},
        **crm_status(),  # hubspot: {configured, connected, portal, ...}, gong: {configured, connected, workspace, ...}
        "granola": granola_status(),
        "meetily": {k: v for k, v in meetily_status().items() if k in ("on", "found", "recording", "error")},
    }


def granola_status():
    on = bool(granola_key())
    with CRM_LOCK:
        st = dict(CRM_STATE["granola"])
    return {"configured": on, "connected": bool(on and st["lastSync"] and not st["lastError"]),
            "lastSync": st["lastSync"] if on else "", "lastError": st["lastError"] if on else ""}


def live_now(records, meta_out=None, now=None):
    """Your calendar + Overture records + HubSpot and Gong -> (live data, the HubSpot/Gong data it used). Raises GoogleError / NotConnected."""
    now = now or datetime.now(timezone.utc)
    tok = token_info() or {}
    me = {"email": tok.get("email", ""), "name": tok.get("name", "")}
    events = fetch_events()
    crm = crm_fetch(upcoming_invites(events, me["email"].lower(), records, now), me["email"], records, now)
    return build_live(events, me, records, now, meta_out=meta_out, crm=crm), crm


def live_script():
    crm_probe()
    data, err = None, ""
    if token_info():
        try:
            prune_old_quotes()  # Settings > Mentions > keep quotes for N days, before the People map shows them
            records, meta = load_records(), {}
            data, _ = live_now(records, meta_out=meta)
            prefs = data.get("appSettings") or effective_settings(records)
            if crm_configured("hubspot") and prefs["research"]["hubspot"]:  # Settings > Alert rules: HubSpot stage changes
                alerts, seen = stage_alerts(data.get("companies"), load_json(stages_path(), {}), datetime.now(timezone.utc), data.get("invites") or [])
                save_json(stages_path(), seen)
                if prefs["alerts"]["signals"]["hubspotStages"]:
                    data["watch"] = data["watch"] + alerts
            if not prefs["research"]["web"]:
                pass  # Settings > Research sources: web research is off, so no guest is looked up on the web
            elif queue_research(meta, records) | queue_org_research(meta, records):  # | : both always run
                research_fill(data, records, meta)  # show the new guests and companies as "Looking up…" at once
        except NotConnected:
            pass
        except GoogleError as e:
            err = str(e)
    st = status_body()  # after the fetch, so HubSpot and Gong say how it went
    out = "window.MOAB_STATUS = " + script_json(st) + ";\nwindow.MOAB_LIVE = " + script_json(data) + ";\n"
    if err:
        out += "window.MOAB_LIVE_ERROR = " + script_json(err) + ";\n"
    return out


# ---------------------------------------------------------------- records store ----------------------------------------------------------------

RECORDS_LOCK = threading.Lock()
MAX_RECORDS_BYTES = 5_000_000
EMAIL_RE = re.compile(r"^[^@\s<>\"']{1,64}@[a-z0-9.-]{1,253}\.[a-z]{2,}$")
DOMAIN_RE = re.compile(r"^(?=.{3,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$")
CALLID_RE = re.compile(r"^[A-Za-z0-9_-]{1,200}$")
YM_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def empty_records():
    return {"version": 1, "companies": {}, "people": {}, "callNotes": {}, "updates": {}, "settings": {}, "hubspotSaved": {},
            "mentions": {}, "knownPeople": {}, "connections": {}, "connectionsRemoved": {}, "granola": {}, "orgs": {}}


def load_records():
    r = load_json(records_path(), None)
    if not isinstance(r, dict):
        return empty_records()
    base = empty_records()
    for k in ("companies", "people", "callNotes", "updates", "settings", "hubspotSaved", "mentions", "knownPeople", "connections", "connectionsRemoved", "granola",
              "orgs"):
        if isinstance(r.get(k), dict):
            base[k] = r[k]
    return base


class Invalid(Exception):
    pass


def _str(body, key, limit, required=False):
    v = body.get(key)
    if v is None:
        if required:
            raise Invalid(key + " is required")
        return None
    if not isinstance(v, str):
        raise Invalid(key + " must be text")
    v = v.strip()
    if len(v) > limit:
        raise Invalid(key + " is too long (max " + str(limit) + ")")
    if required and not v:
        raise Invalid(key + " is required")
    return v


def _only(body, keys):
    if not isinstance(body, dict):
        raise Invalid("send a JSON object")
    extra = set(body) - set(keys)
    if extra:
        raise Invalid("unknown field: " + sorted(extra)[0])


def clean_company(body):
    _only(body, {"name", "status", "notes", "domain", "engineers", "customer"})
    out = {"name": _str(body, "name", 120, True)}
    for k, lim in (("status", 80), ("notes", 4000)):
        v = _str(body, k, lim)
        if v is not None:
            out[k] = v
    d = _str(body, "domain", 253)
    if d is not None:
        d = d.lower()
        if d and (not DOMAIN_RE.match(d) or d in PERSONAL_DOMAINS):
            raise Invalid("domain doesn't look like a company web address")
        out["domain"] = d
    if "engineers" in body:
        e = body["engineers"]
        if e is not None and (isinstance(e, bool) or not isinstance(e, int) or not 0 <= e <= 10_000_000):
            raise Invalid("engineers must be a whole number")
        out["engineers"] = e
    if "customer" in body:
        if not isinstance(body["customer"], bool):
            raise Invalid("customer must be true or false")
        out["customer"] = body["customer"]
    return out


def clean_person(body):
    _only(body, {"email", "title", "note", "startedAt", "previous", "confirm"})
    email = _str(body, "email", 254, True).lower()
    if not EMAIL_RE.match(email):
        raise Invalid("email doesn't look right")
    out = {"email": email}
    if "confirm" in body:
        if body["confirm"] is not True:
            raise Invalid("confirm must be true")
        out["confirm"] = True
    for k, lim in (("title", 120), ("note", 2000), ("previous", 120)):
        v = _str(body, k, lim)
        if v is not None:
            out[k] = v
    s = _str(body, "startedAt", 7)
    if s is not None:
        if s and not YM_RE.match(s):
            raise Invalid("startedAt must look like 2024-05")
        out["startedAt"] = s
    return out


def clean_call_notes(body):
    _only(body, {"callId", "text"})
    cid = _str(body, "callId", 200, True)
    if not CALLID_RE.match(cid):
        raise Invalid("callId doesn't look right")
    text = body.get("text")
    if not isinstance(text, str) or len(text) > 20000:
        raise Invalid("text must be text, at most 20000 characters")
    return {"callId": cid, "text": text}


def clean_apply(body):
    _only(body, {"callId", "company", "accept", "undo"})
    cid = _str(body, "callId", 200, True)
    if not CALLID_RE.match(cid):
        raise Invalid("callId doesn't look right")
    company = _str(body, "company", 120, True)
    lists = {}
    for k in ("accept", "undo"):
        items = body.get(k, [])
        if not isinstance(items, list) or len(items) > 50:
            raise Invalid(k + " must be a list of at most 50 updates")
        clean = []
        for it in items:
            if not isinstance(it, dict) or set(it) - {"kind", "text"}:
                raise Invalid("each update has a kind and a text")
            kind, text = it.get("kind"), it.get("text")
            if kind not in UPDATE_KINDS or not isinstance(text, str) or not text.strip() or len(text) > 1000:
                raise Invalid("bad update")
            clean.append({"kind": kind, "text": text.strip()})
        lists[k] = clean
    if not lists["accept"] and not lists["undo"]:
        raise Invalid("nothing to apply")
    return {"callId": cid, "company": company, "accept": lists["accept"], "undo": lists["undo"]}


SETTINGS = ("gongInAI", "gongTranscripts", "transcriptsInAI")  # all off unless you turn them on (Data page)


def clean_settings(body):
    _only(body, set(SETTINGS))
    if not body:
        raise Invalid("send a setting")
    for k, v in body.items():
        if not isinstance(v, bool):
            raise Invalid(k + " must be true or false")
    return dict(body)


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def write_records(kind, body):
    """Validate, merge and save one change. Returns the saved part."""
    cleaners = {"company": clean_company, "person": clean_person, "call-notes": clean_call_notes, "apply": clean_apply, "settings": clean_settings}
    if kind not in cleaners:
        raise Invalid("unknown record type")
    c = cleaners[kind](body)
    with RECORDS_LOCK:
        r = load_records()
        if kind == "company":
            name = c.pop("name")
            if c.get("domain"):  # one domain belongs to one company
                for other, rec in r["companies"].items():
                    if other != name and isinstance(rec, dict) and rec.get("domain") == c["domain"]:
                        rec["domain"] = ""
            if "status" in c and "customer" not in c:
                c["customer"] = c["status"].startswith("Customer")
            saved = r["companies"].setdefault(name, {})
            saved.update(c, updatedAt=now_iso())
            out = {"name": name, **saved}
        elif kind == "person":
            email = c.pop("email")
            confirm = c.pop("confirm", False)
            saved = r["people"].setdefault(email, {})
            # What the user types (or confirms) is theirs from now on: research never overwrites it.
            auto = [f for f in saved.get("autoFields") or [] if f not in c and not confirm]
            if confirm or saved.get("autoFields"):
                saved["autoFields"] = auto
                if confirm:
                    saved["found"], saved["confirmedAt"] = "confirmed", now_iso()
                elif not auto and saved.get("found") == "auto":
                    saved["found"] = "user"
            saved.update(c, updatedAt=now_iso())
            out = {"email": email, **saved}
        elif kind == "call-notes":
            if c["text"].strip():
                r["callNotes"][c["callId"]] = {"text": c["text"], "updatedAt": now_iso()}
            else:
                r["callNotes"].pop(c["callId"], None)
            out = {"callId": c["callId"], "text": c["text"]}
        elif kind == "settings":
            r["settings"].update(c)
            out = dict(r["settings"])
        else:
            items = r["updates"].setdefault(c["callId"], [])
            drop = {(u["kind"], u["text"]) for u in c["undo"]}
            items[:] = [u for u in items if (u.get("kind"), u.get("text")) not in drop]
            have = {(u.get("kind"), u.get("text")) for u in items}
            for u in c["accept"]:
                if (u["kind"], u["text"]) not in have:
                    items.append({"kind": u["kind"], "text": u["text"], "company": c["company"], "at": now_iso()})
            if not items:
                del r["updates"][c["callId"]]
            out = {"callId": c["callId"], "updates": items}
        if len(json.dumps(r)) > MAX_RECORDS_BYTES:
            raise Invalid("the records store is full")
        save_json(records_path(), r)
    return out


# ---------------------------------------------------------------- settings (the Settings page) ----------------------------------------------------------------
# GET /api/settings returns every setting (stored values over the defaults); PUT /api/settings takes one or more groups, each
# checked against SETTINGS_SPEC. Stored in records.settings next to the three older Data-page switches (gongInAI, gongTranscripts,
# transcriptsInAI), which stay top-level so the code that reads them keeps working; the Research group shows and writes them.
# The defaults must match settings.js (a test compares them).

BRIEF_SECTIONS = ("opener", "since", "lastTalk", "backstage", "todos", "people", "security", "rivals", "papers")
PANEL_CARDS = ("opener", "points", "watch", "send", "people", "map", "notes")
CALL_TYPES = ("intro", "discovery", "demo", "renewal", "other")
ALERT_SIGNALS = ("jobChanges", "newInvitees", "mentioned", "security", "release", "hubspotStages")
MAP_RELATIONS = ("people", "customer", "vendor", "partner", "competitor", "ownership", "other")
PRIORITY_RULES = ("engineers", "adopter", "deal", "alert", "customer")
LEGACY_SETTINGS = ("gongInAI", "gongTranscripts", "transcriptsInAI")
MAX_SETTINGS_BYTES = 64_000
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
# Watch kinds (alerts made on the server) -> the alert signal that turns them on or off. Kinds not listed always show.
ALERT_KIND_SIGNAL = {"Job change": "jobChanges", "New person": "newInvitees", "First meeting": "newInvitees", "Stage change": "hubspotStages"}
DEFAULT_TEMPLATES = {
    "intro": ("Good to meet you, {first_name}", "Hi {first_name},\n\nThanks for making time today. What I heard:\n{summary}\n\nNext step: {next_step}\n\nBest,\n{my_name}"),
    "discovery": ("{company} and Spotify: notes from {date}", "Hi {first_name},\n\nThanks for walking me through how {company} works today. My notes:\n{summary}\n\nNext step: {next_step}\n\nBest,\n{my_name}"),
    "demo": ("Your demo: what we covered", "Hi {first_name},\n\nThanks for joining the demo on {date}. What we covered:\n{summary}\n\nNext step: {next_step}\n\nBest,\n{my_name}"),
    "renewal": ("{company} renewal: next steps", "Hi {first_name},\n\nThanks for the renewal call today. What we agreed:\n{summary}\n\nNext step: {next_step}\n\nBest,\n{my_name}"),
    "other": ("Following up: {company}", "Hi {first_name},\n\nThanks for your time on {date}.\n{summary}\n\nNext step: {next_step}\n\nBest,\n{my_name}"),
}
BOOL = ("bool",)


def default_settings():
    return {
        "brief": {"sections": [{"id": s, "on": True} for s in BRIEF_SECTIONS], "length": "full", "tone": "direct"},
        "priorities": {"targets": [], "rules": {"engineers": {"on": True, "min": 200, "weight": 2}, "adopter": {"on": True, "weight": 2},
                                                "deal": {"on": True, "weight": 3}, "alert": {"on": True, "weight": 1}, "customer": {"on": True, "weight": 1}},
                       "target": 3, "hot": 5, "warm": 2, "sort": True},
        "panel": {"cards": [{"id": c, "on": True} for c in PANEL_CARDS], "density": "full", "listening": False},
        "followup": {"templates": {t: {"subject": s, "body": b} for t, (s, b) in DEFAULT_TEMPLATES.items()}},
        "mentions": {"autoLookup": True, "autoAdd": "single", "mapRelations": list(MAP_RELATIONS), "keepDays": 90},
        "alerts": {"signals": {s: True for s in ALERT_SIGNALS}, "security": "all", "delivery": "instant", "quiet": {"on": False, "from": "18:00", "to": "08:00"}},
        "research": {"web": True, "hubspot": True, "gong": True, "gongTranscripts": False, "gongInAI": False, "transcriptsInAI": False,
                     "aiShare": "notes", "blocked": [], "meetily": False, "granola": False},
        "appearance": {"theme": "dark", "accent": "green", "density": "comfortable"},  # Spotify-style dark + green by default
    }


def _rule(extra=None):
    return {"on": BOOL, "weight": ("int", 0, 5), **(extra or {})}


SETTINGS_SPEC = {
    "brief": {"sections": ("order", BRIEF_SECTIONS), "length": ("enum", ("full", "short")), "tone": ("enum", ("direct", "warm", "curious"))},
    "priorities": {"targets": ("names", 100, 120), "rules": {r: _rule({"min": ("int", 0, 100_000)} if r == "engineers" else None) for r in PRIORITY_RULES},
                   "target": ("int", 0, 5), "hot": ("int", 1, 25), "warm": ("int", 0, 25), "sort": BOOL},
    "panel": {"cards": ("order", PANEL_CARDS), "density": ("enum", ("full", "compact")), "listening": BOOL},
    "followup": {"templates": {t: {"subject": ("text", 200), "body": ("text", 4000)} for t in CALL_TYPES}},
    "mentions": {"autoLookup": BOOL, "autoAdd": ("enum", ("single", "likely")), "mapRelations": ("subset", MAP_RELATIONS), "keepDays": ("int", 1, 365)},
    "alerts": {"signals": {s: BOOL for s in ALERT_SIGNALS}, "security": ("enum", ("critical", "high", "all")), "delivery": ("enum", ("instant", "digest")),
               "quiet": {"on": BOOL, "from": ("time",), "to": ("time",)}},
    "research": {"web": BOOL, "hubspot": BOOL, "gong": BOOL, "gongTranscripts": BOOL, "gongInAI": BOOL, "transcriptsInAI": BOOL,
                 "aiShare": ("enum", ("titles", "notes", "transcripts")), "blocked": ("domains", 50), "meetily": BOOL, "granola": BOOL},
    "appearance": {"theme": ("enum", ("light", "dark")), "accent": ("enum", ("indigo", "green", "blue", "pink", "orange")),
                   "density": ("enum", ("comfortable", "compact"))},
}


def _blocked_domain(v):
    d = re.sub(r"^[a-z]+://", "", v.strip().lower()).split("/")[0].split("?")[0].removeprefix("www.")
    if not DOMAIN_RE.match(d):
        raise Invalid("“" + v[:60] + "” doesn't look like a web address (example: people-site.com)")
    return d


def _leaf(spec, v, path):
    kind = spec[0]
    if kind == "bool":
        if not isinstance(v, bool):
            raise Invalid(path + " must be true or false")
        return v
    if kind == "enum":
        if v not in spec[1]:
            raise Invalid(path + " must be one of " + ", ".join(spec[1]))
        return v
    if kind == "int":
        if isinstance(v, bool) or not isinstance(v, int) or not spec[1] <= v <= spec[2]:
            raise Invalid(path + " must be a whole number from " + str(spec[1]) + " to " + str(spec[2]))
        return v
    if kind == "text":
        if not isinstance(v, str) or len(v) > spec[1]:
            raise Invalid(path + " must be text of at most " + str(spec[1]) + " characters")
        return v
    if kind == "time":
        if not isinstance(v, str) or not TIME_RE.match(v):
            raise Invalid(path + " must be a time like 18:00")
        return v
    if kind == "order":  # every id exactly once, each shown or hidden
        if not isinstance(v, list) or len(v) != len(spec[1]):
            raise Invalid(path + " must list " + ", ".join(spec[1]))
        out = []
        for it in v:
            if not isinstance(it, dict) or set(it) != {"id", "on"} or it["id"] not in spec[1] or not isinstance(it["on"], bool):
                raise Invalid(path + " items are {id, on}")
            out.append({"id": it["id"], "on": it["on"]})
        if len({it["id"] for it in out}) != len(out):
            raise Invalid(path + " lists an item twice")
        return out
    if kind == "subset":
        if not isinstance(v, list) or any(x not in spec[1] for x in v):
            raise Invalid(path + " may only hold " + ", ".join(spec[1]))
        return [x for x in spec[1] if x in v]
    if kind in ("names", "domains"):
        cap = spec[1]
        if not isinstance(v, list) or len(v) > cap:
            raise Invalid(path + " holds at most " + str(cap) + " items")
        out = []
        for x in v:
            if not isinstance(x, str) or not x.strip():
                raise Invalid(path + " items must be text")
            x = _blocked_domain(x) if kind == "domains" else clean_text(x, 10**4).strip()
            if kind == "names" and len(x) > spec[2]:
                raise Invalid(path + " items are at most " + str(spec[2]) + " characters")
            if x.lower() not in {o.lower() for o in out}:
                out.append(x)
        return out
    raise Invalid("bad setting")


def _merge(spec, cur, patch, path):
    """cur (already valid) with patch on top; every value in patch is checked. Lists are replaced whole."""
    if isinstance(spec, dict):
        if not isinstance(patch, dict):
            raise Invalid(path + " must be an object")
        extra = set(patch) - set(spec)
        if extra:
            raise Invalid("unknown setting: " + (path + "." if path else "") + sorted(extra)[0])
        out = dict(cur)
        for k, v in patch.items():
            out[k] = _merge(spec[k], cur.get(k), v, (path + "." if path else "") + k)
        return out
    return _leaf(spec, patch, path)


def _sync_ai_share(research, patch):
    """"What may go to AI" and the older "Use transcripts in AI answers" switch are one choice: keep them in step."""
    if "transcriptsInAI" in patch and "aiShare" not in patch:
        research["aiShare"] = "transcripts" if research["transcriptsInAI"] else ("notes" if research["aiShare"] == "transcripts" else research["aiShare"])
    else:
        research["transcriptsInAI"] = research["aiShare"] == "transcripts"


def effective_settings(records):
    """Every setting: the stored values over the defaults. A stored group that no longer passes the checks falls back to its defaults."""
    out = default_settings()
    stored = records.get("settings") or {}
    for group, spec in SETTINGS_SPEC.items():
        val = stored.get(group)
        if isinstance(val, dict):
            try:
                out[group] = _merge(spec, out[group], val, group)
            except Invalid:
                pass
    res = out["research"]
    for k in LEGACY_SETTINGS:
        res[k] = stored.get(k) is True
    if res["transcriptsInAI"]:
        res["aiShare"] = "transcripts"
    elif res["aiShare"] == "transcripts":
        res["aiShare"] = "notes"
    p = out["priorities"]
    if p["warm"] >= p["hot"]:
        p["warm"] = max(0, p["hot"] - 1)
    return out


def save_settings(body):
    """PUT /api/settings: one or more groups (partial groups are fine). Returns every setting after the change."""
    if not isinstance(body, dict) or not body:
        raise Invalid("send one or more setting groups")
    if len(json.dumps(body)) > MAX_SETTINGS_BYTES:
        raise Invalid("settings are too big")
    with RECORDS_LOCK:
        r = load_records()
        cur = effective_settings(r)
        new = _merge(SETTINGS_SPEC, cur, body, "")
        if "research" in body:
            _sync_ai_share(new["research"], body["research"])
        if "priorities" in body and new["priorities"]["warm"] >= new["priorities"]["hot"]:
            raise Invalid("Warm must be below Hot")
        s = r["settings"]
        for group in body:
            val = dict(new[group])
            if group == "research":
                for k in LEGACY_SETTINGS:
                    s[k] = bool(val.pop(k))
            s[group] = val
        if len(json.dumps(s)) > MAX_SETTINGS_BYTES:
            raise Invalid("settings are too big")
        if len(json.dumps(r)) > MAX_RECORDS_BYTES:
            raise Invalid("the records store is full")
        save_json(records_path(), r)
        out = effective_settings(r)
    _SETTINGS_CACHE.clear()
    if "mentions" in body:
        prune_old_quotes()  # "keep quotes for" lowered: older sentences go now (it takes the records lock itself)
    return out


_SETTINGS_CACHE = PerUser(dict)


def app_settings():
    """The settings as saved on disk, cached until records.json changes. For code that has no records at hand."""
    try:
        key = records_path().stat().st_mtime_ns
    except OSError:
        key = None
    hit = _SETTINGS_CACHE.get("v")
    if hit and hit[0] == key:
        return hit[1]
    val = effective_settings(load_records())
    _SETTINGS_CACHE["v"] = (key, val)
    return val


def _settings_of(records):
    return effective_settings(records) if records is not None else app_settings()


def source_on(source, records=None):
    """Research & privacy: is this source on? web, hubspot and gong are on unless you turn one off; meetily and granola are off
    unless you turn one on."""
    v = _settings_of(records)["research"].get(source)
    return v is True if source in ("meetily", "granola") else v is not False


def extra_blocked(records=None):
    """Sites you added to the blocked list (Settings > Research sources & privacy), on top of BLOCKED_DOMAINS."""
    return list(_settings_of(records)["research"]["blocked"])


def ai_share(records=None):
    """What may go to Claude: "titles" (names, titles, companies), "notes" (+ call notes and record notes) or "transcripts" (+ who was mentioned)."""
    return _settings_of(records)["research"]["aiShare"]


def mention_settings(records=None):
    """Settings > Mentions & connections, for the mentions code: autoLookup (bool), autoAdd ("single" | "likely"),
    mapRelations (list of MAP_RELATIONS shown on the People map) and keepDays (quotes older than this may be dropped)."""
    return dict(_settings_of(records)["mentions"])


def alert_on(kind, settings):
    """Should an alert of this watch kind show? Kinds with no switch always show."""
    sig = ALERT_KIND_SIGNAL.get(kind)
    return not sig or settings["alerts"]["signals"].get(sig) is not False


def apply_alert_rules(watch, settings):
    return [w for w in watch if alert_on(w.get("kind"), settings)]


STAGE_ALERT_DAYS = 7


def stages_path():
    return DATA_DIR / "stages.json"


def stage_alerts(companies, seen, now, invites=()):
    """HubSpot stage changes: compare each HubSpot-set company status with the one seen last time. Returns (alerts, seen).
    A change stays an alert for 7 days. The first time a company is seen it is only remembered."""
    seen = {k: dict(v) for k, v in (seen or {}).items() if isinstance(v, dict)}
    calls = {}
    for i in invites:  # a company's upcoming call, not one that just ended (upcoming calls come first)
        calls.setdefault(i.get("company"), i.get("id"))
    out = []
    for name, c in (companies or {}).items():
        if not isinstance(c, dict) or (c.get("src") or {}).get("status") != "HubSpot":
            continue
        status, prev = str(c.get("status") or ""), seen.get(name)
        if not prev:
            seen[name] = {"status": status}
        elif prev.get("status") != status:
            seen[name] = {"status": status, "from": prev.get("status", ""), "changedAt": now.isoformat()}
        at = parse_dt(seen[name].get("changedAt"))
        if at and now - at <= timedelta(days=STAGE_ALERT_DAYS):
            old = seen[name].get("from") or "a different stage"
            out.append({"date": short_day(to_et(at).date()), "kind": "Stage change", "callId": calls.get(name), "title": name + " moved to " + status,
                        "text": "HubSpot moved " + name + " from " + old + " to " + status + ". Check what changed before you talk."})
    return out, seen


# ---------------------------------------------------------------- Claude ----------------------------------------------------------------

def claude_text(system, content, max_tokens, timeout):
    try:
        import anthropic  # only needed when Claude is on
    except ImportError:
        return 503, {"error": "the anthropic package is not installed"}
    client = anthropic.Anthropic(api_key=claude_key() or None, timeout=timeout, max_retries=1)
    try:
        resp = client.beta.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": "low"},
            system=system,
            messages=[{"role": "user", "content": content}],
        )
    except anthropic.AuthenticationError:
        return 401, {"error": "the Claude key was not accepted"}
    except anthropic.RateLimitError:
        return 429, {"error": "Claude is busy, try again soon"}
    except anthropic.APIStatusError as e:
        return 502, {"error": f"Claude error {e.status_code}"}
    except anthropic.APIConnectionError:
        return 502, {"error": "could not reach Claude"}
    except Exception as e:  # any other SDK or argument error still gets a clear answer
        return 502, {"error": f"Claude call failed ({type(e).__name__})"}
    if resp.stop_reason == "refusal":
        return 422, {"error": "Claude declined to answer"}
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    return (200, {"text": text}) if text else (502, {"error": "Claude sent back no text"})


def brief_facts(body, records):
    """The page's facts for a brief summary. Gong's content is dropped unless "Use Gong notes in AI answers" is on."""
    if not isinstance(body, dict):
        return {}
    if not gong_in_ai(records):
        body = {k: v for k, v in body.items() if k != "gong"}
    if ai_share(records) == "titles":  # Settings > Research & privacy: titles only, so no notes reach Claude
        body = dict(body)
        if isinstance(body.get("people"), list):
            body["people"] = [{k: v for k, v in p.items() if k != "note"} if isinstance(p, dict) else p for p in body["people"]]
        if isinstance(body.get("company"), dict):
            body["company"] = {k: v for k, v in body["company"].items() if k not in ("notes", "history")}
    return research_facts(body, records)  # Overture's web research is public information, so it goes whatever the setting


def research_facts(body, records):
    """Add Overture's own web research to the page's brief facts (people[].profile, company.profile) where the page didn't send it:
    a person's profile when their name and company match the call, the company's when its domain's company is the call's."""
    call = body.get("call") if isinstance(body.get("call"), dict) else {}
    co = norm_name(call.get("company") or "")
    people = body.get("people") if isinstance(body.get("people"), list) else []
    if not co:
        return body
    by_name = {}
    for email, r in (records.get("people") or {}).items():
        p = profile_view((r or {}).get("profile") if isinstance(r, dict) else None, "person")
        if p and p["name"] and norm_name(company_for_domain(domain_of(email), records) or "") == co:
            by_name.setdefault(norm_name(p["name"]), p)
    body = dict(body)
    if by_name:
        body["people"] = [dict(p, profile=profile_for_ai(by_name[norm_name(p.get("name") or "")]))
                          if isinstance(p, dict) and "profile" not in p and norm_name(p.get("name") or "") in by_name else p for p in people]
    org = next((o for d, o in (records.get("orgs") or {}).items() if isinstance(o, dict) and norm_name(company_for_domain(d, records) or "") == co
                and profile_view(o.get("profile"), "org")), None)
    if org:
        prof = profile_for_ai(profile_view(org["profile"], "org"))
        if isinstance(body.get("company"), dict):
            if "profile" not in body["company"]:
                body["company"] = dict(body["company"], profile=prof)
        elif body.get("company") is None:
            body["company"] = {"source": "Overture web research", "profile": prof}
    return body


def ai_trim(live, records):
    """What Ask Overture may send to Claude, per Settings > Research & privacy. "titles": no call notes and no notes in the records."""
    if ai_share(records) != "titles":
        return live, records
    strip = lambda d, keys: {k: v for k, v in d.items() if k not in keys} if isinstance(d, dict) else d  # noqa: E731
    if live:
        live = dict(live, invites=[strip(i, ("afterNotes",)) for i in live.get("invites") or []],
                    people={e: strip(p, ("note",)) for e, p in (live.get("people") or {}).items()},
                    companies={n: strip(c, ("notes", "history")) for n, c in (live.get("companies") or {}).items()})
    records = dict(records, companies={n: strip(c, ("notes",)) for n, c in (records.get("companies") or {}).items()},
                   people={e: strip(p, ("note",)) for e, p in (records.get("people") or {}).items()})
    return live, records


def write_brief(facts):
    # Short timeout so the page never sits waiting (it waits 25 s and shows the rules brief meanwhile); research profiles make the
    # facts longer, so 20 s.
    return claude_text(SYSTEM, "Facts for the call:\n" + json.dumps(facts, indent=1), 1500, 20)


SNAP_CACHE = {}


def snapshot():
    if "snap" not in SNAP_CACHE:
        try:
            t = (HERE / "data" / "snapshot.js").read_text(encoding="utf-8")
            SNAP_CACHE["snap"] = json.loads(t[t.index("{"): t.rindex("}") + 1])
        except (OSError, ValueError):
            SNAP_CACHE["snap"] = {}
    return SNAP_CACHE["snap"]


def ask_context(question, call_id, live, records):
    snap = snapshot()
    live = live or {}
    invites = live.get("invites") or []
    call = next((i for i in invites if i["id"] == call_id), None)
    people = live.get("people") or {}

    def who(a):
        p = people.get(a["email"]) or {}
        return {"name": a["name"], "email": a["email"], "title": p.get("title") or None, "note": p.get("note") or None, "previously": p.get("previous") or None,
                "moabResearch": profile_for_ai((p.get("research") or {}).get("profile"))}

    adopters = {norm_name(a.get("org", "")): a.get("use", "") for a in snap.get("adopters", [])}
    cos = {i["company"] for i in invites}
    ctx = {
        "today": live.get("today"),
        "question": question,
        "thisCall": None if not call else {
            "title": call["title"], "when": call["when"], "company": call["company"], "invite": call["notes"][:1500],
            "people": [who(a) for a in call["attendees"]], "callNotes": call.get("afterNotes", "")[:3000],
            "alerts": [w["text"] for w in live.get("watch", []) if w.get("callId") == call["id"]],
            "company": company_facts((live.get("companies") or {}).get(call["company"])),
            "companyResearch": profile_for_ai(((live.get("companies") or {}).get(call["company"]) or {}).get("profile")),
        },
        "upcomingCalls": [{"title": i["title"], "company": i["company"], "when": i["when"], "ended": bool(i.get("ended")), "people": [a["name"] for a in i["attendees"]]} for i in invites[:25]],
        "alerts": [w["title"] + ": " + w["text"] for w in live.get("watch", [])][:20],
        "moabRecords": {
            "companies": dict(list((records.get("companies") or {}).items())[:60]),
            # research profiles are long: this call's people and company carry theirs above
            "people": {e: {k: v for k, v in r.items() if k != "profile"} if isinstance(r, dict) else r
                       for e, r in list((records.get("people") or {}).items())[:120]},
        },
        "publicData": {
            "latestBackstage": snap.get("latestRelease"),
            "onBackstageAdoptersList": {c: adopters[norm_name(c)] for c in cos if norm_name(c) in adopters},
        },
    }
    if gong_in_ai(records) and live.get("gong"):  # off by default: Gong content reaches Claude only when you turn it on
        ctx["gongLastCalls"] = live["gong"]
    if call and setting_on(records, "transcriptsInAI"):  # off by default: nothing from a transcript reaches Claude unless you turn it on
        said = ((records.get("mentions") or {}).get(call["id"]) or {}).get("items") or []
        ctx["thisCall"]["mentionedOnCall"] = [{"name": (it.get("person") or {}).get("name") or it.get("name") or "", "role": it.get("role", ""),
                                               "title": (it.get("person") or {}).get("title", ""), "said": (it.get("quote") or {}).get("text", "")}
                                              for it in said[:20] if it.get("status") in ("found", "known")]
        orgs = ((records.get("mentions") or {}).get(call["id"]) or {}).get("orgs") or []
        ctx["thisCall"]["companiesMentioned"] = [{"name": o.get("name", ""), "relation": org_edge_label(o.get("relation")) if o.get("relation") else "",
                                                  "said": (o.get("quote") or {}).get("text", "")} for o in orgs[:20] if not o.get("removed")]
    text = json.dumps(ctx, ensure_ascii=False, default=str)
    return text[:60000]


def company_facts(c):
    if not isinstance(c, dict):
        return None
    return {"status": c.get("status"), "employees": c.get("employees"), "engineers": c.get("engineers"), "deals": c.get("deals"),
            "notes": c.get("notes"), "history": (c.get("history") or [])[-5:], "sources": c.get("src") or "Overture records"}


PERSON_ASK_SYSTEM = (
    "You answer a salesperson's question about one person before or during a call. Use only the facts in the JSON: Overture's "
    "research on them (from public pages, each fact tagged with its source number like [2]), their company and their calls. "
    "Answer in 1 to 3 short plain sentences, no markdown. After each fact you use, put its source number in square brackets, "
    "like [2]. If the facts don't answer it, say in one sentence that Overture's research doesn't show that. Never guess, and never "
    "add personal details (family, age, health, home, contact details)."
)


def person_context(email, records):
    """One guest for a quick question: their research with numbered sources (1 = the first source, as the page numbers them),
    their company's research and their calls. From Overture's saved records only: no web search, so it answers in seconds."""
    rec = (records.get("people") or {}).get(email) or {}
    prof = profile_view(rec.get("profile"), "person")
    with RQ_LOCK:
        m = dict(RQ["meta"].get(email) or {})
    n = lambda src: "".join("[" + str(i + 1) + "]" for i in src)  # noqa: E731
    ctx = {"person": {"name": m.get("name") or (prof or {}).get("name", ""), "title": rec.get("title", ""), "team": rec.get("team", ""),
                      "relationship": rec.get("relationship", ""), "company": m.get("company") or name_from_domain(domain_of(email))}}
    if prof:
        r = ctx["research"] = {}
        if prof.get("summary"):
            r["summary"] = prof["summary"]["text"] + " " + n(prof["summary"]["src"])
        for k in ("now", "education", "work", "forCall"):
            if prof.get(k):
                r[k] = [e["text"] + " " + n(e["src"]) for e in prof[k]]
        if prof.get("past"):
            r["past"] = [{"role": e["role"], "org": e["org"], "when": e["when"] + " " + n(e["src"]), "points": [x["text"] + " " + n(x["src"]) for x in e["points"]]}
                         for e in prof["past"]]
        if prof.get("people"):
            r["connectedWith"] = [p["name"] + (" (" + ", ".join(x for x in (p["role"], p["org"]) if x) + ")" if p["role"] or p["org"] else "")
                                  + ": " + p["how"] + " " + n(p["src"]) for p in prof["people"]]
        r["sources"] = {str(i + 1): s["label"] for i, s in enumerate(prof["sources"])}
    org = ((records.get("orgs") or {}).get(domain_of(email)) or {}).get("profile")
    if profile_view(org, "org"):
        ctx["company"] = profile_for_ai(profile_view(org, "org"))  # background on the company: not numbered, so not cited
    if m.get("start"):
        ctx["nextCallWithYou"] = m.get("start")
    return json.dumps(ctx, ensure_ascii=False)[:30000], (prof or {}).get("sources") or []


def answer_question(body):
    if not isinstance(body, dict):
        return 400, {"error": "bad request"}
    q, cid = body.get("question"), body.get("callId")
    if not isinstance(q, str) or not q.strip() or len(q) > 500:
        return 400, {"error": "ask a question of up to 500 characters"}
    if cid is not None and (not isinstance(cid, str) or not CALLID_RE.match(cid)):
        return 400, {"error": "bad callId"}
    person = body.get("person")
    if person is not None and (not isinstance(person, str) or not EMAIL_RE.match(person.strip().lower())):
        return 400, {"error": "bad person"}
    if not claude_on():
        return 503, {"error": "no-key"}
    if person:  # a question about one guest: their saved research only, short answer, cited
        ctx, sources = person_context(person.strip().lower(), load_records())
        code, out = claude_text(PERSON_ASK_SYSTEM, "Facts (JSON):\n" + ctx + "\n\nQuestion: " + q.strip(), 400, 20)
        if code == 200:
            out.update(source="claude", sources=[{"url": s["url"], "label": s["label"]} for s in sources])
        return code, out
    live, records = None, load_records()
    if token_info():
        try:
            live, _ = live_now(records)
        except (GoogleError, NotConnected):
            live = None
    live, records = ai_trim(live, records)
    code, out = claude_text(ASK_SYSTEM, "Facts (JSON):\n" + ask_context(q.strip(), cid, live, records) + "\n\nQuestion: " + q.strip(), 700, 20)
    if code == 200:
        out["source"] = "claude"
    return code, out


# ---------------------------------------------------------------- invitee research ----------------------------------------------------------------
# When someone new is invited, a background worker researches them in depth (deep research: Claude searches the web and opens
# and reads pages with web fetch): their current job and how they relate to the company, plus a profile (contract A: summary,
# current role, past jobs, education, notable work, what to bring up), and the same for their company (contract B).
# The owner's privacy rules are enforced here in code, not only in the prompt:
# - Claude gets the guest's display name, the company name and the company's domain: never an email address or local part.
# - People-search and data-broker sites are blocked in the web search AND web fetch tools and any source on them is dropped.
# - Work information only; a field or bullet is kept only when a kept source (a page the search or fetch really returned)
#   backs it; anything else is "unknown", never a guess. Bullets with contact details or personal-life details are dropped.
# - Guests on personal mail (gmail.com and so on) are never looked up on the web.

RESEARCH_DAYS = 30
RESEARCH_TIMEOUT = 60
WEB_SEARCH_TOOL = "web_search_20260209"
WEB_FETCH_TOOL = "web_fetch_20260209"   # anthropic 1.15 BetaWebFetchTool20260209Param: name "web_fetch", max_uses, blocked_domains, ...
DEEP_SEARCHES = 5          # deep research (a guest on your calls, or their company): web searches at most
DEEP_FETCHES = 4           # and pages opened and read at most (kept low: the owner's own Claude key pays for every page)
DEEP_DAYS_AHEAD = 7        # deep research waits until the call is this close (Look up again works any time)
DEEP_BUDGET = 240          # seconds for one deep lookup, resends included
DEEP_RESUMES = 8           # a search with many tool calls pauses (pause_turn) and is resent this many times at most
DEEP_MAX_TOKENS = 10000
FETCH_PAGE_TOKENS = 5000   # of one opened page's text, at most
PROFILE_V = 2              # the research profile's version: a record looked up before deep research is looked up once more
DEEP_V = 3                 # what a person's deep run asks for; 3 added "people" (who they're publicly connected with at work)
PROFILE_CHARS = 260        # one bullet, at most
PROFILE_SOURCES = 20
RELATIONSHIPS = {"employee": "Employee", "contractor": "Contractor or agency", "partner": "Partner",
                 "investor": "Investor or board", "customer": "Customer", "other": "Other", "unknown": "Unknown"}
SENIORITY = {"executive", "director", "manager", "senior", "individual contributor"}
RESEARCH_FIELDS = ("title", "team", "seniority", "tenure", "relationship")
NO_KEY_NOTE = "Add a Claude key to look up titles automatically"
BLOCKED_DOMAINS = [
    # people-search and contact-data sites
    "zoominfo.com", "rocketreach.co", "rocketreach.com", "contactout.com", "apollo.io", "lusha.com", "signalhire.com",
    "seamless.ai", "uplead.com", "hunter.io", "clearbit.com", "leadiq.com", "kaspr.io", "snov.io", "adapt.io", "datanyze.com",
    "lead411.com", "cognism.com", "salesintel.io", "spokeo.com", "whitepages.com", "beenverified.com", "truepeoplesearch.com",
    "fastpeoplesearch.com", "peoplefinders.com", "radaris.com", "intelius.com", "pipl.com", "peekyou.com", "mylife.com",
    "thatsthem.com", "instantcheckmate.com", "truthfinder.com", "usphonebook.com", "nuwber.com", "clustrmaps.com",
    "idcrawl.com", "peoplelooker.com", "familytreenow.com", "anywho.com", "zabasearch.com", "spytox.com", "voterrecords.com",
    "peoplesearchnow.com", "cyberbackgroundchecks.com", "fastbackgroundcheck.com", "searchpeoplefree.com", "ussearch.com",
    "peoplesmart.com", "411.com", "addresses.com", "socialcatfish.com", "peopledatalabs.com", "fullcontact.com", "wiza.co",
    "salesql.com", "aeroleads.com", "getprospect.com", "skrapp.io", "voilanorbert.com", "findthatlead.com", "anymailfinder.com",
    "swordfish.ai", "nymeria.io",
    # personal social media (a professional profile is fine; these are not)
    "facebook.com", "instagram.com", "tiktok.com", "snapchat.com", "pinterest.com", "x.com", "twitter.com", "threads.net",
    "bsky.app", "reddit.com", "vk.com",
]
# Never sent anywhere, never shown: what the research layer adds to a person's record.
AUTO_KEYS = {"team", "seniority", "relationship", "tenure", "sources", "found", "foundAt", "confidence", "autoFields", "lookup",
             "profile", "deepAt", "searched", "deepV"}

_ITEMS_RULES = (
    "Number the pages in sources from 1 (1 is the first). Every item lists the numbers of the pages that say it; leave out "
    "anything no page says. List in sources only pages you really got from a search or opened, at most 15. "
    "Write each item as one plain sentence of at most 40 words, in your own words. "
)
RESEARCH_SYSTEM = (
    "You research one person in depth for a salesperson's call prep: who they are at work, what they do now, and the work "
    "they did before. Work information only. The salesperson sells Spotify's Backstage products (Portal, Confidence and Xirp). "
    "Do real research, not one search: search the person's name with the company; once you know their past employers, search "
    "their name with those; and search their name with words like talk, podcast, interview, article, blog or GitHub. "
    "Open (fetch) the most useful pages and read them: the company's team, about or leadership pages, the person's own public "
    "professional profile, their talks, articles and interviews, and press about their work. "
    "Use only public professional sources. Never use people-search or contact-data sites. Never search for or report personal "
    "details: no email address, phone number, home address, family or relationships, age or birthday, photos, health, religion "
    "or politics, and no social media beyond a professional profile. Never guess or look up an email address. "
    "Make sure each page is about this same person: the name matches and the page ties them to this company now, or is clearly "
    "the same person's career. If several people share the name and you can't tell which one this is, report found false. "
    "If you can't find this exact person at this company in a public source, report found false. Do not guess.\n"
    "Answer with one JSON object and nothing else, in exactly this shape:\n"
    '{"found": true or false, "confidence": "high, medium or low", '
    '"title": "current job title, or empty", "team": "team or department, or empty", '
    '"seniority": "one of executive, director, manager, senior, individual contributor, or empty", '
    '"tenure": "roughly how long they have been at the company if public, like about 3 years, or empty", '
    '"relationship": "one of employee, contractor, partner, investor, other, unknown", '
    '"sources": [{"url": "https://...", "label": "short name of the page", '
    '"supports": ["the fields above this page backs: title, team, seniority, tenure, relationship (may be empty)"]}], '
    '"summary": {"text": "1 or 2 sentences: who they are at work", "sources": [1]}, '
    '"now": [{"text": "one fact about their current role: what they own, their team, its size or scope, their focus", "sources": [1]}], '
    '"past": [{"role": "job title", "org": "company", "when": "like 2019 - 2022, or empty", "sources": [2], '
    '"points": [{"text": "what they did or achieved there", "sources": [2]}]}], '
    '"education": [{"text": "degree and school, as listed on a professional profile", "sources": [2]}], '
    '"work": [{"text": "a talk, article, podcast, project, open-source work or press about their work", "sources": [3]}], '
    '"forCall": [{"text": "something worth bringing up with them on this call, built only on the facts above", "sources": [1]}], '
    '"people": [{"name": "full name", "role": "their job, or empty", "org": "where, or empty", '
    '"how": "how they are connected through work, like co-founded Forest City SynBio together, or co-hosted the TKS showcase", '
    '"when": "like 2019, or empty", "sources": [2]}]}\n'
    + _ITEMS_RULES +
    "people: people a public page names together with this person in a work setting: co-founders, managers, teammates on the "
    "same team page, co-hosts, co-speakers, panelists, interviewers, co-authors, investors in their company. Only work ties a "
    "source states; never family, partners or friends, and never anyone's contact details. "
    "Give up to 6 now items, up to 8 past jobs (newest first) with up to 4 points each, up to 3 education items, up to 6 work "
    "items, up to 4 forCall items and up to 10 people. "
    "relationship means their relationship to the company: employee, contractor (or agency), partner, investor (or board member), "
    "other, or unknown. Every field above sources that you fill must be backed by a source that lists it in supports."
)
ORG_RESEARCH_SYSTEM = (
    "You research one company in depth for a salesperson's call prep. He sells Spotify's Backstage products (Portal, Confidence "
    "and Xirp). Business information only. "
    "Do real research, not one search: open (fetch) the company's own website (home, about, team or leadership, products or "
    "programs, careers, engineering blog), search for the company by name and website, and search for recent news about it. "
    "Read the pages you open. Make sure every page is about the company at this website, not another one with a similar name. "
    "Use only public sources: the company's own site, news, press releases, its public profiles and its engineering or open-source "
    "work. Never use people-search or contact-data sites, and never report anyone's personal details (email address, phone number, "
    "home address, family). "
    "If you can't find this company in a public source, report found false. Do not guess.\n"
    "Answer with one JSON object and nothing else, in exactly this shape:\n"
    '{"found": true or false, "confidence": "high, medium or low", "name": "the company\'s real full name, as it calls itself", '
    '"sources": [{"url": "https://...", "label": "short name of the page"}], '
    '"summary": {"text": "1 or 2 sentences: what the company is and does", "sources": [1]}, '
    '"facts": [{"label": "Founded, Headquarters, Size, Type, Leaders or Programs/Products", "value": "a few words", "sources": [1]}], '
    '"what": [{"text": "one fact about what they do: products or programs, customers or who they serve, how they work", "sources": [1]}], '
    '"news": [{"text": "a recent change or piece of news", "when": "like March 2026, or empty", "sources": [2]}], '
    '"tech": [{"text": "a fact about their engineering or developer tooling: team, stack, developer portal, open source, feature '
    'flags or experiments, anything relevant to Backstage", "sources": [3]}], '
    '"forCall": [{"text": "something worth bringing up on this call, built only on the facts above", "sources": [1]}]}\n'
    + _ITEMS_RULES +
    "Give up to 8 facts, up to 6 what items, up to 5 news items (newest first, from the last two years), up to 6 tech items "
    "(none if no page says), and up to 4 forCall items."
)

# One queue for every lookup. Jobs: a guest's email (invitee research), "co:<domain>" (company research, like invitee research
# it never takes the last free worker), "mention:<call>:<id>" (someone said on a call) and
# "org:<call>:<id>" (how a company said on a call relates to the call's company). running: the keys being looked up right now.
RQ = PerUser(lambda: {"queue": [], "pending": set(), "running": set(), "errors": {}, "meta": {}, "mentions": {}})  # mentions: key -> job
RQ_LOCK = threading.Condition()
RESEARCH_AUTOSTART = True   # tests turn this off and call research_step() themselves
MAX_WORKERS = 3             # lookups at once; things said on a call go before invitee research
_WORKER = {"threads": []}


class ResearchError(Exception):
    pass


def research_client():
    """The Claude client for research. Tests swap this for a fake."""
    import anthropic
    return anthropic.Anthropic(api_key=claude_key() or None, timeout=RESEARCH_TIMEOUT, max_retries=1)


def norm_org(s):
    s = re.sub(r"[^a-z0-9]+", " ", str(s or "").lower().replace("&", " and "))
    return " ".join(w for w in s.split() if w not in {"inc", "ltd", "llc", "gmbh", "plc", "corp", "corporation", "limited", "se", "ag", "nv", "bv", "sa", "ab", "co", "group"})


def adopter_for(company):
    """The public Backstage adopters list entry for a company, or None."""
    n = norm_org(company)
    if not n:
        return None
    return next((a for a in snapshot().get("adopters", []) if norm_org(a.get("org", "")) == n), None)


def user_known(r):
    """True when the user (not research) has put something in this person's record."""
    r = r if isinstance(r, dict) else {}
    keys = set(r) - AUTO_KEYS
    if "title" in (r.get("autoFields") or []):
        keys.discard("title")
    return bool(keys) or r.get("found") == "confirmed"


def user_has_title(r):
    return bool(r.get("title")) and "title" not in (r.get("autoFields") or [])


def skip_reason(email, m, rec, forced=False):
    """Why this guest is not looked up on the web ("" when they can be)."""
    d = domain_of(email)
    if not d or personal_domain(d):
        return "Personal email address, so Overture doesn't look them up on the web."
    if m.get("internal"):
        return "Works at your own company."
    if fake_domain(d):
        return "Can't find this person: " + d + " isn't a real company (it's an example address), so there is no one to look up."
    if not m.get("named") or not personish({"name": m.get("name", ""), "email": email}):
        return "No name on the invite, and their email address doesn't show one, so Overture can't look them up."
    if m.get("crm") or (not forced and (rec.get("found") == "confirmed" or user_has_title(rec))):
        return " "  # HubSpot has their title, or the user filled this in or confirmed it: nothing to say
    # Look up again (forced) still runs for someone you confirmed: it refreshes the research profile and who they're connected
    # with, and merge_research never overwrites a field you confirmed or typed.
    if not source_on("web"):  # also when it was queued before web research was turned off: the worker asks again
        return WEB_OFF_NOTE
    if not claude_on():
        return NO_KEY_NOTE
    return ""


def needs_research(rec, now):
    """Looked up before deep research existed (no profile of this version): once more, even with a title Overture found. Otherwise:
    no title yet, and not looked up in the last 30 days. Never when you confirmed them or typed their title."""
    if rec.get("found") == "confirmed" or user_has_title(rec):
        return False
    prof = rec.get("profile")
    old_profile = isinstance(prof, dict) and not (isinstance(prof.get("v"), int) and prof["v"] >= PROFILE_V)
    older_run = rec.get("deepAt") and not (isinstance(rec.get("deepV"), int) and rec["deepV"] >= DEEP_V)  # before "people" was asked for
    if rec.get("lookup") in ("done", "unknown") and (not rec.get("deepAt") or old_profile or older_run):
        return True
    if rec.get("title"):
        return False
    at = parse_dt(rec.get("foundAt"))
    return not at or now - at > timedelta(days=RESEARCH_DAYS)


def queue_research(meta, records, now=None):
    """Queue every outside guest who hasn't been looked up. Returns True when something new was queued."""
    now = now or datetime.now(timezone.utc)
    people = records.get("people") or {}
    added = False
    with RQ_LOCK:
        RQ["meta"] = dict(meta)  # the guests on your upcoming calls right now
        for email, m in meta.items():
            rec = people.get(email) or {}
            if email in RQ["pending"] or email in RQ["running"] or email in RQ["errors"]:
                continue
            if skip_reason(email, m, rec) or not call_soon(m, now) or not needs_research(rec, now):
                continue
            RQ["queue"].append((email, False))
            RQ["pending"].add(email)
            added = True
        if added:
            RQ_LOCK.notify_all()
    if added and RESEARCH_AUTOSTART:
        ensure_worker()
    return added


def request_research(email):
    """POST /api/research: look this guest up again now, even within 30 days. Returns (status code, body)."""
    email = str(email or "").strip().lower()
    if not EMAIL_RE.match(email):
        return 400, {"error": "email doesn't look right"}
    with RQ_LOCK:
        m = RQ["meta"].get(email)
    if not m:
        return 404, {"error": "That person isn't on one of your upcoming calls."}
    rec = (load_records().get("people") or {}).get(email) or {}
    reason = skip_reason(email, m, rec, forced=True)
    if reason == NO_KEY_NOTE:
        return 503, {"error": "no-key"}
    if reason:
        return 400, {"error": reason.strip() or "You confirmed their details, so Overture doesn't look them up again."}
    with RQ_LOCK:
        RQ["errors"].pop(email, None)
        if email not in RQ["pending"] and email not in RQ["running"]:
            RQ["queue"].append((email, True))
            RQ["pending"].add(email)
            RQ_LOCK.notify_all()
    if RESEARCH_AUTOSTART:
        ensure_worker()
    return 202, {"ok": True, "status": "pending"}


# ---- company research: the outside companies on your upcoming calls, by their email domain (job key "co:<domain>") ----
# Only the company's name and domain are sent. Personal mail, example domains and your own company are never looked up.

ORG_NO_KEY_NOTE = "Add a Claude key to look up companies automatically"


def org_meta(meta):
    """domain -> {name, domain, callId} for each outside company among the guests on your upcoming calls (meta from build_live)."""
    out = {}
    for m in (meta or {}).values():
        d = str(m.get("domain") or "").lower()
        if not d or d in out or m.get("internal") or personal_domain(d) or not DOMAIN_RE.match(d):
            continue
        out[d] = {"name": str(m.get("company") or "") or name_from_domain(d), "domain": d, "callId": str(m.get("callId") or ""),
                  "start": str(m.get("start") or "")}
    return out


def call_soon(m, now):
    """Deep research costs Claude tokens, so it runs only for calls in the next DEEP_DAYS_AHEAD days (or with no known start)."""
    at = parse_dt((m or {}).get("start"))
    return not at or at - now <= timedelta(days=DEEP_DAYS_AHEAD)


def org_skip_reason(domain):
    """Why this company is not looked up on the web ("" when it can be)."""
    if fake_domain(domain):
        return "Can't find this company: " + domain + " isn't a real company (it's an example address), so there is nothing to look up."
    if not source_on("web"):  # also when it was queued before web research was turned off
        return WEB_OFF_NOTE
    if not claude_on():
        return ORG_NO_KEY_NOTE
    return ""


def org_needs_research(rec, now):
    """Not looked up in the last 30 days (or looked up before deep research)."""
    at = parse_dt((rec or {}).get("foundAt"))
    prof = (rec or {}).get("profile")
    old_profile = isinstance(prof, dict) and not (isinstance(prof.get("v"), int) and prof["v"] >= PROFILE_V)
    return not at or old_profile or now - at > timedelta(days=RESEARCH_DAYS)


def queue_org_research(meta, records, now=None):
    """Queue each outside company on your upcoming calls that hasn't been looked up in 30 days. True when something new was queued."""
    now = now or datetime.now(timezone.utc)
    orgs = records.get("orgs") or {}
    added = False
    with RQ_LOCK:
        RQ["meta"] = dict(meta)  # the guests on your upcoming calls right now (queue_research keeps the same)
        for d, om in org_meta(meta).items():
            key = "co:" + d
            if key in RQ["pending"] or key in RQ["running"] or key in RQ["errors"]:
                continue
            if org_skip_reason(d) or not call_soon(om, now) or not org_needs_research(orgs.get(d), now):
                continue
            RQ["queue"].append((key, False))
            RQ["pending"].add(key)
            added = True
        if added:
            RQ_LOCK.notify_all()
    if added and RESEARCH_AUTOSTART:
        ensure_worker()
    return added


def request_org_research(domain):
    """POST /api/research/org: look this company up again now, even within 30 days. Returns (status code, body)."""
    domain = str(domain or "").strip().lower()
    if not DOMAIN_RE.match(domain):
        return 400, {"error": "domain doesn't look right"}
    with RQ_LOCK:
        known = domain in org_meta(RQ["meta"])
    if not known:
        return 404, {"error": "That company isn't on one of your upcoming calls."}
    reason = org_skip_reason(domain)
    if reason == ORG_NO_KEY_NOTE:
        return 503, {"error": "no-key"}
    if reason:
        return 400, {"error": reason}
    key = "co:" + domain
    with RQ_LOCK:
        RQ["errors"].pop(key, None)
        if key not in RQ["pending"] and key not in RQ["running"]:
            RQ["queue"].append((key, True))
            RQ["pending"].add(key)
            RQ_LOCK.notify_all()
    if RESEARCH_AUTOSTART:
        ensure_worker()
    return 202, {"ok": True, "status": "pending"}


def do_org_research(domain, forced=False, now=None):
    now = now or datetime.now(timezone.utc)
    with RQ_LOCK:
        om = org_meta(RQ["meta"]).get(domain)
    rec = (load_records().get("orgs") or {}).get(domain) or {}
    if not om or org_skip_reason(domain) or (not forced and not org_needs_research(rec, now)):
        return None
    return merge_org(domain, om["name"], research_org(om["name"], domain), now)


def org_research_request(name, domain):
    """The exact request for one company: its name and its website. Nothing else."""
    name, domain = clean_text(name, 120), str(domain or "").lower()
    if "@" in name or not DOMAIN_RE.match(domain) or personal_domain(domain) or fake_domain(domain):
        raise ResearchError("not enough to look it up")
    user = ("Company: " + (name or domain) + "\nCompany website: https://" + domain
            + "\n\nResearch this company in depth: what it is and does, its key facts, recent news, and its engineering and developer "
              "tooling. Answer with the JSON object only.")
    return deep_request(ORG_RESEARCH_SYSTEM, user)


def research_org(name, domain):
    """Ask Claude (searching and reading the web) about one company. Returns {"profile": contract B or None, "searched": sites}."""
    stop, text, seen = run_search(org_research_request(name, domain), DEEP_BUDGET, DEEP_RESUMES)
    if stop == "refusal":
        return {"profile": None, "searched": 0}
    obj = extract_json(text)
    return {"profile": clean_profile(obj, seen, "org", name=name, domain=domain), "searched": sites_searched(seen)}


def merge_org(domain, name, result, now=None):
    """Save a company's research under records.orgs[domain]."""
    now = now or datetime.now(timezone.utc)
    with RECORDS_LOCK:
        r = load_records()
        o = r["orgs"].setdefault(domain, {})
        o.update(name=name, foundAt=now.replace(microsecond=0).isoformat(), lookup="done" if result.get("profile") else "unknown",
                 searched=int(result.get("searched") or 0))
        if result.get("profile"):
            o["profile"] = result["profile"]
        elif not profile_view(o.get("profile"), "org"):
            o.pop("profile", None)  # an older kind of profile: gone, so it isn't looked up again and again
        if len(json.dumps(r)) > MAX_RECORDS_BYTES:
            raise ResearchError("the records store is full")
        save_json(records_path(), r)
        return dict(o)


def org_research_status(domain, rec, om=None, now=None):
    key = "co:" + domain
    with RQ_LOCK:
        if key in RQ["pending"] or key in RQ["running"]:
            return "pending", "Looking up…"
        err = RQ["errors"].get(key)
    if err:
        return "error", "Couldn't look it up: " + err + "."
    if rec.get("lookup") == "done":
        return "done", ""
    if rec.get("lookup") == "unknown":
        return "unknown", searched_note(rec, "information about this company")
    why = org_skip_reason(domain)
    if not why and om and not call_soon(om, now or datetime.now(timezone.utc)):
        return "later", ORG_LATER_NOTE
    return "skipped", why


def org_research_view(domain, om, rec):
    """What the page shows about one company's research (all text is escaped by the page)."""
    rec = rec if isinstance(rec, dict) else {}
    status, note = org_research_status(domain, rec, om)
    return {"status": status, "note": note, "domain": domain, "company": str((om or {}).get("name") or ""),
            "foundAt": str(rec.get("foundAt") or ""), "profile": profile_view(rec.get("profile"), "org")}


def ensure_worker():
    """Start the worker pool: MAX_WORKERS threads, each taking one lookup at a time."""
    with RQ_LOCK:
        alive = [t for t in _WORKER["threads"] if t.is_alive()]
        while len(alive) < MAX_WORKERS:
            t = threading.Thread(target=_worker_loop, name="moab-research-" + str(len(alive) + 1), daemon=True)
            alive.append(t)
            t.start()  # under the lock, so a second caller can't see them not yet alive and start more
        _WORKER["threads"] = alive


def _ready_user():
    """Under RQ_LOCK: an account with a lookup a worker may take now, or None (on your own PC there is only you)."""
    users = [u for u in RQ.users() if u] if HOSTED else [""]
    _WORKER["turn"] = _WORKER.get("turn", 0) + 1  # start with a different account each time, so one account can't hold every worker
    for i in range(len(users)):
        uid = users[(_WORKER["turn"] + i) % len(users)]
        with as_user(uid):
            if _job_ready():
                return uid
    return None


def _worker_loop():
    while True:  # for the life of the server
        with RQ_LOCK:
            uid = _ready_user() if RESEARCH_AUTOSTART else None  # tests turn autostart off and step the queue themselves
            while uid is None:
                RQ_LOCK.wait(1.0)
                uid = _ready_user() if RESEARCH_AUTOSTART else None
        with as_user(uid):  # the lookup reads and saves only that account's records
            research_step()


def _said_job(key):
    return key.startswith(("mention:", "org:"))


def _job_ready():
    """Under RQ_LOCK: True when a worker may take a job now. Invitee research never takes the last free worker, so a name or
    company said on a call always starts at once."""
    if any(_said_job(k) for k, _ in RQ["queue"]):
        return True
    return bool(RQ["queue"]) and sum(1 for k in RQ["running"] if not _said_job(k)) < MAX_WORKERS - 1


def _next_job():
    """Under RQ_LOCK: the next queue entry, or None. Things said on a call (people, companies) go before invitee research."""
    for i, (key, _) in enumerate(RQ["queue"]):
        if _said_job(key):
            return RQ["queue"].pop(i)
    return RQ["queue"].pop(0) if _job_ready() else None


def research_step(now=None):
    """Look up the next queued job. Returns its key (an email, or mention:/org:...), or None when there is nothing to take."""
    with RQ_LOCK:
        nxt = _next_job() if RQ["queue"] else None
        if nxt is None:
            return None
        email, forced = nxt
        RQ["running"].add(email)
        m = dict(RQ["meta"].get(email) or {})
        job = dict(RQ["mentions"].get(email) or {}) if email.startswith(("mention:", "org:")) else None
    try:
        if job is not None:  # said on a call (see "people mentioned on the call")
            if job and email.startswith("org:"):
                do_org_lookup(job, now)
            elif job:
                do_mention_lookup(job, now)
        elif email.startswith("co:"):  # a company on your upcoming calls (see "company research")
            do_org_research(email[3:], forced, now)
        else:
            do_research(email, m, forced, now)
    except ResearchError as e:
        with RQ_LOCK:
            RQ["errors"][email] = str(e)
    except Exception as e:  # never let one guest stop the worker
        with RQ_LOCK:
            RQ["errors"][email] = "research failed (" + type(e).__name__ + ")"
    finally:
        with RQ_LOCK:
            RQ["running"].discard(email)
            RQ["pending"].discard(email)
            RQ_LOCK.notify_all()  # a held-back invitee lookup may start now
    return email


def do_research(email, m, forced=False, now=None):
    now = now or datetime.now(timezone.utc)
    rec = (load_records().get("people") or {}).get(email) or {}
    if skip_reason(email, m, rec, forced) or (not forced and not needs_research(rec, now)):
        return None
    result = research_person(m["name"], m["company"] or name_from_domain(m["domain"]), m["domain"], email)
    return merge_research(email, result, now)


def _get(obj, key, default=None):
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


CONTROL_RE = re.compile(r"[\x00-\x1f\x7f  ]")
PHONE_RE = re.compile(r"\+?\d[\d\s().-]{7,}\d")


def clean_text(v, limit):
    if not isinstance(v, str):
        return ""
    v = " ".join(CONTROL_RE.sub(" ", v).split())
    return v if len(v) <= limit else ""


def clip(v, limit):
    """Like clean_text, but text over the limit is cut short (with …) instead of dropped. For CRM and Gong text."""
    t = clean_text(v, 10**6)
    return t if len(t) <= limit else t[:limit - 1].rstrip() + "…"


def safe_url(u):
    """An http(s) URL with a real host and no user:password part, or ""."""
    if not isinstance(u, str) or len(u) > 500 or re.search(r"\s", u):
        return ""
    try:
        p = urllib.parse.urlsplit(u)
    except ValueError:
        return ""
    host = (p.hostname or "").lower()
    if p.scheme not in ("http", "https") or not host or "@" in p.netloc or not DOMAIN_RE.match(host):
        return ""
    return urllib.parse.urlunsplit((p.scheme, p.netloc.lower(), p.path, p.query, ""))


def blocked_url(u):
    host = (urllib.parse.urlsplit(u).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in BLOCKED_DOMAINS + extra_blocked())  # + the sites you blocked in Settings


def url_key(u):
    p = urllib.parse.urlsplit(u)
    return (p.hostname or "").lower().removeprefix("www.") + p.path.rstrip("/")


def leaks_email(text, email, name):
    """True if the text holds the email address, or its local part as a word that isn't one of the name's own words."""
    low, email = text.lower(), email.lower()
    local = email.split("@")[0]
    if email in low:
        return True
    tokens = set(re.findall(r"[a-z0-9._%+'-]+", low)) | set(re.findall(r"[a-z0-9]+", low))
    return local in tokens and local not in set(re.findall(r"[a-z0-9]+", name.lower()))


def search_request(system, user, max_uses=5):
    """One Claude request with web search: data-broker and personal social sites are blocked in the tool itself."""
    return {
        "model": MODEL, "max_tokens": 8000, "betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default",
        "output_config": {"effort": "low"}, "system": system,
        "tools": [{"type": WEB_SEARCH_TOOL, "name": "web_search", "max_uses": max_uses, "blocked_domains": list(BLOCKED_DOMAINS) + extra_blocked()}],
        "messages": [{"role": "user", "content": user}],
    }


def deep_request(system, user):
    """One Claude request for deep research: web search and web fetch (open and read a page), with data-broker and personal social
    sites blocked in BOTH tools, medium effort, and room for a long answer. Only `user` (a name, a company and its website) goes."""
    blocked = list(dict.fromkeys(list(BLOCKED_DOMAINS) + extra_blocked()))
    return {
        "model": MODEL, "max_tokens": DEEP_MAX_TOKENS, "betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default",
        "output_config": {"effort": "medium"}, "system": system,
        "tools": [{"type": WEB_SEARCH_TOOL, "name": "web_search", "max_uses": DEEP_SEARCHES, "blocked_domains": blocked},
                  {"type": WEB_FETCH_TOOL, "name": "web_fetch", "max_uses": DEEP_FETCHES, "blocked_domains": list(blocked),
                   "max_content_tokens": FETCH_PAGE_TOKENS}],
        # Automatic prompt caching: each search and page read is cached as it arrives, so the steps after it read it back at a
        # tenth of the price instead of paying full price again (most of a deep lookup's input tokens are these re-reads).
        "cache_control": {"type": "ephemeral"},
        "messages": [{"role": "user", "content": user}],
    }


def research_request(name, company, domain, email):
    """The exact request sent to Claude. Only the display name, company name and company domain go in it."""
    name, company, domain = clean_text(name, 100), clean_text(company, 120), str(domain or "").lower()
    if not name or "@" in name or "@" in company or not DOMAIN_RE.match(domain) or personal_domain(domain):
        raise ResearchError("not enough to look them up")
    user = ("Person: " + name + "\nCompany: " + (company or domain) + "\nCompany website: https://" + domain
            + "\n\nResearch this person's work in depth: their current role (title, team, seniority, roughly how long they have been "
              "at the company, and their relationship to it), their past jobs, education as listed on professional profiles, and "
              "their notable work. Answer with the JSON object only.")
    req = deep_request(RESEARCH_SYSTEM, user)
    if leaks_email(user, email, name):  # belt and braces: refuse rather than send an address
        raise ResearchError("their name looks like their email address, so Overture didn't send it")
    return req


def api_error_text(e):
    n = type(e).__name__
    if n == "AuthenticationError":
        return "the Claude key was not accepted"
    if n == "RateLimitError":
        return "Claude is busy, try again soon"
    if n in ("APIConnectionError", "APITimeoutError"):
        return "could not reach Claude"
    if getattr(e, "status_code", None):
        return "Claude error " + str(e.status_code)
    return "Claude call failed (" + n + ")"


def unknown_result():
    return {"status": "unknown", "title": "", "team": "", "seniority": "", "tenure": "", "relationship": "unknown",
            "confidence": "", "sources": []}


def extract_json(text):
    t = str(text or "").strip()
    a, b = t.find("{"), t.rfind("}")
    if a < 0 or b <= a:
        return None
    try:
        obj = json.loads(t[a:b + 1])
    except (ValueError, RecursionError):
        return None
    return obj if isinstance(obj, dict) else None


def clean_research(obj, seen=None):
    """Claude's JSON -> what Overture keeps. Unsourced, unparseable or low-confidence answers become "unknown"."""
    out = unknown_result()
    if not isinstance(obj, dict) or obj.get("found") is not True or obj.get("confidence") not in ("high", "medium"):
        return out
    sources = []
    for s in obj.get("sources") if isinstance(obj.get("sources"), list) else []:
        if not isinstance(s, dict):
            continue
        url = safe_url(s.get("url"))
        if not url or blocked_url(url) or (seen is not None and url_key(url) not in seen):
            continue  # off-list, on a blocked site, or never seen in the search results
        sup = s.get("supports")
        sup = [f for f in sup if f in RESEARCH_FIELDS] if isinstance(sup, list) else []
        if sup:
            label = clean_text(s.get("label"), 120)
            sources.append({"url": url, "label": label if label and "@" not in label else urllib.parse.urlsplit(url).hostname, "supports": sup})
        if len(sources) == 3:
            break
    backed = {f for s in sources for f in s["supports"]}
    vals = {}
    for f, limit in (("title", 120), ("team", 120), ("tenure", 60)):
        v = clean_text(obj.get(f), limit)
        if v and f in backed and "@" not in v and not PHONE_RE.search(v):
            vals[f] = v
    sen = clean_text(obj.get("seniority"), 40).lower()
    if sen in SENIORITY and "seniority" in backed:
        vals["seniority"] = sen
    rel = obj.get("relationship")
    if rel in RELATIONSHIPS and rel != "unknown" and "relationship" in backed:
        vals["relationship"] = rel
    if not vals.get("title") and not vals.get("relationship"):
        return out
    used = [{"url": s["url"], "label": s["label"]} for s in sources if set(s["supports"]) & set(vals)]
    out.update(vals, status="done", confidence=obj["confidence"], sources=used)
    return out


def research_person(name, company, domain, email):
    """Ask Claude (searching and reading the web) who this person is at work. Returns a clean result: the quick fields (title,
    team, ...), "profile" (contract A, or None) and "searched" (how many sites the research saw). Raises ResearchError if Claude
    can't be reached or the answer was cut off."""
    stop, text, seen = run_search(research_request(name, company, domain, email), DEEP_BUDGET, DEEP_RESUMES)
    if stop == "refusal":
        return dict(unknown_result(), profile=None, searched=0)
    obj = extract_json(text)
    out = clean_research(obj, seen)
    profile = clean_profile(obj, seen, "person", name=clean_text(name, 100))
    if profile and out["status"] != "done":  # found and sourced, only without a title: still found
        out.update(status="done", confidence=profile["confidence"])
    return dict(out, profile=profile, searched=sites_searched(seen))


def run_search(req, budget=None, resumes=3):
    """Send one search_request (or deep_request). Returns (stop reason, answer text, seen): seen holds the pages the search really
    returned or web fetch really opened, as url_key -> {"cited": the words the search's citations quote from that page
    (cited_text), "age": its date (page_age) as YYYY-MM-DD or ""}. budget (seconds), when given, caps the whole lookup: each
    request times out within it (the SDK's per-request timeout, no slow retries) and a paused search isn't resumed after it.
    resumes: how many times a paused search (pause_turn) is resent at most. Raises ResearchError if Claude can't be reached or
    the answer was cut off."""
    responses = []  # every reply, also of a lookup that fails partway: its tokens are paid for and logged all the same
    try:
        return _run_search(req, budget, resumes, responses)
    finally:
        if responses:
            log_usage(responses)


def _run_search(req, budget, resumes, responses):
    req = dict(req)
    messages = req.pop("messages")
    start = _time.monotonic()
    try:
        base = research_client()

        def within(seconds):  # a client whose requests time out within what is left of the budget
            return base.with_options(timeout=float(seconds), max_retries=0) if budget and hasattr(base, "with_options") else base
        resp = within(budget).beta.messages.create(messages=messages, **req)
        responses.append(resp)
        for _ in range(resumes):  # a long server-side search can pause; resend to let it finish
            if _get(resp, "stop_reason") != "pause_turn":
                break
            left = budget - (_time.monotonic() - start) if budget else None
            if left is not None and left <= 1:
                break
            box = _get(_get(resp, "container"), "id")  # dynamic filtering runs code: the paused code goes on in its own container
            more = dict(req, container=box) if isinstance(box, str) and box else req
            resp = within(left).beta.messages.create(messages=messages[:1] + [{"role": "assistant", "content": _get(resp, "content")}], **more)
            responses.append(resp)
    except ImportError:
        raise ResearchError("the anthropic package is not installed") from None
    except Exception as e:
        raise ResearchError(api_error_text(e)) from None
    stop = _get(resp, "stop_reason")
    if stop == "refusal":
        return stop, "", {}
    if stop in ("pause_turn", "max_tokens"):  # cut off: not a "found nothing", so it isn't saved
        raise ResearchError("the lookup didn't finish")
    seen = {}

    def page(u):
        return seen.setdefault(url_key(u), {"cited": [], "age": ""})
    asked = {}  # web_fetch's tool use id -> the address Claude asked it to open
    for r in responses:
        for b in _get(r, "content") or []:
            if _get(b, "type") == "server_tool_use" and _get(b, "name") == "web_fetch" and isinstance(_get(b, "input"), dict):
                asked[_get(b, "id")] = _get(b, "input").get("url")
    for r in responses:
        for b in _get(r, "content") or []:  # other blocks (dynamic filtering's code runs, ...) add nothing
            if _get(b, "type") == "web_search_tool_result" and isinstance(_get(b, "content"), list):
                for x in _get(b, "content"):
                    u = safe_url(_get(x, "url"))
                    if u:
                        p = page(u)
                        p["age"] = p["age"] or page_day(_get(x, "page_age"))
            if _get(b, "type") == "web_fetch_tool_result" and _get(_get(b, "content"), "type") == "web_fetch_result":
                for u in (_get(_get(b, "content"), "url"), asked.get(_get(b, "tool_use_id"))):  # opened: where it landed and what was asked
                    u = safe_url(u)
                    if u:
                        page(u)
            for c in _get(b, "citations") or []:
                u = safe_url(_get(c, "url"))
                if u:
                    t = _get(c, "cited_text")
                    page(u)["cited"] += [t[:2000]] if isinstance(t, str) and t.strip() else []
    text = "".join(_get(b, "text") or "" for b in _get(resp, "content") or [] if _get(b, "type") == "text")
    return stop, text, seen


USAGE = PerUser(lambda: {"lookups": 0, "input": 0, "output": 0})  # Claude tokens research used since the server started


def log_usage(responses):
    """Add up one lookup's Claude tokens (all resends) and print them, so the cost of research can be measured."""
    n = {"input": 0, "cached": 0, "written": 0, "output": 0, "searches": 0, "fetches": 0}
    for r in responses:
        u = _get(r, "usage")
        if u is None:
            continue
        for k, f in (("input", "input_tokens"), ("cached", "cache_read_input_tokens"), ("written", "cache_creation_input_tokens"),
                     ("output", "output_tokens")):
            v = _get(u, f)
            n[k] += v if isinstance(v, int) else 0
        st = _get(u, "server_tool_use")
        for k, f in (("searches", "web_search_requests"), ("fetches", "web_fetch_requests")):
            v = _get(st, f) if st is not None else None
            n[k] += v if isinstance(v, int) else 0
    with RQ_LOCK:
        USAGE["lookups"] += 1
        USAGE["input"] += n["input"] + n["cached"] + n["written"]
        USAGE["output"] += n["output"]
        total = dict(USAGE)
    try:  # a closed console must never throw away a lookup that is already paid for
        print("[research] tokens in " + str(n["input"] + n["cached"] + n["written"]) + " (full price " + str(n["input"]) + ", cache reads "
              + str(n["cached"]) + ", cache writes " + str(n["written"]) + "), out " + str(n["output"])
              + "; searches " + str(n["searches"]) + ", pages opened " + str(n["fetches"]) + "; resends " + str(len(responses) - 1)
              + " | since start: " + str(total["lookups"]) + " lookups, in " + str(total["input"]) + ", out " + str(total["output"]), flush=True)
    except (OSError, ValueError):
        pass


def page_day(v):
    """The search's page_age ("April 30, 2025", "Apr 30, 2025", "2025-04-30T…") as YYYY-MM-DD; "" for anything else
    ("3 days ago" included)."""
    s = clean_text(v, 40)
    m = re.match(r"(\d{4}-\d{2}-\d{2})(?:$|[T ])", s)
    tries = [(m.group(1), "%Y-%m-%d")] if m else [(s, f) for f in ("%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y")]
    for t, fmt in tries:
        try:
            return datetime.strptime(t, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return ""


def merge_research(email, result, now=None):
    """Save a result under records.people[email]. Fields the user typed or confirmed are never overwritten."""
    now = now or datetime.now(timezone.utc)
    with RECORDS_LOCK:
        r = load_records()
        rec = r["people"].setdefault(email, {})
        confirmed = rec.get("found") == "confirmed"  # you confirmed them: a fresh look-up only refreshes the profile below
        auto = set(rec.get("autoFields") or [])
        for f in () if confirmed else RESEARCH_FIELDS + ("sources",):
            v = result.get(f)
            if f == "relationship" and v == "unknown":
                v = ""
            if v and (f in auto or not rec.get(f)):
                rec[f] = v
                auto.add(f)
        if not confirmed:
            rec["autoFields"] = sorted(auto)
            if auto:
                rec["found"] = "auto"
            rec["lookup"] = result.get("status", "unknown")
            rec["confidence"] = result.get("confidence", "") if result.get("status") == "done" else ""
            rec["foundAt"] = now.replace(microsecond=0).isoformat()  # (a confirmed person's "found" date, and its alert, stay as they were)
        if "profile" in result:  # deep research ran (research_person): its profile, and that it ran, so it isn't redone for 30 days
            rec["deepAt"], rec["searched"] = now.replace(microsecond=0).isoformat(), int(result.get("searched") or 0)
            rec["deepV"] = DEEP_V  # what this deep run asked for (v3: also who they're connected with), so it's asked once, not again and again
            if result.get("profile"):
                rec["profile"] = result["profile"]
            elif not profile_view(rec.get("profile"), "person"):
                rec.pop("profile", None)  # an older kind of profile: gone, so it isn't looked up again and again
        if len(json.dumps(r)) > MAX_RECORDS_BYTES:
            raise ResearchError("the records store is full")
        save_json(records_path(), r)
        return dict(rec)


def sites_searched(seen):
    """How many sites (hosts) the research saw, blocked ones left out."""
    return len({h for h in (k.split("/", 1)[0] for k in seen or {}) if h and not blocked_url("https://" + h + "/")})


def searched_note(rec, what):
    """The plain note for research that found nothing, like "Overture searched 6 sites and found no public work information about them."."""
    n = rec.get("searched") if isinstance(rec.get("searched"), int) and not isinstance(rec.get("searched"), bool) else 0
    return ("Overture searched " + (str(n) + (" site" if n == 1 else " sites") if n > 0 else "the web") + " and found no public " + what + ".")


# ---- research profiles (contract A: a person, B: a company) ----
# Built in code from Claude's JSON: each bullet is kept only when it cites a page the search or web fetch really returned (and
# that no blocked site holds), with no email address, phone number or personal-life detail in it. Stored profiles are checked
# again before the page gets them (a site you block later drops its bullets).

PROFILE_PHONE_RE = re.compile(r"\+\d[\d\s().-]{6,}\d|\(?\b\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b|\b\d{10,13}\b")  # not "2019 - 2022"
PERSONAL_RE = re.compile(
    r"(?i)\b(?:spouses?|wife|wives|husbands?|married|marriage|fianc[ée]e?|divorc\w*|girlfriend|boyfriend|"
    r"(?:his|her|their|has|have)\s+(?:\w+\s+)?(?:children|kids|daughters?|sons?|child|baby|babies|family)|"
    r"(?:father|mother|mom|mum|dad|parent)\s+of|age\s+\d{1,3}|(?:his|her|their)\s+age|\d{1,3}[- ]years?[- ]old|born\s+(?:on|in)|birthday|"
    r"(?:his|her|their)\s+(?:father|mother|parents?(?!\s+(?:company|companies|organi[sz]ations?|firm|group))|mom|mum|dad|brothers?|sisters?|"
    r"siblings?|cousins?|uncle|aunt|grand\w+)|\w+-in-laws?|"
    r"home\s+address|lives\s+in|resides\s+in|religio\w*|(?:his|her|their)\s+faith|political\s+(?:part(?:y|ies)|views?|affiliation|leanings?)|"
    r"votes?\s+for|(?:his|her|their)\s+(?:health|illness|condition|diagnosis|recovery)|health\s+(?:condition|issue|problem|scare)s?|"
    r"diagnos(?:ed|is|es)|illness|pregnan\w*)\b")
PERSON_LISTS = (("now", 6), ("education", 3), ("work", 6), ("forCall", 4))
ORG_LISTS = (("what", 6), ("tech", 6), ("forCall", 4))


def _profile_text(v, limit, personal=True):
    """One cleaned piece of a profile, cut to `limit` characters, or "" when it holds contact details or (for a person) their
    personal life."""
    t = clip(v, limit) if isinstance(v, str) else ""
    if not t or "@" in t or PROFILE_PHONE_RE.search(t) or re.search(r"(?i)\b(?:https?://|www\.)", t) or (personal and PERSONAL_RE.search(t)):
        return ""
    return t


def _profile_refs(refs, resolve):
    out = []
    for c in refs if isinstance(refs, list) else []:
        i = resolve(c)
        if i is not None and i not in out:
            out.append(i)
    return out


def _profile_lines(items, resolve, limit, personal, when=False, chars=PROFILE_CHARS):
    out = []
    for e in items if isinstance(items, list) else []:
        if not isinstance(e, dict):
            continue  # a bare sentence names no source: dropped
        text = _profile_text(e.get("text"), chars, personal)
        src = _profile_refs(e.get("src", e.get("sources")), resolve)
        if text and src:
            out.append(dict({"text": text, "src": src}, **({"when": _profile_text(e.get("when"), 40, personal)} if when else {})))
        if len(out) == limit:
            break
    return out


def looks_like_name(name):
    """2 to 4 capitalised words of letters (any alphabet: "José García", "Zoë Chen"), apostrophes, dots or hyphens."""
    words = str(name or "").split(" ")
    return 2 <= len(words) <= 4 and all(re.fullmatch(r"[^\W\d_](?:[^\W\d_]|['’.-])*", w) and w[0].isupper() for w in words)


def _profile_people(items, resolve):
    """Who a public page names with them at work: a real-looking full name, how they're connected, and the page that says so.
    The same contact and personal-life filter as every other line; at most 10."""
    out, names = [], set()
    for e in items if isinstance(items, list) else []:
        if not isinstance(e, dict):
            continue
        name, how = _profile_text(e.get("name"), 80), _profile_text(e.get("how"), PROFILE_CHARS)
        src = _profile_refs(e.get("src", e.get("sources")), resolve)
        if not (name and looks_like_name(name) and how and src) or name.lower() in names:
            continue
        names.add(name.lower())
        out.append({"name": name, "role": _profile_text(e.get("role"), 120), "org": _profile_text(e.get("org"), 120), "how": how,
                    "when": _profile_text(e.get("when"), 40), "src": src})
        if len(out) == 10:
            break
    return out


def _profile_body(obj, kind, resolve):
    """The sections of a profile (from Claude's JSON or a stored profile), every src list holding what resolve() gives."""
    personal = kind == "person"
    s = obj.get("summary")
    body = {"summary": (_profile_lines([s], resolve, 1, personal, chars=400) or [None])[0] if isinstance(s, dict) else None}
    for key, n in PERSON_LISTS if personal else ORG_LISTS:
        body[key] = _profile_lines(obj.get(key), resolve, n, personal)
    if personal:
        past = []
        for e in obj.get("past") if isinstance(obj.get("past"), list) else []:
            if not isinstance(e, dict):
                continue
            role, org = _profile_text(e.get("role"), 120), _profile_text(e.get("org"), 120)
            points = _profile_lines(e.get("points"), resolve, 4, True)
            src = _profile_refs(e.get("src", e.get("sources")), resolve) or sorted({i for p in points for i in p["src"]})
            if (role or org) and src:
                past.append({"role": role, "org": org, "when": _profile_text(e.get("when"), 40), "src": src, "points": points})
            if len(past) == 8:
                break
        body["past"] = past
        body["people"] = _profile_people(obj.get("people"), resolve)
    else:
        facts = []
        for e in obj.get("facts") if isinstance(obj.get("facts"), list) else []:
            if not isinstance(e, dict):
                continue
            label, value = _profile_text(e.get("label"), 40, False), _profile_text(e.get("value"), 200, False)
            src = _profile_refs(e.get("src", e.get("sources")), resolve)
            if label and value and src:
                facts.append({"label": label, "value": value, "src": src})
            if len(facts) == 8:
                break
        body["facts"] = facts
        body["news"] = _profile_lines(obj.get("news"), resolve, 5, False, when=True)
    return body


def _profile_finish(kind, body, cands, head):
    """The profile, with only the sources its bullets cite (renumbered from 0 in their order), or None when nothing is left."""
    content = ("summary", "now", "past", "education", "work") if kind == "person" else ("summary", "facts", "what", "news", "tech")
    if not any(body.get(k) for k in content):
        return None
    holders = ([body["summary"]] if body.get("summary") else []) + [e for k, v in body.items() if isinstance(v, list) for e in v]
    holders += [p for e in body.get("past") or [] for p in e["points"]]
    used = sorted({i for h in holders for i in h["src"]})
    remap = {old: new for new, old in enumerate(used)}
    for h in holders:
        h["src"] = [remap[i] for i in h["src"]]
    return dict({"v": PROFILE_V}, **head, **body, sources=[cands[i] for i in used])


def _source_label(s, url):
    label = _profile_text(s.get("label"), 120, False) if isinstance(s, dict) else ""
    return label or urllib.parse.urlsplit(url).hostname


def clean_profile(obj, seen, kind, name="", domain=""):
    """Claude's deep-research JSON -> a person profile (contract A) or a company profile (contract B), or None. Its sources are
    the pages it cites that the search or web fetch really returned (seen, from run_search) and that no blocked site holds."""
    if not isinstance(obj, dict) or obj.get("found") is not True or obj.get("confidence") not in ("high", "medium"):
        return None
    cands, by_num, by_key = [], {}, {}
    for n, s in enumerate(obj.get("sources") if isinstance(obj.get("sources"), list) else [], 1):
        url = safe_url(s.get("url")) if isinstance(s, dict) else ""
        if not url or blocked_url(url) or url_key(url) not in (seen or {}):
            continue  # off-list, on a blocked site, or never returned by the search or web fetch
        k = url_key(url)
        if k not in by_key and len(cands) < PROFILE_SOURCES:
            by_key[k] = len(cands)
            cands.append({"url": url, "label": _source_label(s, url)})
        if k in by_key:
            by_num[n] = by_key[k]

    def resolve(c):  # Claude cites a page by its number in its sources list (1 = the first) or by its address
        if isinstance(c, int) and not isinstance(c, bool):
            return by_num.get(c)
        u = safe_url(c) if isinstance(c, str) else ""
        return by_key.get(url_key(u)) if u else None
    head = {"name": clean_text(name, 120), "at": now_iso(), "confidence": obj["confidence"]}
    if kind == "org":
        real = _profile_text(obj.get("name"), 120, False)
        head = dict(head, domain=str(domain or "").lower(), name=real or clean_text(name, 120))
    return _profile_finish(kind, _profile_body(obj, kind, resolve), cands, head)


def profile_view(p, kind):
    """A stored profile, checked again for the page: sources on a site blocked since (Settings) are dropped and the bullets that
    only cite them go too. None when there is no profile of this version."""
    if not isinstance(p, dict) or p.get("v") != PROFILE_V:
        return None
    cands, remap = [], {}
    for i, s in enumerate(p.get("sources") if isinstance(p.get("sources"), list) else []):
        url = safe_url(s.get("url")) if isinstance(s, dict) else ""
        if url and not blocked_url(url):
            remap[i] = len(cands)
            cands.append({"url": url, "label": _source_label(s, url)})
    head = {"name": clean_text(p.get("name"), 120), "at": clean_text(p.get("at"), 40),
            "confidence": p.get("confidence") if p.get("confidence") in ("high", "medium") else ""}
    if kind == "org":
        head["domain"] = str(p.get("domain") or "").lower() if DOMAIN_RE.match(str(p.get("domain") or "").lower()) else ""
    return _profile_finish(kind, _profile_body(p, kind, lambda c: remap.get(c) if isinstance(c, int) and not isinstance(c, bool) else None),
                           cands, head)


def profile_for_ai(p):
    """A profile as plain sentences for a brief or an answer (Claude doesn't need the page addresses)."""
    if not isinstance(p, dict):
        return None
    out = {"from": "Overture's web research (public pages)", "name": p.get("name", "")}
    if p.get("summary"):
        out["summary"] = p["summary"]["text"]
    for k in ("now", "education", "work", "what", "tech", "forCall"):
        if p.get(k):
            out[k] = [e["text"] for e in p[k]]
    if p.get("past"):
        out["past"] = [{"role": e["role"], "org": e["org"], "when": e["when"], "points": [x["text"] for x in e["points"]]} for e in p["past"]]
    if p.get("facts"):
        out["facts"] = {e["label"]: e["value"] for e in p["facts"]}
    if p.get("news"):
        out["news"] = [(e["when"] + ": " if e.get("when") else "") + e["text"] for e in p["news"]]
    return out


_AHEAD = "a week" if DEEP_DAYS_AHEAD == 7 else str(DEEP_DAYS_AHEAD) + " days"
LATER_NOTE = "Overture researches them in depth " + _AHEAD + " before the call."
ORG_LATER_NOTE = "Overture researches this company in depth " + _AHEAD + " before the call."


def research_status(email, rec, m, now=None):
    if m.get("crm"):
        return "skipped", ""  # the title came from HubSpot
    with RQ_LOCK:
        if email in RQ["pending"] or email in RQ["running"]:
            return "pending", "Looking up…"
        err = RQ["errors"].get(email)
    if err and rec.get("found") != "confirmed":  # a failed refresh never hides what you confirmed
        return "error", "Couldn't look them up: " + err + "."
    if rec.get("lookup") == "done":
        return "done", ""
    if rec.get("lookup") == "unknown":
        return "unknown", searched_note(rec, "work information about them")
    why = skip_reason(email, m, rec).strip()
    if not why and not call_soon(m, now or datetime.now(timezone.utc)):
        return "later", LATER_NOTE  # Look up now still works (request_research doesn't wait)
    return ("notfound" if why.startswith("Can't find") else "skipped"), why


def research_view(email, rec, m):
    """What the page shows about one guest's research (all text is escaped by the page)."""
    rec = rec if isinstance(rec, dict) else {}
    status, note = research_status(email, rec, m)
    srcs = [{"url": u, "label": clean_text(s.get("label"), 120) or urllib.parse.urlsplit(u).hostname}
            for s in rec.get("sources") or [] if isinstance(s, dict) for u in [safe_url(s.get("url"))] if u and not blocked_url(u)]
    return {
        "status": status, "note": note, "found": str(rec.get("found") or ""), "foundAt": str(rec.get("foundAt") or ""),
        "confidence": str(rec.get("confidence") or ""), "title": str(rec.get("title") or ""), "team": str(rec.get("team") or ""),
        "seniority": str(rec.get("seniority") or ""), "tenure": str(rec.get("tenure") or ""),
        "relationship": str(rec.get("relationship") or ""), "sources": srcs[:3], "local": dict(m.get("local") or {}),
        "nameFrom": str(m.get("nameFrom") or ""), "nameUsed": str(m.get("name") or "") if m.get("nameFrom") in ("email", "event") else "",
        "profile": profile_view(rec.get("profile"), "person"),  # contract A, or None
    }


def research_fill(live, records, meta):
    people = records.get("people") or {}
    for email, m in meta.items():
        if email in live["people"]:
            live["people"][email]["research"] = research_view(email, people.get(email) or {}, m)
    # Company research: live.orgs[domain] = {status, note, domain, company, foundAt, profile}, and the profile on the company row
    # the calls use (live.companies[name].profile; a row only research made is marked researchOnly).
    orgs, rec_orgs = {}, records.get("orgs") or {}
    for d, om in org_meta(meta).items():
        view = orgs[d] = org_research_view(d, om, rec_orgs.get(d) or {})
        if view["profile"] and om["name"]:
            row = live["companies"].get(om["name"])
            if not isinstance(row, dict):
                row = live["companies"][om["name"]] = {"engineers": None, "status": "Prospect", "history": [], "customer": False, "notes": "",
                                                       "domain": d, "researchOnly": True}
            row["profile"] = view["profile"]
    live["orgs"] = orgs


def research_body():
    """GET /api/research: statuses for everyone on your upcoming calls, and for their companies (orgs, by domain)."""
    with RQ_LOCK:
        meta = dict(RQ["meta"])
    records = load_records()
    people, rec_orgs = records.get("people") or {}, records.get("orgs") or {}
    return {"claude": claude_on(), "people": {e: research_view(e, people.get(e) or {}, m) for e, m in meta.items()},
            "orgs": {d: org_research_view(d, om, rec_orgs.get(d) or {}) for d, om in org_meta(meta).items()},
            "mentions": mention_statuses(records)}


def research_poll():
    """GET /api/research: a company that waited 30 seconds for an explanation is looked up first, then the statuses."""
    promote_waiting()
    return research_body()


# ---------------------------------------------------------------- HubSpot and Gong ----------------------------------------------------------------
# Read-only, except one guarded write that only happens when you press "Save to HubSpot" (POST /api/hubspot/save with confirm: true).
# Credentials come from the environment or .data/hubspot.json and .data/gong.json (tools/connect.py writes those files).
# They only ever go into an Authorization header to api.hubapi.com or your *.gong.io address: never into a log line, an error
# message, a response, or live.js. Redirects are not followed, so the header can't be carried to another host.
# Shapes checked against developers.hubspot.com (CRM search, notes, associations, account info, pipelines) and help.gong.io
# (API keys, rate limits). Lines marked "untested against a real account" could not be confirmed from public docs.

HUBSPOT_API = "https://api.hubapi.com"
GONG_DEFAULT_BASE = "https://api.gong.io"
CRM_CACHE_SECONDS = 600   # HubSpot and Gong answers are kept 10 minutes
CRM_TIMEOUT = 8           # seconds per request
CRM_BUDGET = 6            # seconds of HubSpot (or Gong) requests per page build (live.js waits for them); the rest comes on a later load
CRM_PAUSE = 60            # after a failure, don't ask that service again for a minute
GONG_DAYS = 180
GONG_WINDOWS = ((0, 14), (14, 45), (45, 90), (90, GONG_DAYS))  # days back, newest first, so a busy workspace never hides its latest calls
GONG_MAX_PAGES = 10       # at most 10 pages of calls (Gong pages hold up to 100), shared across the windows
NOTE_TO_COMPANY, NOTE_TO_CONTACT, NOTE_TO_DEAL = 190, 202, 214  # HubSpot's default association type ids (associations docs)
SERVICE_NAMES = {"hubspot": "HubSpot", "gong": "Gong"}
SECRET_RE = re.compile(r"[\x21-\x7e]+")  # a token or key is printable ASCII with no spaces; anything else was pasted along with it


class ApiError(Exception):
    def __init__(self, message, status=0):
        super().__init__(message)
        self.status = status


class Slow(ApiError):
    """This page build's time budget for the service ran out. Not a failure: keep what came back, the rest comes later."""


class NoAnswer(ApiError):
    """The request went out but no answer came back in time, so a write may or may not have happened."""


class MaybeSaved(ApiError):
    """Save to HubSpot sent the note but never heard back."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # a 3xx comes back as an error instead of re-sending the Authorization header somewhere else


_API_OPENER = urllib.request.build_opener(_NoRedirect)


def _api_http(method, url, body=None, headers=None, timeout=CRM_TIMEOUT):
    """JSON request. Returns (status, parsed JSON or {}, response headers). Raises ApiError("timeout" or "unreachable")
    when no usable answer came back, and nothing else: other errors can quote a header value (a secret) in their message."""
    try:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers=dict(headers or {}))
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with _API_OPENER.open(req, timeout=timeout) as resp:
                raw, status, hdrs = resp.read(), resp.status, dict(resp.headers.items())
        except urllib.error.HTTPError as e:
            raw, status, hdrs = e.read(), e.code, dict((e.headers or {}).items())
    except TimeoutError:
        raise ApiError("timeout") from None
    except (urllib.error.URLError, OSError) as e:
        raise ApiError("timeout" if isinstance(getattr(e, "reason", None), TimeoutError) else "unreachable") from None
    except Exception:  # IncompleteRead, BadStatusLine, a header value that can't be sent (UnicodeEncodeError, ValueError), ...
        raise ApiError("unreachable") from None
    try:
        return status, (json.loads(raw) if raw else {}), hdrs
    except Exception:  # not JSON, or nested too deep (RecursionError)
        return status, {}, hdrs


API_HTTP = _api_http    # tests swap this for a fake
SLEEP = _time.sleep     # and this, so the 429 backoff doesn't slow them down


def hubspot_token():
    """The private app access token from HUBSPOT_TOKEN or .data/hubspot.json, else None."""
    j = load_json(DATA_DIR / "hubspot.json", {})
    t = own_env("HUBSPOT_TOKEN") or (j.get("token") if isinstance(j, dict) else None)
    return t.strip() if isinstance(t, str) and t.strip() else None


def gong_keys():
    """(access key, secret, base URL) from GONG_ACCESS_KEY / GONG_ACCESS_SECRET / GONG_BASE_URL or .data/gong.json, else None."""
    j = load_json(DATA_DIR / "gong.json", {})
    j = j if isinstance(j, dict) else {}
    key = own_env("GONG_ACCESS_KEY") or j.get("access_key")
    secret = own_env("GONG_ACCESS_SECRET") or j.get("access_secret")
    base = os.environ.get("GONG_BASE_URL") or j.get("base_url") or GONG_DEFAULT_BASE
    if not (isinstance(key, str) and key.strip() and isinstance(secret, str) and secret.strip()):
        return None
    return key.strip(), secret.strip(), str(base).strip()


GRANOLA_API = "https://public-api.granola.ai"


def granola_key():
    """Your Granola personal API key from GRANOLA_API_KEY or .data/granola.json, else None."""
    j = load_json(DATA_DIR / "granola.json", {})
    k = own_env("GRANOLA_API_KEY") or (j.get("api_key") if isinstance(j, dict) else None)
    return k.strip() if isinstance(k, str) and k.strip() else None


def gong_base(base):
    """Your Gong API address, without /v2. Only https addresses on gong.io are used, so the key can't be sent elsewhere."""
    try:
        p = urllib.parse.urlsplit(str(base or GONG_DEFAULT_BASE).strip())
        host = (p.hostname or "").lower()
    except ValueError:
        p, host = None, ""
    if not p or p.scheme != "https" or "@" in p.netloc or not (host == "gong.io" or host.endswith(".gong.io")):
        raise ApiError("the Gong address must be an https address on gong.io, like https://api.gong.io (see Settings > Setup guides > Connect Gong)")
    return "https://" + p.netloc.lower()


def crm_configured(service):
    return bool(hubspot_token() if service == "hubspot" else gong_keys())


CRM_STATE = PerUser(lambda: {s: {"lastSync": "", "lastError": "", "pausedUntil": 0.0, "checkedAt": 0.0, "account": ""} for s in list(SERVICE_NAMES) + ["granola"]})
CRM_CACHE = PerUser(dict)  # key -> (saved at, value)
CRM_LOCK = threading.Lock()


def crm_note(service, ok, error=""):
    with CRM_LOCK:
        st = CRM_STATE[service]
        if ok:
            st["lastSync"], st["lastError"], st["pausedUntil"] = now_iso(), "", 0.0
        else:
            st["lastError"], st["pausedUntil"] = error, _time.time() + CRM_PAUSE


def crm_cached(key, fn):
    with CRM_LOCK:
        hit = CRM_CACHE.get(key)
    if hit and _time.time() - hit[0] < CRM_CACHE_SECONDS:
        return hit[1]
    value = fn()
    with CRM_LOCK:
        CRM_CACHE[key] = (_time.time(), value)
        while len(CRM_CACHE) > 2000:  # never grows without bound
            CRM_CACHE.pop(next(iter(CRM_CACHE)))
    return value


def crm_forget(service):
    with CRM_LOCK:
        for k in [k for k in CRM_CACHE if k[0] == service]:
            del CRM_CACHE[k]


def _retry_after(headers):
    for k, v in (headers or {}).items():
        if k.lower() == "retry-after":
            try:
                return min(max(float(v), 1.0), 10.0)
            except ValueError:
                break
    return 2.0


def api_call(service, method, path, body=None, deadline=None):
    """One request to HubSpot or Gong with the saved credentials. Returns the JSON body of a 2xx answer.
    Waits once and retries on 429. Every failure becomes an ApiError with a message that never holds a secret."""
    name = SERVICE_NAMES.get(service) or "Granola"
    if service == "granola":
        key = granola_key()
        if not key:
            raise ApiError("Granola isn't connected")
        if not SECRET_RE.fullmatch(key):
            raise ApiError("Granola's API key has spaces or invisible characters. Run tools/connect.py granola and paste it again.")
        url, auth = GRANOLA_API + path, "Bearer " + key
    elif service == "hubspot":
        token = hubspot_token()
        if not token:
            raise ApiError("HubSpot isn't connected")
        if not SECRET_RE.fullmatch(token):
            raise ApiError("HubSpot's access token has spaces or invisible characters. Run tools/connect.py hubspot and paste it again.")
        url, auth = HUBSPOT_API + path, "Bearer " + token
    else:
        keys = gong_keys()
        if not keys:
            raise ApiError("Gong isn't connected")
        if not (SECRET_RE.fullmatch(keys[0]) and SECRET_RE.fullmatch(keys[1])):
            raise ApiError("Gong's access key or secret has spaces or invisible characters. Run tools/connect.py gong and paste them again.")
        url = gong_base(keys[2]) + path
        auth = "Basic " + base64.b64encode((keys[0] + ":" + keys[1]).encode("utf-8")).decode("ascii")
    status, j, hdrs = 0, {}, {}
    for attempt in (0, 1):
        if deadline and _time.time() > deadline:
            raise Slow(name + " is slow, so Overture stopped asking for now")
        try:
            status, j, hdrs = API_HTTP(method, url, body, {"Authorization": auth})
        except ApiError as e:
            if str(e) == "timeout":
                raise NoAnswer(name + " didn't answer in time") from None
            raise ApiError(name + " couldn't be reached") from None
        if status == 429 and attempt == 0:
            SLEEP(_retry_after(hdrs))
            continue
        break
    if 200 <= status < 300:
        return j if isinstance(j, dict) else {}
    if status == 401:
        raise ApiError(name + " didn't accept " + {"hubspot": "the access token", "gong": "the access key"}.get(service, "the API key") + " (401). Run tools/connect.py again.", 401)
    if status == 403:
        raise ApiError(name + " said no (403): " + {"hubspot": "the private app is missing a scope, see Settings > Setup guides > Connect HubSpot",
                                                    "gong": "the key has no access from here, see Settings > Setup guides > Connect Gong"}.get(service,
                                                    "API access may be off for your workspace, see Settings > Setup guides > After the call with Granola"), 403)
    if status == 429:
        raise ApiError(name + " is limiting requests (429). Overture tries again in a minute.", 429)
    raise ApiError(name + " answered " + str(status), status)


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return int(f) if f == int(f) else f


def _day(v):
    """A HubSpot or Gong date (ISO, or milliseconds) -> "2026-10-20", or ""."""
    s = str(v or "").strip()
    if s.isdigit():
        try:
            return datetime.fromtimestamp(int(s) / 1000, timezone.utc).date().isoformat()
        except (OverflowError, ValueError, OSError):
            return ""
    dt = parse_dt(s)
    return dt.astimezone(timezone.utc).date().isoformat() if dt else (s[:10] if re.match(r"^\d{4}-\d{2}-\d{2}$", s[:10]) else "")


# ---- HubSpot (read) ----

def hubspot_account(deadline=None):
    """Which portal the token belongs to: {"portalId", "uiDomain", "currency"}."""
    def get():
        j = api_call("hubspot", "GET", "/account-info/v3/details", deadline=deadline)
        return {"portalId": clean_text(str(j.get("portalId") or ""), 20), "uiDomain": clean_text(j.get("uiDomain"), 100),
                "currency": clean_text(j.get("companyCurrency"), 8)}
    return crm_cached(("hubspot", "account"), get)


def hubspot_stages(deadline=None):
    """Deal stage id -> {"label", "closed"} for every deal pipeline.
    The stages list and metadata.isClosed in GET /crm/v3/pipelines/deals are untested against a real account."""
    def get():
        out = {}
        for pl in api_call("hubspot", "GET", "/crm/v3/pipelines/deals", deadline=deadline).get("results") or []:
            for stg in (pl.get("stages") or []) if isinstance(pl, dict) else []:
                if isinstance(stg, dict) and stg.get("id"):
                    closed = str((stg.get("metadata") or {}).get("isClosed", "")).lower() == "true"
                    out[str(stg["id"])] = {"label": clean_text(stg.get("label"), 80), "closed": closed}
        return out
    return crm_cached(("hubspot", "stages"), get)


def _assoc_ids(cid, to, deadline):
    """Ids of the records of type `to` linked to one company (associations v4; untested against a real account)."""
    j = api_call("hubspot", "GET", "/crm/v4/objects/companies/" + urllib.parse.quote(str(cid), safe="") + "/associations/" + to + "?limit=100", deadline=deadline)
    return [str(r.get("toObjectId")) for r in j.get("results") or [] if isinstance(r, dict) and r.get("toObjectId")][:100]


def _batch_read(kind, ids, props, deadline):
    if not ids:
        return []
    j = api_call("hubspot", "POST", "/crm/v3/objects/" + kind + "/batch/read",
                 {"properties": props, "inputs": [{"id": i} for i in ids]}, deadline=deadline)
    return [r for r in j.get("results") or [] if isinstance(r, dict)]


def hubspot_company(domain, deadline=None):
    """The HubSpot company with this website domain, its deals and its last 5 notes, or None."""
    def get():
        j = api_call("hubspot", "POST", "/crm/v3/objects/companies/search", {
            "filterGroups": [{"filters": [{"propertyName": "domain", "operator": "EQ", "value": domain}]}],
            "properties": ["name", "domain", "lifecyclestage", "numberofemployees"], "limit": 1}, deadline=deadline)
        found = [r for r in j.get("results") or [] if isinstance(r, dict) and r.get("id")]
        if not found:
            return None
        cid, props = str(found[0]["id"]), found[0].get("properties") or {}
        stages = hubspot_stages(deadline)
        deals = []
        for d in _batch_read("deals", _assoc_ids(cid, "deals", deadline), ["dealname", "dealstage", "amount", "closedate", "pipeline"], deadline):
            p = d.get("properties") or {}
            sid = str(p.get("dealstage") or "")
            stage = stages.get(sid, {})
            deals.append({"id": str(d.get("id")), "name": clip(p.get("dealname"), 200) or "Untitled deal",
                          "stage": stage.get("label") or clean_text(sid, 80), "closed": stage.get("closed", sid in ("closedwon", "closedlost")),
                          "amount": _num(p.get("amount")), "closeDate": _day(p.get("closedate"))})
        deals.sort(key=lambda d: (d["closed"], d["closeDate"] or "9999"))
        # The newest notes on the company, sorted by HubSpot (a company can have hundreds). The associations.company
        # pseudo-property in CRM search is from HubSpot's search docs; untested against a real account.
        try:
            found = api_call("hubspot", "POST", "/crm/v3/objects/notes/search", {
                "filterGroups": [{"filters": [{"propertyName": "associations.company", "operator": "EQ", "value": cid}]}],
                "sorts": [{"propertyName": "hs_timestamp", "direction": "DESCENDING"}],
                "properties": ["hs_note_body", "hs_timestamp"], "limit": 10}, deadline=deadline).get("results") or []
        except ApiError as e:
            if e.status != 403:  # no access to notes: the company and its deals still show, without notes
                raise
            found = []
        notes = []
        for n in found:
            p = (n.get("properties") or {}) if isinstance(n, dict) else {}
            text = plain_text(p.get("hs_note_body"), 600)
            if text:
                notes.append({"date": _day(p.get("hs_timestamp")), "text": text})
        notes.sort(key=lambda n: n["date"], reverse=True)
        return {"id": cid, "name": clean_text(props.get("name"), 120), "lifecycle": str(props.get("lifecyclestage") or "").lower(),
                "employees": _num(props.get("numberofemployees")), "deals": deals[:10], "notes": notes[:5]}
    return crm_cached(("hubspot", "company", domain), get)


def hubspot_contacts(emails, deadline=None):
    """email -> {"id", "name", "title"} for the guests HubSpot has as contacts."""
    emails = sorted({str(e).lower() for e in emails if EMAIL_RE.match(str(e).lower())})[:100]
    if not emails:
        return {}

    def get():
        j = api_call("hubspot", "POST", "/crm/v3/objects/contacts/search", {
            "filterGroups": [{"filters": [{"propertyName": "email", "operator": "IN", "values": emails}]}],
            "properties": ["email", "firstname", "lastname", "jobtitle"], "limit": 100}, deadline=deadline)
        out = {}
        for r in j.get("results") or []:
            p = (r.get("properties") or {}) if isinstance(r, dict) else {}
            em = str(p.get("email") or "").lower()
            if em in emails and r.get("id"):
                out[em] = {"id": str(r["id"]), "title": clip(p.get("jobtitle"), 120),
                           "name": clean_text(" ".join(x for x in (p.get("firstname"), p.get("lastname")) if isinstance(x, str)), 120)}
        return out
    return crm_cached(("hubspot", "contacts", tuple(emails)), get)


def hubspot_status(info):
    """Company status in Overture's words: the open deal's stage, a customer, or a new lead."""
    open_deals = [d for d in info.get("deals") or [] if not d.get("closed")]
    if open_deals:
        return "Open deal: " + (open_deals[0].get("stage") or "open")
    if info.get("lifecycle") == "customer":
        return "Customer"
    return "New lead"


def apply_hubspot_company(companies, name, domain, info):
    """Merge one HubSpot company into live.companies (the data/sample.js shape, plus employees, deals and their sources)."""
    c = companies.setdefault(name, {"engineers": None, "status": "Prospect", "history": [], "customer": False, "notes": "", "domain": domain})
    status = hubspot_status(info)
    customer = info.get("lifecycle") in ("customer", "evangelist") or status.startswith("Customer")  # a customer with an open renewal is still one
    c.update(status=status, customer=customer, employees=info.get("employees"),
             deals=[{k: d.get(k) for k in ("name", "stage", "closed", "amount", "closeDate")} for d in info.get("deals") or []],
             hubspot=True, src={"status": "HubSpot", "employees": "HubSpot", "deals": "HubSpot"})
    hist = [h for h in c.get("history") or [] if h.get("src") != "HubSpot"]
    hist += [{"date": n["date"], "text": n["text"], "src": "HubSpot"} for n in info.get("notes") or []]
    hist.sort(key=lambda h: h.get("date") or "")
    c["history"] = hist


# ---- Gong (read only: call lists and Gong's own summaries, never transcripts) ----

def gong_workspace(deadline=None):
    def get():
        j = api_call("gong", "GET", "/v2/workspaces", deadline=deadline)
        names = [clean_text(w.get("name"), 80) for w in j.get("workspaces") or [] if isinstance(w, dict)]
        return ", ".join(n for n in names if n)[:200]
    return crm_cached(("gong", "workspace"), get)


def _gong_post(body, deadline):
    try:
        return api_call("gong", "POST", "/v2/calls/extensive", body, deadline=deadline)
    except ApiError as e:
        if e.status == 404:  # Gong answers 404 when no call matches the filter
            return {}
        raise


def gong_index(now=None, deadline=None):
    """Gong calls in the last 180 days: id, start, title, duration, link, and its participants' email domains.
    Gong documents no sort order (calls may come oldest first), so it asks for the last 14 days first, then further back,
    with one page budget for all of them. If the time budget runs out, the newest calls it has are kept (and cached).
    Private calls (metaData.isPrivate) are skipped: Gong hides them from most users, and Overture reads with an admin key."""
    now = now or datetime.now(timezone.utc)

    def get():
        out, seen, pages = [], set(), 0
        try:
            for a, b in GONG_WINDOWS:
                flt = {"fromDateTime": (now - timedelta(days=b)).replace(microsecond=0).isoformat(),
                       "toDateTime": (now - timedelta(days=a)).replace(microsecond=0).isoformat()}
                cursor = None
                while pages < GONG_MAX_PAGES:
                    body = {"filter": flt, "contentSelector": {"exposedFields": {"parties": True}}}
                    if cursor:
                        body["cursor"] = cursor
                    j = _gong_post(body, deadline)
                    pages += 1
                    for call in j.get("calls") or []:
                        md = (call.get("metaData") or {}) if isinstance(call, dict) else {}
                        if not md.get("id") or str(md["id"]) in seen or md.get("isPrivate") is True:
                            continue
                        seen.add(str(md["id"]))
                        domains = {domain_of(p.get("emailAddress")) for p in call.get("parties") or [] if isinstance(p, dict)}
                        out.append({"id": str(md["id"]), "started": str(md.get("started") or md.get("scheduled") or ""), "title": clip(md.get("title"), 200),
                                    "duration": _num(md.get("duration")), "url": safe_url(md.get("url")), "domains": sorted(d for d in domains if d)})
                    cursor = (j.get("records") or {}).get("cursor")
                    if not cursor:
                        break
        except Slow:
            if not out:
                raise
        return out
    return crm_cached(("gong", "index"), get)


def gong_details(ids, deadline=None):
    """call id -> Gong's brief, key points, topics and trackers. Transcripts are never asked for.
    The field names under content (brief, keyPoints, topics, trackers) are untested against a real account."""
    ids = sorted(set(ids))[:50]
    if not ids:
        return {}

    def get():
        j = _gong_post({"filter": {"callIds": ids}, "contentSelector": {"exposedFields": {
            "content": {"brief": True, "keyPoints": True, "topics": True, "trackers": True}}}}, deadline)
        out = {}
        for call in j.get("calls") or []:
            if not isinstance(call, dict):
                continue
            cid, ct = str((call.get("metaData") or {}).get("id") or ""), call.get("content") or {}
            if not cid or not isinstance(ct, dict):
                continue
            out[cid] = {
                "brief": " ".join(CONTROL_RE.sub(" ", str(ct.get("brief") or "")).split())[:1500],
                "keyPoints": [t for t in (clip(k.get("text"), 400) for k in ct.get("keyPoints") or [] if isinstance(k, dict)) if t][:6],
                "topics": [t for t in (clean_text(k.get("name"), 60) for k in ct.get("topics") or [] if isinstance(k, dict)) if t][:8],
                "trackers": [{"name": clean_text(k.get("name"), 60), "count": int(_num(k.get("count")) or 0)}
                             for k in ct.get("trackers") or [] if isinstance(k, dict) and clean_text(k.get("name"), 60) and (_num(k.get("count")) or 0) > 0][:8],
            }
        return out
    return crm_cached(("gong", "details", tuple(ids)), get)


def gong_for_invites(invites, records, now=None, deadline=None):
    """Company name -> the last Gong call (last 180 days) with anyone on that company's email domain.
    A call counts when a guest's domain is the same, a subdomain or parent of it, or one your records give the same company.
    A name made up from the domain never counts: acme.com and acme.ai are different companies."""
    calls = gong_index(now, deadline)
    names = {x: records_company(x, records) for c in calls for x in c["domains"]}  # once per domain, not per call
    latest = {}
    for inv in invites:
        d, co = inv.get("domain"), inv["company"]
        if not d or co in latest:
            continue
        want = records_company(d, records)
        mine = [c for c in calls if any(x == d or x.endswith("." + d) or d.endswith("." + x) or (want and names.get(x) == want)
                                        for x in c["domains"])]
        if mine:
            mine.sort(key=lambda c: c["started"], reverse=True)
            latest[co] = dict(mine[0], count=len(mine))
    details = gong_details([c["id"] for c in latest.values()], deadline)
    out = {}
    for co, c in latest.items():
        g = {"title": c["title"] or "Untitled call", "date": _day(c["started"]), "duration": c["duration"], "url": c["url"],
             "count": c["count"], "brief": "", "keyPoints": [], "topics": [], "trackers": []}
        g.update(details.get(c["id"]) or {})
        out[co] = g
    return out


# ---- both ----

def crm_fetch(invites, me_email, records, now=None):
    """HubSpot and Gong data for these calls: {"companies": {domain: ...}, "contacts": {email: ...}, "gong": {company: ...}}.
    Never raises: a service that fails is skipped (its error shows on the Data page) and the page still builds.
    A company HubSpot wasn't asked about before the time budget ran out is left out of "companies" (found but empty is None)."""
    out = {"companies": {}, "contacts": {}, "gong": {}}
    mine = domain_of(me_email)
    for service in SERVICE_NAMES:
        if not crm_configured(service) or not source_on(service, records):  # Settings > Research sources can turn one off
            continue
        with CRM_LOCK:
            if CRM_STATE[service]["pausedUntil"] > _time.time():
                continue
        deadline = _time.time() + CRM_BUDGET
        contacts, companies = {}, {}
        try:
            if service == "hubspot":
                try:
                    out["currency"] = hubspot_account(deadline).get("currency", "")
                except ApiError as e:
                    if e.status != 403:  # 403 here only means no access to account details
                        raise
                emails = [a["email"] for inv in invites for a in inv["attendees"] if not (mine and domain_of(a["email"]) == mine)]
                contacts = hubspot_contacts(emails, deadline)
                for d in sorted({inv["domain"] for inv in invites if inv.get("domain")}):  # one at a time: what came back is kept
                    companies[d] = hubspot_company(d, deadline)
            else:
                out["gong"] = gong_for_invites(invites, records, now, deadline)
        except Slow:
            pass  # the time budget ran out: not a failure, the rest comes on a later load (answers so far are cached)
        except ApiError as e:
            crm_note(service, False, str(e))
            continue
        except Exception:  # an answer Overture didn't expect: never break the page, never show its text (it could quote a secret)
            crm_note(service, False, SERVICE_NAMES[service] + " failed unexpectedly")
            continue
        if service == "hubspot":
            out["contacts"], out["companies"] = contacts, companies
        crm_note(service, True)
    return out


def crm_probe():
    """Check each connected service once every 10 minutes, so the Data page can say which portal or workspace it is."""
    for service in SERVICE_NAMES:
        if not crm_configured(service):
            continue
        with CRM_LOCK:
            st = CRM_STATE[service]
            if st["pausedUntil"] > _time.time() or _time.time() - st["checkedAt"] < CRM_CACHE_SECONDS:
                continue
            st["checkedAt"] = _time.time()
        try:
            if service == "hubspot":
                try:
                    a = hubspot_account(_time.time() + CRM_TIMEOUT)
                    label = ("portal " + a["portalId"] + (" (" + a["uiDomain"] + ")" if a["uiDomain"] else "")) if a["portalId"] else ""
                except ApiError as e:
                    if e.status != 403:  # 403 here only means no access to account details: the token itself works
                        raise
                    label = ""
            else:
                label = gong_workspace(_time.time() + CRM_TIMEOUT)
            with CRM_LOCK:
                CRM_STATE[service]["account"] = label
            crm_note(service, True)
        except ApiError as e:
            crm_note(service, False, str(e))
        except Exception:
            crm_note(service, False, SERVICE_NAMES[service] + " failed unexpectedly")


def crm_status():
    """What /api/status and the Data page say about HubSpot and Gong. No credentials, ever."""
    out = {}
    for service in SERVICE_NAMES:
        on = crm_configured(service)
        with CRM_LOCK:
            st = dict(CRM_STATE[service])
        out[service] = {"configured": on, "connected": bool(on and st["lastSync"] and not st["lastError"]),
                        "lastSync": st["lastSync"] if on else "", "lastError": st["lastError"] if on else ""}
        out[service]["portal" if service == "hubspot" else "workspace"] = st["account"] if on else ""
    return out


def gong_in_ai(records):
    """The "Use Gong notes in AI answers" setting (off unless you turn it on)."""
    return setting_on(records, "gongInAI")


def setting_on(records, key):
    """A Data-page setting: off unless you turned it on."""
    return (records.get("settings") or {}).get(key) is True


# ---- HubSpot (write, only when you press "Save to HubSpot") ----

def clean_hubspot_save(body):
    _only(body, {"callId", "note", "titles", "confirm", "planId"})
    cid = _str(body, "callId", 200, True)
    if not CALLID_RE.match(cid):
        raise Invalid("callId doesn't look right")
    note = body.get("note", "")
    if not isinstance(note, str) or len(note) > 20000:
        raise Invalid("note must be text, at most 20000 characters")
    titles = body.get("titles", [])
    if not isinstance(titles, list) or len(titles) > 20 or not all(isinstance(t, str) and EMAIL_RE.match(t.lower()) for t in titles):
        raise Invalid("titles must be a list of email addresses")
    if "confirm" in body and body["confirm"] is not True:
        raise Invalid("confirm must be true")
    plan_id = _str(body, "planId", 64) or ""
    if body.get("confirm") is True and not re.fullmatch(r"[0-9a-f]{16}", plan_id):
        raise Invalid("planId is missing: check the preview again before saving")
    return {"callId": cid, "note": note.strip(), "titles": sorted({t.lower() for t in titles}), "confirm": body.get("confirm") is True,
            "planId": plan_id}


def note_html(inv, text):
    """The note's body for HubSpot: every character you typed is escaped; line breaks become <br>."""
    lines = html_escape(text).replace("\r\n", "\n").split("\n")
    return ("<p><strong>" + html_escape(inv["title"]) + "</strong> · " + html_escape(inv["when"]) + "</p><p>" + "<br>".join(lines)
            + "</p><p>Saved from Overture</p>")


def hubspot_plan(c, live, crm, records):
    """Exactly what Save to HubSpot would write for one call, or Invalid with the reason it can't."""
    inv = next((i for i in (live or {}).get("invites") or [] if i["id"] == c["callId"]), None)
    if not inv:
        raise Invalid("That call isn't on your calendar any more.")
    companies = crm.get("companies") or {}
    if inv.get("domain") and inv["domain"] not in companies:  # the time budget ran out before Overture asked about it
        raise Invalid("HubSpot is slow right now, so Overture couldn't check " + inv["company"] + " yet. Try again in a moment.")
    info = companies.get(inv.get("domain") or "")
    if not info:
        raise Invalid("HubSpot has no company with the website " + (inv.get("domain") or "of these guests") + ", so there's nothing to add the note to.")
    contacts = crm.get("contacts") or {}
    rec_people = records.get("people") or {}
    on_call = [(a, contacts[a["email"]]) for a in inv["attendees"] if a["email"] in contacts]
    deal = next((d for d in info.get("deals") or [] if not d.get("closed")), None)
    candidates = []
    for a, hs in on_call:
        r = rec_people.get(a["email"]) or {}
        mine = clean_text(r.get("title"), 120)
        if mine and mine.lower() != (hs.get("title") or "").lower():
            why = ("you confirmed it in Overture" if r.get("found") == "confirmed"
                   else "Overture found it automatically" if "title" in (r.get("autoFields") or []) else "you typed it in Overture")
            candidates.append({"email": a["email"], "name": a["name"], "from": hs.get("title") or "", "to": mine, "why": why, "contactId": hs["id"]})
    known = {x["email"] for x in candidates}
    for e in c["titles"]:
        if e not in known:
            raise Invalid("There's no title change for " + e + " to send.")
    picked = [x for x in candidates if x["email"] in c["titles"]]
    saved = (records.get("hubspotSaved") or {}).get(c["callId"]) or {}
    return {
        "company": {"id": info["id"], "name": info.get("name") or inv["company"]},
        "note": {"text": c["note"], "html": note_html(inv, c["note"]),
                 "preview": inv["title"] + " · " + inv["when"] + "\n\n" + c["note"] + "\n\nSaved from Overture"} if c["note"] else None,
        "contacts": [{"id": hs["id"], "name": hs.get("name") or a["name"], "email": a["email"]} for a, hs in on_call],
        "deal": {"id": deal["id"], "name": deal["name"], "stage": deal.get("stage", "")} if deal else None,
        "titleChanges": picked,
        "candidates": [{k: x[k] for k in ("email", "name", "from", "to", "why")} for x in candidates],
        "savedBefore": str(saved.get("at") or ""),
        "savedUnsure": saved.get("note") == "unknown",
    }


def plan_id(plan):
    """A fingerprint of everything a save would write (and of the last save), so confirm writes only the plan you saw."""
    return hashlib.sha256(json.dumps([plan["company"]["id"], plan["deal"] and plan["deal"]["id"], [x["id"] for x in plan["contacts"]],
                                      plan["note"] and plan["note"]["html"], [(x["contactId"], x["to"]) for x in plan["titleChanges"]],
                                      plan["savedBefore"]]).encode("utf-8")).hexdigest()[:16]


def public_plan(plan):
    """The plan as the page sees it: no HubSpot record ids. preview is the note exactly as it will read in HubSpot."""
    return {"company": plan["company"]["name"], "note": plan["note"]["text"] if plan["note"] else "",
            "preview": plan["note"]["preview"] if plan["note"] else "",
            "contacts": [{"name": x["name"], "email": x["email"]} for x in plan["contacts"]],
            "deal": {"name": plan["deal"]["name"], "stage": plan["deal"]["stage"]} if plan["deal"] else None,
            "titleChanges": [{k: x[k] for k in ("email", "name", "from", "to")} for x in plan["titleChanges"]],
            "candidates": plan["candidates"], "savedBefore": plan["savedBefore"], "savedUnsure": plan["savedUnsure"],
            "planId": plan_id(plan)}


def remember_save(call_id, entry):
    with RECORDS_LOCK:
        r = load_records()
        r["hubspotSaved"][call_id] = entry
        save_json(records_path(), r)


def hubspot_write(plan, call_id, now=None):
    """Write the plan: one note (on the company, linked to the call's contacts and the open deal), then the title changes."""
    now = now or datetime.now(timezone.utc)
    wrote_note, done, problems = False, [], []
    if plan["note"]:
        hd = lambda type_id, rid: {"to": {"id": rid}, "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": type_id}]}
        assoc = [hd(NOTE_TO_COMPANY, plan["company"]["id"])] + [hd(NOTE_TO_CONTACT, x["id"]) for x in plan["contacts"]]
        if plan["deal"]:
            assoc.append(hd(NOTE_TO_DEAL, plan["deal"]["id"]))
        try:
            api_call("hubspot", "POST", "/crm/v3/objects/notes", {
                "properties": {"hs_timestamp": now.replace(microsecond=0).isoformat().replace("+00:00", "Z"), "hs_note_body": plan["note"]["html"]},
                "associations": assoc})
        except NoAnswer:
            # HubSpot may have made the note and lost the answer: remember the try, so the next preview warns before a second note
            crm_forget("hubspot")
            remember_save(call_id, {"at": now_iso(), "note": "unknown", "titles": []})
            raise MaybeSaved("HubSpot didn't answer in time. The note may have been saved: check the company in HubSpot before saving again.") from None
        wrote_note = True
    for x in plan["titleChanges"]:
        try:
            api_call("hubspot", "PATCH", "/crm/v3/objects/contacts/" + urllib.parse.quote(x["contactId"], safe=""), {"properties": {"jobtitle": x["to"]}})
            done.append(x["email"])
        except ApiError as e:
            problems.append(x["name"] + "'s title wasn't changed: " + str(e))
    crm_forget("hubspot")  # the next page load shows what HubSpot has now
    crm_note("hubspot", True)
    remember_save(call_id, {"at": now_iso(), "note": wrote_note, "titles": done})
    return {"ok": True, "note": wrote_note, "titles": done, "problems": problems, "savedAt": now_iso()}


def hubspot_save(body):
    """POST /api/hubspot/save. Without confirm: only the plan, nothing is written. With confirm: true: write exactly that plan."""
    if not hubspot_token():
        return 409, {"error": "HubSpot isn't connected. See Settings > Setup guides > Connect HubSpot."}
    if not token_info():
        return 409, {"error": "Connect Google Calendar first, so Overture knows the call."}
    try:
        c = clean_hubspot_save(body)
        records = load_records()
        live, crm = live_now(records)
        err = crm_status()["hubspot"]["lastError"]
        if err:  # HubSpot failed (or is paused after a failure): say so, not "no company"
            return 502, {"error": err}
        plan = hubspot_plan(c, live, crm, records)
        if c["confirm"] and not plan["note"] and not plan["titleChanges"]:
            raise Invalid("Nothing to save yet: write call notes or tick a title change.")
    except Invalid as e:
        return 400, {"error": str(e)}
    except (GoogleError, NotConnected):
        return 502, {"error": "Google Calendar didn't answer, so Overture can't check the call. Try again."}
    if not c["confirm"]:
        return 200, {"ok": True, "plan": public_plan(plan)}
    if c["planId"] != plan_id(plan):  # HubSpot (or the last save) changed since the preview: show the new one first
        return 409, {"error": "HubSpot changed since the preview. Check it again, then save."}
    try:
        return 200, hubspot_write(plan, c["callId"])
    except MaybeSaved as e:
        return 502, {"error": str(e)}
    except ApiError as e:
        crm_note("hubspot", False, str(e))
        return 502, {"error": "Not saved to HubSpot: " + str(e)}


# ---------------------------------------------------------------- people mentioned on the call ----------------------------------------------------------------
# After a call, Overture finds the people who were talked about (not the guests) in a transcript you drop or paste in (Zoom or
# Google Meet .vtt, .srt or .txt), in your own call notes, or (only with "Read Gong transcripts" on) in Gong's transcript.
# The owner's rules, enforced here:
# - The transcript is read in memory and dropped. Only each mention and one sentence (with speaker and time) are saved.
# - Mentions are found here with plain rules (and in the browser with Chrome's on-device AI, when it has it). No outside service.
# - People Overture already knows (calendar, records, HubSpot) show at once. Anyone else is looked up on the web by the research
#   worker, with the same blocked sites and rules: Claude gets the name (or first name), the role or team words, the company
#   name and its domain. Never the transcript, never the quote.
# - A partial mention ("Maria from security") comes back as up to 3 candidates to pick from. Overture never picks for you.
# - Nothing from a transcript reaches Claude's answers unless "Use transcripts in AI answers" is on (Data page, off by default).

MAX_TRANSCRIPT_CHARS = 1_000_000   # about 1 MB of text: a 3-hour call is well under it
MAX_TRANSCRIPT_LINES = 20_000
MAX_MENTION_BODY = 2_500_000       # bytes of JSON for POST /api/mentions (the text, escaped)
MAX_MENTIONS = 60                  # per call
MAX_MENTION_CALLS = 300
TRANSCRIPT_EXTS = (".vtt", ".srt", ".txt")
QUOTE_CHARS = 240
GONG_MATCH_HOURS = 3               # a Gong recording within 3 hours of the calendar call is that call
CONTACT_TO_COMPANY = 279           # HubSpot's default "contact to company" association type id (associations docs)
MENTION_SOURCES = {"upload": "your transcript", "paste": "the pasted transcript", "notes": "your call notes", "gong": "Gong's transcript",
                   "live": "your notes during the call", "meetily": "Meetily's live transcript", "granola": "Granola's transcript",
                   "captions": "Google Meet's captions"}
POST_SOURCES = ("upload", "paste", "notes", "gong", "captions")  # what POST /api/mentions takes; live, Meetily and Granola come from the server itself

_TS = r"(?:\d{1,2}:)?\d{1,2}:\d{2}(?:[.,]\d{1,3})?"
CUE_RE = re.compile(r"^\s*(" + _TS + r")\s*-->\s*(" + _TS + r")")
STAMP_LINE_RE = re.compile(r"^\s*[\[(]?(" + _TS + r")[\])]?\s*$")
ZOOM_HEAD_RE = re.compile(r"^\s*\[([^\[\]]{1,80})\]\s+(" + _TS + r")\s*$")                  # [Chris Park] 10:02:33
NAME_STAMP_RE = re.compile(r"^\s*([A-Z][\w.'’-]*(?:\s+[A-Z][\w.'’-]*){0,3})\s+[\[(]?(" + _TS + r")[\])]?\s*$")  # Chris Park  00:01:02
STAMP_SPEAKER_RE = re.compile(r"^\s*[\[(]?(" + _TS + r")[\])]?\s+(?:From\s+)?([^:]{1,80}?)(?:\s+to\s+[^:]{1,60})?\s*:\s+(.+)$")
SPEAKER_RE = re.compile(r"^\s*([A-Z][\w.'’-]*(?:\s+[A-Z][\w.'’-]*){0,3}|Speaker\s*\d+)\s*:\s+(.+)$")
VOICE_RE = re.compile(r"<v(?:\.[^\s>]*)?\s+([^>]{1,80})>")
TAG_RE = re.compile(r"</?[a-zA-Z][^>]{0,80}>")
NOT_SPEAKERS = {"note", "notes", "action", "action items", "next steps", "summary", "agenda", "todo", "q", "a", "re", "subject", "transcript", "webvtt"}


def _clock(ts):
    """"00:01:02.500" -> "1:02", "01:02:03" -> "1:02:03"."""
    try:
        nums = [int(x) for x in re.sub(r"[.,]\d+$", "", ts).split(":")]
    except ValueError:
        return ""
    h, m, s = ([0] + nums)[-3:] if len(nums) < 3 else nums[:3]
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _ms_clock(ms):
    n = _num(ms)
    if n is None or n < 0:
        return ""
    s = int(n // 1000)
    return _clock(f"{s // 3600}:{s // 60 % 60}:{s % 60}")


def transcript_text_ok(text):
    """True for real text: no NUL bytes and almost no control or replacement characters (a binary file read as text has many)."""
    if not isinstance(text, str) or "\x00" in text:
        return False
    sample = text[:200_000]
    bad = sum(1 for ch in sample if (ord(ch) < 32 and ch not in "\t\n\r\f") or ch == "�")
    return bad <= max(5, len(sample) // 200)


def parse_transcript(text):
    """A Zoom or Google Meet transcript (.vtt, .srt or .txt) -> [{"speaker", "time", "text"}]. Speakers and times when it has them."""
    t = str(text or "").lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    rows = t.split("\n")
    out = []

    def add(speaker, time_, txt):
        txt = " ".join(TAG_RE.sub(" ", txt).split())
        if not txt or len(out) >= MAX_TRANSCRIPT_LINES:
            return
        speaker = clean_text(speaker, 80)
        last = out[-1] if out else None
        # cues cut sentences in two: join a cue to the last one when the same person is still mid-sentence
        if last and last["speaker"] == speaker and not re.search(r"[.!?…]['\"”’)]*$", last["text"]) and len(last["text"]) < 1500:
            last["text"] = (last["text"] + " " + txt)[:4000]
            return
        out.append({"speaker": speaker, "time": time_, "text": txt[:4000]})

    def speaker_split(line):
        m = SPEAKER_RE.match(line)
        if m and m.group(1).strip().lower() not in NOT_SPEAKERS:
            return m.group(1).strip(), m.group(2)
        return None, line

    cues = any(CUE_RE.match(r) for r in rows[:200]) or rows[0].strip().upper().startswith("WEBVTT")
    if cues:  # .vtt or .srt
        time_, in_cue, skip = "", False, False
        for i, raw in enumerate(rows):
            line = raw.strip()
            if line.isdigit() and i + 1 < len(rows) and CUE_RE.match(rows[i + 1]):
                continue  # the next cue's number (some files leave out the blank line)
            if not line:
                in_cue, skip = False, False
                continue
            m = CUE_RE.match(line)
            if m:
                time_, in_cue, skip = _clock(m.group(1)), True, False
                continue
            if not in_cue:
                skip = skip or line.upper().startswith(("WEBVTT", "NOTE", "STYLE", "REGION"))
                continue  # a cue number, the header, a NOTE block
            if skip:
                continue
            v = VOICE_RE.search(line)
            if v:
                add(v.group(1).strip(), time_, VOICE_RE.sub(" ", line))
                continue
            spk, rest = speaker_split(line)
            add(spk or "", time_, rest)
        return out
    speaker, time_ = "", ""
    for raw in rows:  # .txt: "Name: text", "[Name] 10:02:33" then text, "00:01:02" lines, or chat "10:02:33 From Name to Everyone: text"
        line = raw.strip()
        if not line:
            continue
        m = ZOOM_HEAD_RE.match(line)
        if m:
            speaker, time_ = m.group(1).strip(), _clock(m.group(2))
            continue
        m = STAMP_LINE_RE.match(line)
        if m:
            time_ = _clock(m.group(1))
            continue
        m = NAME_STAMP_RE.match(line)
        if m:
            speaker, time_ = m.group(1).strip(), _clock(m.group(2))
            continue
        m = STAMP_SPEAKER_RE.match(line)
        if m and m.group(2).strip().lower() not in NOT_SPEAKERS:
            time_, speaker = _clock(m.group(1)), m.group(2).strip()
            add(speaker, time_, m.group(3))
            continue
        spk, rest = speaker_split(line)
        if spk:
            speaker = spk
        add(speaker, time_, rest)
    return out


# ---- finding mentions (local rules only) ----

NAME_WORD = r"[A-Z][a-z]+(?:[-'’][A-Z]?[a-z]+)?"
PARTICLE = r"(?:van|von|de|da|del|della|di|du|la|le|der|den|bin|al)"
FULL_NAME_RE = re.compile(r"\b(" + NAME_WORD + r"(?:\s+(?:" + PARTICLE + r"\s+)?" + NAME_WORD + r"){1,3})\b")
SINGLE_NAME_RE = re.compile(r"\b(" + NAME_WORD + r")\b")
TEAM_WORDS = ["security", "platform", "platform engineering", "procurement", "legal", "finance", "it", "infra", "infrastructure", "devops",
              "sre", "data", "product", "engineering", "design", "sales", "marketing", "ops", "operations", "hr", "people ops", "compliance",
              "risk", "privacy", "architecture", "developer experience", "devex", "developer productivity", "cloud", "networking", "support",
              "partnerships", "purchasing", "infosec", "information security", "it security", "tooling", "reliability", "qa", "growth",
              "analytics", "payments", "mobile", "frontend", "backend", "ai", "ml", "leadership", "vendor management", "accounting", "research",
              "product management", "product managing", "program management", "program managing", "project management", "project managing",
              "customer success", "solutions engineering", "sales engineering", "revenue operations", "developer relations", "recruiting",
              "business development", "eng", "bizdev", "secops", "revops", "devrel"]
# Short team names that are also everyday words in lower case ("in the pm" is the afternoon): only in capitals.
TEAM_CAPS = ["PM", "CS", "BD"]
# How people say a team -> the team's usual name ("John from product managing" is John in product management).
TEAM_NORMAL = {"product managing": "product management", "program managing": "program management", "project managing": "project management",
               "PM": "product management", "eng": "engineering", "CS": "customer success", "BD": "business development",
               "bizdev": "business development", "devrel": "developer relations"}
TEAM = ("(?:(?i:" + "|".join(re.escape(w).replace(r"\ ", r"\s+") for w in sorted(TEAM_WORDS, key=len, reverse=True)) + ")|"
        + "|".join(TEAM_CAPS) + ")")
_CAPS = r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?"
ROLE = (r"(?:(?:C[EFIMOPRST]O|CISO|CDO|CAIO|S?VP|EVP)(?:,?\s+(?:of\s+)?(?:" + TEAM + r"|" + _CAPS + r"))?"
        r"|(?i:vice\s+president|head|director|chief\s+[a-z]+\s+officer|general\s+manager)\s+(?i:of)\s+(?:" + TEAM + r"|" + _CAPS + r")"
        r"|" + TEAM + r"\s+(?i:lead|leader|director|manager|head|architect|owner)"
        r")")
DET = r"(?i:(our|their|the|your))"
NEWISH = r"(?:(?i:new|current|incoming|interim|acting)\s+)?"
FIRST = r"(" + NAME_WORD + r")"
ROLE_ONLY_RE = re.compile(r"\b" + DET + r"\s+" + NEWISH + r"(" + ROLE + r")\b")
FROM_RE = re.compile(r"\b" + FIRST + r"\s+(?:from|in|on|at|over\s+in)\s+(?:" + DET + r"\s+)?(" + TEAM + r"|" + r"[A-Z][\w&.-]*(?:\s+[A-Z][\w&.-]*)?" + r")"
                     r"(?:\s+(?i:team|group|org|department))?\b")
APPOS_RE = re.compile(r"\b" + FIRST + r",?\s+" + DET + r"\s+" + NEWISH + r"(" + ROLE + r")\b")
# "talk with John about that from product managing": a first name and its team with a few small words between them
# (lower-case words only, so the gap never runs across another name). Only after a word for getting in touch ("talk with",
# "ask", "loop in"...), so "Most of the pushback is from legal" is not a person called Most.
CONTACT = (r"(?i:\b(?:talk(?:s|ed|ing)?|speak(?:s|ing)?|spoke|chat(?:s|ted|ting)?|meet(?:s|ing)?|met|sync(?:s|ed|ing)?(?:\s+up)?|"
           r"check(?:s|ed|ing)?\s+in|follow(?:s|ed|ing)?\s+up|catch(?:es|ing)?\s+up|caught\s+up|loop(?:s|ed|ing)?\s+in|ping(?:s|ed|ing)?|"
           r"ask(?:s|ed|ing)?|email(?:s|ed|ing)?|call(?:s|ed|ing)?|tell(?:s|ing)?|told|cc|bring(?:s|ing)?\s+in|brought\s+in|"
           r"introduc(?:e|es|ed|ing)|reach(?:es|ed|ing)?\s+out\s+to|hear(?:d)?\s+(?:back\s+)?from|connect(?:s|ed|ing)?|"
           r"nudg(?:e|es|ed|ing)|invit(?:e|es|ed|ing))\s+(?:with\s+|to\s+|in\s+)?)")
GAP_RE = re.compile(CONTACT + FIRST + r"((?:,?\s+[a-z][a-z'’-]*){1,6}?),?\s+(?:from|in|on|over\s+in)\s+(?:" + DET + r"\s+)?(" + TEAM + r")"
                    r"(?:\s+(?i:team|group|org|department|side))?\b")
WHO_RE = re.compile(r"\b" + FIRST + r"\s+(?i:who|that)\s+(?i:runs|leads|heads|owns|manages|looks\s+after|is\s+in\s+charge\s+of)\s+(?:" + DET + r"\s+)?(" + TEAM + r")\b")
ROLE_NAME_RE = re.compile(r"\b" + DET + r"\s+" + NEWISH + r"(" + ROLE + r"),?\s+" + FIRST + r"\b")
ROLE_OR_TEAM_RE = re.compile(r"(?:" + DET + r"\s+)?" + NEWISH + r"(?:" + ROLE + r"|" + TEAM + r")(?:\s+(?i:team|group|org|department))?")
SENTENCE_RE = re.compile(r"[^.!?…]+(?:[.!?…]+|$)")
# Internal codenames ("Project Falcon", "the Falcon project", "codename Falcon Labs") never leave this PC. "program management"
# and the like are teams, not codenames.
CODE_WORD = r"(?:project|operation|initiative|program(?:me)?|code\s?name|workstream)"
CODENAME_RE = re.compile(r"(?i)\b" + CODE_WORD + r"\b(?!\s+(?:management|managing|managers?|office|team|teams)\b)")
CODE_BEFORE_RE = re.compile(r"(?i)\b" + CODE_WORD + r"[\s:\"“'‘]*$")       # "Project " / "codename " right before a name
CODE_AFTER_RE = re.compile(r"\s+(?i:project|initiative|program(?:me)?|workstream)\b")  # " project" right after one
TEAM_AFTER_RE = re.compile(r"\s+(?i:team|group|squad|pod|tribe)\b")              # "the Falcon team": a team's own name

# Words that start sentences, greet, or name days and months: never a person's first word.
STARTWORDS = set("""i we you they he she it the a an and but so or if when then thanks thank hi hey hello yes yeah yep no nope okay ok sure great
good right well also just maybe our their your my his her this that these those what who how why where let lets let's please sorry actually
absolutely next last first second monday tuesday wednesday thursday friday saturday sunday january february march april may june july august
september october november december mr mrs ms dr prof sir madam team everyone guys folks all both anyway honestly totally exactly cool awesome
perfect nice wow oh um uh hmm alright today tomorrow yesterday there here now once after before since until while because though although
meanwhile per via re fyi cc bcc eod eow asap q1 q2 q3 q4 do does did can could would should will shall might must is are was were be been
happy hope sounds love looks feels seems someone somebody anyone anybody everybody nobody people updates update feedback
approval input questions question help pushback emails email calls call messages message notes note signoff news requests request
concerns interest budget pricing security legal procurement finance later earlier finally again however otherwise basically really
definitely probably certainly obviously clearly hopefully unfortunately fortunately luckily apparently instead overall separately ideally
personally initially originally eventually plus ask asked asking ping tell loop invite introduce intro meet send get need needs thank talk
check follow remind reach contact schedule book add include sync nudge want wants make have give bring keep set""".split())
# Products, tools, companies and places the calls are about: never a person.
NONPERSON = set("""spotify backstage portal confidence xirp claude codex anthropic openai chatgpt gpt github gitlab bitbucket google meet zoom
slack teams microsoft jira confluence atlassian notion aws amazon azure gcp kubernetes k8s docker terraform datadog pagerduty servicenow workday
okta salesforce hubspot gong linkedin apple android ios windows linux mac port roadie cortex opslevel launchdarkly statsig optimizely sso saml
oauth api apis sdk cli ui ux soc iso gdpr hipaa pci rfp rfi msa nda sow poc pilot demo deck slides doc docs sheet sheets drive docusign
new san los las north south east west united york francisco angeles america europe asia canada london toronto berlin paris amsterdam
stockholm inc llc ltd corp group plc gmbh co company plugin plugins catalog techdocs scaffolder search insights soundcheck rbac
project projects operation initiative program programme migration rollout launch release phase sprint roadmap workstream codename
labs systems technologies solutions services software studio code capital partners ventures holdings bank university institute foundation
christmas bowl learning management""".split())
ROLE_WORDS = set("""ceo cto cio cfo coo cpo cmo cro ciso cdo vp svp evp head director manager lead leader chief president officer founder
cofounder co-founder architect engineer engineering staff principal senior junior intern partner board investor advisor counsel""".split())
TEAM_SET = {w for t in TEAM_WORDS for w in t.split()}


def _sentences(text):
    for m in SENTENCE_RE.finditer(text):
        s = m.group(0)
        if s.strip():
            yield m.start(), s


def quote_for(sentence, start, end):
    """The sentence the mention is in, cut to about QUOTE_CHARS around the name."""
    s = " ".join(sentence.split())
    if len(s) <= QUOTE_CHARS:
        return s
    a = max(0, start - 100)
    b = min(len(sentence), a + QUOTE_CHARS - 2)
    return ("…" if a else "") + " ".join(sentence[a:b].split()) + ("…" if b < len(sentence) else "")


def _bad_word(w, ctx):
    lw = w.lower().strip("'’")
    return lw in NONPERSON or lw in ROLE_WORDS or lw in TEAM_SET or lw in ctx["companyWords"]


def _refers_to_us(det, speaker, ctx):
    """"our" from you, or "your" from one of their people, means your own company: not someone to look up."""
    det, sp = str(det or "").lower(), norm_name(speaker)
    mine = bool(sp) and (sp in ctx["me"] or sp.split()[0] in ctx["meFirst"] or sp in ("your note", "your notes"))  # app.js's speakers for your notes
    if det == "our" and mine:
        return True
    return det == "your" and sp and (sp in ctx["attendees"] or sp.split()[0] in ctx["attendeeFirst"])


def _role_text(role):
    r = " ".join(str(role or "").split())[:80]
    for said, name in TEAM_NORMAL.items():
        r = re.sub(r"(?i)\b" + said + r"\b", name, r)
    return r


def _role_tokens(role):
    return {w for w in re.findall(r"[a-z]+", str(role).lower()) if w not in {"of", "the", "and", "for", "new"}}


def _title_matches(role, title):
    want, have = _role_tokens(role), _role_tokens(title)
    if not want or not have:
        return False
    abbr = {"vp": {"vice", "president"}, "cto": {"technology"}, "ciso": {"security"}, "cfo": {"finance", "financial"}, "ceo": {"executive"}}
    for k, v in abbr.items():  # "VP of Platform" matches "Vice President, Platform"
        if k in want and (v & have):
            want = (want - {k}) | (v & have)
        if k in have and (v & want):
            have = (have - {k}) | (v & want)
    return want <= have


def mention_context(events, me, records, call_id, now=None, hs_contacts=None):
    """What extraction needs about one call: its company, guests, you, and the people Overture already knows there. None if the call isn't found."""
    now = now or datetime.now(timezone.utc)
    me_email = str((me or {}).get("email", "")).lower()
    inv = next((i for i in upcoming_invites(events, me_email, records, now) if i["id"] == call_id), None)
    if not inv:  # a call that already happened
        for ev in events:
            if safe_id(ev.get("id")) == call_id:
                inv = event_to_invite(ev, me_email, records) or inv
    if not inv:
        return None
    domain, company = inv.get("domain") or "", inv.get("company") or ""
    rec_people = records.get("people") or {}
    met, display = {}, {}
    for ev in events:
        start, end = _event_times(ev)
        for a in ev.get("attendees") or []:
            dn, em = str(a.get("displayName") or "").strip(), str(a.get("email", "")).strip().lower()
            if dn and em:
                display[em] = dn
        if ev.get("status") == "cancelled" or not start or end > now:
            continue
        for a in _others(ev, me_email):
            n = norm_name(a["name"])
            if n not in met or met[n] < start:
                met[n] = start
    att_names = {norm_name(a["name"]) for a in inv["attendees"]}
    me_names = {norm_name(x) for x in ((me or {}).get("name", ""), "Chris") if x}
    known = {}

    def put(name, **info):
        n = norm_name(name)
        if len(n.split()) < 2 or n in att_names or n in me_names:
            return
        k = known.setdefault(n, {"name": " ".join(str(name).split()), "title": "", "team": "", "relationship": "", "sources": [], "from": info.get("from", "")})
        for f in ("title", "team", "relationship"):
            if info.get(f) and not k[f]:
                k[f] = info[f]
        if info.get("sources") and not k["sources"]:
            k["sources"] = info["sources"]

    if domain:
        for (em, dn) in display.items():  # your calendar: anyone from this company in the last 6 months or next 2 weeks
            d = domain_of(em)
            if d and same_org(d, domain, records) and personish({"name": dn, "email": em}):
                r = rec_people.get(em) or {}
                put(dn, title=str(r.get("title") or ""), team=str(r.get("team") or ""), relationship=str(r.get("relationship") or ""),
                    **{"from": "Overture records" if r.get("title") else "Your calendar"})
        for c in hs_contacts or []:
            put(c.get("name", ""), title=c.get("title", ""), **{"from": "HubSpot"})
        for k, p in (records.get("knownPeople") or {}).items():
            if isinstance(p, dict) and p.get("domain") and same_org(str(p["domain"]), domain, records):
                put(p.get("name", ""), title=p.get("title", ""), team=p.get("team", ""), relationship=p.get("relationship", ""),
                    sources=p.get("sources") or [], **{"from": "Overture records"})
    titles = []
    for a in inv["attendees"]:
        t = str((rec_people.get(a["email"]) or {}).get("title") or "")
        t = t or next((c.get("title", "") for c in hs_contacts or [] if c.get("email") == a["email"]), "")
        if t:
            titles.append(t)
    co_words = {w for w in re.findall(r"[a-z0-9]+", (norm_org(company) + " " + name_from_domain(domain)).lower()) if len(w) > 2}
    return {
        "invite": inv, "company": company, "domain": domain, "companyWords": co_words,
        "attendees": att_names, "attendeeFirst": {n.split()[0] for n in att_names if n},
        "attendeeTitles": titles, "me": me_names, "meFirst": {n.split()[0] for n in me_names if n},
        "known": list(known.values()), "met": met,
    }


def extract_mentions(lines, ctx, hints=None):
    """Lines of a transcript -> the people talked about (not the guests, not you), each with one quote. Plain rules, nothing sent anywhere."""
    known_full = {norm_name(k["name"]): k for k in ctx["known"]}
    known_first = {}
    for k in ctx["known"]:
        known_first.setdefault(norm_name(k["name"]).split()[0], []).append(k)
    found = {}
    cur = {"si": -1}  # which sentence of the whole transcript we're in (for the follow-up that may explain a relation)

    def note(key, name, role, kind, line, sent, a, b):
        it = found.get(key)
        if it:
            it["count"] += 1
            if role and not it["role"]:
                it["role"] = role
            return
        if len(found) >= MAX_MENTIONS:
            return
        found[key] = {"key": key, "name": name, "role": role, "kind": kind, "count": 1, "si": cur["si"],
                      "quote": {"text": quote_for(sent, a, b), "speaker": clean_text(line.get("speaker"), 80), "time": clean_text(line.get("time"), 12)}}

    def ok_first(w):
        lw = w.lower()
        return lw not in STARTWORDS and not _bad_word(w, ctx) and lw not in ctx["attendeeFirst"] and lw not in ctx["meFirst"]

    def full_name(words, line, sent, a, b):
        while words and words[0].lower() in STARTWORDS:
            words = words[1:]
        while words and (words[-1].lower() in STARTWORDS or _bad_word(words[-1], ctx)):
            words = words[:-1]
        if len(words) < 2:
            return False
        if any(_bad_word(w, ctx) for w in words) or words[0].lower() in STARTWORDS:
            return True  # a product, team or company name: handled, not a person
        name = " ".join(words)
        n = norm_name(name)
        if n in ctx["attendees"] or n in ctx["me"]:
            return True
        note("n:" + n, name, "", "known" if n in known_full else "full", line, sent, a, b)
        return True

    for line in lines:
        text = str(line.get("text") or "")
        for off, sent in _sentences(text):
            cur["si"] += 1
            spk = line.get("speaker") or ""
            taken = []  # (start, end, key): spans already used, so one name isn't counted twice
            for m in FULL_NAME_RE.finditer(sent):
                before = set(found)
                if full_name(m.group(1).split(), line, sent, m.start(), m.end()):
                    keys = [k for k in found if k not in before] or [k for k in found if k == "n:" + norm_name(m.group(1))]
                    taken.append((m.start(), m.end(), keys[0] if keys else ""))
            for rx, fi, di, ri in ((APPOS_RE, 1, 2, 3), (WHO_RE, 1, 2, 3), (FROM_RE, 1, 2, 3), (GAP_RE, 1, 3, 4), (ROLE_NAME_RE, 3, 1, 2)):
                for m in rx.finditer(sent):
                    first, det, role = m.group(fi), m.group(di), _role_text(m.group(ri))
                    # "Maria, the director of Project Falcon", "Maria on the Falcon project": a codename, never sent anywhere
                    code = bool(CODENAME_RE.search(role) or CODE_AFTER_RE.match(sent, m.end(ri)))
                    inside = next((t for t in taken if t[0] <= m.start(fi) < t[1]), None)
                    if inside:  # "our new CTO, Maria Gomez": the full name already counted; keep the role with it
                        if (not code and inside[2] in found and not found[inside[2]]["role"] and (rx is not FROM_RE or re.fullmatch(TEAM, role))
                                and not _refers_to_us(det, spk, ctx)):
                            found[inside[2]]["role"] = role
                        taken.append((m.start(), m.end(), inside[2]))
                        continue
                    if code or not ok_first(first) or _refers_to_us(det, spk, ctx):
                        continue
                    if rx is FROM_RE and not re.fullmatch(TEAM, role):
                        if any(w.lower() in NONPERSON or w.lower() in STARTWORDS for w in role.split()):
                            continue  # "Maria from Spotify": one of yours. "Tom on Monday": a day, not a team
                        if TEAM_AFTER_RE.match(sent, m.end(3)) and role not in (ctx.get("orgs") or {}):
                            role = ""  # "Maria from the Falcon team": a team's own name, not a company, so it isn't sent
                        else:
                            role = "" if any(w.lower() in ctx["companyWords"] for w in role.split()) else "at " + role
                            if sent[m.end(3):m.end(3) + 1] not in ("'", "’"):  # "Sarah at Goldman Sachs": the company isn't a person too
                                for s, e, k in taken:                       # (but "Tom from Jordan Lee's team" keeps Jordan Lee)
                                    if m.start(3) <= s < m.end(3) and k.startswith("n:") and k in found and found[k]["kind"] == "full" and found[k]["count"] == 1:
                                        del found[k]
                    key = "p:" + first.lower() + "|" + role.lower()
                    taken.append((m.start(), m.end(), key))
                    note(key, first, role, "partial", line, sent, m.start(), m.end())
            for m in ROLE_ONLY_RE.finditer(sent):
                det, role = m.group(1), _role_text(m.group(2))
                if any(s <= m.start(2) < e or s <= m.end(2) - 1 < e for s, e, _ in taken) or _refers_to_us(det, spk, ctx):
                    continue
                if any(_title_matches(role, t) for t in ctx["attendeeTitles"]):
                    continue  # that's someone on the call
                note("r:" + role.lower(), "", role, "role", line, sent, m.start(), m.end())
            for m in SINGLE_NAME_RE.finditer(sent):  # a first name alone counts only when Overture knows one person by it there
                w = m.group(1)
                if any(s <= m.start() < e for s, e, _ in taken) or len(known_first.get(w.lower(), [])) != 1 or not ok_first(w):
                    continue
                full = known_first[w.lower()][0]
                if ("n:" + norm_name(full["name"])) in found:
                    found["n:" + norm_name(full["name"])]["count"] += 1
                    continue
                note("p:" + w.lower() + "|", w, "", "partial", line, sent, m.start(), m.end())
    cur["si"] = None  # hints: no follow-up sentence is read for them
    for h in hints or []:  # Chrome's on-device AI suggestions: kept only when the name is really in the transcript
        name, role = " ".join(str(h.get("name") or "").split()), _role_text(h.get("role"))
        if not re.fullmatch(NAME_WORD + r"(?:\s+(?:" + PARTICLE + r"\s+)?" + NAME_WORD + r"){0,3}", name):
            continue
        rx = re.compile(r"\b" + re.escape(name) + r"\b")
        for line in lines:
            hit = next(((sent, m) for _, sent in _sentences(str(line.get("text") or "")) for m in [rx.search(sent)] if m), None)
            if not hit:
                continue
            sent, m = hit
            if role and (role.lower() not in sent.lower() or not ROLE_OR_TEAM_RE.fullmatch(role) or CODENAME_RE.search(role)):
                role = ""  # only role or team words the sentence really says: never free text, never a codename
            words = name.split()
            if len(words) >= 2:
                full_name(words, line, sent, m.start(), m.end())
            elif ok_first(name) and not any(k.startswith("n:" + name.lower() + " ") for k in found):
                note("p:" + name.lower() + "|" + role.lower(), name, role, "partial", line, sent, m.start(), m.end())
            break
    # "Maria Gomez ... Maria from security": one person
    for k in [k for k in found if k.startswith("p:")]:
        first = found[k]["name"].lower()
        fulls = [f for f in found if f.startswith("n:" + first + " ")]
        if len(fulls) == 1:
            f = found[fulls[0]]
            f["count"] += found[k]["count"]
            f["role"] = f["role"] or found[k]["role"]
            del found[k]
    out = []
    for it in found.values():
        if it["kind"] == "known":
            it["known"] = known_full[norm_name(it["name"])]
        elif it["kind"] == "partial":
            it["candidates"] = list(known_first.get(it["name"].lower(), []))[:3]
        elif it["kind"] == "role":
            it["candidates"] = [k for k in ctx["known"] if k.get("title") and _title_matches(it["role"], k["title"])][:3]
        out.append(it)
    return out


# ---- companies mentioned on the call, and what the call itself says about a relation (local rules only) ----
# A company is picked up when Overture knows the name (the public Backstage adopters list, well-known vendors, Overture records, your
# calendar's companies, HubSpot companies it has already read), when a strong cue comes before it ("switched from", "moving to",
# "partnered with", "acquired by", "over at"...), when it ends in a company word (Inc, Labs, Systems, AI...), or when it is said
# with a possessive and a product word ("Brightwave's pricing"). The call's own company, Spotify, its products, places, days,
# team words and codenames ("Project Falcon") are never companies.

ORG_WORD = r"[A-Z][A-Za-z0-9&-]*(?:\.(?:com|io|ai|co|net|org|dev))?"
ORG_NAME = ORG_WORD + r"(?:\s+" + ORG_WORD + r"){0,2}"
ORG_SUFFIX = r"(?:Inc|Labs|Corp|Corporation|Ltd|LLC|GmbH|Technologies|Technology|Systems|AI|Software|Networks|Analytics|Holdings)"
ORG_SUFFIX_RE = re.compile(r"(?<![\w.])(" + ORG_WORD + r"(?:\s+" + ORG_WORD + r"){0,2}?\s+" + ORG_SUFFIX + r")(?![\w])")
ORG_CUE_RE = re.compile(r"\b(?i:switched\s+(?:away\s+|over\s+)?(?:from|to)|moving\s+(?:over\s+)?to|moved\s+(?:over\s+)?(?:to|off)|"
                        r"migrat(?:ing|ed)\s+(?:away\s+)?(?:to|from|off)|partner(?:ed|ing)\s+with|acquired\s+by|bought\s+by|owned\s+by|"
                        r"over\s+at|compet(?:e|es|ing)\s+with|signed\s+with|(?:we|they)\s+(?:use|used|run|ran)|"
                        r"(?:we|they)(?:'re|’re|\s+are)\s+(?:using|on))\s+(" + ORG_NAME + r")(?!['’]s\s+(?i:team|group|org|people))")
ORG_POSS_RE = re.compile(r"(?<![\w.])(" + ORG_NAME + r")['’]s\s+(?i:product|platform|pricing|offering|stack|software|api|tool|tools|contract|deal|sales\s+team|renewal)\b")
CODENAME_WORDS = {"project", "projects", "operation", "initiative", "program", "programme", "codename", "code", "workstream", "phase", "team"}
# Spotify, its products, call words and things that are never a company
NOT_ORG = set("""spotify backstage portal confidence xirp soundcheck techdocs scaffolder catalog plugin plugins insights rbac sso saml oauth
api apis sdk cli ui ux soc iso gdpr hipaa pci rfp rfi msa nda sow poc pilot demo deck slides doc docs sheet sheets drive meet zoom teams
q1 q2 q3 q4 eod eow kubernetes k8s migration rollout launch release sprint roadmap christmas bowl learning management the our their your new old next last this that these those monday tuesday wednesday thursday friday saturday sunday january
february march april may june july august september october november december ga beta alpha prod production staging stage preview uat dev test
gen generative agentic conversational""".split())
PLACES = set("""alabama alaska arizona arkansas california colorado connecticut delaware florida georgia hawaii idaho illinois indiana iowa
kansas kentucky louisiana maine maryland massachusetts michigan minnesota mississippi missouri montana nebraska nevada hampshire jersey
mexico york carolina dakota ohio oklahoma oregon pennsylvania rhode tennessee texas utah vermont virginia washington wisconsin wyoming
canada usa us uk england scotland ireland wales france germany spain portugal italy netherlands belgium sweden norway denmark finland
poland austria switzerland india china japan korea singapore australia brazil argentina chile colombia peru israel dubai europe asia
africa america london paris berlin amsterdam stockholm toronto vancouver montreal chicago boston seattle austin denver atlanta dallas
houston miami phoenix portland francisco angeles diego jose vegas brooklyn manhattan dublin madrid barcelona lisbon munich zurich tokyo
sydney melbourne bangalore mumbai delhi remote office home downtown""".split())
# Well-known vendors in this space (names people say on calls) and their websites.
KNOWN_VENDORS = {"Datadog": "datadoghq.com", "PagerDuty": "pagerduty.com", "GitHub": "github.com", "GitLab": "gitlab.com", "Atlassian": "atlassian.com",
                 "Okta": "okta.com", "Salesforce": "salesforce.com", "ServiceNow": "servicenow.com", "Workday": "workday.com", "Microsoft": "microsoft.com",
                 "Google": "google.com", "Amazon": "amazon.com", "AWS": "aws.amazon.com", "Roadie": "roadie.io", "Cortex": "cortex.io", "OpsLevel": "opslevel.com",
                 "Port": "getport.io", "LaunchDarkly": "launchdarkly.com", "Statsig": "statsig.com", "Optimizely": "optimizely.com", "HashiCorp": "hashicorp.com",
                 "Docker": "docker.com", "Snowflake": "snowflake.com", "Databricks": "databricks.com", "Splunk": "splunk.com", "New Relic": "newrelic.com",
                 "Grafana Labs": "grafana.com", "Snyk": "snyk.io", "Sonatype": "sonatype.com", "Anthropic": "anthropic.com", "OpenAI": "openai.com",
                 "Cloudflare": "cloudflare.com", "Twilio": "twilio.com", "Stripe": "stripe.com", "Harness": "harness.io", "CircleCI": "circleci.com",
                 "JFrog": "jfrog.com", "Elastic": "elastic.co", "MongoDB": "mongodb.com", "Confluent": "confluent.io", "Vercel": "vercel.com",
                 "Netlify": "netlify.com", "Humanitec": "humanitec.com", "Configure8": "configure8.io", "Compass": "atlassian.com", "IBM": "ibm.com",
                 "Oracle": "oracle.com", "SAP": "sap.com", "Accenture": "accenture.com", "Deloitte": "deloitte.com", "Thoughtworks": "thoughtworks.com"}
# Adopters-list names that are also everyday words: only counted with a cue or a company word, never on their own.
COMMON_ORG_WORDS = {"okay", "peak", "box", "stone", "next", "niche", "loft", "unity", "lunar", "via", "six", "rei", "porto", "isaac", "prisma",
                    "plata", "globo", "vr", "b3", "nos", "ndustrial", "inventa", "operate first", "shipshape", "frontside", "wise", "gusto"}
# Known names that are also English words: as a sentence's first word ("Port forwarding broke", "Harness the momentum") they
# count only when a verb follows ("Port is a competitor"). Elsewhere in a sentence they count as usual ("we looked at Port").
AMBIGUOUS_KNOWN = {"grab", "spread", "port", "harness", "elastic", "compass", "gelato", "cortex", "lightspeed", "tui"}
AMBIGUOUS_OK_NEXT = {"is", "are", "was", "were", "has", "have", "had", "and", "or", "also", "just", "said", "says", "told", "called", "emailed",
                     "uses", "used", "offers", "sells", "wants", "will", "would", "can", "could", "does", "did", "acquired", "bought", "raised"}
ORG_SUFFIX_WORDS = {"se", "group", "inc", "inc.", "ltd", "ltd.", "limited", "gmbh", "ab", "retail", "international", "plc", "corp", "llc"}
ORG_RELATIONS = {"customer": "Customer", "vendor": "Vendor or supplier", "partner": "Partner", "competitor": "Competitor", "parent": "Parent company",
                 "subsidiary": "Subsidiary", "investor": "Investor", "acquired": "They acquired it", "acquirer": "It acquired them",
                 "uses_product": "Uses its product", "other": "Other", "unknown": "Unknown"}
WAIT_SECONDS = 30            # a company with no explanation yet: wait this long (or 2 sentences, or the end of the turn) before searching
LOOKUP_BUDGET = 20           # seconds per web lookup for a mention or a company relation
LOOKUP_SEARCHES = 3          # web searches per lookup at most
CACHE_DAYS = 7
LOOKUP_CACHE = PerUser(dict)  # ("person", name, role, company) or ("org", company A, company B) -> (saved at, result)
LOOKUP_CACHE_LOCK = threading.Lock()


def _org_variants(org):
    """"Zalando SE" -> {"Zalando SE", "Zalando"}; "Wise, formerly TransferWise" -> {"Wise", "TransferWise"}."""
    out = set()
    for part in re.split(r"\s*(?:,\s*formerly|/|\(|,)\s*", str(org or "")):
        part = part.strip(" )")
        if not part:
            continue
        out.add(part)
        words = part.split()
        while len(words) > 1 and words[-1].lower() in ORG_SUFFIX_WORDS:
            words = words[:-1]
            out.add(" ".join(words))
    return {v for v in out if len(v) >= 3 and v.lower() not in COMMON_ORG_WORDS and v.lower() not in STARTWORDS and v[0].isupper()}


def known_orgs(events, records, own_domain, me_email):
    """Company names Overture already knows -> {"name", "domain"}: the adopters list, well-known vendors, Overture records,
    the companies in your calendar and the HubSpot companies it has read lately."""
    out = {}

    def put(name, domain=""):
        for v in _org_variants(name) if not domain else {name} | _org_variants(name):
            if v and v.lower() not in COMMON_ORG_WORDS:
                k = out.setdefault(v, {"name": name if domain else v, "domain": domain})
                if domain and not k["domain"]:
                    k["domain"] = domain
    for a in snapshot().get("adopters", []):
        org = str(a.get("org") or "")
        m = re.search(r"\b([a-z0-9-]+\.(?:com|io|co|net))\b", org.lower())
        put(org, m.group(1) if m else "")
    for name, d in KNOWN_VENDORS.items():
        put(name, d)
    for name, c in (records.get("companies") or {}).items():
        if isinstance(c, dict):
            put(str(name), str(c.get("domain") or "").lower())
    mine = domain_of(me_email)
    for ev in events or []:
        for a in ev.get("attendees") or []:
            d = domain_of(str(a.get("email", "")).lower())
            if d and not personal_domain(d) and not (mine and same_org(d, mine, records)):
                co = company_for_domain(d, records)
                if co:
                    put(co, d)
    with CRM_LOCK:
        hs = [v[1] for k, v in CRM_CACHE.items() if isinstance(k, tuple) and k[:2] == ("hubspot", "company") and isinstance(v[1], dict)]
        hs_keys = [k[2] for k, v in CRM_CACHE.items() if isinstance(k, tuple) and k[:2] == ("hubspot", "company") and isinstance(v[1], dict)]
    for info, d in zip(hs, hs_keys):
        if info.get("name"):
            put(info["name"], d)
    return out


_ORG_RX_CACHE = {}


def _known_rx(names):
    key = tuple(sorted(names))
    rx = _ORG_RX_CACHE.get(key)
    if rx is None:
        if len(_ORG_RX_CACHE) > 20:
            _ORG_RX_CACHE.clear()
        alts = sorted(names, key=len, reverse=True)
        rx = re.compile(r"(?<![\w.])(" + "|".join(re.escape(n) for n in alts) + r")(?![\w])") if alts else None
        _ORG_RX_CACHE[key] = rx
    return rx


def sentence_list(lines):
    """Every sentence of the transcript in order: (line index, speaker, time, sentence). Same order as extract_mentions counts them."""
    out = []
    for li, line in enumerate(lines):
        for _, sent in _sentences(str(line.get("text") or "")):
            out.append((li, str(line.get("speaker") or ""), str(line.get("time") or ""), sent))
    return out


def _is_me(speaker, ctx):
    sp = norm_name(speaker)
    return bool(sp) and (sp in ctx["me"] or sp.split()[0] in ctx["meFirst"] or sp in ("your note", "your notes"))


def _org_ok(name, ctx, people_names):
    words = name.split()
    low = [w.lower().strip(".") for w in words]
    if not words or low[0] in STARTWORDS or low[0] in CODENAME_WORDS:
        return False
    if any(w in NOT_ORG or w in PLACES for w in low) or all(w in TEAM_SET or w in ROLE_WORDS or w in STARTWORDS for w in low):
        return False
    n = norm_org(name)
    own = norm_org(ctx.get("company") or "")
    if not n or n == own or set(n.split()) <= ctx["companyWords"] or "spotify" in n:
        return False
    nn = norm_name(name)
    if nn in ctx["attendees"] or nn in ctx["me"] or nn in people_names:
        return False
    if len(words) == 1 and (low[0] in ctx["attendeeFirst"] or low[0] in ctx["meFirst"] or low[0] in {p.split()[0] for p in people_names if p}):
        return False
    return True


def extract_orgs(lines, ctx, people=None):
    """Lines -> the companies talked about (not the call's own company, not Spotify), each with one quote and its sentence number."""
    known = ctx.get("orgs") or {}
    rx = _known_rx(list(known))
    people_names = {norm_name(p.get("name") or "") for p in people or [] if p.get("name")} | {norm_name(k["name"]) for k in ctx.get("known") or []}
    found = {}
    si = -1
    for line in lines:
        text = str(line.get("text") or "")
        for _, sent in _sentences(text):
            si += 1
            hits = []  # (start, end, name, how): "known", "suffix" (a company word ends it), "cue" or "poss"
            if rx:
                hits += [(m.start(1), m.end(1), m.group(1), "known") for m in rx.finditer(sent)]
            hits += [(m.start(1), m.end(1), m.group(1), "suffix") for m in ORG_SUFFIX_RE.finditer(sent)]
            hits += [(m.start(1), m.end(1), m.group(1), "cue") for m in ORG_CUE_RE.finditer(sent)]
            hits += [(m.start(1), m.end(1), m.group(1), "poss") for m in ORG_POSS_RE.finditer(sent)]
            hits.sort(key=lambda h: (h[0], -(h[1] - h[0])))
            used = []
            for a, b, name, how in hits:
                if any(s <= a < e for s, e in used):
                    continue
                words = name.split()
                # a cue can run into the next words ("moved off Loggly Monday"): keep the company words only
                while len(words) > 1 and (words[-1].lower() in NOT_ORG or words[-1].lower() in STARTWORDS or words[-1].lower() in PLACES):
                    words = words[:-1]
                name = " ".join(words)
                info = known.get(name)
                if not info and how != "known":
                    # a cue followed by a known name plus more words: the known name wins
                    sub = next((k for k in known if name.startswith(k + " ")), None)
                    info = known.get(sub) if sub else None
                    name = sub or name
                if CODE_BEFORE_RE.search(sent[:a]) or CODE_AFTER_RE.match(sent, a + len(name)):
                    continue  # "Project Falcon", "codename Falcon Labs", "the Falcon AI project": a codename, never a company and never searched
                if how == "known" and name.lower() in AMBIGUOUS_KNOWN and not re.sub(r"[\W_]+", "", sent[:a]):
                    nxt = re.match(r"\s*([\w'’]+)", sent[a + len(name):])
                    if nxt and nxt.group(1).lower() not in AMBIGUOUS_OK_NEXT and not nxt.group(1).lower().startswith(("'", "’")):
                        continue  # "Port forwarding broke": the word, not the company
                if not _org_ok(name, ctx, people_names if how in ("cue", "poss") and not info else set()):
                    continue
                used.append((a, a + len(name)))
                key = "o:" + norm_org(name)
                it = found.get(key)
                if it:
                    it["count"] += 1
                    continue
                if len(found) >= MAX_MENTIONS:
                    continue
                found[key] = {"key": key, "name": (info or {}).get("name") or name, "domain": (info or {}).get("domain", ""), "count": 1, "si": si,
                              "said": name,
                              "quote": {"text": quote_for(sent, a, a + len(name)), "speaker": clean_text(line.get("speaker"), 80),
                                        "time": clean_text(line.get("time"), 12)}}
    return list(found.values())


# ---- the follow-up: does the call itself say how they relate? ----

_BE = r"(?:\s+(?:is|are|was|were)|['’](?:re|s))"


def _rel_noun(words):
    """A relation noun said about this company: "{N} is our vendor", "they're a partner", "our main vendor, {N}", "{N}, a rival".
    The company (or they / it) must be the subject, so "Harborline wants a partner" or "our investors like it" don't count."""
    return (r"\b(?:{N}|they|it)" + _BE + r"\s+(?:\w+\s+){0,4}?(?:" + words + r")\b"
            r"|\b(?:our|their)\s+(?:\w+\s+){0,2}?(?:" + words + r"),?\s+{N}\b"
            r"|\b{N},\s+(?:our|their|a|an|the)\s+(?:\w+\s+){0,2}?(?:" + words + r")\b")


ORG_REL_RULES = [  # (relation, detail, pattern). {N} is the company's name; checked in this order
    ("acquirer", "", r"\b(?:{N}|they)\s+(?:acquired|bought)\s+us\b|\bwe\s+(?:were|got)\s+(?:acquired|bought)\s+by\s+(?:{N}|them)\b|\b(?:acquired|bought)\s+by\s+{N}\b"),
    ("acquired", "", r"\bwe\s+(?:acquired|bought)\s+(?:{N}|them)\b"),
    ("parent", "", _rel_noun(r"parent(?:\s+company)?") + r"|\b(?:{N}|they)\s+owns?\s+us\b|\b(?:we(?:'re|’re|\s+are)\s+)?owned\s+by\s+(?:{N}|them)\b"),
    ("subsidiary", "", _rel_noun(r"subsidiary|subsidiaries") + r"|\bwe\s+own\s+(?:{N}|them)\b"),
    ("investor", "", _rel_noun(r"investors?|backers?") + r"|\bbacked\s+by\s+(?:{N}|them)\b|\b(?:{N}|they)\s+invested\s+in\s+us\b"
                     r"|\b(?:{N}|they)" + _BE + r"\s+on\s+(?:our|the)\s+cap\s+table\b"),
    ("competitor", "", _rel_noun(r"competitors?|rivals?") + r"|\bcompet(?:e|es|ing)\s+(?:directly\s+)?with\s+(?:{N}|them)\b|\b(?:{N}|they)\s+compet(?:e|es)\s+with\s+us\b"),
    ("customer", "", _rel_noun(r"customers?|clients?") + r"|\b(?:they|{N})\s+(?:buy|buys|bought)\s+from\s+us\b"),
    ("vendor", "former", r"\b(?:switched|moved|migrated)\s+(?:away\s+)?(?:from|off)\s+(?:{N}|them|it)\b|\breplac(?:ed|ing)\s+(?:{N}|them|it)\b|\b(?:used\s+to\s+use|dropped)\s+(?:{N}|them)\b"),
    ("vendor", "", _rel_noun(r"vendors?|suppliers?|providers?") + r"|\bwe\s+(?:buy|license|get)\s+\w+(?:\s+\w+)?\s+from\s+(?:{N}|them)\b|\bwe\s+pay\s+(?:{N}|them)\b"),
    ("partner", "", _rel_noun(r"partners?") + r"|\bpartner(?:ed|ing)?\s+with\s+(?:{N}|them)\b|\b(?:{N}|they)\s+partner(?:ed|s)?\s+with\s+us\b"
                    r"|\bpartnership\s+with\s+(?:{N}|them)\b"),
    ("uses_product", "", r"\bwe\s+(?:use|run|rely\s+on|are\s+on)\s+(?:{N}|them|it)\b|\bwe(?:'re|’re|\s+are)\s+(?:using|on)\s+(?:{N}|them|it)\b|"
                         r"\b(?:switched|moved|moving|migrating)\s+(?:over\s+)?to\s+(?:{N}|them)\b"),
]
NEG_RE = re.compile(r"(?i)\b(?:not|never|no\s+longer|(?:do|does|did|is|are|was|were|has|have|had|wo|ca)n['’]t|cannot)\b")
CLAUSE_CUT_RE = re.compile(r",\s*and\b|;|,?\s+but\b")
COMPANY_NOUN_RE = re.compile(r"(?i)(?:our|their)\s+(?:\w+\s+){0,2}?(?:customers?|clients?|vendors?|suppliers?|providers?|partners?|competitors?|investors?)\b")
PERSON_REL_RE = (r"\b(?:{S})(?:\s+(?:also|basically|actually|really|now))?\s+(owns|runs|leads|heads|manages|handles|looks\s+after|is\s+in\s+charge\s+of|"
                 r"signs\s+off\s+on|approves|decides\s+on|reports\s+to|works\s+(?:on|in|for|with))\s+([^.,;!?]{2,60})"
                 r"|\b(?:{S})(?:'s|’s|\s+is|\s+are|'re|’re)\s+((?:our|their|the|a|an)\s+[^.,;!?]{2,50})")
PERSON_RELATIONSHIP = (("contractor", r"\b(?:contractor|consultant|agency|freelancer)\b"), ("investor", r"\b(?:board|investor|advisor)\b"),
                       ("partner", r"\bpartner\b"), ("customer", r"\bcustomer\b"))


SENT_END_RE = re.compile(r"[.!?…][\"'”’)]*\s*$")


def _followup(sents, si, stop_at, final=True):
    """The sentences to read after a mention: its own, the next two, and the same speaker's next turn (first 2 sentences).
    Stops early at a sentence that mentions someone or something else (a pronoun there could mean them). Returns (list, complete):
    complete is False while the speaker may still be explaining (fewer than 2 finished sentences after it and no later turn;
    a sentence still being typed doesn't count)."""
    if si is None or not 0 <= si < len(sents):
        return [], True
    li, spk = sents[si][0], sents[si][1]
    out = [sents[si]]
    nxt = list(range(si + 1, min(si + 3, len(sents))))
    for j in nxt:
        if j in stop_at:
            break
        out.append(sents[j])
    later = [j for j in range(si + 3, len(sents)) if sents[j][1] == spk and sents[j][0] != li]
    if later and not any(j in stop_at for j in range(si + 1, later[0])):
        first_li = sents[later[0]][0]
        out += [sents[j] for j in later if sents[j][0] == first_li][:2]
    done = [j for j in nxt if SENT_END_RE.search(sents[j][3])]
    complete = final or len(done) >= 2 or any(s[0] != li for s in sents[si + 1:])
    return out, complete


def _own_clause(sent, name, others):
    """The part of the company's own sentence that is about it: cut at another company said in it, and at ", and", ";" or "but"."""
    m = re.search(r"(?<![\w.])" + name + r"(?![\w])", sent)
    if not m:
        return sent
    a, b = m.span()
    lo, hi = [0], [len(sent)]
    spans = [s.span() for s in CLAUSE_CUT_RE.finditer(sent)]
    spans += [s.span() for o in others if o for s in re.finditer(r"(?<![\w.])" + re.escape(o) + r"(?![\w])", sent)]
    for s, e in spans:
        if e <= a:
            lo.append(e)
        elif s >= b:
            hi.append(s)
    return sent[max(lo):min(hi)]


def org_relation_said(org, sents, ctx, stop_at=frozenset(), final=True, others=()):
    """What the call says about how this company relates to the call's company. None when it says nothing, False when the
    speaker may still explain (live notes: fewer than 2 sentences after it so far). Local rules only. others: the other companies'
    names, so "Brightwave is our vendor and Harborline is a partner" gives each its own relation."""
    window, complete = _followup(sents, org.get("si"), stop_at, final)
    name = re.escape(org.get("said") or org["name"])
    for k, (li, spk, time_, sent) in enumerate(window):
        refers = re.search(r"(?i)\b(?:they|them|it|their|its)\b", sent) or re.search(name, sent)
        if k and not refers:
            continue
        text = _own_clause(sent, name, others) if k == 0 else sent
        for rel, detail, pat in ORG_REL_RULES:
            m = next((x for x in re.finditer(pat.replace("{N}", name), text, re.I)
                      if not NEG_RE.search(" ".join(text[:x.start()].split()[-3:]) + " " + text[x.start():x.end()])), None)
            if not m:
                continue  # not said, or said with a "not" / "never" ("we never partnered with them")
            words = text[m.start():m.end()].lower()
            side = "you" if (_is_me(spk, ctx) and re.search(r"\b(?:we|us|our)\b", words)) else "them"
            if rel == "vendor" and not detail:
                f = re.match(r"(?i)\s+for\s+([a-z][a-z-]*(?:\s+(?!(?:and|or|but|so|we|they|it|which|that|because|since)\b)[a-z][a-z-]*){0,2})", text[m.end():])
                detail = f.group(1) if f else ""
            said = " ".join(text[m.start():m.end()].split()) + (" for " + detail if detail and detail != "former" else "")
            return {"type": rel, "detail": detail, "said": "" if re.search(r"\d", said) else said, "source": "said", "sources": [],
                    "confidence": "", "side": side, "speaker": clean_text(spk, 80), "time": clean_text(time_, 12)}
    return None if complete else False   # False: nothing yet, but the speaker may still explain


def person_relation_said(it, sents, stop_at=frozenset()):
    """What the call says about a person right after they come up ("he owns the roadmap", "she runs procurement"), or None.
    Returns {"label", "team", "relationship", "said", ...}. Only team words ever leave this PC (as the role for a lookup)."""
    window, _ = _followup(sents, it.get("si"), stop_at)
    first = (it.get("name") or "").split()[0] if it.get("name") else ""
    subj = "he|she|they" + ("|" + re.escape(first) if first else "") + ("|" + re.escape(it["name"]) if it.get("name") and " " in it["name"] else "")
    rx = re.compile(PERSON_REL_RE.replace("{S}", subj), re.I)
    for k, (li, spk, time_, sent) in enumerate(window):
        for m in rx.finditer(sent):
            if k == 0 and first and not re.match(r"(?i)" + re.escape(first), sent[m.start():]):
                continue  # in the mention's own sentence only the name itself counts as the subject
            verb, obj = (m.group(1), m.group(2)) if m.group(1) else ("is", m.group(3))
            if not m.group(1) and sent[m.start():m.start() + 4].lower() == "they" and COMPANY_NOUN_RE.match(obj):
                continue  # "They're our biggest customer": a company, not this person
            obj = " ".join(obj.split()[:6]).rstrip()
            label = (" ".join(verb.lower().split()) + " " + obj).strip()
            if re.search(r"\d|@", label):
                continue
            team = re.search(r"\b(" + TEAM + r")\b", obj)
            rel = next((r for r, p in PERSON_RELATIONSHIP if re.search(p, obj, re.I)), "")
            return {"label": label[:80], "team": _role_text(team.group(1)).lower() if team else "", "relationship": rel,
                    "said": label[:80], "speaker": clean_text(spk, 80), "time": clean_text(time_, 12)}  # the matched words only
    return None


# ---- the web: how is that company related to the call's company? ----

ORG_SYSTEM = (
    "You find how two companies are related, for a salesperson's notes. Business facts only. "
    "Search the web for both companies together. Use public sources: the companies' own websites, press releases, news, "
    "case studies, partner and customer pages. Never use people-search or contact-data sites. "
    "Give the relation of Company B to Company A: customer (B buys from A), vendor (A buys from B), partner, competitor, "
    "parent (B owns A), subsidiary (A owns B), investor (B invested in A), acquired (A acquired B), acquirer (B acquired A), "
    "uses_product (A uses B's product), other, or unknown. If no public source shows a relation, answer unknown. Do not guess. "
    "Stop searching as soon as one source answers it.\n"
    "Answer with one JSON object and nothing else, in exactly this shape:\n"
    '{"relation": "one of the words above", "detail": "a few words, like for logging, or empty", "confidence": "high, medium or low", '
    '"explanation": [{"text": "one plain sentence on what the relation is: what B does with or for A, for which team or product, '
    'and since when if a source says", "sources": [1]}], '
    '"since": {"text": "when it started if a source says, like 2023 or March 2024, else empty", "sources": [1]}, '
    '"about": {"text": "one plain sentence defining Company B: what it is and what it does, from its own site or a news page, '
    'even when the relation is unknown", "sources": [1]}, '
    '"sources": [{"url": "https://...", "label": "short name of the page", "date": "YYYY-MM-DD, YYYY-MM or YYYY, or empty", '
    '"quote": "up to 25 words copied from the page that show the relation"}]}\n'
    "Write only what the sources say. Give 1 to 3 explanation sentences in plain words, each listing the numbers of the sources "
    "that say it (1 is the first source). Leave out anything no source says. Each source's quote is copied word for word from "
    "that page, at most 25 words, and shows the fact it backs; date is when the page was published or updated, if it shows one."
)


def org_request(a_name, a_domain, b_name, b_domain):
    """The exact request for one company relation: the two company names and their websites. Nothing else."""
    a_name, b_name = clean_text(a_name, 120), clean_text(b_name, 120)
    a_domain, b_domain = str(a_domain or "").lower(), str(b_domain or "").lower()
    if not b_name or "@" in a_name + b_name or not DOMAIN_RE.match(a_domain) or personal_domain(a_domain):
        raise ResearchError("not enough to look it up")
    if CODENAME_RE.search(b_name):
        raise ResearchError("that looks like a codename, so Overture didn't send it")
    if b_domain and (not DOMAIN_RE.match(b_domain) or personal_domain(b_domain)):
        b_domain = ""
    user = ("Company A: " + (a_name or a_domain) + "\nCompany A website: " + a_domain + "\nCompany B: " + b_name
            + "\nCompany B website: " + (b_domain or "(not known)") + "\n\nHow is Company B related to Company A? Answer with the JSON object only.")
    return search_request(ORG_SYSTEM, user, LOOKUP_SEARCHES)


def clean_org_relation(obj, seen):
    """Claude's answer -> a sourced relation, or unknown. Unsourced, unsure or off-list answers are unknown."""
    out = {"type": "unknown", "detail": "", "said": "", "source": "web", "sources": [], "confidence": "", "side": "them", "speaker": "", "time": ""}
    if not isinstance(obj, dict):
        return out
    known = obj.get("relation") in ORG_RELATIONS and obj.get("relation") != "unknown" and obj.get("confidence") in ("high", "medium")
    srcs = []
    for s in obj.get("sources") if isinstance(obj.get("sources"), list) else []:
        url = safe_url(s.get("url")) if isinstance(s, dict) else ""
        if not url or blocked_url(url) or url_key(url) not in seen:
            continue
        label = clean_text(s.get("label"), 120)
        srcs.append({"url": url, "label": label if label and "@" not in label else urllib.parse.urlsplit(url).hostname})
        if len(srcs) == 3:
            break
    if not srcs:
        return out
    srcs = clean_evidence(obj.get("sources"), srcs, seen)
    # What Company B is (shown when you click it), kept only when a kept source says it: also when the relation is unknown.
    about = (clean_explanation([obj["about"]], obj.get("sources"), srcs, 1, 240) or [None])[0] if isinstance(obj.get("about"), dict) else None
    if about and len(about["text"]) > 12 and not PHONE_RE.search(about["text"]):
        out.update(about=about, sources=srcs)
    if not known:
        return out
    detail = clean_text(obj.get("detail"), 80)
    if "@" in detail or PHONE_RE.search(detail):
        detail = ""
    out.update(type=obj["relation"], detail=detail, sources=srcs, confidence=obj["confidence"],
               explanation=clean_explanation(obj.get("explanation"), obj.get("sources"), srcs), since=clean_since(obj.get("since"), obj.get("sources"), srcs))
    return out


def _cache_get(key, forced=False):
    with LOOKUP_CACHE_LOCK:
        hit = LOOKUP_CACHE.get(key)
    if hit and not forced and _time.time() - hit[0] < CACHE_DAYS * 86400:
        return hit[1]
    return None


def _cache_put(key, value):
    with LOOKUP_CACHE_LOCK:
        LOOKUP_CACHE[key] = (_time.time(), value)
        while len(LOOKUP_CACHE) > 1000:
            LOOKUP_CACHE.pop(next(iter(LOOKUP_CACHE)))


def update_org(call_id, oid, fn):
    """Change one saved company mention under the records lock (connections follow). Returns the call's block, or None."""
    with RECORDS_LOCK:
        r = load_records()
        block = (r.get("mentions") or {}).get(call_id)
        it = next((x for x in (block or {}).get("orgs") or [] if x.get("id") == oid), None)
        if not it:
            return None
        fn(it, r)
        block["updatedAt"] = now_iso()
        sync_connections(r, call_id)
        if len(json.dumps(r)) > MAX_RECORDS_BYTES:
            raise Invalid("the records store is full")
        save_json(records_path(), r)
        return block


def do_org_lookup(job, now=None):
    """The research worker's job for one company: how is it related to the call's company? Sourced or unknown."""
    if not source_on("web"):  # turned off while it waited: nothing goes to the web
        return update_org(job["callId"], job["id"], lambda it, _r: it.update(status="nokey", note=WEB_OFF_NOTE) if it.get("status") == "pending" else None)
    if held_back(job, org=True):
        return None
    key = ("org", norm_org(job.get("company")), norm_org(job.get("name")))
    rel = _cache_get(key, job.get("forced"))
    if rel is None:
        stop, text, seen = run_search(org_request(job.get("company"), job.get("domain"), job.get("name"), job.get("orgDomain")), LOOKUP_BUDGET)
        rel = clean_org_relation(None if stop == "refusal" else extract_json(text), seen)
        _cache_put(key, rel)

    def apply(it, _r):
        if it.get("status") != "pending":
            return  # the call explained it meanwhile, or you changed it
        it.update(status="found" if rel["type"] != "unknown" else "unknown", relation=dict(rel), lookedAt=now_iso(),
                  note="" if rel["type"] != "unknown" else "Overture looked on the web and found no public source on how they relate.")
    update_org(job["callId"], job["id"], apply)


def queue_org(call_id, block, it, forced=False):
    """Put one company relation on the research worker's queue (ahead of invitee research)."""
    key = "org:" + call_id + ":" + it["id"]
    with RQ_LOCK:
        RQ.setdefault("mentions", {})[key] = {"type": "org", "callId": call_id, "id": it["id"], "name": it.get("name", ""), "orgDomain": it.get("domain", ""),
                                              "company": block.get("company", ""), "domain": block.get("domain", ""), "forced": forced}
        RQ["errors"].pop(key, None)
        if key not in RQ["pending"] and key not in RQ["running"]:
            RQ["queue"].append((key, True))
            RQ["pending"].add(key)
            RQ_LOCK.notify_all()
    if RESEARCH_AUTOSTART:
        ensure_worker()


def org_status(call_id, it):
    status, note = it.get("status") or "unknown", it.get("note") or ""
    if status == "pending":
        with RQ_LOCK:
            err = RQ["errors"].get("org:" + call_id + ":" + it["id"])
        if err:
            return "error", "Couldn't look it up: " + err + "."
    return status, note


def start_org_lookup(call_id, oid, now=None):
    """No explanation came (2 sentences, the end of the turn, or 30 seconds): look the relation up on the web at once."""
    queued = {}

    def apply(it, r):
        if it.get("status") != "waiting":
            return
        block = r["mentions"][call_id]
        blocker = lookup_blocker(block, it.get("source") in AUTO_SOURCES, r)
        if blocker:
            it.update(status=blocked_status(blocker, True), note=blocker, waitUntil=0)
        else:
            it.update(status="pending", waitUntil=0)
            queued["it"] = dict(it)
    block = update_org(call_id, oid, apply)
    if block and queued:
        queue_org(call_id, block, queued["it"])


def promote_waiting(now=None):
    """Start the web lookup for every company whose 30 seconds of waiting for an explanation are over."""
    t = _time.time() if now is None else now
    due = []
    for cid, block in (load_records().get("mentions") or {}).items():
        for it in (block or {}).get("orgs") or [] if isinstance(block, dict) else []:
            if it.get("status") == "waiting" and float(it.get("waitUntil") or 0) <= t:
                due.append((cid, it["id"]))
    for cid, oid in due:
        start_org_lookup(cid, oid)
    return len(due)


def _wait_timer(call_id, oid, seconds):
    if not RESEARCH_AUTOSTART:
        return  # tests call promote_waiting themselves
    t = threading.Timer(seconds + 0.2, contextvars.copy_context().run, args=(start_org_lookup, call_id, oid))
    t.daemon = True
    t.start()


# ---- connections: what goes on the People map ----

ORG_EDGE_LABEL = {"customer": "{w} customer", "vendor": "{w} vendor", "partner": "partner", "competitor": "competitor", "parent": "{w} parent company",
                  "subsidiary": "{w} subsidiary", "investor": "{w} investor", "acquired": "{W} acquired it", "acquirer": "acquired {o}",
                  "uses_product": "{W} use its product", "other": "related", "unknown": "relation unknown"}


def org_edge_label(rel):
    rel = rel or {}
    t = rel.get("type") or "unknown"
    you = rel.get("side") == "you"
    if t == "vendor" and rel.get("detail") == "former":
        return "your former vendor" if you else "their former vendor"
    lab = ORG_EDGE_LABEL.get(t, "related").format(w="your" if you else "their", W="you" if you else "they", o="you" if you else "them")
    d = rel.get("detail") or ""
    return (lab + " (" + d + ")") if d and d != "former" and t in ("vendor", "partner", "other", "uses_product") else lab


def connection_id(call_id, kind, key):
    return hashlib.sha256((call_id + "|" + kind + "|" + key).encode("utf-8")).hexdigest()[:12]


# ---- explaining a connection: what it is, backed by sources ----
# Claude's answer carries 1 to 3 plain sentences, each citing its sources by number, and per source a short quote (25 words at
# most, shown only when the search's own citations of that page hold those words) and the page's date (the search's, never
# Claude's). A sentence whose sources were all dropped (blocked, never in the search results) is dropped too, so the card never
# says more than the sources do; with no sentence left it shows only the relation type.

EVIDENCE_WORDS = 25
PAGE_DATE_RE = re.compile(r"^\d{4}(?:-(?:0[1-9]|1[0-2])(?:-(?:0[1-9]|[12]\d|3[01]))?)?$")


def _evidence_quote(v):
    t = clean_text(v, 2000)
    if not t or "@" in t or PHONE_RE.search(t) or re.search(r"https?://", t):
        return ""
    t = t.strip("\"“”'‘’ ")
    w = t.split()
    return t if len(w) <= EVIDENCE_WORDS else " ".join(w[:EVIDENCE_WORDS]) + "…"


_QUOTE_FOLD = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'", "…": " "})


def _quote_words(t):
    """Text to compare word for word: curly quotes made straight, case, spacing and the quotation marks or dots at either end left out."""
    return " ".join(str(t or "").translate(_QUOTE_FOLD).split()).lower().strip("\"'. ")


def clean_evidence(raw_sources, kept, seen=None):
    """The kept sources ({url, label}) with a short quote and the page's date, neither only on Claude's word: the quote Claude gave
    (from its own sources list) is kept only when the search's own citations of that page hold those words (seen, from
    run_search), and the date is the one the search gave for the page."""
    by = {}
    for s in raw_sources if isinstance(raw_sources, list) else []:
        u = safe_url(s.get("url")) if isinstance(s, dict) else ""
        if u:
            by.setdefault(url_key(u), s)
    out = []
    for k in kept:
        raw = by.get(url_key(k["url"])) or {}
        page = (seen.get(url_key(k["url"])) if isinstance(seen, dict) else None) or {}
        q = _evidence_quote(raw.get("quote"))
        if not _quote_words(q) or not any(_quote_words(q) in _quote_words(c) for c in page.get("cited") or []):
            q = ""
        d = str(page.get("age") or "")
        out.append({"url": k["url"], "label": k.get("label") or "", "date": d if PAGE_DATE_RE.match(d) else "", "quote": q})
    return out


def clean_explanation(expl, raw_sources, kept, limit=3, chars=300):
    """Up to `limit` sentences, each backed by at least one kept source. Sources are cited by number (1 = the first in Claude's
    sources list) or by URL; the result cites them by position in `kept` (0-based)."""
    raw = raw_sources if isinstance(raw_sources, list) else []
    keys = [url_key(k["url"]) for k in kept]
    out = []
    for e in expl[:6] if isinstance(expl, list) else []:
        if not isinstance(e, dict):
            continue  # a bare sentence names no source: dropped
        text = clean_text(e.get("text"), chars)
        if not text or "@" in text or PHONE_RE.search(text) or re.search(r"https?://", text):
            continue
        refs = []
        for c in e.get("sources") if isinstance(e.get("sources"), list) else []:
            u = ""
            if isinstance(c, int) and not isinstance(c, bool) and 1 <= c <= len(raw) and isinstance(raw[c - 1], dict):
                u = safe_url(raw[c - 1].get("url"))
            elif isinstance(c, str):
                u = safe_url(c)
            k = url_key(u) if u else ""
            if k in keys and keys.index(k) not in refs:
                refs.append(keys.index(k))
        if refs:
            out.append({"text": text, "sources": refs})
        if len(out) == limit:
            break
    return out


def clean_since(since, raw_sources, kept):
    """When the relation started, only when a kept source says it ({"text", "sources"}), else None."""
    got = clean_explanation([since] if isinstance(since, dict) else [], raw_sources, kept, 1, 40)
    return got[0] if got and not PHONE_RE.search(got[0]["text"]) else None


def _evidence_view(srcs):
    """(the sources shown, at most 3; {stored index: shown index}). A source dropped now (a site you blocked in Settings since)
    moves the ones after it up, so the map is what keeps each sentence on the source it really cites."""
    out, remap = [], {}
    for i, s in enumerate(srcs or []):
        u = safe_url(s.get("url")) if isinstance(s, dict) else ""
        if not u or blocked_url(u):
            continue
        d = clean_text(s.get("date"), 10)
        remap[i] = len(out)
        out.append({"url": u, "label": clean_text(s.get("label"), 120) or urllib.parse.urlsplit(u).hostname,
                    "date": d if PAGE_DATE_RE.match(d) else "", "quote": _evidence_quote(s.get("quote"))})
        if len(out) == 3:
            break
    return out, remap


def _explanation_view(expl, remap):
    """Sentences as stored, checked again: each one's sources (stored indices) are moved to where they are shown (remap, from
    _evidence_view); a sentence none of whose sources is shown any more is dropped."""
    out = []
    for e in expl if isinstance(expl, list) else []:
        refs = []
        for i in (e.get("sources") or []) if isinstance(e, dict) else []:
            if isinstance(i, int) and not isinstance(i, bool) and i in remap and remap[i] not in refs:
                refs.append(remap[i])
        text = clean_text(e.get("text"), 300) if isinstance(e, dict) else ""
        if text and refs:
            out.append({"text": text, "sources": refs})
    return out[:3]


def explain_view(kind, it, block):
    """The card behind a connection or mention: relation type, the sourced sentences, short quotes with links and dates,
    what was said on the call, when and where it was found, and the confidence. Old results with no sentences still work:
    the card then shows the relation type and whatever else is known."""
    q = it.get("quote") or {}
    found = {"call": clean_text(block.get("company"), 120), "title": clean_text(block.get("title"), 200),
             "via": MENTION_SOURCES.get(it.get("source"), ""), "time": clean_text(q.get("time"), 12),
             "at": str(it.get("lookedAt") or it.get("at") or "")}
    mention = {"text": clean_text(q.get("text"), 400), "speaker": clean_text(q.get("speaker"), 80), "time": clean_text(q.get("time"), 12)} if q.get("text") else None
    if kind == "company":
        rel = it.get("relation") if isinstance(it.get("relation"), dict) else {}
        t = rel.get("type") if rel.get("type") in ORG_RELATIONS else "unknown"
        ev, remap = _evidence_view(rel.get("sources"))
        said = {"text": clean_text(rel.get("said"), 200), "speaker": clean_text(rel.get("speaker"), 80), "time": clean_text(rel.get("time"), 12)} \
            if rel.get("source") == "said" and rel.get("said") else None
        since = rel.get("since") if isinstance(rel.get("since"), dict) else None
        since = (_explanation_view([since], remap) or [None])[0] if since else None
        about = rel.get("about") if isinstance(rel.get("about"), dict) else None
        about = (_explanation_view([about], remap) or [None])[0] if about else None
        how = "Said on the call" if rel.get("source") == "said" else "Found on the web" if ev else ""
        return {"kind": "company", "name": clean_text(it.get("name"), 120), "type": t, "typeLabel": ORG_RELATIONS.get(t, "Unknown"),
                "label": org_edge_label(rel) if rel else "mentioned", "detail": clean_text(rel.get("detail"), 80) if rel.get("detail") != "former" else "former",
                "explanation": _explanation_view(rel.get("explanation"), remap), "since": since, "about": about, "evidence": ev, "said": said,
                "mention": mention, "found": dict(found, how=how), "confidence": rel.get("confidence") if rel.get("confidence") in ("high", "medium") else ""}
    p, likely = it.get("person"), False
    if not isinstance(p, dict) and it.get("status") == "pick" and it.get("candidates"):
        p, likely = it["candidates"][0], True
    p = p if isinstance(p, dict) else {}
    ev, remap = _evidence_view(p.get("sources"))
    sd = it.get("said") if isinstance(it.get("said"), dict) else {}
    said = {"text": clean_text(sd.get("said"), 200), "speaker": clean_text(sd.get("speaker"), 80), "time": clean_text(sd.get("time"), 12)} if sd.get("said") else None
    rel = str(p.get("relationship") or sd.get("relationship") or "")
    how = "Likely, not confirmed" if likely else "Known to Overture" if it.get("status") == "known" else "Found on the web" if p.get("from") == "Web" else (p.get("from") or "")
    return {"kind": "person", "name": clean_text(p.get("name") or it.get("name") or it.get("role"), 100), "title": clean_text(p.get("title"), 120),
            "type": rel if rel in RELATIONSHIPS else "", "typeLabel": RELATIONSHIPS.get(rel, "") if rel != "unknown" else "",
            "label": clean_text(sd.get("label"), 80) or clean_text(it.get("role"), 80), "team": clean_text(p.get("team"), 120),
            "explanation": _explanation_view(p.get("explanation"), remap), "since": None, "evidence": ev, "said": said, "mention": mention,
            "found": dict(found, how=how), "confidence": p.get("confidence") if p.get("confidence") in ("high", "medium") else "", "likely": likely}


def prune_quotes(r, now=None):
    """Settings > Mentions > keep quotes for N days: a call's sentences (the quote and what was said about them) older than that
    are dropped, inside the records lock, and so is Granola's summary of the call. The mention, its relation and its web sources
    stay, and the Granola note's title and link. Returns the call ids changed."""
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=mention_settings(r)["keepDays"])
    changed = set()
    for cid, block in (r.get("mentions") or {}).items():
        for it in ((block.get("items") or []) + (block.get("orgs") or [])) if isinstance(block, dict) else []:
            at = parse_dt(it.get("at")) if isinstance(it, dict) else None
            if not at or at > cutoff:
                continue
            q = it.get("quote") if isinstance(it.get("quote"), dict) else {}
            if q.get("text"):
                it["quote"] = {"text": "", "speaker": str(q.get("speaker") or ""), "time": str(q.get("time") or "")}
                changed.add(cid)
            for k in ("said", "relation"):
                x = it.get(k)
                if isinstance(x, dict) and x.get("said"):
                    x["said"] = ""
                    changed.add(cid)
    for cid in changed:
        sync_connections(r, cid)
    for cid, g in (r.get("granola") or {}).items():
        at = parse_dt(g.get("at")) if isinstance(g, dict) else None
        if at and at <= cutoff and g.get("summary"):
            g["summary"] = ""
            changed.add(cid)
    return changed


def prune_old_quotes(now=None):
    """prune_quotes on the saved records, written only when something is dropped."""
    if not prune_quotes(load_records(), now):  # a quick look first, without the lock
        return False
    with RECORDS_LOCK:
        r = load_records()
        if prune_quotes(r, now):
            save_json(records_path(), r)
    return True


def sync_connections(r, call_id):
    """Rebuild one call's connections from its mentions (inside the records lock). People count once they're found automatically
    (one clear match), known, picked or confirmed; companies at once, with their relation when there is one. Removed ones stay removed."""
    conns = r.setdefault("connections", {})
    removed = r.get("connectionsRemoved") or {}
    block = (r.get("mentions") or {}).get(call_id) or {}
    likely_too = mention_settings(r)["autoAdd"] == "likely"  # Settings > Mentions: the most likely match goes on the map too
    keep = {}
    for it in block.get("items") or []:
        p, likely = it.get("person"), False
        if it.get("status") == "pick" and likely_too and it.get("candidates") and isinstance(it["candidates"][0], dict):
            p, likely = it["candidates"][0], True
        elif it.get("status") not in ("found", "known"):
            continue
        if not isinstance(p, dict) or not p.get("name"):
            continue
        cid = connection_id(call_id, "person", it.get("key") or it["id"])
        if cid in removed:
            continue
        said = it.get("said") or {}
        keep[cid] = {"id": cid, "kind": "person", "callId": call_id, "mentionId": it["id"], "company": block.get("company", ""),
                     "domain": block.get("domain", ""), "name": clean_text(p.get("name"), 100), "title": clean_text(p.get("title"), 120),
                     "team": clean_text(p.get("team") or it.get("role"), 120), "relationship": str(p.get("relationship") or said.get("relationship") or ""),
                     "label": said.get("label") or (it.get("role") if it.get("role") and not str(it.get("role")).startswith("at ") else "") or "mentioned",
                     "said": said.get("said", ""), "source": "Said on the call" if said else (p.get("from") or "Web"),
                     "sources": (_person_view(p) or {}).get("sources", []), "from": it.get("fromNode") or "",
                     "speaker": (it.get("quote") or {}).get("speaker", ""), "time": (it.get("quote") or {}).get("time", ""),
                     "auto": bool(it.get("autoFound")) and not it.get("confirmed"), "likely": likely, "via": str(it.get("source") or ""),
                     "at": (conns.get(cid) or {}).get("at") or it.get("at") or now_iso()}
    for it in block.get("orgs") or []:
        cid = connection_id(call_id, "company", it.get("key") or it["id"])
        if cid in removed or it.get("removed"):
            continue
        rel = it.get("relation") or {}
        keep[cid] = {"id": cid, "kind": "company", "callId": call_id, "mentionId": it["id"], "company": block.get("company", ""),
                     "domain": block.get("domain", ""), "name": clean_text(it.get("name"), 120), "orgDomain": str(it.get("domain") or ""),
                     "relation": rel.get("type") or "", "label": org_edge_label(rel) if rel else "mentioned", "said": rel.get("said", ""),
                     "source": "Said on the call" if rel.get("source") == "said" else "Web" if rel.get("sources") else "",
                     "sources": rel.get("sources") or [], "from": it.get("fromNode") or "", "status": it.get("status", ""),
                     "speaker": (it.get("quote") or {}).get("speaker", ""), "time": (it.get("quote") or {}).get("time", ""),
                     "via": str(it.get("source") or ""), "at": (conns.get(cid) or {}).get("at") or it.get("at") or now_iso()}
    for cid in [c for c, v in conns.items() if isinstance(v, dict) and v.get("callId") == call_id and c not in keep]:
        del conns[cid]
    conns.update(keep)


def connections_graph(records, call_ids, attendees=None):
    """The saved connections of these calls as map nodes and labelled edges (live data: "mentioned" and "relationships")."""
    nodes, edges = [], []
    blocks = records.get("mentions") or {}
    for c in (records.get("connections") or {}).values():
        if not isinstance(c, dict) or c.get("callId") not in call_ids:
            continue
        frm = c.get("from") or "you"
        if frm.startswith("p:") and attendees is not None and frm[2:] not in attendees:
            frm = "you"
        when = (" at " + c["time"]) if c.get("time") else ""
        heard = {"meetily": "Heard on the call (Meetily)", "granola": "In Granola's transcript", "gong": "In Gong's transcript"}.get(c.get("via"))
        by = (c.get("speaker") + " mentioned them on the call" + when + ".") if c.get("speaker") and not c["speaker"].lower().startswith("your note") \
            else (heard + when + ".") if heard else "Mentioned in your call notes."
        block = blocks.get(c["callId"]) if isinstance(blocks.get(c["callId"]), dict) else {}
        src = next((x for x in (block.get("items") if c["kind"] == "person" else block.get("orgs")) or [] if isinstance(x, dict) and x.get("id") == c.get("mentionId")), None)
        explain = explain_view(c["kind"], src, block) if src else None  # the card behind the line (built from the saved mention, never stored twice)
        if c["kind"] == "person":
            nid = "m:" + c["id"]
            sub = c.get("title") or (c.get("team") or "").capitalize() or "Mentioned on the call"
            nodes.append({"id": nid, "type": "person", "label": c["name"], "sub": ("Likely · " + sub) if c.get("likely") else sub, "company": c.get("company", ""),
                          "callId": c["callId"], "mentioned": True, "auto": bool(c.get("auto")), "likely": bool(c.get("likely"))})
            why = c["name"] + (", " + c["title"] if c.get("title") else "") + ". " + by + ((" “" + c["said"] + "”") if c.get("said") else "")
        else:
            nid = "co:" + c["name"]
            nodes.append({"id": nid, "type": "company", "label": c["name"], "callId": c["callId"], "mentioned": True, "relation": c.get("relation", "")})
            why = by + ((" “" + c["said"] + "”") if c.get("said") else (" Relation found on the web." if c.get("sources") else ""))
        edges.append({"a": frm, "b": nid, "kind": "mentioned", "label": c.get("label") or "mentioned", "why": why.strip(), "src": "call",
                      "callId": c["callId"], "connId": c["id"], "mentionId": c.get("mentionId", ""), "source": c.get("source", ""),
                      "sources": c.get("sources") or [], "likely": bool(c.get("likely")), "explain": explain})
    return nodes, edges

# ---- looking them up (the research worker, Claude + web search) ----

MENTION_SYSTEM = (
    "You find out who a person mentioned on a sales call is, for a salesperson's notes. Work information only. "
    "You get a name or a first name, maybe a role or team, and the company they were mentioned with. "
    "Search the web for them together with the company. Use only public professional sources: the company's own website, "
    "conference talks, press releases and news, GitHub, published articles, and the person's own public professional profile. "
    "Never search for or report personal details: no personal email, phone number, home address, family, age, photos, "
    "or social media beyond a professional profile. Never use people-search or contact-data sites. "
    "Return every real person who fits, up to 3, best first. If nobody fits for sure, return an empty list. Do not guess. "
    "Stop searching as soon as a source answers it.\n"
    "Answer with one JSON object and nothing else, in exactly this shape:\n"
    '{"candidates": [{"name": "full name", "title": "current job title, or empty", "team": "team or department, or empty", '
    '"seniority": "one of executive, director, manager, senior, individual contributor, or empty", '
    '"tenure": "roughly how long at the company if public, or empty", '
    '"relationship": "one of employee, contractor, partner, investor, customer, other, unknown", '
    '"confidence": "high, medium or low", "why": "one short line: why this person fits the mention", '
    '"explanation": [{"text": "one plain sentence on who they are at the company and how they fit the mention: their role, '
    'team or product, and since when if a source says", "sources": [1]}], '
    '"sources": [{"url": "https://...", "label": "short name of the page", "date": "YYYY-MM-DD, YYYY-MM or YYYY, or empty", '
    '"quote": "up to 25 words copied from the page that show it", '
    '"supports": ["the fields this page backs: title, team, seniority, tenure, relationship"]}]}]}\n'
    "relationship means their relationship to the company: employee, contractor (or agency), partner, investor (or board member), "
    "customer, other, or unknown. Give 1 to 3 sources per person. Every field you fill must be backed by a source that lists it in supports. "
    "Write only what the sources say. Give 1 to 3 explanation sentences in plain words, each listing the numbers of the sources "
    "that say it (1 is the first source). Leave out anything no source says. Each source's quote is copied word for word from "
    "that page, at most 25 words, and shows the fact it backs; date is when the page was published or updated, if it shows one."
)


def mention_request(name, role, company, domain):
    """The exact request for one mention: the name or first name, the role or team words, the company name and domain. Nothing else."""
    name, role, company, domain = clean_text(name, 100), clean_text(role, 80), clean_text(company, 120), str(domain or "").lower()
    if (not name and not role) or "@" in name + role + company or not DOMAIN_RE.match(domain) or personal_domain(domain):
        raise ResearchError("not enough to look them up")
    if CODENAME_RE.search(name + " " + role):
        raise ResearchError("that looks like a codename, so Overture didn't send it")
    user = ("Mentioned on the call: " + (name or "(no name given)") + "\nRole or team: " + (role or "(not said)")
            + "\nCompany: " + (company or domain) + "\nCompany website: " + domain
            + "\n\nWho is this? Answer with the JSON object only.")
    return search_request(MENTION_SYSTEM, user, LOOKUP_SEARCHES)


def clean_candidates(obj, seen, job):
    """Claude's candidates -> at most 3 sourced people whose name fits the mention. Anything unsourced or unsure is dropped."""
    out, names = [], set()
    cands = obj.get("candidates") if isinstance(obj, dict) else None
    want = norm_name(job.get("name") or "")
    for c in cands[:6] if isinstance(cands, list) else []:
        if not isinstance(c, dict):
            continue
        r = clean_research(dict(c, found=True), seen)
        name = clean_text(c.get("name"), 100)
        n = norm_name(name)
        if r["status"] != "done" or len(n.split()) < 2 or "@" in name or re.search(r"\d", name) or n in names:
            continue
        if want and (n != want if len(want.split()) > 1 else n.split()[0] != want):
            continue  # not the name that was said
        why = clean_text(c.get("why"), 200)
        if "@" in why or PHONE_RE.search(why):
            why = ""
        names.add(n)
        ev = clean_evidence(c.get("sources"), r["sources"], seen)
        out.append({"name": name, "title": r["title"], "team": r["team"], "seniority": r["seniority"], "tenure": r["tenure"],
                    "relationship": r["relationship"] if r["relationship"] != "unknown" else "", "confidence": r["confidence"],
                    "sources": ev, "why": why, "from": "Web", "explanation": clean_explanation(c.get("explanation"), c.get("sources"), ev)})
        if len(out) == 3:
            break
    return out


def mention_key(call_id, mid):
    return "mention:" + call_id + ":" + mid


def update_mention(call_id, mid, fn):
    """Change one saved mention under the records lock (its connection follows). Returns the call's saved block, or None if it's gone."""
    with RECORDS_LOCK:
        r = load_records()
        block = (r.get("mentions") or {}).get(call_id)
        it = next((x for x in (block or {}).get("items") or [] if x.get("id") == mid), None)
        if not it:
            return None
        fn(it, r)
        block["updatedAt"] = now_iso()
        sync_connections(r, call_id)
        if len(json.dumps(r)) > MAX_RECORDS_BYTES:
            raise Invalid("the records store is full")
        save_json(records_path(), r)
        return block


# Whole words, with a short list of forms that mean the same team (not 5-letter prefixes: "product" isn't "production").
_NORM = {"management": "manage", "manager": "manage", "managers": "manage", "managing": "manage", "financial": "finance",
         "engineering": "engineer", "engineers": "engineer", "designer": "design", "designers": "design", "recruiter": "recruiting",
         "recruiters": "recruiting", "recruitment": "recruiting", "accountant": "accounting", "accountants": "accounting",
         "researcher": "research", "researchers": "research", "architect": "architecture", "architects": "architecture",
         "infrastructure": "infra", "analyst": "analytics", "analysts": "analytics"}


def _stem(w):
    w = _NORM.get(w, w)
    return w[:-1] if len(w) > 4 and w.endswith("s") and not w.endswith("ss") else w


def role_fits(role, c):
    """True when a candidate's title or team says the role or team that was said with the name
    ("product management" fits "Group Product Manager", "security" fits team "Security")."""
    role = str(role or "")
    if not role or role.startswith("at "):
        return False
    want = {_stem(w) for w in _role_tokens(role) if w not in {"team", "group", "org", "department", "side", "our", "their", "your"}}
    have = {_stem(w) for w in _role_tokens(str(c.get("title") or "") + " " + str(c.get("team") or ""))}
    return bool(want) and (want <= have or _title_matches(role, c.get("title") or ""))


def on_company_site(c, domain):
    """True when one of the candidate's sources is on the call company's own website (or a subdomain of it)."""
    d = str(domain or "").lower()
    hosts = [(urllib.parse.urlsplit(str(s.get("url") or "")).hostname or "").lower() for s in c.get("sources") or [] if isinstance(s, dict)]
    return bool(d) and any(h.removeprefix("www.") == d or h.endswith("." + d) for h in hosts)


def do_mention_lookup(job, now=None):
    """The research worker's job for one mention: search, keep sourced candidates. Exactly one sourced match for the name and the
    role or team said with it is marked found automatically (you can change it); several, or one that doesn't clearly fit, are
    shown most likely first as "Likely, not confirmed" and nothing is saved as a connection until you pick or confirm."""
    if not source_on("web"):  # turned off while it waited: nothing goes to the web
        return update_mention(job["callId"], job["id"], lambda it, _r: it.update(status="nokey", note=WEB_OFF_NOTE) if it.get("status") == "pending" else None)
    if held_back(job):
        return None
    role = job.get("role") or ""
    key = ("person", norm_name(job.get("name") or ""), role.lower(), norm_org(job.get("company")))
    cands = _cache_get(key, job.get("forced"))
    if cands is None:
        stop, text, seen = run_search(mention_request(job.get("name"), role, job.get("company"), job.get("domain")), LOOKUP_BUDGET)
        cands = [] if stop == "refusal" else clean_candidates(extract_json(text), seen, job)
        _cache_put(key, cands)
    cands = sorted((dict(c) for c in cands), key=lambda c: (not role_fits(role, c), c.get("confidence") != "high"))  # most likely first
    # Found automatically: one full name, or one first name whose team fits and whose source is the company's own website.
    # A role with no name ("our new CTO") is never auto-picked: the web often still lists the one before.
    auto = len(cands) == 1 and (job.get("kind") == "full" or (job.get("kind") == "partial" and bool(job.get("name"))
                                                              and on_company_site(cands[0], job.get("domain")) and role_fits(role, cands[0])))
    status = "notfound" if not cands else "found" if auto else "pick"

    def apply(it, _r):
        if it.get("status") != "pending":
            return  # you answered it meanwhile
        it.update(status=status, person=cands[0] if auto else None, candidates=cands if status == "pick" else [], autoFound=auto,
                  note="" if cands else "Overture looked on the web and found no one who clearly fits.", lookedAt=now_iso())
    update_mention(job["callId"], job["id"], apply)


def queue_mention(call_id, block, it, forced=False):
    """Put one mention on the research worker's queue (ahead of invitee research; up to MAX_WORKERS lookups run at once)."""
    key = mention_key(call_id, it["id"])
    with RQ_LOCK:
        RQ.setdefault("mentions", {})[key] = {"type": "person", "callId": call_id, "id": it["id"], "name": it.get("name", ""),
                                              "role": it.get("role", ""), "kind": it.get("kind", ""), "company": block.get("company", ""),
                                              "domain": block.get("domain", ""), "forced": forced}
        RQ["errors"].pop(key, None)
        if key not in RQ["pending"] and key not in RQ["running"]:
            RQ["queue"].append((key, True))
            RQ["pending"].add(key)
            RQ_LOCK.notify_all()
    if RESEARCH_AUTOSTART:
        ensure_worker()


WEB_OFF_NOTE = "Web research is off (Settings > Research sources and privacy), so Overture didn't look it up on the web."
AUTO_OFF_NOTE = "Automatic look-up is off (Settings > Mentions and connections). Press Look up on the web to look it up."
AUTO_SOURCES = ("live", "meetily", "captions")   # found while the call runs: looked up on their own only with automatic look-up on


def lookup_blocker(block, auto=False, records=None):
    """Why mentions on this call can't be looked up on the web ("" when they can). auto: found while the call runs (notes as
    you type, Meetily), which only goes to the web by itself while Settings > Mentions > automatic look-up is on."""
    d = block.get("domain") or ""
    if not d or personal_domain(d):
        return "This call has no company web address, so Overture can't look people up for it."
    if not source_on("web", records):
        return WEB_OFF_NOTE
    if not claude_on():
        return "Add a Claude key to look them up on the web."
    if auto and not mention_settings(records)["autoLookup"]:
        return AUTO_OFF_NOTE
    return ""


def blocked_status(blocker, org=False):
    """The status for a mention that can't be looked up: "nokey" ("Not looked up", and Look up on the web works once it can)
    when a setting or the missing key stops it, else not found / unknown."""
    if blocker.startswith("Add a Claude") or blocker in (WEB_OFF_NOTE, AUTO_OFF_NOTE):
        return "nokey"
    return "unknown" if org else "notfound"


def held_back(job, org=False):
    """For the research worker: automatic look-up was turned off while a lookup found during the call (notes as you type,
    Meetily) waited. It shows "Not looked up" instead of going to the web; Look up on the web (forced) still goes. True when held."""
    if job.get("forced") or mention_settings()["autoLookup"]:
        return False
    block = (load_records().get("mentions") or {}).get(job["callId"]) or {}
    it = next((x for x in block.get("orgs" if org else "items") or [] if isinstance(x, dict) and x.get("id") == job["id"]), None)
    if not it or it.get("source") not in AUTO_SOURCES:
        return False
    (update_org if org else update_mention)(job["callId"], job["id"], lambda x, _r: x.update(status="nokey", note=AUTO_OFF_NOTE) if x.get("status") == "pending" else None)
    return True


def mention_status(call_id, it):
    """(status, note): pending, found, known, pick, notfound, error, nokey."""
    status, note = it.get("status") or "notfound", it.get("note") or ""
    if status == "pending":
        key = mention_key(call_id, it["id"])
        with RQ_LOCK:
            err = RQ["errors"].get(key)
        if err:
            return "error", "Couldn't look them up: " + err + "."
    return status, note


def _person_view(p):
    if not isinstance(p, dict):
        return None
    srcs, remap = _evidence_view(p.get("sources"))
    rel = str(p.get("relationship") or "")
    return {"name": clean_text(p.get("name"), 100), "title": clean_text(p.get("title"), 120), "team": clean_text(p.get("team"), 120),
            "seniority": clean_text(p.get("seniority"), 40), "tenure": clean_text(p.get("tenure"), 60),
            "relationship": rel if rel in RELATIONSHIPS else "", "confidence": str(p.get("confidence") or "") if p.get("confidence") in ("high", "medium") else "",
            "why": clean_text(p.get("why"), 200), "from": clean_text(p.get("from"), 40), "sources": srcs,
            "explanation": _explanation_view(p.get("explanation"), remap)}


def _said_view(said):
    if not isinstance(said, dict):
        return None
    return {k: clean_text(said.get(k), 200) for k in ("label", "team", "relationship", "said", "speaker", "time")}


def mention_view(call_id, it, met, conns=None, block=None):
    """One mention as the page sees it. met: name -> last time you met them (from your calendar), or None if unknown."""
    status, note = mention_status(call_id, it)
    person = _person_view(it.get("person"))
    out = {"id": it["id"], "name": str(it.get("name") or ""), "role": str(it.get("role") or ""), "kind": str(it.get("kind") or ""),
           "quote": {k: str((it.get("quote") or {}).get(k) or "") for k in ("text", "speaker", "time")}, "count": int(it.get("count") or 1),
           "source": str(it.get("source") or ""), "status": status, "note": note, "person": person,
           "candidates": [_person_view(c) for c in it.get("candidates") or []][:3] if status == "pick" else [],
           "confirmed": bool(it.get("confirmed")), "added": bool(it.get("added")), "hubspot": str(it.get("hubspot") or ""),
           "autoFound": bool(it.get("autoFound")) and status == "found", "likely": status == "pick" and bool(it.get("candidates")),
           "said": _said_view(it.get("said")), "removed": bool(it.get("removed")), "explain": explain_view("person", it, block or {})}
    if conns is not None:
        out["connected"] = connection_id(call_id, "person", it.get("key") or it["id"]) in conns
    if met is not None:
        for p in [out["person"]] + out["candidates"]:
            if p and p["name"]:
                at = met.get(norm_name(p["name"]))
                p["met"] = {"known": True, "last": (short_day(to_et(at).date()) + ", " + str(to_et(at).year)) if at else ""}
    return out


def calendar_met():
    """name -> the last time you met them, from your calendar (None when the calendar can't be read)."""
    if not token_info():
        return None
    try:
        events, now = fetch_events(), datetime.now(timezone.utc)
    except (GoogleError, NotConnected):
        return None
    me_email = str((token_info() or {}).get("email", "")).lower()
    met = {}
    for ev in events:
        start, end = _event_times(ev)
        if ev.get("status") == "cancelled" or not start or end > now:
            continue
        for a in _others(ev, me_email):
            n = norm_name(a["name"])
            if n not in met or met[n] < start:
                met[n] = start
    return met


def org_view(call_id, it, conns=None, block=None):
    """One company mentioned on the call, with how it relates to the call's company (said on the call, found on the web, or unknown)."""
    status, note = org_status(call_id, it)
    rel = it.get("relation") if isinstance(it.get("relation"), dict) else None
    srcs, remap = _evidence_view((rel or {}).get("sources"))
    out = {"id": it["id"], "kind": "company", "name": clean_text(it.get("name"), 120), "domain": str(it.get("domain") or ""),
           "quote": {k: str((it.get("quote") or {}).get(k) or "") for k in ("text", "speaker", "time")}, "count": int(it.get("count") or 1),
           "source": str(it.get("source") or ""), "status": status, "note": note, "removed": bool(it.get("removed")),
           "relation": None if not rel else {"type": rel.get("type") if rel.get("type") in ORG_RELATIONS else "unknown", "label": org_edge_label(rel),
                                             "detail": clean_text(rel.get("detail"), 80), "said": clean_text(rel.get("said"), 200),
                                             "source": "said" if rel.get("source") == "said" else "web", "sources": srcs[:3],
                                             "confidence": rel.get("confidence") if rel.get("confidence") in ("high", "medium") else "",
                                             "speaker": clean_text(rel.get("speaker"), 80), "time": clean_text(rel.get("time"), 12),
                                             "explanation": _explanation_view(rel.get("explanation"), remap)},
           "explain": explain_view("company", it, block or {})}
    if conns is not None:
        out["connected"] = connection_id(call_id, "company", it.get("key") or it["id"]) in conns
    return out


def mentions_body(call_id, met=None, requeue=True):
    """GET /api/mentions?callId=: the people and companies mentioned on one call, and the call's connections for the map.
    A lookup left waiting (the server restarted) is queued again, and a company whose 30 seconds of waiting are over is looked up."""
    if requeue:
        promote_waiting()
        prune_old_quotes()
        settle_blocked(call_id)
    records = load_records()
    block = (records.get("mentions") or {}).get(call_id) or {}
    items = block.get("items") or []
    blockers = {auto: lookup_blocker(block, auto) for auto in (False, True)} if requeue else {}
    if requeue and not blockers[False]:
        for it in items:
            if it.get("status") == "pending" and not blockers[it.get("source") in AUTO_SOURCES]:
                key = mention_key(call_id, it["id"])
                with RQ_LOCK:
                    waiting = key in RQ["pending"] or key in RQ["running"] or key in RQ["errors"]
                if not waiting:
                    queue_mention(call_id, block, it)
        for it in block.get("orgs") or []:
            if it.get("status") == "pending" and not blockers[it.get("source") in AUTO_SOURCES]:
                key = "org:" + call_id + ":" + it["id"]
                with RQ_LOCK:
                    waiting = key in RQ["pending"] or key in RQ["running"] or key in RQ["errors"]
                if not waiting:
                    queue_org(call_id, block, it)
    conns = {c for c, v in (records.get("connections") or {}).items() if isinstance(v, dict) and v.get("callId") == call_id}
    nodes, edges = connections_graph(records, {call_id})
    return {"callId": call_id, "company": str(block.get("company") or ""), "updatedAt": str(block.get("updatedAt") or ""),
            "claude": claude_on(), "items": [mention_view(call_id, it, met, conns, block) for it in items],
            "orgs": [org_view(call_id, it, conns, block) for it in block.get("orgs") or []],
            "graph": {"mentioned": nodes, "relationships": edges}, "granola": granola_view(records, call_id)}


def settle_blocked(call_id):
    """Lookups left "Looking up…" that can't run now (web research turned off, the key removed, or automatic look-up turned off
    for one found during the call) and aren't queued show "Not looked up" instead, so nothing spins for ever. They can be looked
    up again once it is allowed."""
    block = (load_records().get("mentions") or {}).get(call_id) or {}
    blockers = {auto: lookup_blocker(block, auto) for auto in (False, True)} if block else {}
    if not blockers.get(True):  # automatic look-up adds a reason, never takes one away: nothing is blocked
        return 0
    with RQ_LOCK:
        busy = RQ["pending"] | RQ["running"]
    todo = [(k, it["id"], blockers[it.get("source") in AUTO_SOURCES]) for k in ("items", "orgs") for it in block.get(k) or []
            if isinstance(it, dict) and it.get("status") == "pending" and blockers[it.get("source") in AUTO_SOURCES]
            and (mention_key(call_id, it["id"]) if k == "items" else "org:" + call_id + ":" + it["id"]) not in busy]
    for k, mid, blocker in todo:
        fn = update_mention if k == "items" else update_org
        fn(call_id, mid, lambda it, _r: it.update(status=blocked_status(blocker, k == "orgs"), note=blocker) if it.get("status") == "pending" else None)
    return len(todo)


def mention_statuses(records):
    """For GET /api/research: call id -> mention id -> status (people and companies), so the page knows when to fetch a call's mentions again."""
    out = {}
    for cid, block in (records.get("mentions") or {}).items():
        if isinstance(block, dict):
            out[cid] = {it["id"]: mention_status(cid, it)[0] for it in block.get("items") or [] if isinstance(it, dict) and it.get("id")}
            out[cid].update({it["id"]: org_status(cid, it)[0] for it in block.get("orgs") or [] if isinstance(it, dict) and it.get("id")})
    return out


# ---- the endpoints ----

def clean_mentions_post(body):
    _only(body, {"callId", "text", "filename", "lines", "hints", "source"})
    cid = _str(body, "callId", 200, True)
    if not CALLID_RE.match(cid):
        raise Invalid("callId doesn't look right")
    source = body.get("source", "upload")
    if source not in POST_SOURCES:
        raise Invalid("source must be upload, paste, notes, gong or captions")
    fname = _str(body, "filename", 200)
    if fname and not fname.lower().endswith(TRANSCRIPT_EXTS):
        raise Invalid("Use a .vtt, .srt or .txt transcript from Zoom or Google Meet.")
    text = body.get("text")
    if text is not None:
        if not isinstance(text, str):
            raise Invalid("text must be text")
        if len(text) > MAX_TRANSCRIPT_CHARS:
            raise Invalid("That transcript is too long (over 1 MB of text).")
        if not transcript_text_ok(text):
            raise Invalid("That file doesn't look like a text transcript.")
    lines = body.get("lines", [])
    if not isinstance(lines, list) or len(lines) > 5000:
        raise Invalid("lines must be a list of at most 5000 lines")
    clean_lines = []
    for ln in lines:
        if not isinstance(ln, dict) or set(ln) - {"speaker", "time", "text"}:
            raise Invalid("each line has a speaker, a time and a text")
        vals = {k: ln.get(k, "") for k in ("speaker", "time", "text")}
        if not all(isinstance(v, str) for v in vals.values()) or len(vals["speaker"]) > 80 or len(vals["time"]) > 12 or len(vals["text"]) > 4000:
            raise Invalid("a line is too long")
        if not transcript_text_ok(vals["text"]):
            raise Invalid("a line isn't text")
        clean_lines.append(vals)
    hints = body.get("hints", [])
    if not isinstance(hints, list) or len(hints) > 50:
        raise Invalid("hints must be a list of at most 50")
    for h in hints:
        if not isinstance(h, dict) or set(h) - {"name", "role"} or not all(isinstance(v, str) and len(v) <= 100 for v in h.values()):
            raise Invalid("each hint has a name and a role")
    if source != "gong" and not (text and text.strip()) and not clean_lines:
        raise Invalid("Nothing to read: add a transcript or some notes.")
    return {"callId": cid, "source": source, "text": text or "", "lines": clean_lines, "hints": hints}


def hubspot_domain_contacts(domain, deadline=None):
    """Contacts HubSpot has on this company's email domain, for names said on a call.
    The hs_email_domain search filter is from HubSpot's contact properties docs; untested against a real account."""
    def get():
        j = api_call("hubspot", "POST", "/crm/v3/objects/contacts/search", {
            "filterGroups": [{"filters": [{"propertyName": "hs_email_domain", "operator": "EQ", "value": domain}]}],
            "properties": ["email", "firstname", "lastname", "jobtitle"], "limit": 100}, deadline=deadline)
        out = []
        for r in j.get("results") or []:
            p = (r.get("properties") or {}) if isinstance(r, dict) else {}
            name = clean_text(" ".join(x for x in (p.get("firstname"), p.get("lastname")) if isinstance(x, str)), 120)
            if r.get("id") and len(name.split()) >= 2:
                out.append({"id": str(r["id"]), "name": name, "title": clip(p.get("jobtitle"), 120), "email": str(p.get("email") or "").lower()})
        return out
    return crm_cached(("hubspot", "domain-contacts", domain), get)


def gong_call_for(inv, now=None, deadline=None):
    """The Gong recording of this calendar call: same company domain, started within GONG_MATCH_HOURS of it. None if there's none."""
    start, d = parse_dt(inv.get("start")), inv.get("domain") or ""
    if not start or not d:
        return None
    best = None
    for c in gong_index(now, deadline):
        if not any(x == d or x.endswith("." + d) or d.endswith("." + x) for x in c["domains"]):
            continue
        st = parse_dt(c["started"])
        diff = abs((st - start).total_seconds()) if st else None
        if diff is not None and diff <= GONG_MATCH_HOURS * 3600 and (best is None or diff < best[0]):
            best = (diff, c)
    return best[1] if best else None


def gong_transcript_lines(inv, now=None):
    """Gong's transcript of this call as lines. Only called when "Read Gong transcripts" is on, and never cached or saved.
    POST /v2/calls/transcript (callTranscripts[].transcript[].sentences) and the speaker names from /v2/calls/extensive parties
    are from Gong's public API docs; untested against a real account."""
    deadline = _time.time() + 25
    call = gong_call_for(inv, now, deadline)
    if not call:
        raise Invalid("Gong has no recording of this call yet. Gong can take a while after a call ends.")
    names = {}
    for c in _gong_post({"filter": {"callIds": [call["id"]]}, "contentSelector": {"exposedFields": {"parties": True}}}, deadline).get("calls") or []:
        for p in (c.get("parties") or []) if isinstance(c, dict) else []:
            if isinstance(p, dict) and p.get("speakerId") is not None:
                names[str(p["speakerId"])] = clean_text(p.get("name"), 80)
    try:
        j = api_call("gong", "POST", "/v2/calls/transcript", {"filter": {"callIds": [call["id"]]}}, deadline=deadline)
    except ApiError as e:
        if e.status == 404:
            raise Invalid("Gong has no transcript for this call yet.") from None
        raise
    lines = []
    for ct in j.get("callTranscripts") or []:
        if not isinstance(ct, dict) or str(ct.get("callId")) != call["id"]:
            continue
        for mono in ct.get("transcript") or []:
            if not isinstance(mono, dict):
                continue
            spk = names.get(str(mono.get("speakerId")), "")
            for s in mono.get("sentences") or []:
                t = s.get("text") if isinstance(s, dict) else None
                if isinstance(t, str) and t.strip() and len(lines) < MAX_TRANSCRIPT_LINES:
                    lines.append({"speaker": spk, "time": _ms_clock(s.get("start")), "text": t[:4000]})
    if not lines:
        raise Invalid("Gong has no transcript for this call yet.")
    return lines


def _from_node(speaker, ctx):
    """Who said it, as a map node: "you" for you and your notes, "p:<email>" for a guest, "" when Overture can't tell."""
    if not speaker or _is_me(speaker, ctx):
        return "you"
    n = norm_name(speaker)
    atts = (ctx.get("invite") or {}).get("attendees") or []
    a = next((a for a in atts if norm_name(a["name"]) == n), None)
    if not a:
        same = [a for a in atts if norm_name(a["name"]).split()[:1] == n.split()[:1]]
        a = same[0] if len(same) == 1 else None
    return "p:" + a["email"] if a else ""


def find_all(lines, ctx, hints=None, final=True):
    """People and companies talked about, with what the call itself says about them right after (local rules only).
    final: the text is complete (a transcript, or a saved note); while you are still typing, a company with no explanation yet waits."""
    people = extract_mentions(lines, ctx, hints)
    known = {norm_org(k) for k in ctx.get("orgs") or {}}
    people = [p for p in people if not (p["kind"] == "full" and norm_org(p["name"]) in known)]  # "Acme Freight" is a company Overture knows
    orgs = extract_orgs(lines, ctx, people)
    named = {norm_org(o["name"]) for o in orgs} | {norm_org(o["said"]) for o in orgs}
    people = [p for p in people if not (p["kind"] == "full" and norm_org(p["name"]) in named)]  # "Acme Robotics Inc": a company, not a person
    people = [p for p in people if not (p["kind"] == "partial" and p["name"] and norm_org(p["name"]) in named | known)]  # "Datadog from sales"
    sents = sentence_list(lines)
    p_si = {p["si"] for p in people if p.get("si") is not None}
    o_si = {o["si"] for o in orgs}
    for p in people:
        p["said"] = person_relation_said(p, sents, (p_si | o_si) - {p["si"]}) if p.get("si") is not None else None
        if p["said"] and p["said"]["team"] and not p["role"] and p["kind"] in ("partial", "full"):
            p["role"] = p["said"]["team"]  # "Tom ... he runs procurement": only the team word is ever used for a lookup
    for o in orgs:
        o["relation"] = org_relation_said(o, sents, ctx, (o_si | p_si) - {o["si"]}, final, [x["said"] for x in orgs if x is not o])
    return people, orgs


def _untouched(it):
    """A person mention you haven't acted on (confirmed, picked, added, saved to HubSpot or removed), so Overture may take it back."""
    if it.get("confirmed") or it.get("added") or it.get("hubspot") or it.get("removed") or it.get("pickedAt"):
        return False
    return it.get("status") != "found" or bool(it.get("autoFound"))


def _unqueue(keys):
    """Forget queued lookups that aren't needed any more. One that is already running finishes, and its answer is dropped."""
    with RQ_LOCK:
        for k in keys:
            RQ["errors"].pop(k, None)
            if k in RQ["running"]:
                continue
            RQ["queue"] = [q for q in RQ["queue"] if q[0] != k]
            RQ["pending"].discard(k)
            RQ["mentions"].pop(k, None)


def save_mentions(call_id, ctx, found, source, orgs=None, bump=True, now=None, drop=frozenset(), auto=None):
    """Merge newly found mentions (people and companies) into the call's saved list (only the mention and its sentence; never the
    transcript) and update the call's connections. drop: keys a live note said before and no longer says ("John Sm" before
    "John Smith"); they are taken back unless you acted on them. Returns (block, new people, companies to look up now, companies
    waiting, new companies, queued lookups that aren't needed any more). auto (default: the source is notes as you type or
    Meetily) follows Settings > Mentions > automatic look-up; web research off stops every lookup."""
    t = _time.time() if now is None else now
    auto = source in AUTO_SOURCES if auto is None else auto
    with RECORDS_LOCK:
        r = load_records()
        allm = r.setdefault("mentions", {})
        block = allm.setdefault(call_id, {"company": ctx["company"], "domain": ctx["domain"], "items": []})
        block.update(company=ctx["company"], domain=ctx["domain"], title=clean_text((ctx.get("invite") or {}).get("title"), 200))
        block.setdefault("orgs", [])
        unqueue = []
        if drop:
            gone_p = {it["id"] for it in block["items"] if it.get("key") in drop and _untouched(it)}
            gone_o = {it["id"] for it in block["orgs"] if it.get("key") in drop and not it.get("removed")}
            block["items"] = [it for it in block["items"] if it["id"] not in gone_p]
            block["orgs"] = [it for it in block["orgs"] if it["id"] not in gone_o]
            unqueue += [mention_key(call_id, i) for i in gone_p] + ["org:" + call_id + ":" + i for i in gone_o]
        have = {it.get("key"): it for it in block["items"]}
        new = []
        blocker = lookup_blocker(block, auto, r)
        for f in found:
            old = have.get(f["key"])
            if old:
                if bump:
                    old["count"] = int(old.get("count") or 1) + f["count"]
                if f.get("said") and not old.get("said"):
                    old["said"] = f["said"]
                continue
            if len(block["items"]) >= MAX_MENTIONS:
                break
            it = {"id": hashlib.sha256((call_id + "|" + f["key"]).encode("utf-8")).hexdigest()[:12], "key": f["key"], "name": f["name"],
                  "role": f["role"], "kind": f["kind"], "count": f["count"], "quote": f["quote"], "source": source, "at": now_iso(),
                  "person": None, "candidates": [], "note": "", "confirmed": False, "added": False, "hubspot": "",
                  "said": f.get("said") or None, "fromNode": _from_node(f["quote"].get("speaker"), ctx), "autoFound": False}
            if f["kind"] == "known":
                it.update(status="known", person=dict(f["known"]))
            elif f.get("candidates"):
                it.update(status="pick", candidates=[dict(c) for c in f["candidates"]],
                          note="People Overture already knows at " + (ctx["company"] or "this company") + " by that " + ("name" if f["name"] else "title") + ".")
            elif blocker:
                it.update(status=blocked_status(blocker), note=blocker)
            else:
                it["status"] = "pending"
            block["items"].append(it)
            new.append(it)
        have_o = {it.get("key"): it for it in block["orgs"]}
        go, wait, new_o = [], [], []
        for o in orgs or []:
            rel, old = o.get("relation"), have_o.get(o["key"])
            if old:
                if bump:
                    old["count"] = int(old.get("count") or 1) + o["count"]
                if rel and old.get("status") in ("waiting", "pending"):  # explained on the call: that wins over the web
                    if old["status"] == "pending":
                        unqueue.append("org:" + call_id + ":" + old["id"])
                    old.update(status="said", relation=rel, waitUntil=0, note="")
                elif old.get("status") == "waiting":
                    if rel is None and blocker:
                        old.update(status=blocked_status(blocker, True), note=blocker, waitUntil=0)
                    elif rel is None:  # the speaker moved on without explaining it: look it up now
                        old.update(status="pending", waitUntil=0)
                        go.append(old)
                continue
            if len(block["orgs"]) >= MAX_MENTIONS:
                break
            it = {"id": hashlib.sha256((call_id + "|" + o["key"]).encode("utf-8")).hexdigest()[:12], "key": o["key"], "name": o["name"],
                  "domain": o.get("domain") or "", "kind": "company", "count": o["count"], "quote": o["quote"], "source": source, "at": now_iso(),
                  "fromNode": _from_node(o["quote"].get("speaker"), ctx), "relation": None, "note": "", "removed": False, "waitUntil": 0}
            if rel:
                it.update(status="said", relation=rel)  # the call explained it: no web lookup
            elif rel is False:
                it.update(status="waiting", waitUntil=t + WAIT_SECONDS)  # you're still typing: give the explanation a moment
                wait.append(it)
            elif blocker:
                it.update(status=blocked_status(blocker, True), note=blocker)
            else:
                it["status"] = "pending"
                go.append(it)
            block["orgs"].append(it)
            new_o.append(it)
        block["updatedAt"] = now_iso()
        prune_quotes(r)  # Settings > Mentions: sentences older than "keep quotes for" are dropped
        while len(allm) > MAX_MENTION_CALLS:  # oldest calls go first
            gone = min(allm, key=lambda k: str((allm[k] or {}).get("updatedAt") or ""))
            allm.pop(gone)
            sync_connections(r, gone)
        sync_connections(r, call_id)
        if len(json.dumps(r)) > MAX_RECORDS_BYTES:
            raise Invalid("the records store is full")
        save_json(records_path(), r)
        return dict(block), new, [dict(x) for x in go], [dict(x) for x in wait], new_o, unqueue


def _queue_found(call_id, block, new, go, wait):
    for it in new:
        if it["status"] == "pending":
            queue_mention(call_id, block, it)
    for it in go:
        queue_org(call_id, block, it)
    for it in wait:
        _wait_timer(call_id, it["id"], WAIT_SECONDS)


def _domain_contacts(domain):
    """hubspot_domain_contacts within CRM_BUDGET; [] (and the error noted) when HubSpot fails."""
    try:
        return hubspot_domain_contacts(domain, _time.time() + CRM_BUDGET)
    except ApiError as e:
        if not isinstance(e, Slow):
            crm_note("hubspot", False, str(e))
    except Exception:
        crm_note("hubspot", False, "HubSpot failed unexpectedly")
    return []


HS_WARMING = PerUser(set)    # domains whose HubSpot contacts are being fetched in the background for live notes


def _domain_contacts_cached(domain):
    """For live notes, which must never wait on HubSpot: the contacts Overture already has for this domain (even a little old), and a
    background fetch when they are missing or old, ready for the next part of the note."""
    key = ("hubspot", "domain-contacts", domain)
    with CRM_LOCK:
        hit = CRM_CACHE.get(key)
        fetch = not (hit and _time.time() - hit[0] < CRM_CACHE_SECONDS) and domain not in HS_WARMING
        if fetch:
            HS_WARMING.add(domain)

    def fill():
        try:
            _domain_contacts(domain)
        finally:
            with CRM_LOCK:
                HS_WARMING.discard(domain)
    if fetch:
        threading.Thread(target=contextvars.copy_context().run, args=(fill,), name="moab-hubspot-contacts", daemon=True).start()
    return list(hit[1]) if hit and isinstance(hit[1], list) else []


def _call_context(call_id, records, now, live=False):
    """(events, the call's mention context with the companies Overture knows), or raises Invalid / GoogleError.
    live: for live notes, HubSpot's contacts come from what Overture already has, never a request the note waits for."""
    tok = token_info() or {}
    me = {"email": tok.get("email", ""), "name": tok.get("name", "")}
    events = fetch_events()
    ctx = mention_context(events, me, records, call_id, now)
    if not ctx:
        return events, None
    hs = []
    if ctx["domain"] and crm_configured("hubspot"):
        hs = _domain_contacts_cached(ctx["domain"]) if live else _domain_contacts(ctx["domain"])
    if hs:
        ctx = mention_context(events, me, records, call_id, now, hs)
    ctx["orgs"] = known_orgs(events, records, ctx["domain"], me["email"])
    return events, ctx


def mentions_post(body, now=None):
    """POST /api/mentions: read a transcript (or your notes, or Gong's transcript), find the people and companies here, queue web lookups.
    The text is only used inside this function: it is never saved, logged or sent anywhere."""
    now = now or datetime.now(timezone.utc)
    if not token_info():
        return 409, {"error": "Connect Google Calendar first, so Overture knows the call."}
    try:
        c = clean_mentions_post(body)
        records = load_records()
        events, ctx = _call_context(c["callId"], records, now)
        if not ctx:
            return 404, {"error": "That call isn't in your calendar."}
        if c["source"] == "gong":
            if not setting_on(records, "gongTranscripts"):
                return 403, {"error": "Turn on Read Gong transcripts on the Data page first."}
            if not crm_configured("gong"):
                return 409, {"error": "Gong isn't connected. See Settings > Setup guides > Connect Gong."}
            try:
                lines = gong_transcript_lines(ctx["invite"], now)
            except ApiError as e:
                crm_note("gong", False, str(e))
                return 502, {"error": str(e)}
        else:
            lines = (parse_transcript(c["text"]) if c["text"].strip() else []) + c["lines"]
        found, orgs = find_all(lines, ctx, c["hints"])
        del lines, c["text"]  # the transcript goes no further
        block, new, go, wait, new_o, unqueue = save_mentions(c["callId"], ctx, found, c["source"], orgs)
    except Invalid as e:
        return 400, {"error": str(e)}
    except (GoogleError, NotConnected):
        return 502, {"error": "Google Calendar didn't answer, so Overture can't check the call. Try again."}
    _unqueue(unqueue)
    _queue_found(c["callId"], block, new, go, wait)
    out = mentions_body(c["callId"], ctx["met"], requeue=False)
    out["found"] = len(new) + len(new_o)
    return 200, out


# ---- live notes: the in-call panel sends what you type, a little at a time ----
# Only the new text is sent (debounced about half a second). The server keeps each note's text in memory while you type it,
# never on disk, and drops it when you save the note, switch calls, or after 10 minutes without a change (the panel then sends
# the whole note again). Names are found while the call is running.

LIVE_SEGMENTS = PerUser(dict)  # (call id, segment id) -> {"text", "at", "keys": the mentions this note added}
LIVE_LOCK = threading.Lock()
LIVE_MAX_CHARS = 8000
LIVE_TTL = 10 * 60
SEGMENT_RE = re.compile(r"^[a-z0-9]{6,32}$")
LIVE_SENT_END_RE = re.compile(r"[.!?…]+[\"'”’)]*(?=\s|$)")


def clean_live(body):
    _only(body, {"callId", "segment", "offset", "text", "final", "pause", "source"})
    if body.get("source", "live") not in ("live", "captions"):
        raise Invalid("source must be live or captions")
    cid = _str(body, "callId", 200, True)
    seg = _str(body, "segment", 32, True)
    if not CALLID_RE.match(cid) or not SEGMENT_RE.match(seg):
        raise Invalid("callId or segment doesn't look right")
    off, text, final, pause = body.get("offset", 0), body.get("text", ""), body.get("final", False), body.get("pause", False)
    if isinstance(off, bool) or not isinstance(off, int) or not 0 <= off <= LIVE_MAX_CHARS:
        raise Invalid("offset must be a number")
    if not isinstance(text, str) or len(text) > 4000 or not transcript_text_ok(text):
        raise Invalid("text must be up to 4000 characters of text")
    if not isinstance(final, bool) or not isinstance(pause, bool):
        raise Invalid("final and pause must be true or false")
    return cid, seg, off, text, final, pause


def mentions_live(body, now=None):
    """POST /api/mentions/live {callId, segment, offset, text, final, pause}: the new part of a note you're typing in the in-call panel.
    Finds people and companies as you type; a company's relation waits for your next sentences (or 30 seconds) before a web lookup.
    While you type, only finished sentences are read (". ! ? …"); a pause (pause: true, after about 1.5 s) reads the rest, and
    saving the note (final: true) ends it. The note remembers what it added: something it no longer says ("John Sm" once it reads
    "John Smith", "John from product" once it reads "product management") is taken back off the list and the map, and its queued
    lookup dropped, unless you acted on it."""
    now = now or datetime.now(timezone.utc)
    if not token_info():
        return 409, {"error": "Connect Google Calendar first, so Overture knows the call."}
    if not mention_settings()["autoLookup"]:  # Settings > Mentions: off means nothing is read while you type
        return 403, {"error": "Automatic look-up is off in Settings > Mentions and connections."}
    try:
        cid, seg, off, text, final, pause = clean_live(body)
        src = "captions" if body.get("source") == "captions" else "live"  # Google Meet's captions, read by the Chrome extension
        t = _time.time()
        with LIVE_LOCK:
            for k in [k for k, v in LIVE_SEGMENTS.items() if t - v["at"] > LIVE_TTL]:
                del LIVE_SEGMENTS[k]
            cur = LIVE_SEGMENTS.get((cid, seg)) or {"text": "", "at": t}
            if off > len(cur["text"]):
                return 409, {"error": "resend", "have": len(cur["text"])}
            full = cur["text"][:off] + text
            if len(full) > LIVE_MAX_CHARS:
                raise Invalid("That note is too long to read as you type. Save it and start a new one.")
            mine = set(cur.get("keys") or ())
            if final:
                LIVE_SEGMENTS.pop((cid, seg), None)
            else:
                LIVE_SEGMENTS[(cid, seg)] = {"text": full, "at": t, "keys": mine}
                while len(LIVE_SEGMENTS) > 200:
                    LIVE_SEGMENTS.pop(next(iter(LIVE_SEGMENTS)))
        if final or pause:
            ready = full
        else:  # a sentence still being typed isn't read yet ("from product " may become "from product management")
            ends = [m.end() for m in LIVE_SENT_END_RE.finditer(full)]
            ready = full[:ends[-1]] if ends else ""
        records = load_records()
        events, ctx = _call_context(cid, records, now, live=True)
        if not ctx:
            return 404, {"error": "That call isn't in your calendar."}

        def read(s):
            if not s.strip():
                return [], []
            # Google Meet's captions come as "Name: words" lines: keep who said what (your own note is one block, from you)
            lines = parse_transcript(s) if src == "captions" else [{"speaker": "Your note", "time": "", "text": s}]
            return find_all(lines, ctx, None, final) if lines else ([], [])
        found, orgs = read(ready)
        present = {x["key"] for x in found + orgs}
        if mine and ready != full:  # what the whole note says now, so a sentence still being typed keeps what it found on a pause
            more = read(full)
            present |= {x["key"] for x in more[0] + more[1]}
        del ready
        block, new, go, wait, new_o, unqueue = save_mentions(cid, ctx, found, src, orgs, bump=False, drop=mine - present)
        mine = (mine & present) | {x["key"] for x in new + new_o}
        if not final:
            with LIVE_LOCK:
                if (cid, seg) in LIVE_SEGMENTS:
                    LIVE_SEGMENTS[(cid, seg)]["keys"] = mine
    except Invalid as e:
        return 400, {"error": str(e)}
    except (GoogleError, NotConnected):
        return 502, {"error": "Google Calendar didn't answer, so Overture can't check the call. Try again."}
    _unqueue(unqueue)
    _queue_found(cid, block, new, go, wait)
    out = mentions_body(cid, ctx["met"], requeue=False)
    out["found"] = len(new) + len(new_o)
    out["have"] = 0 if final else len(full)
    return 200, out


def clean_mention_action(body):
    _only(body, {"callId", "id", "action", "index"})
    cid, mid = _str(body, "callId", 200, True), _str(body, "id", 20, True)
    if not CALLID_RE.match(cid) or not re.fullmatch(r"[0-9a-f]{12}", mid):
        raise Invalid("callId or id doesn't look right")
    action = body.get("action")
    if action not in ("pick", "confirm", "none", "again", "add", "remove", "restore"):
        raise Invalid("action must be pick, confirm, none, again, add, remove or restore")
    idx = body.get("index")
    if action == "pick" and (isinstance(idx, bool) or not isinstance(idx, int) or not 0 <= idx <= 2):
        raise Invalid("index must be 0, 1 or 2")
    if action != "pick" and idx is not None:
        raise Invalid("index is only for pick")
    return cid, mid, action, idx


def _set_removed(r, call_id, kind, x, removed):
    """Take a wrong connection off the map (or put it back). Yours to decide: Overture never adds a removed one again."""
    cid = connection_id(call_id, kind, x.get("key") or x["id"])
    gone = r.setdefault("connectionsRemoved", {})
    if removed:
        gone[cid] = now_iso()
    else:
        gone.pop(cid, None)
    x["removed"] = removed


def org_action(cid, block, it, action):
    """Your answer for one company: look its relation up on the web again, or remove / restore its connection."""
    if action == "again":
        blocker = lookup_blocker(block)
        if blocker:
            return (503, {"error": "no-key"}) if blocker.startswith("Add a Claude") else (400, {"error": blocker})
        if it.get("status") in ("pending", "said"):
            raise Invalid("Nothing to look up: " + ("it's being looked up." if it.get("status") == "pending" else "the call said how they relate."))
    elif action not in ("remove", "restore"):
        raise Invalid("For a company: again, remove or restore.")

    def apply(x, r):
        if action == "again":
            x.update(status="pending", relation=None, note="", waitUntil=0)
        else:
            _set_removed(r, cid, "company", x, action == "remove")
    saved = update_org(cid, it["id"], apply)
    if action == "again" and saved:
        queue_org(cid, saved, next(x for x in saved["orgs"] if x.get("id") == it["id"]), forced=True)
    return 200, mentions_body(cid, calendar_met(), requeue=False)


def mention_action(body):
    """POST /api/mentions/pick: your answer for one mention. People: pick a candidate, confirm, none of these, look up again, add to
    Overture records, remove or restore the connection. Companies: look up again, remove or restore the connection."""
    try:
        cid, mid, action, idx = clean_mention_action(body)
        block = (load_records().get("mentions") or {}).get(cid) or {}
        org = next((x for x in block.get("orgs") or [] if x.get("id") == mid), None)
        if org:
            return org_action(cid, block, org, action)
        it = next((x for x in block.get("items") or [] if x.get("id") == mid), None)
        if not it:
            return 404, {"error": "That mention isn't saved any more."}
        if action == "again":
            blocker = lookup_blocker(block)
            if blocker:
                return (503, {"error": "no-key"}) if blocker.startswith("Add a Claude") else (400, {"error": blocker})
            if it.get("status") not in ("notfound", "pending", "pick", "nokey") and not it.get("autoFound"):
                raise Invalid("Overture already knows who this is.")
        err = {}

        def apply(x, r):
            st = x.get("status")
            if action == "pick":
                cands = x.get("candidates") or []
                if st != "pick" or idx >= len(cands):
                    err["e"] = "There's no such candidate to pick."
                    return
                x.update(status="found", person=dict(cands[idx]), candidates=[], confirmed=True, autoFound=False, note="", pickedAt=now_iso())
            elif action == "confirm":
                if st not in ("found", "known") or not x.get("person"):
                    err["e"] = "There's nothing to confirm yet."
                    return
                x["confirmed"] = True
            elif action == "none":
                if st not in ("pick", "found"):
                    err["e"] = "There's nothing to turn down."
                    return
                x.update(status="notfound", person=None, candidates=[], confirmed=False, autoFound=False, note="You said none of these.")
            elif action == "again":
                x.update(status="pending", person=None, candidates=[], note="", autoFound=False, confirmed=False)
            elif action in ("remove", "restore"):
                _set_removed(r, cid, "person", x, action == "remove")
            else:  # add to Overture records: the next transcript knows them at once
                p = x.get("person")
                if st not in ("found", "known") or not isinstance(p, dict) or len(norm_name(p.get("name", "")).split()) < 2:
                    err["e"] = "Pick who this is first."
                    return
                key = (block.get("domain") or "") + "|" + norm_name(p["name"])
                r.setdefault("knownPeople", {})[key] = {
                    "name": clean_text(p.get("name"), 100), "title": clean_text(p.get("title"), 120), "team": clean_text(p.get("team"), 120),
                    "relationship": str(p.get("relationship") or ""), "company": block.get("company", ""), "domain": block.get("domain", ""),
                    "sources": (_person_view(p) or {}).get("sources", []), "fromCall": cid, "addedAt": now_iso()}
                x.update(added=True, confirmed=True)
        saved = update_mention(cid, mid, apply)
        if err:
            raise Invalid(err["e"])
        if action == "again" and saved:
            with RQ_LOCK:
                RQ["errors"].pop(mention_key(cid, mid), None)
            queue_mention(cid, saved, next(x for x in saved["items"] if x.get("id") == mid), forced=True)
    except Invalid as e:
        return 400, {"error": str(e)}
    return 200, mentions_body(cid, calendar_met(), requeue=False)


def clean_mention_hubspot(body):
    _only(body, {"callId", "id", "confirm", "planId"})
    cid, mid = _str(body, "callId", 200, True), _str(body, "id", 20, True)
    if not CALLID_RE.match(cid) or not re.fullmatch(r"[0-9a-f]{12}", mid):
        raise Invalid("callId or id doesn't look right")
    if "confirm" in body and body["confirm"] is not True:
        raise Invalid("confirm must be true")
    pid = _str(body, "planId", 64) or ""
    if body.get("confirm") is True and not re.fullmatch(r"[0-9a-f]{16}", pid):
        raise Invalid("planId is missing: check the preview again before saving")
    return cid, mid, body.get("confirm") is True, pid


def mention_hubspot(body):
    """POST /api/mentions/hubspot: save one mentioned person to HubSpot as a contact. Without confirm: exactly what would be written
    (nothing is). With confirm: true and that planId: write it. Name and job title only, never an email address or phone number.
    Creating a contact with associations (type 279, contact to company) is from HubSpot's docs; untested against a real account."""
    if not hubspot_token():
        return 409, {"error": "HubSpot isn't connected. See Settings > Setup guides > Connect HubSpot."}
    try:
        cid, mid, confirm, pid = clean_mention_hubspot(body)
        block = (load_records().get("mentions") or {}).get(cid) or {}
        it = next((x for x in block.get("items") or [] if x.get("id") == mid), None)
        p = (it or {}).get("person")
        if not it or it.get("status") not in ("found", "known") or not isinstance(p, dict):
            raise Invalid("Pick who this is first.")
        if it.get("hubspot") and it["hubspot"] != "unknown":
            raise Invalid("Already saved to HubSpot as a contact.")
        if p.get("from") == "HubSpot":
            raise Invalid("They're already a contact in HubSpot.")
        words = clean_text(p.get("name"), 100).split()
        if len(words) < 2:
            raise Invalid("Overture needs their full name to add them to HubSpot.")
        first, last, title = words[0], " ".join(words[1:]), clean_text(p.get("title"), 120)
        deadline = _time.time() + 15
        try:
            info = hubspot_company(block["domain"], deadline) if block.get("domain") else None
            dup = api_call("hubspot", "POST", "/crm/v3/objects/contacts/search", {
                "filterGroups": [{"filters": [{"propertyName": "firstname", "operator": "EQ", "value": first},
                                              {"propertyName": "lastname", "operator": "EQ", "value": last}]}],
                "properties": ["firstname", "lastname"], "limit": 5}, deadline=deadline).get("results") or []
        except ApiError as e:
            return 502, {"error": str(e)}
        if dup:
            raise Invalid("HubSpot already has a contact named " + first + " " + last + ". Nothing was written.")
        props = {"firstname": first, "lastname": last}
        if title:
            props["jobtitle"] = title
        plan = {"properties": props, "company": {"id": info["id"], "name": info.get("name") or block.get("company", "")} if info else None}
        plan_id = hashlib.sha256(json.dumps([mid, props, plan["company"] and plan["company"]["id"], it.get("hubspot")]).encode("utf-8")).hexdigest()[:16]
        public = {"firstname": first, "lastname": last, "jobtitle": title, "company": plan["company"]["name"] if plan["company"] else "",
                  "savedBefore": str(it.get("hubspot") or ""), "planId": plan_id}
        if not confirm:
            return 200, {"ok": True, "plan": public}
        if pid != plan_id:
            return 409, {"error": "HubSpot changed since the preview. Check it again, then save."}
        req = {"properties": props}
        if plan["company"]:
            req["associations"] = [{"to": {"id": plan["company"]["id"]},
                                    "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": CONTACT_TO_COMPANY}]}]
        try:
            api_call("hubspot", "POST", "/crm/v3/objects/contacts", req)
        except NoAnswer:
            update_mention(cid, mid, lambda x, r: x.update(hubspot="unknown"))
            crm_forget("hubspot")
            return 502, {"error": "HubSpot didn't answer in time. The contact may have been saved: check HubSpot before saving again."}
        except ApiError as e:
            crm_note("hubspot", False, str(e))
            return 502, {"error": "Not saved to HubSpot: " + str(e)}
        at = now_iso()
        update_mention(cid, mid, lambda x, r: x.update(hubspot=at))
        crm_forget("hubspot")
        crm_note("hubspot", True)
        return 200, {"ok": True, "savedAt": at}
    except Invalid as e:
        return 400, {"error": str(e)}


# ---------------------------------------------------------------- Meetily: the live transcript, read on this PC ----------------------------------------------------------------
# Meetily (github.com/Zackriya-Solutions/meetily, MIT) records and transcribes calls on this PC. While it records, its Rust core
# writes <recordings>/<meeting name>_<YYYY-MM-DD_HH-MM>/transcripts.json after every new or changed segment (a temp file, then a
# rename, so a read never sees half a file): {"version", "segments": [{"id", "text", "audio_start_time", "audio_end_time",
# "duration", "display_time": "[02:15]", "confidence", "sequence_id"}], "last_updated", "total_segments"}, next to metadata.json
# ({"meeting_name", "created_at", "status": "recording" | "completed", ...}). The recordings folder is %USERPROFILE%\Music\
# meetily-recordings on Windows (Documents\meetily-recordings without a Music folder). From src-tauri/src/audio/recording_saver.rs,
# audio_processing.rs and recording_preferences.rs (main branch, release v0.4.1, checked Oct 21, 2026).
# Overture only reads those two files. It never opens Meetily's database, never talks to Meetily or anything else over the network for
# it, and never sends audio or the transcript anywhere: the lines stay in this process's memory while the call runs, and only each
# mention and its sentence are saved. Untested against a real Meetily install: built from its source code, tested with fake folders.

MEETILY_POLL = 2.0              # seconds between looks at the transcript file
MEETILY_MAX_AGE = 6 * 3600      # a "recording" folder untouched for 6 hours is a recording that crashed, not a call
MEETILY_SLACK = 15 * 60         # Meetily started up to 15 minutes before the calendar call, or any time during it
MEETILY_QUIET = 120             # "Listening via Meetily" while a line came in the last 2 minutes
MEETILY_PIN_HOURS = 4           # a call picked in the panel stays picked this long
MEETILY_MAX_BYTES = 8_000_000
MEETILY_AUTOSTART = True        # tests turn this off and call meetily_step() themselves
MEETILY_LOCK = threading.Lock()
MEETILY = PerUser(lambda: dict(folder="", mtime=None, seqs={}, lines=[], callId="", lastLineAt=0.0, recording=False, error="",
                               pinned="", pinnedAt=0.0, pinnedFolder="", name=""))


def meetily_reset(keep_pin=True):
    with MEETILY_LOCK:
        pin = (MEETILY.get("pinned", ""), MEETILY.get("pinnedAt", 0.0), MEETILY.get("pinnedFolder", "")) if keep_pin else ("", 0.0, "")
        MEETILY.clear()
        MEETILY.update(folder="", mtime=None, seqs={}, lines=[], callId="", lastLineAt=0.0, recording=False, error="",
                       pinned=pin[0], pinnedAt=pin[1], pinnedFolder=pin[2], name="")



def _known_music_folder():
    """Windows' own Music folder (it may live on OneDrive or another drive), or None."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [("a", wintypes.DWORD), ("b", wintypes.WORD), ("c", wintypes.WORD), ("d", ctypes.c_ubyte * 8)]
        music = GUID(0x4BD8D571, 0x6D19, 0x48D3, (ctypes.c_ubyte * 8)(0xBE, 0x97, 0x42, 0x22, 0x20, 0x08, 0x0E, 0x43))  # FOLDERID_Music
        out = ctypes.c_wchar_p()
        if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(music), 0, None, ctypes.byref(out)) != 0:
            return None
        path = out.value
        ctypes.windll.ole32.CoTaskMemFree(out)
        return Path(path) if path else None
    except Exception:
        return None


def meetily_roots():
    """Where Meetily keeps its recordings: MEETILY_RECORDINGS_DIR when set, else its defaults (Music, then Documents)."""
    env = os.environ.get("MEETILY_RECORDINGS_DIR")
    if env:
        return [Path(env)]
    home = Path.home()
    cands = [_known_music_folder(), home / "Music", home / "OneDrive" / "Music", home / "Documents", home / "OneDrive" / "Documents"]
    out = []
    for c in cands:
        p = c / "meetily-recordings" if c else None
        if p and p.is_dir() and p not in out:
            out.append(p)
    return out


def _read_small_json(path, limit):
    try:
        if path.stat().st_size > limit:
            return None
        j = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError, UnicodeDecodeError):
        return None
    return j if isinstance(j, dict) else None


def meetily_recording(now_ts=None):
    """The newest meeting Meetily is recording right now: (folder, metadata) or (None, None)."""
    t = _time.time() if now_ts is None else now_ts
    best = None
    for root in meetily_roots():
        try:
            dirs = sorted((d for d in root.iterdir() if d.is_dir() and not d.name.startswith(".")), key=lambda d: d.stat().st_mtime, reverse=True)[:50]
        except OSError:
            continue
        for d in dirs:
            meta = _read_small_json(d / "metadata.json", 64_000)
            if not meta or meta.get("status") != "recording":
                continue
            try:
                seen = max(f.stat().st_mtime for f in (d / "metadata.json", d / "transcripts.json") if f.exists())
            except (OSError, ValueError):
                continue
            if t - seen > MEETILY_MAX_AGE:
                continue
            at = parse_dt(meta.get("created_at"))
            key = at.timestamp() if at else seen
            if not best or key > best[0]:
                best = (key, d, meta)
    return (best[1], best[2]) if best else (None, None)


def meetily_segments(folder):
    """transcripts.json -> lines in order [{"speaker", "time", "text", "seq"}]. Meetily doesn't say who spoke."""
    j = _read_small_json(folder / "transcripts.json", MEETILY_MAX_BYTES) or {}
    segs = []
    for s in j.get("segments") or [] if isinstance(j.get("segments"), list) else []:
        if not isinstance(s, dict) or not isinstance(s.get("text"), str) or not s["text"].strip():
            continue
        seq = s.get("sequence_id")
        if isinstance(seq, bool) or not isinstance(seq, int):
            continue
        m = re.search(r"(\d{1,2}:)?\d{1,2}:\d{2}", str(s.get("display_time") or ""))
        segs.append({"speaker": "", "time": _clock(m.group(0)) if m else _ms_clock((_num(s.get("audio_start_time")) or 0) * 1000),
                     "text": s["text"][:4000], "seq": seq})
    segs.sort(key=lambda x: x["seq"])
    return segs[:MAX_TRANSCRIPT_LINES]


def meetily_call_for(meta, now=None):
    """The calendar call this recording belongs to: the call picked in the panel for this recording, else the call running when
    Meetily started (from 15 minutes before it to its end). "" when none fits."""
    now = now or datetime.now(timezone.utc)
    with MEETILY_LOCK:
        pin, pin_at, same = MEETILY.get("pinned"), MEETILY.get("pinnedAt") or 0.0, MEETILY.get("pinnedFolder") == MEETILY.get("folder")
    if pin and same and _time.time() - pin_at < MEETILY_PIN_HOURS * 3600:
        return pin
    if not token_info():
        return ""
    started = parse_dt((meta or {}).get("created_at")) or now
    me_email = str((token_info() or {}).get("email", "")).lower()
    best = None
    for inv in upcoming_invites(fetch_events(), me_email, load_records(), now - timedelta(hours=6)):
        s, e = parse_dt(inv.get("start")), parse_dt(inv.get("end"))
        if s and e and s - timedelta(seconds=MEETILY_SLACK) <= started <= e:
            d = abs((started - s).total_seconds())
            if not best or d < best[0]:
                best = (d, inv["id"])
    return best[1] if best else ""


def meetily_feed(call_id, lines, first_new, final, now=None):
    """New Meetily lines -> the instant mentions pipeline for that call (like notes as you type, but read from the transcript).
    Only the new lines and the 6 before them are read (a company's explanation can come a sentence later)."""
    now = now or datetime.now(timezone.utc)
    records = load_records()
    _events, ctx = _call_context(call_id, records, now, live=True)
    if not ctx:
        return 0
    window = [{k: x[k] for k in ("speaker", "time", "text")} for x in lines[max(0, first_new - 6):]]
    found, orgs = find_all(window, ctx, None, final)
    del window
    block, new, go, wait, new_o, unqueue = save_mentions(call_id, ctx, found, "meetily", orgs, bump=False)
    _unqueue(unqueue)
    _queue_found(call_id, block, new, go, wait)
    return len(new) + len(new_o)


def meetily_step(now=None):
    """Look at Meetily once: read new transcript lines and feed them in. Returns how many new mentions were found."""
    now = now or datetime.now(timezone.utc)
    if not source_on("meetily"):
        meetily_reset()
        return 0
    with MEETILY_LOCK:
        tracked = MEETILY["folder"]
    folder, meta, final = None, None, False
    if tracked:  # the meeting already being read: keep it until Meetily says it is done
        meta = _read_small_json(Path(tracked) / "metadata.json", 64_000)
        if meta:
            folder, final = Path(tracked), meta.get("status") != "recording"
    if not folder or final:
        newer, newer_meta = meetily_recording()
        if newer and str(newer) != tracked:
            if folder and final:  # one last read of the one that just ended first
                _meetily_read(folder, meta, True, now)
            folder, meta, final = newer, newer_meta, False
    if not folder:
        meetily_reset()
        return 0
    n = _meetily_read(folder, meta, final, now)
    if final:
        meetily_reset(False)  # a call picked for this recording ends with it
    return n


def _meetily_read(folder, meta, final, now):
    try:
        mtime = (folder / "transcripts.json").stat().st_mtime_ns
    except OSError:
        mtime = None
    with MEETILY_LOCK:
        if MEETILY["folder"] != str(folder):  # another recording: a call picked for an earlier one doesn't carry over
            pin = (MEETILY["pinned"], MEETILY["pinnedAt"], MEETILY["pinnedFolder"]) if MEETILY["pinnedFolder"] == str(folder) else ("", 0.0, "")
            MEETILY.update(folder=str(folder), mtime=None, seqs={}, lines=[], callId="", lastLineAt=0.0, error="",
                           name=clean_text((meta or {}).get("meeting_name"), 120), pinned=pin[0], pinnedAt=pin[1], pinnedFolder=pin[2])
        MEETILY["recording"] = not final
        if mtime == MEETILY["mtime"] and not final:
            return 0
        seqs = dict(MEETILY["seqs"])
    segs = meetily_segments(folder) if mtime is not None else []
    first_new = next((i for i, s in enumerate(segs) if seqs.get(s["seq"]) != s["text"]), len(segs))
    try:
        call_id = meetily_call_for(meta)
    except (GoogleError, NotConnected):
        call_id = ""
    with MEETILY_LOCK:
        if call_id != MEETILY["callId"]:
            first_new = 0  # a different call (picked in the panel): read the whole transcript for it
        MEETILY.update(mtime=mtime, seqs={s["seq"]: s["text"] for s in segs}, lines=segs, callId=call_id)
        if first_new < len(segs):
            MEETILY["lastLineAt"] = _time.time()
    if not call_id or (first_new >= len(segs) and not final):
        return 0
    try:
        return meetily_feed(call_id, segs, first_new, final, now)
    except (Invalid, GoogleError, NotConnected) as e:
        with MEETILY_LOCK:
            MEETILY["error"] = str(e)[:200] or "couldn't read the call"
        return 0


def meetily_status(call_id=""):
    """GET /api/meetily: is Overture listening through Meetily, and for which call. No transcript text, ever."""
    on = source_on("meetily")
    with MEETILY_LOCK:
        st = dict(MEETILY)
    match = bool(st["callId"]) and (not call_id or st["callId"] == call_id)
    return {"on": on, "found": bool(meetily_roots()) if on else False, "recording": on and st["recording"], "callId": st["callId"] if on else "",
            "meeting": st["name"] if on else "", "lines": len(st["lines"]) if on and match else 0,
            "listening": on and st["recording"] and match and _time.time() - st["lastLineAt"] < MEETILY_QUIET,
            "pinned": st["pinned"] if on else "", "error": st["error"] if on else ""}


def meetily_pick(body):
    """POST /api/meetily/pick {callId}: the call the recording Meetily is making now belongs to (picked in the panel); "" lets Overture
    match it by time. The pick holds for that recording only."""
    if not isinstance(body, dict) or set(body) != {"callId"} or not isinstance(body["callId"], str):
        return 400, {"error": "send {callId}"}
    cid = body["callId"]
    if cid and not CALLID_RE.match(cid):
        return 400, {"error": "callId doesn't look right"}
    with MEETILY_LOCK:
        MEETILY.update(pinned=cid, pinnedAt=_time.time() if cid else 0.0, pinnedFolder=MEETILY["folder"] if cid else "", mtime=None)  # read again for the picked call
    return 200, meetily_status(cid)


# ---------------------------------------------------------------- Granola: notes and transcript after the call ----------------------------------------------------------------
# Granola's public API (docs.granola.ai, openapi.json, checked Oct 21, 2026): https://public-api.granola.ai, Authorization: Bearer
# <personal API key> (Business or Enterprise plan). GET /v1/notes?created_after&created_before&page_size (<= 30) lists notes
# (only ones with a finished summary); GET /v1/notes/{not_...}?include=transcript gives calendar_event (calendar_event_id,
# scheduled_start_time, invitees), summary_text / summary_markdown, web_url and transcript [{speaker {source, attribution me|them,
# name}, text, start_time, end_time}]; 413 means the transcript must be paged from GET /v1/notes/{id}/transcript (cursor).
# The transcript is read in memory and dropped: Overture keeps the note's title, link and summary, and each mention with its sentence.
# Untested against a real account.

GRANOLA_CHECK = 300           # look for finished calls' notes every 5 minutes
GRANOLA_AFTER = 5 * 60        # Granola needs a few minutes after a call to write the summary
GRANOLA_WINDOW = 24 * 3600    # calls that ended in the last day
GRANOLA_RETRY = 30 * 60       # no note yet: look again in 30 minutes
GRANOLA_MATCH = 20 * 60       # a note whose calendar event starts within 20 minutes of the call (and shares a guest or the title)
GRANOLA_STATE = PerUser(lambda: {"checkedAt": 0.0})


def _granola_get(path, deadline):
    return api_call("granola", "GET", path, deadline=deadline)


def _z(dt):
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def granola_note_for(inv, deadline=None):
    """The Granola note of this calendar call (with its transcript), or None. Matched by the calendar event id, else by the
    start time and a shared guest (or the same title), from each note without its transcript: only the matching note's
    transcript is fetched, never another meeting's."""
    start, end = parse_dt(inv.get("start")), parse_dt(inv.get("end"))
    if not start:
        return None
    q = urllib.parse.urlencode({"created_after": _z(start - timedelta(hours=2)), "created_before": _z((end or start) + timedelta(hours=12)), "page_size": 30})
    notes, cursor = [], None
    for _ in range(3):
        j = _granola_get("/v1/notes?" + q + ("&cursor=" + urllib.parse.quote(cursor) if cursor else ""), deadline)
        notes += [n for n in j.get("notes") or [] if isinstance(n, dict) and re.fullmatch(r"not_[A-Za-z0-9]{14}", str(n.get("id") or ""))]
        cursor = j.get("cursor") if j.get("hasMore") and isinstance(j.get("cursor"), str) else None
        if not cursor:
            break
    guests = {a["email"] for a in inv.get("attendees") or []}
    best = None
    for n in notes[:8]:
        try:
            d = _granola_get("/v1/notes/" + n["id"], deadline)
        except ApiError as e:
            if e.status == 404:
                continue
            raise
        ce = d.get("calendar_event") if isinstance(d.get("calendar_event"), dict) else {}
        if ce.get("calendar_event_id") and safe_id(ce["calendar_event_id"]) == re.sub(r"-\d+$", "", inv["id"]):
            best = (-1.0, n["id"], d)
            break
        st = parse_dt(ce.get("scheduled_start_time"))
        invitees = {str(x.get("email") or "").lower() for x in ce.get("invitees") or [] if isinstance(x, dict)}
        same = (guests & invitees) or norm_name(ce.get("event_title") or d.get("title") or "") == norm_name(inv.get("title") or "")
        if st and abs((st - start).total_seconds()) <= GRANOLA_MATCH and same:
            diff = abs((st - start).total_seconds())
            if not best or diff < best[0]:
                best = (diff, n["id"], d)
    if not best:
        return None
    _diff, nid, d = best
    try:
        return _granola_get("/v1/notes/" + nid + "?include=transcript", deadline)
    except ApiError as e:
        if e.status != 413:
            raise
    d["transcript"] = granola_transcript_pages(nid, deadline)  # too big to send inline: page it
    return d


def granola_transcript_pages(note_id, deadline):
    out, cursor = [], None
    for _ in range(40):
        j = _granola_get("/v1/notes/" + note_id + "/transcript?page_size=100" + ("&cursor=" + urllib.parse.quote(cursor) if cursor else ""), deadline)
        out += [t for t in j.get("transcript") or [] if isinstance(t, dict)]
        cursor = j.get("cursor") if j.get("hasMore") and isinstance(j.get("cursor"), str) else None
        if not cursor or len(out) >= MAX_TRANSCRIPT_LINES:
            break
    return out


def granola_lines(note, me_name=""):
    """Granola's transcript -> lines. "me" is you (so "our CTO" from you is Spotify's); a named speaker keeps the name."""
    items = [t for t in note.get("transcript") or [] if isinstance(t, dict) and isinstance(t.get("text"), str) and t["text"].strip()]
    t0 = next((parse_dt(t.get("start_time")) for t in items if parse_dt(t.get("start_time"))), None)
    lines = []
    for t in items[:MAX_TRANSCRIPT_LINES]:
        sp = t.get("speaker") if isinstance(t.get("speaker"), dict) else {}
        who = clean_text(sp.get("name"), 80) or ((me_name or "Your side") if sp.get("attribution") == "me" else "")
        st = parse_dt(t.get("start_time"))
        lines.append({"speaker": who, "time": _ms_clock((st - t0).total_seconds() * 1000) if st and t0 else "", "text": t["text"][:4000]})
    return lines


def granola_fetch(call_id, now=None, forced=False):
    """Read Granola's note for one call: its transcript goes through the mentions pipeline (then dropped), and the note's title,
    link and summary are kept under records.granola. Returns (status code, body)."""
    now = now or datetime.now(timezone.utc)
    if not source_on("granola"):
        return 403, {"error": "Turn on Granola in Settings > Research sources and privacy first."}
    if not granola_key():
        return 409, {"error": "Granola isn't connected. See Settings > Setup guides > After the call with Granola."}
    if not token_info():
        return 409, {"error": "Connect Google Calendar first, so Overture knows the call."}
    try:
        records = load_records()
        _events, ctx = _call_context(call_id, records, now)
        if not ctx:
            return 404, {"error": "That call isn't in your calendar."}
        try:
            note = granola_note_for(ctx["invite"], _time.time() + 25)
        except ApiError as e:
            crm_note("granola", False, str(e))
            return 502, {"error": str(e)}
        crm_note("granola", True)
        if not note:
            _granola_save(call_id, {"status": "none", "tried": now_iso()})
            return 404, {"error": "Granola has no finished note for this call yet. Granola writes it a few minutes after the call."}
        lines = granola_lines(note, (token_info() or {}).get("name", ""))
        found, orgs = find_all(lines, ctx, None, True)
        n = len(lines)
        del lines
        note.pop("transcript", None)  # the transcript goes no further
        # read by itself after the call: Settings > Mentions > automatic look-up decides; Read Granola's note is your own action
        block, new, go, wait, new_o, unqueue = save_mentions(call_id, ctx, found, "granola", orgs, auto=not forced)
        url = safe_url(note.get("web_url"))
        host = (urllib.parse.urlsplit(url).hostname or "") if url else ""
        _granola_save(call_id, {"status": "done", "noteId": str(note.get("id") or ""), "title": clip(note.get("title"), 200),
                                "url": url if host == "granola.ai" or host.endswith(".granola.ai") else "",
                                "summary": clip(note.get("summary_markdown") or note.get("summary_text"), 6000), "lines": n,
                                "found": len(new) + len(new_o), "at": now_iso()})
    except Invalid as e:
        return 400, {"error": str(e)}
    except (GoogleError, NotConnected):
        return 502, {"error": "Google Calendar didn't answer, so Overture can't check the call. Try again."}
    _unqueue(unqueue)
    _queue_found(call_id, block, new, go, wait)
    out = mentions_body(call_id, ctx["met"], requeue=False)
    out["found"] = len(new) + len(new_o)
    return 200, out


def _granola_save(call_id, entry):
    with RECORDS_LOCK:
        r = load_records()
        g = r.setdefault("granola", {})
        if entry.get("status") == "none" and (g.get(call_id) or {}).get("status") == "done":
            return  # a note read before stays
        g[call_id] = entry
        while len(g) > MAX_MENTION_CALLS:
            g.pop(min(g, key=lambda k: str((g[k] or {}).get("at") or (g[k] or {}).get("tried") or "")))
        if len(json.dumps(r)) > MAX_RECORDS_BYTES:
            raise Invalid("the records store is full")
        save_json(records_path(), r)


def granola_view(records, call_id):
    g = (records.get("granola") or {}).get(call_id)
    if not isinstance(g, dict):
        return None
    return {"status": "done" if g.get("status") == "done" else "none", "title": clean_text(g.get("title"), 200), "url": safe_url(g.get("url")),
            "summary": str(g.get("summary") or "")[:6000], "at": str(g.get("at") or g.get("tried") or ""), "found": int(g.get("found") or 0)}


def granola_step(now=None):
    """After a call: fetch Granola's note for calls that ended 5 minutes to a day ago (each once; no note yet: again in 30 minutes)."""
    now = now or datetime.now(timezone.utc)
    if not source_on("granola") or not granola_key() or not token_info():
        return 0
    if _time.time() - GRANOLA_STATE["checkedAt"] < GRANOLA_CHECK:
        return 0
    GRANOLA_STATE["checkedAt"] = _time.time()
    records, me_email = load_records(), str((token_info() or {}).get("email", "")).lower()
    done = 0
    for ev in fetch_events():
        start, end = _event_times(ev)
        if not end or not now - timedelta(seconds=GRANOLA_WINDOW) <= end <= now - timedelta(seconds=GRANOLA_AFTER):
            continue
        inv = event_to_invite(ev, me_email, records)
        if not inv:
            continue
        g = (records.get("granola") or {}).get(inv["id"]) or {}
        tried = parse_dt(g.get("tried"))
        if g.get("status") == "done" or (tried and (now - tried).total_seconds() < GRANOLA_RETRY):
            continue
        granola_fetch(inv["id"], now)
        done += 1
        if done >= 3:
            break
    return done


def _sources_loop():
    """Meetily every 2 seconds, Granola every 5 minutes. Never lets one failure stop the loop."""
    while True:
        for step in (meetily_step, granola_step):
            try:
                step()
            except Exception as e:  # the file or the API answered something Overture didn't expect
                with MEETILY_LOCK:
                    if step is meetily_step:
                        MEETILY["error"] = "Meetily: " + type(e).__name__
        _time.sleep(MEETILY_POLL)


def start_sources_loop():
    if MEETILY_AUTOSTART:
        threading.Thread(target=_sources_loop, name="moab-sources", daemon=True).start()


# ---------------------------------------------------------------- request guards ----------------------------------------------------------------

EXTENSION_DIR = HERE / "extension"
EXT_ID_RE = re.compile(r"^[a-p]{32}$")
_EXT_CACHE = {}


def extension_id_from_key(key_b64):
    """Chrome's extension id for a manifest "key": the SHA-256 of the public key, first 32 hex digits written with a-p."""
    der = base64.b64decode(key_b64)
    return "".join(chr(ord("a") + int(c, 16)) for c in hashlib.sha256(der).hexdigest()[:32])


def extension_ids():
    """Overture's Chrome extension (fixed by the "key" in extension/manifest.json), plus any ids in MOAB_EXTENSION_IDS."""
    out = []
    try:
        path = EXTENSION_DIR / "manifest.json"
        mt = path.stat().st_mtime_ns
        if _EXT_CACHE.get("mtime") != mt:  # read once, again only when the manifest changes
            key = json.loads(path.read_text(encoding="utf-8")).get("key")
            _EXT_CACHE.update(mtime=mt, id=extension_id_from_key(key) if isinstance(key, str) and key else "")
        if _EXT_CACHE.get("id"):
            out.append(_EXT_CACHE["id"])
    except (OSError, ValueError, TypeError):
        pass
    out += [x.strip() for x in os.environ.get("MOAB_EXTENSION_IDS", "").split(",") if EXT_ID_RE.match(x.strip())]
    return list(dict.fromkeys(out))


def frame_ancestors(raw_path):
    """'self' everywhere; the in-call panel also lets Overture's extension frame it."""
    p = urllib.parse.unquote(urllib.parse.urlsplit(str(raw_path)).path).replace("\\", "/").lower()
    if p.rstrip("/").split("/")[-1] == "panel.html":
        return " ".join(["'self'"] + ["chrome-extension://" + i for i in extension_ids()])
    return "'self'"


def host_ok(headers):
    return headers.get("Host") in allowed_hosts()


def read_guard_ok(headers):
    """Reads of private data: right host, and never as a script or fetch from another site."""
    return host_ok(headers) and headers.get("Sec-Fetch-Site", "same-origin") in ("same-origin", "none")


def write_guard_ok(headers):
    """Writes: right host, the X-MOAB header (other sites can't send it without a preflight we never answer), and our own Origin."""
    if not host_ok(headers) or headers.get("X-MOAB") != "1":
        return False
    origin = headers.get("Origin")
    if origin:
        return origin in allowed_origins()
    ref = headers.get("Referer") or ""
    return any(ref.startswith(o + "/") for o in allowed_origins())


def hidden_path(path):
    """Any path segment that starts with a dot (after decoding, any case, either slash)."""
    p = urllib.parse.unquote(str(path)).replace("\\", "/").lower()
    return any(seg.startswith(".") for seg in p.split("/") if seg)


def page(title, message, link="/", link_text="Back to Overture"):
    return ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>"
            + html_escape(title) + " · Overture</title><style>body{font:15px/1.5 system-ui,sans-serif;color:#1e1f21;background:#f6f5f4;margin:0;padding:48px 16px}"
            "main{max-width:480px;margin:0 auto;background:#fff;border:1px solid #edeae9;border-radius:16px;padding:28px}"
            "h1{font-size:20px;line-height:1.35;margin:0 0 8px}p{margin:0 0 16px;color:#48494b}a{color:#13773a;font-weight:500}</style><main><h1>"
            + html_escape(title) + "</h1><p>" + html_escape(message) + "</p><a href='" + html_escape(link) + "'>" + html_escape(link_text) + "</a></main>")


class Handler(SimpleHTTPRequestHandler):
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map,
                      ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".md": "text/plain; charset=utf-8"}

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        # Only Overture's own pages may frame Overture (the In-call page frames the panel). The in-call panel may also be framed by
        # Overture's Chrome extension (its side panel), and by no other site.
        self.send_header("Content-Security-Policy", "frame-ancestors " + frame_ancestors(getattr(self, "path", "") or ""))
        super().end_headers()

    def log_message(self, fmt, *args):
        # Query strings can hold an OAuth code or state: never write them to the log.
        args = tuple(re.sub(r"\?\S*", "?[hidden]", a) if isinstance(a, str) else a for a in args)
        super().log_message(fmt, *args)

    def send_body(self, code, data, ctype, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def send_json(self, code, body):
        self.send_body(code, json.dumps(body).encode("utf-8"), "application/json")

    def send_page(self, code, title, message):
        self.send_body(code, page(title, message).encode("utf-8"), "text/html; charset=utf-8")

    def redirect(self, location):
        self.send_body(302, b"", "text/plain", {"Location": location})

    def read_json(self, limit=200_000):
        length = int(self.headers.get("Content-Length") or 0)
        if length > limit and length <= 4 * MAX_MENTION_BODY:
            left = length  # read what was sent, so the page gets the 413 instead of a reset connection
            while left > 0:
                left -= len(self.rfile.read(min(left, 65536)) or b"x" * left)
        if length < 0 or length > limit:
            raise ValueError("size")
        return json.loads(self.rfile.read(length) or b"{}")

    def route_path(self):
        return urllib.parse.urlsplit(self.path).path

    def parse_request(self):
        _USER.set(None)  # every request on a kept-alive connection says again who it is for
        ok = super().parse_request()
        if ok and HOSTED:
            _USER.set(session_user(self.headers))
        return ok

    def signed_out(self):
        """The shared site: an account's routes need that account signed in. True (and the answer sent) when nobody is."""
        if not HOSTED or _USER.get():
            return False
        path = self.route_path()
        if path in ("/data/live.js", "/api/status"):
            with as_user(SIGNED_OUT):  # the connect screen: Google is set up, nothing is connected
                st = status_body()
            if path == "/api/status":
                self.send_json(200, st)
            else:
                self.send_body(200, ("window.MOAB_STATUS = " + script_json(st) + ";\nwindow.MOAB_LIVE = null;\n").encode("utf-8"), "text/javascript")
            return True
        if path.startswith("/api/") or path == "/auth/google/disconnect":
            self.send_json(401, {"error": "sign in first"})
            return True
        return False

    def translate_path(self, path):
        """Never map a URL onto .data or another dot folder, however it is spelled (Windows also calls .data DATA~1)."""
        p = super().translate_path(path)
        real, root = os.path.normcase(os.path.realpath(p)), os.path.normcase(os.path.realpath(self.directory))
        data = os.path.normcase(os.path.realpath(DATA_ROOT))
        inside = real[len(root):].split(os.sep) if real.startswith(root + os.sep) else []
        if real == data or real.startswith(data + os.sep) or any(seg.startswith(".") for seg in inside):
            return os.path.join(self.directory, "__no_such_file__")
        return p

    def do_GET(self):
        # Absolute-form targets (x://...) and renamed hosts (DNS rebinding) get nothing, static files included.
        if not self.path.startswith("/") or not host_ok(self.headers):
            return self.send_json(403, {"error": "not allowed"})
        path = self.route_path()
        if self.signed_out():
            return None
        if hidden_path(path):  # .data holds the Google client secret, tokens and records: never served as files
            return self.send_json(404, {"error": "not found"})
        if path == "/api/status":
            return self.send_json(200, status_body())
        if path == "/data/live.js":
            if not read_guard_ok(self.headers):
                return self.send_body(200, b"window.MOAB_LIVE = null;\n", "text/javascript")
            return self.send_body(200, live_script().encode("utf-8"), "text/javascript")
        if path == "/api/records":
            if not read_guard_ok(self.headers):
                return self.send_json(403, {"error": "not allowed"})
            return self.send_json(200, load_records())
        if path == "/api/settings":
            if not read_guard_ok(self.headers):
                return self.send_json(403, {"error": "not allowed"})
            return self.send_json(200, {"settings": effective_settings(load_records()), "defaults": default_settings()})
        if path == "/api/claude-key":
            if not read_guard_ok(self.headers):
                return self.send_json(403, {"error": "not allowed"})
            return self.send_json(200, claude_key_state())
        if path == "/api/research":
            if not read_guard_ok(self.headers):
                return self.send_json(403, {"error": "not allowed"})
            return self.send_json(200, research_poll())
        if path == "/api/meetily":
            if not read_guard_ok(self.headers):
                return self.send_json(403, {"error": "not allowed"})
            cid = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.path).query)).get("callId", "")
            if cid and not CALLID_RE.match(cid):
                return self.send_json(400, {"error": "bad callId"})
            return self.send_json(200, meetily_status(cid))
        if path == "/api/mentions":
            if not read_guard_ok(self.headers):
                return self.send_json(403, {"error": "not allowed"})
            cid = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.path).query)).get("callId", "")
            if not CALLID_RE.match(cid):
                return self.send_json(400, {"error": "bad callId"})
            return self.send_json(200, mentions_body(cid, calendar_met()))
        if path == "/auth/google":
            client = google_client()
            if not client:
                return self.send_page(503, "Google sign-in isn't set up yet", "Follow the steps in docs/GOOGLE-SETUP.md (in Overture: Settings > Setup guides > Connect Google Calendar) to add your Google OAuth client, then restart server.py.")
            url, state = new_auth_request(client[0])
            if HOSTED:  # the callback must come back to this same browser, so nobody can sign you in as them
                return self.send_body(302, b"", "text/plain", {"Location": url, "Set-Cookie": OAUTH_COOKIE + "=" + state +
                                      "; Path=/auth/google/callback; Max-Age=" + str(STATE_TTL) + "; HttpOnly; Secure; SameSite=Lax"})
            return self.redirect(url)
        if path == "/auth/google/callback":
            return self.oauth_callback()
        return super().do_GET()

    def do_HEAD(self):
        if not self.path.startswith("/") or not host_ok(self.headers):
            return self.send_json(403, {"error": "not allowed"})
        path = self.route_path()
        if hidden_path(path) or path.startswith("/api/") or path.startswith("/auth/") or path == "/data/live.js":
            return self.send_json(404, {"error": "not found"})
        return super().do_HEAD()

    def oauth_callback(self):
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.path).query))
        if HOSTED and not hmac.compare_digest(_cookie_value(self.headers, OAUTH_COOKIE), str(q.get("state") or "")):
            return self.send_page(400, "Sign-in expired", "That sign-in didn't start in this browser. Press Connect Google Calendar again.")
        verifier = take_state(q.get("state"))
        if q.get("error"):
            msg = "You didn't allow access, so nothing was connected." if q["error"] == "access_denied" else "Google stopped the sign-in (" + q["error"][:60] + ")."
            return self.send_page(400, "Not connected", msg)
        if not verifier:
            return self.send_page(400, "Sign-in expired", "That sign-in link was old or already used. Press Connect Google Calendar again.")
        if not q.get("code"):
            return self.send_page(400, "Not connected", "Google sent no sign-in code. Try again.")
        try:
            tok = exchange_code(q["code"], verifier)
        except GoogleError as e:
            return self.send_page(400, "Not connected", str(e))
        if HOSTED:  # signed in: this browser now opens this Google account's own Overture
            sid = new_session(tok["email"])
            return self.send_body(302, b"", "text/plain", {"Location": "/#/home", "Set-Cookie": session_cookie(sid)})
        return self.redirect("/#/home")

    def do_PUT(self):
        path = self.route_path()
        if self.signed_out():
            return None
        if path == "/api/settings":
            # Settings: only from this page (X-MOAB + our Origin), JSON only, at most 64 KB, every value checked (save_settings).
            if not write_guard_ok(self.headers) or self.headers.get_content_type() != "application/json":
                return self.send_json(403, {"error": "not allowed"})
            try:
                body = self.read_json(MAX_SETTINGS_BYTES)
            except ValueError as e:
                return self.send_json(413 if str(e) == "size" else 400, {"error": "settings are too big" if str(e) == "size" else "bad request"})
            except RecursionError:
                return self.send_json(400, {"error": "bad request"})
            try:
                return self.send_json(200, {"ok": True, "settings": save_settings(body)})
            except Invalid as e:
                return self.send_json(400, {"error": str(e)})
        if path == "/api/claude-key":
            # The Claude key from Settings: only from this page, JSON, tiny, must look like an Anthropic key. Saved in .data/ (never served).
            if not write_guard_ok(self.headers) or self.headers.get_content_type() != "application/json":
                return self.send_json(403, {"error": "not allowed"})
            try:
                body = self.read_json(2048)
            except (ValueError, RecursionError):
                return self.send_json(400, {"error": "bad request"})
            key = str((body or {}).get("key") or "").strip() if isinstance(body, dict) else ""
            if not CLAUDE_KEY_RE.fullmatch(key):
                return self.send_json(400, {"error": "That doesn't look like a Claude API key (they start with sk-ant-)."})
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            save_json(claude_key_path(), {"key": key})
            return self.send_json(200, dict(claude_key_state(), ok=True))
        if not path.startswith("/api/records/"):
            return self.send_json(404, {"error": "not found"})
        self.handle_write(path.rsplit("/", 1)[1])

    def handle_write(self, kind):
        if not write_guard_ok(self.headers) or self.headers.get_content_type() != "application/json":
            return self.send_json(403, {"error": "not allowed"})
        try:
            body = self.read_json()
        except (ValueError, RecursionError):
            return self.send_json(400, {"error": "bad request"})
        try:
            return self.send_json(200, {"ok": True, "saved": write_records(kind, body)})
        except Invalid as e:
            return self.send_json(400, {"error": str(e)})

    def do_POST(self):
        path = self.route_path()
        if self.signed_out():
            return None
        if path == "/api/claude-key/remove":
            if not write_guard_ok(self.headers):
                return self.send_json(403, {"error": "not allowed"})
            remove_file(claude_key_path())
            return self.send_json(200, dict(claude_key_state(), ok=True))
        if path == "/api/records/apply":
            return self.handle_write("apply")
        if path == "/auth/google/disconnect":
            if not write_guard_ok(self.headers):
                return self.send_json(403, {"error": "not allowed"})
            disconnect()
            if HOSTED:  # signing out of the shared site also ends this browser's session
                end_sessions(_USER.get())
                return self.send_body(200, b'{"ok": true}', "application/json", {"Set-Cookie": session_cookie("", 0)})
            return self.send_json(200, {"ok": True})
        if path == "/api/research":
            if not write_guard_ok(self.headers) or self.headers.get_content_type() != "application/json":
                return self.send_json(403, {"error": "not allowed"})
            try:
                body = self.read_json()
            except (ValueError, RecursionError):
                return self.send_json(400, {"error": "bad request"})
            if not isinstance(body, dict) or set(body) != {"email"}:
                return self.send_json(400, {"error": "send {email}"})
            if not source_on("web"):
                return self.send_json(403, {"error": "Web research is off in Settings > Research sources & privacy."})
            return self.send_json(*request_research(body["email"]))
        if path == "/api/research/org":  # look a company on your calls up again now: the same guards as /api/research
            if not write_guard_ok(self.headers) or self.headers.get_content_type() != "application/json":
                return self.send_json(403, {"error": "not allowed"})
            try:
                body = self.read_json(2_000)
            except (ValueError, RecursionError):
                return self.send_json(400, {"error": "bad request"})
            if not isinstance(body, dict) or set(body) != {"domain"} or not isinstance(body["domain"], str):
                return self.send_json(400, {"error": "send {domain}"})
            if not source_on("web"):
                return self.send_json(403, {"error": "Web research is off in Settings > Research sources & privacy."})
            return self.send_json(*request_org_research(body["domain"]))
        if path in ("/api/meetily/pick", "/api/granola/fetch"):
            # Meetily's call and Granola's note: only from this page (X-MOAB + our Origin), JSON only.
            if not write_guard_ok(self.headers) or self.headers.get_content_type() != "application/json":
                return self.send_json(403, {"error": "not allowed"})
            try:
                body = self.read_json(2_000)
            except (ValueError, RecursionError):
                return self.send_json(400, {"error": "bad request"})
            if path == "/api/meetily/pick":
                return self.send_json(*meetily_pick(body))
            if not isinstance(body, dict) or set(body) != {"callId"} or not isinstance(body["callId"], str) or not CALLID_RE.match(body["callId"]):
                return self.send_json(400, {"error": "send {callId}"})
            return self.send_json(*granola_fetch(body["callId"], forced=True))
        if path in ("/api/mentions", "/api/mentions/live", "/api/mentions/pick", "/api/mentions/hubspot"):
            # People mentioned on a call: only from this page (X-MOAB + our Origin), JSON only, with a size limit.
            if not write_guard_ok(self.headers) or self.headers.get_content_type() != "application/json":
                return self.send_json(403, {"error": "not allowed"})
            try:
                body = self.read_json(MAX_MENTION_BODY if path == "/api/mentions" else 20_000)
            except ValueError as e:
                if str(e) == "size":
                    return self.send_json(413, {"error": "That transcript is too big (1 MB of text at most)."})
                return self.send_json(400, {"error": "bad request"})
            except RecursionError:
                return self.send_json(400, {"error": "bad request"})
            handler = {"/api/mentions": mentions_post, "/api/mentions/live": mentions_live, "/api/mentions/pick": mention_action,
                       "/api/mentions/hubspot": mention_hubspot}[path]
            return self.send_json(*handler(body))
        if path == "/api/hubspot/save":
            # Writes to HubSpot: only from this page (X-MOAB + our Origin), and only with confirm: true (see hubspot_save).
            if not write_guard_ok(self.headers) or self.headers.get_content_type() != "application/json":
                return self.send_json(403, {"error": "not allowed"})
            try:
                body = self.read_json()
            except (ValueError, RecursionError):
                return self.send_json(400, {"error": "bad request"})
            return self.send_json(*hubspot_save(body))
        if path not in ("/api/brief", "/api/ask"):
            return self.send_json(404, {"error": "not found"})
        # Only this page may spend the Claude key: other sites can't send JSON here without a preflight we never answer,
        # and a renamed host (DNS rebinding) is turned away.
        if not host_ok(self.headers) or self.headers.get_content_type() != "application/json":
            return self.send_json(403, {"error": "not allowed"})
        if path == "/api/ask" and not write_guard_ok(self.headers):
            return self.send_json(403, {"error": "not allowed"})
        try:
            body = self.read_json()
        except (ValueError, RecursionError):
            return self.send_json(400, {"error": "bad request"})
        if path == "/api/ask":
            return self.send_json(*answer_question(body))
        if not claude_on():
            return self.send_json(503, {"error": "no Claude key set"})
        self.send_json(*write_brief(brief_facts(body, load_records())))


def main(argv):
    global PORT
    if "--port" in argv:
        PORT = int(argv[argv.index("--port") + 1])
    elif os.environ.get("MOAB_PORT"):
        PORT = int(os.environ["MOAB_PORT"])
    elif HOSTED and os.environ.get("PORT"):  # Render says which port to listen on
        PORT = int(os.environ["PORT"])
    ensure_data_dir()
    if HOSTED:
        try:
            n = db_restore()
        except Exception as e:  # serving from an empty disk would overwrite the saved copy: stop, Render starts it again
            sys.exit(f"[db] {type(e).__name__}: could not read the saved files from Postgres, so Overture did not start")
        server = ThreadingHTTPServer(("0.0.0.0", PORT), partial(Handler, directory=str(HERE)))
        print(f"Overture shared site {PUBLIC_URL} on port {PORT} ({n} saved files restored; Google sign-in "
              f"{'set up' if google_client() else 'NOT set up: add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET'})", flush=True)
        return server.serve_forever()  # Meetily and Granola read files on your own PC, so the shared site doesn't poll them
    server = ThreadingHTTPServer(("127.0.0.1", PORT), partial(Handler, directory=str(HERE)))
    st = status_body()
    g = "connected" if st["google"]["connected"] else "set up, not connected" if st["google"]["configured"] else "not set up"
    crm = "; ".join(SERVICE_NAMES[s] + (" set up" if st[s]["configured"] else " not set up") for s in SERVICE_NAMES)
    print(f"Overture on http://localhost:{PORT}  (Google Calendar {g}; Claude {'on' if claude_on() else 'off'}; {crm})", flush=True)
    start_sources_loop()  # Meetily (when on in Settings) and Granola (when on and connected)
    server.serve_forever()


if __name__ == "__main__":
    main(sys.argv[1:])
