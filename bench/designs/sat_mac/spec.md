# sat_mac: saturating multiply-accumulate unit

A signed 8-bit x 8-bit multiply-accumulate (MAC) unit with a 16-bit accumulator that saturates instead of wrapping, as used in neural-network accelerators.

## Ports

| Port | Dir | Width | Description |
|---|---|---|---|
| `clk` | in | 1 | clock, rising edge |
| `rst` | in | 1 | synchronous, active-high reset |
| `valid` | in | 1 | multiply `a * b` and accumulate |
| `clear` | in | 1 | start a new accumulation |
| `a` | in | 8 | signed operand (two's complement, -128 to 127) |
| `b` | in | 8 | signed operand (two's complement, -128 to 127) |
| `acc` | out | 16 | signed accumulator (registered) |
| `sat` | out | 1 | sticky: saturation happened since the last clear/reset (registered) |

## Behaviour

Let `p = a * b` (signed product, -16256 to 16384). At each rising clock edge:

1. If `rst` = 1: `acc` = 0, `sat` = 0.
2. Else if `valid` = 1:
   - the base value is 0 if `clear` = 1, otherwise the current `acc`;
   - `s = base + p` computed exactly (no wrap);
   - if `s > 32767`: `acc` = 32767; if `s < -32768`: `acc` = -32768; otherwise `acc` = `s`;
   - `sat` becomes 1 if this step saturated. Otherwise it keeps its old value, except that when `clear` = 1 the old value is discarded (so `sat` is 0 unless this step saturated).
3. Else if `clear` = 1: `acc` = 0, `sat` = 0.
4. Otherwise both hold.

So `clear` together with `valid` starts a new sum with the current product (`acc` = `a * b`), while `clear` alone zeroes the accumulator.
