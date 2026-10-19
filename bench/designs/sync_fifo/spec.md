# sync_fifo: 8-entry synchronous FIFO

An 8-deep, 8-bit wide synchronous FIFO with **first-word fall-through** output (the oldest entry is always visible on `dout` without popping first), occupancy count, and sticky overflow/underflow error flags.

## Ports

| Port | Dir | Width | Description |
|---|---|---|---|
| `clk` | in | 1 | clock, rising edge |
| `rst` | in | 1 | synchronous, active-high reset |
| `push` | in | 1 | write request |
| `din` | in | 8 | write data |
| `pop` | in | 1 | read request |
| `dout` | out | 8 | oldest entry (valid only when `empty` = 0) |
| `full` | out | 1 | `count == 8` |
| `empty` | out | 1 | `count == 0` |
| `almost_full` | out | 1 | `count >= 6` |
| `count` | out | 4 | number of stored entries, 0 to 8 |
| `overflow` | out | 1 | sticky: a push was rejected |
| `underflow` | out | 1 | sticky: a pop was rejected |

## Behaviour

All state changes happen at the rising clock edge. `full`, `empty`, `almost_full` and `dout` are combinational functions of the stored state.

- **Pop** is accepted when `pop` = 1 and the FIFO is not empty. The oldest entry is removed.
- **Push** is accepted when `push` = 1 and either the FIFO is not full, or a pop is accepted in the same cycle (so a full FIFO can push and pop simultaneously, keeping `count` at 8). The value `din` is stored as the newest entry.
- On an empty FIFO, `push` = 1 and `pop` = 1 together: the push is accepted, the pop is rejected (there is nothing to read yet).
- `count` increases by 1 when only a push is accepted, decreases by 1 when only a pop is accepted, and holds otherwise.
- `overflow` becomes 1 when `push` = 1 but the push is rejected. `underflow` becomes 1 when `pop` = 1 but the pop is rejected. Both stay 1 until reset.
- `dout` always shows the oldest stored entry while `empty` = 0. Its value while empty is unspecified.
- Reset (rising edge with `rst` = 1) empties the FIFO and clears `count`, `overflow` and `underflow`. Push and pop are ignored during reset.
