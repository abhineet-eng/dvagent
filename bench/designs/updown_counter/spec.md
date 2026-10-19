# updown_counter: 8-bit up/down counter with programmable wrap

An 8-bit counter that counts up or down between 0 and a programmable maximum `max_val`, wrapping around at both ends. It can be loaded with a value.

## Ports

| Port | Dir | Width | Description |
|---|---|---|---|
| `clk` | in | 1 | clock, rising edge |
| `rst_n` | in | 1 | **asynchronous**, active-low reset |
| `en` | in | 1 | count enable |
| `up` | in | 1 | direction: 1 = up, 0 = down |
| `load` | in | 1 | synchronous load |
| `d` | in | 8 | load value |
| `max_val` | in | 8 | maximum count value (wrap point) |
| `count` | out | 8 | current count (registered) |
| `tc` | out | 1 | terminal count (combinational, see below) |
| `zero` | out | 1 | 1 when `count == 0` (combinational) |

## Behaviour

- While `rst_n` is 0, `count` is 0 immediately (asynchronous reset).
- At each rising clock edge (with `rst_n` = 1), in priority order:
  1. If `load` = 1: `count` becomes `d`, except that if `d > max_val` it becomes `max_val` (the load value is clamped).
  2. Else if `en` = 1 and `up` = 1: if `count >= max_val`, `count` becomes 0 (wrap); otherwise `count` increments by 1.
  3. Else if `en` = 1 and `up` = 0: if `count == 0`, `count` becomes `max_val` (wrap); otherwise `count` decrements by 1.
  4. Otherwise `count` holds.
- `tc` = 1 exactly when the next enabled count step will wrap: `en` = 1 and `load` = 0 and either (`up` = 1 and `count >= max_val`) or (`up` = 0 and `count == 0`). It is combinational from the current inputs and `count`.
- `max_val` may change at any time; comparisons always use its current value. Note that `count` can be larger than `max_val` if `max_val` is lowered; counting up from there wraps to 0 at the next enabled step.
- All comparisons are unsigned.
