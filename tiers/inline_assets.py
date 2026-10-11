"""Inline local assets a page references, so no second request can fail.

usage: inline_assets.py <built-page> <asset-dir>

Caddy runs no file_server for this host and Flask routes only /, /api/* and
/img/<sha>, so a <script src="board.js"> is a request nothing can answer. The
page returned 200 while its script returned 404, which is indistinguishable
from a working page unless you fetch the asset.
"""

import pathlib
import re
import sys


def inline(page: pathlib.Path, assets: pathlib.Path) -> int:
    html = page.read_text()
    done = 0

    def script(m):
        nonlocal done
        src = m.group(1)
        if src.startswith(("http://", "https://", "//", "data:")):
            return m.group(0)
        f = assets / src.lstrip("/")
        if not f.exists():
            raise SystemExit(f"inline_assets: {src} referenced by the page does not exist at {f}")
        done += 1
        # </script> inside JS would close the tag early. Nothing here contains
        # it today; refuse rather than emit a page that parses differently.
        body = f.read_text()
        if "</script" in body.lower():
            raise SystemExit(f"inline_assets: {src} contains a closing script tag")
        return "<script>\n" + body + "\n</script>"

    html = re.sub(r'<script[^>]*\ssrc="([^"]+)"[^>]*>\s*</script>', script, html)

    def link(m):
        nonlocal done
        href = m.group(1)
        if href.startswith(("http://", "https://", "//", "data:")):
            return m.group(0)
        f = assets / href.lstrip("/")
        if not f.exists():
            raise SystemExit(f"inline_assets: {href} referenced by the page does not exist at {f}")
        done += 1
        return "<style>\n" + f.read_text() + "\n</style>"

    html = re.sub(r'<link[^>]*\srel="stylesheet"[^>]*\shref="([^"]+)"[^>]*>', link, html)

    page.write_text(html)
    return done


if __name__ == "__main__":
    page, assets = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
    n = inline(page, assets)
    print(f"inlined {n} local asset(s) into {page.name}")
