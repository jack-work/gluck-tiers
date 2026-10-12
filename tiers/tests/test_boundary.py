"""The four boundary controls, each watched to FAIL.

El Inspector found two holes in the shipped module. This file is the standing
proof that both stay shut, and it is written to be watched rather than trusted:
every control prints what it refused and why.

It reads no private object to make its point. Each control counts the mirror
before and after, because no new bytes is the honest evidence that nothing was
fetched, and a test that reads a private file to prove a private file was not
read has exfiltrated it to make its argument.
"""

import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

STATE = tempfile.mkdtemp(prefix="tiers-boundary-")
os.environ["TIERS_STATE"] = STATE
os.environ.pop("STATE_DIRECTORY", None)
TEMPLATES = os.path.join(STATE, "templates")
os.makedirs(TEMPLATES, exist_ok=True)
open(os.path.join(TEMPLATES, "board.html"), "w").write("<!doctype html><title>stub</title>")
os.environ["TIERS_TEMPLATES"] = TEMPLATES

import main  # noqa: E402
import mirror  # noqa: E402

# Real objects, all of them already on the bucket. Nothing is created.
OUTSIDE_PREFIX = "dad/Mitchell-MachineLearning-1997.pdf"   # legal-looking, wrong place
NOT_AN_IMAGE = "tiers/peak-millenial-optimism.json"        # right place, wrong bytes
SLUG = "peak-millenial-optimism"
USER = {"Remote-User": "gluck", "Remote-Groups": "site-tiers-access"}

c = main.app.test_client()
passed = 0


def check(label, cond, detail=""):
    global passed
    if not cond:
        raise AssertionError(label)
    passed += 1
    print(f"ok   {label}")
    if detail:
        print(f"       {detail}")


def mirror_files():
    return sorted(p.name for p in main.images().dir.glob("*.*"))


def ingest_one(source, allow_keys):
    """Drive the real ingest path for one source. Returns (sha, error)."""
    before = mirror_files()
    items, errors = main.images().ingest_list(
        [{"id": "probe", "name": "probe", "sub": None, "img": source, "img_url": None}],
        allow_keys=allow_keys,
    )
    return items[0]["img"], (errors[0]["error"] if errors else None), before, mirror_files()


print("=== CONTROL 1: a key OUTSIDE the prefix ===")
img, err, before, after = ingest_one(OUTSIDE_PREFIX, allow_keys=True)
check("the card became a chip rather than an image", img is None)
check("the refusal names the prefix rule", "outside the" in (err or ""), err)
check("THE MIRROR GAINED NOTHING, so the object was never read", before == after,
      f"{len(before)} files before, {len(after)} after")

print("\n=== CONTROL 2: a NON-IMAGE under a LEGAL prefix key ===")
img, err, before, after = ingest_one(NOT_AN_IMAGE, allow_keys=True)
check("the card became a chip", img is None)
check("the refusal says it is not an image", "not an image" in (err or ""), err)
check("nothing was mirrored, so no octet-stream can be served", before == after)
check(
    "and no sniffer accepts those bytes",
    mirror.sniff(b'{"title": "a json file, not a jpeg"}') == (None, None),
)

print("\n=== CONTROL 3: a URL source, now that remote fetching is gone ===")
for url in ("https://i.scdn.co/image/ab67616d00001e027823743acd3aa25a3a4c5758",
            "http://127.0.0.1:3900/files/" + OUTSIDE_PREFIX):
    img, err, before, after = ingest_one(url, allow_keys=True)
    check(f"refused: {url[:48]}", img is None and before == after, err)
# Parsed, not grepped. A first attempt at this check searched the source TEXT
# for "urllib" and failed on the COMMENT that explains why urllib was removed:
# an instrument reporting on itself rather than on the code. The AST sees
# imports and calls, and cannot see prose.
import ast  # noqa: E402

