---
name: imports
description: Why an imported tier list stays in the browser, and what the rule is if persistence is ever wanted. Read before adding any write path to this service.
---

# Importing a list from a local file

Gluck asked for a button that reads a file off his machine. It parses through
**the same parser** as a bucket input: the three shapes in
`doc/input-format.md`, the same tolerances, the same skip-and-count behaviour.
There is no second code path, so a file that works as an import works as a
bucket object and the fixtures cover both.

## An import is ephemeral, and that is a security property

An imported list lives in the browser for the session. **It is not written to
the bucket.**

| if imports were persisted by this service | consequence |
|---|---|
| `gluck-tiers-ro` would need `PutObject` on `files` | a read-only credential becomes a write credential |
| the blast radius of a compromise | changes from "read objects the service already serves" to "write anything into the estate's file store" |

That credential is read-only deliberately, and it was negative-controlled: a
`PutObject` probe returned `AccessDenied`. Widening it to make a convenience
button slightly more convenient trades a real security property for nothing
anybody asked for.

## If persistence is ever wanted, the write does not go here

The rule, so the next aria does not quietly widen the credential:

**A persisted import must be written through El Portero's lister, under the
USER's own per-path write grant, not through this service's key.**

That is the whole point of the per-path ACL work: the lister is the gateway
for every request, grants are per path and inherit down the tree, and a write
is attributable to the human who made it. Writing through a service key makes
every write look like the service, which destroys attribution and bypasses the
grant model that already exists.

So the shape, if it is ever built:

| step | who |
|---|---|
| user picks a file | browser |
| parse and preview | this service, or the browser |
| upload to `tiers/<name>.json` | the **lister**, as the user, needing a write grant on that prefix |
| appear in the picker | this service, next listing |

This service stays read-only on the bucket in every version of that story.
