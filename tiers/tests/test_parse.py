"""Parser tests. The fixtures are the real files off the bucket, not inventions.

A mock that encodes your assumption cannot falsify it, so the two fixtures
under examples/ are byte-for-byte what Gluck's data looks like.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import parse  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
EX = os.environ.get("TIERS_EXAMPLES") or os.path.join(HERE, "..", "..", "examples")


def read(name):
    with open(os.path.join(EX, name), encoding="utf-8") as f:
        return f.read()


def check(label, cond):
    if not cond:
        raise AssertionError(label)
    print(f"ok   {label}")


def expect_raises(label, fn):
    try:
        fn()
    except parse.InputError:
        print(f"ok   {label}")
        return
    raise AssertionError(f"{label}: expected InputError, got none")


# ── the real JSON ────────────────────────────────────────────────────
d = parse.parse(read("peak-millenial-optimism.json"))
check("json: title read", d["title"] == "Peak Millenial Optimism")
check("json: 72 items", len(d["items"]) == 72)
check("json: tiers S..F", d["tiers"] == ["S", "A", "B", "C", "D", "F"])
check("json: ids unique", len({i["id"] for i in d["items"]}) == 72)
check("json: every item has a name", all(i["name"] for i in d["items"]))
check("json: every item has a sub", all(i["sub"] for i in d["items"]))
check("json: every item has an img", all(i["img"] for i in d["items"]))
check("json: 61 distinct covers", len({i["img"] for i in d["items"]}) == 61)
check(
    "json: imgs are bucket keys, not URLs",
    all(i["img"].startswith("tiers/img/") for i in d["items"]),
)

# ── the real line format ─────────────────────────────────────────────
t = parse.parse(read("peak-millenial-optimism.txt"))
check("txt: title read from '# '", t["title"] == "Peak Millenial Optimism")
check("txt: 72 rows", len(t["items"]) == 72)
check("txt: tiers read from 'tiers:'", t["tiers"] == ["S", "A", "B", "C", "D", "F"])
check(
    "txt: second field recognised as an image by inspection",
    all(i["img"] and i["img"].startswith("https://") for i in t["items"]),
)
check("txt: no sub invented", all(i["sub"] is None for i in t["items"]))
check(
    "txt: 'Kids - MGMT' NOT split by default",
    t["items"][0]["name"] == "Kids - MGMT",
)

# ── the split directive, opt in only ─────────────────────────────────
s = parse.parse('# T\nsplit: " - "\nKids - MGMT | https://x/y.jpg\n')
check("split: opt-in splits name", s["items"][0]["name"] == "Kids")
check("split: opt-in fills sub", s["items"][0]["sub"] == "MGMT")

# ── minimal, the shape he will imitate ───────────────────────────────
m = parse.parse(read("minimal.txt"))
check("minimal: parses", len(m["items"]) >= 3)
check("minimal: no images at all", all(i["img"] is None for i in m["items"]))
check("minimal: default tiers when unstated", m["tiers"] == parse.DEFAULT_TIERS)

# ── CSV, with music words as aliases ─────────────────────────────────
c = parse.parse(read("films.csv"))
check("csv: rows parsed", len(c["items"]) >= 3)
check("csv: 'artist' alias became sub", any(i["sub"] for i in c["items"]))
check("csv: 'image' alias became img", any(i["img"] for i in c["items"]))

# ── image inspection ────────────────────────────────────────────────
check("image: https URL", parse.looks_like_image("https://i.scdn.co/image/ab6"))
check("image: bucket key", parse.looks_like_image("tiers/img/abc.jpg"))
check("image: bare artist name is not an image", not parse.looks_like_image("MGMT"))
check("image: empty is not an image", not parse.looks_like_image(""))
check(
    "image: a key with no extension is not assumed to be one",
    not parse.looks_like_image("tiers/img/abc"),
)

# ── id stability and collisions ─────────────────────────────────────
dup = parse.parse("A | B\nA | B\n")
check("ids: collision disambiguated", dup["items"][0]["id"] != dup["items"][1]["id"])
again = parse.parse(read("peak-millenial-optimism.json"))
check(
    "ids: stable across parses of the same input",
    [i["id"] for i in again["items"]] == [i["id"] for i in d["items"]],
)

# ── negative controls. Each must FAIL, or the check above proves nothing ──
expect_raises("neg: invalid JSON rejected", lambda: parse.parse("{nope"))
expect_raises("neg: empty input rejected", lambda: parse.parse("   \n  \n"))
expect_raises(
    "neg: JSON object without items rejected", lambda: parse.parse('{"title":"x"}')
)
expect_raises(
    "neg: CSV without a name column rejected",
    lambda: parse.parse_csv("colour,size\nred,big\n"),
)
expect_raises(
    "neg: item with no name rejected",
    lambda: parse.parse_json('{"items":[{"sub":"MGMT"}]}'),
)

# A check that cannot fail is not a check: prove the harness itself fails.
try:
    check("harness: deliberately false", False)
except AssertionError:
    print("ok   harness: a false check does raise")
else:
    raise SystemExit("harness never fails, so no result above means anything")

print(f"\nall parser checks passed ({len(d['items'])} real items exercised)")
