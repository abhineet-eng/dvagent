"""Prompt templates for every agent step."""
from __future__ import annotations

from .design import Design
from .extract import number_lines
from .rtl import module_header

SYSTEM = """\
You are DVAgent, a senior design-verification engineer. You verify Verilog RTL designs by writing \
self-checking cocotb testbenches in Python, running them, and debugging failures.

Simulation environment: cocotb 1.9 with Icarus Verilog 12 (a 4-state simulator: signals that are \
not reset read as X, and int() of an X value raises ValueError). Python 3.12 standard library only.

How to write the testbench (follow all of these):
1. Imports: `import cocotb`, `from cocotb.clock import Clock`, \
`from cocotb.triggers import RisingEdge, FallingEdge, ReadOnly, Timer, ClockCycles`, plus `random`.
2. Clock: `cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())` (use the design's clock port name).
3. Drive with `dut.port.value = value`. Read with `int(dut.port.value)`; for a signed port use \
`dut.port.value.signed_integer`.
4. Race-free timing: change inputs right after `await FallingEdge(dut.clk)`. Check registered outputs \
after `await RisingEdge(dut.clk)` followed by `await ReadOnly()`. Never assign a signal while in \
ReadOnly (the next `await FallingEdge(...)` leaves that phase). For combinational logic, set the inputs, \
`await Timer(1, "ns")`, then check.
5. Every test starts by starting the clock, giving every input a known value and applying reset as the \
spec describes. Tests run one after another in the same simulation.
6. Write a Python reference model of the spec (a class with a `step(...)` method that mirrors one clock \
edge) and compare the DUT against it on every cycle, not only at the end.
7. Use `assert got == expected, f"..."` with a message that states the cycle or inputs, the expected \
value and the actual value.
8. Cover the spec systematically: several `@cocotb.test()` functions, each focused on one feature or \
corner case named in the spec, plus constrained-random tests with a fixed seed (`random.Random(1)`). \
Keep each test under about 20,000 clock cycles.
9. Never wait on a DUT signal without a bound: loop over clock cycles with a maximum count instead of \
`await RisingEdge(dut.some_output)`.
10. Access only the ports of the module. Do not read internal signals.
11. Return the complete testbench file in one ```python code block.
"""


def design_brief(d: Design, show_rtl: bool = False) -> str:
    rtl = d.rtl_text()
    parts = [f"# Design under test: `{d.top}`\n", "## Specification\n", d.spec.strip(), "\n## Module interface\n",
             "```verilog\n" + module_header(rtl, d.top) + "\n```"]
    if d.parameters:
        parts.append(f"Parameter overrides used in simulation: {d.parameters}")
    if show_rtl:
        parts += ["\n## RTL source\n", "```verilog\n" + number_lines(rtl) + "\n```"]
    return "\n".join(parts)


def generate(d: Design, show_rtl: bool = False) -> list[dict]:
    user = f"""{design_brief(d, show_rtl)}

## Task

Write a complete cocotb testbench for `{d.top}` that checks every behaviour in the specification.
Start the file with a docstring containing a short verification plan (the features and corner cases \
you will check). Then the code. Remember: the reference model must come from the specification, \
and every expected value must be checked on every cycle."""
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def fix(d: Design, tb: str, report: str, history: list[str], show_rtl: bool = False,
        reviewer_note: str = "") -> list[dict]:
    hist = "\n".join(f"- {h}" for h in history[-6:]) or "- (first run)"
    note = f"\n## Reviewer note\n\n{reviewer_note}\n" if reviewer_note else ""
    user = f"""{design_brief(d, show_rtl)}

## Current testbench (line numbers added for reference)

```python
{number_lines(tb)}
```

## Simulation result

```
{report}
```

## History of earlier attempts

{hist}
{note}
## Task

The testbench did not pass. Find the root cause. Decide whether the failure comes from a bug in the \
testbench (wrong reference model, wrong timing, wrong API use, wrong assumption) or from a real \
violation of the specification by the design.

Reply in this order:
1. A JSON object in a ```json block:
   {{"blame": "testbench" or "design", "root_cause": "<one or two sentences>", \
"evidence": "<the observed values and the spec rule they break>"}}
2. If the blame is "testbench": the complete corrected testbench file in one ```python block. Fix the \
root cause; keep the tests that already work.
   If the blame is "design": no code; the JSON is your bug report."""
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def coverage(d: Design, tb: str, cov_percent: float, missed: str, show_rtl: bool = False) -> list[dict]:
    user = f"""{design_brief(d, show_rtl)}

## Current testbench (passes on the design)

```python
{tb}
```

## Code coverage

The testbench passes, but RTL line/branch coverage is {cov_percent:.1f}%. These RTL statements or \
branches were never executed:

```
{missed}
```

## Task

Add tests (or extend the stimulus) so that these behaviours are exercised and checked against the \
reference model. Work out from the specification which input sequences reach them. Keep all existing \
tests unchanged unless they need a fix. Reply with the complete updated testbench file in one ```python block."""
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


DEBUG_SYSTEM = """\
You are DVAgent, a senior design-verification engineer debugging a failing Verilog design. \
You read the specification, the RTL and the failing test output, find the faulty RTL line, and \
propose a minimal fix. You never change the testbench in this task."""


def debug(d: Design, rtl_text: str, rtl_file: str, tb: str, report: str,
          previous: list[str] | None = None) -> list[dict]:
    prev = ""
    if previous:
        prev = "\n## Earlier fix attempts that did not work\n\n" + "\n".join(f"- {p}" for p in previous) + "\n"
    user = f"""# Design under test: `{d.top}`

## Specification

{d.spec.strip()}

## RTL source: `{rtl_file}` (line numbers added for reference)

```verilog
{number_lines(rtl_text)}
```

## Testbench

This testbench passed on a previous, correct version of the design. It now fails, so a bug was \
introduced into the RTL above.

```python
{tb}
```

## Failing simulation output

```
{report}
```
{prev}
## Task

Find the RTL line that contains the bug and fix it with the smallest possible change.
Reply with only a JSON object in a ```json block:
{{"bug_line": <line number in {rtl_file}>, "explanation": "<what is wrong and which spec rule it breaks>", \
"fix": [{{"line": <line number>, "old_text": "<that line exactly as it is now>", \
"new_text": "<the complete corrected text of that line>"}}]}}
Take the line number from the numbers printed in front of the RTL above. The fix list normally has one \
entry. Keep the original indentation. Do not add or remove lines."""
    return [{"role": "system", "content": DEBUG_SYSTEM}, {"role": "user", "content": user}]
