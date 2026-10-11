---
name: http-contract
description: The HTTP surface between the board in www/ and the service in tiers/. Frozen by the integrator so the two halves cannot disagree. Read before changing a route, a field name or a status code.
---

# HTTP contract

Frozen 2026-10-10 by `3893e0ee`. `www/` and `tiers/` are built in parallel by
different arias, so this file is the only agreement between them. Change it by
asking the integrator, not by editing one side.

| method | path | returns |
|---|---|---|
| GET | `/` | the board HTML, built by `zanni-inline` |
| GET | `/api/lists` | `{"lists":[{"slug","title","items"}]}`, the inventory |
| GET | `/api/list/<slug>` | one list, shape below |
| GET | `/img/<sha256>` | image bytes, `Cache-Control: public, max-age=31536000, immutable` |
| GET | `/api/save/<slug>` | this user's arrangement, `{"assign":{"<id>":"<tier>"}}`, `{}` when none |
| PUT | `/api/save/<slug>` | accepts the same shape, 204 on success |

## `/api/list/<slug>`

```json
{
  "slug":  "peak-millenial-optimism",
  "title": "Peak Millenial Optimism",
  "tiers": ["S", "A", "B", "C", "D", "F"],
  "items": [
    { "id": "...", "name": "Kids", "sub": "MGMT", "img": "/img/<sha256>" }
  ]
}
```

**The board never sees a bucket key and never sees a remote URL.** The service
resolves both to `/img/<sha256>` or to `null`. `img_url` and `link` are not
sent unless `link` is later needed; ask first.

`img: null` means render a text chip. The board must handle it, because the
minimal example input has no images at all.

## Identity

The service keys saves on the `Remote-User` request header. Verified on the live
box 2026-10-10: Caddy **strips** inbound `Remote-User`, `Remote-Groups`,
`Remote-Email` and `Remote-Name` per site, then `forward_auth` to Authelia sets
them with `copy_headers`. So the header is trustworthy, and spoofing it from
outside does not work.

The board sends no identity of its own. It is a cookie-authenticated browser
session as far as it knows.

## Admin

Writes to the inventory require `group:gluck-tiers-admin`, read from
`Remote-Groups`. Everything else needs only `site-tiers-access`, which the
hostname derives automatically.

Admin is a **grant, not a branch**: there is no `if admin` in the read path, and
Gluck's own requests pass through exactly the checks any other user's do. That
pattern is El Portero's and it is not up for renegotiation.

## Errors

| case | status |
|---|---|
| unknown slug | 404 |
| unknown image sha | 404 |
| save body not an object of id to tier | 400, with the offending field named |
| tier not in the list's `tiers` | 400 |
| unknown item id in a save | 400 |

A save that references an item the list does not contain is rejected rather
than stored. Storing it would make a save that silently loses cards when the
list is refilled, and the loss would look like a UI bug.
