# rr_arbiter: 4-way round-robin bus arbiter

Arbitrates one shared bus between 4 requesters. A requester that has been granted the bus keeps it for as long as it holds its request. When it releases the bus, the next owner is chosen in round-robin order, starting after the most recent owner.

## Ports

| Port | Dir | Width | Description |
|---|---|---|---|
| `clk` | in | 1 | clock, rising edge |
| `rst` | in | 1 | synchronous, active-high reset |
| `req` | in | 4 | `req[i]` = 1: requester i wants the bus |
| `grant` | out | 4 | registered, one-hot grant (or all zero when idle) |
| `owner` | out | 2 | index of the requester currently or most recently granted (registered) |
| `busy` | out | 1 | 1 when any `grant` bit is 1 (combinational from `grant`) |

## Behaviour

The arbiter remembers `last`, the index of the most recently granted requester. After reset, `last` = 3, `grant` = 0 and `owner` = 0.

At each rising clock edge (with `rst` = 0):

1. **Keep**: if `grant` is non-zero and `req[owner]` = 1, nothing changes (the owner keeps the bus).
2. **Arbitrate** otherwise: search the requesters in the order `last+1, last+2, last+3, last+4` (all modulo 4, so the previous owner is checked last). The first index `i` in that order with `req[i]` = 1 wins: `grant` becomes one-hot with bit `i` set, `owner` becomes `i`, and `last` becomes `i`.
3. If no requester is requesting, `grant` becomes 0. `owner` and `last` keep their values.

Notes:
- The hand-over has no idle cycle: at the edge where the owner's request is seen low, the next requester (if any) is granted.
- The previous owner can win again immediately if it is the only requester.
- At most one `grant` bit is ever 1.
