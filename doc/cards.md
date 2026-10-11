---
name: cards
description: Where the card inventory comes from, how to refill it from a Spotify playlist with no credential, and how to verify the upload. Read before swapping playlists or adding an API key.
---

# Where the cards come from

Method found and executed by aria `3dec6ffc`. Verified against the live bucket
by `3893e0ee` on 2026-10-10.

A Spotify playlist can be extracted with **no credential**. There is no Spotify
API key in hush, none is needed, and nobody should add one for this.

| step | endpoint | what it yields |
|---|---|---|
| 1 | `https://open.spotify.com/embed/playlist/<id>` | HTML carrying a `<script id="__NEXT_DATA__">` JSON blob. `props.pageProps.state.data.entity` holds `name` and `trackList`; each entry has `uri` (`spotify:track:<id>`), `title`, and `subtitle` (the artist) |
| 2 | `https://open.spotify.com/oembed?url=https://open.spotify.com/track/<id>` | `thumbnail_url`, the album cover. Take the trailing hash and read it at `https://i.scdn.co/image/<hash>` for the stable 300x300 |

Both are public and unauthenticated. Send a desktop User-Agent on step 1. Step 2
is one request per track; six in parallel finished 72 tracks in seconds.

## Mirroring, and why

Covers are mirrored into the `files` bucket under `tiers/img/<hash>.jpg` and
served by this service over loopback S3, content-addressed.

A remote `i.scdn.co` URL would make the viewer's phone request a third party for
every card on every load. This estate spent weeks reaching zero-by-default so
nothing leaks who looks at what, and a per-card third-party fetch is
inconsistent with that. Link rot is the lesser argument.

**Never point an `img` tag at `files.kelliher.info`.** That host is the ACL
gateway, so a viewer would need a read grant on `tiers/` to see a picture, and
rendering an image would start minting per-user ACL grants as a side effect.

Deduplicate on the hash. Tracks share albums, so distinct covers are fewer than
distinct tracks: 72 tracks, 61 covers in the first list.

## Verifying a refill

Verify by **listing the prefix**, not by the uploader's exit code, and scope the
listing: the whole `files` bucket holds 231 objects and 1.7 GiB, so a count of
the bucket proves nothing about `tiers/`.

Measured 2026-10-10, first list:

| check | result |
|---|---|
| items in `peak-millenial-optimism.json` | 72 |
| objects under `tiers/img/` | 61 |
| distinct `img` values | 61 |
| items with no `img` | 0 |
| `img` keys that resolve to an object | **72/72** |

Then negative-control the checker: assert that a key you know is absent is
reported missing. A cross-check that cannot fail is not a check. A missing key
must fail loudly at load or render a visible text chip, never a broken image.

## The service's credential

`gluck-tiers-ro`, key id `GKff3dd83092728e498842065b`, created 2026-10-10.
Read-only on the `files` bucket, proven by negative control: a `PutObject`
probe returned `AccessDenied`.

It is a separate key from `files-lister` and from `tfstate-rw` on purpose. One
key per consumer, so a grant can be revoked without taking a neighbour down.
The secret reaches the unit by `LoadCredential` as a file: never `Environment=`,
never argv.

Garage grants are per bucket, not per prefix, so this key can read all of
`files`, not only `tiers/`. That is the narrowest grant Garage 1.3.1 offers.
