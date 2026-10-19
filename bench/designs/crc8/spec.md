# crc8: byte-wide CRC-8 engine

Computes the CRC-8 of a byte stream, one byte per clock cycle.

CRC parameters: width 8, polynomial `0x07` (x^8 + x^2 + x + 1), initial value `0x00`, no input or output reflection, no final XOR. This is the common "CRC-8" (also called CRC-8/SMBUS). Its check value for the ASCII string `123456789` is `0xF4`.

## Ports

| Port | Dir | Width | Description |
|---|---|---|---|
| `clk` | in | 1 | clock, rising edge |
| `rst` | in | 1 | synchronous, active-high reset |
| `init` | in | 1 | synchronous restart of the CRC |
| `valid` | in | 1 | `data` holds a byte to add to the CRC |
| `data` | in | 8 | input byte |
| `crc` | out | 8 | CRC of all bytes accepted since the last reset/init (registered) |
| `nbytes` | out | 8 | number of bytes accepted since the last reset/init, wraps from 255 to 0 (registered) |

## Behaviour

At each rising clock edge:

1. If `rst` = 1 or `init` = 1: `crc` becomes `0x00` and `nbytes` becomes 0. `valid` is ignored in that cycle.
2. Else if `valid` = 1: the byte `data` is processed, most significant bit first, and `crc` becomes the updated CRC; `nbytes` increments by 1 (wrapping at 256).
3. Otherwise both outputs hold.

Reference algorithm for one byte (all values 8 bits):

```
r = crc XOR data
repeat 8 times:
    if r[7] == 1:  r = ((r << 1) mod 256) XOR 0x07
    else:          r = (r << 1) mod 256
new crc = r
```
