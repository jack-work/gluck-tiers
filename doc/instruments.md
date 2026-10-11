---
name: instruments
description: Diagnostics that lied on this project, what they actually measured, and the ground truth that replaced each one. Read before trusting any check, and add a row whenever an instrument fools you.
---

# Instruments that lied

Four arias, five instruments, one family: **the check ran, the check passed,
the check was not asking the question.** Every row below cost real time on one
night, 2026-10-10.

| instrument | what it looked like | what it actually measured | ground truth |
|---|---|---|---|
| `pgrep -f 'ssh -N -L 3900'` | a tunnel exists | **the text of the briefing that mentioned the command**, and later my own `grep` | `ss -ltn` on the listening socket |
| `aws s3 ls … \| wc -l` | 2 objects | 2 lines of an `AccessDenied` error | parse the listing, or check the exit status |
| `git merge --ff-only … \| tail -1; echo rc=$?` | the merge succeeded | **`tail`'s** exit status. The merge had aborted | check the status with no pipe, or `PIPESTATUS` |
| `ls -A /var/lib/gluck-tiers \| head -3; echo exit=$?` | an empty state directory | **`head`'s** exit status, swallowing `Permission denied`. `DynamicUser` relocates `StateDirectory` under root-only `/var/lib/private` | `sudo ls`, and disbelieve implausible emptiness |
| `${#P}` on a page in a shell | 42,568 bytes | 42,568 **characters**: the page holds ~1,100 multibyte UTF-8 characters | `Content-Length`, or `wc -c` |
| `curl` returning `302` | the site works | the Authelia gate answered. It says nothing about the app | follow it, and negative-control against a hostname that does not exist |
| `/` returning `200` | the board renders | the **template built**. `<script src="board.js">` was returning 404 and nothing ran | fetch the page, extract every asset, demand 200 each |

## The two that generalise

**A pipeline reports the LAST command.** Three of the seven rows are this. If
you intend to read a status, do not put a pipe in front of it.

**Implausibility is the signal, not the status.** The empty state directory and
the two-object bucket both returned success. Both were caught because the
*value* was absurd, never because the instrument complained.

## A rendered page is the only proof a page works

`/` is 200, every asset is 200, and the board can still be empty, because a
script that loads and throws satisfies both. The check that holds is: render
in a real browser against the **running service**, assert the tier rows exist
and the card count exceeds zero, and negative-control it by stripping the
script from the same page and watching the check go red.

## `Last-Modified` carries no information here

The board reports `Last-Modified: Thu, 01 Jan 1970 00:00:01 GMT` because Nix
zeroes mtimes in the store, which is what makes builds reproducible. The
`ETag` does all the revalidation work.

Do not "fix" the date. A real mtime would vary between otherwise identical
builds, and it would buy nothing: the document is served `no-store`, so there
is no revalidation to improve.

## A string replacement that matched nothing, and said it worked

Twice in one night, in this repo, a patch script of mine wrote code that was
never applied and reported success anyway:

```python
if 'TIERS_DEFAULT_SLUG' not in s and 'test_assets' in s:
    s = s.replace(old, new)        # old did not occur: no-op
    p.write_text(s)
    print("flake: asset check given an explicit default")
```

The guard tested the wrong thing, the replacement found no anchor, the file was
rewritten unchanged, and the script printed a confident sentence. The build
then failed somewhere else entirely, so the diagnosis cost two cycles: once for
`/` answering 503 because the environment variable never reached the derivation,
and once for `MAX_IMPORT_BYTES` being undefined at runtime because the
constants block was never inserted.

The tell was available and ignored both times: **the error was about a thing the
patch claimed to have fixed.**

| rule | why |
|---|---|
| assert the anchor before writing | `assert old in s, "anchor missing"` turns a silent no-op into a loud stop |
| never let the success message come from reaching the end of the script | it must come from observing the change |
| grep the file for the new text afterwards | one command, and it reads the artifact rather than the intention |

This is the same family as the `tail` that exited 0 for a failing `git`, the
`pgrep` that matched the text of a briefing instead of a process, and the proxy
that dropped the header it was measuring. The instrument reported on itself
rather than on the world.
