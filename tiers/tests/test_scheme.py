"""The board renders the reader's light/dark choice from the zanni-scheme
cookie that settings.kelliher.info sets, and renders nothing for any other
value, so a forged cookie cannot put markup into the page. Runs offline: an
unreachable bucket makes the board serve its shell."""

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

STATE = tempfile.mkdtemp(prefix="tiers-scheme-")
os.environ["TIERS_STATE"] = STATE
os.environ.pop("STATE_DIRECTORY", None)
os.environ.setdefault("TIERS_S3_ENDPOINT", "http://127.0.0.1:9")
TEMPLATES = os.path.join(STATE, "templates")
os.makedirs(TEMPLATES)
with open(os.path.join(TEMPLATES, "board.html"), "w") as f:
    f.write('<!doctype html>\n<html lang="en"><title>stub</title></html>')
os.environ["TIERS_TEMPLATES"] = TEMPLATES

import main  # noqa: E402

USER = {"Remote-User": "gluck", "Remote-Groups": "admin,site-tiers-access"}
c = main.app.test_client()
passed = 0


def check(label, cond, detail=""):
    global passed
    if not cond:
        raise AssertionError(f"{label}: {detail}")
    passed += 1
    print(f"ok   {label}")


def page(cookie=None):
    if cookie is not None:
        c.set_cookie("zanni-scheme", cookie)
    else:
        c.delete_cookie("zanni-scheme")
    r = c.get("/l/anything", headers=USER)
    return r, r.get_data(as_text=True)


r, body = page()
check("no cookie: the page follows the OS", r.status_code == 200 and "data-scheme" not in body, body[:80])
check("the page varies by cookie", "Cookie" in r.headers.get("Vary", ""))
for s in ("dark", "light"):
    r, body = page(s)
    check(f"{s}: pinned on <html>", f'<html data-scheme="{s}" lang="en">' in body, body[:80])
for bad in ("system", "", 'dark" onload="x', "DARK"):
    r, body = page(bad)
    check(f"{bad!r}: ignored", "data-scheme" not in body, body[:80])
print(f"{passed} passed")
