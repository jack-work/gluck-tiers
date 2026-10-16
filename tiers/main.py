"""gluck-tiers: the service.

Routes are frozen in doc/http-contract.md. The board never receives a bucket
key or a remote URL: every image is resolved here to /img/<sha256> or to null.
"""

import json
import logging
import os
import pathlib
import socket
import sys
import threading
from urllib.parse import urlsplit

from flask import Flask, Response, jsonify, redirect, request, send_file

import mirror
import parse

STATE = pathlib.Path(os.environ.get("STATE_DIRECTORY") or os.environ.get("TIERS_STATE", "/var/lib/gluck-tiers"))
TEMPLATES = pathlib.Path(os.environ.get("TIERS_TEMPLATES", pathlib.Path(__file__).parent / "templates"))
ADMIN_GROUP = os.environ.get("TIERS_ADMIN_GROUP", "gluck-tiers-admin")

# A forgiving parser handed a 200 MB file is a denial of service against a
# 15 GB box that is also the house router. The real lists are 7 to 23 KB.
MAX_IMPORT_BYTES = int(os.environ.get("TIERS_MAX_IMPORT_BYTES", 1 << 20))
MAX_IMPORT_ITEMS = int(os.environ.get("TIERS_MAX_IMPORT_ITEMS", 2000))

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_IMPORT_BYTES


@app.errorhandler(413)
def too_large(_e):
    return jsonify(error=f"import exceeds {MAX_IMPORT_BYTES} bytes"), 413


@app.after_request
def cache_policy(resp):
    """An API response with no cache directive is a policy nobody chose.

    Three different answers, because the three things differ:

    | path         | policy             | why |
    |--------------|--------------------|-----|
    | `/`          | no-store           | the script is INLINE, so the document is the whole application. A kept copy is a stale app, not a stale shell |
    | `/api/*`     | no-store           | live state: a list re-parses when its object's ETag moves |
    | `/img/<sha>` | immutable, 1 year  | content-addressed, so the bytes cannot change under the name |

    no-cache would be the better choice for a document, since it permits a
    stored copy and demands revalidation, which keeps the ETag useful. It is
    the wrong choice here because a client that ignores the directive keeps a
    whole application. A webview did exactly that.

    send_file sets `no-cache` itself, so this must OVERWRITE rather than
    setdefault. A setdefault here would be a line that looks like a policy and
    changes nothing.
    """
    if request.path == "/":
        resp.headers["Cache-Control"] = "no-store"
    elif request.path.startswith("/api/"):
        resp.headers.setdefault("Cache-Control", "no-store")
    return resp
log = logging.getLogger("gluck-tiers")

# Nothing here touches the disk. Importing a module must be free of side
# effects, or the packaging check cannot import it and the unit's startup is
# coupled to a writable path existing before python runs. The packaging check
# in flake.nix caught exactly that.
_mirror = None
_store = None
_cache = {}
_collisions = {}
_lock = threading.Lock()


def images():
    global _mirror
    if _mirror is None:
        _mirror = mirror.Mirror(STATE)
    return _mirror


def store():
    global _store
    if _store is None:
        from store import Store

        _store = Store(STATE / "saves.sqlite")
    return _store


def identity():
    """Authelia sets these; Caddy strips any inbound copy first. Verified on
    the live Caddyfile 2026-10-10, see doc/http-contract.md."""
    user = request.headers.get("Remote-User")
    groups = [g.strip() for g in (request.headers.get("Remote-Groups") or "").split(",") if g.strip()]
    return user, groups


def same_origin():
    """Refuse a state-changing request that did not come from this site.

    The session is a cookie, so without this a cross-site request carries
    Gluck's identity for free. Browsers send Origin on every non-GET fetch, so
    its ABSENCE means a non-browser caller, and this service has none: refusing
    is the explicit choice rather than an oversight. doc/http-contract.md.
    """
    origin = request.headers.get("Origin")
    if not origin:
        return jsonify(error="Origin header is required on a state-changing request"), 403
    got = urlsplit(origin).netloc
    if got != request.host:
        log.warning("cross-origin write refused: Origin %s, Host %s", got, request.host)
        return jsonify(error=f"origin {got} is not {request.host}"), 403
    return None


def require_user():
    user, groups = identity()
    if not user:
        return None, None, (jsonify(error="no identity on the request"), 401)
    return user, groups, None


