"""Input parsing for gluck-tiers.

doc/input-format.md is the contract. Three shapes in, one canonical list out.
"""

import csv
import io
import json
import re
import unicodedata

IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif")

NAME_KEYS = ("name", "title", "card", "item")
SUB_KEYS = ("sub", "subtitle", "artist", "author", "by")
IMG_KEYS = ("img", "image", "thumbnail", "thumb", "cover", "art")
URL_KEYS = ("img_url", "image_url", "src")
LINK_KEYS = ("link", "url", "href")

DEFAULT_TIERS = ["S", "A", "B", "C", "D", "F"]


class InputError(ValueError):
    """Raised when input cannot be read as a list at all."""


def looks_like_image(value):
    """Decide by inspection, never by position. doc/input-format.md."""
    if not value:
        return False
    v = value.strip()
    if v.startswith(("http://", "https://")):
        return True
    if v.lower().endswith(IMAGE_EXT):
        return True
    return False


def slugify(text):
    text = unicodedata.normalize("NFKD", text or "")
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "item"


def _first(d, keys):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None


def _item(raw, seen):
    """Canonicalise one item dict. Aliases resolve before validation."""
    name = _first(raw, NAME_KEYS)
    if not name:
        raise InputError(f"item has no name: {raw!r}")
    item = {
        "name": str(name).strip(),
        "sub": (str(_first(raw, SUB_KEYS)).strip() if _first(raw, SUB_KEYS) else None),
        "img": _first(raw, IMG_KEYS),
        "img_url": _first(raw, URL_KEYS),
        "link": _first(raw, LINK_KEYS),
    }
    ident = raw.get("id") or f"{slugify(item['name'])}--{slugify(item['sub'] or '')}"
    # An id collision would make two cards share one saved position.
    base, n = ident, 2
    while ident in seen:
        ident = f"{base}-{n}"
        n += 1
    seen.add(ident)
    item["id"] = ident
    return item


def parse_json(text):
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise InputError(f"not valid JSON: {e}") from e
    if not isinstance(data, dict) or "items" not in data:
        raise InputError("JSON must be an object carrying an items array")
    seen = set()
    return {
        "title": data.get("title") or "Untitled",
        "source": data.get("source"),
        "tiers": list(data.get("tiers") or DEFAULT_TIERS),
        "items": [_item(i, seen) for i in data["items"]],
    }


def parse_lines(text):
    """The hand-written shape. Field count decides meaning."""
    title, tiers, split_on, rows = None, None, None, []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            title = title or line.lstrip("#").strip()
            continue
        low = line.lower()
        if low.startswith("tiers:"):
            tiers = [t.strip() for t in line.split(":", 1)[1].split(",") if t.strip()]
            continue
        if low.startswith("split:"):
            split_on = line.split(":", 1)[1].strip().strip("\"'")
            continue
        rows.append(line)

    seen, items = set(), []
    for row in rows:
        fields = [f.strip() for f in row.split("|")]
        raw = {}
        if len(fields) >= 3:
            raw = {"name": fields[0], "sub": fields[1], "img": fields[2]}
        elif len(fields) == 2:
            if looks_like_image(fields[1]):
                raw = {"name": fields[0], "img": fields[1]}
            else:
                raw = {"name": fields[0], "sub": fields[1]}
        else:
            raw = {"name": fields[0]}
        # Only when the file asks for it. A default " - " split is wrong for
        # every title containing a hyphen, and wrong quietly.
        if split_on and not raw.get("sub") and split_on in raw["name"]:
            head, tail = raw["name"].split(split_on, 1)
            raw["name"], raw["sub"] = head.strip(), tail.strip()
        items.append(_item(raw, seen))

    if not items:
        raise InputError("no rows found")
    return {
        "title": title or "Untitled",
        "source": None,
        "tiers": tiers or DEFAULT_TIERS,
        "items": items,
    }


def parse_csv(text):
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise InputError("CSV has no header row")
    lowered = {f.lower().strip(): f for f in reader.fieldnames if f}
    if not any(k in lowered for k in NAME_KEYS):
        raise InputError(f"CSV header names no name column: {reader.fieldnames}")
    seen, items = set(), []
    for row in reader:
        raw = {k: row[v] for k, v in lowered.items() if row.get(v) not in (None, "")}
        if not any(k in raw for k in NAME_KEYS):
            continue
        items.append(_item(raw, seen))
    if not items:
        raise InputError("CSV had a header and no rows")
    return {"title": "Untitled", "source": None, "tiers": DEFAULT_TIERS, "items": items}


def parse(text, hint=None):
    """Sniff the shape. hint is a filename suffix when one is known."""
    stripped = text.lstrip()
    if stripped.startswith(("{", "[")):
        return parse_json(text)
    if hint == ".csv":
        return parse_csv(text)
    head = stripped.splitlines()[0] if stripped.splitlines() else ""
    if "," in head and "|" not in head and any(
        k in head.lower() for k in NAME_KEYS
    ):
        return parse_csv(text)
    return parse_lines(text)
