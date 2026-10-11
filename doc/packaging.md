---
name: packaging
description: Why this service ships as a derivation holding its whole tree rather than as a single entrypoint file, and the negative control that proves the packaging check can fail. Read before changing flake.nix or adding a module.
---

# Packaging

`mkPythonService` builds its unit as:

```
ExecStart = "${py}/bin/python ${entrypoint}"
```

`entrypoint` is a nix path. Passing `./tiers/main.py` copies **that one file**
into the store, so `import parse` fails at startup. The suite does not notice,
because the suite runs in a working directory where every module exists.

That is not a hypothetical. On this estate it shipped 51 green tests and two
units that both died at import on `ModuleNotFoundError`.

## The choice

| option | why not / why |
|---|---|
| collapse to one file | cannot fail this way, but puts the parser, the mirror and the store in one unreviewable file |
| **ship the tree, point `entrypoint` inside it** | chosen. `mkApp` copies `tiers/*.py` into `$out` and the unit runs `${app}/main.py` |

## The two checks, which must be able to disagree

| check | runs against | what it proves |
|---|---|---|
| `tiers/tests/test_parse.py` | the **source** tree | the parser is correct |
| the packaging check in `mkApp` | `$out` **alone**, via `PYTHONPATH=$out` | every import the entrypoint needs actually shipped |

They are separate on purpose. A green suite is not evidence about the artifact,
and conflating the two is the exact mistake this file exists to prevent.

## The negative control, kept rather than performed

`checks.packaging-negative-control` ships the tree **minus `mirror.py`** and
asserts the import **fails**. It also asserts it failed for the right reason,
by grepping for `No module named 'mirror'`, because an import can break for
reasons that have nothing to do with packaging and a check that accepts any
failure is barely a check.

If that derivation ever succeeds, the packaging check in `mkApp` is worthless
and the build says so out loud.

Run it:

```sh
nix build .#checks.x86_64-linux.packaging-negative-control --print-build-logs
```

## Why the API suite is not in the derivation

`tiers/tests/test_api.py` reads the real bucket over the loopback tunnel and
mirrors the real covers. A nix build sandbox has no network, correctly, so that
suite cannot run inside a derivation and is not pretended into one. It runs
outside, against the real dependency, because a mock that encodes your
assumption cannot falsify it.

| suite | where | needs |
|---|---|---|
| `test_parse.py` | inside the derivation | nothing |
| `test_api.py` | outside, by hand or in CI with a tunnel | `ssh -N -f -L 3900:127.0.0.1:3900 spain@spain` and a credential file |

## The credential

The code takes a **credential file path**, never a key and secret:

| environment | path used |
|---|---|
| deployed | `$CREDENTIALS_DIRECTORY/garage`, from `LoadCredential` |
| local | `TIERS_CREDENTIALS_FILE`, or `~/.config/gluck-tiers/credentials` |

`mkPythonService` has no `credentials` parameter, unlike `mkScheduledJob`, so
the unit gets it through `extraServiceConfig.LoadCredential`. Worth upstreaming
a `credentials` parameter to `gluck-service-lib` for symmetry; not done here.

Never `Environment=`, never argv, never printed.
