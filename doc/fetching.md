---
name: fetching
description: Why this service makes no outbound HTTP at all, the two ceilings on what a bucket input may name, and the cache window on mirrored assets. Read before adding any fetch, widening a key rule, or touching the /img route.
---

# Fetching

**This service makes no outbound HTTP requests.** There is no url branch, no
opener, no address guard, because there is nothing left to guard.

## Why the guard was deleted rather than fixed

An earlier version resolved a hostname, refused loopback, private, link-local
and reserved addresses, and refused redirects. El Inspector defeated it with a
resolver that answered **public on the check and loopback on the connect**:
`urllib` resolves again when it opens the socket, so the check and the
operation asked about different moments. The shipped module fetched and cached
a loopback sentinel.

Literal loopback was correctly refused, which is what made the bypass real
rather than theoretical: the guard worked, and still did not hold.

Repairing it needs the connection pinned to the validated address, which
`urllib` does not offer. So the capability is gone, including the
`allow_remote` parameter, because **a capability nobody may use is still a
capability** and the next author will find a use for it.

| was | is |
|---|---|
| `assert_fetchable`, `_NoRedirects`, `_OPENER` | deleted |
| `allow_remote` parameter | deleted |
| a url in any input | refused and counted |

`test_boundary.py` asserts the absence **by AST**, not by grep: it walks each
module for a network import or a `urlopen` call. A first attempt grepped the
source text and failed on the comment explaining why urllib was removed, which
is an instrument reporting on itself. The AST check also negative-controls
itself, and deliberately does **not** flag `urllib.parse`, which is a string
parser the origin check needs. A check that forbids too much is one somebody
relaxes carelessly later.

## The consequence, stated rather than discovered

The `.txt` fixture names remote `i.scdn.co` covers, so **those cards now render
as text chips**. That is correct and acceptable:

- the `.json` wins by suffix precedence for the same slug, and it carries
  bucket keys
- mirroring covers into the bucket is the **refill step's** job, which runs on
  a workstation, not on the house router

Fetching 61 covers is a workstation's work. spain is the router.

## Two ceilings on a bucket input

An admin-controlled input may name a bucket key, and only within these:

| ceiling | rule | why |
|---|---|---|
| **prefix** | the key must sit under `TIERS_PREFIX` after normalisation, with no leading slash, no backslash and no traversal | the service's Garage grant is per **bucket**, not per prefix, so an unconstrained key meant every object in `files` |
| **content** | the bytes must sniff as jpeg, png, gif or webp | an earlier `_ext` returned `.bin` for unknown magic, so any object was mirrored and served as `application/octet-stream` |

Both refusals are loud and counted, in the same shape as an import's: the card
renders as a visible text chip and the reason names the rule.

There is no `.bin` fallback and `Content-Type` comes from the **sniffed magic**,
never from the key's extension, because the key is chosen by whoever wrote the
input file.

## The cache window on `/img/<sha256>`

```
private, max-age=3600
```

Not `public`, not a year, not `immutable`.

A content-addressed path is a **capability URL**: whoever holds it holds the
bytes, with no expiry, no revocation and no audit. It leaks nothing today
because every route is gated, but two consequences stood out:

- deleting a source list did not unpublish its cached assets
- **a hash is not an authorization policy**

The bytes remain immutable per hash, so correctness is unaffected. Only the
publication window shrinks.

## What an import may name

Nothing on this page. An imported list resolves images **only** to a hash
already in the mirror, so it can reuse a cover an admin-controlled input
brought in and reach nothing else. See `doc/imports.md`.
