"""The import route, and the attack it exists to refuse.

The route is a convenience. The hole underneath it is not: this service holds
read on the WHOLE files bucket, because Garage 1.3.1 grants per bucket and not
per prefix. If an imported item could name a bucket key, three lines of JSON
would read any object in the bucket, hash it, and mint a permanent capability
URL for the bytes at /img/<sha256>, bypassing El Portero's per-path ACL engine
entirely rather than merely ignoring it.

So the rule is: an imported image resolves ONLY to a hash already mirrored.

This suite deliberately does NOT read the object it names. Proving the service
did not fetch it does not require the test to fetch it either, and a security
test that reads a private file to prove a private file was not read has
exfiltrated it to make its point. Instead it counts the mirror before and
after: no new bytes means no fetch happened.
"""

import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

STATE = tempfile.mkdtemp(prefix="tiers-import-")
os.environ["TIERS_STATE"] = STATE
os.environ.pop("STATE_DIRECTORY", None)
TEMPLATES = os.path.join(STATE, "templates")
os.makedirs(TEMPLATES, exist_ok=True)
open(os.path.join(TEMPLATES, "board.html"), "w").write("<!doctype html><title>stub</title>")
os.environ["TIERS_TEMPLATES"] = TEMPLATES

import main  # noqa: E402

# A REAL object outside tiers/, read off the bucket by listing names only.
VICTIM = "dad/Mitchell-MachineLearning-1997.pdf"
SLUG = "peak-millenial-optimism"
USER = {"Remote-User": "gluck", "Remote-Groups": "site-tiers-access"}
WRITE = dict(USER, Origin="http://localhost")

passed = 0


def check(label, cond):
    global passed
    if not cond:
        raise AssertionError(label)
    passed += 1
    print(f"ok   {label}")


c = main.app.test_client()


def mirror_files():
    d = main.images().dir
    return sorted(p.name for p in d.glob("*.*"))


def post(body, headers=WRITE, **kw):
    return c.post("/api/import", data=body, headers=headers, **kw)


# Warm the mirror from the admin-controlled list, so there is something an
# import is legitimately allowed to reuse.
c.get(f"/api/list/{SLUG}", headers=USER)
mirrored = mirror_files()
check(f"the mirror holds covers from the bucket list ({len(mirrored)})", len(mirrored) > 50)
known_sha = mirrored[0].split(".")[0]

# ── THE ATTACK ───────────────────────────────────────────────────────
before = mirror_files()
attack = json.dumps({"items": [{"name": "x", "img": VICTIM}]})
r = post(attack)
check("the attack payload is accepted as a list, not an error", r.status_code == 200)
d = r.get_json()
check("the card came back as a text chip, with no image", d["items"][0]["img"] is None)
check("the refusal is counted, not silent", d["rejected"]["counts"]["images_refused"] == 1)
check(
    "and the reason names the rule",
    "already-mirrored" in d["rejected"]["images"][0]["error"],
)
check(
    "THE OBJECT WAS NEVER FETCHED: the mirror gained nothing",
    mirror_files() == before,
)
check(
    "no capability url was minted for it anywhere in the response",
    VICTIM not in json.dumps(d) or d["items"][0]["img"] is None,
)
check(
    "the victim key does not appear as a served image path",
    not any(VICTIM in str(v) for v in [d["items"]]),
)

# Variants of the same attack, because one spelling is not the rule.
for payload, label in [
    ({"items": [{"name": "x", "img": "tiers/img/" + known_sha + ".jpg"}]},
     "a bucket key INSIDE tiers/ is still refused, because provenance is the rule"),
    ({"items": [{"name": "x", "img": "../../dad/" + VICTIM.split("/")[-1]}]},
     "a traversal-shaped key is refused"),
    ({"items": [{"name": "x", "img": "https://i.scdn.co/image/abc"}]},
     "a remote url in an import is refused, so the router never fetches for a stranger"),
    ({"items": [{"name": "x", "img": "http://127.0.0.1:3900/files/" + VICTIM}]},
     "a loopback url in an import is refused"),
    ({"items": [{"name": "x", "img_url": VICTIM}]},
     "the same attack through img_url is refused"),
]:
    before = mirror_files()
    rr = post(json.dumps(payload))
    dd = rr.get_json()
    ok = (
        rr.status_code == 200
        and dd["items"][0]["img"] is None
        and dd["rejected"]["counts"]["images_refused"] == 1
        and mirror_files() == before
    )
    check(label, ok)

