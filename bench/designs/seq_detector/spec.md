# seq_detector: serial "1011" pattern detector

Watches a serial bit stream and reports every occurrence of the bit pattern **1011** (first received bit first). Occurrences may overlap: in the stream `1011011`, the pattern is found twice.

## Ports

| Port | Dir | Width | Description |
|---|---|---|---|
| `clk` | in | 1 | clock, rising edge |
| `rst` | in | 1 | synchronous, active-high reset |
| `din` | in | 1 | serial data bit |
| `din_valid` | in | 1 | `din` is sampled only when this is 1 |
| `match` | out | 1 | registered match pulse |
| `count` | out | 8 | number of matches since reset, saturating at 255 |

## Behaviour

- A bit is received at a rising clock edge where `din_valid` = 1. Edges where `din_valid` = 0 are ignored completely: they neither add a bit to the stream nor break a partial match.
- `match` is a registered output. It is 1 for exactly one clock cycle, the cycle that follows the rising edge at which the final `1` of a `1011` occurrence was received. At every other edge it becomes 0.
- `count` increments by 1 at the same edge where `match` is set to 1, and stays at 255 once it reaches 255 (it never wraps).
- After a match, detection continues with overlap: the trailing `1` can be the first bit of the next occurrence (`1011011` gives two matches; `10111011` gives two matches).
- Reset (at a rising edge with `rst` = 1) clears `match` and `count` to 0 and forgets any partially received pattern.
