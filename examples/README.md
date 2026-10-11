# examples

| file | shape | why it exists |
|---|---|---|
| `peak-millenial-optimism.json` | canonical JSON | the real first list, 72 tracks, 61 covers, bucket keys |
| `peak-millenial-optimism.txt` | line format | the same list, remote URLs, artist folded into field one |
| `minimal.txt` | line format | bare names, no images, no tiers line. The shape to imitate |
| `films.csv` | CSV | music words as aliases, and two rows with no image |

Images are optional everywhere. A card without one renders as a text chip.

| `messy.txt` | line format | what a human actually types: a BOM, CRLF endings, uppercase `TIERS:` with spaces, a stray separator, a trailing pipe, a comment left mid-file |

Tolerances the parser owes a hand-written file are in `doc/input-format.md`.
A row it cannot read is skipped and **counted**, never silently dropped: the
count reaches `/api/status`.