def slug_of(key):
    return pathlib.Path(key).stem


# Two files can name the same list: the canonical .json and a .txt or .csv
# written by hand. The suffix decides which one wins, because directory order
# must never decide what a reader sees. doc/input-format.md calls JSON
# canonical, so JSON wins, and the shipped .txt stays a fixture for the second
# parser path rather than becoming a competing source of truth.
#
# The cost of getting this wrong is not cosmetic: the .txt folds the artist
# into the name as "Kids - MGMT" and carries no sub, so letting it win empties
# the secondary line on every card.
SUFFIX_RANK = {".json": 0, ".csv": 1, ".txt": 2}


def _rank(key):
    return SUFFIX_RANK.get(pathlib.Path(key).suffix.lower(), 99)


def inventory(s3=None):
    """Map slug to the one winning key, deterministically and audibly."""
    groups = {}
    for i in mirror.list_inputs(s3):
        groups.setdefault(slug_of(i["key"]), []).append(i["key"])
    best = {}
    for slug, keys in groups.items():
        winner = sorted(keys, key=lambda k: (_rank(k), k))[0]
        best[slug] = winner
        if len(keys) > 1:
            losers = [k for k in keys if k != winner]
            _collisions[slug] = {"winner": winner, "losers": losers}
            log.warning(
                "input collision: slug %s is claimed by %d files, serving %s, ignoring %s",
                slug, len(keys), winner, ", ".join(losers),
            )
        else:
            _collisions.pop(slug, None)
    return best


def load_list(slug):
    """Parse and mirror one list, cached on the object's ETag."""
    s3 = mirror.client()
    inputs = inventory(s3)
    key = inputs.get(slug)
    if not key:
        return None
    head = s3.head_object(Bucket=mirror.BUCKET, Key=key)
    tag = head.get("ETag")
    with _lock:
        hit = _cache.get(slug)
        if hit and hit["etag"] == tag:
            return hit
    raw = mirror.get_object(key, s3=s3).decode("utf-8", "replace")
    parsed = parse.parse(raw, hint=pathlib.Path(key).suffix)
    # Stated rather than defaulted. A bucket object is admin-controlled, so it
    # may name keys and may be fetched from; doc/fetching.md.
    # A bucket object is admin-controlled, so it may name keys, but only keys
    # under the prefix and only objects whose bytes are images. doc/fetching.md.
    items, errors = images().ingest_list(parsed["items"], s3=s3, allow_keys=True)
    for e in errors:
        log.error("image unresolved id=%s source=%s: %s", e["id"], e["source"], e["error"])
    for w in parsed.get("warnings", []):
        log.warning("input %s: %s", key, w)
    entry = {
        "slug": slug,
        "etag": tag,
        "title": parsed["title"],
        "tiers": parsed["tiers"],
        "items": [{k: i[k] for k in ("id", "name", "sub", "img")} for i in items],
        "errors": errors,
        "warnings": parsed.get("warnings", []),
    }
    with _lock:
        _cache[slug] = entry
    return entry


def default_slug(inv=None):
    """Which list / lands on, decided deterministically.

    TIERS_DEFAULT_SLUG wins when set, and is used VERBATIM even if no such
    list exists, so a typo becomes a 404 naming the slug rather than a
    silent fallback to a different list. Otherwise the alphabetically first
    slug, which is stable across listings; directory order is not.
    """
    explicit = os.environ.get("TIERS_DEFAULT_SLUG", "").strip()
    if explicit:
        return explicit
    inv = inventory() if inv is None else inv
    return sorted(inv)[0] if inv else None


SCHEMES = {"light", "dark"}


def with_scheme(html):
    scheme = request.cookies.get("zanni-scheme")
    if scheme not in SCHEMES:
        return html
    return html.replace("<html", f'<html data-scheme="{scheme}"', 1)


def _board_page():
    page = TEMPLATES / "board.html"
    if not page.exists():
        return None, Response(
            "board template not built: www/board.html.in has not landed yet",
            status=503,
            mimetype="text/plain",
        )
    return page, None


