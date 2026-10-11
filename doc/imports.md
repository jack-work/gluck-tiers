---
name: imports
description: Why an imported tier list stays in the browser, why no persistence path exists at all, and the limits an import must enforce because it is user-supplied input. Read before adding any write path or any server-side fetch.
---

# Importing a list from a local file

Gluck asked for a button that reads a file off his machine. It parses through
**the same parser** as a bucket input: the three shapes in
`doc/input-format.md`, the same tolerances, the same skip-and-count behaviour.
There is no second code path, so a file that works as an import works as a
bucket object and the fixtures cover both.

## An import is ephemeral, and there is no alternative

An imported list lives in the browser for the session. **It is not written to
the bucket**, and it gets no slug and no URL.

| if imports were persisted by this service | consequence |
|---|---|
| `gluck-tiers-ro` would need `PutObject` on `files` | a read-only credential becomes a write credential |
| the blast radius of a compromise | changes from "read objects the service already serves" to "write anything into the estate's file store" |

That credential is read-only deliberately, and it was negative-controlled: a
`PutObject` probe returned `AccessDenied`.

## NO PERSISTENCE CONTRACT EXISTS. UNBUILT.

**Corrected 2026-10-11.** An earlier version of this file said a persisted
import should be written through El Portero's lister under the user's own
per-path **write** grant. **That mechanism does not exist.** Verified against
the running lister and its source by `ad2373f1`:

| claim | truth |
|---|---|
| the lister enforces per-path write grants | **false.** It enforces `read` and `list` only |
| the `write` column in the ACL table | **reserved and unenforced** |
| SigV4 uploads straight to Garage | **bypass the ACL engine entirely** |

So there is no "later, persist it through the lister" fallback to lean on.
There is no write path with user attribution anywhere in this estate today.
Imports are ephemeral because that is the only honest option, not because a
better one is being saved for later.

This correction is itself an instance of the rule in
`spain-flake/docs/deploying.md`: **reviewed prose is not a tested claim.** The
false sentence was reasoned confidently, written down, read back, and quoted
by the seat while it was quoting that very file. A design doc here once
asserted a bucket grant that did not exist and the first real upload disproved
it in thirty seconds. Mark a mechanism UNBUILT until something has exercised
it.

## An imported image resolves to a hash, or to nothing

This is a security boundary, not a parser detail.

An imported file names its own images. If an imported item could resolve a
**bucket key**, the service would read that key with **its own credential**,
and that credential has read on the entire `files` bucket, because Garage
1.3.1 grants per bucket and not per prefix. Three lines of JSON would then be
an arbitrary read of the whole file store:

```json
{ "items": [ { "name": "x", "img": "dad/rental-agreement.pdf" } ] }
```

The service would fetch an object the user holds no grant for, hash it, and
serve the bytes at `/img/<sha256>`, bypassing the per-path ACL engine
entirely rather than merely ignoring it, and minting a permanent capability
URL for the stolen object. The file in that example is the exact one the
acceptance test proved Gluck's father could not reach.

| an imported item's `img` | result |
|---|---|
| a bare `sha256` already in the mirror | accepted |
| `/img/<sha256>` already in the mirror | accepted |
| a well-formed sha that is **not** mirrored | refused, counted |
| a bucket key, anywhere, including inside `tiers/` | refused, counted |
| a remote URL, including one pointing at loopback | refused, counted |
| the same attack through `img_url` | refused, counted |

A refusal renders a visible text chip and appears in the rejection report. It
is never silent.

**Provenance decides, not location.** A bucket key inside `tiers/` is refused
too, because the question is who supplied the input, not where the object
lives. `allow_remote` and `allow_keys` are keyword-only with **no defaults**,
so a call site must state its permission in words; that change immediately
caught an internal call that had omitted one, failing with a `TypeError`
rather than quietly inheriting permission.

### How this is tested, and one choice worth copying

`bae66181` fired the payload above at a **real** object outside `tiers/`,
plus five variants, and asserted the mirror gained nothing each time.

The test **does not read the object it names.** Proving the service did not
fetch something does not require the test to fetch it, and a security test
that reads a private file to prove a private file was not read has exfiltrated
it to make its point. It counts mirror bytes before and after instead: no new
bytes means no fetch. That is also the stronger assertion, because it observes
the artifact rather than comparing hashes the test would have had to read the
file to compute.

And the guard **discriminates**, which is the half that makes it evidence: an
already-mirrored hash is accepted while an unmirrored one is refused. A guard
that refuses everything proves nothing about whether it is looking.

## An import is the most attackable surface on this service

It is the only input a user supplies directly. Three limits, all mandatory.

### Size limit

Enforce one, on the request and on the parse. A forgiving parser handed a
200 MB file is a denial of service against a 15 GB box that is also the house
router.

### NO REMOTE FETCH FROM AN IMPORTED FILE

An imported input may name `img_url`. **It must never be fetched.**

Spain is the house router. It holds a loopback Garage endpoint on 3900, a
loopback Authelia on 9091, lldap on 17170 and every other service bound to
127.0.0.1. A server-side fetch of a URL chosen by an uploaded file is an SSRF
into all of that, from the one machine on the estate where it hurts most.

| input source | remote URL in the file |
|---|---|
| bucket object, admin-controlled | fetched once, mirrored, served content-addressed. This is deliberate: it is how the browser never touches Spotify's CDN |
| **imported file, user-supplied** | **never fetched.** Images resolve only from keys already in the mirror, otherwise the card renders as a text chip |

The distinction is the **provenance of the input**, not the shape of the URL.
Harden the bucket path too: refuse any URL resolving to loopback, link-local or
private address space, because the admin path is not a trust boundary worth
betting the router on.

### Origin and CSRF

Check `Origin` on the import route and on every save route. The service sits
behind Authelia with a cookie session, so a cross-site form post carries the
user's identity for free unless something refuses it.

## Do not scrape the lister's HTML to find importable files

Named and forbidden. The lister's listing checks `ACL.list` on the **prefix**
and does **not** filter each displayed entry by `ACL.read`, so its HTML can
name files the viewer may not read. Turning that page into an import menu
would show a user a menu of things they cannot have.

The fix is not to filter it here. A second implementation of someone else's
authz drifts from it the first time a rule changes.

## What "download then import" buys

If per-user visibility is deferred, download-then-local-import gets nearly all
of it with **no new trust surface**: the lister already decides what the user
may download, as that user, and the file arrives in the browser where the
import path already handles it.

That makes the import button worth building well rather than minimally:

- accept a dropped file, not only a file chooser
- take the list's name from its contents, not from the filename
- say clearly what it rejected and why, with a count, because a tolerant
  parser that is silent about what it skipped is just a parser that loses data
