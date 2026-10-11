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
    """Follow / to the list it redirects to, and assert the RENDERED document.

    / is a 302 now. Treating a 302 as a pass would reintroduce the exact bug
    this file exists to catch: a status code that looks like success while
    nothing was ever rendered.
    """
    c = main.app.test_client()
    h = {"Remote-User": "asset-check", "Remote-Groups": ""}
    r = c.get("/", headers=h)
    if r.status_code != 302:
        raise SystemExit(f"asset check: / returned {r.status_code}, expected a 302")
    target = r.headers.get("Location", "")
    if not target.startswith("/l/"):
        raise SystemExit(f"asset check: / redirected to {target!r}, expected /l/<slug>")
    r = c.get(target, headers=h)
    if r.status_code != 200:
        raise SystemExit(
            f"asset check: {target} returned {r.status_code}, expected 200. "
            f"The redirect target must render, not merely exist."
        )
    html = r.get_data(as_text=True)
    if "<" not in html or len(html) < 1000:
        raise SystemExit(f"asset check: {target} returned {len(html)} bytes, not a document")
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

    # Second negative control, demanded because / is a redirect now: point
    # the default at a list that does not exist and the check must REFUSE.
    # Without this, a redirect to nowhere would pass as "the page is whole".
    #
    # It can only run where the BUCKET IS REACHABLE, because an unknown slug
    # is only refused when the service can see the inventory. In a build
    # sandbox there is no network, so the mode is printed rather than the
    # control being quietly skipped.
    import mirror

    try:
        mirror.list_inputs()
        bucket = True
    except Exception as e:
        bucket = False
        print(f"note bucket unreachable ({type(e).__name__}), so the unknown-slug "
              f"control cannot run here; the page-whole check above still did")

    if not bucket:
        print(
            f"asset check: page whole, {len(local)} local asset reference(s), "
            f"all 200; one negative control fired, one needs the bucket"
        )
        raise SystemExit(0)

    before = os.environ.get("TIERS_DEFAULT_SLUG")
    os.environ["TIERS_DEFAULT_SLUG"] = "definitely-not-a-list"
    try:
        check()
    except SystemExit as e:
        if "404" not in str(e):
            raise SystemExit(
                f"asset check is BROKEN: a default pointing at nothing failed for "
                f"the wrong reason: {e}"
            )
        print(f"ok   negative control: a default pointing at nothing refuses ({e})")
    else:
        raise SystemExit(
            "asset check is BROKEN: a default slug that does not exist still passed, "
            "so a redirect to nowhere reads as a whole page"
        )
    finally:
        if before is None:
            os.environ.pop("TIERS_DEFAULT_SLUG", None)
        else:
            os.environ["TIERS_DEFAULT_SLUG"] = before

    print(
        f"asset check: page whole, {len(local)} local asset reference(s), "
        f"all 200; both negative controls fired"
    )
