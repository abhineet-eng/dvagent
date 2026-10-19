# DVAgent benchmark results

Model: `gemini-3.5-flash-lite` via gemini, run 2026-10-19 18:27:00. 10 designs, 120 injected bugs, 84 LLM calls.

## Headline

| Stage | Testbenches passing on the correct design | Bugs caught | Mean line/branch coverage |
|---|---|---|---|
| One-shot LLM | 4/10 | 67/120 (55.8%) | 84.2% |
| + simulation feedback | 7/10 | 100/120 (83.3%) | 98.4% |
| + coverage closure | 7/10 | 100/120 (83.3%) | 98.4% |

| Debugging (bugs caught by the final testbench) | Result |
|---|---|
| Bug cases debugged | 38 |
| Faulty line found on the first try | 34/38 (89.5%) |
| Correct fix on the first try | 32/38 (84.2%) |
| Correct fix with verify-and-retry (up to 3 tries) | 34/38 (89.5%) |

False design-bug reports on correct designs: 0.

## Per design

| Design | Level | Passes (1-shot / final) | Coverage (1-shot / final) | Bugs caught: 1-shot / +feedback / final | Debug: line found / fixed | LLM calls |
|---|---|---|---|---|---|---|
| alu8 | easy | yes (4/4) / yes (4/4) | 100.0% / 100.0% | 12 / 12 / 12 of 12 | 4/4 / 4/4 | 5 |
| updown_counter | easy | no (1/6) / no (3/6) | 57.1% / 100.0% | 4 / 5 / 5 of 12 | 4/4 / 3/4 | 14 |
| seq_detector | easy | no (1/5) / yes (5/5) | 33.3% / 100.0% | 2 / 12 / 12 of 12 | 3/4 / 4/4 | 8 |
| sync_fifo | medium | no (0/0) / yes (5/5) | n/a / 100.0% | 0 / 12 / 12 of 12 | 4/4 / 4/4 | 7 |
| rr_arbiter | medium | yes (5/5) / yes (5/5) | 100.0% / 100.0% | 12 / 12 / 12 of 12 | 3/4 / 3/4 | 7 |
| crc8 | medium | no (1/5) / yes (5/5) | 83.3% / 100.0% | 11 / 12 / 12 of 12 | 4/4 / 4/4 | 6 |
| sat_mac | medium | yes (5/5) / yes (5/5) | 100.0% / 100.0% | 11 / 11 / 11 of 12 | 4/4 / 4/4 | 5 |
| uart_tx | hard | yes (6/6) / yes (6/6) | 100.0% / 100.0% | 11 / 11 / 11 of 12 | 3/4 / 3/4 | 7 |
| spi_master | hard | no (2/4) / no (3/4) | 91.7% / 91.7% | 2 / 11 / 11 of 12 | 3/4 / 3/4 | 15 |
| apb_regs | hard | no (1/4) / no (2/4) | 92.3% / 92.3% | 2 / 2 / 2 of 12 | 2/2 / 2/2 | 10 |
