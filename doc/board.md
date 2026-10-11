---
name: board
description: How the tier board drags, drops and saves, the boil policy and the measurements behind it, and what could not be measured on this workstation. Read before changing the drop logic, the thresholds or the filter policy.
---

# The board

`www/board.html.in` plus the script inside it. Built by `zanni-inline`, checked
by `zanni-check` in the same derivation that ships it.

## heft gives the gesture, not the drop

Read out of `zanni/assets/heft/heft.js` rather than assumed:

| heft does | heft does not |
|---|---|
| arms every `.heft` automatically, including nodes added later | hit test |
| begins a drag past 8px, and not if a text selection started | know about drop targets |
| moves by the CSS `translate` property, so it never fights an animation | reparent anything |
| `body.hefting` raises the `.heft-lift` **ancestor** | emit a drop event |
| `touch-action: none`, no native image drag, no selection halo | |
| on release, snaps back to origin over 650ms | |

The snap-back is the feature. A drop into a row reparents the card, so the
reset is invisible; an invalid drop is left alone and the snap-back **is** the
correct "it goes home", already curved.

## The drop

| decision | why |
|---|---|
| rectangle hit test over `.drop` | the dragged card sits under the finger, so `elementFromPoint` returns the card and `closest('.drop')` resolves to the row it is **leaving** |
| own `pointerdown`/`pointerup` pair, 8px threshold | matches heft's `SLACK2`. Reading heft's classes instead would race its 720ms `settling` timer |
| clear `.settling` and `translate` on a valid drop | otherwise the card springs from its new slot by the delta of a drag that is over |
| insert by nearest card centre, `y` weighted twice `x` | rows wrap, so vertical proximity matters more |
| page autoscroll within 64px of an edge | six rows plus 72 cards do not fit a phone |

Listener order is on our side: heft registers its window `pointerup` during
`arm()` at DOMContentLoaded, so a listener added afterwards runs after heft has
released. Verified in a browser, not reasoned about.

## Saves

Keyed on **item id**, never on array index or name, so refilling a list does
not scramble an arrangement.

`assign` carries **only ranked cards**. A card absent from `assign` is
unranked. The alternative, storing `""` for the pool, would collide with the
contract's rule that a tier must be one of the list's `tiers`.

## Images

The board never sees a bucket key or a remote URL; the service resolves both to
`/img/<sha256>` or `null`. `null` renders a text chip, and an `img` that fails
to load is converted to the same chip by an `error` handler, because a broken
image icon is a bug rather than a fallback.

61 covers serve 72 cards, since tracks share albums. Nothing is keyed on the
image.

## Boil policy, and the measurement that failed

**Shipped: boil on the title and the row headers. Cards plain.**
`?boil=cards` switches cards on and exists only so the question can be settled
on real hardware.

Measured in Chromium 152, `--disable-gpu`, 390x844, 2026-10-10:

| variant | filtered area | drag, frames over 20ms | scroll, frames over 20ms |
|---|---|---|---|
| plain | 0 px² (row heads 22,245 px²) | 0 of 58 | 0 of 58 |
| boiled | **578,921 px²** | 0 of 58 | 0 of 58 |

The variant was confirmed applied: 72 of 72 cards computed
`filter: url("#pixel-text")`.

**Those numbers are not evidence, and the record should say so.** Identical
frame times across a 578,921 px² difference in filtered area is implausible,
and implausibility is a signal. In headless Chromium `requestAnimationFrame`
ticks on a BeginFrame timer that does not wait for rasterisation, so frame
cadence is decoupled from the cost being asked about. Reporting "no dropped
frames, boiling is free" would have been a check that passed without asking the
question.

`chrome.gpuBenchmarking.runMicroBenchmark('rasterize_and_record_micro')` is the
right instrument and is wired up in `test/raster-bench.js`. It timed out twice
on this workstation. **Raster cost was therefore not measured.**

The decision does not depend on it: 578,921 against 22,245 px² is 26x, and
26x the raster budget of the entire visible chrome is not worth spending on
thumbnails nobody asked to shimmer. What would settle it: the microbenchmark on
a machine with a GPU, or the page on Gluck's actual phone.

Two facts that make the drag the cheap case either way, so the open question is
scrolling rather than dragging: `heft.css` sets `filter: none` on `.held`, and
`zanni/docs/motion.md` establishes that moving a filtered element does not
re-rasterise it.

## Testing

`test/drag-harness.html` drives the real page in an iframe with real pointer
events and posts a verdict to the dev server. `test/measure-boil.sh` runs both
variants.

Its negative controls, which all fire:

| control | asserts |
|---|---|
| drop outside every zone | the card does **not** move |
| press under 8px | not treated as a drag |
| a real drop after both | the suite can still detect success |

Two of its own checks had to be repaired after lying:

- "heft armed every card" passed against **zero** cards, because the iframe
  reference pointed at the discarded `about:blank`. `[].every()` is `true`.
  It now asserts a non-empty set.
- the runner's wait tested for the result **file**, which its own heartbeat
  created, so the browser was killed mid-measurement. It now waits for a
  verdict field.

Firefox on this workstation could not run the harness at all: a trivial page
that only posts a timestamp also failed. Chromium from the nix store works.
