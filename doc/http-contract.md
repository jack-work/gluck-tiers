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

**The header is trustworthy only because Caddy is the only way in.** The
service reads `Remote-User` for identity and `Remote-Groups` for admin, and
checks neither against anything. So anything that reaches `127.0.0.1:9104`
without passing through Caddy can claim to be anyone, including admin, by
sending a header.

That happened on 2026-10-10. `3893e0ee` left an `ssh -L 9104` forward and three
local proxies that injected `Remote-Groups: gluck-tiers-admin` running on the
workstation for two days, so every process there, every aria included, could
act as Gluck with admin. Found by another aria, closed 2026-10-13.

| when you need the unit directly | do |
|---|---|
| a forward or a header-injecting proxy | start it in the same command that uses it, and kill it in that command too |
| anything that must outlive one command | do not. Go through `https://tiers.kelliher.info` |

Spain's own loopback carries the same trust: any process on the box can do
what the forward did. That is the estate-wide `mkPythonService` model, shared
with portero mint, and not something this service can fix alone.

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

## The default list, stated rather than discovered

`/` redirects, 302, and what it redirects to is decided in one place:

| condition | default |
|---|---|
| `TIERS_DEFAULT_SLUG` is set | that slug, **verbatim** |
| otherwise | the **alphabetically first** slug in the inventory |
| no lists at all | 503 naming the reason, never a redirect loop |
| the bucket is unreachable | 503 naming the error |

An explicit default is used verbatim even when no such list exists, so a typo
produces a 404 naming the slug instead of silently serving a different list.
Alphabetical order is chosen because it is stable across listings; directory
order is not.

`/l/<slug>` serves the **same document** for every list. The slug lives in the
URL and the inlined script reads it from there, so there is no template per
list. The document is a shell and is not the authority on whether a list
exists: `/api/list/<slug>` is. When the bucket is reachable an unknown slug is
refused at `/l/` as a courtesy; when it is not, the shell is served and the API
reports the truth. Serving a shell is never wrong, but claiming a list exists
would be.

## Origin, on every state-changing route

`PUT /api/save/<slug>` requires an `Origin` header matching the request's host.

The session is a cookie, so without this a cross-site request carries Gluck's
identity for free. This was live until 2026-10-10: a grep for `Origin`,
`Referer` or `CSRF` returned nothing.

| request | result |
|---|---|
| `Origin` matching the host | proceeds |
| `Origin` from anywhere else | 403 naming the origin |
| **no `Origin` at all** | 403 |

Refusing an absent `Origin` is a deliberate choice, not an oversight. Browsers
send it on every non-GET fetch, so absence means a non-browser caller, and this
service has none. Reads are exempt because they change nothing.
