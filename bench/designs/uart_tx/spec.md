# uart_tx: UART transmitter

Serialises one byte per request into a standard asynchronous serial (UART) frame:
1 start bit (0), 8 data bits **least significant bit first**, an optional parity bit, and 1 stop bit (1).

## Parameter

| Name | Default | Description |
|---|---|---|
| `CLKS_PER_BIT` | 4 | number of clock cycles each bit lasts on `tx` |

## Ports

| Port | Dir | Width | Description |
|---|---|---|---|
| `clk` | in | 1 | clock, rising edge |
| `rst` | in | 1 | synchronous, active-high reset |
| `start` | in | 1 | request to send `data` (sampled only when idle) |
| `data` | in | 8 | byte to send |
| `parity_en` | in | 1 | 1: send a parity bit after the data bits |
| `parity_odd` | in | 1 | parity type when enabled: 0 = even, 1 = odd |
| `tx` | out | 1 | serial output (registered), 1 when idle |
| `busy` | out | 1 | 1 while a frame is being sent |
| `done` | out | 1 | one-cycle pulse after a frame completes (registered) |

## Behaviour

- After reset: `tx` = 1, `busy` = 0, `done` = 0.
- When idle (`busy` = 0), a rising edge with `start` = 1 begins a frame. `data`, `parity_en` and `parity_odd` are captured at that edge; later changes to them do not affect the frame. `start` is ignored while `busy` = 1.
- From the edge that accepts `start`, `tx` outputs, each for exactly `CLKS_PER_BIT` clock cycles and with no gaps:
  1. the start bit (0),
  2. `data[0]`, `data[1]`, ..., `data[7]`,
  3. if `parity_en` was 1: the parity bit. Even parity: the bit makes the total number of 1s in the 8 data bits plus the parity bit even (it equals the XOR of the data bits). Odd parity: the inverse,
  4. the stop bit (1).
- `busy` is 1 from the edge that accepts `start` until the stop bit has lasted `CLKS_PER_BIT` cycles. At that edge `busy` becomes 0 and `done` becomes 1 for exactly one clock cycle. `tx` stays 1 while idle.
- A new `start` can be accepted at the edge right after the frame ends (during the cycle where `done` = 1), giving back-to-back frames with no idle bit between the stop bit and the next start bit.

So a frame lasts `10 * CLKS_PER_BIT` cycles without parity and `11 * CLKS_PER_BIT` cycles with parity.
