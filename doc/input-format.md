---
name: input-format
description: The accepted input shapes for a tier list, the canonical JSON schema, and the tolerances the parser owes a hand-written file. Read before changing the parser or writing an example.
---

# Input format

Three shapes are accepted. JSON is canonical and is what a generator should
emit. The other two exist because Gluck will hand-write lists later, and the
examples he imitates must be forgiving.

## Canonical JSON

Accepted and in use as of 2026-10-10, verified against
`tiers/peak-millenial-optimism.json`, 72 items.

```json
{
  "title": "Peak Millenial Optimism",
  "source": "<where it came from, free text>",
  "tiers": ["S", "A", "B", "C", "D", "F"],
  "items": [
    {
      "id":      "stable identity, used as the key for saved arrangements",
      "name":    "Kids",
      "sub":     "MGMT",
      "img":     "tiers/img/<hash>.jpg",
      "img_url": "https://i.scdn.co/image/<hash>",
      "link":    "optional, opens the thing"
    }
  ]
}
```

| field | required | notes |
|---|---|---|
| `id` | yes in practice | saved arrangements key on it. If absent, derive a slug from `name` plus `sub`. **Changing an id orphans a save** |
| `name` | yes | the card's first line |
| `sub` | no | the second line. Two Blur songs are indistinguishable at thumbnail size, which is why this field exists |
| `img` | no | a **bucket key**, read over loopback S3 |
| `img_url` | no | the original remote URL. Fallback and provenance only. Not what the page loads |
| `link` | no | optional target |

A card with no image renders as a text chip. Thumbnails are optional, never
required.

## Line format

```
# Peak Millenial Optimism
tiers: S,A,B,C,D,F
Kids | MGMT | tiers/img/abc.jpg
Walking On A Dream | Empire Of The Sun | https://i.scdn.co/image/<hash>
Lisztomania
```

Field count decides the meaning, because a hand-written file will not be
consistent:

| fields | reading |
|---|---|
| 3 | `name`, `sub`, image |
| 2, second looks like an image | `name`, image, no `sub` |
| 2, otherwise | `name`, `sub` |
| 1 | `name` only |

"Looks like an image" means an `http(s)` URL, or a bucket key ending in a known
image extension. Decide by **inspection, not by position**.

The shipped fixture `tiers/peak-millenial-optimism.txt` is the 2-field
image case and folds the artist into field one as `Kids - MGMT`. Do **not**
split on `" - "` by default: song and film titles contain hyphens, and a
heuristic that is right 90% of the time produces a list that looks correct and
is wrong in ways nobody audits. If a file wants that split, it asks for it:

```
split: " - "
```

## CSV

A header row naming at least a name column. `name`, `title` and `card` all mean
the name; `sub`, `subtitle` and `artist` all mean the second line; `img`,
`image` and `thumbnail` all mean the image. Unknown columns are ignored rather
than fatal.

## Aliases, generally

The parser canonicalises before it validates. `artist` and `subtitle` become
`sub`; `image` and `thumbnail` become `img`. A generic app should not make a
music list a special case, but a music list is what exists, so the music words
are accepted.

## Images

An image slot may hold a bucket key or a remote URL, and both appear in real
files. The service resolves them the same way:

| slot holds | what happens |
|---|---|
| bucket key | read over loopback S3, served content-addressed |
| remote URL | fetched **once** server-side, mirrored, then served content-addressed |

So the browser never requests a third party, whatever the input said. See
`cards.md` for why that matters.

## Failure, which must be loud

An `img` key that resolves to no object must fail at load or render a visible
text chip. It must never emit a broken image tag. This estate has shipped more
than one check that passed without asking the question.
