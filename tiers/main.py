"""gluck-tiers: the service.

Routes are frozen in doc/http-contract.md. The board never receives a bucket
key or a remote URL: every image is resolved here to /img/<sha256> or to null.
"""

import json
import logging
import os
import pathlib
import threading

from flask import Flask, Response, jsonify, request, send_file

import mirror
import parse

STATE = pathlib.Path(os.environ.get("STATE_DIRECTORY") or os.environ.get("TIERS_STATE", "/var/lib/gluck-tiers"))
TEMPLATES = pathlib.Path(os.environ.get("TIERS_TEMPLATES", pathlib.Path(__file__).parent / "templates"))
ADMIN_GROUP = os.environ.get("TIERS_ADMIN_GROUP", "gluck-tiers-admin")

app = Flask(__name__)


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
    items, errors = images().ingest_list(parsed["items"], s3=s3)
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


@app.get("/")
def board():
    user, _, err = require_user()
    if err:
        return err
    page = TEMPLATES / "board.html"
    if not page.exists():
        return Response(
            "board template not built: www/board.html.in has not landed yet",
            status=503,
            mimetype="text/plain",
        )
    return send_file(page)


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
    resp = send_file(path)
    resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
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


def main():
    from waitress import serve

    port = int(os.environ.get("PORT", "9099"))
    logging.basicConfig(level=logging.INFO)
    log.info("gluck-tiers on 127.0.0.1:%s, state %s", port, STATE)
    serve(app, host="127.0.0.1", port=port, threads=8)


if __name__ == "__main__":
    main()
