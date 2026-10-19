# alu8: 8-bit ALU

A purely combinational 8-bit arithmetic logic unit. Outputs settle combinationally after any input change. There is no clock and no reset.

## Ports

| Port | Dir | Width | Description |
|---|---|---|---|
| `a` | in | 8 | operand A |
| `b` | in | 8 | operand B |
| `op` | in | 3 | operation select (table below) |
| `y` | out | 8 | result |
| `carry` | out | 1 | carry / borrow / shifted-out bit (see table) |
| `overflow` | out | 1 | signed (two's complement) overflow |
| `zero` | out | 1 | 1 when `y == 0` |
| `negative` | out | 1 | equals `y[7]` |

## Operations

`s` below means `b[2:0]` (the shift amount, 0 to 7). Upper bits of `b` are ignored by the shifts.

| `op` | Name | `y` | `carry` | `overflow` |
|---|---|---|---|---|
| 0 | ADD | `(a + b) mod 256` | 1 if `a + b > 255` (unsigned carry out) | 1 if `a` and `b` have the same sign bit and the sign bit of `y` differs from it |
| 1 | SUB | `(a - b) mod 256` | 1 if `a < b` as unsigned numbers (borrow) | 1 if `a` and `b` have different sign bits and the sign bit of `y` differs from the sign bit of `a` |
| 2 | AND | `a & b` | 0 | 0 |
| 3 | OR | `a \| b` | 0 | 0 |
| 4 | XOR | `a ^ b` | 0 | 0 |
| 5 | SHL | `(a << s) mod 256` | if `s == 0`: 0, else bit `a[8 - s]` (the last bit shifted out) | 0 |
| 6 | SHR | `a >> s` (logical, zeros shifted in) | if `s == 0`: 0, else bit `a[s - 1]` (the last bit shifted out) | 0 |
| 7 | SLT | 1 if `a < b` as **signed** 8-bit numbers, else 0 | 0 | 0 |

`zero` and `negative` are derived from `y` for every operation.
