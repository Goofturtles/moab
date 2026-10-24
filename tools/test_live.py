"""Tests for Overture's live mode (server.py): calendar mapping, company naming, job changes, live.js escaping,
OAuth state and PKCE, the records store and its write guard, invitee research, and HubSpot and Gong (fake HTTP).
Fake data only: nothing here touches the network.

Run:  tks-spotify/.venv/Scripts/python.exe -I tks-spotify/centralize/tools/test_live.py
"""
import base64
import hashlib
import http.client
import json
import os
import re
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
from datetime import datetime, timedelta, timezone
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

TMP = tempfile.mkdtemp(prefix="overture-test-")
os.environ["OVERTURE_DATA_DIR"] = TMP  # before the import: server.py reads it once
for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "HUBSPOT_TOKEN", "GONG_ACCESS_KEY", "GONG_ACCESS_SECRET", "GONG_BASE_URL",
          "GRANOLA_API_KEY", "MEETILY_RECORDINGS_DIR", "OVERTURE_EXTENSION_IDS"):
    os.environ.pop(k, None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server as S  # noqa: E402

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)  # 8:00 in New York (EDT)
ME = {"email": "chris@spotify.com", "name": "Chris Park"}


def ev(eid, start, minutes, attendees, **extra):
    s = datetime.fromisoformat(start)
    e = s + timedelta(minutes=minutes)
    out = {"id": eid, "status": "confirmed", "summary": extra.pop("summary", "Call " + eid),
           "start": {"dateTime": s.isoformat()}, "end": {"dateTime": e.isoformat()}, "attendees": attendees}
    out.update(extra)
    return out


def att(email, name=None, **kw):
    a = {"email": email, "responseStatus": "accepted"}
    if name:
        a["displayName"] = name
    a.update(kw)
    return a


SELF = att("chris@spotify.com", "Chris Park", self=True)


class Fresh(unittest.TestCase):
    def setUp(self):
        for f in Path(TMP).glob("*"):
            if f.is_file():
                f.unlink()
        S.PENDING.clear()
        S.clear_cache()
        S.LOOKUP_CACHE.clear()
        with S.LIVE_LOCK:
            S.LIVE_SEGMENTS.clear()


class TimeTests(unittest.TestCase):
    def test_eastern_offsets(self):
        self.assertEqual(S.et_offset(datetime(2026, 1, 15, tzinfo=timezone.utc)), timedelta(hours=-5))
        self.assertEqual(S.et_offset(datetime(2026, 7, 15, tzinfo=timezone.utc)), timedelta(hours=-4))
        # 2026: daylight time starts Sun Mar 8 at 7:00 UTC and ends Sun Nov 1 at 6:00 UTC
        self.assertEqual(S.et_offset(datetime(2026, 3, 8, 6, 59, tzinfo=timezone.utc)), timedelta(hours=-5))
        self.assertEqual(S.et_offset(datetime(2026, 3, 8, 7, 0, tzinfo=timezone.utc)), timedelta(hours=-4))
        self.assertEqual(S.et_offset(datetime(2026, 11, 1, 5, 59, tzinfo=timezone.utc)), timedelta(hours=-4))
        self.assertEqual(S.et_offset(datetime(2026, 11, 1, 6, 0, tzinfo=timezone.utc)), timedelta(hours=-5))

    def test_when_string_matches_sample_format(self):
        s = datetime(2026, 10, 20, 14, 0, tzinfo=timezone.utc)
        self.assertEqual(S.when_string(s, s + timedelta(minutes=45)), "Tue Oct 20, 10:00 to 10:45 ET")
        w = datetime(2026, 12, 3, 14, 5, tzinfo=timezone.utc)  # winter: UTC-5
        self.assertEqual(S.when_string(w, w + timedelta(minutes=30)), "Thu Dec 3, 9:05 to 9:35 ET")


class InviteMapping(unittest.TestCase):
    def test_event_to_invite(self):
        e = ev("abc123_20261020T140000Z", "2026-10-20T14:00:00+00:00", 45, [
            SELF, att("priya.raman@northwind-freight.com", "Priya Raman"), att("marcus.bell@northwind-freight.com"),
            att("room-4@resource.calendar.google.com", "Room 4", resource=True)],
            summary="Discovery: Northwind and Portal", hangoutLink="https://meet.google.com/abc-defg-hij",
            description="<p>Marcus says upgrades <b>hurt</b>.</p><br>They looked at Port &amp; Roadie.")
        inv = S.event_to_invite(e, ME["email"], S.empty_records())
        self.assertEqual(inv["id"], "abc123_20261020T140000Z")
        self.assertEqual(inv["company"], "Northwind Freight")
        self.assertEqual(inv["domain"], "northwind-freight.com")
        self.assertEqual(inv["when"], "Tue Oct 20, 10:00 to 10:45 ET")
        self.assertEqual(inv["meetingCode"], "abc-defg-hij")
        self.assertEqual([a["email"] for a in inv["attendees"]], ["priya.raman@northwind-freight.com", "marcus.bell@northwind-freight.com"])
        self.assertEqual(inv["attendees"][1]["name"], "Marcus Bell")  # no display name: made from the address
        self.assertEqual(inv["notes"], "Marcus says upgrades hurt.\n\nThey looked at Port & Roadie.")
        self.assertTrue(inv["start"].startswith("2026-10-20T10:00:00-04:00"))
        for k in ("versionFile", "backstageSince", "afterNotes", "title", "end"):
            self.assertIn(k, inv)

    def test_conference_id_fallback(self):
        e = ev("x", "2026-10-20T14:00:00+00:00", 30, [SELF, att("a@acme.com")],
               conferenceData={"conferenceId": "xyz-abcd-efg", "conferenceSolution": {"key": {"type": "hangoutsMeet"}}})
        self.assertEqual(S.event_to_invite(e, ME["email"], S.empty_records())["meetingCode"], "xyz-abcd-efg")

    def test_skipped_events(self):
        rec = S.empty_records()
        allday = {"id": "d", "summary": "Offsite", "start": {"date": "2026-10-21"}, "end": {"date": "2026-10-22"}, "attendees": [SELF, att("a@acme.com")]}
        cancelled = ev("c", "2026-10-21T14:00:00+00:00", 30, [SELF, att("a@acme.com")], status="cancelled")
        declined = ev("n", "2026-10-21T14:00:00+00:00", 30, [att("chris@spotify.com", self=True, responseStatus="declined"), att("a@acme.com")])
        alone = ev("s", "2026-10-21T14:00:00+00:00", 30, [SELF])
        no_guests = ev("g", "2026-10-21T14:00:00+00:00", 30, [])
        for e in (allday, cancelled, declined, alone, no_guests):
            self.assertIsNone(S.event_to_invite(e, ME["email"], rec), e["id"])

    def test_safe_ids_and_unique(self):
        e1 = ev("a b<c>", "2026-10-21T14:00:00+00:00", 30, [SELF, att("a@acme.com")])
        e2 = ev("a b<c>", "2026-10-22T14:00:00+00:00", 30, [SELF, att("a@acme.com")])
        live = S.build_live([e1, e2], ME, S.empty_records(), NOW)
        self.assertEqual([i["id"] for i in live["invites"]], ["abc", "abc-2"])


class CompanyNaming(unittest.TestCase):
    def test_from_domain(self):
        rec = S.empty_records()
        self.assertEqual(S.company_for_domain("acme.com", rec), "Acme")
        self.assertEqual(S.company_for_domain("mail.acme.co.uk", rec), "Acme")
        self.assertEqual(S.company_for_domain("northwind-freight.io", rec), "Northwind Freight")
        self.assertIsNone(S.company_for_domain("gmail.com", rec))
        self.assertIsNone(S.company_for_domain("outlook.com", rec))

    def test_records_map_wins_and_covers_subdomains(self):
        rec = S.empty_records()
        rec["companies"]["Bol"] = {"domain": "bol.com", "status": "New lead"}
        rec["companies"]["Acme Corporation"] = {"domain": "acme.com"}
        self.assertEqual(S.company_for_domain("acme.com", rec), "Acme Corporation")
        self.assertEqual(S.company_for_domain("eu.acme.com", rec), "Acme Corporation")

    def test_personal_domains_use_title(self):
        e = ev("p", "2026-10-21T14:00:00+00:00", 30, [SELF, att("sam@gmail.com", "Sam")], summary="Coffee with Sam")
        self.assertEqual(S.event_to_invite(e, ME["email"], S.empty_records())["company"], "Coffee with Sam")

    def test_own_domain_is_not_the_company(self):
        e = ev("i", "2026-10-21T14:00:00+00:00", 30, [SELF, att("jo@spotify.com", "Jo"), att("li@quillstack.ai", "Li")])
        self.assertEqual(S.event_to_invite(e, ME["email"], S.empty_records())["company"], "Quillstack")
        internal = ev("j", "2026-10-21T14:00:00+00:00", 30, [SELF, att("jo@spotify.com", "Jo")], summary="1:1 with Jo")
        self.assertIsNone(S.event_to_invite(internal, ME["email"], S.empty_records()))

    def test_internal_meetings_are_not_calls(self):
        rec = S.empty_records()
        standup = ev("standup1", "2026-10-21T14:00:00+00:00", 15, [SELF, att("alex.kim@spotify.com"), att("jo@spotify.com")], summary="Team standup")
        self.assertIsNone(S.event_to_invite(standup, ME["email"], rec))
        self.assertEqual(S.build_live([standup], ME, rec, NOW)["invites"], [])
        with_gmail = ev("g1", "2026-10-21T14:00:00+00:00", 30, [SELF, att("jo@spotify.com"), att("sam@gmail.com", "Sam Lee")], summary="Coffee with Sam")
        self.assertEqual(S.event_to_invite(with_gmail, ME["email"], rec)["company"], "Coffee with Sam")
        gmail_me = ev("g2", "2026-10-21T14:00:00+00:00", 30, [att("me@gmail.com", self=True), att("pat@gmail.com", "Pat Roe")], summary="Chat with Pat")
        self.assertIsNotNone(S.event_to_invite(gmail_me, "me@gmail.com", rec))  # personal mail isn't "your company"

    def test_most_common_domain_wins(self):
        e = ev("m", "2026-10-21T14:00:00+00:00", 30, [SELF, att("a@partner.com"), att("b@rookery.com"), att("c@rookery.com")])
        self.assertEqual(S.event_to_invite(e, ME["email"], S.empty_records())["company"], "Rookery")


class Signals(unittest.TestCase):
    def test_job_change_and_first_meeting(self):
        past = ev("p1", "2026-08-03T15:00:00+00:00", 30, [SELF, att("dana.li@lumenair.com", "Dana Li")])
        upcoming = ev("u1", "2026-10-21T18:00:00+00:00", 30, [SELF, att("dana.li@quillstack.ai", "Dana Li"), att("sam@quillstack.ai", "Sam Okafor")],
                      summary="Intro: Quillstack")
        live = S.build_live([past, upcoming], ME, S.empty_records(), NOW)
        kinds = {w["kind"]: w for w in live["watch"]}
        self.assertIn("Job change", kinds)
        self.assertEqual(kinds["Job change"]["title"], "Dana Li moved to Quillstack")
        self.assertEqual(kinds["Job change"]["callId"], "u1")
        self.assertIn("Lumenair", kinds["Job change"]["text"])
        self.assertEqual(live["people"]["dana.li@quillstack.ai"]["previous"], "Lumenair")
        self.assertIn("First meeting", kinds)  # nobody from quillstack.ai before
        self.assertEqual(kinds["First meeting"]["title"], "First meeting with Quillstack")
        self.assertEqual(live["watch"][0]["date"], "Oct 20")

    def test_no_alerts_for_the_same_company(self):
        past = ev("p1", "2026-09-01T15:00:00+00:00", 30, [SELF, att("dana@acme.com", "Dana Li")])
        upcoming = ev("u1", "2026-10-21T18:00:00+00:00", 30, [SELF, att("dana@eu.acme.com", "Dana Li")])
        rec = S.empty_records()
        rec["companies"]["Acme"] = {"domain": "acme.com"}
        live = S.build_live([past, upcoming], ME, rec, NOW)
        self.assertEqual(live["watch"], [])

    def test_personal_mail_never_counts_as_a_job(self):
        past = ev("p1", "2026-09-01T15:00:00+00:00", 30, [SELF, att("dana@gmail.com", "Dana Li")])
        upcoming = ev("u1", "2026-10-21T18:00:00+00:00", 30, [SELF, att("dana@acme.com", "Dana Li")])
        live = S.build_live([past, upcoming], ME, S.empty_records(), NOW)
        self.assertNotIn("Job change", [w["kind"] for w in live["watch"]])

    def test_first_names_and_role_mailboxes_are_not_people(self):
        cases = [("sarah@acme-robotics.com", "sarah@globex.io"), ("info@initech.com", "info@hooli.com"),
                 ("sales@initech.com", "sales@hooli.com")]
        for old, new in cases:
            past = ev("p1", "2026-09-01T15:00:00+00:00", 30, [SELF, att(old)])
            upcoming = ev("u1", "2026-10-21T18:00:00+00:00", 30, [SELF, att(new)])
            live = S.build_live([past, upcoming], ME, S.empty_records(), NOW)
            self.assertNotIn("Job change", [w["kind"] for w in live["watch"]], new)
        past = ev("p1", "2026-09-01T15:00:00+00:00", 30, [SELF, att("info@initech.com", "Dana Li")])
        upcoming = ev("u1", "2026-10-21T18:00:00+00:00", 30, [SELF, att("info@hooli.com", "Dana Li")])
        self.assertNotIn("Job change", [w["kind"] for w in S.build_live([past, upcoming], ME, S.empty_records(), NOW)["watch"]])
        # a met domain still counts, so no false "First meeting" for Initech
        again = ev("u2", "2026-10-22T18:00:00+00:00", 30, [SELF, att("sarah@initech.com")])
        live = S.build_live([ev("p2", "2026-09-01T15:00:00+00:00", 30, [SELF, att("info@initech.com")]), again], ME, S.empty_records(), NOW)
        self.assertNotIn("First meeting", [w["kind"] for w in live["watch"]])

    def test_shape_matches_sample(self):
        rec = S.empty_records()
        rec["people"]["a@acme.com"] = {"title": "CTO", "note": "Met at KubeCon", "startedAt": "2024-05"}
        rec["companies"]["Acme"] = {"domain": "acme.com", "status": "Open deal: Portal", "engineers": 300, "notes": "Wants SSO"}
        rec["updates"]["u1"] = [{"kind": "Next step", "text": "Send a quote", "company": "Acme", "at": "2026-10-19T10:00:00+00:00"}]
        rec["callNotes"]["u1"] = {"text": "Pilot next month"}
        upcoming = ev("u1", "2026-10-21T18:00:00+00:00", 30, [SELF, att("a@acme.com", "Ann Lee")])
        later = ev("u2", "2026-11-20T18:00:00+00:00", 30, [SELF, att("b@acme.com")])  # beyond 14 days
        gone = ev("u0", "2026-10-17T18:00:00+00:00", 30, [SELF, att("b@acme.com")])   # over more than 48 hours ago
        just = ev("u3", "2026-10-19T18:00:00+00:00", 30, [SELF, att("c@acme.com")])   # ended yesterday: kept, so After the call works
        live = S.build_live([gone, just, upcoming, later], ME, rec, NOW)
        for k in ("today", "invites", "people", "companies", "papers", "currentSecurityPack", "relationships", "watch"):
            self.assertIn(k, live)
        self.assertEqual(live["today"], "2026-10-20")
        self.assertEqual([(i["id"], i["ended"]) for i in live["invites"]], [("u1", False), ("u3", True)])  # upcoming first
        live["invites"] = [i for i in live["invites"] if i["id"] == "u1"]
        self.assertEqual(live["invites"][0]["afterNotes"], "Pilot next month")
        p = live["people"]["a@acme.com"]
        self.assertEqual((p["title"], p["note"], p["startedAt"], p["known"]), ("CTO", "Met at KubeCon", "2024-05", True))
        c = live["companies"]["Acme"]
        self.assertEqual(c["status"], "Open deal: Portal")
        self.assertEqual(c["history"], [{"date": "2026-10-19", "text": "Next step: Send a quote"}])
        self.assertEqual(live["relationships"], [])


class LiveScript(Fresh):
    def test_escaping(self):
        out = S.script_json({"t": "</script><script>alert(1)</script>", "u": " "})
        self.assertNotIn("</", out)
        self.assertNotIn(" ", out)
        self.assertEqual(json.loads(out)["t"], "</script><script>alert(1)</script>")

    def test_null_when_not_connected(self):
        out = S.live_script()
        self.assertIn("window.OVERTURE_LIVE = null;", out)
        st = json.loads(out.split("window.OVERTURE_STATUS = ")[1].split(";\n")[0])
        self.assertEqual(st["google"], {"configured": False, "connected": False, "email": ""})
        self.assertNotIn("token", out.lower())

    def test_connected_builds_data_from_fake_google(self):
        S.save_json(S.token_path(), {"access_token": "AT-secret", "refresh_token": "RT-secret", "expires_at": time.time() + 3000,
                                     "email": "chris@spotify.com", "name": "Chris Park"})
        start = (datetime.now(timezone.utc) + timedelta(days=2)).replace(microsecond=0)
        calls = []

        def fake(method, url, form=None, headers=None, timeout=15):
            calls.append(url)
            if url.startswith(S.EVENTS_URL):
                return 200, {"items": [ev("e1", start.isoformat(), 30, [SELF, att("a@acme.com", "Ann </script> Lee")])]}
            return 404, {}
        old = S.HTTP
        S.HTTP = fake
        try:
            out = S.live_script()
        finally:
            S.HTTP = old
        self.assertNotIn("AT-secret", out)
        self.assertNotIn("RT-secret", out)
        self.assertNotIn("</", out)
        data = json.loads(out.split("window.OVERTURE_LIVE = ")[1].split(";\n")[0])
        self.assertEqual(data["invites"][0]["company"], "Acme")
        self.assertEqual(data["me"]["email"], "chris@spotify.com")
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(calls[0]).query)
        self.assertEqual(q["singleEvents"], ["true"])


class OAuth(Fresh):
    def test_auth_url_state_and_pkce(self):
        url, state = S.new_auth_request("cid.apps.googleusercontent.com", now=1000)
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        self.assertEqual(q["state"], state)
        self.assertEqual(q["code_challenge_method"], "S256")
        self.assertEqual(q["access_type"], "offline")
        self.assertEqual(q["prompt"], "consent")
        self.assertEqual(q["scope"], "openid email profile https://www.googleapis.com/auth/calendar.readonly")
        self.assertEqual(q["redirect_uri"], "http://localhost:%d/auth/google/callback" % S.PORT)
        verifier = S.PENDING[state][0]
        self.assertTrue(43 <= len(verifier) <= 128)
        expect = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        self.assertEqual(q["code_challenge"], expect)
        self.assertNotIn(verifier, url)
        self.assertEqual(S.take_state(state, now=1001), verifier)
        self.assertIsNone(S.take_state(state, now=1002))  # single use

    def test_state_expires_and_unknown(self):
        _, state = S.new_auth_request("cid", now=1000)
        self.assertIsNone(S.take_state(state, now=1000 + S.STATE_TTL + 1))
        self.assertIsNone(S.take_state("made-up", now=1000))
        self.assertIsNone(S.take_state("", now=1000))
        self.assertIsNone(S.take_state(None, now=1000))

    def test_client_from_downloaded_json(self):
        self.assertIsNone(S.google_client())
        S.save_json(Path(TMP) / "google-client.json", {"web": {"client_id": "cid", "client_secret": "sec"}})
        self.assertEqual(S.google_client(), ("cid", "sec"))

    def test_exchange_needs_calendar_scope_and_keeps_secrets_out(self):
        S.save_json(Path(TMP) / "google-client.json", {"web": {"client_id": "cid", "client_secret": "sec"}})
        sent = {}

        def fake(method, url, form=None, headers=None, timeout=15):
            if url == S.TOKEN_URL:
                sent.update(form)
                return 200, {"access_token": "AT", "refresh_token": "RT", "expires_in": 3600, "scope": "openid email"}
            return 200, {"email": "chris@spotify.com", "name": "Chris"}
        old = S.HTTP
        S.HTTP = fake
        try:
            with self.assertRaises(S.GoogleError):
                S.exchange_code("code", "verifier")
            self.assertEqual(sent["code_verifier"], "verifier")
            self.assertFalse(S.token_path().exists())

            def ok(method, url, form=None, headers=None, timeout=15):
                if url == S.TOKEN_URL:
                    return 200, {"access_token": "AT", "refresh_token": "RT", "expires_in": 3600, "scope": "openid email " + S.CAL_SCOPE}
                return 200, {"email": "chris@spotify.com", "name": "Chris"}
            S.HTTP = ok
            S.exchange_code("code", "verifier")
            self.assertEqual(S.status_body()["google"], {"configured": True, "connected": True, "email": "chris@spotify.com"})
            self.assertNotIn("RT", json.dumps(S.status_body()))
        finally:
            S.HTTP = old

    def test_refresh_when_expired_and_forget_on_invalid_grant(self):
        S.save_json(Path(TMP) / "google-client.json", {"web": {"client_id": "cid", "client_secret": "sec"}})
        S.save_json(S.token_path(), {"access_token": "old", "refresh_token": "RT", "expires_at": time.time() - 10})
        old = S.HTTP
        S.HTTP = lambda m, u, form=None, headers=None, timeout=15: (200, {"access_token": "new", "expires_in": 3600})
        try:
            self.assertEqual(S.access_token(), "new")
            self.assertEqual(S.access_token(), "new")  # cached now
            S.HTTP = lambda m, u, form=None, headers=None, timeout=15: (400, {"error": "invalid_grant"})
            with self.assertRaises(S.GoogleError):
                S.access_token(force_refresh=True)
            self.assertFalse(S.token_path().exists())
        finally:
            S.HTTP = old


class Records(Fresh):
    def test_validation(self):
        bad = [
            ("company", {"status": "x"}),                                   # no name
            ("company", {"name": "Acme", "colour": "red"}),                 # unknown field
            ("company", {"name": "Acme", "engineers": "many"}),
            ("company", {"name": "Acme", "engineers": True}),
            ("company", {"name": "Acme", "domain": "gmail.com"}),
            ("company", {"name": "Acme", "domain": "not a domain"}),
            ("company", {"name": "Acme", "notes": "x" * 4001}),
            ("company", {"name": "Acme", "customer": "yes"}),
            ("person", {"email": "nope"}),
            ("person", {"email": "a@acme.com", "startedAt": "May 2024"}),
            ("person", {"email": "a@acme.com", "title": 5}),
            ("call-notes", {"callId": "../x", "text": "hi"}),
            ("call-notes", {"callId": "abc", "text": 5}),
            ("apply", {"callId": "abc", "company": "Acme", "accept": [{"kind": "Gossip", "text": "x"}]}),
            ("apply", {"callId": "abc", "company": "Acme", "accept": [{"kind": "Deal", "text": ""}]}),
            ("apply", {"callId": "abc", "company": "Acme"}),
            ("apply", {"callId": "abc", "company": "Acme", "accept": [{"kind": "Deal", "text": "x"}] * 51}),
            ("nope", {}),
            ("company", ["not", "an", "object"]),
        ]
        for kind, body in bad:
            with self.assertRaises(S.Invalid, msg=(kind, body)):
                S.write_records(kind, body)
        self.assertFalse(S.records_path().exists())

    def test_round_trip(self):
        S.write_records("company", {"name": "Acme", "status": "Customer: Portal", "domain": "ACME.com", "engineers": 300})
        S.write_records("company", {"name": "Acme", "notes": "Wants SSO"})  # merges
        S.write_records("person", {"email": "Ann@Acme.com", "title": "CTO", "startedAt": "2024-05"})
        S.write_records("call-notes", {"callId": "e1", "text": "Pilot next month"})
        r = S.load_records()
        self.assertEqual(r["companies"]["Acme"]["domain"], "acme.com")
        self.assertTrue(r["companies"]["Acme"]["customer"])
        self.assertEqual(r["companies"]["Acme"]["notes"], "Wants SSO")
        self.assertEqual(r["people"]["ann@acme.com"]["title"], "CTO")
        self.assertEqual(r["callNotes"]["e1"]["text"], "Pilot next month")
        S.write_records("call-notes", {"callId": "e1", "text": "  "})
        self.assertNotIn("e1", S.load_records()["callNotes"])
        self.assertEqual(list(Path(TMP).glob("*.tmp")), [])  # atomic writes leave no temp files
        self.assertEqual((Path(TMP) / ".gitignore").read_text().strip(), "*")

    def test_domain_belongs_to_one_company(self):
        S.write_records("company", {"name": "Acme", "domain": "acme.com"})
        S.write_records("company", {"name": "Acme Corp", "domain": "acme.com"})
        r = S.load_records()
        self.assertEqual(r["companies"]["Acme"]["domain"], "")
        self.assertEqual(S.company_for_domain("acme.com", r), "Acme Corp")

    def test_apply_and_undo(self):
        body = {"callId": "e1", "company": "Acme", "accept": [{"kind": "Next step", "text": "Send a quote"}, {"kind": "Deal", "text": "Budget approved"}]}
        S.write_records("apply", body)
        S.write_records("apply", body)  # the same update twice is stored once
        self.assertEqual(len(S.load_records()["updates"]["e1"]), 2)
        S.write_records("apply", {"callId": "e1", "company": "Acme", "undo": [{"kind": "Deal", "text": "Budget approved"}]})
        self.assertEqual([u["text"] for u in S.load_records()["updates"]["e1"]], ["Send a quote"])
        S.write_records("apply", {"callId": "e1", "company": "Acme", "undo": [{"kind": "Next step", "text": "Send a quote"}]})
        self.assertNotIn("e1", S.load_records()["updates"])


class Guards(unittest.TestCase):
    def test_write_guard(self):
        host = "localhost:%d" % S.PORT
        ok = {"Host": host, "X-OVERTURE": "1", "Origin": "http://" + host}
        self.assertTrue(S.write_guard_ok(ok))
        self.assertTrue(S.write_guard_ok({"Host": host, "X-OVERTURE": "1", "Referer": "http://127.0.0.1:%d/#/home" % S.PORT}))
        self.assertFalse(S.write_guard_ok({**ok, "X-OVERTURE": "0"}))
        self.assertFalse(S.write_guard_ok({k: v for k, v in ok.items() if k != "X-OVERTURE"}))
        self.assertFalse(S.write_guard_ok({**ok, "Origin": "https://evil.example"}))
        self.assertFalse(S.write_guard_ok({**ok, "Origin": "http://" + host + ".evil.example"}))
        self.assertFalse(S.write_guard_ok({"Host": host, "X-OVERTURE": "1"}))  # neither Origin nor Referer
        self.assertFalse(S.write_guard_ok({"Host": host, "X-OVERTURE": "1", "Referer": "http://localhost:%d.evil.example/" % S.PORT}))
        self.assertFalse(S.write_guard_ok({**ok, "Host": "evil.example"}))

    def test_read_guard(self):
        host = "localhost:%d" % S.PORT
        self.assertTrue(S.read_guard_ok({"Host": host}))
        self.assertTrue(S.read_guard_ok({"Host": host, "Sec-Fetch-Site": "same-origin"}))
        self.assertFalse(S.read_guard_ok({"Host": host, "Sec-Fetch-Site": "cross-site"}))
        self.assertFalse(S.read_guard_ok({"Host": host, "Sec-Fetch-Site": "same-site"}))
        self.assertFalse(S.read_guard_ok({"Host": "rebound.example"}))

    def test_log_hides_query_strings(self):
        seen = []
        h = S.Handler.__new__(S.Handler)
        h.client_address, h.requestline = ("127.0.0.1", 1), ""
        import http.server as hs
        old = hs.BaseHTTPRequestHandler.log_message
        hs.BaseHTTPRequestHandler.log_message = lambda self, fmt, *args: seen.append(fmt % args)
        try:
            S.Handler.log_message(h, '"%s" %s %s', "GET /auth/google/callback?code=SECRETCODE&state=abc HTTP/1.1", "302", "-")
        finally:
            hs.BaseHTTPRequestHandler.log_message = old
        self.assertNotIn("SECRETCODE", seen[0])

    def test_hidden_paths(self):
        for p in ("/.data/google-token.json", "/%2Edata/records.json", "/.DATA/x", "/x/.git/config", "/%2e%64ata/google-client.json"):
            self.assertTrue(S.hidden_path(p), p)
        self.assertFalse(S.hidden_path("/data/live.js"))


class FakeClaude:
    """Stands in for anthropic.Anthropic(): records every request, answers from a list. No network."""

    def __init__(self, *replies):
        self.calls, self.replies = [], list(replies)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kw):
        self.calls.append(kw)
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def reply(answer, urls=(), stop="end_turn", cited=None, ages=None):
    """A Claude response: optional web search results (ages: url -> the result's page_age), then the answer text (cited: url ->
    the cited_text of a citation of that page)."""
    content = []
    if urls:
        content.append(SimpleNamespace(type="web_search_tool_result", content=[SimpleNamespace(type="web_search_result", url=u, page_age=(ages or {}).get(u)) for u in urls]))
    cites = [SimpleNamespace(type="web_search_result_location", url=u, cited_text=t) for u, t in (cited or {}).items()]
    content.append(SimpleNamespace(type="text", text=answer if isinstance(answer, str) else json.dumps(answer), citations=cites or None))
    return SimpleNamespace(stop_reason=stop, content=content)


FOUND = {"found": True, "title": "VP, Platform Engineering", "team": "Platform", "seniority": "executive", "tenure": "about 2 years",
         "relationship": "employee", "confidence": "high",
         "sources": [{"url": "https://northwind-freight.com/about/team", "label": "Northwind Freight team page", "supports": ["title", "team", "relationship"]},
                     {"url": "https://kubecon.example.org/talks/priya", "label": "KubeCon talk", "supports": ["seniority", "tenure"]}]}
FOUND_URLS = ("https://northwind-freight.com/about/team", "https://kubecon.example.org/talks/priya/")


class RateLimitError(Exception):
    pass


