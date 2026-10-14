---
name: ports
description: Why this service holds no TCP port, and the rule for reading the box before claiming one. Read before adding a service to the estate.
---

# Ports

`gluck-tiers` binds **no port**. It serves on `/run/kweb/gluck-tiers.sock`,
handed over by systemd and reachable only by Caddy; see
`doc/http-contract.md`. It held `127.0.0.1:9104` from 2026-10-10 until it moved
to the socket, and a port that trusts `Remote-User` is reachable by every
local process.

## The rule that chose the old port

Read the box at the moment you claim a port, with `ss -ltn`, rather than
inferring from the repo: services declare their ports in their own flakes and
no single file in `spain-flake` lists them all. 9103 was picked first from the
obvious pattern and was already listening. A port table in a doc is a dated
measurement, not a reservation.

9100 is left alone on purpose: it is the conventional Prometheus
`node_exporter` port, and netmon's observability work has every reason to want
it.
