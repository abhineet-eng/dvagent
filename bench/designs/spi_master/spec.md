# spi_master: SPI mode-0 master

Performs 8-bit full-duplex SPI transfers in **mode 0** (CPOL = 0: SCLK idles low; CPHA = 0: data is sampled on SCLK rising edges and changed on SCLK falling edges). Data is sent and received **most significant bit first**.

## Parameter

| Name | Default | Description |
|---|---|---|
| `CLK_DIV` | 2 | number of `clk` cycles in each SCLK half period (SCLK low phase and high phase are each `CLK_DIV` cycles) |

## Ports

| Port | Dir | Width | Description |
|---|---|---|---|
| `clk` | in | 1 | system clock, rising edge |
| `rst` | in | 1 | synchronous, active-high reset |
| `start` | in | 1 | begin a transfer of `tx_data` (sampled only when not busy) |
| `tx_data` | in | 8 | byte to send on MOSI |
| `rx_data` | out | 8 | last byte received on MISO (registered, updated at the end of a transfer) |
| `busy` | out | 1 | 1 while a transfer is in progress |
| `done` | out | 1 | one-cycle pulse at the end of a transfer (registered) |
| `sclk` | out | 1 | SPI clock (registered) |
| `mosi` | out | 1 | master out, slave in (registered) |
| `miso` | in | 1 | master in, slave out |
| `cs_n` | out | 1 | chip select, active low (registered) |

## Behaviour

All outputs change only at rising edges of `clk`. After reset: `cs_n` = 1, `sclk` = 0, `busy` = 0, `done` = 0, `rx_data` = 0, `mosi` = 0.

A transfer is started by a rising `clk` edge with `start` = 1 while `busy` = 0 (call it edge 0). `tx_data` is captured at edge 0. Then, counting `clk` edges from edge 0, with `D = CLK_DIV`:

- At edge 0: `cs_n` goes to 0, `busy` goes to 1, and `mosi` shows `tx_data[7]`. `sclk` is 0.
- For bit k = 1 to 8:
  - at edge `(2k - 1) * D`, `sclk` rises and the master **samples `miso`** (the value of `miso` just before that `clk` edge). This is received bit number k, MSB first;
  - at edge `2k * D`, `sclk` falls. For k < 8, `mosi` changes at the same edge to the next transmit bit (`tx_data[7 - k]`).
- At edge `16 * D` (the 8th falling edge of `sclk`), the transfer ends: `cs_n` goes to 1, `busy` goes to 0, `rx_data` is updated with the 8 received bits, and `done` is 1 for exactly the following clock cycle.
- `start` is ignored while `busy` = 1. A new transfer can start at the edge after the transfer ended (during the `done` cycle).
- While `cs_n` = 1, the value of `mosi` is don't-care.

A slave connected to this master should put its first bit (MSB) on `miso` when `cs_n` falls and move to the next bit after each falling edge of `sclk`.