@app.get("/")
def root():
    """A 302, because this URL is already in Gluck's phone. A url that stops
    working is a bug regardless of what replaced it."""
    user, _, err = require_user()
    if err:
        return err
    explicit = os.environ.get("TIERS_DEFAULT_SLUG", "").strip()
    if explicit:
        # No bucket round trip when the default is stated, which is what lets
        # the asset check run inside a build sandbox that has no network.
        return redirect(f"/l/{explicit}", code=302)
    try:
        slug = default_slug()
    except Exception as e:
        log.error("cannot reach the bucket to choose a default list: %s", e)
        return Response(
            f"cannot reach the bucket to choose a default list: {e}",
            status=503,
            mimetype="text/plain",
        )
    if not slug:
        return Response(
            "no input files under the tiers/ prefix, so there is no list to show",
            status=503,
            mimetype="text/plain",
        )
    return redirect(f"/l/{slug}", code=302)


@app.get("/l/<slug>")
def board(slug):
    """One document for every list. The slug lives in the URL and the inlined
    script reads it from there, so there is no template per list."""
    user, _, err = require_user()
    if err:
        return err
    page, err = _board_page()
    if err:
        return err
    # The document is a SHELL and is not the authority on whether a list
    # exists: /api/list/<slug> is, and it answers 404. So when the bucket is
    # reachable an unknown slug is refused here as a courtesy, and when it is
    # not reachable the shell is still served and the API reports the truth.
    # Serving a shell is never wrong; claiming a list exists would be.
    try:
        known = slug in inventory()
    except Exception as e:
        log.warning("cannot verify slug %r against the bucket: %s", slug, e)
        known = True
    if not known:
        return jsonify(error=f"no such list: {slug}"), 404
    return Response(with_scheme(page.read_text()), mimetype="text/html", headers={"Vary": "Cookie"})


@app.get("/api/lists")
def api_lists():
    user, _, err = require_user()
    if err:
        return err
    out = []
    for slug, key in sorted(inventory().items()):
        cached = _cache.get(slug)
        out.append({
            "slug": slug,
            "title": cached["title"] if cached else slug.replace("-", " ").title(),
            "items": len(cached["items"]) if cached else None,
            "source": key,
        })
    return jsonify(lists=out)


@app.get("/api/list/<slug>")
def api_list(slug):
    user, _, err = require_user()
    if err:
        return err
    entry = load_list(slug)
    if not entry:
        return jsonify(error=f"no such list: {slug}"), 404
    return jsonify({k: entry[k] for k in ("slug", "title", "tiers", "items")})


@app.get("/img/<sha>")
def img(sha):
    user, _, err = require_user()
    if err:
        return err
    if not sha.isalnum() or len(sha) != 64:
        return jsonify(error="not a sha256"), 404
    path = images().path_for(sha)
    if not path:
        return jsonify(error="unknown image"), 404
    # Content type from the SNIFFED magic, stored as the file's extension.
    # Never octet-stream: serving unknown bytes was half of how any object in
    # the bucket became downloadable.
    ctype = mirror.CONTENT_TYPE_BY_EXT.get(path.suffix)
    if not ctype:
        log.error("mirrored file %s has no known image type", path.name)
        return jsonify(error="unknown image"), 404
    resp = send_file(path, mimetype=ctype)
    # NOT public, NOT immutable, NOT a year. Deleting a source list must not
    # leave its assets published, and a hash is not an authorization policy:
    # whoever holds the url holds the bytes for as long as the cache lives.
    # The bytes are still immutable per hash, so only the window shrinks.
    resp.headers["Cache-Control"] = "private, max-age=3600"
    return resp


@app.get("/api/save/<slug>")
def get_save(slug):
    user, _, err = require_user()
    if err:
        return err
    return jsonify(assign=store().get(user, slug))


@app.put("/api/save/<slug>")
def put_save(slug):
    user, _, err = require_user()
    if err:
        return err
    bad = same_origin()
    if bad:
        return bad
    entry = load_list(slug)
    if not entry:
        return jsonify(error=f"no such list: {slug}"), 404
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or not isinstance(body.get("assign"), dict):
        return jsonify(error="body must be an object with an assign object"), 400
    assign = body["assign"]
    ids = {i["id"] for i in entry["items"]}
    tiers = set(entry["tiers"])
    for item_id, tier in assign.items():
        if item_id not in ids:
            return jsonify(error=f"unknown item id: {item_id}"), 400
        if tier not in tiers:
            return jsonify(error=f"tier not in this list: {tier}"), 400
    store().put(user, slug, assign)
    return "", 204