class Research(Fresh):
    def setUp(self):
        super().setUp()
        with S.RQ_LOCK:
            S.RQ.update(queue=[], pending=set(), running=set(), errors={}, meta={})
        self.old = (S.research_client, S.RESEARCH_AUTOSTART)
        S.RESEARCH_AUTOSTART = False
        os.environ["ANTHROPIC_API_KEY"] = "test-key"

    def tearDown(self):
        S.research_client, S.RESEARCH_AUTOSTART = self.old
        os.environ.pop("ANTHROPIC_API_KEY", None)

    def fake(self, *replies):
        f = FakeClaude(*replies)
        S.research_client = lambda: f
        return f

    def build(self, attendees, now=NOW, eid="u1", summary="Discovery: Northwind"):
        events = [ev(eid, (now + timedelta(days=1, hours=6)).isoformat(), 30, [SELF] + attendees, summary=summary)]
        meta, rec = {}, S.load_records()
        live = S.build_live(events, ME, rec, now, meta_out=meta)
        return live, meta, rec

    def queue(self, attendees, now=NOW):
        live, meta, rec = self.build(attendees, now)
        return S.queue_research(meta, rec, now), meta

    def test_request_never_holds_an_email_or_local_part(self):
        f = self.fake(reply(FOUND, FOUND_URLS), reply({"found": False}))
        queued, _ = self.queue([att("priya.raman@northwind-freight.com", "Priya Raman"), att("mbell42@northwind-freight.com", "Marcus Bell")])
        self.assertTrue(queued)
        while S.research_step(NOW):
            pass
        self.assertEqual(len(f.calls), 2)
        for call, name, local in ((f.calls[0], "Priya Raman", "priya.raman"), (f.calls[1], "Marcus Bell", "mbell42")):
            sent = json.dumps(call, default=str).lower()
            self.assertNotIn("@", json.dumps(call["messages"]))
            self.assertNotIn("@northwind", sent)
            self.assertNotIn(local, sent)
            self.assertIn(name, call["messages"][0]["content"])
            self.assertIn("Northwind Freight", call["messages"][0]["content"])
            self.assertIn("northwind-freight.com", call["messages"][0]["content"])
        self.assertNotIn("@", json.dumps(f.calls[0]))

    def test_request_shape_and_blocked_domains(self):
        req = S.research_request("Priya Raman", "Northwind Freight", "northwind-freight.com", "priya.raman@northwind-freight.com")
        self.assertEqual(req["model"], "claude-opus-5-5")
        self.assertEqual(req["betas"], ["server-side-fallback-2026-07-01"])
        self.assertEqual(req["fallbacks"], "default")
        self.assertEqual(req["output_config"], {"effort": "medium"})  # deep research (was "low" for the one quick search)
        self.assertEqual(req["max_tokens"], S.DEEP_MAX_TOKENS)
        tool, fetch = req["tools"]
        self.assertEqual((tool["type"], tool["name"]), ("web_search_20260209", "web_search"))
        self.assertEqual((fetch["type"], fetch["name"]), ("web_fetch_20260209", "web_fetch"))
        self.assertEqual((tool["max_uses"], fetch["max_uses"]), (S.DEEP_SEARCHES, S.DEEP_FETCHES))
        for t in (tool, fetch):  # blocked in BOTH tools
            for d in ("zoominfo.com", "rocketreach.co", "contactout.com", "apollo.io", "lusha.com", "signalhire.com", "seamless.ai", "uplead.com",
                      "hunter.io", "clearbit.com", "spokeo.com", "whitepages.com", "beenverified.com", "truepeoplesearch.com",
                      "fastpeoplesearch.com", "peoplefinders.com", "radaris.com", "intelius.com", "pipl.com",
                      "x.com", "twitter.com", "reddit.com", "peopledatalabs.com", "fullcontact.com", "cyberbackgroundchecks.com"):
                self.assertIn(d, t["blocked_domains"])
            self.assertEqual(len(t["blocked_domains"]), len(set(t["blocked_domains"])))  # no duplicates
        self.assertTrue(S.blocked_url("https://x.com/priyaraman"))
        self.assertFalse(S.blocked_url("https://box.com/x"))
        # the code refuses to send a name that is really the address
        with self.assertRaises(S.ResearchError):
            S.research_request("priya.raman", "Northwind", "northwind-freight.com", "priya.raman@northwind-freight.com")
        with self.assertRaises(S.ResearchError):
            S.research_request("Priya Raman priya.raman@northwind-freight.com", "Northwind", "northwind-freight.com", "priya.raman@northwind-freight.com")
        with self.assertRaises(S.ResearchError):
            S.research_request("Sam Lee", "Gmail", "gmail.com", "sam@gmail.com")

    def test_a_guest_queued_before_web_research_is_turned_off_is_never_sent(self):
        f = self.fake(reply(FOUND, FOUND_URLS))
        queued, meta = self.queue([att("priya.raman@northwind-freight.com", "Priya Raman")])
        self.assertTrue(queued)
        S.save_settings({"research": {"web": False}})  # while it waits behind the call's mentions
        while S.research_step(NOW):
            pass
        self.assertEqual(f.calls, [])
        r = S.research_view("priya.raman@northwind-freight.com", {}, meta["priya.raman@northwind-freight.com"])
        self.assertEqual((r["status"], r["note"]), ("skipped", S.WEB_OFF_NOTE))

    def test_personal_domains_no_name_and_colleagues_are_skipped(self):
        f = self.fake()
        # mbell@ has no name on the invite and the address doesn't show one; dana@ is a first name only
        queued, meta = self.queue([att("sam.lee@gmail.com", "Sam Lee"), att("mbell@northwind-freight.com"),
                                   att("jo.park@spotify.com", "Jo Park"), att("dana@northwind-freight.com", "Dana")])
        self.assertFalse(queued)
        self.assertEqual(f.calls, [])
        live, _, _ = self.build([att("sam.lee@gmail.com", "Sam Lee"), att("mbell@northwind-freight.com")])
        r = live["people"]["sam.lee@gmail.com"]["research"]
        self.assertEqual(r["status"], "skipped")
        self.assertIn("Personal email", r["note"])
        self.assertEqual(r["local"]["company"], "")
        self.assertIn("No name on the invite", live["people"]["mbell@northwind-freight.com"]["research"]["note"])
        self.assertTrue(meta["jo.park@spotify.com"]["internal"])

    def test_deep_research_waits_until_the_call_is_a_week_away(self):
        now = datetime(2026, 10, 21, 18, 0, tzinfo=timezone.utc)
        self.assertTrue(S.call_soon({"start": "2026-10-22T15:15:00-04:00"}, now))
        self.assertFalse(S.call_soon({"start": "2026-11-02T15:15:00-05:00"}, now))
        self.assertTrue(S.call_soon({}, now))  # no known start: don't hold it back

    def test_a_guest_on_a_call_more_than_a_week_away_says_when_research_happens(self):
        now = datetime(2026, 10, 21, 18, 0, tzinfo=timezone.utc)
        m = {"name": "Marcus Bell", "named": True, "domain": "northwind-freight.com", "company": "Northwind Freight", "start": "2026-11-02T15:15:00-05:00"}
        self.assertEqual(S.research_status("marcus.bell@northwind-freight.com", {}, m, now), ("later", S.LATER_NOTE))
        soon = dict(m, start="2026-10-22T15:15:00-04:00")
        self.assertNotEqual(S.research_status("marcus.bell@northwind-freight.com", {}, soon, now)[0], "later")
        om = {"name": "Northwind Freight", "domain": "northwind-freight.com", "start": m["start"]}
        self.assertEqual(S.org_research_status("northwind-freight.com", {}, om, now), ("later", S.ORG_LATER_NOTE))
        # Far-off guests and companies aren't queued (that costs tokens) until the call is a week away.
        meta = {"marcus.bell@northwind-freight.com": m}
        self.assertFalse(S.queue_research(meta, S.load_records(), now))
        self.assertFalse(S.queue_org_research(meta, S.load_records(), now))

    def test_event_names_skip_titles_dates_and_read_html_descriptions(self):
        self.assertEqual(S.name_from_event("shea@tks.world", {"title": "Meeting with Shea Kim CEO", "notes": ""}), "Shea Kim")
        self.assertEqual(S.name_from_event("shea@tks.world", {"title": "Shea Thursday", "notes": "Shea October review"}), "")
        self.assertEqual(S.name_from_event("shea@tks.world", {"title": "", "notes": "Call with Shea McDonald-Ray"}), "Shea McDonald-Ray")
        self.assertEqual(S.name_from_event("shea@tks.world", {"title": "Call with Shea Kim's team", "notes": ""}), "Shea Kim")
        self.assertEqual(S.name_from_event("shea@tks.world", {"title": "Call with Shea Kim's Backstage demo", "notes": ""}), "Shea Kim")

    def test_connected_people_names_any_alphabet_and_no_family(self):
        self.assertTrue(S.looks_like_name("José García") and S.looks_like_name("Zoë Chen") and S.looks_like_name("Ian Lockhart"))
        self.assertTrue(S.looks_like_name("Seán O'Brien") and S.looks_like_name("Anne-Marie Lee") and S.looks_like_name("John F. Kennedy"))
        self.assertTrue(S._profile_text("She ran product at their parent company, Acme.", 260) and S._profile_text("Worked with Ana Cousins on the launch.", 260))
        self.assertFalse(S.looks_like_name("the team") or S.looks_like_name("Ian") or S.looks_like_name("Team 7 Leads"))
        for t in ("Her brother co-founded Acme with her.", "Her father, the CEO, hired her.", "Her sister-in-law runs sales."):
            self.assertEqual(S._profile_text(t, 260), "", t)
        self.assertTrue(S._profile_text("Ran launches at Acme's sister company, Acme Labs.", 260))  # business words stay

    def test_setup_guides_use_only_markdown_the_guide_pages_can_draw(self):
        # guides.js draws headings, lists, code blocks, `code`, **bold** and links. A table or a #### heading would show as raw text.
        root = Path(S.__file__).parent
        files = re.findall(r'file: "([A-Z-]+\.md)"', (root / "guides.js").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(files), 7)
        for f in files:
            for n, line in enumerate((root / "docs" / f).read_text(encoding="utf-8").splitlines(), 1):
                self.assertFalse(re.match(r"^\s*\|", line) or line.startswith("####"), f + ":" + str(n) + " can't be drawn: " + line)
        e = ev("h1", "2026-10-22T19:15:00+00:00", 25, [SELF, att("shea@tks.world")], summary="Prototype review")
        e["description"] = "<p>Her name is <b>Shea&nbsp;Kim</b>.</p>"
        self.assertEqual([a["name"] for a in S._others(e, ME["email"])], ["Shea Kim"])

    def test_people_she_is_publicly_connected_with_are_kept_only_with_a_source(self):
        seen = {S.url_key("https://www.tks.world/team"): {"cited": [], "age": ""}}
        obj = {"found": True, "confidence": "high", "sources": [{"url": "https://www.tks.world/team", "label": "TKS team"},
                                                                {"url": "https://unseen.example.org/x", "label": "Not seen"}],
               "summary": {"text": "Director at TKS.", "sources": [1]},
               "people": [{"name": "Navid Nathoo", "role": "Co-founder", "org": "TKS", "how": "Leads TKS, where she is a director.", "sources": [1]},
                          {"name": "Pat Lee", "how": "Named with her on a page Overture never saw.", "sources": [2]},
                          {"name": "Sam Kim", "how": "Her husband.", "sources": [1]},
                          {"name": "the team", "how": "Worked together.", "sources": [1]},
                          {"name": "Navid Nathoo", "how": "Again.", "sources": [1]}]}
        prof = S.clean_profile(obj, seen, "person", "Shea Kim")
        self.assertEqual([p["name"] for p in prof["people"]], ["Navid Nathoo"])
        self.assertEqual(prof["people"][0]["src"], [0])
        self.assertEqual([p["name"] for p in S.profile_view(prof, "person")["people"]], ["Navid Nathoo"])
        # A record whose last deep run didn't ask for people is researched once more, then not again.
        now = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)
        rec = {"lookup": "done", "title": "Director", "autoFields": ["title"], "deepAt": "2026-10-22T03:00:00+00:00", "profile": prof}
        self.assertTrue(S.needs_research(rec, now))
        self.assertFalse(S.needs_research(dict(rec, deepV=S.DEEP_V), now))

    def test_name_from_the_event_description(self):
        inv = {"title": "Overture prototype review", "notes": "Call with Shea Kim from TKS to improve the prototype."}
        self.assertEqual(S.name_from_event("shea@tks.world", inv), "Shea Kim")
        self.assertEqual(S.name_from_event("shea@tks.world", {"title": "Review with Shea", "notes": "Shea will review it."}), "")
        self.assertEqual(S.name_from_event("info@tks.world", inv), "")

    def test_first_last_work_address_gives_a_name_and_example_domains_are_not_found(self):
        # No name on the invite, but first.last@company: Overture uses "Marcus Bell" and says where it came from.
        meta, rec = {}, S.load_records()
        S.build_live([ev("u2", "2026-10-21T18:00:00+00:00", 30, [SELF, att("marcus.bell@northwind-freight.com")], summary="Intro")], ME, rec, NOW, meta_out=meta)
        m = meta["marcus.bell@northwind-freight.com"]
        self.assertEqual((m["name"], m["named"], m["nameFrom"]), ("Marcus Bell", True, "email"))
        view = S.research_view("marcus.bell@northwind-freight.com", {}, m)
        self.assertEqual((view["nameFrom"], view["nameUsed"]), ("email", "Marcus Bell"))
        # A reserved example domain: nobody to find, and the page says so.
        meta2, rec2 = {}, S.load_records()
        S.build_live([ev("u3", "2026-10-21T18:00:00+00:00", 30, [SELF, att("priya.raman@northwind-freight.example")], summary="Intro")], ME, rec2, NOW, meta_out=meta2)
        st, note = S.research_status("priya.raman@northwind-freight.example", {}, meta2["priya.raman@northwind-freight.example"])
        self.assertEqual(st, "notfound")
        self.assertIn("Can't find this person", note)
        self.assertEqual(S.name_from_work_email("info.desk@acme.com"), "Info Desk")
        self.assertEqual(S.name_from_work_email("jsmith@acme.com"), "")

    def test_isp_and_regional_webmail_are_personal(self):
        f = self.fake()
        guests = [att("sam.lee@rogers.com", "Sam Lee"), att("ann.ko@hotmail.ca", "Ann Ko"), att("li.wu@yahoo.co.uk", "Li Wu"),
                  att("bo.ng@sympatico.ca", "Bo Ng"), att("al.ho@comcast.net", "Al Ho"), att("di.ma@gmx.de", "Di Ma")]
        queued, _ = self.queue(guests)
        self.assertFalse(queued)
        self.assertEqual(f.calls, [])
        live, _, _ = self.build(guests)
        for a in guests:
            r = live["people"][a["email"]]["research"]
            self.assertEqual(r["status"], "skipped", a["email"])
            self.assertIn("Personal email", r["note"], a["email"])
        with self.assertRaises(S.ResearchError):
            S.research_request("Sam Lee", "Rogers", "rogers.com", "sam.lee@rogers.com")
        for d in ("gmail.com", "outlook.co.uk", "live.ca", "proton.me", "mail.ru", "yandex.ru", "aol.co.uk", "web.de"):
            self.assertTrue(S.personal_domain(d), d)
        for d in ("northwind-freight.com", "mail.acme.com", "yahoo-inc.com", "acme.co.uk", "live-nation.com", ""):
            self.assertFalse(S.personal_domain(d), d)

    def test_name_sent_is_a_real_display_name_never_the_address(self):
        f = self.fake(reply(FOUND, FOUND_URLS))
        past = ev("p1", "2026-08-03T15:00:00+00:00", 30, [SELF, att("john.doe@northwind-freight.com", "Johnny")])
        upcoming = ev("u1", "2026-10-21T18:00:00+00:00", 30, [SELF, att("john.doe@northwind-freight.com")], summary="Discovery: Northwind")
        meta, rec = {}, S.load_records()
        live = S.build_live([past, upcoming], ME, rec, NOW, meta_out=meta)
        self.assertEqual(meta["john.doe@northwind-freight.com"]["name"], "Johnny")
        self.assertFalse(S.queue_research(meta, rec, NOW))
        self.assertEqual(S.request_research("john.doe@northwind-freight.com")[0], 400)
        while S.research_step(NOW):
            pass
        self.assertEqual(f.calls, [])
        self.assertIn("No name on the invite", live["people"]["john.doe@northwind-freight.com"]["research"]["note"])
        self.assertEqual(live["invites"][0]["attendees"][0]["name"], "John Doe")  # the page may still show a made-up name

    def test_without_a_key_only_local_facts(self):
        os.environ.pop("ANTHROPIC_API_KEY", None)
        f = self.fake()
        past = ev("p1", "2026-08-03T15:00:00+00:00", 30, [SELF, att("priya.raman@northwind-freight.com", "Priya Raman")])
        meta, rec = {}, S.load_records()
        live = S.build_live([past, ev("u1", "2026-10-21T18:00:00+00:00", 30, [SELF, att("priya.raman@northwind-freight.com", "Priya Raman")])], ME, rec, NOW, meta_out=meta)
        self.assertFalse(S.queue_research(meta, rec, NOW))
        self.assertEqual(f.calls, [])
        p = live["people"]["priya.raman@northwind-freight.com"]
        self.assertEqual(p["title"], "")
        self.assertEqual(p["research"]["status"], "skipped")
        self.assertEqual(p["research"]["note"], "Add a Claude key to look up titles automatically")
        self.assertEqual(p["research"]["local"], {"company": "Northwind Freight", "adopter": False, "metBefore": True, "lastMet": "Aug 3, 2026"})

    def test_found_result_is_stored_with_sources_and_alert(self):
        self.fake(reply(FOUND, FOUND_URLS))
        self.queue([att("priya.raman@northwind-freight.com", "Priya Raman")])
        S.research_step(NOW)
        rec = S.load_records()["people"]["priya.raman@northwind-freight.com"]
        self.assertEqual((rec["title"], rec["team"], rec["relationship"], rec["seniority"], rec["tenure"]),
                         ("VP, Platform Engineering", "Platform", "employee", "executive", "about 2 years"))
        self.assertEqual((rec["found"], rec["lookup"], rec["confidence"]), ("auto", "done", "high"))
        self.assertEqual([s["url"] for s in rec["sources"]], [FOUND_URLS[0], "https://kubecon.example.org/talks/priya"])
        self.assertTrue(rec["foundAt"].startswith("2026-10-20T12:00"))
        live, _, _ = self.build([att("priya.raman@northwind-freight.com", "Priya Raman")])
        p = live["people"]["priya.raman@northwind-freight.com"]
        self.assertEqual(p["title"], "VP, Platform Engineering")
        self.assertFalse(p["known"])  # research alone isn't the user's own record
        self.assertEqual((p["research"]["status"], p["research"]["found"]), ("done", "auto"))
        new = [w for w in live["watch"] if w["kind"] == "New person"]
        self.assertEqual(len(new), 1)
        self.assertEqual(new[0]["title"], "New on the Northwind Freight call: Priya Raman, VP, Platform Engineering")
        self.assertEqual(new[0]["callId"], "u1")
        self.assertEqual(new[0]["person"], "Priya Raman")

    def test_unknown_result_alert_says_role_unknown(self):
        self.fake(reply("I could not find them."))
        self.queue([att("priya.raman@northwind-freight.com", "Priya Raman")])
        S.research_step(NOW)
        rec = S.load_records()["people"]["priya.raman@northwind-freight.com"]
        self.assertEqual(rec["lookup"], "unknown")
        self.assertNotIn("title", rec)
        live, _, _ = self.build([att("priya.raman@northwind-freight.com", "Priya Raman")])
        self.assertEqual(live["people"]["priya.raman@northwind-freight.com"]["research"]["status"], "unknown")
        self.assertIn("New on the Northwind Freight call: Priya Raman, role unknown", [w["title"] for w in live["watch"]])

    def test_unsourced_invalid_or_unsure_answers_become_unknown(self):
        seen = {S.url_key(u) for u in FOUND_URLS}
        cases = [
            None, {"found": False}, dict(FOUND, found="yes"), dict(FOUND, confidence="low"), dict(FOUND, sources=[]),
            dict(FOUND, sources="https://northwind-freight.com"),
            dict(FOUND, sources=[{"url": "https://northwind-freight.com/about/team", "label": "x", "supports": []}]),
            dict(FOUND, sources=[{"url": "javascript:alert(1)", "label": "x", "supports": ["title"]}]),
            dict(FOUND, sources=[{"url": "https://made-up.example/never-seen", "label": "x", "supports": ["title"]}]),  # not in the search results
        ]
        for obj in cases:
            self.assertEqual(S.clean_research(obj, seen)["status"], "unknown", obj)
        for text in ("not json", "{broken", "[1, 2]", ""):
            self.assertIsNone(S.extract_json(text))
        self.assertEqual(S.extract_json('Here: ```json\n{"found": false}\n```'), {"found": False})
        # a field no kept source backs is dropped, and so is anything that looks like contact details
        only_title = dict(FOUND, team="Platform", tenure="call +1 (555) 010-2000",
                          sources=[{"url": FOUND_URLS[0], "label": "Team page", "supports": ["title", "tenure"]}])
        out = S.clean_research(only_title, seen)
        self.assertEqual(out["status"], "done")
        self.assertEqual((out["title"], out["team"], out["tenure"], out["relationship"]), ("VP, Platform Engineering", "", "", "unknown"))
        self.assertEqual(S.clean_research(dict(FOUND, title="priya@northwind-freight.com", relationship="unknown"), seen)["status"], "unknown")
        # an unknown relationship value is never kept
        self.assertEqual(S.clean_research(dict(FOUND, relationship="friend"), seen)["relationship"], "unknown")

    def test_blocked_source_urls_are_dropped(self):
        obj = dict(FOUND, sources=[
            {"url": "https://www.zoominfo.com/p/priya-raman", "label": "ZoomInfo", "supports": ["title", "relationship"]},
            {"url": "https://people.spokeo.com/Priya-Raman", "label": "Spokeo", "supports": ["title"]},
            {"url": "https://user:pw@northwind-freight.com/about/team", "label": "x", "supports": ["title"]},
            {"url": "https://northwind-freight.com/about/team", "label": "Team page", "supports": ["title", "relationship"]}])
        seen = {S.url_key(s["url"]) for s in obj["sources"]}  # all "seen", so only the block list can drop them
        out = S.clean_research(obj, seen)
        self.assertEqual([s["url"] for s in out["sources"]], ["https://northwind-freight.com/about/team"])
        only_blocked = dict(FOUND, sources=obj["sources"][:2])
        self.assertEqual(S.clean_research(only_blocked, seen)["status"], "unknown")
        self.assertTrue(S.blocked_url("https://a.b.rocketreach.co/x"))
        self.assertFalse(S.blocked_url("https://notzoominfo.com/x"))
        # stored sources are re-checked before they reach the page
        view = S.research_view("a@acme.com", {"sources": [{"url": "javascript:alert(1)", "label": "x"}, {"url": "https://zoominfo.com/x", "label": "z"},
                                                          {"url": "https://acme.com/team", "label": "<b>Team</b>"}]}, {})
        self.assertEqual(view["sources"], [{"url": "https://acme.com/team", "label": "<b>Team</b>"}])  # the page escapes the label

    def test_no_search_results_means_no_sources(self):
        invented = dict(FOUND, title="Chief Revenue Officer",
                        sources=[{"url": "https://totally-invented.example/bio", "label": "Bio", "supports": ["title", "relationship"]}])
        self.fake(reply(invented))  # answered without searching: no web_search_tool_result, no citations
        self.assertEqual(S.research_person("Ann Lee", "Acme", "acme.com", "ann@acme.com")["status"], "unknown")
        self.fake(reply(FOUND))
        self.assertEqual(S.research_person("Ann Lee", "Acme", "acme.com", "ann@acme.com")["status"], "unknown")
        self.assertEqual(S.clean_research(invented, set())["status"], "unknown")

    def test_user_fields_are_never_overwritten(self):
        S.write_records("person", {"email": "priya.raman@northwind-freight.com", "title": "CTO", "note": "Met at KubeCon"})
        f = self.fake(reply(FOUND, FOUND_URLS))
        queued, _ = self.queue([att("priya.raman@northwind-freight.com", "Priya Raman")])
        self.assertFalse(queued)  # she has a title you typed: nothing to look up
        self.assertEqual(S.request_research("priya.raman@northwind-freight.com")[0], 202)  # you can still ask
        S.research_step(NOW)
        self.assertEqual(len(f.calls), 1)
        rec = S.load_records()["people"]["priya.raman@northwind-freight.com"]
        self.assertEqual((rec["title"], rec["note"]), ("CTO", "Met at KubeCon"))
        self.assertEqual(rec["relationship"], "employee")  # empty fields can still be filled
        self.assertNotIn("title", rec["autoFields"])
        # Confirm makes everything the user's; a forced lookup later changes none of it
        S.write_records("person", {"email": "priya.raman@northwind-freight.com", "confirm": True})
        rec = S.load_records()["people"]["priya.raman@northwind-freight.com"]
        self.assertEqual((rec["found"], rec["autoFields"]), ("confirmed", []))
        S.merge_research("priya.raman@northwind-freight.com", dict(S.unknown_result(), status="done", title="Intern", team="Sales",
                                                                    relationship="partner", sources=[{"url": "https://x.example/a", "label": "x"}]))
        rec = S.load_records()["people"]["priya.raman@northwind-freight.com"]
        self.assertEqual((rec["title"], rec["team"], rec["relationship"]), ("CTO", "Platform", "employee"))
        self.assertEqual(rec["found"], "confirmed")
        with self.assertRaises(S.Invalid):
            S.write_records("person", {"email": "priya.raman@northwind-freight.com", "confirm": "yes"})
        # editing a found title makes it yours
        S.merge_research("dana.li@acme.com", dict(S.unknown_result(), status="done", title="Head of DX", relationship="employee"))
        S.write_records("person", {"email": "dana.li@acme.com", "title": "Head of DX", "note": ""})
        rec = S.load_records()["people"]["dana.li@acme.com"]
        self.assertEqual(rec["autoFields"], ["relationship"])
        self.assertTrue(S.user_known(rec))

    def test_confirmed_people_are_not_looked_up_again(self):
        email = "priya.raman@northwind-freight.com"
        S.merge_research(email, dict(S.unknown_result(), status="done", title="CTO", relationship="employee"), NOW - timedelta(days=40))
        S.write_records("person", {"email": email, "confirm": True})
        f = self.fake(reply(FOUND, FOUND_URLS))
        self.assertFalse(self.queue([att(email, "Priya Raman")])[0])  # never on its own
        while S.research_step(NOW):
            pass
        self.assertEqual(f.calls, [])
        # Look up again: allowed, but it only refreshes the research profile; what you confirmed stays as it was.
        st, body = S.request_research(email)
        self.assertEqual(st, 202)
        while S.research_step(NOW):
            pass
        self.assertEqual(len(f.calls), 1)
        rec = S.load_records()["people"][email]
        self.assertEqual((rec["found"], rec["title"], rec.get("team", "")), ("confirmed", "CTO", ""))

    def test_no_repeat_within_30_days(self):
        f = self.fake(reply({"found": False}), reply({"found": False}))
        guest = [att("priya.raman@northwind-freight.com", "Priya Raman")]
        self.assertTrue(self.queue(guest)[0])
        self.assertFalse(self.queue(guest)[0])  # already pending
        S.research_step(NOW)
        self.assertFalse(self.queue(guest, NOW + timedelta(days=1))[0])
        self.assertFalse(self.queue(guest, NOW + timedelta(days=29))[0])
        self.assertTrue(self.queue(guest, NOW + timedelta(days=31))[0])  # still nothing known after 30 days: try once more
        S.research_step(NOW + timedelta(days=31))
        self.assertEqual(len(f.calls), 2)
        # someone with a found title is not looked up again on their own (once deep research has run for them; a title found
        # the old, quick way gets one deep look-up: see DeepResearch.test_an_old_quick_record_is_looked_up_deeply_once)
        S.merge_research("ann.lee@northwind-freight.com", dict(S.unknown_result(), status="done", title="CTO", profile=None), NOW - timedelta(days=90))
        self.assertFalse(self.queue([att("ann.lee@northwind-freight.com", "Ann Lee")])[0])

    def test_claude_errors_and_pause_turn(self):
        f = self.fake(RateLimitError("slow down"))
        self.queue([att("priya.raman@northwind-freight.com", "Priya Raman")])
        S.research_step(NOW)
        live, _, _ = self.build([att("priya.raman@northwind-freight.com", "Priya Raman")])
        r = live["people"]["priya.raman@northwind-freight.com"]["research"]
        self.assertEqual(r["status"], "error")
        self.assertIn("Claude is busy", r["note"])
        self.assertFalse(S.records_path().exists())  # an error is never saved as a lookup
        self.assertFalse(self.queue([att("priya.raman@northwind-freight.com", "Priya Raman")])[0])  # no retry loop
        f = self.fake(reply("", stop="pause_turn"), reply(FOUND, FOUND_URLS))
        self.assertEqual(S.request_research("priya.raman@northwind-freight.com")[0], 202)
        S.research_step(NOW)
        self.assertEqual(len(f.calls), 2)
        self.assertEqual(f.calls[1]["messages"][1]["role"], "assistant")
        self.assertEqual(S.load_records()["people"]["priya.raman@northwind-freight.com"]["lookup"], "done")
        f = self.fake(SimpleNamespace(stop_reason="refusal", content=[]))
        self.assertEqual(S.research_person("Ann Lee", "Acme", "acme.com", "ann@acme.com")["status"], "unknown")

    def test_unfinished_lookups_are_errors_not_finds(self):
        email = "priya.raman@northwind-freight.com"
        self.fake(reply('{"found": true, "title": "VP, Plat', stop="max_tokens"))
        self.queue([att(email, "Priya Raman")])
        S.research_step(NOW)
        self.assertFalse(S.records_path().exists())  # not saved as "found nothing"
        live, _, _ = self.build([att(email, "Priya Raman")])
        r = live["people"][email]["research"]
        self.assertEqual(r["status"], "error")
        self.assertIn("didn't finish", r["note"])
        self.assertNotIn("New person", [w["kind"] for w in live["watch"]])
        f = self.fake(*[reply("", stop="pause_turn") for _ in range(S.DEEP_RESUMES + 1)])  # still paused after every resend
        self.assertEqual(S.request_research(email)[0], 202)
        S.research_step(NOW)
        self.assertEqual(len(f.calls), S.DEEP_RESUMES + 1)  # deep research resends a paused search up to DEEP_RESUMES times (was 3)
        self.assertFalse(S.records_path().exists())
        self.assertEqual(self.build([att(email, "Priya Raman")])[0]["people"][email]["research"]["status"], "error")

    def test_the_worker_pool_starts_once(self):
        started, done = [], threading.Event()

        class SlowStart(threading.Thread):
            def start(self):
                time.sleep(0.05)  # widen the gap between deciding to start a worker and starting it
                started.append(self)
                super().start()
        old = (S.threading, S._worker_loop, S._WORKER["threads"])
        S.threading, S._worker_loop, S._WORKER["threads"] = SimpleNamespace(Thread=SlowStart), done.wait, []
        try:
            callers = [threading.Thread(target=S.ensure_worker) for _ in range(2)]
            for c in callers:
                c.start()
            for c in callers:
                c.join(5)
        finally:
            done.set()
            S.threading, S._worker_loop, S._WORKER["threads"] = old
        self.assertEqual(len(started), S.MAX_WORKERS)  # two callers at once still start one pool of 3

    def test_worker_thread_runs_the_queue(self):
        self.fake(reply(FOUND, FOUND_URLS))
        S.RESEARCH_AUTOSTART = True
        self.queue([att("priya.raman@northwind-freight.com", "Priya Raman")])
        for _ in range(100):
            if S.research_body()["people"]["priya.raman@northwind-freight.com"]["status"] != "pending":
                break
            time.sleep(0.02)
        self.assertEqual(S.research_body()["people"]["priya.raman@northwind-freight.com"]["status"], "done")


# ---------------------------------------------------------------- deep research: people and companies ----------------------------------------------------------------

def deep_reply(answer, searched=(), fetched=(), asked=None, failed=(), stop="end_turn", container=None):
    """A deep-research response: search results, pages web fetch opened (asked: url -> the address Claude asked for), fetches that
    failed, a code run's output (dynamic filtering: its printed address must not count), then the answer."""
    content = []
    if searched:
        content.append(SimpleNamespace(type="web_search_tool_result", content=[SimpleNamespace(type="web_search_result", url=u, page_age=None) for u in searched]))
    for i, u in enumerate(list(fetched) + list(failed)):
        content.append(SimpleNamespace(type="server_tool_use", id="srvtoolu_%d" % i, name="web_fetch", input={"url": (asked or {}).get(u, u)}))
        ok = SimpleNamespace(type="web_fetch_result", url=u, retrieved_at="2026-10-20T11:00:00Z",
                             content=SimpleNamespace(type="document", source=SimpleNamespace(type="text", media_type="text/plain", data="page text"), title="Page"))
        content.append(SimpleNamespace(type="web_fetch_tool_result", tool_use_id="srvtoolu_%d" % i,
                                       content=ok if u in fetched else SimpleNamespace(type="web_fetch_tool_result_error", error_code="url_not_accessible")))
    content.append(SimpleNamespace(type="bash_code_execution_tool_result", tool_use_id="srvtoolu_x",
                                   content=SimpleNamespace(type="bash_code_execution_result", stdout="https://printed-by-code.example/x", stderr="", return_code=0)))
    content.append(SimpleNamespace(type="text", text=answer if isinstance(answer, str) else json.dumps(answer), citations=None))
    return SimpleNamespace(stop_reason=stop, content=content, container=container)


TKS_TEAM, SHEA_PROFILE, SHEA_TALK = "https://tks.world/team", "https://www.linkedin.com/in/shea-kim", "https://events.example.org/talks/shea"
SHEA = {
    "found": True, "confidence": "high", "title": "Director, Program Success", "team": "Program Success", "seniority": "director",
    "tenure": "", "relationship": "employee",
    "sources": [
        {"url": TKS_TEAM, "label": "TKS team page", "supports": ["title", "team", "relationship"]},   # 1: in the search results
        {"url": SHEA_PROFILE, "label": "Professional profile", "supports": ["seniority"]},       # 2: opened by web fetch
        {"url": "https://never-seen.example.com/bio", "label": "Made up", "supports": []},       # 3: never returned
        {"url": "https://www.zoominfo.com/p/shea-kim", "label": "ZoomInfo", "supports": []},   # 4: a blocked site
        {"url": SHEA_TALK, "label": "Summit talk", "supports": []}],                             # 5: in the search results
    "summary": {"text": "Shea Kim leads Program Success at The Knowledge Society.", "sources": [1]},
    "now": [{"text": "Runs the team that supports students through TKS programs.", "sources": [1, 2]},
            {"text": "Owns partner outcomes.", "sources": [3]},
            {"text": "Has a ZoomInfo profile.", "sources": [4]},
            {"text": "Reach Shea at shea@tks.world.", "sources": [1]},
            {"text": "Call Shea on +1 416 555 0100.", "sources": [1]},
            {"text": "Shea is married with two kids.", "sources": [1]},
            {"text": "Lives in Toronto.", "sources": [1]},
            {"text": "No source for this one.", "sources": []},
            "A bare sentence."],
    "past": [{"role": "Program Manager", "org": "Shopify", "when": "2018 - 2021", "sources": [2],
              "points": [{"text": "Ran the 2019 - 2021 intern program.", "sources": [2]}, {"text": "Unsourced.", "sources": []}]},
             {"role": "Coordinator", "org": "Made Up Inc", "when": "", "sources": [3], "points": [{"text": "Never seen.", "sources": [3]}]},
             {"role": "Analyst", "org": "Acme", "when": "2016 - 2018", "sources": [], "points": [{"text": "Built the reporting for the youth program.", "sources": [5]}]}],
    "education": [{"text": "BA, University of Toronto", "sources": [2]}],
    "work": [{"text": "Spoke about program design at a 2025 education summit.", "sources": [5]}],
    "forCall": [{"text": "Ask how Program Success tracks student outcomes across programs.", "sources": [1]}],
}
TKS_HOME, TKS_ABOUT, TKS_NEWS = "https://tks.world/", "https://tks.world/about", "https://news.example.com/2026/tks-expands"
TKS_ORG = {
    "found": True, "confidence": "high", "name": "The Knowledge Society (TKS)",
    "sources": [{"url": TKS_HOME, "label": "TKS home"}, {"url": TKS_ABOUT, "label": "About TKS"}, {"url": TKS_NEWS, "label": "Example News"},
                {"url": "https://never-seen.example.com/tks", "label": "Made up"}],
    "summary": {"text": "The Knowledge Society (TKS) runs innovation programs for teens.", "sources": [1]},
    "facts": [{"label": "Founded", "value": "2016", "sources": [2]}, {"label": "Headquarters", "value": "Toronto", "sources": [2]},
              {"label": "Size", "value": "500 staff", "sources": [4]}],
    "what": [{"text": "Runs year-long programs on emerging technology for students aged 13 to 17.", "sources": [1, 2]},
             {"text": "Email hello@tks.world to apply.", "sources": [1]}],
    "news": [{"text": "Opened programs in two more cities.", "when": "March 2026", "sources": [3]}],
    "tech": [],
    "forCall": [{"text": "Ask how Program Success tracks student outcomes today.", "sources": [1]}],
}


