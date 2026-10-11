"""API tests against the REAL bucket. No mocks.

A mock that encodes your assumption cannot falsify it: this estate shipped 16
green tests over a mock that returned None where lldap raises. So these tests
read the real objects through the loopback tunnel and mirror the real covers.

Requires: ssh -N -f -L 3900:127.0.0.1:3900 spain@spain, and a credential file
at ~/.config/gluck-tiers/credentials (profile tiers-ro).
"""

import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

STATE = tempfile.mkdtemp(prefix="tiers-test-")
os.environ["TIERS_STATE"] = STATE
os.environ.pop("STATE_DIRECTORY", None)

import main  # noqa: E402

SLUG = "peak-millenial-optimism"
USER = {"Remote-User": "gluck", "Remote-Groups": "admin,site-tiers-access"}
OTHER = {"Remote-User": "dad", "Remote-Groups": "site-tiers-access"}

passed = 0


def check(label, cond):
    global passed
    if not cond:
        raise AssertionError(label)
    passed += 1
    print(f"ok   {label}")


c = main.app.test_client()

# ── identity is required, and that is the negative control ───────────
check("401 without Remote-User on /api/lists", c.get("/api/lists").status_code == 401)
check("401 without Remote-User on the board", c.get("/").status_code == 401)
check("401 without Remote-User on an image", c.get("/img/" + "a" * 64).status_code == 401)

# ── the inventory, read off the real bucket ──────────────────────────
r = c.get("/api/lists", headers=USER)
check("/api/lists is 200", r.status_code == 200)
slugs = [x["slug"] for x in r.get_json()["lists"]]
check(f"the real list is listed ({slugs})", SLUG in slugs)

# ── one list, parsed and mirrored for real ───────────────────────────
r = c.get(f"/api/list/{SLUG}", headers=USER)
check("/api/list is 200", r.status_code == 200)
d = r.get_json()
check("title", d["title"] == "Peak Millenial Optimism")
check("tiers", d["tiers"] == ["S", "A", "B", "C", "D", "F"])
check("72 items", len(d["items"]) == 72)
check(
    "every img is a service path, never a bucket key or a CDN URL",
    all(i["img"] and i["img"].startswith("/img/") for i in d["items"]),
)
check("61 distinct covers after dedup", len({i["img"] for i in d["items"]}) == 61)
check(
    "no bucket key leaked to the board",
    not any("tiers/img" in json.dumps(i) for i in d["items"]),
)
check(
    "no third-party URL leaked to the board",
    not any("scdn.co" in json.dumps(i) for i in d["items"]),
)
check("fields are exactly the contract's", set(d["items"][0]) == {"id", "name", "sub", "img"})

# ── images actually serve ────────────────────────────────────────────
sha = d["items"][0]["img"].rsplit("/", 1)[1]
r = c.get(f"/img/{sha}", headers=USER)
check("image serves 200", r.status_code == 200)
check("image has bytes", len(r.data) > 1000)
check("image is immutable-cached", "immutable" in r.headers.get("Cache-Control", ""))
check("bogus sha is 404", c.get("/img/" + "b" * 64, headers=USER).status_code == 404)
check("non-sha path is 404", c.get("/img/not-a-sha", headers=USER).status_code == 404)
check("unknown slug is 404", c.get("/api/list/nope", headers=USER).status_code == 404)

# ── saves ────────────────────────────────────────────────────────────
ids = [i["id"] for i in d["items"]]
check("save starts empty", c.get(f"/api/save/{SLUG}", headers=USER).get_json()["assign"] == {})
good = {ids[0]: "S", ids[1]: "F"}
r = c.put(f"/api/save/{SLUG}", json={"assign": good}, headers=USER)
check("valid save is 204", r.status_code == 204)
check(
    "save reads back",
    c.get(f"/api/save/{SLUG}", headers=USER).get_json()["assign"] == good,
)
check(
    "another user's save is separate",
    c.get(f"/api/save/{SLUG}", headers=OTHER).get_json()["assign"] == {},
)

# ── the error table, each case must FAIL ─────────────────────────────
r = c.put(f"/api/save/{SLUG}", json={"assign": {"no-such-id": "S"}}, headers=USER)
check("unknown item id is 400", r.status_code == 400)
check("and it names the offender", "no-such-id" in r.get_json()["error"])
r = c.put(f"/api/save/{SLUG}", json={"assign": {ids[0]: "Z"}}, headers=USER)
check("unknown tier is 400", r.status_code == 400)
check("and it names the tier", "Z" in r.get_json()["error"])
check(
    "a non-object body is 400",
    c.put(f"/api/save/{SLUG}", json=[1, 2], headers=USER).status_code == 400,
)
check(
    "assign missing is 400",
    c.put(f"/api/save/{SLUG}", json={"nope": {}}, headers=USER).status_code == 400,
)
check(
    "the rejected save did not overwrite the good one",
    c.get(f"/api/save/{SLUG}", headers=USER).get_json()["assign"] == good,
)

# ── status, and the mirror on disk ───────────────────────────────────
s = c.get("/api/status", headers=USER).get_json()
check("status counts the mirror", s["mirrored"] == 61)
check("status reports zero image errors", s["lists"][SLUG]["image_errors"] == 0)
check("admin group recognised", c.get("/api/status", headers={"Remote-User": "gluck", "Remote-Groups": "gluck-tiers-admin"}).get_json()["admin"] is True)
check("non-admin not admin", s["admin"] is False)

# ── the harness must be able to fail ─────────────────────────────────
try:
    check("harness: deliberately false", False)
except AssertionError:
    print("ok   harness: a false check does raise")
else:
    raise SystemExit("harness never fails, so nothing above means anything")

shutil.rmtree(STATE, ignore_errors=True)
print(f"\nall {passed} API checks passed against the real bucket")