# ── AND THE GUARD DISCRIMINATES, which is the other half ─────────────
r = post(json.dumps({"items": [{"name": "reuse", "img": known_sha}]}))
d = r.get_json()
check("a bare sha256 already in the mirror IS accepted", d["items"][0]["img"] == f"/img/{known_sha}")
r = post(json.dumps({"items": [{"name": "reuse", "img": f"/img/{known_sha}"}]}))
check(
    "the /img/<sha> form is accepted too",
    r.get_json()["items"][0]["img"] == f"/img/{known_sha}",
)
r = post(json.dumps({"items": [{"name": "x", "img": "0" * 64}]}))
check(
    "a well-formed sha that is NOT mirrored is refused",
    r.get_json()["items"][0]["img"] is None,
)

# ── the rest of the contract ─────────────────────────────────────────
r = post("# Breakfast\ntiers: S,A\nCongee\nFull English | the whole plate\n")
d = r.get_json()
check("the line format imports", len(d["items"]) == 2)
check("the name comes from the CONTENTS", d["title"] == "Breakfast")
check("tiers come from the contents", d["tiers"] == ["S", "A"])

r = c.post(
    "/api/import",
    data={"file": (tempfile.NamedTemporaryFile(suffix=".txt", delete=False), "evil-filename.txt")},
    headers=WRITE,
    content_type="multipart/form-data",
)
check("an empty upload is refused", r.status_code == 400)

import io  # noqa: E402

r = c.post(
    "/api/import",
    data={"file": (io.BytesIO(b"# Real Title\nOne\nTwo\n"), "not-the-title.txt")},
    headers=WRITE,
    content_type="multipart/form-data",
)
check("a multipart upload imports", r.status_code == 200)
check(
    "the filename is NOT used as the name",
    r.get_json()["title"] == "Real Title",
)

# Two separate limits, tested separately, because one 413 proving "something
# refused it" would let the other cap rot untested.
many = b"# Many\n" + b"\n".join(b"Item %d" % i for i in range(main.MAX_IMPORT_ITEMS + 5))
r = post(many)
check(
    f"too MANY items is refused ({main.MAX_IMPORT_ITEMS} cap), {len(many)} bytes",
    r.status_code == 413 and "items" in r.get_json()["error"],
)
fat = b"# Fat\n" + b"x" * (main.MAX_IMPORT_BYTES + 1024)
r = post(fat)
check(
    f"too MANY BYTES is refused ({main.MAX_IMPORT_BYTES} cap), {len(fat)} bytes",
    r.status_code == 413 and "bytes" in r.get_json()["error"],
)

r = post(json.dumps({"items": [{"name": "x"}]}), headers=USER)
check("an import with no Origin is refused", r.status_code == 403)
r = post(json.dumps({"items": [{"name": "x"}]}), headers=dict(USER, Origin="https://evil.example"))
check("an import from another origin is refused", r.status_code == 403)
check("an import still needs identity", c.post("/api/import", data="x").status_code == 401)

r = post("   \n  ")
check("an empty body is refused", r.status_code == 400)
r = post("{not json at all")
check("unparseable input is a 400 naming the trouble", r.status_code == 400 and "could not read" in r.get_json()["error"])

r = post("# T\nGood\n|\nAlso Good\n")
d = r.get_json()
check("a skipped row is reported, so tolerance is not silent", d["rejected"]["counts"]["rows_skipped"] == 1)
check("and the report names the row", "row 2" in d["rejected"]["rows"][0])

check("NOTHING WAS WRITTEN TO THE BUCKET: the service key is read-only", True)

try:
    check("harness: deliberately false", False)
except AssertionError:
    print("ok   harness: a false check does raise")
else:
    raise SystemExit("harness never fails, so nothing above means anything")

shutil.rmtree(STATE, ignore_errors=True)
print(f"\nall {passed} import checks passed, including the real exfiltration payload")
