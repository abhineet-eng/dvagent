"""
Verification Plan for sat_mac:
1. Reset behavior: active-high synchronous reset sets acc = 0 and sat = 0 immediately.
2. Idle behavior: when valid = 0 and clear = 0 (and rst = 0), acc and sat hold their values.
3. Clear behavior: when clear = 1 and valid = 0, acc = 0 and sat = 0.
4. Basic MAC operation: valid = 1, clear = 0 accumulates products correctly over multiple cycles.
5. Restart accumulation: valid = 1 and clear = 1 starts a new accumulation with the current product.
6. Positive saturation: accumulation exceeding 32767 clamps to 32767 and sets sticky 'sat' flag to 1.
7. Negative saturation: accumulation falling below -32768 clamps to -32768 and sets sticky 'sat' flag to 1.
8. Sticky sat flag: once sat becomes 1, it remains 1 until a new clear or reset, even if subsequent steps do not saturate.
9. Constrained-random test: random inputs for valid, clear, a, b to verify against Python reference model.
"""

import random
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, ReadOnly, Timer, ClockCycles

class SatMacRefModel:
    def __init__(self):
        self.acc = 0
        self.sat = 0

    def step(self, rst, valid, clear, a, b):
        if rst:
            self.acc = 0
            self.sat = 0
        elif valid:
            base = 0 if clear else self.acc
            p = a * b
            s = base + p
            
            step_sat = 0
            if s > 32767:
                self.acc = 32767
                step_sat = 1
            elif s < -32768:
                self.acc = -32768
                step_sat = 1
            else:
                self.acc = s

            if clear:
                self.sat = step_sat
            else:
                self.sat = self.sat | step_sat
        elif clear:
            self.acc = 0
            self.sat = 0
        else:
            # Holds values
            pass
        return self.acc, self.sat


async def apply_inputs(dut, rst, valid, clear, a, b):
    await FallingEdge(dut.clk)
    dut.rst.value = rst
    dut.valid.value = valid
    dut.clear.value = clear
    dut.a.value = a
    dut.b.value = b


async def check_outputs(ref_model, dut):
    await RisingEdge(dut.clk)
    await ReadOnly()
    expected_acc, expected_sat = ref_model.acc, ref_model.sat
    got_acc = dut.acc.value.signed_integer
    got_sat = int(dut.sat.value)
    assert got_acc == expected_acc, f"ACC mismatch: expected {expected_acc}, got {got_acc}"
    assert got_sat == expected_sat, f"SAT mismatch: expected {expected_sat}, got {got_sat}"


@cocotb.test()
async def test_reset(dut):
    """Test synchronous reset behavior."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    ref = SatMacRefModel()

    # Initial drive
    await apply_inputs(dut, rst=1, valid=0, clear=0, a=0, b=0)
    ref.step(rst=1, valid=0, clear=0, a=0, b=0)
    await check_outputs(ref, dut)

    # Deassert reset, check zero state
    await apply_inputs(dut, rst=0, valid=0, clear=0, a=10, b=20)
    ref.step(rst=0, valid=0, clear=0, a=10, b=20)
    await check_outputs(ref, dut)

    # Assert reset mid-operation
    await apply_inputs(dut, rst=1, valid=1, clear=0, a=50, b=50)
    ref.step(rst=1, valid=1, clear=0, a=50, b=50)
    await check_outputs(ref, dut)


@cocotb.test()
async def test_idle_and_clear(dut):
    """Test idle holding and clear functionality."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    ref = SatMacRefModel()

    # Reset first
    await apply_inputs(dut, rst=1, valid=0, clear=0, a=0, b=0)
    ref.step(rst=1, valid=0, clear=0, a=0, b=0)
    await check_outputs(ref, dut)

    # Accumulate some value
    await apply_inputs(dut, rst=0, valid=1, clear=1, a=10, b=10)
    ref.step(rst=0, valid=1, clear=1, a=10, b=10)
    await check_outputs(ref, dut) # acc = 100

    # Idle (valid=0, clear=0) should hold value
    await apply_inputs(dut, rst=0, valid=0, clear=0, a=20, b=20)
    ref.step(rst=0, valid=0, clear=0, a=20, b=20)
    await check_outputs(ref, dut) # acc = 100

    # Clear alone (valid=0, clear=1) should zero out
    await apply_inputs(dut, rst=0, valid=0, clear=1, a=0, b=0)
    ref.step(rst=0, valid=0, clear=1, a=0, b=0)
    await check_outputs(ref, dut) # acc = 0, sat = 0