class DeepResearch(Fresh):
    SHEA_GUEST = [att("shea@tks.world", "Shea Kim")]
    fake, build, queue = Research.fake, Research.build, Research.queue

    def setUp(self):
        super().setUp()
        with S.RQ_LOCK:
            S.RQ.update(queue=[], pending=set(), running=set(), errors={}, meta={})
        self.old = (S.research_client, S.RESEARCH_AUTOSTART)
        S.RESEARCH_AUTOSTART = False
        os.environ["ANTHROPIC_API_KEY"] = "test-key"

    def tearDown(self):
        S.research_client, S.RESEARCH_AUTOSTART = self.old
        os.environ.pop("ANTHROPIC_API_KEY", None)

    def test_deep_result_keeps_sourced_bullets_past_roles_and_education(self):
        f = self.fake(deep_reply(SHEA, searched=[TKS_TEAM, "https://www.zoominfo.com/p/shea-kim", SHEA_TALK], fetched=[SHEA_PROFILE]))
        self.assertTrue(self.queue(self.SHEA_GUEST)[0])
        S.research_step(NOW)
        self.assertEqual(len(f.calls), 1)
        rec = S.load_records()["people"]["shea@tks.world"]
        self.assertEqual((rec["title"], rec["team"], rec["relationship"], rec["seniority"], rec["lookup"]),
                         ("Director, Program Success", "Program Success", "employee", "director", "done"))  # the quick fields still work
        self.assertTrue(rec["deepAt"].startswith("2026-10-20T12:00"))
        self.assertEqual(rec["searched"], 3)  # tks.world, linkedin.com, events.example.org (the blocked site isn't counted)
        p = rec["profile"]
        self.assertEqual((p["v"], p["name"], p["confidence"]), (2, "Shea Kim", "high"))
        self.assertEqual(p["sources"], [{"url": TKS_TEAM, "label": "TKS team page"}, {"url": SHEA_PROFILE, "label": "Professional profile"},
                                        {"url": SHEA_TALK, "label": "Summit talk"}])
        self.assertEqual(p["summary"], {"text": "Shea Kim leads Program Success at The Knowledge Society.", "src": [0]})
        self.assertEqual(p["now"], [{"text": "Runs the team that supports students through TKS programs.", "src": [0, 1]}])
        self.assertEqual(p["past"], [
            {"role": "Program Manager", "org": "Shopify", "when": "2018 - 2021", "src": [1], "points": [{"text": "Ran the 2019 - 2021 intern program.", "src": [1]}]},
            {"role": "Analyst", "org": "Acme", "when": "2016 - 2018", "src": [2], "points": [{"text": "Built the reporting for the youth program.", "src": [2]}]}])
        self.assertEqual(p["education"], [{"text": "BA, University of Toronto", "src": [1]}])
        self.assertEqual(p["work"], [{"text": "Spoke about program design at a 2025 education summit.", "src": [2]}])
        self.assertEqual(p["forCall"], [{"text": "Ask how Program Success tracks student outcomes across programs.", "src": [0]}])
        saved = json.dumps(p)
        for gone in ("Owns partner outcomes", "ZoomInfo", "zoominfo", "never-seen", "Made Up Inc", "shea@", "555", "married", "Lives in", "No source", "bare", "Unsourced"):
            self.assertNotIn(gone, saved)
        # the page gets the same profile (live.js and GET /api/research), and the alert gives the facts with no homework
        live, _, _ = self.build(self.SHEA_GUEST)
        r = live["people"]["shea@tks.world"]["research"]
        self.assertEqual((r["status"], r["profile"]), ("done", p))
        self.assertEqual(S.research_body()["people"]["shea@tks.world"]["profile"], p)
        alert = next(w for w in live["watch"] if w["kind"] == "New person")
        self.assertEqual(alert["text"], "Overture looked them up: Director, Program Success, Employee, Program Success. "
                                        "Shea Kim leads Program Success at The Knowledge Society.")
        self.assertFalse(S.needs_research(rec, NOW + timedelta(days=60)))  # deep research done and a title found: not again on its own

    def test_unseen_and_blocked_sources_never_back_a_bullet(self):
        seen = {S.url_key(u): {} for u in (TKS_TEAM, SHEA_TALK, "https://www.zoominfo.com/p/shea-kim")}  # no web fetch this time
        p = S.clean_profile(SHEA, seen, "person", name="Shea Kim")
        self.assertEqual([s["url"] for s in p["sources"]], [TKS_TEAM, SHEA_TALK])
        self.assertEqual(p["past"], [{"role": "Analyst", "org": "Acme", "when": "2016 - 2018", "src": [1],
                                      "points": [{"text": "Built the reporting for the youth program.", "src": [1]}]}])  # Shopify's page was never opened
        self.assertEqual(p["education"], [])
        self.assertEqual(p["now"], [{"text": "Runs the team that supports students through TKS programs.", "src": [0]}])  # its unseen source is left off
        self.assertIsNone(S.clean_profile(dict(SHEA, sources=SHEA["sources"][2:4]), seen, "person", name="Shea Kim"))  # only unseen or blocked pages
        for bad in (None, {"found": False}, dict(SHEA, confidence="low"), dict(SHEA, found="yes")):
            self.assertIsNone(S.clean_profile(bad, seen, "person", name="Shea Kim"))
        self.assertIsNone(S.clean_profile(SHEA, {}, "person", name="Shea Kim"))  # nothing searched: nothing kept
        # Claude may cite a page by its address too, never by one it didn't see
        p2 = S.clean_profile(dict(SHEA, now=[{"text": "Leads a team of 12.", "sources": [TKS_TEAM, "https://never-seen.example.com/bio"]}]), seen, "person")
        self.assertEqual(p2["now"], [{"text": "Leads a team of 12.", "src": [0]}])
        # a site blocked later (Settings) drops its bullets from the stored profile, and the rest are renumbered
        S.save_settings({"research": {"blocked": ["tks.world"]}})
        v = S.profile_view(p, "person")
        self.assertEqual([s["url"] for s in v["sources"]], [SHEA_TALK])
        self.assertEqual((v["summary"], v["now"], v["forCall"]), (None, [], []))
        self.assertEqual(v["past"][0]["src"], [0])
        self.assertIsNone(S.profile_view(dict(p, v=1), "person"))

    def test_contact_details_and_personal_life_are_dropped(self):
        for t in ("Reach her at ann@acme.com", "Call 416-555-0100", "Phone +44 20 7946 0958", "Married to a designer", "Her husband is a doctor",
                  "Has two kids", "Father of three", "Age 34", "A 34-year-old engineer", "Born in 1990", "Lives in Toronto", "Her religion",
                  "Political party member", "Her health condition", "Was diagnosed last year", "See https://acme.com/team", "Visit www.acme.com"):
            self.assertEqual(S._profile_text(t, 260), "", t)
        for t in ("Ran the 2019 - 2021 intern program.", "Led a team of 40 engineers across 3 offices.", "Worked at Roche Diagnostics.",
                  "Built tools for a digital health startup.", "Program Manager, 2018-2021"):
            self.assertEqual(S._profile_text(t, 260), t, t)
        self.assertEqual(S._profile_text("Runs programs for students aged 13 to 17", 260, personal=False), "Runs programs for students aged 13 to 17")
        long = S._profile_text("word " * 100, 260)
        self.assertTrue(len(long) <= 260 and long.endswith("…"))

    def test_web_fetch_results_count_as_seen(self):
        self.fake(deep_reply("{}", searched=[TKS_TEAM], fetched=[SHEA_PROFILE], asked={SHEA_PROFILE: "https://linkedin.com/in/shea-kim?trk=x"},
                             failed=["https://broken.example.com/page"]))
        stop, _, seen = S.run_search(S.research_request("Shea Kim", "Tks", "tks.world", "shea@tks.world"), S.DEEP_BUDGET, S.DEEP_RESUMES)
        self.assertEqual(stop, "end_turn")
        self.assertIn(S.url_key(TKS_TEAM), seen)
        self.assertIn(S.url_key(SHEA_PROFILE), seen)                                    # the page web fetch opened
        self.assertIn(S.url_key("https://linkedin.com/in/shea-kim?trk=x"), seen)     # and the address Claude asked it to open
        self.assertNotIn(S.url_key("https://broken.example.com/page"), seen)           # a fetch that failed opened nothing
        self.assertNotIn(S.url_key("https://printed-by-code.example/x"), seen)         # an address a code run printed isn't a page Overture saw
        # a paused deep search is resent with its code container, and the pages of every part count
        f = self.fake(deep_reply("", searched=[TKS_TEAM], stop="pause_turn", container=SimpleNamespace(id="container_abc")),
                      deep_reply(SHEA, fetched=[SHEA_PROFILE]))
        out = S.research_person("Shea Kim", "Tks", "tks.world", "shea@tks.world")
        self.assertEqual(len(f.calls), 2)
        self.assertEqual(f.calls[1]["container"], "container_abc")
        self.assertNotIn("container", f.calls[0])
        self.assertEqual([s["url"] for s in out["profile"]["sources"]], [TKS_TEAM, SHEA_PROFILE])

    def test_requests_send_no_email_and_block_sites_in_both_tools(self):
        S.save_settings({"research": {"blocked": ["people-site.com", "zoominfo.com"]}})
        f = self.fake(deep_reply({"found": False}, searched=[TKS_TEAM]), deep_reply({"found": False}))
        live, meta, rec = self.build([att("skim@tks.world", "Shea Kim")])
        S.queue_research(meta, rec, NOW)
        S.queue_org_research(meta, rec, NOW)
        while S.research_step(NOW):
            pass
        self.assertEqual(len(f.calls), 2)  # the person, then the company
        for call in f.calls:
            sent = json.dumps(call, default=str)
            self.assertNotIn("@", sent)
            self.assertNotIn("skim", sent.lower())
            self.assertIn("tks.world", call["messages"][0]["content"])
            self.assertEqual([t["name"] for t in call["tools"]], ["web_search", "web_fetch"])
            for t in call["tools"]:
                self.assertIn("zoominfo.com", t["blocked_domains"])
                self.assertIn("people-site.com", t["blocked_domains"])
                self.assertIn("spokeo.com", t["blocked_domains"])
                self.assertEqual(len(t["blocked_domains"]), len(set(t["blocked_domains"])))
            self.assertEqual(call["output_config"], {"effort": "medium"})
        self.assertIn("Shea Kim", f.calls[0]["messages"][0]["content"])
        self.assertNotIn("Shea", json.dumps(f.calls[1]))  # the company request holds only its name and website
        self.assertEqual(f.calls[1]["system"], S.ORG_RESEARCH_SYSTEM)
        with self.assertRaises(S.ResearchError):
            S.org_research_request("Gmail", "gmail.com")
        with self.assertRaises(S.ResearchError):
            S.org_research_request("Example", "example.com")
        # nothing found: a plain note, never "look it up"
        r = S.research_view("skim@tks.world", S.load_records()["people"]["skim@tks.world"], meta["skim@tks.world"])
        self.assertEqual((r["status"], r["profile"]), ("unknown", None))
        self.assertEqual(r["note"], "Overture searched 1 site and found no public work information about them.")
        self.assertEqual(S.searched_note({"searched": 6}, "information about this company"), "Overture searched 6 sites and found no public information about this company.")
        self.assertEqual(S.searched_note({}, "work information about them"), "Overture searched the web and found no public work information about them.")

    def test_an_old_quick_record_is_looked_up_deeply_once(self):
        email = "shea@tks.world"
        # Shea, looked up the old quick way two days ago: a title, no profile
        S.merge_research(email, dict(S.unknown_result(), status="done", title="Director, Program Success", relationship="employee",
                                     confidence="medium", sources=[{"url": TKS_TEAM, "label": "Team"}]), NOW - timedelta(days=2))
        self.assertTrue(S.needs_research(S.load_records()["people"][email], NOW))
        f = self.fake(deep_reply(SHEA, searched=[TKS_TEAM, SHEA_TALK], fetched=[SHEA_PROFILE]))
        self.assertTrue(self.queue(self.SHEA_GUEST)[0])
        S.research_step(NOW)
        self.assertEqual(len(f.calls), 1)
        rec = S.load_records()["people"][email]
        self.assertEqual(rec["profile"]["v"], 2)
        self.assertFalse(self.queue(self.SHEA_GUEST)[0])  # once
        self.assertFalse(self.queue(self.SHEA_GUEST, NOW + timedelta(days=40))[0])
        # an old "found nothing" gets one deep look too; a deep "found nothing" waits the 30 days
        S.merge_research("ann.ko@tks.world", S.unknown_result(), NOW - timedelta(days=2))
        self.assertTrue(S.needs_research(S.load_records()["people"]["ann.ko@tks.world"], NOW))
        S.merge_research("ann.ko@tks.world", dict(S.unknown_result(), profile=None, searched=4), NOW - timedelta(days=1))
        rec = S.load_records()["people"]["ann.ko@tks.world"]
        self.assertFalse(S.needs_research(rec, NOW))
        self.assertTrue(S.needs_research(rec, NOW + timedelta(days=31)))
        # a profile of an older kind is redone, and dropped if the new look finds nothing (so it isn't redone again and again)
        S.merge_research("bo.ng@tks.world", dict(S.unknown_result(), profile=None), NOW)
        with S.RECORDS_LOCK:
            r = S.load_records()
            r["people"]["bo.ng@tks.world"]["profile"] = {"v": 1, "summary": "old"}
            S.save_json(S.records_path(), r)
        self.assertTrue(S.needs_research(S.load_records()["people"]["bo.ng@tks.world"], NOW))
        S.merge_research("bo.ng@tks.world", dict(S.unknown_result(), profile=None), NOW)
        self.assertNotIn("profile", S.load_records()["people"]["bo.ng@tks.world"])
        # a title you typed, or details you confirmed, are never redone on their own
        S.merge_research("dee.li@tks.world", dict(S.unknown_result(), status="done", title="CTO"), NOW - timedelta(days=2))
        S.write_records("person", {"email": "dee.li@tks.world", "title": "Chief Technology Officer"})
        self.assertFalse(S.needs_research(S.load_records()["people"]["dee.li@tks.world"], NOW))
        S.merge_research("eve.ma@tks.world", dict(S.unknown_result(), status="done", title="CTO"), NOW - timedelta(days=2))
        S.write_records("person", {"email": "eve.ma@tks.world", "confirm": True})
        self.assertFalse(S.needs_research(S.load_records()["people"]["eve.ma@tks.world"], NOW))

    def test_company_research_for_outside_companies_only(self):
        guests = self.SHEA_GUEST + [att("sam.lee@gmail.com", "Sam Lee"), att("ann.lee@example.com", "Ann Lee"), att("jo.park@spotify.com", "Jo Park")]
        live, meta, rec = self.build(guests)
        self.assertEqual(live["companyDomains"], {"Tks": "tks.world"})
        os.environ.pop("ANTHROPIC_API_KEY", None)
        self.assertFalse(S.queue_org_research(meta, rec, NOW))  # no key: nothing queued
        self.assertEqual(S.research_body()["orgs"]["tks.world"]["note"], S.ORG_NO_KEY_NOTE)
        os.environ["ANTHROPIC_API_KEY"] = "test-key"
        S.save_settings({"research": {"web": False}})
        self.assertFalse(S.queue_org_research(meta, rec, NOW))  # web research off: nothing queued
        S.save_settings({"research": {"web": True}})
        f = self.fake(deep_reply(TKS_ORG, searched=[TKS_HOME, TKS_NEWS], fetched=[TKS_ABOUT]))
        self.assertTrue(S.queue_org_research(meta, rec, NOW))
        with S.RQ_LOCK:
            self.assertEqual(S.RQ["queue"], [("co:tks.world", False)])  # not gmail.com, example.com or your own company
        orgs = S.research_body()["orgs"]
        self.assertEqual(set(orgs), {"tks.world", "example.com"})
        self.assertEqual(orgs["tks.world"]["status"], "pending")
        self.assertEqual(orgs["example.com"]["status"], "skipped")
        self.assertIn("Can't find this company", orgs["example.com"]["note"])
        self.assertFalse(S.queue_org_research(meta, rec, NOW))  # one job per domain
        while S.research_step(NOW):
            pass
        self.assertEqual(len(f.calls), 1)
        self.assertIn("Company: Tks\nCompany website: https://tks.world", f.calls[0]["messages"][0]["content"])
        o = S.load_records()["orgs"]["tks.world"]
        self.assertEqual((o["lookup"], o["name"], o["searched"]), ("done", "Tks", 2))
        p = o["profile"]
        self.assertEqual((p["v"], p["domain"], p["name"], p["confidence"]), (2, "tks.world", "The Knowledge Society (TKS)", "high"))
        self.assertEqual([s["url"] for s in p["sources"]], [TKS_HOME, TKS_ABOUT, TKS_NEWS])
        self.assertEqual(p["summary"], {"text": "The Knowledge Society (TKS) runs innovation programs for teens.", "src": [0]})
        self.assertEqual(p["facts"], [{"label": "Founded", "value": "2016", "src": [1]}, {"label": "Headquarters", "value": "Toronto", "src": [1]}])
        self.assertEqual(p["what"], [{"text": "Runs year-long programs on emerging technology for students aged 13 to 17.", "src": [0, 1]}])
        self.assertEqual(p["news"], [{"text": "Opened programs in two more cities.", "when": "March 2026", "src": [2]}])
        self.assertEqual((p["tech"], p["forCall"]), ([], [{"text": "Ask how Program Success tracks student outcomes today.", "src": [0]}]))
        # live.companies[name].profile (a row research made is marked), live.orgs and GET /api/research orgs[domain]
        live2, meta2, rec2 = self.build(guests)
        row = live2["companies"]["Tks"]
        self.assertEqual((row["profile"], row["researchOnly"], row["domain"], row["status"]), (p, True, "tks.world", "Prospect"))
        self.assertEqual((live2["orgs"]["tks.world"]["status"], live2["orgs"]["tks.world"]["company"]), ("done", "Tks"))
        self.assertEqual(S.research_body()["orgs"]["tks.world"]["profile"], p)
        first = next(w for w in live2["watch"] if w["kind"] == "First meeting")
        self.assertTrue(first["text"].endswith("so this looks like your first talk. The Knowledge Society (TKS) runs innovation programs for teens."))
        # a company in your records keeps its row; the profile is added to it
        S.write_records("company", {"name": "Tks", "domain": "tks.world", "status": "New lead", "notes": "Intro from Devursh"})
        row = self.build(guests)[0]["companies"]["Tks"]
        self.assertEqual((row["status"], row["notes"], row["profile"]["name"], "researchOnly" in row), ("New lead", "Intro from Devursh", p["name"], False))
        # 30 days, then once more
        self.assertFalse(S.queue_org_research(meta2, S.load_records(), NOW + timedelta(days=29)))
        self.assertTrue(S.queue_org_research(meta2, S.load_records(), NOW + timedelta(days=31)))

    def test_the_brief_and_answers_get_the_research_and_no_homework(self):
        for phrase in ("what to do before the call", "what to add to Overture"):
            self.assertNotIn(phrase, S.SYSTEM + S.ASK_SYSTEM)
        self.assertIn("never tell the reader to look anything up", S.SYSTEM)
        self.assertIn("never call a fact automatic or unconfirmed", S.SYSTEM)
        self.assertIn("End with what to bring up on the call", S.SYSTEM)
        self.assertIn("Never tell them to look something up or to add it to Overture's records", S.ASK_SYSTEM)
        homework = re.compile(r"(?i)\b(?:look (?:them|it|this|that) up|check it|confirm (?:it|their)|verify|add (?:it|them|what you learn) to)\b")
        self.fake(deep_reply(SHEA, searched=[TKS_TEAM, SHEA_TALK], fetched=[SHEA_PROFILE]), deep_reply(TKS_ORG, searched=[TKS_HOME, TKS_NEWS], fetched=[TKS_ABOUT]))
        live, meta, rec = self.build(self.SHEA_GUEST)
        for w in live["watch"]:
            self.assertIsNone(homework.search(w["text"]), w["text"])
        S.queue_research(meta, rec, NOW)
        S.queue_org_research(meta, rec, NOW)
        while S.research_step(NOW):
            pass
        live, _, _ = self.build(self.SHEA_GUEST)
        for w in live["watch"]:
            self.assertIsNone(homework.search(w["text"]), w["text"])
        # the brief's facts carry both profiles (as plain sentences), also when only titles may go to AI
        facts = {"call": {"title": "Intro", "company": "Tks"}, "people": [{"name": "Shea Kim", "title": "Director, Program Success", "note": "n"}],
                 "company": None}
        for share in ("notes", "titles"):
            S.save_settings({"research": {"aiShare": share}})
            out = S.brief_facts(facts, S.load_records())
            self.assertEqual(out["people"][0]["profile"]["summary"], "Shea Kim leads Program Success at The Knowledge Society.")
            self.assertEqual(out["people"][0]["profile"]["past"][0]["org"], "Shopify")
            self.assertEqual(out["company"]["profile"]["name"], "The Knowledge Society (TKS)")
            self.assertEqual(out["company"]["profile"]["facts"], {"Founded": "2016", "Headquarters": "Toronto"})
            self.assertNotIn("http", json.dumps(out["people"][0]["profile"]))
        self.assertNotIn("note", out["people"][0])  # titles only: still no notes
        self.assertNotIn("profile", facts["people"][0])  # the page's copy is untouched
        other = S.brief_facts({"call": {"company": "Acme"}, "people": [{"name": "Shea Kim"}], "company": None}, S.load_records())
        self.assertNotIn("profile", other["people"][0])  # another company's call: not this Shea
        self.assertIsNone(other["company"])
        # Ask Overture: this call's people and company carry their research
        ctx = json.loads(S.ask_context("who is Shea?", live["invites"][0]["id"], live, S.load_records()))
        self.assertEqual(ctx["thisCall"]["people"][0]["overtureResearch"]["summary"], "Shea Kim leads Program Success at The Knowledge Society.")
        self.assertEqual(ctx["thisCall"]["companyResearch"]["name"], "The Knowledge Society (TKS)")
        self.assertNotIn("profile", ctx["overtureRecords"]["people"]["shea@tks.world"])


