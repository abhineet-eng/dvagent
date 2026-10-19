# apb_regs: APB3 register block

An AMBA APB3 slave with four 32-bit registers. Accesses to the DATA register take one wait state. Invalid accesses get an error response (`pslverr`).

## Ports

| Port | Dir | Width | Description |
|---|---|---|---|
| `pclk` | in | 1 | clock, rising edge |
| `presetn` | in | 1 | **asynchronous**, active-low reset |
| `psel` | in | 1 | slave select |
| `penable` | in | 1 | second (ACCESS) phase of a transfer |
| `pwrite` | in | 1 | 1 = write, 0 = read |
| `paddr` | in | 8 | byte address |
| `pwdata` | in | 32 | write data |
| `prdata` | out | 32 | read data |
| `pready` | out | 1 | transfer completes in this ACCESS cycle |
| `pslverr` | out | 1 | error response (valid when `pready` = 1 in an ACCESS cycle) |

## APB transfer (standard APB3)

- SETUP cycle: master sets `psel` = 1, `penable` = 0, and drives `paddr`, `pwrite`, `pwdata`.
- ACCESS cycle(s): master sets `penable` = 1 and keeps all other signals stable. The transfer completes at the rising edge of the first ACCESS cycle in which `pready` = 1. Then the master either starts another transfer (SETUP) or sets `psel` = 0.

## Register map

| Address | Name | Access | Reset | Description |
|---|---|---|---|---|
| `0x00` | CTRL | read/write | `0x00000000` | only bits [7:0] are stored; bits [31:8] read as 0 |
| `0x04` | DATA | read/write | `0x00000000` | 32-bit storage; **every access has one wait state** |
| `0x08` | STATUS | read-only | `0x00000000` | bits [15:0] = number of successful writes since reset (wraps at 65536); bits [31:16] read as 0 |
| `0x0C` | ID | read-only | `0xA5B00001` | constant identification value |

Any other address (including addresses that are not multiples of 4) is invalid.

## Behaviour

- `pready` is 1 in every cycle, except in the **first** ACCESS cycle of a transfer to address `0x04` (DATA), where it is 0. So a DATA transfer has SETUP, one ACCESS cycle with `pready` = 0, then one ACCESS cycle with `pready` = 1. All other transfers complete in their first ACCESS cycle.
- `pslverr` is 1 only in the completing ACCESS cycle (`psel` = 1, `penable` = 1, `pready` = 1) of an erroneous transfer, and 0 at all other times. A transfer is erroneous when the address is invalid, or when it is a write to a read-only register (STATUS or ID).
- **Writes** take effect at the rising edge that completes a non-erroneous write transfer: CTRL stores `pwdata[7:0]`, DATA stores `pwdata`. Each such successful write (to CTRL or DATA) increments the STATUS write counter by 1. Erroneous writes change nothing.
- **Reads**: in the completing ACCESS cycle of a read, `prdata` holds the register value (as listed above). For an invalid address `prdata` is 0. `prdata` is don't-care in all other cycles.
- `presetn` = 0 immediately resets all registers and the write counter (asynchronous reset).
