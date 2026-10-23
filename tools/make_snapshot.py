"""Save a copy of the public Backstage data MOAB uses, so the demo still works offline.

Writes data/snapshot.js with:
- the public Backstage adopters list (company name and the reason they gave; contacts left out)
- the latest Backstage release
- the package lists of a few releases (the sample company's, a common older one, and the latest)
- every published security notice that affects those packages

Run: python -I tools/make_snapshot.py   (re-run on the morning of a demo so the numbers are current)
"""
import json
import re
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_RELEASE = "1.24.0"
EXTRA_RELEASES = ["1.30.0"]  # versions likely to be typed into "Check any company" during a demo
RANGE_PART = re.compile(r"^(<=|>=|<|>|=)?\s*\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$")


def get(url, with_next=False):
    req = urllib.request.Request(url, headers={"User-Agent": "centralize-demo", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = resp.read().decode("utf-8")
        if not with_next:
            return body
        # GitHub pages this endpoint with a cursor in the Link header, not a page number.
        m = re.search(r'<([^>]+)>;\s*rel="next"', resp.headers.get("Link") or "")
        return body, (m.group(1) if m else None)


def clean(cell):
    cell = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", cell)  # keep link text only
    cell = re.sub(r"<[^>]+>", "", cell)
    return " ".join(cell.split())


def adopters():
    rows = []
    for line in get("https://raw.githubusercontent.com/backstage/backstage/master/ADOPTERS.md").splitlines():
        if not line.startswith("|") or set(line.replace("|", "").strip()) <= set("-: "):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3 or cells[0].lower() == "organization":
            continue
        name = clean(cells[0])
        if name:
            rows.append({"org": name, "use": clean(cells[2])[:400]})
    return rows


def advisories(packages):
    found = {}
    names = sorted(packages)
    for i in range(0, len(names), 40):
        url = "https://api.github.com/advisories?" + urllib.parse.urlencode(
            {"ecosystem": "npm", "affects": ",".join(names[i:i + 40]), "per_page": 100})
        while url:
            text, url = get(url, with_next=True)
            for a in json.loads(text):
                vulns = [
                    {"pkg": v["package"]["name"], "range": v.get("vulnerable_version_range") or "",
                     "patched": v.get("first_patched_version") or ""}
                    for v in a.get("vulnerabilities", []) if v.get("package", {}).get("name", "").startswith("@backstage/")
                ]
                for v in vulns:  # the page's matcher only reads full x.y.z versions; say so if a range is something else
                    if not all(RANGE_PART.match(p.strip()) for p in v["range"].split(",")):
                        print(f"warning: {a['ghsa_id']} {v['pkg']} range {v['range']!r} will not be matched")
                if vulns:
                    found[a["ghsa_id"]] = {
                        "id": a["ghsa_id"], "summary": a["summary"], "severity": a.get("severity") or "unknown",
                        "published": (a.get("published_at") or "")[:10], "url": a["html_url"], "vulns": vulns,
                    }
    return sorted(found.values(), key=lambda a: a["published"], reverse=True)


def manifest(version):
    data = json.loads(get(f"https://versions.backstage.io/v1/releases/{version}/manifest.json"))
    return {p["name"]: p["version"] for p in data["packages"]}


latest = json.loads(get("https://api.github.com/repos/backstage/backstage/releases/latest"))
latest_version = latest["tag_name"].lstrip("v")
manifests = {v: manifest(v) for v in dict.fromkeys([SAMPLE_RELEASE, *EXTRA_RELEASES, latest_version])}
all_packages = set().union(*manifests.values())
snapshot = {
    "takenOn": date.today().isoformat(),
    "latestRelease": {"version": latest_version, "date": latest["published_at"][:10]},
    "sampleRelease": SAMPLE_RELEASE,
    "manifests": manifests,
    "adopters": adopters(),
    "advisories": advisories(all_packages),
}
out = ROOT / "data" / "snapshot.js"
out.parent.mkdir(exist_ok=True)
out.write_text("// Public Backstage data saved by tools/make_snapshot.py. Regenerate to refresh.\n"
               "window.SNAPSHOT = " + json.dumps(snapshot, indent=1) + ";\n", encoding="utf-8")
print(f"adopters {len(snapshot['adopters'])}, manifests {list(manifests)}, "
      f"advisories {len(snapshot['advisories'])}, latest {snapshot['latestRelease']}")