class ServerBase(Fresh):
    """The real handler on a spare local port (127.0.0.1 only)."""

    @classmethod
    def setUpClass(cls):
        cls.old_port = S.PORT
        cls.old_log = S.Handler.log_message
        S.Handler.log_message = lambda *a, **k: None  # keep test output quiet
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(S.Handler, directory=str(S.HERE)))
        S.PORT = cls.httpd.server_address[1]
        cls.t = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.t.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        S.PORT = cls.old_port
        S.Handler.log_message = cls.old_log

    def req(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", S.PORT, timeout=10)
        h = {"Host": "localhost:%d" % S.PORT}
        h.update(headers or {})
        data = json.dumps(body).encode() if body is not None else None
        if data is not None:
            h.setdefault("Content-Type", "application/json")
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        out = (r.status, r.read().decode("utf-8", "replace"), dict(r.getheaders()))
        c.close()
        return out



class ServerEndToEnd(ServerBase):
    def test_writes_need_header_and_origin(self):
        origin = "http://localhost:%d" % S.PORT
        body = {"name": "Acme", "status": "New lead"}
        self.assertEqual(self.req("PUT", "/api/records/company", body)[0], 403)
        self.assertEqual(self.req("PUT", "/api/records/company", body, {"X-OVERTURE": "1"})[0], 403)
        self.assertEqual(self.req("PUT", "/api/records/company", body, {"X-OVERTURE": "1", "Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.req("PUT", "/api/records/company", body, {"X-OVERTURE": "1", "Origin": origin, "Content-Type": "text/plain"})[0], 403)
        st, txt, _ = self.req("PUT", "/api/records/company", body, {"X-OVERTURE": "1", "Origin": origin})
        self.assertEqual(st, 200, txt)
        st, txt, _ = self.req("PUT", "/api/records/company", {"name": 5}, {"X-OVERTURE": "1", "Origin": origin})
        self.assertEqual(st, 400)
        st, txt, _ = self.req("POST", "/api/records/apply", {"callId": "e1", "company": "Acme", "accept": [{"kind": "Deal", "text": "Budget approved"}]}, {"X-OVERTURE": "1", "Origin": origin})
        self.assertEqual(st, 200, txt)
        st, txt, _ = self.req("GET", "/api/records")
        self.assertEqual(json.loads(txt)["companies"]["Acme"]["status"], "New lead")
        self.assertEqual(self.req("GET", "/api/records", headers={"Sec-Fetch-Site": "cross-site"})[0], 403)
        self.assertEqual(self.req("GET", "/api/records", headers={"Host": "evil.example"})[0], 403)

    def test_status_live_js_and_secrets(self):
        st, txt, _ = self.req("GET", "/api/status")
        j = json.loads(txt)
        self.assertEqual(st, 200)
        self.assertEqual(set(j), {"hosted", "claude", "google", "ai", "hubspot", "gong", "granola", "meetily"})
        self.assertEqual((j["hubspot"]["configured"], j["hubspot"]["connected"], j["gong"]["configured"], j["gong"]["connected"]), (False, False, False, False))
        st, txt, h = self.req("GET", "/data/live.js")
        self.assertEqual(st, 200)
        self.assertIn("text/javascript", h.get("Content-Type", ""))
        self.assertIn("window.OVERTURE_LIVE = null;", txt)
        st, txt, _ = self.req("GET", "/data/live.js", headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(txt.strip(), "window.OVERTURE_LIVE = null;")
        self.assertNotIn("OVERTURE_STATUS", txt)
        S.save_json(S.token_path(), {"access_token": "AT-secret", "refresh_token": "RT-secret", "expires_at": 0})
        for p in ("/.data/google-token.json", "/%2Edata/google-token.json", "/.DATA/google-token.json"):
            st, txt, _ = self.req("GET", p)
            self.assertEqual(st, 404, p)
            self.assertNotIn("secret", txt)
            self.assertEqual(self.req("HEAD", p)[0], 404, p)

    def test_dot_folders_by_short_name_or_odd_targets(self):
        # Windows also names .data "DATA~1" (8.3 short name); that spelling must not reach it either.
        long = S.HERE / ".data"
        long.mkdir(exist_ok=True)
        probe = long / "overture-test-probe.json"
        probe.write_text('{"refresh_token": "RT-secret"}')
        try:
            paths = ["/x://.data/overture-test-probe.json"]
            if os.name == "nt":
                import ctypes
                buf = ctypes.create_unicode_buffer(1024)
                short = Path(buf.value).name if ctypes.windll.kernel32.GetShortPathNameW(str(long), buf, 1024) else ""
                if short and short != ".data":
                    paths += ["/" + short + "/overture-test-probe.json", "/" + short + "/", "/" + short.lower() + "/overture-test-probe.json"]
            for p in paths:
                st, txt, _ = self.req("GET", p)
                self.assertEqual(st, 404, p)
                self.assertNotIn("RT-secret", txt, p)
                self.assertNotIn("overture-test-probe", txt, p)
                self.assertEqual(self.req("HEAD", p)[0], 404, p)
            st, txt, _ = self.req("GET", "x://.data/overture-test-probe.json")  # absolute-form target
            self.assertEqual(st, 403)
            self.assertNotIn("RT-secret", txt)
        finally:
            probe.unlink()

    def test_static_files_need_our_host(self):
        self.assertEqual(self.req("GET", "/index.html")[0], 200)
        self.assertEqual(self.req("GET", "/index.html", headers={"Host": "127.0.0.1:%d" % S.PORT})[0], 200)
        self.assertEqual(self.req("HEAD", "/index.html")[0], 200)
        for p in ("/index.html", "/", "/data/sample.js"):
            self.assertEqual(self.req("GET", p, headers={"Host": "rebind.example:%d" % S.PORT})[0], 403, p)
            self.assertEqual(self.req("HEAD", p, headers={"Host": "rebind.example:%d" % S.PORT})[0], 403, p)

    def test_auth_routes(self):
        st, txt, _ = self.req("GET", "/auth/google")
        self.assertEqual(st, 503)  # no client set up yet
        self.assertIn("GOOGLE-SETUP", txt)
        S.save_json(Path(TMP) / "google-client.json", {"web": {"client_id": "cid", "client_secret": "sec"}})
        st, _, h = self.req("GET", "/auth/google")
        self.assertEqual(st, 302)
        loc = h["Location"]
        self.assertTrue(loc.startswith(S.AUTH_URL))
        self.assertNotIn("sec", urllib.parse.parse_qs(urllib.parse.urlsplit(loc).query).get("client_secret", [""])[0] or "")
        st, txt, _ = self.req("GET", "/auth/google/callback?code=abc&state=forged")
        self.assertEqual(st, 400)
        self.assertIn("expired", txt)
        st, txt, _ = self.req("GET", "/auth/google/callback?error=access_denied&state=x")
        self.assertEqual(st, 400)
        self.assertEqual(self.req("POST", "/auth/google/disconnect")[0], 403)

    def test_research_guards(self):
        origin = "http://localhost:%d" % S.PORT
        old = (S.research_client, S.RESEARCH_AUTOSTART)
        S.RESEARCH_AUTOSTART = False
        with S.RQ_LOCK:
            S.RQ.update(queue=[], pending=set(), running=set(), errors={},
                        meta={"ann.lee@acme.com": {"name": "Ann Lee", "company": "Acme", "domain": "acme.com", "callId": "u1", "named": True, "internal": False, "local": {}}})
        try:
            st, txt, _ = self.req("GET", "/api/research")
            self.assertEqual(st, 200)
            self.assertEqual(json.loads(txt)["people"]["ann.lee@acme.com"]["note"], "Add a Claude key to look up titles automatically")
            self.assertEqual(self.req("GET", "/api/research", headers={"Sec-Fetch-Site": "cross-site"})[0], 403)
            self.assertEqual(self.req("GET", "/api/research", headers={"Host": "evil.example"})[0], 403)
            self.assertEqual(self.req("HEAD", "/api/research")[0], 404)
            body = {"email": "ann.lee@acme.com"}
            self.assertEqual(self.req("POST", "/api/research", body)[0], 403)
            self.assertEqual(self.req("POST", "/api/research", body, {"X-OVERTURE": "1"})[0], 403)
            self.assertEqual(self.req("POST", "/api/research", body, {"X-OVERTURE": "1", "Origin": "https://evil.example"})[0], 403)
            self.assertEqual(self.req("POST", "/api/research", body, {"X-OVERTURE": "1", "Origin": origin, "Content-Type": "text/plain"})[0], 403)
            st, txt, _ = self.req("POST", "/api/research", body, {"X-OVERTURE": "1", "Origin": origin})
            self.assertEqual((st, json.loads(txt)), (503, {"error": "no-key"}))
            os.environ["ANTHROPIC_API_KEY"] = "test-key"
            self.assertEqual(self.req("POST", "/api/research", {"email": "x"}, {"X-OVERTURE": "1", "Origin": origin})[0], 400)
            self.assertEqual(self.req("POST", "/api/research", {"email": "a@acme.com", "x": 1}, {"X-OVERTURE": "1", "Origin": origin})[0], 400)
            self.assertEqual(self.req("POST", "/api/research", {"email": "who@other.com"}, {"X-OVERTURE": "1", "Origin": origin})[0], 404)
            st, txt, _ = self.req("POST", "/api/research", body, {"X-OVERTURE": "1", "Origin": origin})
            self.assertEqual((st, json.loads(txt)["status"]), (202, "pending"))
            self.assertEqual(json.loads(self.req("GET", "/api/research")[1])["people"]["ann.lee@acme.com"]["status"], "pending")
        finally:
            os.environ.pop("ANTHROPIC_API_KEY", None)
            S.research_client, S.RESEARCH_AUTOSTART = old
            with S.RQ_LOCK:
                S.RQ.update(queue=[], pending=set(), running=set(), errors={}, meta={})

    def test_ask_without_key(self):
        origin = "http://localhost:%d" % S.PORT
        st, txt, _ = self.req("POST", "/api/ask", {"question": "Who is on my next call?"}, {"X-OVERTURE": "1", "Origin": origin})
        self.assertEqual((st, json.loads(txt)), (503, {"error": "no-key"}))
        self.assertEqual(self.req("POST", "/api/ask", {"question": "x"})[0], 403)
        st, _, _ = self.req("POST", "/api/ask", {"question": ""}, {"X-OVERTURE": "1", "Origin": origin})
        self.assertEqual(st, 400)


# ---------------------------------------------------------------- HubSpot and Gong (fake HTTP, no network) ----------------------------------------------------------------

HS_TOKEN = "pat-na1-SECRET-hubspot-0000"
GRANOLA_KEY = "grn_SECRET-granola-0000"
GONG_KEY, GONG_SECRET = "GONGKEY-SECRET-1111", "GONGSECRET-SECRET-2222"
SECRETS = (HS_TOKEN, GONG_KEY, GONG_SECRET, base64.b64encode((GONG_KEY + ":" + GONG_SECRET).encode()).decode())


def gong_call(cid, title, started, *emails, **meta):
    return {"metaData": dict({"id": cid, "title": title, "started": started}, **meta), "parties": [{"emailAddress": e} for e in emails]}


class FakeApi:
    """Stands in for server.API_HTTP: answers HubSpot and Gong from small tables, records every request."""

    def __init__(self):
        self.calls, self.queued = [], []   # queued: (path prefix, answer) handed out first, answer = (status, body, headers) or an Exception
        self.after = None                  # after(path) runs on every request (a test can move a fake clock)
        self.gong_page = 1                 # calls per Gong page, oldest first (what Gong is reported to do)
        self.transcripts, self.parties = {}, {}  # Gong call id -> transcript monologues / parties (speakerId, name)
        self.gong_calls = [
            gong_call("g1", "Acme intro", "2026-08-01T15:00:00Z", "ann.lee@acme.com", "chris@spotify.com", duration=900, url="https://app.gong.io/call?id=g1"),
            gong_call("g9", "Other co", "2026-09-01T15:00:00Z", "x@other.com", duration=600, url="https://app.gong.io/call?id=g9"),
            gong_call("g2", "Acme pricing", "2026-09-10T15:00:00Z", "bo.chen@acme.com", duration=1830, url="javascript:alert(1)")]

    def __call__(self, method, url, body=None, headers=None, timeout=8):
        self.calls.append({"method": method, "url": url, "body": json.loads(json.dumps(body)) if body is not None else None, "headers": dict(headers or {})})
        u = urllib.parse.urlsplit(url)
        path = u.path + ("?" + u.query if u.query else "")
        if self.after:
            self.after(u.path)
        for i, (prefix, answer) in enumerate(self.queued):
            if path.startswith(prefix):
                del self.queued[i]
                if isinstance(answer, Exception):
                    raise answer
                return answer
        return self.route(method, u.netloc, u.path, body or {})

    def writes(self):
        return [c for c in self.calls if c["method"] in ("PATCH", "PUT", "DELETE") or c["url"].endswith("/crm/v3/objects/notes")]

    def route(self, method, host, path, body):
        if host == "api.hubapi.com":
            if path == "/account-info/v3/details":
                return 200, {"portalId": 4242, "uiDomain": "app.hubspot.com", "companyCurrency": "USD"}, {}
            if path == "/crm/v3/pipelines/deals":
                return 200, {"results": [{"id": "default", "label": "Sales", "stages": [
                    {"id": "s1", "label": "Contract sent", "metadata": {"isClosed": "false"}},
                    {"id": "closedwon", "label": "Closed won", "metadata": {"isClosed": "true"}}]}]}, {}
            if path == "/crm/v3/objects/companies/search":
                d = body["filterGroups"][0]["filters"][0]["value"]
                if d == "acme.com":
                    return 200, {"total": 1, "results": [{"id": "101", "properties": {"name": "Acme Corp", "domain": "acme.com", "lifecyclestage": "opportunity", "numberofemployees": "1200"}}]}, {}
                return 200, {"total": 0, "results": []}, {}
            if path == "/crm/v4/objects/companies/101/associations/deals":
                return 200, {"results": [{"toObjectId": 501}, {"toObjectId": 502}]}, {}
            if path == "/crm/v3/objects/deals/batch/read":
                return 200, {"results": [
                    {"id": "502", "properties": {"dealname": "Portal 2025", "dealstage": "closedwon", "amount": "20000", "closedate": "2025-06-30T00:00:00Z"}},
                    {"id": "501", "properties": {"dealname": "Portal renewal <b>", "dealstage": "s1", "amount": "48000", "closedate": "2026-11-30T00:00:00Z"}}]}, {}
            if path == "/crm/v3/objects/notes/search":
                if body["filterGroups"][0]["filters"][0]["value"] != "101":
                    return 200, {"total": 0, "results": []}, {}
                return 200, {"total": 1, "results": [{"id": "701", "properties": {"hs_note_body": "<p>Asked about <b>SSO</b> &amp; pricing</p>", "hs_timestamp": "2026-10-01T15:00:00Z"}}]}, {}
            if path == "/crm/v3/objects/contacts/search":
                people = {"ann.lee@acme.com": ("9001", "Ann", "Lee", "VP Platform"), "bo.chen@acme.com": ("9002", "Bo", "Chen", "")}
                flt = body["filterGroups"][0]["filters"]
                if flt[0]["propertyName"] == "hs_email_domain":  # contacts on a company's domain (people mentioned on a call)
                    extra = {"cy.diaz@acme.com": ("9003", "Cy", "Diaz", "Head of Security")}
                    return 200, {"results": [{"id": v[0], "properties": {"email": e, "firstname": v[1], "lastname": v[2], "jobtitle": v[3]}}
                                             for e, v in {**people, **extra}.items() if e.endswith("@" + flt[0]["value"])]}, {}
                if flt[0]["propertyName"] == "firstname":  # is there a contact with this name already?
                    names = {(v[1], v[2]) for v in people.values()}
                    hit = (flt[0]["value"], flt[1]["value"]) in names
                    return 200, {"results": [{"id": "9001", "properties": {}}] if hit else []}, {}
                vals = body["filterGroups"][0]["filters"][0]["values"]
                return 200, {"results": [{"id": people[e][0], "properties": {"email": e, "firstname": people[e][1], "lastname": people[e][2], "jobtitle": people[e][3]}}
                                         for e in vals if e in people]}, {}
            if path == "/crm/v3/objects/notes" and method == "POST":
                return 201, {"id": "8001"}, {}
            if path == "/crm/v3/objects/contacts" and method == "POST":
                return 201, {"id": "9100"}, {}
            if path.startswith("/crm/v3/objects/contacts/") and method == "PATCH":
                return 200, {"id": path.rsplit("/", 1)[1]}, {}
        if host == "api.gong.io":
            if path == "/v2/workspaces":
                return 200, {"workspaces": [{"id": "1", "name": "Sales NA"}]}, {}
            if path == "/v2/calls/transcript":
                return 200, {"callTranscripts": [{"callId": cid, "transcript": t} for cid, t in self.transcripts.items()
                                                 if cid in (body.get("filter") or {}).get("callIds", [])]}, {}
            if path == "/v2/calls/extensive":
                flt = body.get("filter") or {}
                if flt.get("callIds") and ((body.get("contentSelector") or {}).get("exposedFields") or {}).get("parties"):
                    return 200, {"calls": [{"metaData": {"id": i}, "parties": self.parties.get(i, [])} for i in flt["callIds"]]}, {}
                if flt.get("callIds"):
                    return 200, {"records": {}, "calls": [{"metaData": {"id": "g2"}, "content": {
                        "brief": "They run Backstage 1.20 <script>x</script>", "keyPoints": [{"text": "Wants SSO"}],
                        "topics": [{"name": "Pricing", "duration": 300}],
                        "trackers": [{"id": "t1", "name": "Competitors", "count": 2}, {"id": "t2", "name": "Never said", "count": 0}]}}]}, {}
                lo, hi = datetime.fromisoformat(flt["fromDateTime"]), datetime.fromisoformat(flt["toDateTime"])
                started = lambda c: datetime.fromisoformat(c["metaData"]["started"])
                found = sorted((c for c in self.gong_calls if lo <= started(c) < hi), key=started)
                at = int(body.get("cursor") or 0)
                nxt = at + self.gong_page
                return 200, {"records": {"cursor": str(nxt)} if nxt < len(found) else {}, "calls": found[at:nxt]}, {}
        return 404, {}, {}


class Clock:
    """Stands in for server._time: real time plus a jump the test controls."""

    def __init__(self):
        self.jump = 0.0

    def time(self):
        return time.time() + self.jump

    def sleep(self, s):
        pass


def acme_events(start):
    return [ev("e1", start.isoformat(), 30, [SELF, att("ann.lee@acme.com", "Ann Lee"), att("bo.chen@acme.com", "Bo Chen")], summary="Acme: pricing")]


class CrmFakes:
    def crm_setup(self):
        with S.CRM_LOCK:
            S.CRM_CACHE.clear()
            for st in S.CRM_STATE.values():
                st.update(lastSync="", lastError="", pausedUntil=0.0, checkedAt=0.0, account="")
        with S.RQ_LOCK:
            S.RQ.update(queue=[], pending=set(), running=set(), errors={}, meta={})
        self.old = (S.API_HTTP, S.SLEEP, S.HTTP, S.RESEARCH_AUTOSTART, S.claude_text)
        self.api, self.slept = FakeApi(), []
        S.API_HTTP, S.SLEEP, S.RESEARCH_AUTOSTART = self.api, self.slept.append, False

    def crm_teardown(self):
        S.API_HTTP, S.SLEEP, S.HTTP, S.RESEARCH_AUTOSTART, S.claude_text = self.old
        for k in ("HUBSPOT_TOKEN", "GONG_ACCESS_KEY", "GONG_ACCESS_SECRET", "GONG_BASE_URL", "ANTHROPIC_API_KEY"):
            os.environ.pop(k, None)

    def connect(self, hubspot=True, gong=True):
        if hubspot:
            S.save_json(Path(TMP) / "hubspot.json", {"token": HS_TOKEN})
        if gong:
            S.save_json(Path(TMP) / "gong.json", {"access_key": GONG_KEY, "access_secret": GONG_SECRET, "base_url": "https://api.gong.io"})

    def google(self):
        """A connected Google account whose calendar holds one Acme call in two days."""
        S.save_json(S.token_path(), {"access_token": "AT-x", "refresh_token": "RT-x", "expires_at": time.time() + 3000, "email": "chris@spotify.com", "name": "Chris Park"})
        start = (datetime.now(timezone.utc) + timedelta(days=2)).replace(microsecond=0)
        S.HTTP = lambda method, url, form=None, headers=None, timeout=15: (200, {"items": acme_events(start)}) if url.startswith(S.EVENTS_URL) else (404, {})



class Crm(Fresh, CrmFakes):
    def setUp(self):
        super().setUp()
        self.crm_setup()

    def tearDown(self):
        self.crm_teardown()

    def fetch(self, rec=None, now=NOW):
        rec = rec or S.empty_records()
        events = acme_events(NOW + timedelta(days=1))
        crm = S.crm_fetch(S.upcoming_invites(events, ME["email"], rec, now), ME["email"], rec, now)
        meta = {}
        return S.build_live(events, ME, rec, now, meta_out=meta, crm=crm), crm, meta, rec

    def test_request_building_and_auth_headers(self):
        self.connect()
        self.fetch()
        hs = [c for c in self.api.calls if "hubapi" in c["url"]]
        gg = [c for c in self.api.calls if "gong.io" in c["url"]]
        self.assertTrue(hs and gg)
        for c in hs:
            self.assertTrue(c["url"].startswith("https://api.hubapi.com/"), c["url"])
            self.assertEqual(c["headers"], {"Authorization": "Bearer " + HS_TOKEN})
        basic = "Basic " + base64.b64encode((GONG_KEY + ":" + GONG_SECRET).encode()).decode()
        for c in gg:
            self.assertTrue(c["url"].startswith("https://api.gong.io/v2/"), c["url"])
            self.assertEqual(c["headers"], {"Authorization": basic})
        search = next(c for c in hs if c["url"].endswith("/companies/search"))
        self.assertEqual(search["body"]["filterGroups"], [{"filters": [{"propertyName": "domain", "operator": "EQ", "value": "acme.com"}]}])
        self.assertIn("numberofemployees", search["body"]["properties"])
        people = next(c for c in hs if c["url"].endswith("/contacts/search"))
        self.assertEqual(people["body"]["filterGroups"][0]["filters"][0], {"propertyName": "email", "operator": "IN", "values": ["ann.lee@acme.com", "bo.chen@acme.com"]})
        self.assertFalse(any("chris@spotify.com" in json.dumps(c["body"]) for c in hs))  # your own address isn't looked up
        lists = [c for c in gg if c["url"].endswith("/calls/extensive") and "fromDateTime" in c["body"]["filter"]]
        days = lambda c, k: (NOW - datetime.fromisoformat(c["body"]["filter"][k])).days
        # newest first: the last 14 days, then further back to 180 days; the 45-90 day window had two pages (followed the cursor)
        self.assertEqual([(days(c, "toDateTime"), days(c, "fromDateTime")) for c in lists], [(0, 14), (14, 45), (45, 90), (45, 90), (90, 180)])
        self.assertEqual([c["body"].get("cursor") for c in lists], [None, None, None, "1", None])
        detail = next(c for c in gg if "callIds" in c["body"]["filter"])
        self.assertEqual(detail["body"]["filter"]["callIds"], ["g2"])
        self.assertEqual(set(detail["body"]["contentSelector"]["exposedFields"]["content"]), {"brief", "keyPoints", "topics", "trackers"})
        self.assertFalse(any("transcript" in c["url"] or "transcript" in json.dumps(c["body"] or {}).lower() for c in gg))  # never transcripts
        self.assertEqual(self.api.writes(), [])  # reading never writes

    def test_mapping_into_live_shape(self):
        self.connect()
        live, crm, meta, _ = self.fetch()
        c = live["companies"]["Acme"]
        self.assertEqual(c["status"], "Open deal: Contract sent")
        self.assertEqual((c["employees"], c["engineers"], c["customer"]), (1200, None, False))
        self.assertEqual(c["src"], {"status": "HubSpot", "employees": "HubSpot", "deals": "HubSpot"})
        self.assertEqual([d["name"] for d in c["deals"]], ["Portal renewal <b>", "Portal 2025"])  # open deal first; the page escapes
        self.assertEqual((c["deals"][0]["amount"], c["deals"][0]["closeDate"], c["deals"][0]["closed"]), (48000, "2026-11-30", False))
        self.assertEqual(c["history"], [{"date": "2026-10-01", "text": "Asked about SSO & pricing", "src": "HubSpot"}])
        self.assertEqual(live["currency"], "USD")
        ann, bo = live["people"]["ann.lee@acme.com"], live["people"]["bo.chen@acme.com"]
        self.assertEqual((ann["title"], ann["titleSrc"], ann["known"]), ("VP Platform", "HubSpot", True))
        self.assertEqual((bo["title"], bo["known"]), ("", True))
        g = live["gong"]["Acme"]
        self.assertEqual((g["title"], g["date"], g["duration"], g["count"]), ("Acme pricing", "2026-09-10", 1830, 2))
        self.assertEqual(g["url"], "")  # not http(s): dropped
        self.assertEqual((g["keyPoints"], g["topics"], g["trackers"]), (["Wants SSO"], ["Pricing"], [{"name": "Competitors", "count": 2}]))
        self.assertNotIn("Other co", json.dumps(live))
        self.assertEqual(S.hubspot_status({"lifecycle": "customer", "deals": [{"closed": True}]}), "Customer")
        self.assertEqual(S.hubspot_status({"lifecycle": "lead", "deals": []}), "New lead")
        out = S.script_json(live)  # live.js escaping still holds for HubSpot and Gong text
        self.assertNotIn("</", out)

    def test_hubspot_titles_first_and_research_only_without_one(self):
        self.connect(gong=False)
        os.environ["ANTHROPIC_API_KEY"] = "test-key"
        rec = S.empty_records()
        rec["people"]["ann.lee@acme.com"] = {"title": "Engineer", "autoFields": ["title"], "found": "auto", "lookup": "done", "foundAt": "2026-10-19T10:00:00+00:00"}
        live, crm, meta, rec = self.fetch(rec)
        self.assertEqual((live["people"]["ann.lee@acme.com"]["title"], live["people"]["ann.lee@acme.com"]["titleSrc"]), ("VP Platform", "HubSpot"))
        self.assertEqual(live["people"]["ann.lee@acme.com"]["research"]["status"], "skipped")
        self.assertTrue(meta["ann.lee@acme.com"]["crm"])
        self.assertFalse(meta["bo.chen@acme.com"]["crm"])
        S.queue_research(meta, rec, NOW)
        with S.RQ_LOCK:
            queued = [e for e, _ in S.RQ["queue"]]
        self.assertEqual(queued, ["bo.chen@acme.com"])  # HubSpot has no title for Bo, so only Bo is looked up
        # a title you typed in Overture still shows (and is offered to HubSpot after the call)
        rec["people"]["ann.lee@acme.com"] = {"title": "CTO"}
        live, *_ = self.fetch(rec)
        self.assertEqual((live["people"]["ann.lee@acme.com"]["title"], live["people"]["ann.lee@acme.com"]["titleSrc"]), ("CTO", "Overture records"))

    def test_401_403_429_and_timeout(self):
        self.connect()
        self.api.queued = [("/account-info", (401, {"message": "bad token " + HS_TOKEN}, {}))]
        live, crm, *_ = self.fetch()
        st = S.crm_status()
        self.assertIn("401", st["hubspot"]["lastError"])
        self.assertFalse(st["hubspot"]["connected"])
        self.assertNotIn(HS_TOKEN, json.dumps(st))
        self.assertNotIn("hubspot", live["companies"].get("Acme", {}))  # the page still builds without HubSpot
        self.assertEqual(live["gong"]["Acme"]["title"], "Acme pricing")  # and Gong still works
        self.assertTrue(st["gong"]["connected"])
        before = len(self.api.calls)
        self.fetch()  # paused for a minute after a failure: HubSpot isn't asked again
        self.assertFalse(any("hubapi" in c["url"] for c in self.api.calls[before:]))

        self.setUp()
        self.connect()
        self.api.queued = [("/crm/v3/objects/contacts/search", (429, {}, {"Retry-After": "3"}))]
        live, *_ = self.fetch()
        self.assertEqual(self.slept, [3.0])  # one backoff, then the retry worked
        self.assertEqual(live["people"]["ann.lee@acme.com"]["title"], "VP Platform")

        self.setUp()
        self.connect()
        self.api.queued = [("/crm/v3/objects/contacts/search", (429, {}, {})), ("/crm/v3/objects/contacts/search", (429, {}, {}))]
        self.fetch()
        self.assertEqual(len(self.slept), 1)  # only one backoff
        self.assertIn("429", S.crm_status()["hubspot"]["lastError"])

        self.setUp()
        self.connect()
        self.api.queued = [("/v2/calls/extensive", S.ApiError("timeout"))]
        live, *_ = self.fetch()
        self.assertIn("didn't answer in time", S.crm_status()["gong"]["lastError"])
        self.assertNotIn("gong", live)
        self.assertEqual(live["companies"]["Acme"]["status"], "Open deal: Contract sent")

        self.setUp()
        self.connect()
        self.api.queued = [("/crm/v3/pipelines/deals", (403, {}, {}))]
        self.fetch()
        self.assertIn("missing a scope", S.crm_status()["hubspot"]["lastError"])

    def test_gong_404_means_no_calls_and_bad_base_url(self):
        self.connect(hubspot=False)
        self.api.gong_calls = []
        self.api.queued = [("/v2/calls/extensive", (404, {"errors": ["No calls found corresponding to the provided filters"]}, {}))] * len(S.GONG_WINDOWS)
        live, *_ = self.fetch()
        self.assertEqual(self.api.queued, [])  # every window was asked
        self.assertNotIn("gong", live)
        self.assertTrue(S.crm_status()["gong"]["connected"])
        for bad in ("http://api.gong.io", "https://evil.example", "https://api.gong.io.evil.example", "https://user:pw@api.gong.io", "ftp://api.gong.io"):
            with self.assertRaises(S.ApiError, msg=bad):
                S.gong_base(bad)
        self.assertEqual(S.gong_base("https://us-123.api.gong.io/v2/"), "https://us-123.api.gong.io")
        S.save_json(Path(TMP) / "gong.json", {"access_key": GONG_KEY, "access_secret": GONG_SECRET, "base_url": "https://evil.example"})
        n = len(self.api.calls)
        with self.assertRaises(S.ApiError):
            S.api_call("gong", "GET", "/v2/workspaces")
        self.assertEqual(len(self.api.calls), n)  # the key was never sent

    def test_redirects_are_not_followed(self):
        """A real local server answers 302 to another local server: the Authorization header must not reach it."""
        from http.server import BaseHTTPRequestHandler
        seen = []

        class Catch(BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append(self.headers.get("Authorization"))
                self.send_response(200)
                self.end_headers()

            def log_message(self, *a):
                pass
        catch = ThreadingHTTPServer(("127.0.0.1", 0), Catch)

        class Bounce(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(302)
                self.send_header("Location", "http://127.0.0.1:%d/steal" % catch.server_address[1])
                self.end_headers()

            def log_message(self, *a):
                pass
        bounce = ThreadingHTTPServer(("127.0.0.1", 0), Bounce)
        for srv in (catch, bounce):
            threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            status, _, _ = S._api_http("GET", "http://127.0.0.1:%d/x" % bounce.server_address[1], headers={"Authorization": "Bearer " + HS_TOKEN}, timeout=5)
        finally:
            for srv in (catch, bounce):
                srv.shutdown()
                srv.server_close()
        self.assertEqual(status, 302)
        self.assertEqual(seen, [])

    def test_secrets_never_in_responses_logs_or_live_js(self):
        self.connect()
        self.google()
        self.api.queued = [("/crm/v3/objects/contacts/search", (401, {"message": "token " + HS_TOKEN}, {}))]
        out = S.live_script()
        self.assertIn("window.OVERTURE_LIVE = {", out)
        st = json.loads(out.split("window.OVERTURE_STATUS = ")[1].split(";\n")[0])
        self.assertEqual(set(st["hubspot"]) >= {"configured", "connected", "portal"}, True)
        self.assertEqual(set(st["gong"]) >= {"configured", "connected"}, True)
        self.assertEqual((st["gong"]["configured"], st["gong"]["connected"], st["gong"]["workspace"]), (True, True, "Sales NA"))
        blob = out + json.dumps(S.status_body()) + json.dumps(S.load_records()) + json.dumps(S.research_body())
        for s in SECRETS:
            self.assertNotIn(s, blob)
        # the env route too
        for f in ("hubspot.json", "gong.json"):
            (Path(TMP) / f).unlink()
        os.environ.update(HUBSPOT_TOKEN=HS_TOKEN, GONG_ACCESS_KEY=GONG_KEY, GONG_ACCESS_SECRET=GONG_SECRET)
        self.assertEqual(S.hubspot_token(), HS_TOKEN)
        self.assertEqual(S.gong_keys(), (GONG_KEY, GONG_SECRET, "https://api.gong.io"))
        self.assertTrue(S.status_body()["hubspot"]["configured"])
        for s in SECRETS:
            self.assertNotIn(s, json.dumps(S.status_body()))

    def test_save_to_hubspot_plan_then_explicit_write(self):
        self.connect(gong=False)
        self.google()
        live, _ = S.live_now(S.load_records())
        cid = live["invites"][0]["id"]
        S.write_records("person", {"email": "bo.chen@acme.com", "title": "Staff Engineer"})
        note = "Wants <script>alert(1)</script> & SSO\nPilot in Nov"
        code, j = S.hubspot_save({"callId": cid, "note": note})
        self.assertEqual(code, 200, j)
        self.assertEqual(self.api.writes(), [])  # the plan writes nothing
        p = j["plan"]
        self.assertEqual((p["company"], p["note"], p["deal"]), ("Acme Corp", note.strip(), {"name": "Portal renewal <b>", "stage": "Contract sent"}))
        self.assertEqual([x["email"] for x in p["contacts"]], ["ann.lee@acme.com", "bo.chen@acme.com"])
        self.assertEqual(p["candidates"], [{"email": "bo.chen@acme.com", "name": "Bo Chen", "from": "", "to": "Staff Engineer", "why": "you typed it in Overture"}])
        self.assertEqual(p["titleChanges"], [])
        self.assertNotIn("8001", json.dumps(p))
        self.assertNotIn('"101"', json.dumps(p))  # no HubSpot ids reach the page
        # validation: confirm must be exactly true; only offered title changes can be sent
        self.assertEqual(S.hubspot_save({"callId": cid, "note": note, "confirm": False})[0], 400)
        self.assertEqual(S.hubspot_save({"callId": cid, "note": note, "titles": ["ann.lee@acme.com"]})[0], 400)
        empty = S.hubspot_save({"callId": cid, "note": ""})[1]["plan"]["planId"]
        code, j = S.hubspot_save({"callId": cid, "note": "", "confirm": True, "planId": empty})
        self.assertEqual(code, 400)
        self.assertIn("Nothing to save", j["error"])
        self.assertEqual(S.hubspot_save({"callId": "nope", "note": note})[0], 400)
        self.assertEqual(S.hubspot_save({"callId": cid, "note": note, "extra": 1})[0], 400)
        self.assertEqual(self.api.writes(), [])
        pid = S.hubspot_save({"callId": cid, "note": note, "titles": ["bo.chen@acme.com"]})[1]["plan"]["planId"]
        code, j = S.hubspot_save({"callId": cid, "note": note, "titles": ["bo.chen@acme.com"], "confirm": True, "planId": pid})
        self.assertEqual((code, j["note"], j["titles"], j["problems"]), (200, True, ["bo.chen@acme.com"], []))
        w = self.api.writes()
        self.assertEqual([(c["method"], urllib.parse.urlsplit(c["url"]).path) for c in w],
                         [("POST", "/crm/v3/objects/notes"), ("PATCH", "/crm/v3/objects/contacts/9002")])
        body = w[0]["body"]
        assoc = sorted((a["to"]["id"], a["types"][0]["associationTypeId"], a["types"][0]["associationCategory"]) for a in body["associations"])
        self.assertEqual(assoc, [("101", 190, "HUBSPOT_DEFINED"), ("501", 214, "HUBSPOT_DEFINED"), ("9001", 202, "HUBSPOT_DEFINED"), ("9002", 202, "HUBSPOT_DEFINED")])
        html = body["properties"]["hs_note_body"]
        self.assertIn("Wants &lt;script&gt;alert(1)&lt;/script&gt; &amp; SSO<br>Pilot in Nov", html)
        self.assertNotIn("<script>", html)
        self.assertTrue(body["properties"]["hs_timestamp"].endswith("Z"))
        self.assertEqual(w[1]["body"], {"properties": {"jobtitle": "Staff Engineer"}})
        self.assertTrue(S.load_records()["hubspotSaved"][cid]["at"])
        code, j = S.hubspot_save({"callId": cid, "note": note})
        self.assertTrue(j["plan"]["savedBefore"])

    def test_save_write_failure_is_reported(self):
        self.connect(gong=False)
        self.google()
        cid = S.live_now(S.load_records())[0]["invites"][0]["id"]
        pid = S.hubspot_save({"callId": cid, "note": "hello"})[1]["plan"]["planId"]
        self.api.queued = [("/crm/v3/objects/notes", (403, {"message": HS_TOKEN}, {}))]
        code, j = S.hubspot_save({"callId": cid, "note": "hello", "confirm": True, "planId": pid})
        self.assertEqual(code, 502)
        self.assertIn("missing a scope", j["error"])
        self.assertNotIn(HS_TOKEN, j["error"])
        self.assertNotIn(cid, S.load_records()["hubspotSaved"])

    def test_save_says_when_hubspot_is_down(self):
        self.connect(gong=False)
        self.google()
        self.api.queued = [("/account-info", S.ApiError("timeout"))]
        code, j = S.hubspot_save({"callId": "e1", "note": "hello"})
        self.assertEqual(code, 502)
        self.assertIn("didn't answer in time", j["error"])
        self.assertEqual(self.api.writes(), [])

    def test_note_text_escaping(self):
        inv = {"title": "Acme <b>call</b>", "when": "Tue Oct 20, 10:00 to 10:30 ET"}
        h = S.note_html(inv, '<img src=x onerror=alert(1)> "q" & \'s\r\nnext')
        self.assertNotIn("<img", h)
        self.assertNotIn("<b>call", h)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt; &quot;q&quot; &amp; &#x27;s<br>next", h)

    def test_gong_not_sent_to_claude_unless_setting_is_on(self):
        self.connect(hubspot=False)
        live, crm, meta, rec = self.fetch()
        cid = live["invites"][0]["id"]
        self.assertFalse(live["settings"]["gongInAI"])
        ctx = S.ask_context("What happened last time?", cid, live, rec)
        self.assertNotIn("Acme pricing", ctx)
        self.assertNotIn("Wants SSO", ctx)
        facts = {"call": {"title": "x"}, "gong": live["gong"]["Acme"]}
        self.assertNotIn("gong", S.brief_facts(facts, rec))
        S.write_records("settings", {"gongInAI": True})
        rec = S.load_records()
        self.assertIn("Wants SSO", S.ask_context("What happened last time?", cid, live, rec))
        self.assertEqual(S.brief_facts(facts, rec)["gong"]["title"], "Acme pricing")
        with self.assertRaises(S.Invalid):
            S.write_records("settings", {"gongInAI": "yes"})
        with self.assertRaises(S.Invalid):
            S.write_records("settings", {"gongInAI": True, "x": 1})

    def test_connect_tool_writes_files_and_never_prints_secrets(self):
        import contextlib
        import getpass
        import io
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import connect
        import builtins
        answers = iter([HS_TOKEN, GONG_KEY, GONG_SECRET, GRANOLA_KEY])
        old = (getpass.getpass, builtins.input)
        getpass.getpass = lambda prompt="": next(answers)
        builtins.input = lambda prompt="": "https://us-55.api.gong.io/v2/"
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                self.assertEqual(connect.main([]), 0)
        finally:
            getpass.getpass, builtins.input = old
        for s in SECRETS:
            self.assertNotIn(s, out.getvalue())
        self.assertEqual(S.hubspot_token(), HS_TOKEN)
        self.assertEqual(S.gong_keys(), (GONG_KEY, GONG_SECRET, "https://us-55.api.gong.io"))
        self.assertEqual(S.granola_key(), GRANOLA_KEY)
        self.assertNotIn(GRANOLA_KEY, out.getvalue())

    def test_connect_tool_asks_again_for_a_token_with_invisible_characters(self):
        import contextlib
        import getpass
        import io
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import connect
        answers = iter([HS_TOKEN + "​", HS_TOKEN])  # a zero-width space copied along with it, then a clean paste
        old = getpass.getpass
        getpass.getpass = lambda prompt="": next(answers)
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                connect.hubspot()
        finally:
            getpass.getpass = old
        self.assertIn("invisible characters", out.getvalue())
        self.assertNotIn(HS_TOKEN, out.getvalue())
        self.assertEqual(S.hubspot_token(), HS_TOKEN)

    # ---- review fixes ----

    def test_gong_reads_the_newest_calls_first(self):
        """Gong may list the oldest calls first: with a small page budget the latest call must still be found."""
        self.connect(hubspot=False)
        at = lambda days: (NOW - timedelta(days=days)).isoformat()
        self.api.gong_calls = [gong_call(i, "Call " + i, at(d), "ann.lee@acme.com") for i, d in
                               (("old1", 170), ("old2", 160), ("old3", 120), ("old4", 100), ("new", 3))]
        old = S.GONG_MAX_PAGES
        S.GONG_MAX_PAGES = 2
        try:
            live, *_ = self.fetch()
        finally:
            S.GONG_MAX_PAGES = old
        self.assertEqual(live["gong"]["Acme"]["title"], "Call new")
        self.assertEqual(len([c for c in self.api.calls if "fromDateTime" in json.dumps(c["body"])]), 2)  # the page budget held

    def test_gong_private_calls_are_skipped(self):
        self.connect(hubspot=False)
        self.api.gong_calls.append(gong_call("g7", "Private: Acme exec sync", "2026-10-10T15:00:00Z", "ann.lee@acme.com", isPrivate=True))
        live, *_ = self.fetch()
        self.assertEqual((live["gong"]["Acme"]["title"], live["gong"]["Acme"]["count"]), ("Acme pricing", 2))
        self.assertNotIn("Private: Acme exec sync", json.dumps(live))

    def test_gong_matches_domains_not_names_made_from_them(self):
        self.connect(hubspot=False)
        self.api.gong_calls += [gong_call("g5", "Acme AI demo", "2026-10-12T15:00:00Z", "sam@acme.ai"),         # another company, also "Acme"
                                gong_call("g6", "Acme EU sync", "2026-10-01T15:00:00Z", "li@eu.acme.com")]      # a subdomain: same company
        live, *_ = self.fetch()
        self.assertEqual((live["gong"]["Acme"]["title"], live["gong"]["Acme"]["count"]), ("Acme EU sync", 3))
        self.assertNotIn("Acme AI demo", json.dumps(live))
        # your records can still join two subdomains of one company
        S.crm_forget("gong")
        rec = S.empty_records()
        rec["companies"]["Acme Corp"] = {"domain": "acme.com"}
        self.api.gong_calls = [gong_call("g8", "US sync", "2026-10-02T15:00:00Z", "jo@us.acme.com")]
        out = S.gong_for_invites([{"domain": "eu.acme.com", "company": "Acme Corp"}], rec, NOW)
        self.assertEqual(out["Acme Corp"]["title"], "US sync")

    def test_api_http_never_lets_another_error_out(self):
        """A token pasted with a zero-width space or a newline, or an answer cut short, is an ApiError without the secret."""
        for auth in ("Bearer pat-SECRET123​", "Bearer pat-SECRET123\nX-Evil: 1"):
            with self.assertRaises(S.ApiError) as cm:
                S._api_http("GET", "http://127.0.0.1:9/x", headers={"Authorization": auth}, timeout=2)
            self.assertNotIn("SECRET123", str(cm.exception))
            self.assertTrue(cm.exception.__suppress_context__)  # a printed traceback won't show the original error (and the token)
        import socket
        for answer in (b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 100\r\n\r\n{\"a\":",  # IncompleteRead
                       b"garbage\r\n\r\n"):                                                                    # BadStatusLine
            srv = socket.socket()
            srv.bind(("127.0.0.1", 0))
            srv.listen(1)

            def serve(srv=srv, answer=answer):
                conn, _ = srv.accept()
                conn.recv(65536)
                conn.sendall(answer)
                conn.close()
            t = threading.Thread(target=serve, daemon=True)
            t.start()
            try:
                with self.assertRaises(S.ApiError):
                    S._api_http("GET", "http://127.0.0.1:%d/x" % srv.getsockname()[1], timeout=5)
            finally:
                t.join(5)
                srv.close()

    def test_a_token_with_invisible_characters_is_never_sent(self):
        S.save_json(Path(TMP) / "hubspot.json", {"token": HS_TOKEN + "​"})
        S.save_json(Path(TMP) / "gong.json", {"access_key": GONG_KEY + "\nX", "access_secret": GONG_SECRET})
        live, *_ = self.fetch()
        self.assertEqual(self.api.calls, [])
        st = S.crm_status()
        self.assertIn("invisible characters", st["hubspot"]["lastError"])
        self.assertIn("invisible characters", st["gong"]["lastError"])
        for s in SECRETS:
            self.assertNotIn(s, json.dumps(st))
        self.assertEqual(live["invites"][0]["company"], "Acme")

    def test_answers_of_an_unexpected_shape_never_break_the_page(self):
        self.connect()
        self.api.queued = [("/crm/v3/objects/contacts/search", (200, {"results": 5}, {})),
                           ("/v2/calls/extensive", (200, {"calls": [{"metaData": {"id": "x"}, "parties": 7}]}, {}))]
        live, *_ = self.fetch()
        st = S.crm_status()
        self.assertEqual((st["hubspot"]["lastError"], st["gong"]["lastError"]), ("HubSpot failed unexpectedly", "Gong failed unexpectedly"))
        self.assertEqual(live["invites"][0]["company"], "Acme")
        self.assertNotIn("gong", live)

    def test_slow_hubspot_keeps_what_came_back_and_is_not_a_failure(self):
        self.connect(gong=False)
        clock, old = Clock(), S._time
        events = acme_events(NOW + timedelta(days=1)) + [ev("e2", (NOW + timedelta(days=2)).isoformat(), 30, [SELF, att("zed@zeta.com", "Zed Ray")], summary="Zeta intro")]
        rec = S.empty_records()
        self.api.after = lambda path: setattr(clock, "jump", clock.jump + 60) if path == "/crm/v3/objects/notes/search" else None  # Acme's last request uses up the budget
        S._time = clock
        try:
            crm = S.crm_fetch(S.upcoming_invites(events, ME["email"], rec, NOW), ME["email"], rec, NOW)
        finally:
            S._time = old
        self.assertEqual(crm["companies"]["acme.com"]["name"], "Acme Corp")
        self.assertNotIn("zeta.com", crm["companies"])  # not asked yet: comes on a later load
        self.assertEqual(crm["contacts"]["ann.lee@acme.com"]["title"], "VP Platform")
        st = S.crm_status()["hubspot"]
        self.assertEqual((st["lastError"], st["connected"]), ("", True))
        self.assertEqual(S.CRM_STATE["hubspot"]["pausedUntil"], 0.0)  # not paused: Save to HubSpot still works
        live = S.build_live(events, ME, rec, NOW, crm=crm)
        self.assertTrue(live["companies"]["Acme"]["hubspot"])
        zid = next(i["id"] for i in live["invites"] if i["domain"] == "zeta.com")
        with self.assertRaises(S.Invalid) as cm:  # says HubSpot was slow, not "no company"
            S.hubspot_plan(S.clean_hubspot_save({"callId": zid, "note": "x"}), live, crm, rec)
        self.assertIn("slow", str(cm.exception))

    def test_notes_are_the_newest_from_a_search(self):
        self.connect(gong=False)
        self.fetch()
        hs = [c for c in self.api.calls if "hubapi" in c["url"]]
        found = [c["body"] for c in hs if c["url"].endswith("/crm/v3/objects/notes/search")]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["filterGroups"], [{"filters": [{"propertyName": "associations.company", "operator": "EQ", "value": "101"}]}])
        self.assertEqual(found[0]["sorts"], [{"propertyName": "hs_timestamp", "direction": "DESCENDING"}])
        self.assertFalse(any("/associations/notes" in c["url"] for c in hs))

    def test_a_403_on_notes_drops_only_the_notes(self):
        self.connect(gong=False)
        self.api.queued = [("/crm/v3/objects/notes/search", (403, {}, {}))]
        live, *_ = self.fetch()
        c = live["companies"]["Acme"]
        self.assertEqual((c["status"], c["employees"], c["history"]), ("Open deal: Contract sent", 1200, []))
        self.assertEqual(S.crm_status()["hubspot"]["lastError"], "")

    def test_customer_with_an_open_deal_is_still_a_customer(self):
        cos = {}
        S.apply_hubspot_company(cos, "Acme", "acme.com", {"lifecycle": "customer", "deals": [{"name": "Renewal", "stage": "Contract sent", "closed": False}]})
        self.assertEqual((cos["Acme"]["status"], cos["Acme"]["customer"]), ("Open deal: Contract sent", True))
        S.apply_hubspot_company(cos, "Beta", "beta.com", {"lifecycle": "opportunity", "deals": [{"name": "New", "stage": "Contract sent", "closed": False}]})
        self.assertFalse(cos["Beta"]["customer"])

    def test_long_crm_text_is_cut_short_not_dropped(self):
        self.assertEqual(S.clip("a" * 130, 120), "a" * 119 + "…")
        self.assertEqual(S.clip(" Head  of\nPlatform ", 120), "Head of Platform")
        self.connect(gong=False)
        long_title = "VP " + "Platform Engineering and Developer Experience, " * 3
        self.api.queued = [("/crm/v3/objects/contacts/search", (200, {"results": [
            {"id": "9001", "properties": {"email": "ann.lee@acme.com", "firstname": "Ann", "lastname": "Lee", "jobtitle": long_title}}]}, {}))]
        live, crm, meta, _ = self.fetch()
        t = live["people"]["ann.lee@acme.com"]["title"]
        self.assertTrue(t.startswith("VP Platform Engineering") and t.endswith("…") and len(t) <= 120, t)
        self.assertTrue(meta["ann.lee@acme.com"]["crm"])  # HubSpot knows her title, so no web lookup

    def test_preview_is_the_whole_note_and_confirm_needs_the_same_plan(self):
        self.connect(gong=False)
        self.google()
        inv = S.live_now(S.load_records())[0]["invites"][0]
        p = S.hubspot_save({"callId": inv["id"], "note": "hello"})[1]["plan"]
        self.assertEqual(p["preview"], inv["title"] + " · " + inv["when"] + "\n\nhello\n\nSaved from Overture")
        self.assertRegex(p["planId"], r"^[0-9a-f]{16}$")
        code, j = S.hubspot_save({"callId": inv["id"], "note": "hello", "confirm": True})
        self.assertEqual(code, 400)
        self.assertIn("planId", j["error"])
        # between the preview and the click, HubSpot's open deal changes: nothing is written
        S.crm_forget("hubspot")
        self.api.queued = [("/crm/v3/objects/deals/batch/read", (200, {"results": [
            {"id": "503", "properties": {"dealname": "Upsell", "dealstage": "s1", "closedate": "2026-12-01T00:00:00Z"}}]}, {}))]
        code, j = S.hubspot_save({"callId": inv["id"], "note": "hello", "confirm": True, "planId": p["planId"]})
        self.assertEqual(code, 409)
        self.assertIn("changed since the preview", j["error"])
        self.assertEqual(self.api.writes(), [])
        p2 = S.hubspot_save({"callId": inv["id"], "note": "hello"})[1]["plan"]
        self.assertEqual(p2["deal"]["name"], "Upsell")
        code, j = S.hubspot_save({"callId": inv["id"], "note": "hello", "confirm": True, "planId": p2["planId"]})
        self.assertEqual(code, 200, j)
        self.assertEqual("503", self.api.writes()[0]["body"]["associations"][-1]["to"]["id"])

    def test_note_timeout_is_remembered_so_the_next_preview_warns(self):
        self.connect(gong=False)
        self.google()
        cid = S.live_now(S.load_records())[0]["invites"][0]["id"]
        p = S.hubspot_save({"callId": cid, "note": "hello"})[1]["plan"]
        self.api.queued = [("/crm/v3/objects/notes", S.ApiError("timeout"))]
        code, j = S.hubspot_save({"callId": cid, "note": "hello", "confirm": True, "planId": p["planId"]})
        self.assertEqual(code, 502)
        self.assertIn("may have been saved", j["error"])
        self.assertNotIn("Not saved", j["error"])
        self.assertEqual(S.load_records()["hubspotSaved"][cid]["note"], "unknown")
        p2 = S.hubspot_save({"callId": cid, "note": "hello"})[1]["plan"]
        self.assertTrue(p2["savedBefore"] and p2["savedUnsure"])
        self.assertEqual(S.hubspot_save({"callId": cid, "note": "hello", "confirm": True, "planId": p["planId"]})[0], 409)  # the old preview can't save
        self.assertEqual(len(self.api.writes()), 1)  # only the try that timed out


class CrmEndToEnd(ServerBase, CrmFakes):
    """The HubSpot and Gong routes through the real handler (fake HubSpot, fake Google)."""

    def setUp(self):
        super().setUp()
        self.crm_setup()

    def tearDown(self):
        self.crm_teardown()

    def test_save_route_guards_and_no_write_without_confirm(self):
        origin = "http://localhost:%d" % S.PORT
        body = {"callId": "e1", "note": "hi"}
        self.assertEqual(self.req("POST", "/api/hubspot/save", body)[0], 403)
        self.assertEqual(self.req("POST", "/api/hubspot/save", body, {"X-OVERTURE": "1"})[0], 403)
        self.assertEqual(self.req("POST", "/api/hubspot/save", body, {"X-OVERTURE": "1", "Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.req("POST", "/api/hubspot/save", body, {"X-OVERTURE": "1", "Origin": origin, "Content-Type": "text/plain"})[0], 403)
        self.assertEqual(self.req("POST", "/api/hubspot/save", body, {"X-OVERTURE": "1", "Origin": origin, "Host": "evil.example"})[0], 403)
        st, txt, _ = self.req("POST", "/api/hubspot/save", body, {"X-OVERTURE": "1", "Origin": origin})
        self.assertEqual(st, 409)  # not connected yet
        self.connect(gong=False)
        self.google()
        cid = S.live_now(S.load_records())[0]["invites"][0]["id"]
        st, txt, _ = self.req("POST", "/api/hubspot/save", {"callId": cid, "note": "hi"}, {"X-OVERTURE": "1", "Origin": origin})
        self.assertEqual(st, 200, txt)
        self.assertIn("plan", json.loads(txt))
        self.assertEqual(self.api.writes(), [])
        pid = json.loads(txt)["plan"]["planId"]
        st, txt, _ = self.req("POST", "/api/hubspot/save", {"callId": cid, "note": "hi", "confirm": True, "planId": pid}, {"X-OVERTURE": "1", "Origin": origin})
        self.assertEqual(st, 200, txt)
        self.assertEqual(len(self.api.writes()), 1)
        for s in SECRETS:
            self.assertNotIn(s, txt)

    def test_status_live_js_and_log_lines_hold_no_secrets(self):
        import contextlib
        import io
        self.connect()
        self.google()
        log = io.StringIO()
        S.Handler.log_message = vars(type(self))["old_log"]  # the real one (hides query strings)
        try:
            with contextlib.redirect_stderr(log):
                pages = [self.req("GET", p)[1] for p in ("/api/status", "/data/live.js", "/api/records", "/api/research")]
        finally:
            S.Handler.log_message = lambda *a, **k: None
        self.assertIn("/data/live.js", log.getvalue())
        st = json.loads(pages[0])
        self.assertTrue(st["hubspot"]["configured"] and st["gong"]["configured"])
        self.assertIn("Contract sent", pages[1])
        for s in SECRETS:
            for text in pages + [log.getvalue()]:
                self.assertNotIn(s, text)
        origin = "http://localhost:%d" % S.PORT
        self.assertEqual(self.req("PUT", "/api/records/settings", {"gongInAI": True})[0], 403)
        st, txt, _ = self.req("PUT", "/api/records/settings", {"gongInAI": True}, {"X-OVERTURE": "1", "Origin": origin})
        self.assertEqual((st, json.loads(txt)["saved"]), (200, {"gongInAI": True}))
        self.assertEqual(self.req("PUT", "/api/records/settings", {"gongInAI": 1}, {"X-OVERTURE": "1", "Origin": origin})[0], 400)

    def test_brief_drops_gong_unless_setting_is_on(self):
        os.environ["ANTHROPIC_API_KEY"] = "test-key"
        sent = []
        S.claude_text = lambda system, content, max_tokens, timeout: (sent.append(content), (200, {"text": "ok"}))[1]
        facts = {"call": {"title": "Acme"}, "gong": {"brief": "GONG-ONLY-TEXT"}}
        st, _, _ = self.req("POST", "/api/brief", facts)
        self.assertEqual(st, 200)
        self.assertNotIn("GONG-ONLY-TEXT", sent[-1])
        S.write_records("settings", {"gongInAI": True})
        self.req("POST", "/api/brief", facts)
        self.assertIn("GONG-ONLY-TEXT", sent[-1])


# ---------------------------------------------------------------- people mentioned on the call ----------------------------------------------------------------

VTT_T = """WEBVTT

1
00:00:01.000 --> 00:00:04.000
<v Priya Raman>Thanks for joining. Maria Gomez from our security team will want the pack.</v>

2
00:00:05.000 --> 00:00:09.000
<v Chris Park>Great. Is our CTO joining next time? Backstage Portal and Spotify Confidence are both on the list.</v>

3
00:01:10.500 --> 00:01:14.000
Marcus Bell: Tom from security asked about SSO. Also our new CTO wants to see the
4
00:01:14.000 --> 00:01:16.000
Marcus Bell: plugin catalog before Q1.

5
00:02:00.000 --> 00:02:05.000
Marcus Bell: Grace in finance signs it. Priya Raman and Chris will set it up. The budget line is PLAN-ONLY-IN-TRANSCRIPT.
"""
SRT_T = "1\n00:00:01,000 --> 00:00:04,000\nPriya Raman: Jordan Lee, our VP of Platform, has the budget.\n\n2\n00:00:05,000 --> 00:00:07,000\nDana who runs procurement needs the MSA.\n"
TXT_ZOOM = "[Priya Raman] 10:02:33\nJordan Lee runs our platform team.\n[Marcus Bell] 10:03:01\nOkay.\n"
TXT_MEET = "Northwind call - Transcript\n00:00:00\n \nPriya Raman: Hi Chris.\n00:01:02\nMarcus Bell: Dana in legal will read it.\n"
TXT_CHAT = "10:02:33 From Marcus Bell to Everyone: loop in Sam Rivera please\n"


def mention_reply(cands, urls=(), stop="end_turn", **kw):
    return reply({"candidates": cands}, urls, stop, **kw)


def cand(name, title="Security Engineering Manager", url="https://northwind-freight.com/team/x", conf="high", why="Leads security at Northwind"):
    return {"name": name, "title": title, "team": "Security", "relationship": "employee", "confidence": conf, "why": why,
            "sources": [{"url": url, "label": "Team page", "supports": ["title", "team", "relationship"]}]}


def northwind_events(now):
    """One upcoming Northwind call (Priya, Marcus), one past one with Grace Ito, one past Acme call."""
    up = ev("nw1", (now + timedelta(days=1)).isoformat(), 45, [SELF, att("priya.raman@northwind-freight.com", "Priya Raman"),
                                                               att("marcus.bell@northwind-freight.com", "Marcus Bell")], summary="Northwind: pilot")
    past = ev("nw0", (now - timedelta(days=40)).isoformat(), 30, [SELF, att("grace.ito@northwind-freight.com", "Grace Ito")], summary="Northwind: pricing")
    return [past, up]


class MentionParsing(unittest.TestCase):
    def test_vtt_speakers_times_cue_numbers_and_joined_sentences(self):
        lines = S.parse_transcript(VTT_T)
        self.assertEqual(lines[0], {"speaker": "Priya Raman", "time": "0:01", "text": "Thanks for joining. Maria Gomez from our security team will want the pack."})
        self.assertEqual(lines[1]["speaker"], "Chris Park")
        self.assertEqual((lines[2]["speaker"], lines[2]["time"]), ("Marcus Bell", "1:10"))
        self.assertTrue(lines[2]["text"].endswith("wants to see the plugin catalog before Q1."))  # two cues, one sentence
        self.assertFalse(any(l["text"] in ("1", "2", "3", "4", "5", "WEBVTT") for l in lines))

    def test_srt_and_txt_formats(self):
        srt = S.parse_transcript(SRT_T)
        self.assertEqual(srt[0], {"speaker": "Priya Raman", "time": "0:01", "text": "Jordan Lee, our VP of Platform, has the budget."})
        self.assertEqual(srt[1]["text"], "Dana who runs procurement needs the MSA.")
        zoom = S.parse_transcript(TXT_ZOOM)
        self.assertEqual(zoom[0], {"speaker": "Priya Raman", "time": "10:02:33", "text": "Jordan Lee runs our platform team."})
        meet = S.parse_transcript(TXT_MEET)
        self.assertIn({"speaker": "Marcus Bell", "time": "1:02", "text": "Dana in legal will read it."}, meet)
        chat = S.parse_transcript(TXT_CHAT)
        self.assertEqual((chat[0]["speaker"], chat[0]["time"], chat[0]["text"]), ("Marcus Bell", "10:02:33", "loop in Sam Rivera please"))
        plain = S.parse_transcript("Note: Maria Gomez will call.\nJust a line.")
        self.assertEqual(plain[0]["speaker"], "")  # "Note:" isn't a speaker
        self.assertEqual(S.parse_transcript("WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n<v.loud Ann Lee>Hi <b>there</b></v>\n")[0],
                         {"speaker": "Ann Lee", "time": "0:01", "text": "Hi there"})

    def test_non_text_is_refused(self):
        self.assertFalse(S.transcript_text_ok("PK\x03\x04\x00\x00binary"))
        self.assertFalse(S.transcript_text_ok("�" * 50 + "abc"))
        self.assertTrue(S.transcript_text_ok(VTT_T))
        for body in ({"callId": "nw1", "text": "x\x00y"}, {"callId": "nw1", "text": "hello", "filename": "call.pdf"},
                     {"callId": "nw1", "text": "a" * (S.MAX_TRANSCRIPT_CHARS + 1)}, {"callId": "nw1"},
                     {"callId": "nw1", "lines": [{"speaker": "a", "text": "b", "extra": 1}]}, {"callId": "nw1", "text": "hi", "source": "email"},
                     {"callId": "nw1", "text": "hi", "hints": [{"name": "x" * 101}]}, {"callId": "../x", "text": "hi"}):
            with self.assertRaises(S.Invalid, msg=str(body)[:80]):
                S.clean_mentions_post(body)


class MentionExtraction(unittest.TestCase):
    def ctx(self, known=None):
        rec = S.empty_records()
        for k in known or []:
            rec["knownPeople"]["northwind-freight.com|" + S.norm_name(k[0])] = {"name": k[0], "title": k[1], "domain": "northwind-freight.com"}
        rec["people"]["priya.raman@northwind-freight.com"] = {"title": "VP, Platform Engineering"}
        c = S.mention_context(northwind_events(NOW), ME, rec, "nw1", NOW)
        self.assertIsNotNone(c)
        return c

    def found(self, text, known=None, hints=None):
        return {(m["kind"], m["name"], m["role"]): m for m in S.extract_mentions(S.parse_transcript(text), self.ctx(known), hints)}

    def test_known_names_new_full_names_partials_and_roles(self):
        f = self.found(VTT_T)
        self.assertIn(("full", "Maria Gomez", "security"), f)
        self.assertIn(("partial", "Tom", "security"), f)
        self.assertIn(("role", "", "CTO"), f)  # "our new CTO" from Marcus: their CTO
        grace = f[("partial", "Grace", "finance")]  # Grace Ito is in your calendar (met 40 days ago)
        self.assertEqual([c["name"] for c in grace["candidates"]], ["Grace Ito"])
        q = f[("full", "Maria Gomez", "security")]["quote"]
        self.assertEqual(q, {"text": "Maria Gomez from our security team will want the pack.", "speaker": "Priya Raman", "time": "0:01"})
        full = self.found("Priya Raman: Grace Ito approved it.")
        self.assertEqual(full[("known", "Grace Ito", "")]["known"]["from"], "Your calendar")
        f2 = self.found(SRT_T + "\n")
        self.assertIn(("full", "Jordan Lee", "VP of Platform"), f2)
        self.assertIn(("partial", "Dana", "procurement"), f2)

    def test_skips_guests_chris_products_and_your_own_side(self):
        names = {k[1] for k in self.found(VTT_T)}
        for n in ("Priya Raman", "Priya", "Chris", "Chris Park", "Marcus Bell", "Backstage Portal", "Spotify Confidence", "Backstage", "Portal", "Spotify"):
            self.assertNotIn(n, names)
        roles = [k for k in self.found(VTT_T) if k[0] == "role"]
        self.assertEqual(len(roles), 1)  # Chris's "our CTO" is Spotify's: not looked up
        self.assertEqual(self.found("Chris Park: Maria from our security team will help."), {})  # Chris's colleague
        self.assertEqual(self.found("Priya Raman: Maria from Spotify said so."), {})
        self.assertEqual(self.found("Marcus Bell: our VP of Platform will decide."), {})  # Priya, who is on the call
        self.assertEqual(self.found("Marcus Bell: Northwind Freight and Developer Portal and Platform Engineering and New York."), {})
        self.assertEqual(self.found("Marcus Bell: Hello from the platform team. Updates from security soon."), {})

    def test_full_and_partial_are_one_person_and_hints_are_checked(self):
        f = self.found("Marcus Bell: Maria Gomez owns it. Later Maria from security called.")
        self.assertEqual(list(f), [("full", "Maria Gomez", "security")])
        self.assertEqual(f[("full", "Maria Gomez", "security")]["count"], 2)
        h = self.found("Marcus Bell: ask maria about it.", hints=[{"name": "Invented Person", "role": ""}, {"name": "Maria", "role": "security"}])
        self.assertEqual(h, {})  # neither hint is really in the transcript as a name ("maria" is lower case)
        h = self.found("Marcus Bell: Kenji handles that for us.", hints=[{"name": "Kenji", "role": "data team"}, {"name": "Spotify", "role": ""}])
        self.assertEqual(list(h), [("partial", "Kenji", "")])  # the role wasn't said with him, so it is dropped
        h = self.found("Marcus Bell: Kenji handles the security reviews.", hints=[{"name": "Kenji", "role": "security"}])
        self.assertEqual(list(h), [("partial", "Kenji", "security")])  # a team the sentence names is kept
        said = "he is getting divorced and moving to Ohio next month"
        h = self.found("Marcus Bell: Kenji handles that, " + said + ".", hints=[{"name": "Kenji", "role": said}, {"name": "Kenji", "role": "handles"}])
        self.assertEqual(list(h), [("partial", "Kenji", "")])  # in the sentence, but not a role or team: dropped

    def test_codenames_holidays_and_company_words_are_not_people(self):
        for s in ("Project Falcon is the acquisition we can't talk about.", "Operation Bluebird starts soon.", "Atlas Migration is behind.",
                  "Grafana Labs is fine.", "Visual Studio Code is fine.", "Christmas Eve is off.", "Super Bowl ads.", "Machine Learning is hot."):
            self.assertEqual(self.found("Marcus Bell: " + s), {}, s)
        self.assertIn(("full", "Eve Chen", ""), self.found("Marcus Bell: Eve Chen owns it."))  # real first names still count

    def test_your_notes_are_yours(self):
        note = "We need our CTO on the next call. Tom from our security team can help."
        ctx = self.ctx()
        for sp in ("Your note", "Your notes"):  # the speakers app.js gives your call notes
            self.assertEqual(S.extract_mentions([{"speaker": sp, "time": "", "text": note}], ctx), [], sp)
        self.assertEqual(len(S.extract_mentions([{"speaker": "Marcus Bell", "time": "", "text": note}], ctx)), 2)  # theirs: looked up

    def test_verbs_that_start_a_sentence_are_not_names(self):
        f = self.found("Marcus Bell: Ping Maria Gomez about the MSA. Invite Dana Li next time. Loop Tom into the thread. "
                       "Ask Sam from our legal team. Need our CTO on the next call.")
        self.assertEqual(set(f), {("full", "Maria Gomez", ""), ("full", "Dana Li", ""), ("partial", "Sam", "legal"), ("role", "", "CTO")})
        self.assertIn(("full", "Chase Miller", ""), self.found("Marcus Bell: Chase Miller owns it."))  # Chase is a name, not a verb here

    def test_days_months_and_other_companies_are_not_roles(self):
        f = self.found("Marcus Bell: I'll ping Tom on Monday. Ask Tom in March. Sarah at Goldman Sachs called.")
        self.assertEqual(set(f), {("partial", "Sarah", "at Goldman Sachs")})  # not "at Monday", and Goldman Sachs isn't a person
        f = self.found("Marcus Bell: Tom from Jordan Lee's team signs.")
        self.assertTrue(any(k[0] == "full" and k[1].startswith("Jordan Lee") for k in f), f)  # a person's team: the person stays


class MentionFlow(Fresh):
    """POST /api/mentions -> local extraction -> the research worker (fake Claude) -> pick, confirm, add. No network."""

    def setUp(self):
        super().setUp()
        with S.RQ_LOCK:
            S.RQ.update(queue=[], pending=set(), running=set(), errors={}, meta={}, mentions={})
        self.old = (S.research_client, S.RESEARCH_AUTOSTART, S.HTTP, S.claude_text)
        S.RESEARCH_AUTOSTART = False
        os.environ["ANTHROPIC_API_KEY"] = "test-key"
        S.save_json(S.token_path(), {"access_token": "AT-x", "refresh_token": "RT-x", "expires_at": time.time() + 3000, "email": "chris@spotify.com", "name": "Chris Park"})
        self.events = northwind_events(datetime.now(timezone.utc))
        S.HTTP = lambda method, url, form=None, headers=None, timeout=15: (200, {"items": self.events}) if url.startswith(S.EVENTS_URL) else (404, {})

    def tearDown(self):
        S.research_client, S.RESEARCH_AUTOSTART, S.HTTP, S.claude_text = self.old
        os.environ.pop("ANTHROPIC_API_KEY", None)

    def fake(self, *replies):
        f = FakeClaude(*replies)
        S.research_client = lambda: f
        return f

    def post(self, text=VTT_T, **kw):
        st, body = S.mentions_post(dict({"callId": "nw1", "text": text, "filename": "call.vtt"}, **kw))
        self.assertEqual(st, 200, body)
        return body

    def by(self, body):
        return {(i["name"] or i["role"]): i for i in body["items"]}

    def test_nothing_goes_to_claude_until_the_worker_and_then_only_name_role_company_domain(self):
        f = self.fake(mention_reply([cand("Maria Gomez")], ["https://northwind-freight.com/team/x"]),
                      mention_reply([]), mention_reply([]))
        body = self.post()
        self.assertEqual(f.calls, [])  # extraction is local
        items = self.by(body)
        self.assertEqual(items["Maria Gomez"]["status"], "pending")
        self.assertEqual(items["Grace"]["status"], "pick")  # known to Overture: no web lookup
        self.assertEqual(body["found"], 4)
        while S.research_step():
            pass
        self.assertEqual(len(f.calls), 3)  # Maria Gomez, Tom (security), the CTO
        for call in f.calls:
            sent = json.dumps(call, default=str)
            user = call["messages"][0]["content"]
            for bit in ("will want the pack", "asked about SSO", "PLAN-ONLY-IN-TRANSCRIPT", "Priya", "Marcus", "@", "0:01", "Thanks for joining"):
                self.assertNotIn(bit, sent)
            self.assertIn("Northwind Freight", user)
            self.assertIn("northwind-freight.com", user)
            self.assertEqual(set(re.findall(r"^([A-Za-z ]+):", user, re.M)), {"Mentioned on the call", "Role or team", "Company", "Company website"})
            self.assertEqual(call["tools"][0]["blocked_domains"], S.BLOCKED_DOMAINS)
        self.assertIn("Mentioned on the call: Maria Gomez\nRole or team: security", f.calls[0]["messages"][0]["content"])
        self.assertIn("Mentioned on the call: (no name given)\nRole or team: CTO", f.calls[2]["messages"][0]["content"])
        after = self.by(S.mentions_body("nw1"))
        self.assertEqual((after["Maria Gomez"]["status"], after["Maria Gomez"]["person"]["title"]), ("found", "Security Engineering Manager"))
        self.assertEqual(after["Tom"]["status"], "notfound")

    def test_only_mentions_and_quotes_are_saved_never_the_transcript(self):
        self.fake()
        self.post()
        self.post(TXT_MEET, filename="meet.txt")
        saved = (Path(TMP) / "records.json").read_text(encoding="utf-8")
        for bit in ("PLAN-ONLY-IN-TRANSCRIPT", "Backstage Portal and Spotify Confidence", "Thanks for joining", "Hi Chris"):
            self.assertNotIn(bit, saved)
        block = S.load_records()["mentions"]["nw1"]
        self.assertTrue(all(set(it["quote"]) == {"text", "speaker", "time"} for it in block["items"]))
        self.assertTrue(all(len(it["quote"]["text"]) <= S.QUOTE_CHARS + 2 for it in block["items"]))
        self.assertNotIn("text", block)
        self.assertNotIn("lines", block)
        self.assertIn("Dana", {it["name"] for it in block["items"]})  # the second transcript added to the same call

    def test_ambiguous_mentions_are_never_auto_picked(self):
        two = [cand("Tom Hughes"), cand("Tom Baker", "Security Analyst", "https://northwind-freight.com/team/y")]
        urls = ["https://northwind-freight.com/team/x", "https://northwind-freight.com/team/y"]
        self.fake(mention_reply([]), mention_reply(two, urls), mention_reply([]))
        self.post()
        while S.research_step():
            pass
        tom = self.by(S.mentions_body("nw1"))["Tom"]
        self.assertEqual(tom["status"], "pick")
        self.assertIsNone(tom["person"])
        self.assertEqual([c["name"] for c in tom["candidates"]], ["Tom Hughes", "Tom Baker"])
        self.assertTrue(all(c["sources"] and c["why"] for c in tom["candidates"]))
        self.assertTrue(tom["likely"])  # several: most likely first, "Likely, not confirmed", nothing on the map yet
        self.assertFalse(tom["connected"])
        # one sourced candidate that fits the first name and the team said with it: found automatically (you can change it)
        job = {"callId": "nw1", "id": tom["id"], "name": "Tom", "role": "security", "kind": "partial", "company": "Northwind Freight", "domain": "northwind-freight.com"}
        S.LOOKUP_CACHE.clear()
        S.update_mention("nw1", tom["id"], lambda x, r: x.update(status="pending", candidates=[]))
        self.fake(mention_reply([cand("Tom Hughes")], urls))
        S.do_mention_lookup(job)
        t = self.by(S.mentions_body("nw1", requeue=False))["Tom"]
        self.assertEqual((t["status"], t["autoFound"], t["connected"]), ("found", True, True))
        # a first name with no team said: one candidate is only "likely", never picked for you
        S.LOOKUP_CACHE.clear()
        S.update_mention("nw1", tom["id"], lambda x, r: x.update(status="pending", candidates=[], person=None, autoFound=False))
        self.fake(mention_reply([cand("Tom Hughes")], urls))
        S.do_mention_lookup(dict(job, role=""))
        t = self.by(S.mentions_body("nw1", requeue=False))["Tom"]
        self.assertEqual((t["status"], t["likely"], t["person"], t["connected"]), ("pick", True, None, False))
        # a full name with two different people behind it: pick, too
        S.LOOKUP_CACHE.clear()
        S.update_mention("nw1", tom["id"], lambda x, r: x.update(status="pending", candidates=[]))
        self.fake(mention_reply([cand("Tom Hughes"), cand("Tom Hughes", "CTO", "https://northwind-freight.com/team/y")], urls))
        S.do_mention_lookup(dict(job, name="Tom Hughes", kind="full"))  # same name twice: kept once, so one candidate -> found
        self.assertEqual(self.by(S.mentions_body("nw1", requeue=False))["Tom"]["status"], "found")

    def test_blocked_unsourced_and_wrong_name_candidates_are_dropped(self):
        bad = [cand("Maria Gomez", url="https://www.zoominfo.com/p/Maria-Gomez/1"), cand("Maria Lopez"), cand("Maria Gomez", conf="low"),
               dict(cand("Maria Gomez"), sources=[]), cand("Maria Gomez", url="https://never-searched.example.com/x")]
        self.fake(mention_reply(bad, ["https://www.zoominfo.com/p/Maria-Gomez/1", "https://northwind-freight.com/team/x"]), mention_reply([]), mention_reply([]))
        self.post()
        while S.research_step():
            pass
        m = self.by(S.mentions_body("nw1"))["Maria Gomez"]
        self.assertEqual((m["status"], m["person"]), ("notfound", None))
        self.assertIn("found no one", m["note"])
        self.assertTrue(S.blocked_url("https://www.zoominfo.com/p/x"))

    def test_pick_confirm_none_again_add(self):
        self.fake(mention_reply([]), mention_reply([cand("Tom Hughes"), cand("Tom Baker")], ["https://northwind-freight.com/team/x"]), mention_reply([]))
        self.post()
        while S.research_step():
            pass
        tom = self.by(S.mentions_body("nw1"))["Tom"]
        st, out = S.mention_action({"callId": "nw1", "id": tom["id"], "action": "pick", "index": 1})
        self.assertEqual(st, 200, out)
        t = self.by(out)["Tom"]
        self.assertEqual((t["status"], t["person"]["name"], t["confirmed"]), ("found", "Tom Baker", True))
        self.assertEqual(S.mention_action({"callId": "nw1", "id": tom["id"], "action": "pick", "index": 0})[0], 400)  # already picked
        st, out = S.mention_action({"callId": "nw1", "id": tom["id"], "action": "add"})
        self.assertEqual(st, 200)
        kp = S.load_records()["knownPeople"]
        self.assertEqual(kp["northwind-freight.com|tom baker"]["title"], "Security Engineering Manager")
        # the next transcript knows him at once: no lookup
        f = self.fake()
        body = self.post("Marcus Bell: Tom Baker signed off.", filename="b.txt")
        self.assertEqual(self.by(body)["Tom Baker"]["status"], "known")
        self.assertEqual(S.research_step(), None)
        self.assertEqual(f.calls, [])
        grace = self.by(S.mentions_body("nw1"))["Grace"]
        st, out = S.mention_action({"callId": "nw1", "id": grace["id"], "action": "none"})
        self.assertEqual(self.by(out)["Grace"]["status"], "notfound")
        st, out = S.mention_action({"callId": "nw1", "id": grace["id"], "action": "again"})
        self.assertEqual((st, self.by(out)["Grace"]["status"]), (200, "pending"))
        os.environ.pop("ANTHROPIC_API_KEY")
        self.assertEqual(S.mention_action({"callId": "nw1", "id": grace["id"], "action": "again"}), (503, {"error": "no-key"}))
        for bad in ({"callId": "nw1", "id": grace["id"], "action": "delete"}, {"callId": "nw1", "id": "zz", "action": "confirm"},
                    {"callId": "nw1", "id": grace["id"], "action": "pick", "index": True}, {"callId": "nw1", "id": grace["id"], "action": "confirm", "x": 1}):
            self.assertEqual(S.mention_action(bad)[0], 400, bad)

    def test_free_text_hint_roles_never_reach_claude(self):
        f = self.fake(mention_reply([]), mention_reply([]))
        said = "he is getting divorced and moving to Ohio next month"
        body = self.post("Marcus Bell: Kenji handles that, " + said + ".", filename="k.txt",
                         hints=[{"name": "Kenji", "role": said}, {"name": "Kenji", "role": "handles"}])
        self.assertEqual([(i["name"], i["role"]) for i in body["items"]], [("Kenji", "")])
        while S.research_step():
            pass
        self.assertEqual(len(f.calls), 1)
        sent = json.dumps(f.calls, default=str)
        for bit in ("divorced", "Ohio", "handles"):
            self.assertNotIn(bit, sent)
        self.assertIn("Mentioned on the call: Kenji\nRole or team: (not said)", f.calls[0]["messages"][0]["content"])

    def test_without_a_key_nothing_is_queued(self):
        os.environ.pop("ANTHROPIC_API_KEY")
        body = self.post()
        self.assertEqual(self.by(body)["Maria Gomez"]["status"], "nokey")
        with S.RQ_LOCK:
            self.assertEqual(S.RQ["queue"], [])

    def test_errors_show_and_research_lists_mention_statuses(self):
        self.fake(RateLimitError("busy"), mention_reply([]), mention_reply([]))
        self.post()
        S.research_step()
        m = self.by(S.mentions_body("nw1", requeue=False))["Maria Gomez"]
        self.assertEqual(m["status"], "error")
        self.assertIn("Couldn't look them up", m["note"])
        rb = S.research_body()["mentions"]["nw1"]
        self.assertEqual(rb[m["id"]], "error")

    def test_transcripts_reach_claude_answers_only_with_the_setting(self):
        self.fake()
        self.post()
        S.update_mention("nw1", self.by(S.mentions_body("nw1", requeue=False))["Maria Gomez"]["id"],
                         lambda x, r: x.update(status="found", person={"name": "Maria Gomez", "title": "CISO"}))
        sent = []
        S.claude_text = lambda system, content, max_tokens, timeout: (sent.append(content), (200, {"text": "ok"}))[1]
        S.answer_question({"question": "Who came up?", "callId": "nw1"})
        self.assertNotIn("will want the pack", sent[-1])
        self.assertNotIn("Maria Gomez", sent[-1])
        S.write_records("settings", {"transcriptsInAI": True})
        S.answer_question({"question": "Who came up?", "callId": "nw1"})
        self.assertIn("will want the pack", sent[-1])
        self.assertIn("Maria Gomez", sent[-1])

    def test_settings_are_off_by_default_and_validated(self):
        live = S.build_live(self.events, ME, S.load_records(), datetime.now(timezone.utc))
        self.assertEqual(live["settings"], {"gongInAI": False, "gongTranscripts": False, "transcriptsInAI": False})
        with self.assertRaises(S.Invalid):
            S.write_records("settings", {"gongTranscripts": "yes"})
        with self.assertRaises(S.Invalid):
            S.write_records("settings", {})
        with self.assertRaises(S.Invalid):
            S.write_records("settings", {"readEverything": True})
        self.assertEqual(S.write_records("settings", {"gongTranscripts": True}), {"gongTranscripts": True})
        self.fake()
        self.post()
        self.assertEqual(S.build_live(self.events, ME, S.load_records(), datetime.now(timezone.utc))["mentions"], {"nw1": 4})


class MentionCrm(Fresh, CrmFakes):
    """Gong transcripts (only with the setting on) and Save to HubSpot as a contact (only on confirm). Fake HTTP only."""

    def setUp(self):
        super().setUp()
        self.crm_setup()
        with S.RQ_LOCK:
            S.RQ["mentions"] = {}
        S.save_json(S.token_path(), {"access_token": "AT-x", "refresh_token": "RT-x", "expires_at": time.time() + 3000, "email": "chris@spotify.com", "name": "Chris Park"})
        now = datetime.now(timezone.utc).replace(microsecond=0)
        self.start = now - timedelta(days=1)
        self.events = [ev("ac1", self.start.isoformat(), 30, [SELF, att("ann.lee@acme.com", "Ann Lee"), att("bo.chen@acme.com", "Bo Chen")], summary="Acme: pricing")]
        S.HTTP = lambda method, url, form=None, headers=None, timeout=15: (200, {"items": self.events}) if url.startswith(S.EVENTS_URL) else (404, {})
        self.api.gong_calls.append(gong_call("g7", "Acme pricing call", (self.start + timedelta(minutes=2)).isoformat().replace("+00:00", "Z"),
                                             "ann.lee@acme.com", "chris@spotify.com", duration=1800))
        self.api.transcripts["g7"] = [
            {"speakerId": "s1", "topic": "Pricing", "sentences": [{"start": 61000, "end": 64000, "text": "Cy Diaz will want to see the security pack."},
                                                                 {"start": 64000, "end": 66000, "text": "And Rosa Quint from our legal team signs. GONG-ONLY-SENTENCE."}]},
            {"speakerId": "s2", "topic": "", "sentences": [{"start": 70000, "end": 72000, "text": "Great."}]}]
        self.api.parties["g7"] = [{"speakerId": "s1", "name": "Ann Lee"}, {"speakerId": "s2", "name": "Chris Park"}]

    def tearDown(self):
        self.crm_teardown()

    def gong_paths(self):
        return [c["url"] for c in self.api.calls if "gong.io" in c["url"]]

    def test_gong_transcript_only_with_the_setting_on(self):
        self.connect(hubspot=False)
        st, body = S.mentions_post({"callId": "ac1", "source": "gong"})
        self.assertEqual(st, 403)
        self.assertIn("Read Gong transcripts", body["error"])
        self.assertEqual(self.gong_paths(), [])  # not even the call list
        S.write_records("settings", {"gongTranscripts": True})
        st, body = S.mentions_post({"callId": "ac1", "source": "gong"})
        self.assertEqual(st, 200, body)
        self.assertTrue(any(u.endswith("/v2/calls/transcript") for u in self.gong_paths()))
        t = next(c for c in self.api.calls if c["url"].endswith("/v2/calls/transcript"))
        self.assertEqual(t["body"], {"filter": {"callIds": ["g7"]}})
        items = {i["name"]: i for i in body["items"]}
        self.assertEqual(items["Rosa Quint"]["quote"]["speaker"], "Ann Lee")
        self.assertEqual(items["Rosa Quint"]["quote"]["time"], "1:04")
        self.assertEqual(items["Rosa Quint"]["source"], "gong")
        self.assertNotIn("GONG-ONLY-SENTENCE", (Path(TMP) / "records.json").read_text(encoding="utf-8").replace(items["Rosa Quint"]["quote"]["text"], ""))
        self.assertFalse(any(k[1] == "transcript" for k in S.CRM_CACHE if isinstance(k, tuple) and len(k) > 1))  # never cached

    def test_hubspot_contacts_count_as_known_and_contact_write_needs_confirm(self):
        self.connect(gong=False)
        st, body = S.mentions_post({"callId": "ac1", "text": "Ann Lee: Cy Diaz will want the pack. Rosa Quint from our legal team signs."})
        self.assertEqual(st, 200, body)
        items = {i["name"]: i for i in body["items"]}
        self.assertEqual((items["Cy Diaz"]["status"], items["Cy Diaz"]["person"]["from"], items["Cy Diaz"]["person"]["title"]), ("known", "HubSpot", "Head of Security"))
        self.assertEqual(S.mention_hubspot({"callId": "ac1", "id": items["Cy Diaz"]["id"]})[0], 400)  # already in HubSpot
        rosa = items["Rosa Quint"]
        self.assertEqual(S.mention_hubspot({"callId": "ac1", "id": rosa["id"]})[0], 400)  # not found yet: nothing to save
        S.update_mention("ac1", rosa["id"], lambda x, r: x.update(status="found", person={"name": "Rosa Quint", "title": "General Counsel", "from": "Web"}))
        creates = lambda: [c for c in self.api.calls if c["url"].endswith("/crm/v3/objects/contacts") and c["method"] == "POST"]
        st, out = S.mention_hubspot({"callId": "ac1", "id": rosa["id"]})
        self.assertEqual(st, 200, out)
        self.assertEqual((out["plan"]["firstname"], out["plan"]["lastname"], out["plan"]["jobtitle"], out["plan"]["company"]), ("Rosa", "Quint", "General Counsel", "Acme Corp"))
        self.assertEqual(creates(), [])  # a preview writes nothing
        self.assertEqual(S.mention_hubspot({"callId": "ac1", "id": rosa["id"], "confirm": True})[0], 400)  # no planId
        self.assertEqual(S.mention_hubspot({"callId": "ac1", "id": rosa["id"], "confirm": True, "planId": "0" * 16})[0], 409)
        self.assertEqual(creates(), [])
        st, done = S.mention_hubspot({"callId": "ac1", "id": rosa["id"], "confirm": True, "planId": out["plan"]["planId"]})
        self.assertEqual(st, 200, done)
        self.assertEqual(len(creates()), 1)
        self.assertEqual(creates()[0]["body"], {"properties": {"firstname": "Rosa", "lastname": "Quint", "jobtitle": "General Counsel"},
                                                "associations": [{"to": {"id": "101"}, "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 279}]}]})
        self.assertNotIn("@", json.dumps(creates()[0]["body"]))
        self.assertTrue(S.mentions_body("ac1", requeue=False)["items"][[i["name"] for i in body["items"]].index("Rosa Quint")]["hubspot"])
        # saved once: another tab's fresh preview can't save again (HubSpot's name search lags behind new contacts)
        st, out = S.mention_hubspot({"callId": "ac1", "id": rosa["id"]})
        self.assertEqual(st, 400, out)
        self.assertIn("Already saved", out["error"])
        self.assertEqual(len(creates()), 1)
        S.update_mention("ac1", rosa["id"], lambda x, r: x.update(hubspot="unknown"))  # no answer last time: you may check and try again
        st, out = S.mention_hubspot({"callId": "ac1", "id": rosa["id"]})
        self.assertEqual((st, out["plan"]["savedBefore"]), (200, "unknown"))
        # a name HubSpot already has is never written twice
        S.update_mention("ac1", rosa["id"], lambda x, r: x.update(hubspot="", person={"name": "Bo Chen", "title": "x", "from": "Web"}))
        st, out = S.mention_hubspot({"callId": "ac1", "id": rosa["id"]})
        self.assertEqual(st, 400)
        self.assertIn("already has a contact", out["error"])
        for s in SECRETS:
            self.assertNotIn(s, json.dumps(body) + json.dumps(out))


class MentionRoutes(ServerBase, CrmFakes):
    def setUp(self):
        super().setUp()
        self.crm_setup()
        with S.RQ_LOCK:
            S.RQ["mentions"] = {}
        S.save_json(S.token_path(), {"access_token": "AT-x", "refresh_token": "RT-x", "expires_at": time.time() + 3000, "email": "chris@spotify.com", "name": "Chris Park"})
        events = northwind_events(datetime.now(timezone.utc))
        S.HTTP = lambda method, url, form=None, headers=None, timeout=15: (200, {"items": events}) if url.startswith(S.EVENTS_URL) else (404, {})

    def tearDown(self):
        self.crm_teardown()

    def test_guards_size_limits_and_reads(self):
        origin = "http://localhost:%d" % S.PORT
        good = {"X-OVERTURE": "1", "Origin": origin}
        body = {"callId": "nw1", "text": VTT_T, "filename": "call.vtt"}
        for path in ("/api/mentions", "/api/mentions/pick", "/api/mentions/hubspot"):
            self.assertEqual(self.req("POST", path, body)[0], 403)
            self.assertEqual(self.req("POST", path, body, {"X-OVERTURE": "1"})[0], 403)
            self.assertEqual(self.req("POST", path, body, {"X-OVERTURE": "1", "Origin": "https://evil.example"})[0], 403)
            self.assertEqual(self.req("POST", path, body, dict(good, **{"Content-Type": "text/plain"}))[0], 403)
            self.assertEqual(self.req("POST", path, body, dict(good, Host="evil.example"))[0], 403)
        st, txt, _ = self.req("POST", "/api/mentions", {"callId": "nw1", "text": "x" * (S.MAX_TRANSCRIPT_CHARS + 1)}, good)
        self.assertEqual(st, 400)
        st, txt, _ = self.req("POST", "/api/mentions", {"callId": "nw1", "text": "é" * 500_000}, good)  # over the byte limit once escaped
        self.assertEqual(st, 413)
        self.assertEqual(self.req("POST", "/api/mentions", {"callId": "nw1", "text": "a\u0000b"}, good)[0], 400)
        self.assertEqual(self.req("POST", "/api/mentions/pick", {"callId": "nw1", "id": "a" * 12, "action": "x" * 30_000}, good)[0], 413)
        st, txt, _ = self.req("POST", "/api/mentions", body, good)
        self.assertEqual(st, 200, txt)
        names = {i["name"] for i in json.loads(txt)["items"]}
        self.assertIn("Maria Gomez", names)
        st, txt, _ = self.req("GET", "/api/mentions?callId=nw1")
        self.assertEqual((st, {i["name"] for i in json.loads(txt)["items"]}), (200, names))
        self.assertEqual(self.req("GET", "/api/mentions?callId=../x")[0], 400)
        self.assertEqual(self.req("GET", "/api/mentions?callId=nw1", headers={"Sec-Fetch-Site": "cross-site"})[0], 403)
        self.assertEqual(self.req("HEAD", "/api/mentions?callId=nw1")[0], 404)
        self.assertIn("mentions", json.loads(self.req("GET", "/api/research")[1]))
        self.assertNotIn("PLAN-ONLY-IN-TRANSCRIPT", self.req("GET", "/api/records")[1])


# ---------------------------------------------------------------- sensing references, follow-ups and connections ----------------------------------------------------------------

JOHN_T = "Priya Raman: I'll have to talk with John about that from product managing."
VENDOR_T = "Marcus Bell: Most of our alerts still go through Brightwave Systems. They're our vendor for logging."
HARBOR_T = "Priya Raman: Harborline Labs keeps asking about the pilot too."


def org_answer(relation="partner", url="https://harborline.example/partners", conf="medium", detail=""):
    return reply({"relation": relation, "detail": detail, "confidence": conf, "sources": [{"url": url, "label": "Partners page"}]}, [url])


class SlowClaude(FakeClaude):
    """A fake Claude whose answers wait for a signal, counting how many requests are in flight at once."""

    def __init__(self, answer):
        super().__init__()
        self.answer, self.go, self.lock, self.now, self.most, self.options = answer, threading.Event(), threading.Lock(), 0, 0, []

    def with_options(self, **kw):
        self.options.append(kw)
        return self

    def create(self, **kw):
        with self.lock:
            self.calls.append(kw)
            self.now += 1
            self.most = max(self.most, self.now)
        self.go.wait(5)
        with self.lock:
            self.now -= 1
        return self.answer


class References(Fresh):
    """Sensing people and companies, the follow-up that explains a relation, fast lookups and the People map's connections."""

    def setUp(self):
        super().setUp()
        with S.RQ_LOCK:
            S.RQ.update(queue=[], pending=set(), running=set(), errors={}, meta={}, mentions={})
        self.old = (S.research_client, S.RESEARCH_AUTOSTART, S.HTTP)
        S.RESEARCH_AUTOSTART = False
        os.environ["ANTHROPIC_API_KEY"] = "test-key"
        S.save_json(S.token_path(), {"access_token": "AT-x", "refresh_token": "RT-x", "expires_at": time.time() + 3000, "email": "chris@spotify.com", "name": "Chris Park"})
        self.events = northwind_events(datetime.now(timezone.utc))
        S.HTTP = lambda method, url, form=None, headers=None, timeout=15: (200, {"items": self.events}) if url.startswith(S.EVENTS_URL) else (404, {})

    def tearDown(self):
        S.research_client, S.RESEARCH_AUTOSTART, S.HTTP = self.old
        os.environ.pop("ANTHROPIC_API_KEY", None)

    fake, post, by = MentionFlow.fake, MentionFlow.post, MentionFlow.by

    def ctx(self):
        rec = S.load_records()
        c = S.mention_context(self.events, ME, rec, "nw1", datetime.now(timezone.utc))
        c["orgs"] = S.known_orgs(self.events, rec, c["domain"], ME["email"])
        return c

    def orgs(self, text):
        return {o["name"]: o for o in S.find_all(S.parse_transcript(text), self.ctx())[1]}

    def org(self, body, name):
        return next(o for o in body["orgs"] if o["name"] == name)

    def test_john_with_words_between_his_name_and_team(self):
        people, _ = S.find_all(S.parse_transcript(JOHN_T + " He owns the roadmap."), self.ctx())
        self.assertEqual([(p["kind"], p["name"], p["role"]) for p in people], [("partial", "John", "product management")])  # "managing" normalised
        self.assertEqual(people[0]["said"]["label"], "owns the roadmap")  # the follow-up, said on the call
        f = self.fake(mention_reply([cand("John Reyes", "Group Product Manager", "https://northwind-freight.com/team/john")], ["https://northwind-freight.com/team/john"]))
        body = self.post(JOHN_T + " He owns the roadmap.", filename="n.txt")
        with S.RQ_LOCK:
            self.assertEqual([k for k, _ in S.RQ["queue"]], ["mention:nw1:" + self.by(body)["John"]["id"]])  # queued at once
        while S.research_step():
            pass
        user = f.calls[0]["messages"][0]["content"]
        self.assertIn("Mentioned on the call: John\nRole or team: product management\nCompany: Northwind Freight\nCompany website: northwind-freight.com", user)
        self.assertNotIn("roadmap", json.dumps(f.calls, default=str))  # what was said about him stays here
        john = self.by(S.mentions_body("nw1", requeue=False))["John"]
        self.assertEqual((john["status"], john["autoFound"], john["person"]["name"], john["connected"]), ("found", True, "John Reyes", True))
        conn = next(c for c in S.load_records()["connections"].values() if c["kind"] == "person")
        self.assertEqual((conn["name"], conn["label"], conn["source"], conn["from"], conn["callId"]),
                         ("John Reyes", "owns the roadmap", "Said on the call", "p:priya.raman@northwind-freight.com", "nw1"))
        self.assertTrue(conn["at"])

    def test_company_cues_known_names_and_skips(self):
        o = self.orgs("Marcus Bell: We switched from Loggly last year. Datadog's team called. We partnered with Acme Robotics Inc in March. "
                      "Zephyr AI acquired us. We also looked at Port last quarter. Nimbus Labs is new.")
        self.assertEqual(set(o), {"Loggly", "Datadog", "Acme Robotics Inc", "Zephyr AI", "Port", "Nimbus Labs"})
        self.assertEqual(o["Datadog"]["domain"], "datadoghq.com")  # a vendor Overture knows: its website goes with the lookup
        self.assertEqual((o["Loggly"]["relation"]["type"], o["Loggly"]["relation"]["detail"]), ("vendor", "former"))
        self.assertEqual(o["Acme Robotics Inc"]["relation"]["type"], "partner")
        self.assertEqual(o["Zephyr AI"]["relation"]["type"], "acquirer")
        self.assertIsNone(o["Port"]["relation"])  # nothing said about it: looked up on the web
        people = {p["name"] for p in S.find_all(S.parse_transcript("Marcus Bell: We partnered with Acme Robotics Inc."), self.ctx())[0]}
        self.assertNotIn("Acme Robotics", people)  # a company, not a person
        for s in ("We use Backstage and Spotify Portal.", "Northwind Freight is great.", "Project Falcon is the acquisition we can't talk about.",
                  "Kenji is moving to Ohio next month.", "Tom's team signs on Monday.", "We switched from them in March.",
                  "Operation Bluebird starts soon.", "Maria from Spotify said so.", "Our Confidence pilot."):
            self.assertEqual(self.orgs("Marcus Bell: " + s), {}, s)
        known = self.orgs("Marcus Bell: Expedia and Zalando use it. bol.com too.")  # the public Backstage adopters list
        self.assertTrue({"Expedia", "Zalando"} <= set(known), known)

    def test_follow_up_explains_the_relation_so_no_lookup(self):
        f = self.fake()
        body = self.post(VENDOR_T, filename="v.txt")
        o = self.org(body, "Brightwave Systems")
        self.assertEqual((o["status"], o["relation"]["type"], o["relation"]["detail"], o["relation"]["source"]), ("said", "vendor", "logging", "said"))
        self.assertEqual(o["relation"]["label"], "their vendor (logging)")
        self.assertIn("vendor for logging", o["relation"]["said"])
        with S.RQ_LOCK:
            self.assertEqual(S.RQ["queue"], [])
        self.assertIsNone(S.research_step())
        self.assertEqual(f.calls, [])  # explained on the call: nothing goes to the web
        conn = next(c for c in S.load_records()["connections"].values() if c["kind"] == "company")
        self.assertEqual((conn["name"], conn["relation"], conn["label"], conn["source"], conn["from"]),
                         ("Brightwave Systems", "vendor", "their vendor (logging)", "Said on the call", "p:marcus.bell@northwind-freight.com"))

    def test_no_follow_up_means_a_web_lookup_at_once(self):
        f = self.fake(org_answer("partner"))
        body = self.post(HARBOR_T, filename="h.txt")
        o = self.org(body, "Harborline Labs")
        self.assertEqual(o["status"], "pending")
        with S.RQ_LOCK:
            self.assertEqual([k for k, _ in S.RQ["queue"]], ["org:nw1:" + o["id"]])  # queued in the same request
        self.assertTrue(o["connected"])  # on the map straight away, relation to follow
        S.research_step()
        user = f.calls[0]["messages"][0]["content"]
        self.assertEqual(user.split("\n\n")[0], "Company A: Northwind Freight\nCompany A website: northwind-freight.com\nCompany B: Harborline Labs\nCompany B website: (not known)")
        self.assertEqual(f.calls[0]["tools"][0]["max_uses"], 3)
        o = self.org(S.mentions_body("nw1", requeue=False), "Harborline Labs")
        self.assertEqual((o["status"], o["relation"]["type"], o["relation"]["source"], o["relation"]["sources"][0]["url"]),
                         ("found", "partner", "web", "https://harborline.example/partners"))
        # unsourced, unsure or off-list answers are "unknown", never a guess; the answer is cached by the two companies
        S.LOOKUP_CACHE.clear()
        for bad in (org_answer("partner", conf="low"), reply({"relation": "partner", "confidence": "high", "sources": [{"url": "https://never-searched.example.com/x"}]}),
                    org_answer("best friends"), org_answer("partner", url="https://www.zoominfo.com/c/harborline")):
            S.update_org("nw1", o["id"], lambda x, r: x.update(status="pending", relation=None))
            S.LOOKUP_CACHE.clear()
            self.fake(bad)
            S.do_org_lookup({"callId": "nw1", "id": o["id"], "name": "Harborline Labs", "company": "Northwind Freight", "domain": "northwind-freight.com"})
            self.assertEqual(self.org(S.mentions_body("nw1", requeue=False), "Harborline Labs")["status"], "unknown")
        f = self.fake()
        S.update_org("nw1", o["id"], lambda x, r: x.update(status="pending", relation=None))
        S.do_org_lookup({"callId": "nw1", "id": o["id"], "name": "Harborline Labs", "company": "Northwind Freight", "domain": "northwind-freight.com"})
        self.assertEqual(f.calls, [])  # (Northwind Freight, Harborline Labs) came from the cache

    def test_lookups_carry_only_names_roles_companies_and_domains(self):
        f = self.fake(mention_reply([]), reply({"relation": "unknown"}), mention_reply([]), mention_reply([]), mention_reply([]))
        text = VTT_T + "\n6\n00:03:00.000 --> 00:03:04.000\nMarcus Bell: " + HARBOR_T.split(": ", 1)[1] + " SECRET-PRICE-123.\n"
        self.post(text)
        while S.research_step():
            pass
        self.assertTrue(f.calls)
        sent = json.dumps(f.calls, default=str)
        for bit in ("keeps asking", "pilot", "SECRET-PRICE-123", "will want the pack", "Priya", "Marcus", "@", "0:01"):
            self.assertNotIn(bit, sent)
        for call in f.calls:
            keys = set(re.findall(r"^([A-Za-z ]+):", call["messages"][0]["content"], re.M))
            self.assertIn(keys, ({"Mentioned on the call", "Role or team", "Company", "Company website"},
                                 {"Company A", "Company A website", "Company B", "Company B website"}))
            self.assertEqual((call["tools"][0]["max_uses"], call["output_config"]), (3, {"effort": "low"}))
            self.assertEqual(call["tools"][0]["blocked_domains"], S.BLOCKED_DOMAINS)

    def test_fast_lookups_use_a_20_second_budget(self):
        slow = SlowClaude(mention_reply([]))
        slow.go.set()
        S.research_client = lambda: slow
        self.post(JOHN_T, filename="j.txt")
        S.research_step()
        self.assertEqual(slow.options, [{"timeout": 20.0, "max_retries": 0}])

    def test_three_lookups_at_once_and_said_on_a_call_goes_first(self):
        S.queue_research({"ann@acme.com": {"name": "Ann Lee", "company": "Acme", "domain": "acme.com", "named": True, "callId": "x"}}, S.empty_records())
        block = {"company": "Northwind Freight", "domain": "northwind-freight.com"}
        S.queue_mention("nw1", block, {"id": "a" * 12, "name": "Maria Gomez", "kind": "full"})
        S.queue_org("nw1", block, {"id": "b" * 12, "name": "Harborline Labs"})
        with S.RQ_LOCK:
            order = []
            while S.RQ["queue"]:
                order.append(S._next_job()[0])
            S.RQ["pending"].clear()
        self.assertEqual(order, ["mention:nw1:" + "a" * 12, "org:nw1:" + "b" * 12, "ann@acme.com"])  # invitee research waits its turn
        slow = SlowClaude(mention_reply([]))
        S.research_client = lambda: slow
        S.RESEARCH_AUTOSTART = True
        try:
            for i in range(6):
                S.queue_mention("nw1", block, {"id": "%012x" % i, "name": "Person %d Lee" % i, "kind": "full"})
            for _ in range(200):
                if slow.now >= S.MAX_WORKERS:
                    break
                time.sleep(0.01)
            time.sleep(0.1)
            self.assertEqual((slow.now, slow.most), (S.MAX_WORKERS, S.MAX_WORKERS))  # three at once, never more
        finally:
            slow.go.set()
            for _ in range(300):
                with S.RQ_LOCK:
                    if not S.RQ["queue"] and not S.RQ["running"]:
                        break
                time.sleep(0.01)
            S.RESEARCH_AUTOSTART = False
        self.assertEqual(len(slow.calls), 6)

    def test_live_notes_are_read_as_you_type(self):
        f = self.fake(org_answer("partner"))
        seg = "abc123xyz"

        def send(off, text, final=False, pause=False):
            st, body = S.mentions_live({"callId": "nw1", "segment": seg, "offset": off, "text": text, "final": final, "pause": pause})
            self.assertEqual(st, 200, body)
            return body
        b = send(0, "Talk with John Sm")
        self.assertEqual(b["items"], [])  # "Sm" is still being typed: not read yet, so no "John Sm"
        t1 = "Talk with John Sm"
        b = send(len(t1), "ith later. Our logs go through Brightwave Systems", pause=True)  # only the new text; a pause reads the last word
        self.assertEqual([i["name"] for i in b["items"]], ["John Smith"])
        self.assertEqual(self.org(b, "Brightwave Systems")["status"], "waiting")  # the speaker may still explain it
        t2 = t1 + "ith later. Our logs go through Brightwave Systems"
        b = send(len(t2), ". They're their vendor for logging. ")
        o = self.org(b, "Brightwave Systems")
        self.assertEqual((o["status"], o["relation"]["type"]), ("said", "vendor"))
        self.assertEqual(f.calls, [])
        with S.LIVE_LOCK:
            self.assertEqual(S.LIVE_SEGMENTS[("nw1", seg)]["text"], t2 + ". They're their vendor for logging. ")  # memory only
        b = send(0, "Harborline Labs called", pause=True)  # an edit from the start replaces the text (no full stop: read on the pause)
        h = self.org(b, "Harborline Labs")
        self.assertEqual(h["status"], "waiting")
        self.assertEqual(([i["name"] for i in b["items"]], [o["name"] for o in b["orgs"]]), ([], ["Harborline Labs"]))  # the note no longer says them
        self.assertEqual(S.promote_waiting(_time_now() + 5), 0)  # still inside its 30 seconds
        self.assertEqual(S.promote_waiting(_time_now() + S.WAIT_SECONDS + 1), 1)  # 30 seconds and nothing more: look it up
        with S.RQ_LOCK:
            self.assertIn("org:nw1:" + h["id"], S.RQ["pending"])
        b = send(len("Harborline Labs called"), ".", final=True)
        with S.LIVE_LOCK:
            self.assertNotIn(("nw1", seg), S.LIVE_SEGMENTS)  # saved: the note's text is dropped
        saved = (Path(TMP) / "records.json").read_text(encoding="utf-8")
        self.assertNotIn("Talk with John Smith later. Our logs", saved)  # one sentence per mention, never the note
        self.assertEqual(self.org(S.mentions_body("nw1", requeue=False), "Harborline Labs")["quote"]["text"], "Harborline Labs called")  # its own sentence
        self.assertEqual(S.mentions_live({"callId": "nw1", "segment": seg, "offset": 99, "text": "x"})[0], 409)  # resend from the start
        for bad in ({"callId": "nw1", "segment": "x", "text": "a"}, {"callId": "nw1", "segment": seg, "offset": -1, "text": "a"},
                    {"callId": "nw1", "segment": seg, "text": "a" * 4001}, {"callId": "nw1", "segment": seg, "text": "a", "final": "yes"},
                    {"callId": "nw1", "segment": seg, "text": "a\x00b"}, {"callId": "nw1", "segment": seg, "text": "a", "extra": 1}):
            self.assertEqual(S.mentions_live(bad)[0], 400, bad)

    def test_google_meet_captions_are_read_live_and_again_after_the_call(self):
        self.fake(org_answer("partner"), org_answer("partner"))
        st, b = S.mentions_live({"callId": "nw1", "segment": "capseg01", "offset": 0, "text": "Shea Kim: Harborline Labs called us.", "final": True,
                                 "source": "captions"})
        self.assertEqual(st, 200)
        org = self.org(b, "Harborline Labs")
        self.assertEqual(org["source"] if "source" in org else "captions", "captions")
        self.assertEqual(S.mentions_live({"callId": "nw1", "segment": "capseg02", "text": "a", "source": "radio"})[0], 400)
        # after the call: the whole caption transcript, read like an uploaded one
        st, b = S.mentions_post({"callId": "nw1", "text": "Shea Kim: Harborline Labs called us.\nMarcus Bell: Talk to Rivet Analytics.", "source": "captions"})
        self.assertEqual(st, 200)
        self.assertEqual(S.MENTION_SOURCES["captions"], "Google Meet's captions")
        self.assertIn("captions", S.AUTO_SOURCES)

    def test_finished_note_decides_at_once(self):
        f = self.fake(org_answer("partner"))
        st, b = S.mentions_live({"callId": "nw1", "segment": "seg999xyz", "offset": 0, "text": "Harborline Labs called.", "final": True})
        self.assertEqual(self.org(b, "Harborline Labs")["status"], "pending")  # no explanation and the note is done: search now
        S.research_step()
        self.assertEqual(self.org(S.mentions_body("nw1", requeue=False), "Harborline Labs")["status"], "found")
        self.assertEqual(len(f.calls), 1)

    def test_codename_protection_still_works(self):
        f = self.fake()
        body = self.post("Marcus Bell: Project Falcon is the acquisition we can't talk about. Operation Bluebird too.", filename="c.txt")
        self.assertEqual((body["items"], body["orgs"]), ([], []))
        self.assertIsNone(S.research_step())
        self.assertEqual(f.calls, [])

    def test_connections_reach_the_map_and_removed_ones_stay_removed(self):
        self.fake(mention_reply([cand("Maria Gomez")], ["https://northwind-freight.com/team/x"]), mention_reply([]), mention_reply([]))
        self.post(VTT_T + "\n6\n00:03:00.000 --> 00:03:04.000\n" + VENDOR_T + "\n")
        while S.research_step():
            pass
        now = datetime.now(timezone.utc)
        live = S.build_live(self.events, ME, S.load_records(), now)
        nodes = {n["id"]: n for n in live["mentioned"]}
        edges = {e["b"]: e for e in live["relationships"]}
        maria = next(n for n in nodes.values() if n["label"] == "Maria Gomez")
        self.assertEqual((maria["type"], maria["company"], maria["callId"], maria["mentioned"]), ("person", "Northwind Freight", "nw1", True))
        self.assertEqual((edges[maria["id"]]["a"], edges[maria["id"]]["kind"], edges[maria["id"]]["label"]), ("p:priya.raman@northwind-freight.com", "mentioned", "security"))
        self.assertEqual(nodes["co:Brightwave Systems"]["type"], "company")
        self.assertEqual(edges["co:Brightwave Systems"]["label"], "their vendor (logging)")
        self.assertIn("vendor for logging", edges["co:Brightwave Systems"]["why"])
        self.assertNotIn("Tom", {n["label"] for n in nodes.values()})  # not found: nothing on the map
        self.assertNotIn("Grace Ito", {n["label"] for n in nodes.values()})  # "pick": not until you pick
        self.assertEqual(live["mentions"], {"nw1": 5})
        # remove a wrong one: gone from the map, and a new transcript doesn't bring it back
        st, out = S.mention_action({"callId": "nw1", "id": edges["co:Brightwave Systems"]["mentionId"], "action": "remove"})
        self.assertEqual(st, 200, out)
        self.assertNotIn("co:Brightwave Systems", {e["b"] for e in out["graph"]["relationships"]})
        self.post(VENDOR_T, filename="again.txt")
        live = S.build_live(self.events, ME, S.load_records(), now)
        self.assertNotIn("co:Brightwave Systems", {e["b"] for e in live["relationships"]})
        st, out = S.mention_action({"callId": "nw1", "id": edges["co:Brightwave Systems"]["mentionId"], "action": "restore"})
        self.assertIn("co:Brightwave Systems", {e["b"] for e in out["graph"]["relationships"]})
        st, out = S.mention_action({"callId": "nw1", "id": edges[maria["id"]]["mentionId"], "action": "remove"})
        self.assertTrue(self.by(out)["Maria Gomez"]["removed"])
        self.assertNotIn(maria["id"], {n["id"] for n in out["graph"]["mentioned"]})
        # your answer wins: "none" takes an automatic find off the map too
        st, out = S.mention_action({"callId": "nw1", "id": edges[maria["id"]]["mentionId"], "action": "restore"})
        st, out = S.mention_action({"callId": "nw1", "id": edges[maria["id"]]["mentionId"], "action": "none"})
        self.assertEqual(self.by(out)["Maria Gomez"]["status"], "notfound")
        self.assertNotIn("Maria Gomez", {n["label"] for n in out["graph"]["mentioned"]})


class PausingClaude(FakeClaude):
    """A fake Claude that records the per-request options (timeouts) it is given."""

    def __init__(self, *replies):
        super().__init__(*replies)
        self.options = []

    def with_options(self, **kw):
        self.options.append(kw)
        return self


class ReviewFixes(Fresh):
    """Codenames, live-note intermediate states, auto-matching, relation rules, worker slots and HubSpot during live notes."""

    def setUp(self):
        super().setUp()
        with S.RQ_LOCK:
            S.RQ.update(queue=[], pending=set(), running=set(), errors={}, meta={}, mentions={})
        self.old = (S.research_client, S.RESEARCH_AUTOSTART, S.HTTP)
        S.RESEARCH_AUTOSTART = False
        os.environ["ANTHROPIC_API_KEY"] = "test-key"
        S.save_json(S.token_path(), {"access_token": "AT-x", "refresh_token": "RT-x", "expires_at": time.time() + 3000, "email": "chris@spotify.com", "name": "Chris Park"})
        self.events = northwind_events(datetime.now(timezone.utc))
        S.HTTP = lambda method, url, form=None, headers=None, timeout=15: (200, {"items": self.events}) if url.startswith(S.EVENTS_URL) else (404, {})

    def tearDown(self):
        S.research_client, S.RESEARCH_AUTOSTART, S.HTTP = self.old
        os.environ.pop("ANTHROPIC_API_KEY", None)

    fake, post, by = MentionFlow.fake, MentionFlow.post, MentionFlow.by

    def ctx(self):
        rec = S.load_records()
        c = S.mention_context(self.events, ME, rec, "nw1", datetime.now(timezone.utc))
        c["orgs"] = S.known_orgs(self.events, rec, c["domain"], ME["email"])
        return c

    def find(self, text, speaker="Marcus Bell"):
        p, o = S.find_all([{"speaker": speaker, "time": "", "text": text}], self.ctx())
        return [(x["kind"], x["name"], x["role"]) for x in p], {x["name"]: x["relation"] for x in o}

    def live(self, seg, off, text, final=False, pause=False):
        st, body = S.mentions_live({"callId": "nw1", "segment": seg, "offset": off, "text": text, "final": final, "pause": pause})
        self.assertEqual(st, 200, body)
        return body

    def queued(self):
        with S.RQ_LOCK:
            return [k for k, _ in S.RQ["queue"]]

    def test_codenames_never_reach_claude(self):
        for s in ("Maria, the director of Project Falcon, signs off.", "The director of Project Falcon, Maria, signs off.",
                  "Dana, our VP of Project Falcon, decides.", "Maria on the Falcon project will join.", "Maria Gomez, our director of Project Falcon, signs.",
                  "Under the codename Falcon Labs we are building it.", "We are moving to project Falcon AI soon.", "The Falcon AI project is late."):
            people, orgs = self.find(s)
            self.assertFalse(any("Falcon" in r for _, _, r in people), s)
            self.assertEqual(orgs, {}, s)
        self.assertEqual(self.find("Maria from the Falcon team will join.")[0], [("partial", "Maria", "")])  # a team's own name: not sent
        self.assertEqual(self.find("Sarah at Goldman Sachs called.")[0], [("partial", "Sarah", "at Goldman Sachs")])  # companies still are
        self.assertEqual(self.find("Dana from program management signs.")[0], [("partial", "Dana", "program management")])  # a team, not a codename
        for name, role in (("Maria", "director of Project Falcon"), ("Maria", "at Falcon project")):
            with self.assertRaises(S.ResearchError):
                S.mention_request(name, role, "Northwind Freight", "northwind-freight.com")
        with self.assertRaises(S.ResearchError):
            S.org_request("Northwind Freight", "northwind-freight.com", "Project Falcon AI", "")
        S.mention_request("Dana", "program management", "Northwind Freight", "northwind-freight.com")  # fine
        f = self.fake(*[mention_reply([]) for _ in range(6)])
        self.post("Marcus Bell: Maria, the director of Project Falcon, signs off. Dana on the Falcon project will join. "
                  "Under the codename Falcon Labs we build it. Maria Gomez, our VP of Project Falcon, decides.", filename="c.txt")
        while S.research_step():
            pass
        self.assertNotIn("Falcon", json.dumps(f.calls, default=str))

    def test_live_note_takes_back_what_it_no_longer_says(self):
        john = cand("John Doe", "Product Designer", "https://northwind-freight.com/team/john")
        self.fake(mention_reply([john], ["https://northwind-freight.com/team/john"]), mention_reply([]), mention_reply([]))
        t1 = "talk with John about that from product "
        self.assertEqual(self.live("seg1abcd", 0, t1)["items"], [])  # no full stop and no pause yet: not read
        b = self.live("seg1abcd", 0, t1, pause=True)  # a pause between words reads it as team "product"
        self.assertEqual([(i["name"], i["role"]) for i in b["items"]], [("John", "product")])
        S.research_step()
        b = S.mentions_body("nw1", requeue=False)
        self.assertEqual((b["items"][0]["status"], b["items"][0]["autoFound"], b["items"][0]["connected"]), ("found", True, True))
        b = self.live("seg1abcd", len(t1), "managing.")
        self.assertEqual([(i["name"], i["role"], i["status"]) for i in b["items"]], [("John", "product management", "pending")])  # one John
        self.assertEqual(self.queued(), ["mention:nw1:" + b["items"][0]["id"]])
        self.assertEqual([c["kind"] for c in S.load_records()["connections"].values()], [])  # the wrong automatic find is off the map
        # a pause in the middle of a name: "John Sm" goes once "John Smith" is read, and so does its queued lookup
        b = self.live("seg2abcd", 0, "Ping John Sm", pause=True)
        sm = next(i for i in b["items"] if i["name"] == "John Sm")
        self.assertIn("mention:nw1:" + sm["id"], self.queued())
        b = self.live("seg2abcd", len("Ping John Sm"), "ith today.")
        self.assertNotIn("John Sm", [i["name"] for i in b["items"]])
        self.assertIn("John Smith", [i["name"] for i in b["items"]])
        self.assertNotIn("mention:nw1:" + sm["id"], self.queued())
        # a company typed in two goes: one company, one connection
        b = self.live("seg3abcd", 0, "We switched from Acme", pause=True)
        self.assertIn("Acme", [o["name"] for o in b["orgs"]])
        b = self.live("seg3abcd", len("We switched from Acme"), " Freight last year.")
        self.assertEqual([o["name"] for o in b["orgs"] if o["name"].startswith("Acme")], ["Acme Freight"])
        self.assertEqual([c["name"] for c in S.load_records()["connections"].values() if c["kind"] == "company"], ["Acme Freight"])
        # what you acted on stays, even when the note changes
        b = self.live("seg4abcd", 0, "Ask Kenji about it from legal.")
        kenji = next(i for i in b["items"] if i["name"] == "Kenji")
        S.update_mention("nw1", kenji["id"], lambda x, r: x.update(status="found", person={"name": "Kenji Sato", "title": "Counsel"}, confirmed=True))
        b = self.live("seg4abcd", 0, "Ask Kenji about it from legal ops.")
        self.assertEqual(sorted(i["role"] for i in b["items"] if i["name"] == "Kenji"), ["legal"])  # "legal ops" isn't a team: only the confirmed one
        # a sentence still being typed keeps what a pause found in it
        b = self.live("seg5abcd", 0, "Harborline Labs called", pause=True)
        b = self.live("seg5abcd", len("Harborline Labs called"), " and")
        self.assertIn("Harborline Labs", [o["name"] for o in b["orgs"]])

    def test_live_text_is_dropped_after_ten_quiet_minutes(self):
        self.live("seg6abcd", 0, "Harborline Labs called.")
        with S.LIVE_LOCK:
            S.LIVE_SEGMENTS[("nw1", "seg6abcd")]["at"] -= S.LIVE_TTL + 1
        self.assertLessEqual(S.LIVE_TTL, 15 * 60)
        st, body = S.mentions_live({"callId": "nw1", "segment": "seg6abcd", "offset": 5, "text": "x"})
        self.assertEqual((st, body.get("error")), (409, "resend"))  # the panel then sends the whole note again

    def test_role_fits_whole_words(self):
        for role, title in (("product management", "Production Manager"), ("product", "Production Support Engineer"), ("sales", "Salesforce Administrator"),
                            ("marketing", "Marketplace Operations Lead"), ("security", "Securities Counsel")):
            self.assertFalse(S.role_fits(role, {"title": title}), (role, title))
        for role, title in (("product management", "Group Product Manager"), ("security", "Security Engineering Manager"), ("finance", "Financial Analyst"),
                            ("engineering", "Software Engineer"), ("design", "Product Designer"), ("operations", "Operations Lead"), ("sales", "Sales Director")):
            self.assertTrue(S.role_fits(role, {"title": title}), (role, title))

    def test_no_name_or_another_company_is_never_auto_picked(self):
        self.fake(mention_reply([cand("Old Boss", "CTO", "https://northwind-freight.com/team/old")], ["https://northwind-freight.com/team/old"]))
        self.post("Marcus Bell: Our new CTO starts Monday.", filename="cto.txt")
        while S.research_step():
            pass
        cto = self.by(S.mentions_body("nw1", requeue=False))["CTO"]
        self.assertEqual((cto["status"], cto["autoFound"], cto["connected"]), ("pick", False, False))  # likely, not confirmed
        S.LOOKUP_CACHE.clear()
        other = "https://othercorp.example/team/john"
        self.fake(mention_reply([cand("John Reyes", "Group Product Manager", other)], [other]))
        self.post(JOHN_T, filename="j.txt")
        while S.research_step():
            pass
        j = self.by(S.mentions_body("nw1", requeue=False))["John"]
        self.assertEqual((j["status"], j["autoFound"], j["connected"]), ("pick", False, False))  # a source at another company: not auto
        self.assertFalse(S.on_company_site({"sources": [{"url": "https://northwind-freight.com.evil.example/x"}]}, "northwind-freight.com"))
        self.assertTrue(S.on_company_site({"sources": [{"url": "https://www.northwind-freight.com/x"}]}, "northwind-freight.com"))

    def test_only_the_matched_words_are_saved(self):
        self.fake()
        self.post("Marcus Bell: Most of our alerts still go through Brightwave Systems. They're our vendor for logging and we pay them 40k a year.", filename="v.txt")
        self.post("Marcus Bell: Talk with John from product. He owns the roadmap, and he signed a 2 million deal.", filename="p.txt")
        saved = (Path(TMP) / "records.json").read_text(encoding="utf-8")
        for bit in ("40k", "we pay them", "2 million"):
            self.assertNotIn(bit, saved)
        said = {c["name"]: c["said"] for c in S.load_records()["connections"].values()}
        self.assertEqual(said["Brightwave Systems"], "They're our vendor for logging")
        john = next(i for i in S.load_records()["mentions"]["nw1"]["items"] if i["name"] == "John")
        self.assertEqual(john["said"]["said"], "owns the roadmap")

    def test_lookup_budget_covers_resends(self):
        f = PausingClaude(reply("{}", stop="pause_turn"), reply("{}", stop="pause_turn"), mention_reply([]))
        S.research_client = lambda: f
        ticks = iter([0.0, 15.0, 19.5])
        old = S._time
        S._time = SimpleNamespace(monotonic=lambda: next(ticks), time=time.time, sleep=time.sleep)
        try:
            with self.assertRaises(S.ResearchError):  # out of time while paused: an error, not "found nobody"
                S.run_search(S.mention_request("John", "product", "Northwind Freight", "northwind-freight.com"), 20)
        finally:
            S._time = old
        self.assertEqual([o["timeout"] for o in f.options], [20.0, 5.0])  # the resend gets what is left, not another 20 s
        self.assertEqual(len(f.calls), 2)

    def test_contact_words_anchor_a_name_and_its_team(self):
        for s in ("Most of the pushback is from legal.", "Waiting on a reply from security.", "Nothing yet from finance.", "Everything else comes from platform.",
                  "Getting sign off from legal is slow.", "Headcount was cut in engineering.", "Access requests are handled in IT.",
                  "Brightwave had a rep in from sales last week."):
            self.assertEqual(self.find(s)[0], [], s)
        self.assertEqual(self.find(JOHN_T.split(": ", 1)[1], "Priya Raman")[0], [("partial", "John", "product management")])
        self.assertEqual(self.find("Ask Sarah about the contract from legal.")[0], [("partial", "Sarah", "legal")])

    def test_team_shorthand(self):
        self.assertEqual(self.find("Talk with John from PM about the roadmap.")[0], [("partial", "John", "product management")])
        self.assertEqual(self.find("Ping Sarah in eng about SSO.")[0], [("partial", "Sarah", "engineering")])
        self.assertEqual(self.find("Ask Dana from CS.")[0], [("partial", "Dana", "customer success")])
        self.assertEqual(self.find("Ask Raj from BD.")[0], [("partial", "Raj", "business development")])
        self.assertEqual(self.find("Call Dana later in the pm about it.")[0], [])  # the afternoon, not product management
        self.assertTrue(S.role_fits("product management", {"title": "Group Product Manager"}))

    def test_everyday_words_are_not_companies(self):
        for s in ("We're moving to GA next month.", "We're moving to Beta soon.", "We're moving to Production on Friday.", "They're moving to Staging.",
                  "We're moving to Prod.", "Grab the deck before Friday.", "Spread the word internally.", "Port forwarding broke.", "Harness the momentum.",
                  "Elastic scaling is a must.", "Compass points to the old docs.", "We need the Gen AI story."):
            self.assertEqual(self.find(s)[1], {}, s)
        self.assertIn("Port", self.find("We also looked at Port last quarter.")[1])
        self.assertEqual(self.find("Port is a competitor.")[1]["Port"]["type"], "competitor")
        self.assertEqual(self.find("We use Harness for CI.")[1]["Harness"]["type"], "uses_product")
        self.assertIn("Port", self.find("Port's pricing is high.")[1])

    def test_a_relation_belongs_to_the_company_it_is_said_about(self):
        o = self.find("Brightwave Systems is our vendor and Harborline Labs is a partner.")[1]
        self.assertEqual((o["Brightwave Systems"]["type"], o["Harborline Labs"]["type"]), ("vendor", "partner"))
        for s in ("Harborline Labs keeps asking about the pilot, since our investors like it.", "Harborline Labs called. They want a partner for the rollout.",
                  "We never partnered with Brightwave Systems.", "Harborline Labs isn't a competitor."):
            self.assertTrue(all(v is None for v in self.find(s)[1].values()), s)
        self.assertEqual(self.find("Harborline Labs? Not a competitor at all, they're a partner.")[1]["Harborline Labs"]["type"], "partner")
        p, _ = S.find_all([{"speaker": "Marcus Bell", "time": "", "text": "Talk with John from product. They're our biggest customer."}], self.ctx())
        self.assertIsNone(p[0]["said"])  # "they're our biggest customer" is about a company, not John

    def test_an_unfinished_sentence_is_not_a_follow_up(self):
        f = self.fake(org_answer("competitor"))
        t1 = "Harborline Labs called. Quick note. They're a "
        b = self.live("seg7abcd", 0, t1, pause=True)
        self.assertEqual(self.org_of(b)["status"], "waiting")  # "They're a" is still being typed
        b = self.live("seg7abcd", len(t1), "partner of ours.")
        self.assertEqual((self.org_of(b)["status"], self.org_of(b)["relation"]["type"]), ("said", "partner"))
        self.assertEqual(f.calls, [])
        # explained after the web lookup was queued: what the call said wins, and the lookup is dropped
        S.mentions_post({"callId": "nw1", "text": "Priya Raman: Nimbus Labs keeps asking.", "filename": "a.txt"})
        self.assertEqual(len(self.queued()), 1)
        b = self.post("Priya Raman: Nimbus Labs keeps asking. They're a partner of ours.", filename="b.txt")
        nimbus = next(o for o in b["orgs"] if o["name"] == "Nimbus Labs")
        self.assertEqual((nimbus["status"], nimbus["relation"]["type"]), ("said", "partner"))
        self.assertEqual(self.queued(), [])

    def org_of(self, body, name="Harborline Labs"):
        return next(o for o in body["orgs"] if o["name"] == name)

    def test_said_on_a_call_always_gets_a_worker(self):
        with S.RQ_LOCK:
            S.RQ["running"] |= {"a@acme.com", "b@acme.com"}  # two invitee lookups running
            S.RQ["queue"].append(("c@acme.com", False))
            S.RQ["pending"].add("c@acme.com")
        try:
            self.assertIsNone(S.research_step())  # the third worker stays free for things said on the call
            with S.RQ_LOCK:
                self.assertEqual(S.RQ["queue"], [("c@acme.com", False)])
                self.assertFalse(S._job_ready())
            self.fake(mention_reply([]))
            S.queue_mention("nw1", {"company": "Northwind Freight", "domain": "northwind-freight.com"}, {"id": "c" * 12, "name": "Maria Gomez", "kind": "full"})
            self.assertEqual(S.research_step(), "mention:nw1:" + "c" * 12)
        finally:
            with S.RQ_LOCK:
                S.RQ["running"] -= {"a@acme.com", "b@acme.com"}
        self.assertEqual(S.research_step(), "c@acme.com")  # and invitee research goes on once a worker is free

    def test_live_notes_never_wait_for_hubspot(self):
        gate, calls = threading.Event(), []

        def slow(domain, deadline=None):
            calls.append(domain)
            gate.wait(5)
            return []
        old = (S.crm_configured, S.hubspot_domain_contacts)
        S.crm_configured = lambda s: s == "hubspot"
        S.hubspot_domain_contacts = slow
        try:
            t0 = time.time()
            self.live("seg8abcd", 0, "Ask Maria Gomez.")
            self.live("seg8abcd", len("Ask Maria Gomez."), " Ping Dana Li.")
            self.assertLess(time.time() - t0, 2)  # HubSpot is asked in the background, once
            self.assertEqual(calls, ["northwind-freight.com"])
            gate.set()
            for _ in range(200):
                with S.CRM_LOCK:
                    if not S.HS_WARMING:
                        break
                time.sleep(0.01)
            self.post("Marcus Bell: Ask Maria Gomez.", filename="m.txt")  # a transcript still asks HubSpot itself
            self.assertEqual(len(calls), 2)
        finally:
            gate.set()
            S.crm_configured, S.hubspot_domain_contacts = old


def _time_now():
    return time.time()


class LiveRoute(ServerBase):
    def setUp(self):
        super().setUp()
        S.save_json(S.token_path(), {"access_token": "AT-x", "refresh_token": "RT-x", "expires_at": time.time() + 3000, "email": "chris@spotify.com", "name": "Chris Park"})
        events = northwind_events(datetime.now(timezone.utc))
        self.old = (S.HTTP, S.RESEARCH_AUTOSTART)
        S.RESEARCH_AUTOSTART = False
        S.HTTP = lambda method, url, form=None, headers=None, timeout=15: (200, {"items": events}) if url.startswith(S.EVENTS_URL) else (404, {})

    def tearDown(self):
        S.HTTP, S.RESEARCH_AUTOSTART = self.old
        with S.RQ_LOCK:
            S.RQ.update(queue=[], pending=set(), running=set(), errors={}, mentions={})

    def test_live_notes_route_has_the_write_guards(self):
        origin = "http://localhost:%d" % S.PORT
        body = {"callId": "nw1", "segment": "seg123abc", "offset": 0, "text": "Harborline Labs called. They're a partner.", "final": True}
        self.assertEqual(self.req("POST", "/api/mentions/live", body)[0], 403)
        self.assertEqual(self.req("POST", "/api/mentions/live", body, {"X-OVERTURE": "1", "Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.req("POST", "/api/mentions/live", dict(body, text="x" * 30_000), {"X-OVERTURE": "1", "Origin": origin})[0], 413)
        st, txt, _ = self.req("POST", "/api/mentions/live", body, {"X-OVERTURE": "1", "Origin": origin})
        self.assertEqual(st, 200, txt)
        o = json.loads(txt)["orgs"][0]
        self.assertEqual((o["name"], o["status"], o["relation"]["type"]), ("Harborline Labs", "said", "partner"))
        st, txt, _ = self.req("GET", "/api/mentions?callId=nw1")
        self.assertIn("graph", json.loads(txt))
        self.assertEqual(self.req("HEAD", "/api/mentions/live")[0], 404)


# ---------------------------------------------------------------- Settings page (GET/PUT /api/settings) ----------------------------------------------------------------

def _js_json(path, start, end):
    t = Path(path).read_text(encoding="utf-8")
    return json.loads(t[t.index(start) + len(start): t.index(end, t.index(start))])


class SettingsStore(Fresh):
    def test_defaults_and_the_page_copy_match(self):
        s = S.effective_settings(S.empty_records())
        self.assertEqual(s, S.default_settings())
        self.assertEqual(s["research"]["aiShare"], "notes")  # call notes may go to Claude, as before
        for k in S.LEGACY_SETTINGS:  # the three Data-page switches stay off by default
            self.assertIs(s["research"][k], False)
        here = Path(S.HERE)
        self.assertEqual(_js_json(here / "settings.js", "/*defaults*/", "/*end*/"), S.default_settings())
        self.assertEqual(_js_json(here / "settings-page.js", "/*blocked*/", "/*end*/"), S.BLOCKED_DOMAINS)

    def test_partial_groups_merge_and_persist(self):
        out = S.save_settings({"brief": {"tone": "warm"}})
        self.assertEqual(out["brief"]["tone"], "warm")
        self.assertEqual(out["brief"]["length"], "full")  # the rest of the group kept
        S.save_settings({"brief": {"length": "short"}, "appearance": {"theme": "dark"}})
        s = S.effective_settings(S.load_records())
        self.assertEqual((s["brief"]["tone"], s["brief"]["length"], s["appearance"]["theme"]), ("warm", "short", "dark"))
        order = [{"id": i, "on": i != "rivals"} for i in reversed(S.BRIEF_SECTIONS)]
        S.save_settings({"brief": {"sections": order}})
        self.assertEqual(S.effective_settings(S.load_records())["brief"]["sections"], order)
        rec = S.load_records()["settings"]
        self.assertEqual(rec["brief"]["tone"], "warm")  # stored in records.settings

    def test_validation(self):
        bad = [
            {}, [], {"nope": {}}, {"brief": {"tone": "loud"}}, {"brief": {"extra": 1}}, {"brief": "warm"},
            {"brief": {"sections": [{"id": "opener", "on": True}]}},                                   # not every section
            {"brief": {"sections": [{"id": "opener", "on": True}] * len(S.BRIEF_SECTIONS)}},           # one twice
            {"brief": {"sections": [{"id": s, "on": "yes"} for s in S.BRIEF_SECTIONS]}},
            {"priorities": {"hot": 0}}, {"priorities": {"hot": True}}, {"priorities": {"warm": 9, "hot": 5}},
            {"priorities": {"rules": {"engineers": {"min": -1}}}}, {"priorities": {"targets": ["x"] * 101}},
            {"priorities": {"targets": ["y" * 121]}}, {"priorities": {"targets": [3]}},
            {"alerts": {"quiet": {"from": "25:00"}}}, {"alerts": {"security": "some"}}, {"alerts": {"signals": {"weather": True}}},
            {"mentions": {"mapRelations": ["people", "friends"]}}, {"mentions": {"keepDays": 0}},
            {"research": {"blocked": ["not a site"]}}, {"research": {"blocked": ["a.com"] * 51}}, {"research": {"web": 1}},
            {"followup": {"templates": {"intro": {"subject": "x" * 201}}}}, {"followup": {"templates": {"webinar": {}}}},
            {"appearance": {"accent": "purple"}}, {"panel": {"density": "tiny"}},
        ]
        for body in bad:
            with self.assertRaises(S.Invalid, msg=str(body)[:80]):
                S.save_settings(body)
        self.assertEqual(S.effective_settings(S.load_records()), S.default_settings())  # nothing was saved
        with self.assertRaisesRegex(S.Invalid, "too big"):  # checked before anything else
            S.save_settings({"brief": {"tone": "x" * 70000}})

    def test_lists_are_cleaned(self):
        out = S.save_settings({"research": {"blocked": ["https://www.People-Site.com/search?q=1", "people-site.com", "data.example.org"]},
                               "priorities": {"targets": ["Northwind Freight", "northwind freight", " Quillstack "]}})
        self.assertEqual(out["research"]["blocked"], ["people-site.com", "data.example.org"])
        self.assertEqual(out["priorities"]["targets"], ["Northwind Freight", "Quillstack"])

    def test_old_switches_live_in_the_research_group(self):
        S.save_settings({"research": {"gongTranscripts": True}})
        r = S.load_records()
        self.assertIs(r["settings"]["gongTranscripts"], True)        # top-level, where the transcripts code reads it
        self.assertNotIn("gongTranscripts", r["settings"]["research"])
        self.assertTrue(S.setting_on(r, "gongTranscripts"))
        S.write_records("settings", {"gongInAI": True})                # the older endpoint still works and shows here
        self.assertIs(S.effective_settings(S.load_records())["research"]["gongInAI"], True)
        # "What may go to AI" and "Use transcripts in AI answers" are one choice
        out = S.save_settings({"research": {"aiShare": "transcripts"}})
        self.assertIs(out["research"]["transcriptsInAI"], True)
        self.assertTrue(S.setting_on(S.load_records(), "transcriptsInAI"))
        out = S.save_settings({"research": {"transcriptsInAI": False}})
        self.assertEqual(out["research"]["aiShare"], "notes")
        out = S.save_settings({"research": {"aiShare": "titles"}})
        self.assertIs(out["research"]["transcriptsInAI"], False)
        S.write_records("settings", {"transcriptsInAI": True})
        self.assertEqual(S.effective_settings(S.load_records())["research"]["aiShare"], "transcripts")

    def test_a_broken_stored_group_falls_back_to_its_defaults(self):
        r = S.load_records()
        r["settings"]["brief"] = {"tone": "shouty"}
        r["settings"]["alerts"] = {"delivery": "digest"}
        S.save_json(S.records_path(), r)
        s = S.effective_settings(S.load_records())
        self.assertEqual(s["brief"], S.default_settings()["brief"])
        self.assertEqual(s["alerts"]["delivery"], "digest")


class SettingsHelpers(Fresh):
    def job_change_events(self):
        past = ev("p1", "2026-08-03T15:00:00+00:00", 30, [SELF, att("dana.li@lumenair.com", "Dana Li")])
        upcoming = ev("u1", "2026-10-21T18:00:00+00:00", 30, [SELF, att("dana.li@quillstack.ai", "Dana Li")], summary="Intro: Quillstack")
        return [past, upcoming]

    def test_alert_rules_turn_server_alerts_off(self):
        kinds = lambda rec: {w["kind"] for w in S.build_live(self.job_change_events(), ME, rec, NOW)["watch"]}  # noqa: E731
        self.assertEqual(kinds(S.empty_records()), {"Job change", "First meeting"})
        S.save_settings({"alerts": {"signals": {"jobChanges": False}}})
        self.assertEqual(kinds(S.load_records()), {"First meeting"})
        S.save_settings({"alerts": {"signals": {"jobChanges": True, "newInvitees": False}}})
        self.assertEqual(kinds(S.load_records()), {"Job change"})
        live = S.build_live(self.job_change_events(), ME, S.load_records(), NOW)
        self.assertIs(live["appSettings"]["alerts"]["signals"]["newInvitees"], False)  # the page gets every setting
        self.assertEqual(set(live["settings"]), set(S.LEGACY_SETTINGS))

    def test_hubspot_stage_changes(self):
        cos = {"Acme": {"status": "Open deal: Discovery", "src": {"status": "HubSpot"}}, "Mine": {"status": "Customer"}}
        alerts, seen = S.stage_alerts(cos, {}, NOW, [{"company": "Acme", "id": "c1"}])
        self.assertEqual(alerts, [])                                  # first sight: only remembered
        self.assertEqual(seen, {"Acme": {"status": "Open deal: Discovery"}})
        cos["Acme"]["status"] = "Open deal: Contract sent"
        alerts, seen = S.stage_alerts(cos, seen, NOW, [{"company": "Acme", "id": "c1"}])
        self.assertEqual(len(alerts), 1)
        self.assertEqual((alerts[0]["kind"], alerts[0]["callId"], alerts[0]["title"]), ("Stage change", "c1", "Acme moved to Open deal: Contract sent"))
        self.assertIn("Open deal: Discovery", alerts[0]["text"])
        alerts, _ = S.stage_alerts(cos, seen, NOW + timedelta(days=8), [])
        self.assertEqual(alerts, [])                                  # a week later it is old news
        self.assertFalse(S.alert_on("Stage change", S.effective_settings({"settings": {"alerts": {"signals": {"hubspotStages": False}}}})))
        self.assertTrue(S.alert_on("Come back", S.effective_settings({"settings": {"alerts": {"signals": {s: False for s in S.ALERT_SIGNALS}}}})))

    def test_what_may_go_to_ai(self):
        facts = {"people": [{"name": "Ann Lee", "title": "CTO", "note": "Hates long decks"}], "company": {"status": "New lead", "notes": "Budget in Q1", "history": [1]},
                 "call": {"title": "Acme: pricing"}}
        self.assertEqual(S.brief_facts(facts, S.load_records()), facts)  # default: notes may go
        S.save_settings({"research": {"aiShare": "titles"}})
        out = S.brief_facts(facts, S.load_records())
        self.assertEqual(out["people"], [{"name": "Ann Lee", "title": "CTO"}])
        self.assertEqual(out["company"], {"status": "New lead"})
        self.assertEqual(facts["people"][0]["note"], "Hates long decks")  # the page's copy is untouched
        live = {"invites": [{"id": "c1", "afterNotes": "secret plan", "title": "t"}], "people": {"a@acme.com": {"title": "CTO", "note": "n"}},
                "companies": {"Acme": {"status": "New lead", "notes": "n", "history": []}}}
        recs = S.load_records()
        recs["people"] = {"a@acme.com": {"title": "CTO", "note": "n"}}
        l2, r2 = S.ai_trim(live, recs)
        self.assertNotIn("afterNotes", l2["invites"][0])
        self.assertEqual(l2["people"]["a@acme.com"], {"title": "CTO"})
        self.assertEqual(r2["people"]["a@acme.com"], {"title": "CTO"})
        self.assertNotIn("notes", l2["companies"]["Acme"])
        ctx = json.loads(S.ask_context("what next?", "c1", dict(l2, invites=[{"id": "c1", "title": "t", "when": "w", "company": "Acme", "notes": "", "attendees": []}]), r2))
        self.assertEqual(ctx["thisCall"]["callNotes"], "")

    def test_blocked_sites_reach_the_search_tool(self):
        self.assertFalse(S.blocked_url("https://people-site.com/ann"))
        S.save_settings({"research": {"blocked": ["people-site.com"]}})
        self.assertTrue(S.blocked_url("https://people-site.com/ann"))
        self.assertTrue(S.blocked_url("https://eu.people-site.com/ann"))
        self.assertTrue(S.blocked_url("https://www.zoominfo.com/p/x"))  # the built-in list still applies
        tool = S.search_request("sys", "user")["tools"][0]
        self.assertIn("people-site.com", tool["blocked_domains"])
        self.assertIn("zoominfo.com", tool["blocked_domains"])

    def test_mention_settings_helper(self):
        self.assertEqual(S.mention_settings(S.load_records()), {"autoLookup": True, "autoAdd": "single", "mapRelations": list(S.MAP_RELATIONS), "keepDays": 90})
        S.save_settings({"mentions": {"autoLookup": False, "autoAdd": "likely", "keepDays": 30, "mapRelations": ["vendor", "people"]}})
        m = S.mention_settings()
        self.assertEqual((m["autoLookup"], m["autoAdd"], m["keepDays"]), (False, "likely", 30))
        self.assertEqual(m["mapRelations"], ["people", "vendor"])  # kept in the menu's order

    def test_sources_can_be_turned_off(self):
        self.assertTrue(S.source_on("hubspot"))
        S.save_settings({"research": {"hubspot": False, "web": False}})
        self.assertFalse(S.source_on("hubspot"))
        self.assertFalse(S.source_on("web"))
        self.assertTrue(S.source_on("gong"))


class SettingsCrm(Fresh, CrmFakes):
    def setUp(self):
        super().setUp()
        self.crm_setup()

    def tearDown(self):
        self.crm_teardown()

    def test_hubspot_off_means_no_hubspot_requests(self):
        self.connect(hubspot=True, gong=False)
        inv = [{"id": "e1", "company": "Acme", "domain": "acme.com", "attendees": [{"email": "ann.lee@acme.com", "name": "Ann Lee"}]}]
        S.save_settings({"research": {"hubspot": False}})
        out = S.crm_fetch(inv, "chris@spotify.com", S.load_records(), NOW)
        self.assertEqual(self.api.calls, [])
        self.assertEqual((out["contacts"], out["companies"]), ({}, {}))
        S.save_settings({"research": {"hubspot": True}})
        S.crm_fetch(inv, "chris@spotify.com", S.load_records(), NOW)
        self.assertTrue(any("hubapi.com" in c["url"] for c in self.api.calls))


class SettingsRoutes(ServerBase):
    def test_get_and_put_with_the_guards(self):
        origin = "http://localhost:%d" % S.PORT
        ok = {"X-OVERTURE": "1", "Origin": origin}
        st, txt, _ = self.req("GET", "/api/settings")
        self.assertEqual(st, 200)
        self.assertEqual(json.loads(txt)["settings"], S.default_settings())
        self.assertEqual(self.req("GET", "/api/settings", headers={"Sec-Fetch-Site": "cross-site"})[0], 403)
        self.assertEqual(self.req("GET", "/api/settings", headers={"Host": "evil.example"})[0], 403)
        body = {"appearance": {"theme": "light"}}
        self.assertEqual(self.req("PUT", "/api/settings", body)[0], 403)                                       # no X-OVERTURE
        self.assertEqual(self.req("PUT", "/api/settings", body, {"X-OVERTURE": "1", "Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.req("PUT", "/api/settings", body, dict(ok, **{"Content-Type": "text/plain"}))[0], 403)
        self.assertEqual(self.req("PUT", "/api/settings", {"appearance": {"theme": "neon"}}, ok)[0], 400)
        self.assertEqual(self.req("PUT", "/api/settings", {"followup": {"templates": {"intro": {"body": "x" * 70_000}}}}, ok)[0], 413)
        self.assertEqual(S.effective_settings(S.load_records())["appearance"]["theme"], "dark")  # nothing saved yet: dark is the default
        st, txt, _ = self.req("PUT", "/api/settings", body, ok)
        self.assertEqual(st, 200, txt)
        self.assertEqual(json.loads(txt)["settings"]["appearance"]["theme"], "light")
        self.assertEqual(json.loads(self.req("GET", "/api/settings")[1])["settings"]["appearance"]["theme"], "light")
        self.assertEqual(self.req("HEAD", "/api/settings")[0], 404)

    def test_web_research_off_refuses_a_lookup(self):
        S.save_settings({"research": {"web": False}})
        st, txt, _ = self.req("POST", "/api/research", {"email": "ann.lee@acme.com"}, {"X-OVERTURE": "1", "Origin": "http://localhost:%d" % S.PORT})
        self.assertEqual(st, 403)
        self.assertIn("Web research is off", json.loads(txt)["error"])


# ---------------------------------------------------------------- Settings > Mentions in the mentions code ----------------------------------------------------------------

def mention_setup(t):
    """MentionFlow's setUp for the classes below (a connected calendar with the Northwind calls, a fake Claude, no worker)."""
    Fresh.setUp(t)
    with S.RQ_LOCK:
        S.RQ.update(queue=[], pending=set(), running=set(), errors={}, meta={}, mentions={})
    t.old = (S.research_client, S.RESEARCH_AUTOSTART, S.HTTP, S.claude_text)
    S.RESEARCH_AUTOSTART = False
    os.environ["ANTHROPIC_API_KEY"] = "test-key"
    S.save_json(S.token_path(), {"access_token": "AT-x", "refresh_token": "RT-x", "expires_at": time.time() + 3000, "email": "chris@spotify.com", "name": "Chris Park"})
    t.events = northwind_events(datetime.now(timezone.utc))
    S.HTTP = lambda method, url, form=None, headers=None, timeout=15: (200, {"items": t.events}) if url.startswith(S.EVENTS_URL) else (404, {})


def mention_teardown(t):
    S.research_client, S.RESEARCH_AUTOSTART, S.HTTP, S.claude_text = t.old
    os.environ.pop("ANTHROPIC_API_KEY", None)


class MentionSettingsHooks(Fresh):
    """mention_settings(): automatic look-up, the auto-add rule, quote retention; and web research off stopping every lookup."""

    def setUp(self):
        mention_setup(self)

    def tearDown(self):
        mention_teardown(self)

    fake, post, by = MentionFlow.fake, MentionFlow.post, MentionFlow.by

    def queued(self):
        with S.RQ_LOCK:
            return [k for k, _ in S.RQ["queue"]]

    def test_automatic_look_up_off_refuses_notes_as_you_type_and_holds_back_live_lookups(self):
        f = self.fake()
        S.save_settings({"mentions": {"autoLookup": False}})
        st, body = S.mentions_live({"callId": "nw1", "segment": "seg123abc", "offset": 0, "text": "Maria Gomez from security called.", "final": True})
        self.assertEqual(st, 403)
        self.assertIn("Automatic look-up is off", body["error"])
        self.assertNotIn("nw1", S.load_records().get("mentions") or {})  # nothing read
        # found while the call runs (Meetily): listed, not looked up, with a way to look it up by hand
        ctx = S._call_context("nw1", S.load_records(), datetime.now(timezone.utc))[1]
        found, orgs = S.find_all(S.parse_transcript(HARBOR_T + " Maria Gomez from security called."), ctx)
        S.save_mentions("nw1", ctx, found, "meetily", orgs, bump=False)
        body = S.mentions_body("nw1", requeue=False)
        self.assertEqual({i["status"] for i in body["items"]} | {o["status"] for o in body["orgs"]}, {"nokey"})
        self.assertTrue(all(S.AUTO_OFF_NOTE == x["note"] for x in body["items"] + body["orgs"]))
        self.assertEqual(self.queued(), [])
        self.assertIsNone(S.research_step())
        self.assertEqual(f.calls, [])
        # an uploaded transcript (After the call) is your own action: still looked up
        self.post()
        self.assertTrue(self.queued())
        # Look up on the web by hand works for the held-back one
        mid = self.by(body)["Maria Gomez"]["id"]
        self.assertEqual(S.mention_action({"callId": "nw1", "id": mid, "action": "again"})[0], 200)
        self.assertIn(S.mention_key("nw1", mid), self.queued())

    def test_auto_add_rule_single_vs_likely(self):
        two = [cand("Tom Hughes"), cand("Tom Baker", "Security Analyst", "https://northwind-freight.com/team/y")]
        self.fake(mention_reply(two, ["https://northwind-freight.com/team/x", "https://northwind-freight.com/team/y"]))
        self.post(TXT_MEET.replace("Dana in legal will read it.", "Tom from security asked about SSO."), filename="m.txt")
        while S.research_step():
            pass
        tom = self.by(S.mentions_body("nw1", requeue=False))["Tom"]
        self.assertEqual((tom["status"], tom["connected"]), ("pick", False))  # only clear matches: not on the map
        self.assertEqual([c for c in S.load_records()["connections"].values() if c["kind"] == "person"], [])
        S.save_settings({"mentions": {"autoAdd": "likely"}})
        with S.RECORDS_LOCK:  # the map follows the setting on the next change
            r = S.load_records()
            S.sync_connections(r, "nw1")
            S.save_json(S.records_path(), r)
        tom = self.by(S.mentions_body("nw1", requeue=False))["Tom"]
        self.assertTrue(tom["connected"])
        conn = next(c for c in S.load_records()["connections"].values() if c["kind"] == "person")
        self.assertEqual((conn["name"], conn["likely"]), ("Tom Hughes", True))  # the most likely one, marked
        nodes, edges = S.connections_graph(S.load_records(), {"nw1"})
        node = next(n for n in nodes if n["type"] == "person")
        self.assertTrue(node["likely"])
        self.assertTrue(node["sub"].startswith("Likely · "))
        self.assertEqual(edges[0]["explain"]["found"]["how"], "Likely, not confirmed")
        S.save_settings({"mentions": {"autoAdd": "single"}})
        with S.RECORDS_LOCK:
            r = S.load_records()
            S.sync_connections(r, "nw1")
            S.save_json(S.records_path(), r)
        self.assertEqual([c for c in S.load_records()["connections"].values() if c["kind"] == "person"], [])

    def test_quotes_older_than_keep_days_are_dropped(self):
        self.fake()
        self.post(VENDOR_T + " Tom Hughes runs security.", filename="v.txt")
        with S.RECORDS_LOCK:
            r = S.load_records()
            old = (datetime.now(timezone.utc) - timedelta(days=40)).replace(microsecond=0).isoformat()
            for it in r["mentions"]["nw1"]["orgs"]:
                it["at"] = old  # Brightwave came up 40 days ago; Tom today
            S.save_json(S.records_path(), r)
        S.save_settings({"mentions": {"keepDays": 30}})
        body = S.mentions_body("nw1")
        bw = next(o for o in body["orgs"] if o["name"] == "Brightwave Systems")
        self.assertEqual((bw["quote"]["text"], bw["relation"]["said"]), ("", ""))
        self.assertEqual(bw["relation"]["type"], "vendor")  # the relation stays
        self.assertIsNone(bw["explain"]["said"])
        tom = next(i for i in body["items"] if i["name"] == "Tom Hughes")
        self.assertTrue(tom["quote"]["text"])  # newer than 30 days: kept
        saved = (Path(TMP) / "records.json").read_text(encoding="utf-8")
        self.assertNotIn("go through Brightwave", saved)
        self.assertNotIn("vendor for logging", saved)
        self.assertIn("runs security", saved)

    def test_old_quotes_are_dropped_before_the_people_map_and_when_keep_days_is_lowered(self):
        self.fake()
        saved = lambda: (Path(TMP) / "records.json").read_text(encoding="utf-8")

        def age(name, days):
            with S.RECORDS_LOCK:
                r = S.load_records()
                for it in r["mentions"]["nw1"]["orgs"]:
                    if it["name"] == name:
                        it["at"] = (datetime.now(timezone.utc) - timedelta(days=days)).replace(microsecond=0).isoformat()
                S.save_json(S.records_path(), r)
        self.post(VENDOR_T, filename="v.txt")
        S.save_settings({"mentions": {"keepDays": 7}})
        age("Brightwave Systems", 30)  # it ages past "keep quotes for" with no new transcript and no GET /api/mentions
        js = S.live_script()
        self.assertIn("Brightwave Systems", js)  # still on the People map
        self.assertNotIn("go through Brightwave", js)
        self.assertNotIn("vendor for logging", js)
        self.assertNotIn("go through Brightwave", saved())
        S.save_settings({"mentions": {"keepDays": 90}})
        self.post(HARBOR_T, filename="h.txt")
        age("Harborline Labs", 30)
        self.assertIn("keeps asking about the pilot", saved())
        S.save_settings({"mentions": {"keepDays": 7}})  # lowered: dropped at once
        self.assertNotIn("keeps asking about the pilot", saved())

    def test_automatic_look_up_turned_off_holds_back_lookups_already_queued(self):
        f = self.fake(mention_reply([]))
        ctx = S._call_context("nw1", S.load_records(), datetime.now(timezone.utc))[1]
        found, orgs = S.find_all(S.parse_transcript(HARBOR_T + " Maria Gomez from security called."), ctx)
        block, new, go, wait, new_o, unqueue = S.save_mentions("nw1", ctx, found, "meetily", orgs, bump=False)  # heard through Meetily
        S._queue_found("nw1", block, new, go, wait)
        S.promote_waiting(time.time() + 60)
        maria = self.by(S.mentions_body("nw1", requeue=False))["Maria Gomez"]
        oid = next(o["id"] for o in S.mentions_body("nw1", requeue=False)["orgs"] if o["name"] == "Harborline Labs")
        self.assertEqual(set(self.queued()), {S.mention_key("nw1", maria["id"]), "org:nw1:" + oid})
        S.save_settings({"mentions": {"autoLookup": False}})  # while they wait
        while S.research_step():
            pass
        self.assertEqual(f.calls, [])
        body = S.mentions_body("nw1", requeue=False)
        self.assertEqual({(x["status"], x["note"]) for x in body["items"] + body["orgs"] if x["name"] in ("Maria Gomez", "Harborline Labs")},
                         {("nokey", S.AUTO_OFF_NOTE)})
        # left "Looking up…" by a restart: not queued again, and shown as not looked up
        with S.RECORDS_LOCK:
            r = S.load_records()
            for it in r["mentions"]["nw1"]["items"] + r["mentions"]["nw1"]["orgs"]:
                if it["status"] == "nokey":
                    it["status"] = "pending"
            S.save_json(S.records_path(), r)
        body = S.mentions_body("nw1")
        self.assertEqual(self.queued(), [])
        self.assertNotIn("pending", {x["status"] for x in body["items"] + body["orgs"]})
        # Look up on the web (your own action) still goes
        self.assertEqual(S.mention_action({"callId": "nw1", "id": maria["id"], "action": "again"})[0], 200)
        while S.research_step():
            pass
        self.assertEqual(len(f.calls), 1)
        self.assertIn("Maria Gomez", f.calls[0]["messages"][0]["content"])

    def test_web_research_off_stops_people_and_company_lookups(self):
        f = self.fake(org_answer("partner"))
        S.save_settings({"research": {"web": False}})
        body = self.post(HARBOR_T + " Maria Gomez from security called.", filename="h.txt")
        self.assertEqual(self.queued(), [])
        self.assertEqual({x["status"] for x in body["items"] + body["orgs"] if x["status"] not in ("pick", "known")}, {"nokey"})
        self.assertTrue(any(x["note"] == S.WEB_OFF_NOTE for x in body["items"] + body["orgs"]))
        mid = self.by(body)["Maria Gomez"]["id"]
        st, out = S.mention_action({"callId": "nw1", "id": mid, "action": "again"})
        self.assertEqual(st, 400)
        self.assertIn("Web research is off", out["error"])
        oid = next(o["id"] for o in body["orgs"] if o["name"] == "Harborline Labs")
        self.assertEqual(S.mention_action({"callId": "nw1", "id": oid, "action": "again"})[0], 400)
        # one already queued when web research is turned off: the worker never sends it
        S.save_settings({"research": {"web": True}})
        self.assertEqual(S.mention_action({"callId": "nw1", "id": oid, "action": "again"})[0], 200)
        S.save_settings({"research": {"web": False}})
        while S.research_step():
            pass
        self.assertEqual(f.calls, [])
        o = next(o for o in S.mentions_body("nw1", requeue=False)["orgs"] if o["id"] == oid)
        self.assertEqual((o["status"], o["note"]), ("nokey", S.WEB_OFF_NOTE))
        # pending ones left from before (a restart) show "Not looked up" instead of spinning
        with S.RECORDS_LOCK:
            r = S.load_records()
            r["mentions"]["nw1"]["orgs"][0]["status"] = "pending"
            S.save_json(S.records_path(), r)
        self.assertNotIn("pending", {o["status"] for o in S.mentions_body("nw1")["orgs"]})


# ---------------------------------------------------------------- click-to-explain: sourced explanations ----------------------------------------------------------------

HARBOR_EXPLAINED = {
    "relation": "partner", "detail": "", "confidence": "medium",
    "explanation": [
        {"text": "Harborline Labs builds route planning on Northwind Freight's shipment data.", "sources": [1]},
        {"text": "They announced the partnership for Northwind's tracking product in 2024.", "sources": [2]},
        {"text": "Harborline is also Northwind's biggest customer.", "sources": [3]},  # its source was never in the search results
        {"text": "They are close friends.", "sources": []},                         # no source at all
        "A bare sentence with no sources."],
    "since": {"text": "2024", "sources": [2]},
    "sources": [
        {"url": "https://harborline.example/partners", "label": "Partners page", "date": "2026-08",
         "quote": "Northwind Freight: our route-planning tools run on Northwind's live shipment data, updated every few minutes for every lane and every carrier we plan with across North America and Europe."},
        {"url": "https://news.example.com/2024/harborline-northwind", "label": "Example News", "date": "June 2024", "quote": "“Harborline and Northwind announced a partnership.”"},
        {"url": "https://never-searched.example.com/x", "label": "Made up", "quote": "Harborline buys from Northwind."}]}
HARBOR_URLS = ["https://harborline.example/partners", "https://news.example.com/2024/harborline-northwind"]


class Explanations(Fresh):
    def setUp(self):
        mention_setup(self)

    def tearDown(self):
        mention_teardown(self)

    fake, post, by = MentionFlow.fake, MentionFlow.post, MentionFlow.by

    def test_a_company_said_on_a_call_gets_a_sourced_definition_even_with_no_relation(self):
        seen = {S.url_key(u): {"cited": [], "age": ""} for u in HARBOR_URLS}
        about = {"text": "Harborline is a freight software company that builds routing tools for shippers.", "sources": [1]}
        rel = S.clean_org_relation(dict(HARBOR_EXPLAINED, relation="unknown", about=about), seen)
        self.assertEqual((rel["type"], rel["about"]["text"]), ("unknown", about["text"]))
        self.assertTrue(rel["sources"])
        found = S.clean_org_relation(dict(HARBOR_EXPLAINED, about=about), seen)
        self.assertEqual(found["about"]["text"], about["text"])
        unsourced = S.clean_org_relation(dict(HARBOR_EXPLAINED, about={"text": about["text"], "sources": [9]}), seen)
        self.assertNotIn("about", unsourced)

    def test_only_sourced_sentences_short_quotes_and_dates_are_kept(self):
        # what the search itself showed of each page: the words of its citations and the page's date (page_age, made YYYY-MM-DD)
        seen = {S.url_key(HARBOR_URLS[0]): {"cited": [HARBOR_EXPLAINED["sources"][0]["quote"]], "age": "2026-08"},
                S.url_key(HARBOR_URLS[1]): {"cited": ["Harborline and Northwind announced a partnership."], "age": "June 2024"}}
        rel = S.clean_org_relation(HARBOR_EXPLAINED, seen)
        self.assertEqual([s["url"] for s in rel["sources"]], HARBOR_URLS)  # the unsearched page is dropped
        self.assertEqual([e["text"] for e in rel["explanation"]], [HARBOR_EXPLAINED["explanation"][0]["text"], HARBOR_EXPLAINED["explanation"][1]["text"]])
        self.assertEqual([e["sources"] for e in rel["explanation"]], [[0], [1]])
        self.assertEqual(rel["since"], {"text": "2024", "sources": [1]})
        q0 = rel["sources"][0]["quote"]
        self.assertLessEqual(len(q0.rstrip("…").split()), 25)
        self.assertTrue(q0.endswith("…"))
        self.assertEqual(rel["sources"][1]["quote"], "Harborline and Northwind announced a partnership.")  # quote marks trimmed
        self.assertEqual((rel["sources"][0]["date"], rel["sources"][1]["date"]), ("2026-08", ""))  # "June 2024" isn't a date Overture shows
        bare = S.clean_org_relation(HARBOR_EXPLAINED, {S.url_key(u) for u in HARBOR_URLS})  # the search showed nothing of the pages
        self.assertEqual([(s["quote"], s["date"]) for s in bare["sources"]], [("", ""), ("", "")])  # Claude's quote and date alone aren't shown
        none = S.clean_org_relation(dict(HARBOR_EXPLAINED, explanation=[{"text": "x", "sources": [9]}], since={"text": "2020", "sources": [3]}),
                                    {S.url_key(u) for u in HARBOR_URLS})
        self.assertEqual((none["explanation"], none["since"]), ([], None))
        leak = S.clean_org_relation(dict(HARBOR_EXPLAINED, explanation=[{"text": "Call jane@harborline.example or +1 415 555 0100.", "sources": [1]}]),
                                    {S.url_key(u) for u in HARBOR_URLS})
        self.assertEqual(leak["explanation"], [])

    def test_web_lookup_fills_the_card_and_the_map_line(self):
        f = self.fake(reply(HARBOR_EXPLAINED, HARBOR_URLS))
        self.post(HARBOR_T, filename="h.txt")
        while S.research_step():
            pass
        self.assertIn('"explanation"', f.calls[0]["system"])  # the prompt asks for sourced sentences
        self.assertNotIn("keeps asking", json.dumps(f.calls, default=str))  # the sentence said on the call never goes
        o = next(o for o in S.mentions_body("nw1", requeue=False)["orgs"] if o["name"] == "Harborline Labs")
        x = o["explain"]
        self.assertEqual((x["kind"], x["type"], x["typeLabel"], x["confidence"]), ("company", "partner", "Partner", "medium"))
        self.assertEqual(len(x["explanation"]), 2)
        self.assertEqual(x["since"]["text"], "2024")
        self.assertEqual([e["url"] for e in x["evidence"]], HARBOR_URLS)
        self.assertEqual((x["found"]["how"], x["found"]["call"], x["found"]["via"]), ("Found on the web", "Northwind Freight", "your transcript"))
        self.assertEqual(x["found"]["title"], "Northwind: pilot")
        self.assertEqual(x["mention"]["text"], "Harborline Labs keeps asking about the pilot too.")
        self.assertIsNone(x["said"])
        _, edges = S.connections_graph(S.load_records(), {"nw1"})
        self.assertEqual(edges[0]["explain"], x)  # the People map's line explains itself the same way

    def test_said_on_the_call_and_old_results_without_explanations_still_render(self):
        self.fake()
        body = self.post(VENDOR_T, filename="v.txt")
        x = next(o for o in body["orgs"] if o["name"] == "Brightwave Systems")["explain"]
        self.assertEqual((x["typeLabel"], x["found"]["how"], x["explanation"], x["evidence"]), ("Vendor or supplier", "Said on the call", [], []))
        self.assertEqual((x["said"]["text"], x["said"]["speaker"], x["said"]["time"]), ("They're our vendor for logging", "Marcus Bell", ""))
        with S.RECORDS_LOCK:  # a relation saved before explanations existed
            r = S.load_records()
            r["mentions"]["nw1"]["orgs"].append({"id": "0123456789ab", "key": "o:old", "name": "Oldco", "status": "found", "source": "upload", "at": S.now_iso(),
                                                 "relation": {"type": "competitor", "source": "web", "confidence": "high", "sources": [{"url": "https://oldco.example/about", "label": "About"}]}})
            S.save_json(S.records_path(), r)
        old = next(o for o in S.mentions_body("nw1", requeue=False)["orgs"] if o["name"] == "Oldco")["explain"]
        self.assertEqual((old["typeLabel"], old["explanation"], old["since"]), ("Competitor", [], None))
        self.assertEqual(old["evidence"], [{"url": "https://oldco.example/about", "label": "About", "date": "", "quote": ""}])

    def test_people_get_sourced_explanations_too(self):
        c = cand("Maria Gomez")
        c["explanation"] = [{"text": "Maria Gomez leads security engineering at Northwind Freight.", "sources": [1]}, {"text": "Unsourced.", "sources": [2]}]
        c["sources"][0].update(date="2025-11-02", quote="Maria Gomez, Security Engineering Manager")
        team = "https://northwind-freight.com/team/x"
        self.fake(mention_reply([c], [team], cited={team: "Maria Gomez, Security Engineering Manager, leads the team that ..."}, ages={team: "November 2, 2025"}),
                  mention_reply([]), mention_reply([]))
        self.post()
        while S.research_step():
            pass
        maria = self.by(S.mentions_body("nw1", requeue=False))["Maria Gomez"]
        self.assertEqual([e["text"] for e in maria["person"]["explanation"]], ["Maria Gomez leads security engineering at Northwind Freight."])
        x = maria["explain"]
        self.assertEqual((x["kind"], x["typeLabel"], x["title"], x["found"]["how"]), ("person", "Employee", "Security Engineering Manager", "Found on the web"))
        self.assertEqual(x["evidence"][0], {"url": "https://northwind-freight.com/team/x", "label": "Team page", "date": "2025-11-02", "quote": "Maria Gomez, Security Engineering Manager"})
        self.assertIn('"explanation"', S.MENTION_SYSTEM)

    def test_quotes_only_in_the_words_the_search_showed_and_dates_only_from_the_search(self):
        page0 = ("Northwind Freight: our route-planning tools run on Northwind’s live shipment data, updated every few minutes for every lane "
                 "and every carrier we plan with across North America and Europe.")
        self.fake(reply(HARBOR_EXPLAINED, HARBOR_URLS, cited={HARBOR_URLS[0]: page0, HARBOR_URLS[1]: "Harborline and Northwind announced a new partnership for tracking."},
                        ages={HARBOR_URLS[0]: "August 14, 2026", HARBOR_URLS[1]: "3 days ago"}))
        self.post(HARBOR_T, filename="h.txt")
        while S.research_step():
            pass
        x = next(o for o in S.mentions_body("nw1", requeue=False)["orgs"] if o["name"] == "Harborline Labs")["explain"]
        self.assertTrue(x["evidence"][0]["quote"].startswith("Northwind Freight: our route-planning tools run on Northwind's live shipment data"))
        self.assertEqual(x["evidence"][1]["quote"], "")  # "announced a partnership": not the page's words
        self.assertEqual([e["date"] for e in x["evidence"]], ["2026-08-14", ""])  # the search's dates, never Claude's ("2026-08", "June 2024")
        self.assertEqual([S.page_day(v) for v in ("April 30, 2025", "Apr 3, 2025", "2025-04-30T10:00:00Z", "3 days ago", "", None)],
                         ["2025-04-30", "2025-04-03", "2025-04-30", "", "", ""])

    def test_a_site_blocked_later_never_moves_a_sentence_onto_another_source(self):
        self.fake()
        self.post(HARBOR_T, filename="h.txt")
        with S.RECORDS_LOCK:
            r = S.load_records()
            o = next(o for o in r["mentions"]["nw1"]["orgs"] if o["name"] == "Harborline Labs")
            o.update(status="found", relation={"type": "partner", "source": "web", "confidence": "high", "side": "them", "detail": "",
                                               "sources": [{"url": "https://example-a.com/news", "label": "A news"}, {"url": "https://example-b.com/news", "label": "B news"}],
                                               "explanation": [{"text": "A news says this.", "sources": [0]}, {"text": "B news says that.", "sources": [1]}],
                                               "since": {"text": "2023", "sources": [0]}})
            S.sync_connections(r, "nw1")
            S.save_json(S.records_path(), r)
        S.save_settings({"research": {"blocked": ["example-a.com"]}})  # Settings > Research sources: A news is blocked now
        o = next(o for o in S.mentions_body("nw1", requeue=False)["orgs"] if o["name"] == "Harborline Labs")
        x = o["explain"]
        self.assertEqual([e["label"] for e in x["evidence"]], ["B news"])
        self.assertEqual(x["explanation"], [{"text": "B news says that.", "sources": [0]}])  # B's sentence, cited to B
        self.assertIsNone(x["since"])  # only A news said when
        self.assertEqual(o["relation"]["explanation"], x["explanation"])
        _, edges = S.connections_graph(S.load_records(), {"nw1"})
        self.assertEqual(next(e for e in edges if e["explain"]["name"] == "Harborline Labs")["explain"], x)
        p = S._person_view({"name": "Maria Gomez", "sources": [{"url": "https://example-a.com/t"}, {"url": "https://example-b.com/t"}],
                            "explanation": [{"text": "A says so.", "sources": [0]}, {"text": "B says so.", "sources": [1]}]})
        self.assertEqual(p["explanation"], [{"text": "B says so.", "sources": [0]}])


# ---------------------------------------------------------------- Meetily (fake recording folders) ----------------------------------------------------------------

def live_call_events(now):
    """One Northwind call running now (started 10 minutes ago)."""
    return [ev("nwlive", (now - timedelta(minutes=10)).isoformat(), 45, [SELF, att("priya.raman@northwind-freight.com", "Priya Raman"),
                                                                       att("marcus.bell@northwind-freight.com", "Marcus Bell")], summary="Northwind: live call")]


class MeetilyTests(Fresh):
    def setUp(self):
        super().setUp()
        with S.RQ_LOCK:
            S.RQ.update(queue=[], pending=set(), running=set(), errors={}, meta={}, mentions={})
        self.root = Path(tempfile.mkdtemp(prefix="meetily-"))
        os.environ["MEETILY_RECORDINGS_DIR"] = str(self.root)
        self.old = (S.research_client, S.RESEARCH_AUTOSTART, S.HTTP, S.API_HTTP)
        S.RESEARCH_AUTOSTART = False
        S.API_HTTP = lambda *a, **k: self.fail("Meetily must never use the network")
        S.research_client = lambda: self.fail("no Claude key: nothing is looked up")
        S.save_json(S.token_path(), {"access_token": "AT-x", "refresh_token": "RT-x", "expires_at": time.time() + 3000, "email": "chris@spotify.com", "name": "Chris Park"})
        self.now = datetime.now(timezone.utc)
        self.events = live_call_events(self.now) + northwind_events(self.now)
        self.http = []

        def http(method, url, form=None, headers=None, timeout=15):
            self.http.append(url)
            return (200, {"items": self.events}) if url.startswith(S.EVENTS_URL) else (404, {})
        S.HTTP = http
        S.meetily_reset(False)

    def tearDown(self):
        S.research_client, S.RESEARCH_AUTOSTART, S.HTTP, S.API_HTTP = self.old
        os.environ.pop("MEETILY_RECORDINGS_DIR", None)
        S.meetily_reset(False)

    def meeting(self, name="Northwind sync_2026-10-21_15-00", status="recording", started=None, segs=()):
        d = self.root / name
        d.mkdir(exist_ok=True)
        (d / "metadata.json").write_text(json.dumps({"version": "1.0", "meeting_id": None, "meeting_name": name.split("_")[0],
                                                     "created_at": (started or self.now - timedelta(minutes=8)).isoformat(), "completed_at": None,
                                                     "duration_seconds": None, "devices": {"microphone": None, "system_audio": None},
                                                     "audio_file": "audio.mp4", "transcript_file": "transcripts.json", "sample_rate": 48000, "status": status}), encoding="utf-8")
        self.write(d, segs)
        return d

    def write(self, d, segs):
        segs = [{"id": "seg_%d" % i, "text": t, "audio_start_time": i * 4.0, "audio_end_time": i * 4.0 + 3, "duration": 3.0,
                 "display_time": "[%02d:%02d]" % (i * 4 // 60, i * 4 % 60), "confidence": 0.9, "sequence_id": i} for i, t in enumerate(segs)]
        tmp = d / ".transcripts.json.tmp"
        tmp.write_text(json.dumps({"version": "1.0", "segments": segs, "last_updated": S.now_iso(), "total_segments": len(segs)}), encoding="utf-8")
        os.replace(tmp, d / "transcripts.json")
        t = time.time() + len(segs)  # a new mtime on every write, however fast the test runs
        os.utime(d / "transcripts.json", (t, t))

    def names(self):
        b = (S.load_records().get("mentions") or {}).get("nwlive") or {}
        return {x["name"] for x in b.get("items", []) + b.get("orgs", [])}

    def test_off_by_default_and_reads_nothing(self):
        self.meeting(segs=["Maria Gomez from our security team will want the pack."])
        self.assertFalse(S.source_on("meetily"))
        self.assertEqual(S.meetily_step(), 0)
        self.assertEqual(self.names(), set())
        self.assertEqual(S.meetily_status()["on"], False)

    def test_live_lines_feed_the_mentions_of_the_running_call(self):
        S.save_settings({"research": {"meetily": True}})
        d = self.meeting(segs=["Thanks for joining.", "Maria Gomez from our security team will want the pack."])
        S.meetily_step()
        self.assertEqual(self.names(), {"Maria Gomez"})
        st = S.meetily_status("nwlive")
        self.assertEqual((st["listening"], st["callId"], st["lines"], st["recording"]), (True, "nwlive", 2, True))
        self.assertFalse(S.meetily_status("nw1")["listening"])  # another call
        b = S.load_records()["mentions"]["nwlive"]
        it = b["items"][0]
        self.assertEqual((it["source"], it["quote"]["time"], it["status"]), ("meetily", "0:04", "nokey"))  # no Claude key: listed, not looked up
        # new lines: only they (and a few before) are read again; a company said with its relation
        self.write(d, ["Thanks for joining.", "Maria Gomez from our security team will want the pack.",
                       "Most of our alerts still go through Brightwave Systems.", "They're our vendor for logging."])
        S.meetily_step()
        self.assertEqual(self.names(), {"Maria Gomez", "Brightwave Systems"})
        bw = next(o for o in S.load_records()["mentions"]["nwlive"]["orgs"])
        self.assertEqual((bw["status"], bw["relation"]["type"]), ("said", "vendor"))
        self.assertEqual(S.load_records()["mentions"]["nwlive"]["items"][0]["count"], 1)  # read again, not counted twice
        S.meetily_step()  # nothing new: nothing read
        saved = (Path(TMP) / "records.json").read_text(encoding="utf-8")
        self.assertNotIn("Thanks for joining", saved)  # only mentions and their sentence
        self.assertTrue(all(S.EVENTS_URL in u for u in self.http))  # the only request: your calendar
        # Meetily stops: one last read, then the lines are let go
        meta = json.loads((d / "metadata.json").read_text(encoding="utf-8"))
        (d / "metadata.json").write_text(json.dumps(dict(meta, status="completed")), encoding="utf-8")
        S.meetily_step()
        st = S.meetily_status("nwlive")
        self.assertEqual((st["recording"], st["listening"], st["lines"]), (False, False, 0))
        with S.MEETILY_LOCK:
            self.assertEqual(S.MEETILY["lines"], [])
        self.assertEqual(S.meetily_step(), 0)  # a finished recording is never read again

    def test_matching_by_time_and_the_call_picked_in_the_panel(self):
        S.save_settings({"research": {"meetily": True}})
        self.meeting(started=self.now - timedelta(days=2), segs=["Maria Gomez from security."])  # no call ran then
        S.meetily_step()
        self.assertEqual(S.meetily_status()["callId"], "")
        self.assertEqual((S.load_records().get("mentions") or {}), {})
        S.meetily_pick({"callId": "nw1"})
        S.meetily_step()
        self.assertEqual(S.meetily_status()["callId"], "nw1")
        self.assertIn("Maria Gomez", {x["name"] for x in S.load_records()["mentions"]["nw1"]["items"]})
        self.assertEqual(S.meetily_pick({"callId": "../x"})[0], 400)
        self.assertEqual(S.meetily_pick({"callId": "nw1", "x": 1})[0], 400)

    def end(self, d):
        meta = json.loads((d / "metadata.json").read_text(encoding="utf-8"))
        (d / "metadata.json").write_text(json.dumps(dict(meta, status="completed")), encoding="utf-8")

    def nw1(self):
        return {x["name"] for x in S.load_records()["mentions"]["nw1"]["items"]}

    def test_a_call_picked_for_one_recording_never_carries_over_to_the_next(self):
        S.save_settings({"research": {"meetily": True}})
        d1 = self.meeting(name="Ad hoc_2026-10-19_09-00", started=self.now - timedelta(days=2), segs=["Maria Gomez from security."])
        S.meetily_step()
        S.meetily_pick({"callId": "nw1"})  # this recording is the Northwind pilot call
        S.meetily_step()
        self.assertEqual(self.nw1(), {"Maria Gomez"})
        self.end(d1)
        S.meetily_step()
        d2 = self.meeting(segs=["Tom Hughes from our security team will want the pack."])  # the next one, during the nwlive call
        S.meetily_step()
        self.assertEqual((S.meetily_status()["callId"], S.meetily_status()["pinned"]), ("nwlive", ""))
        self.assertEqual(self.names(), {"Tom Hughes"})
        self.assertEqual(self.nw1(), {"Maria Gomez"})
        # the same when the next recording has already started as one picked for another call ends
        S.meetily_pick({"callId": "nw1"})
        self.end(d2)
        self.meeting(name="Northwind again_2026-10-21_15-05", started=self.now - timedelta(minutes=5), segs=["Maria Gomez from our security team will want the pack."])
        S.meetily_step()
        self.assertEqual(S.meetily_status()["callId"], "nwlive")
        self.assertIn("Tom Hughes", self.nw1())  # recording 2 was picked for nw1 and read once more for it as it ended
        self.assertEqual(self.names(), {"Tom Hughes", "Maria Gomez"})

    def test_old_and_crashed_recordings_are_ignored(self):
        S.save_settings({"research": {"meetily": True}})
        self.meeting(name="Old_2026-10-01_10-00", status="completed", segs=["Maria Gomez from security."])
        d = self.meeting(name="Crashed_2026-10-02_10-00", segs=["Tom Hughes from security."])
        old = time.time() - S.MEETILY_MAX_AGE - 60
        for f in (d / "metadata.json", d / "transcripts.json"):
            os.utime(f, (old, old))
        self.assertEqual(S.meetily_recording(), (None, None))
        self.assertEqual(S.meetily_step(), 0)

    def test_settings_switch_and_status(self):
        self.assertEqual((S.default_settings()["research"]["meetily"], S.default_settings()["research"]["granola"]), (False, False))
        S.save_settings({"research": {"meetily": True}})
        self.assertTrue(S.source_on("meetily"))
        st = S.status_body()["meetily"]
        self.assertEqual((st["on"], st["found"]), (True, True))
        with self.assertRaises(S.Invalid):
            S.save_settings({"research": {"meetily": "yes"}})


class MeetilyRoutes(ServerBase):
    def setUp(self):
        super().setUp()
        S.meetily_reset(False)

    def test_status_and_pick_have_the_guards(self):
        origin = "http://localhost:%d" % S.PORT
        st, txt, _ = self.req("GET", "/api/meetily?callId=nw1")
        self.assertEqual(st, 200)
        self.assertEqual(json.loads(txt)["on"], False)
        self.assertEqual(self.req("GET", "/api/meetily", headers={"Sec-Fetch-Site": "cross-site"})[0], 403)
        self.assertEqual(self.req("GET", "/api/meetily?callId=a/b")[0], 400)
        self.assertEqual(self.req("POST", "/api/meetily/pick", {"callId": "nw1"})[0], 403)
        self.assertEqual(self.req("POST", "/api/meetily/pick", {"callId": "nw1"}, {"X-OVERTURE": "1", "Origin": "https://evil.example"})[0], 403)
        st, txt, _ = self.req("POST", "/api/meetily/pick", {"callId": "nw1"}, {"X-OVERTURE": "1", "Origin": origin})
        self.assertEqual(st, 200, txt)
        with S.MEETILY_LOCK:
            self.assertEqual(S.MEETILY["pinned"], "nw1")
        self.assertEqual(self.req("HEAD", "/api/meetily")[0], 404)


# ---------------------------------------------------------------- Granola (fake API) ----------------------------------------------------------------

def granola_note(nid, event_id, start, invitees, transcript, title="Northwind: pilot"):
    return {"id": nid, "object": "note", "title": title, "owner": {"name": "Chris Park", "email": "chris@spotify.com"},
            "created_at": start, "updated_at": start, "web_url": "https://notes.granola.ai/d/" + nid,
            "calendar_event": {"event_title": title, "invitees": [{"email": e} for e in invitees], "organiser": "chris@spotify.com",
                               "calendar_event_id": event_id, "scheduled_start_time": start, "scheduled_end_time": start},
            "attendees": [], "summary_text": "We talked about the pilot.", "summary_markdown": "## Pilot\nWe talked about the pilot.",
            "transcript": transcript}


class FakeGranola:
    def __init__(self, notes, too_big=()):
        self.notes, self.too_big, self.calls = {n["id"]: n for n in notes}, set(too_big), []

    def __call__(self, method, url, body=None, headers=None, timeout=8):
        self.calls.append({"method": method, "url": url, "headers": dict(headers or {})})
        u = urllib.parse.urlsplit(url)
        q = dict(urllib.parse.parse_qsl(u.query))
        if u.netloc != "public-api.granola.ai":
            return 404, {}, {}
        if u.path == "/v1/notes":
            return 200, {"notes": [{k: n[k] for k in ("id", "object", "title", "owner", "created_at", "updated_at")} for n in self.notes.values()],
                         "hasMore": False, "cursor": None}, {}
        m = re.fullmatch(r"/v1/notes/(not_\w+)(/transcript)?", u.path)
        if not m or m.group(1) not in self.notes:
            return 404, {}, {}
        n = self.notes[m.group(1)]
        if m.group(2):
            items = n["transcript"]
            start = int(q.get("cursor") or 0)
            page = items[start:start + 2]
            more = start + 2 < len(items)
            return 200, {"transcript": page, "hasMore": more, "cursor": str(start + 2) if more else None}, {}
        if q.get("include") == "transcript":
            if n["id"] in self.too_big:
                return 413, {"message": "TRANSCRIPT_TOO_LARGE"}, {}
            return 200, dict(n), {}  # a fresh copy each time, like real JSON
        return 200, {k: v for k, v in n.items() if k != "transcript"}, {}


def gt(text, who="them", name=None, at="2026-10-19T15:00:00Z"):
    sp = {"source": "speaker", "attribution": who}
    if name:
        sp["name"] = name
    return {"speaker": sp, "text": text, "start_time": at, "end_time": at}


class GranolaTests(Fresh):
    def setUp(self):
        super().setUp()
        with S.RQ_LOCK:
            S.RQ.update(queue=[], pending=set(), running=set(), errors={}, meta={}, mentions={})
        self.old = (S.research_client, S.RESEARCH_AUTOSTART, S.HTTP, S.API_HTTP, dict(S.GRANOLA_STATE))
        S.RESEARCH_AUTOSTART = False
        S.save_json(S.token_path(), {"access_token": "AT-x", "refresh_token": "RT-x", "expires_at": time.time() + 3000, "email": "chris@spotify.com", "name": "Chris Park"})
        self.now = datetime.now(timezone.utc)
        start = self.now - timedelta(hours=2)
        self.events = [ev("nwpast", start.isoformat(), 45, [SELF, att("priya.raman@northwind-freight.com", "Priya Raman"),
                                                          att("marcus.bell@northwind-freight.com", "Marcus Bell")], summary="Northwind: pilot")]
        S.HTTP = lambda method, url, form=None, headers=None, timeout=15: (200, {"items": self.events}) if url.startswith(S.EVENTS_URL) else (404, {})
        z = start.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        self.transcript = [gt("Hi all.", "me", at=z), gt("Maria Gomez from our security team will want the pack.", name="Priya Raman", at=z),
                           gt("Most of our alerts still go through Brightwave Systems.", name="Marcus Bell", at=z), gt("They're our vendor for logging.", name="Marcus Bell", at=z)]
        self.api = FakeGranola([granola_note("not_AAAAAAAAAAAAAA", "other-event", z, ["x@other.com"], [gt("Nothing here.")], title="Other"),
                                granola_note("not_BBBBBBBBBBBBBB", "nwpast", z, ["priya.raman@northwind-freight.com"], self.transcript)])
        S.API_HTTP = self.api
        S.GRANOLA_STATE["checkedAt"] = 0.0

    def tearDown(self):
        S.research_client, S.RESEARCH_AUTOSTART, S.HTTP, S.API_HTTP, st = self.old
        S.GRANOLA_STATE.update(st)
        os.environ.pop("GRANOLA_API_KEY", None)

    def test_off_and_not_connected(self):
        self.assertEqual(S.granola_fetch("nwpast")[0], 403)
        S.save_settings({"research": {"granola": True}})
        self.assertEqual(S.granola_fetch("nwpast")[0], 409)
        self.assertEqual(self.api.calls, [])
        self.assertEqual(S.granola_step(), 0)

    def test_reads_the_matching_note_keeps_only_mentions_title_link_and_summary(self):
        os.environ["GRANOLA_API_KEY"] = GRANOLA_KEY
        S.save_settings({"research": {"granola": True}})
        st, body = S.granola_fetch("nwpast")
        self.assertEqual(st, 200, body)
        names = {x["name"] for x in body["items"] + body["orgs"]}
        self.assertEqual(names, {"Maria Gomez", "Brightwave Systems"})
        self.assertEqual({x["source"] for x in body["items"] + body["orgs"]}, {"granola"})
        self.assertEqual(body["granola"]["title"], "Northwind: pilot")
        self.assertEqual(body["granola"]["url"], "https://notes.granola.ai/d/not_BBBBBBBBBBBBBB")
        self.assertIn("We talked about the pilot.", body["granola"]["summary"])
        for c in self.api.calls:
            self.assertTrue(c["url"].startswith("https://public-api.granola.ai/v1/notes"))
            self.assertEqual(c["headers"], {"Authorization": "Bearer " + GRANOLA_KEY})
            self.assertEqual(c["method"], "GET")
        saved = (Path(TMP) / "records.json").read_text(encoding="utf-8")
        self.assertNotIn("Hi all.", saved)
        self.assertNotIn(GRANOLA_KEY, saved + json.dumps(body) + S.live_script())
        x = next(o for o in body["orgs"] if o["name"] == "Brightwave Systems")["explain"]
        self.assertEqual((x["found"]["via"], x["said"]["speaker"]), ("Granola's transcript", "Marcus Bell"))
        self.assertIn("granola", S.status_body())
        self.assertTrue(S.status_body()["granola"]["connected"])

    def test_a_long_transcript_is_paged(self):
        os.environ["GRANOLA_API_KEY"] = GRANOLA_KEY
        S.save_settings({"research": {"granola": True}})
        self.api.too_big.add("not_BBBBBBBBBBBBBB")
        st, body = S.granola_fetch("nwpast")
        self.assertEqual(st, 200, body)
        self.assertIn("Maria Gomez", {x["name"] for x in body["items"]})
        self.assertTrue(any("/transcript?page_size=100&cursor=2" in c["url"] for c in self.api.calls))

    def test_only_the_matching_notes_transcript_is_fetched(self):
        os.environ["GRANOLA_API_KEY"] = GRANOLA_KEY
        S.save_settings({"research": {"granola": True}})
        self.assertEqual(S.granola_fetch("nwpast")[0], 200)
        urls = [c["url"] for c in self.api.calls]
        self.assertFalse([u for u in urls if "not_AAAAAAAAAAAAAA" in u and "transcript" in u], urls)  # the other meeting's transcript is never read
        self.assertTrue(any(u.endswith("/v1/notes/not_BBBBBBBBBBBBBB?include=transcript") for u in urls), urls)

    def test_the_read_after_the_call_follows_automatic_look_up(self):
        os.environ["GRANOLA_API_KEY"] = GRANOLA_KEY
        os.environ["ANTHROPIC_API_KEY"] = "test-key"
        self.addCleanup(os.environ.pop, "ANTHROPIC_API_KEY", None)
        S.research_client = lambda: self.fail("automatic look-up is off: nothing goes to Claude")
        S.save_settings({"research": {"granola": True}, "mentions": {"autoLookup": False}})
        self.assertEqual(S.granola_step(), 1)  # by itself, after the call
        maria = next(i for i in S.load_records()["mentions"]["nwpast"]["items"] if i["name"] == "Maria Gomez")
        self.assertEqual((maria["status"], maria["note"]), ("nokey", S.AUTO_OFF_NOTE))
        with S.RQ_LOCK:
            self.assertEqual(S.RQ["queue"], [])
        with S.RECORDS_LOCK:
            r = S.load_records()
            r["mentions"].pop("nwpast")
            S.save_json(S.records_path(), r)
        st, body = S.granola_fetch("nwpast", forced=True)  # Read Granola's note: your own action, so it is looked up
        self.assertEqual(st, 200, body)
        self.assertEqual(next(i for i in body["items"] if i["name"] == "Maria Gomez")["status"], "pending")
        with S.RQ_LOCK:
            self.assertTrue(S.RQ["queue"])

    def test_the_summary_goes_with_old_quotes(self):
        os.environ["GRANOLA_API_KEY"] = GRANOLA_KEY
        S.save_settings({"research": {"granola": True}, "mentions": {"keepDays": 1}})
        self.assertEqual(S.granola_fetch("nwpast")[0], 200)
        self.assertIn("We talked about the pilot.", (Path(TMP) / "records.json").read_text(encoding="utf-8"))
        S.prune_old_quotes(datetime.now(timezone.utc) + timedelta(days=30))
        self.assertNotIn("We talked about the pilot.", (Path(TMP) / "records.json").read_text(encoding="utf-8"))
        g = S.load_records()["granola"]["nwpast"]
        self.assertEqual((g["status"], g["title"], g["summary"]), ("done", "Northwind: pilot", ""))  # the note's title and link stay
        self.assertEqual(S.granola_view(S.load_records(), "nwpast")["summary"], "")

    def test_after_the_call_once_and_no_note_tried_again_later(self):
        os.environ["GRANOLA_API_KEY"] = GRANOLA_KEY
        S.save_settings({"research": {"granola": True}})
        self.assertEqual(S.granola_step(), 1)
        self.assertEqual(S.load_records()["granola"]["nwpast"]["status"], "done")
        S.GRANOLA_STATE["checkedAt"] = 0.0
        self.assertEqual(S.granola_step(), 0)  # read once
        self.api.notes.clear()
        with S.RECORDS_LOCK:
            r = S.load_records()
            r.pop("granola")
            S.save_json(S.records_path(), r)
        S.GRANOLA_STATE["checkedAt"] = 0.0
        self.assertEqual(S.granola_step(), 1)
        self.assertEqual(S.load_records()["granola"]["nwpast"]["status"], "none")
        S.GRANOLA_STATE["checkedAt"] = 0.0
        self.assertEqual(S.granola_step(), 0)  # no note yet: not asked again for 30 minutes

    def test_errors_never_show_the_key(self):
        os.environ["GRANOLA_API_KEY"] = GRANOLA_KEY
        S.save_settings({"research": {"granola": True}})
        S.API_HTTP = lambda *a, **k: (401, {}, {})
        st, body = S.granola_fetch("nwpast")
        self.assertEqual(st, 502)
        self.assertIn("didn't accept the API key", body["error"])
        self.assertNotIn(GRANOLA_KEY, json.dumps(body) + json.dumps(S.status_body()))


class GranolaRoutes(ServerBase):
    def test_fetch_route_guards(self):
        origin = "http://localhost:%d" % S.PORT
        self.assertEqual(self.req("POST", "/api/granola/fetch", {"callId": "nw1"})[0], 403)
        self.assertEqual(self.req("POST", "/api/granola/fetch", {"callId": "nw1"}, {"X-OVERTURE": "1", "Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.req("POST", "/api/granola/fetch", {"callId": "a/b"}, {"X-OVERTURE": "1", "Origin": origin})[0], 400)
        st, txt, _ = self.req("POST", "/api/granola/fetch", {"callId": "nw1"}, {"X-OVERTURE": "1", "Origin": origin})
        self.assertEqual(st, 403)  # off by default
        self.assertIn("Turn on Granola", json.loads(txt)["error"])

    def test_connect_tool_granola_only(self):
        import contextlib
        import getpass
        import io
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import connect
        old = getpass.getpass
        getpass.getpass = lambda prompt="": GRANOLA_KEY
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                self.assertEqual(connect.main(["granola"]), 0)
        finally:
            getpass.getpass = old
        self.assertEqual(S.granola_key(), GRANOLA_KEY)
        self.assertNotIn(GRANOLA_KEY, out.getvalue())
        self.assertEqual(json.loads((Path(TMP) / "granola.json").read_text(encoding="utf-8")), {"api_key": GRANOLA_KEY})


# ---------------------------------------------------------------- Chrome extension: manifest and the frame allow-list ----------------------------------------------------------------

EXT = Path(__file__).resolve().parent.parent / "extension"


class ExtensionManifest(unittest.TestCase):
    def manifest(self):
        return json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))

    def test_permissions_are_minimal_and_hosts_limited(self):
        m = self.manifest()
        self.assertEqual(m["manifest_version"], 3)
        self.assertEqual(m["permissions"], ["sidePanel", "scripting"])  # scripting: add the caption reader to Meet tabs already open after a reload
        self.assertEqual(m["host_permissions"], ["https://meet.google.com/*", "https://*.zoom.us/*", "http://localhost:3576/*"])
        # One content script, on Google Meet only: it reads Meet's captions (when CC is on) for the side panel.
        self.assertEqual(m["content_scripts"], [{"matches": ["https://meet.google.com/*"], "js": ["captions.js"], "run_at": "document_idle"}])
        for k in ("optional_permissions", "optional_host_permissions", "externally_connectable", "web_accessible_resources", "side_panel"):
            self.assertNotIn(k, m)
        self.assertNotIn("<all_urls>", json.dumps(m))
        csp = m["content_security_policy"]["extension_pages"]
        self.assertIn("script-src 'self'", csp)
        self.assertIn("frame-src http://localhost:3576;", csp)
        self.assertIn("connect-src http://localhost:3576;", csp)
        self.assertNotIn("unsafe", csp)
        self.assertEqual(m["background"], {"service_worker": "background.js"})
        for f in ["background.js", "sidepanel.html", "sidepanel.js", "sidepanel.css"]:
            self.assertTrue((EXT / f).is_file(), f)
        for size, path in m["icons"].items():
            data = (EXT / path).read_bytes()
            self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(struct_unpack_size(data), (int(size), int(size)))
        # the extension's pages and scripts only ever name Overture's own address (and the meeting sites they read)
        text = "".join((EXT / f).read_text(encoding="utf-8") for f in ("background.js", "sidepanel.js", "sidepanel.html"))
        self.assertEqual(set(re.findall(r"https?://[a-z0-9.:-]+", text)), {"http://localhost:3576"})
        self.assertNotIn("eval(", text)
        self.assertNotIn("innerHTML", text)

    def test_fixed_id_matches_the_docs_and_the_frame_allow_list(self):
        eid = S.extension_id_from_key(self.manifest()["key"])
        self.assertRegex(eid, r"^[a-p]{32}$")
        self.assertIn(eid, (S.HERE / "docs" / "CHROME-EXTENSION.md").read_text(encoding="utf-8"))
        self.assertEqual(S.frame_ancestors("/panel.html?host=ext&meet=abc-defg-hij"), "'self' chrome-extension://" + eid)
        self.assertEqual(S.frame_ancestors("/PANEL.html"), "'self' chrome-extension://" + eid)
        for p in ("/", "/index.html", "/index.html?x=panel.html", "/api/mentions", "/settings.js"):
            self.assertEqual(S.frame_ancestors(p), "'self'", p)
        os.environ["OVERTURE_EXTENSION_IDS"] = "abcdefghijklmnopabcdefghijklmnop, *, https://evil.example, ABCDEFGHIJKLMNOPABCDEFGHIJKLMNOP"
        try:
            self.assertEqual(S.frame_ancestors("/panel.html"), "'self' chrome-extension://" + eid + " chrome-extension://abcdefghijklmnopabcdefghijklmnop")
        finally:
            os.environ.pop("OVERTURE_EXTENSION_IDS", None)

    def test_meeting_codes_from_tab_addresses(self):
        import shutil
        import subprocess
        node = shutil.which("node")
        if not node:
            self.skipTest("node isn't installed")
        js = ("global.document={getElementById:()=>({addEventListener(){},hidden:false})};"
              "global.chrome={tabs:{onActivated:{addListener(){}},onUpdated:{addListener(){}},query:async()=>[]}};"
              "global.fetch=async()=>({ok:false});"
              "const m=require(process.argv[1]);"
              "const urls=['https://meet.google.com/abc-defg-hij','https://meet.google.com/ABC-DEFG-HIJ?authuser=1','https://meet.google.com/landing',"
              "'https://app.zoom.us/wc/81234567890/join?fromPWA=1','https://zoom.us/wc/join/81234567890','https://us05web.zoom.us/j/81234567890?pwd=x',"
              "'https://evilzoom.us/wc/81234567890/join','http://meet.google.com/abc-defg-hij','https://example.com/abc-defg-hij','not a url'];"
              "console.log(JSON.stringify(urls.map(u=>m.meetingParams(u)).concat([m.panelUrl({meet:'abc-defg-hij'}),m.panelUrl({zoom:'81234567890'})])));")
        out = subprocess.run([node, "-e", js, str(EXT / "sidepanel.js")], capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        got = json.loads(out.stdout)
        self.assertEqual(got[:10], [{"meet": "abc-defg-hij"}, {"meet": "abc-defg-hij"}, {}, {"zoom": "81234567890"}, {"zoom": "81234567890"},
                                    {"zoom": "81234567890"}, {}, {}, {}, {}])
        self.assertEqual(got[10:], ["http://localhost:3576/panel.html?host=ext&meet=abc-defg-hij", "http://localhost:3576/panel.html?host=ext&zoom=81234567890"])


def struct_unpack_size(png):
    import struct
    return struct.unpack(">II", png[16:24])


class FrameHeaders(ServerBase):
    def test_only_overture_and_its_extension_may_frame_the_panel(self):
        eid = S.extension_ids()[0]
        st, _, h = self.req("GET", "/panel.html?host=ext&meet=abc-defg-hij")
        self.assertEqual(st, 200)
        self.assertEqual(h["Content-Security-Policy"], "frame-ancestors 'self' chrome-extension://" + eid)
        self.assertNotIn("X-Frame-Options", h)  # it would block the extension
        for p in ("/", "/index.html", "/api/status"):
            self.assertEqual(self.req("GET", p)[2]["Content-Security-Policy"], "frame-ancestors 'self'", p)


class DeepResearchRoutes(ServerBase):
    def test_look_a_company_up_again_has_the_write_guards(self):
        origin = "http://localhost:%d" % S.PORT
        old = (S.research_client, S.RESEARCH_AUTOSTART)
        S.RESEARCH_AUTOSTART = False
        with S.RQ_LOCK:
            S.RQ.update(queue=[], pending=set(), running=set(), errors={},
                        meta={"shea@tks.world": {"name": "Shea Kim", "company": "Tks", "domain": "tks.world", "callId": "u1", "named": True, "internal": False, "local": {}}})
        ok = {"X-OVERTURE": "1", "Origin": origin}
        try:
            st, txt, _ = self.req("GET", "/api/research")
            self.assertEqual((st, json.loads(txt)["orgs"]["tks.world"]["note"]), (200, S.ORG_NO_KEY_NOTE))
            body = {"domain": "tks.world"}
            self.assertEqual(self.req("POST", "/api/research/org", body)[0], 403)
            self.assertEqual(self.req("POST", "/api/research/org", body, {"X-OVERTURE": "1"})[0], 403)
            self.assertEqual(self.req("POST", "/api/research/org", body, {"X-OVERTURE": "1", "Origin": "https://evil.example"})[0], 403)
            self.assertEqual(self.req("POST", "/api/research/org", body, dict(ok, **{"Content-Type": "text/plain"}))[0], 403)
            st, txt, _ = self.req("POST", "/api/research/org", body, ok)
            self.assertEqual((st, json.loads(txt)), (503, {"error": "no-key"}))
            os.environ["ANTHROPIC_API_KEY"] = "test-key"
            self.assertEqual(self.req("POST", "/api/research/org", {"domain": "not a domain"}, ok)[0], 400)
            self.assertEqual(self.req("POST", "/api/research/org", {"domain": "tks.world", "x": 1}, ok)[0], 400)
            self.assertEqual(self.req("POST", "/api/research/org", {"domain": ["tks.world"]}, ok)[0], 400)
            self.assertEqual(self.req("POST", "/api/research/org", {"domain": "acme.com"}, ok)[0], 404)
            st, txt, _ = self.req("POST", "/api/research/org", body, ok)
            self.assertEqual((st, json.loads(txt)["status"]), (202, "pending"))
            self.assertEqual(json.loads(self.req("GET", "/api/research")[1])["orgs"]["tks.world"]["status"], "pending")
            with S.RQ_LOCK:
                self.assertEqual(S.RQ["queue"], [("co:tks.world", True)])
            S.save_settings({"research": {"web": False}})
            self.assertEqual(self.req("POST", "/api/research/org", body, ok)[0], 403)
        finally:
            os.environ.pop("ANTHROPIC_API_KEY", None)
            S.research_client, S.RESEARCH_AUTOSTART = old
            with S.RQ_LOCK:
                S.RQ.update(queue=[], pending=set(), running=set(), errors={}, meta={})


class ZoomIds(unittest.TestCase):
    def test_zoom_meeting_number_from_the_invite(self):
        base = [SELF, att("a@acme.com")]
        e = ev("z", "2026-10-21T14:00:00+00:00", 30, base, location="https://us02web.zoom.us/j/81234567890?pwd=abc")
        self.assertEqual(S.event_to_invite(e, ME["email"], S.empty_records())["zoomId"], "81234567890")
        e = ev("z", "2026-10-21T14:00:00+00:00", 30, base, conferenceData={"entryPoints": [{"entryPointType": "video", "uri": "https://acme.zoom.us/j/9876543210"}]})
        self.assertEqual(S.event_to_invite(e, ME["email"], S.empty_records())["zoomId"], "9876543210")
        for loc in ("https://zoom.us.evil.example/j/81234567890", "Room 4", "https://zoom.us/j/12"):
            e = ev("z", "2026-10-21T14:00:00+00:00", 30, base, location=loc)
            self.assertEqual(S.event_to_invite(e, ME["email"], S.empty_records())["zoomId"], "", loc)


class SharedSite(ServerBase):
    """The shared site (Render): each Google account sees only its own data; a signed-out visitor sees the connect screen."""
    URL = "https://overture.example.com"
    ENV = {"GOOGLE_CLIENT_ID": "cid", "GOOGLE_CLIENT_SECRET": "csecret"}

    def setUp(self):
        super().setUp()
        import shutil
        shutil.rmtree(Path(TMP) / "users", ignore_errors=True)
        self.old = (S.HOSTED, S.PUBLIC_URL, S.HTTP, {k: os.environ.get(k) for k in list(self.ENV) + ["OVERTURE_ALLOWED", "DATABASE_URL"]})
        S.HOSTED, S.PUBLIC_URL = True, self.URL
        os.environ.update(self.ENV)
        os.environ.pop("OVERTURE_ALLOWED", None)
        S.HTTP = self.google

    def tearDown(self):
        S.HOSTED, S.PUBLIC_URL, S.HTTP, env = self.old
        for k, v in env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def google(self, method, url, form=None, headers=None, timeout=15):
        """Google's side: the code is the email signing in."""
        if url == S.TOKEN_URL:
            return 200, {"access_token": "AT-" + form["code"], "refresh_token": "RT-" + form["code"], "expires_in": 3600, "scope": S.CAL_SCOPE}
        if url == S.USERINFO_URL:
            return 200, {"email": headers["Authorization"].split("AT-", 1)[1], "name": "Someone"}
        return 200, {}  # revoke

    def hreq(self, method, path, body=None, cookie=None, write=False, signin=None):
        h = {"Host": "overture.example.com"}
        jar = ([S.SESSION_COOKIE + "=" + cookie] if cookie else []) + ([S.OAUTH_COOKIE + "=" + signin] if signin else [])
        if jar:
            h["Cookie"] = "; ".join(jar)
        if write:
            h.update({"X-OVERTURE": "1", "Origin": self.URL})
        return self.req(method, path, body, h)

    def callback(self, email, same_browser=True):
        st, _, h = self.hreq("GET", "/auth/google")  # the sign-in starts here: Google's address, and a cookie for this browser
        self.assertEqual(st, 302)
        state = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(h["Location"]).query))["state"]
        self.assertIn(S.OAUTH_COOKIE + "=" + state, h["Set-Cookie"])
        return self.hreq("GET", "/auth/google/callback?state=" + state + "&code=" + urllib.parse.quote(email),
                         signin=state if same_browser else None)

    def sign_in(self, email):
        st, txt, h = self.callback(email)
        self.assertEqual(st, 302, txt)
        self.assertIn("HttpOnly", h["Set-Cookie"])
        self.assertIn("Secure", h["Set-Cookie"])
        return h["Set-Cookie"].split(";")[0].split("=", 1)[1]

    def test_signed_out_sees_only_the_connect_screen(self):
        st, js, _ = self.hreq("GET", "/data/live.js")
        self.assertEqual(st, 200)
        self.assertIn("window.OVERTURE_LIVE = null", js)
        self.assertIn('"hosted": true', js)
        st, txt, _ = self.hreq("GET", "/api/status")
        self.assertEqual((st, json.loads(txt)["google"]["connected"]), (200, False))
        self.assertEqual(self.hreq("GET", "/api/records")[0], 401)
        self.assertEqual(self.hreq("GET", "/api/records", cookie="made-up")[0], 401)
        self.assertEqual(self.hreq("PUT", "/api/records/company", {"name": "Acme", "status": "New lead"}, write=True)[0], 401)
        self.assertEqual(self.hreq("POST", "/auth/google/disconnect", {}, write=True)[0], 401)
        self.assertEqual(self.hreq("GET", "/index.html")[0], 200)
        self.assertEqual(self.req("GET", "/api/status", headers={"Host": "evil.example"})[0], 403)

    def test_each_account_sees_only_its_own_data(self):
        a, b = self.sign_in("chris@spotify.com"), self.sign_in("sam@example.org")
        st, txt, _ = self.hreq("PUT", "/api/records/company", {"name": "Acme", "status": "New lead"}, cookie=a, write=True)
        self.assertEqual(st, 200, txt)
        self.assertIn("Acme", self.hreq("GET", "/api/records", cookie=a)[1])
        self.assertNotIn("Acme", self.hreq("GET", "/api/records", cookie=b)[1])
        self.assertEqual(json.loads(self.hreq("GET", "/api/status", cookie=a)[1])["google"]["email"], "chris@spotify.com")
        self.assertEqual(json.loads(self.hreq("GET", "/api/status", cookie=b)[1])["google"]["email"], "sam@example.org")
        folder = Path(TMP) / "users" / S.account_id("chris@spotify.com")
        self.assertEqual(S.load_json(folder / "google-token.json", {})["access_token"], "AT-chris@spotify.com")
        self.assertFalse((Path(TMP) / "google-token.json").exists())  # nothing lands outside an account's folder
        self.assertNotIn(a, (Path(TMP) / "sessions.json").read_text(encoding="utf-8"))  # only hashes of the cookies are saved

    def test_sign_out_ends_the_session_on_every_device(self):
        a, phone, other = self.sign_in("chris@spotify.com"), self.sign_in("chris@spotify.com"), self.sign_in("sam@example.org")
        st, _, h = self.hreq("POST", "/auth/google/disconnect", {}, cookie=a, write=True)
        self.assertEqual(st, 200)
        self.assertIn("Max-Age=0", h["Set-Cookie"])
        self.assertEqual(self.hreq("GET", "/api/records", cookie=a)[0], 401)
        self.assertEqual(self.hreq("GET", "/api/records", cookie=phone)[0], 401)
        self.assertEqual(self.hreq("GET", "/api/records", cookie=other)[0], 200)

    def test_sign_in_must_finish_in_the_browser_that_started_it(self):
        st, txt, h = self.callback("eve@evil.example", same_browser=False)  # a callback link someone else sent you
        self.assertEqual(st, 400)
        self.assertNotIn("Set-Cookie", h)

    def test_removed_account_is_signed_out(self):
        a = self.sign_in("chris@spotify.com")
        os.environ["OVERTURE_ALLOWED"] = "sam@example.org"
        self.assertEqual(self.hreq("GET", "/api/records", cookie=a)[0], 401)

    def test_environment_crm_keys_are_ignored_on_the_shared_site(self):
        old = os.environ.get("HUBSPOT_TOKEN")
        os.environ["HUBSPOT_TOKEN"] = "pat-operator"
        try:
            with S.as_user("u1"):
                self.assertFalse(S.crm_configured("hubspot"))
        finally:
            os.environ.pop("HUBSPOT_TOKEN") if old is None else os.environ.__setitem__("HUBSPOT_TOKEN", old)

    def test_allowed_accounts(self):
        os.environ["OVERTURE_ALLOWED"] = "@spotify.com, sam@example.org"
        self.assertTrue(S.account_allowed("Chris@Spotify.com"))
        self.assertTrue(S.account_allowed("sam@example.org"))
        self.assertFalse(S.account_allowed("eve@evil.example"))
        self.assertFalse(S.account_allowed(""))
        st, txt, h = self.callback("eve@evil.example")
        self.assertEqual(st, 400)
        self.assertNotIn("Set-Cookie", h)
        self.assertFalse((Path(TMP) / "users" / S.account_id("eve@evil.example")).exists())

    def test_no_account_means_no_data(self):
        with self.assertRaises(S.NoUser):
            S.DATA_DIR / "records.json"
        with self.assertRaises(S.NoUser):
            S.CACHE["at"]
        with S.as_user("u1"):
            S.CACHE["at"] = 5.0
        with S.as_user("u2"):
            self.assertEqual(S.CACHE["at"], 0.0)
            self.assertEqual(Path(S.DATA_DIR / "x"), Path(TMP) / "users" / "u2" / "x")

    def test_research_worker_takes_each_accounts_jobs_in_that_account(self):
        with S.RQ_LOCK:
            with S.as_user("u1"):
                S.RQ["queue"].append(("x@acme.com", False))
            try:
                self.assertEqual(S._ready_user(), "u1")
            finally:
                with S.as_user("u1"):
                    S.RQ["queue"].clear()
            self.assertIsNone(S._ready_user())

    def test_saved_files_kept_in_the_database(self):
        os.environ["DATABASE_URL"] = "postgres://example"
        calls = []
        old = S._db_run
        S._db_run = lambda sql, args=(), must=False: calls.append((sql.split()[0], args)) or (
            [("users/u9/records.json", '{"a": 1}'), ("../evil.json", "x")] if sql.startswith("SELECT") else [])
        try:
            with S.as_user("u1"):
                S.save_json(S.DATA_DIR / "records.json", {"a": 1})
                S.remove_file(S.DATA_DIR / "records.json")
            self.assertEqual([(c, a[0]) for c, a in calls], [("INSERT", "users/u1/records.json"), ("DELETE", "users/u1/records.json")])
            self.assertEqual(S.db_restore(), 1)
            self.assertEqual(S.load_json(Path(TMP) / "users" / "u9" / "records.json", {}), {"a": 1})
            self.assertFalse((Path(TMP).parent / "evil.json").exists())
        finally:
            S._db_run = old


if __name__ == "__main__":
    unittest.main(verbosity=1)
