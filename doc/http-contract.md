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
| GET | `/` | **302 to the default list**, so the url already on his phone keeps working |
| GET | `/l/<slug>` | the board HTML for one list, built by `zanni-inline` |
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

## Addendum, 2026-10-11: lists are addressable

Two lists exist on the bucket now, so a list needs a URL.

| was | is |
|---|---|
| `/` served the board and the board chose a list | `/l/<slug>` serves the board for one list |
| nothing was linkable | every list is linkable |

`/` **must keep working**: it redirects, 302, to the default list. Gluck
already has `https://tiers.kelliher.info` in his phone and a URL that stops
working is a bug regardless of what replaced it.

The picker reads `/api/lists` and links to `/l/<slug>`. It already carries the
winning `source` key per slug, so which input file won is visible rather than
inferred.

### Import

An imported file is parsed and held **in the browser**. It is never written to
the bucket, and this service's Garage key stays read-only. See `doc/imports.md`
for why, and for the rule if persistence is ever wanted: the write goes through
the lister under the user's own grant, never through the service key.

An imported list is addressable only as the browser's current state. It gets no
slug and no URL, because a URL that only works in one browser session is worse
than no URL.
