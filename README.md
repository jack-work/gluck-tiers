# gluck-tiers

A tier list at tiers.kelliher.info. Cards come from an input file on
files.kelliher.info, dragged between rows with a finger.

| dir | owner | holds |
|---|---|---|
| `www/` | UI worker | the board: markup, zanni components, the drag and drop |
| `tiers/` | service worker | the python service: parser, image mirror, saves |
| `examples/` | service worker | example input files, one deliberately minimal |
| `doc/` | both | reasoning, skilldoc-shaped, one file per subject |

Two workers share this repo and must not edit each other's directory.
