---
name: ports
description: The loopback port this service claims, how it was chosen, and every port already taken on spain at the time of claiming. Read before adding a service to the estate.
---

# Ports

`gluck-tiers` binds **127.0.0.1:9104**.

## How it was chosen

9103 was picked first, from the obvious pattern, and **9103 was already
listening**. Read off the box with `ss -ltn` at the moment of claiming, rather
than inferred from the repo, because services declare their ports in their own
flakes and no single file in `spain-flake` lists them all.

Taken on spain, 2026-10-10:

| port | 
|---|
| 22, 53 |
| 2019 |
| 3890, 3900, 3901, 3902, 3903 |
| 4317, 4318, 4320 |
| 5432 |
| 8008, 8780 |
| 9091, 9092, 9093, 9094, 9095, 9096, 9097, 9098, 9099 |
| 9101, 9102, 9103 |
| 17170, 20241, 37435, 65120 |

So 9100 and 9104 upward were free.

**9100 was deliberately left alone.** It is the conventional Prometheus
`node_exporter` port, and netmon already runs an OTLP receiver on 4317 and
4318. Taking 9100 would collide with observability work that has every reason
to want it.

## The rule this came from

Read the box at the moment you claim the port. A port table in a doc, this one
included, is a dated measurement and not a reservation: anything here is true
for 2026-10-10 and must be re-read before the next claim. The estate's
signature failure is a measurement quoted past its expiry.