@app.post("/api/import")
def api_import():
    """Parse a dropped file and hand the list back. Nothing is stored.

    One parser, this one, because a second parser in JS drifts from it the
    first time a tolerance changes. Nothing reaches the bucket: there is no
    write path and the service key is read-only by design.

    The security boundary is the image rule. An imported item names its own
    images, and this service holds read on the WHOLE files bucket because
    Garage grants per bucket rather than per prefix. So an imported image
    resolves ONLY to a hash already mirrored. Were it allowed to name a bucket
    key, three lines of JSON would read any object in the bucket and mint a
    permanent capability URL for it. doc/imports.md.
    """
    user, _, err = require_user()
    if err:
        return err
    bad = same_origin()
    if bad:
        return bad

    hint = None
    if request.files:
        f = next(iter(request.files.values()))
        raw = f.read(MAX_IMPORT_BYTES + 1)
        # The filename is read for a format HINT only. The list's name comes
        # from the contents, never from what the file happened to be called.
        hint = pathlib.Path(f.filename or "").suffix.lower() or None
    else:
        raw = request.get_data(cache=False)[: MAX_IMPORT_BYTES + 1]
    if len(raw) > MAX_IMPORT_BYTES:
        return jsonify(error=f"import exceeds {MAX_IMPORT_BYTES} bytes"), 413
    if not raw.strip():
        return jsonify(error="the imported file is empty"), 400

    try:
        parsed = parse.parse(raw.decode("utf-8", "replace"), hint=hint)
    except parse.InputError as e:
        return jsonify(error=f"could not read that file: {e}"), 400
    if len(parsed["items"]) > MAX_IMPORT_ITEMS:
        return jsonify(
            error=f"{len(parsed['items'])} items exceeds the limit of {MAX_IMPORT_ITEMS}"
        ), 413

    items, errors = images().ingest_list(parsed["items"], allow_keys=False)
    for e in errors:
        log.info("import refused an image for %s: %s", user, e["error"])
    return jsonify(
        title=parsed["title"],
        tiers=parsed["tiers"],
        items=[{k: i[k] for k in ("id", "name", "sub", "img")} for i in items],
        rejected={
            "rows": parsed.get("warnings", []),
            "images": errors,
            "counts": {
                "rows_skipped": len(parsed.get("warnings", [])),
                "images_refused": len(errors),
                "items_accepted": len(items),
            },
        },
    )


@app.get("/api/status")
def status():
    """Unresolved images, counted rather than hidden. Contract addendum, asked
    of the integrator: additive, the board does not read it."""
    user, groups = identity()
    if not user:
        return jsonify(error="no identity on the request"), 401
    lists = {}
    for slug, entry in _cache.items():
        lists[slug] = {
            "items": len(entry["items"]),
            "image_errors": len(entry["errors"]),
            # A tolerated row is still a row nobody read. Counted here so
            # tolerance never becomes silence.
            "input_warnings": entry.get("warnings", []),
        }
    return jsonify(
        admin=ADMIN_GROUP in groups,
        mirrored=len(list(images().dir.glob("*.*"))),
        lists=lists,
        # Two input files claiming one slug. Deterministic precedence picks a
        # winner, but a silent pick is the defect: the loser tonight was the
        # format carrying the artist field.
        input_collisions=_collisions,
    )


def inherited_sockets():
    if os.environ.get("LISTEN_PID") != str(os.getpid()):
        return []
    return [socket.socket(fileno=3 + i) for i in range(int(os.environ.get("LISTEN_FDS", "0")))]


def main():
    from waitress import serve

    logging.basicConfig(level=logging.INFO)
    sockets = inherited_sockets()
    if sockets:
        log.info("gluck-tiers on the inherited socket, state %s", STATE)
        serve(app, sockets=sockets, threads=8)
    elif os.environ.get("KWEB_LISTEN") == "socket":
        sys.exit("no listening socket from systemd; refusing to fall back to TCP")
    else:
        port = int(os.environ.get("PORT", "9099"))
        log.info("gluck-tiers on 127.0.0.1:%s, state %s", port, STATE)
        serve(app, host="127.0.0.1", port=port, threads=8)


if __name__ == "__main__":
    main()
