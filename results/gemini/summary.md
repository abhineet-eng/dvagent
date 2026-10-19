# DVAgent benchmark results

Model: `gemini-3.8-flash` via gemini, run 2026-10-19 17:42:35. 1 designs, 12 injected bugs, 1 LLM calls.

## Headline

| Stage | Testbenches passing on the correct design | Bugs caught | Mean line/branch coverage |
|---|---|---|---|
| One-shot LLM | 1/1 | 12/12 (100.0%) | 100.0% |
| + simulation feedback | 1/1 | 12/12 (100.0%) | 100.0% |
| + coverage closure | 1/1 | 12/12 (100.0%) | 100.0% |

False design-bug reports on correct designs: 0.

## Per design

| Design | Level | Passes (1-shot / final) | Coverage (1-shot / final) | Bugs caught: 1-shot / +feedback / final | Debug: line found / fixed | LLM calls |
|---|---|---|---|---|---|---|
| alu8 | easy | yes (7/7) / yes (7/7) | 100.0% / 100.0% | 12 / 12 / 12 of 12 | 0/0 / 0/0 | 1 |