# The capability, not the package. urllib.parse is a STRING parser and the
# origin check needs it; urllib.request is the fetch. Forbidding the whole
# package would be an over-broad check, and an over-broad check is one somebody
# relaxes carelessly later, which is how a guard dies.
NETWORK_MODULES = {"urllib.request", "urllib.error", "http.client", "requests",
                   "socket", "httplib2", "aiohttp", "httpx", "ftplib", "telnetlib"}


def _is_network(name):
    return name in NETWORK_MODULES or any(
        name.startswith(n + ".") for n in NETWORK_MODULES
    )
offenders = []
for m in ("mirror.py", "main.py", "parse.py", "store.py"):
    tree = ast.parse(open(os.path.join(HERE, "..", m)).read(), filename=m)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if _is_network(a.name):
                    offenders.append(f"{m}: import {a.name}")
        elif isinstance(node, ast.ImportFrom) and node.module:
            if _is_network(node.module):
                offenders.append(f"{m}: from {node.module} import ...")
        elif isinstance(node, ast.Call):
            f = node.func
            name = getattr(f, "attr", None) or getattr(f, "id", None)
            if name in ("urlopen", "urlretrieve", "request"):
                offenders.append(f"{m}: calls {name}() at line {node.lineno}")
check(
    "no outbound HTTP exists in the serving path at all, by AST and not by grep",
    not offenders,
    "; ".join(offenders) or "no network import, no urlopen call",
)
# And the check must be able to fail, or its silence means nothing.
_fake = ast.parse("import urllib.request\nurllib.request.urlopen('x')\n")
_found = [
    n for n in ast.walk(_fake)
    if isinstance(n, ast.Import) and _is_network(n.names[0].name)
]
_allowed = ast.parse("from urllib.parse import urlsplit\n")
_wrongly = [
    n for n in ast.walk(_allowed)
    if isinstance(n, ast.ImportFrom) and _is_network(n.module)
]
check("and that AST check does detect a network import when one exists", bool(_found))
check(
    "while urllib.parse, a string parser, is correctly NOT flagged",
    not _wrongly,
)
check(
    "and the capability is gone rather than merely unused",
    not hasattr(mirror, "assert_fetchable") and not hasattr(mirror, "_OPENER"),
)

print("\n=== CONTROL 4: the discrimination half, which makes the rest evidence ===")
r = c.get(f"/api/list/{SLUG}", headers=USER)
d = r.get_json()
check("a legal prefix key holding a real image still works", r.status_code == 200)
check("every card got its cover", all(i["img"] for i in d["items"]), f"{len(d['items'])} cards")
check("61 distinct covers, deduplicated on content", len({i["img"] for i in d["items"]}) == 61)
lists = c.get("/api/lists", headers=USER).get_json()["lists"]
check(f"both lists are still served ({[x['slug'] for x in lists]})", len(lists) >= 2)
other = [x["slug"] for x in lists if x["slug"] != SLUG][0]
check(
    f"and the second list renders too ({other})",
    len(c.get(f"/api/list/{other}", headers=USER).get_json()["items"]) > 0,
)

sha = d["items"][0]["img"].rsplit("/", 1)[1]
r = c.get(f"/img/{sha}", headers=USER)
check("the image serves", r.status_code == 200 and len(r.data) > 1000)
check(
    "with a sniffed content type, never octet-stream",
    r.headers["Content-Type"].startswith("image/"),
    r.headers["Content-Type"],
)
cc = r.headers["Cache-Control"]
check("cache is private, not public", "private" in cc and "public" not in cc, cc)
check("cache is an hour, not a year, and not immutable",
      "max-age=3600" in cc and "immutable" not in cc, cc)

print()
try:
    check("harness: deliberately false", False)
except AssertionError:
    print("ok   harness: a false check does raise")
else:
    raise SystemExit("harness never fails, so nothing above means anything")

shutil.rmtree(STATE, ignore_errors=True)
print(f"\nall {passed} boundary checks passed, every refusal watched")
