---
name: fetching
description: What this service is allowed to fetch, why provenance rather than url shape decides it, and the limits on size and redirects. Read before adding any server-side fetch or touching mirror.ingest.
---

# Fetching

spain is the **house router**. On its loopback sit Garage on 3900, Authelia on
9091 and lldap on 17170, and `spain:17170` resolves only through its own
dnsmasq. A service on that box that fetches a url an attacker chose is an SSRF
with the whole estate behind it, so the fetch path is fenced in three ways.

## 1. Provenance, not url shape

`mirror.ingest(..., allow_remote=)` is a statement about **where the input came
from**, never about how the url looks.

| input | remote fetch | why |
|---|---|---|
| bucket object under `tiers/`, admin-controlled | **allowed** | it is how the browser never touches Spotify's CDN. The cover is fetched once, server-side, and served content-addressed |
| imported file, user-supplied | **never** | an uploaded list naming `img_url` would make the router fetch on a stranger's behalf. Images resolve only from hashes already mirrored, otherwise the card renders as a text chip |

A url that looks public is not evidence of anything: DNS is the attacker's to
choose. The caller declares provenance because only the caller knows it.

## 2. Address refusal, on the resolved address

`assert_fetchable` resolves the host and refuses loopback, private,
link-local, multicast, reserved and unspecified addresses, and any scheme that
is not `http` or `https`.

Verified, not reasoned:

| url | result |
|---|---|
| `http://127.0.0.1:3900/files` | blocked, Garage |
| `http://localhost:9091/` | blocked, Authelia |
| `http://192.168.2.1/` | blocked, the LAN |
| `http://169.254.169.254/latest/meta-data/` | blocked, cloud metadata |
| `http://[::1]:17170/` | blocked, lldap over v6 |
| `http://spain:17170/` | blocked, resolves private through dnsmasq |
| `file:///etc/passwd` | blocked, scheme |
| `https://i.scdn.co/image/abc` | **allowed**, so the guard is not a wall |

The last row matters as much as the others: a guard that refuses everything
proves nothing about whether it discriminates.

## 3. Redirects are refused outright

A redirect is a **second url, and the second one was never checked**.
Validating the first host and then following a 302 to `127.0.0.1` is the
standard way such a guard is defeated, so the opener raises on any redirect
rather than re-validating. A 302 from a CDN is rare; being wrong here is not
recoverable.

## Size

| limit | value | why |
|---|---|---|
| one image | 8 MiB | reads one byte past the cap and refuses, rather than trusting `Content-Length`, which the server chooses |

A 15 GB box that is also the house router cannot afford a forgiving parser or
an unbounded read.

## Known limit, written down rather than implied

This checks the address at resolution time, so a hostile DNS server could
answer public once and private on the connect that follows. Defeating that
needs the connection pinned to the validated address, which `urllib` does not
offer. The exposure is small because the only remote urls reaching this path
come from an admin-controlled bucket object, and it is recorded here so nobody
later reads this file as a promise it does not make.
