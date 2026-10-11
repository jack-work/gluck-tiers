"""The page must be WHOLE, not merely 200.

Fetches / through the real app, extracts every asset the returned HTML
references, and demands each one answers 200. The failure this exists to catch:
/ returned 200 with 33719 bytes while <script src="board.js"> returned 404, so
nothing on the board ever ran and every API test still passed.

Run with TIERS_TEMPLATES pointing at the built templates directory.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402

EXTERNAL = ("http://", "https://", "//", "data:", "#", "mailto:")


def referenced(html):
    refs = re.findall(r'(?:src|href)\s*=\s*"([^"]+)"', html)
    return [r for r in refs if r and not r.startswith(EXTERNAL)]


def check(inject=None):
    c = main.app.test_client()
    h = {"Remote-User": "asset-check", "Remote-Groups": ""}
    r = c.get("/", headers=h)
    if r.status_code != 200:
        raise SystemExit(f"asset check: / returned {r.status_code}, expected 200")
    html = r.get_data(as_text=True)
    if inject:
        html += f'\n<script src="{inject}"></script>'

    local = referenced(html)
    bad = []
    for path in local:
        rr = c.get("/" + path.lstrip("/"), headers=h)
        ctype = rr.headers.get("Content-Type", "")
        if rr.status_code != 200:
            bad.append(f"{path} -> {rr.status_code}")
        elif "html" in ctype and not path.endswith((".html", "/")):
            bad.append(f"{path} -> 200 but Content-Type {ctype}, which is the 404 page")
    return local, bad


if __name__ == "__main__":
    local, bad = check()
    if bad:
        for b in bad:
            print("BROKEN ASSET:", b, file=sys.stderr)
        raise SystemExit("asset check FAILED: the page is not whole")

    # Negative control, in the same run, because a check that has never
    # refused anything is not a check. A deliberately missing asset must be
    # reported; if it is not, the check above proved nothing.
    _, bad_injected = check(inject="definitely-not-here.js")
    if not bad_injected:
        raise SystemExit(
            "asset check is BROKEN: a deliberately missing asset was not detected"
        )

    print(
        f"asset check: page whole, {len(local)} local asset reference(s), "
        f"all 200; negative control fired on a missing asset"
    )
