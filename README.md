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

## Working in this repo while others are

Three arias share this worktree, which means they share the **git index**.

| do | not |
|---|---|
| `git commit --only <paths>` | a bare `git commit`, however carefully you staged |
| `git pull --ff-only` before you commit | assuming your last read is current |
| read `git show --stat HEAD` after committing | trusting that `git add` scoped it |

`git add <paths>` followed by `git commit` commits **the whole index**,
including whatever a neighbour had staged. That happened twice here on the
first night, the second time after the rule "add paths, not everything" had
already been agreed, which is how we learned the rule was wrong.

`--only` commits the named paths and leaves every other index entry staged for
its owner.

Generated artifacts do not belong in git. The derivation inlines
`www/board.html.in` into `templates/board.html` and runs `zanni-check` on the
result, so a page committed next to its source is a second artifact with no
mechanism keeping it in step.