@cocotb.test()
async def test_basic_mac_and_restart(dut):
    """Test basic MAC accumulation and clear+valid restart."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    ref = SatMacRefModel()

    await apply_inputs(dut, rst=1, valid=0, clear=0, a=0, b=0)
    ref.step(rst=1, valid=0, clear=0, a=0, b=0)
    await check_outputs(ref, dut)

    # Start accumulation with clear=1, valid=1
    await apply_inputs(dut, rst=0, valid=1, clear=1, a=5, b=10)
    ref.step(rst=0, valid=1, clear=1, a=5, b=10)
    await check_outputs(ref, dut) # acc = 50

    # Continue accumulation
    await apply_inputs(dut, rst=0, valid=1, clear=0, a=3, b=4)
    ref.step(rst=0, valid=1, clear=0, a=3, b=4)
    await check_outputs(ref, dut) # acc = 50 + 12 = 62

    # Restart accumulation with clear=1, valid=1
    await apply_inputs(dut, rst=0, valid=1, clear=1, a=-2, b=15)
    ref.step(rst=0, valid=1, clear=1, a=-2, b=15)
    await check_outputs(ref, dut) # acc = -30


@cocotb.test()
async def test_positive_and_negative_saturation(dut):
    """Test positive and negative saturation and sticky sat flag."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    ref = SatMacRefModel()

    await apply_inputs(dut, rst=1, valid=0, clear=0, a=0, b=0)
    ref.step(rst=1, valid=0, clear=0, a=0, b=0)
    await check_outputs(ref, dut)

    # Drive a large positive product to saturate (127 * 127 = 16129, do twice: 32258, then another step)
    # Let's do 127 * 127 twice with clear=1 then clear=0
    await apply_inputs(dut, rst=0, valid=1, clear=1, a=127, b=127)
    ref.step(rst=0, valid=1, clear=1, a=127, b=127)
    await check_outputs(ref, dut) # acc = 16129, sat = 0

    await apply_inputs(dut, rst=0, valid=1, clear=0, a=127, b=127)
    ref.step(rst=0, valid=1, clear=0, a=127, b=127)
    await check_outputs(ref, dut) # acc = 32258, sat = 0

    # Next addition should saturate at 32767
    await apply_inputs(dut, rst=0, valid=1, clear=0, a=127, b=127)
    ref.step(rst=0, valid=1, clear=0, a=127, b=127)
    await check_outputs(ref, dut) # acc = 32767, sat = 1

    # Non-saturating operation should keep sat = 1 (sticky)
    await apply_inputs(dut, rst=0, valid=1, clear=0, a=1, b=1)
    ref.step(rst=0, valid=1, clear=0, a=1, b=1)
    await check_outputs(ref, dut) # acc = 32767, sat = 1

    # Clear should clear sat
    await apply_inputs(dut, rst=0, valid=0, clear=1, a=0, b=0)
    ref.step(rst=0, valid=0, clear=1, a=0, b=0)
    await check_outputs(ref, dut) # acc = 0, sat = 0

    # Negative saturation test (-128 * 127 = -16256, twice -> -32512, third -> clamp to -32768)
    await apply_inputs(dut, rst=0, valid=1, clear=1, a=-128, b=127)
    ref.step(rst=0, valid=1, clear=1, a=-128, b=127)
    await check_outputs(ref, dut) # acc = -16256

    await apply_inputs(dut, rst=0, valid=1, clear=0, a=-128, b=127)
    ref.step(rst=0, valid=1, clear=0, a=-128, b=127)
    await check_outputs(ref, dut) # acc = -32512

    await apply_inputs(dut, rst=0, valid=1, clear=0, a=-128, b=127)
    ref.step(rst=0, valid=1, clear=0, a=-128, b=127)
    await check_outputs(ref, dut) # acc = -32768, sat = 1


@cocotb.test()
async def test_constrained_random(dut):
    """Constrained-random test comparing DUT against reference model."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    ref = SatMacRefModel()

    rng = random.Random(42)

    # Reset
    await apply_inputs(dut, rst=1, valid=0, clear=0, a=0, b=0)
    ref.step(rst=1, valid=0, clear=0, a=0, b=0)
    await check_outputs(ref, dut)

    for _ in range(5000):
        # Weighted random inputs to cover all corner cases nicely
        rst = 1 if rng.random() < 0.02 else 0
        valid = rng.randint(0, 1)
        clear = rng.randint(0, 1)
        a = rng.randint(-128, 127)
        b = rng.randint(-128, 127)

        await apply_inputs(dut, rst=rst, valid=valid, clear=clear, a=a, b=b)
        ref.step(rst=rst, valid=valid, clear=clear, a=a, b=b)
        await check_outputs(ref, dut)
