"""
Verification Plan for updown_counter:
1. test_async_reset:
   - Verify asynchronous assertion of rst_n drives count to 0 immediately
     (without waiting for a clock edge).
   - Verify combinational signals (zero=1) update immediately.
   - Verify count remains 0 while rst_n is held low across clock edges.
   - Verify normal operation resumes after deasserting rst_n.
2. test_count_up_and_wrap:
   - Count up from 0 to max_val with wrapping.
   - Verify step-by-step increments, tc assertion at wrap boundary (count >= max_val),
     and zero flag.
3. test_count_down_and_wrap:
   - Count down from max_val to 0 with wrapping.
   - Verify step-by-step decrements, tc assertion at wrap boundary (count == 0),
     and zero flag.
4. test_enable_and_hold:
   - When en=0, count holds previous value.
   - Verify tc is strictly 0 when en=0 even if count == 0 or count >= max_val.
5. test_load_and_clamping:
   - Verify synchronous load when load=1 (takes priority over en).
   - Test loading value d <= max_val.
   - Test clamped loading when d > max_val (count becomes max_val).
   - Verify tc=0 when load=1.
6. test_dynamic_max_val_and_out_of_bounds:
   - Change max_val on the fly.
   - Test lowering max_val below current count (count > max_val):
     * Counting up wraps immediately to 0 on the next enabled clock edge, tc=1.
     * Counting down decrements normally until 0, tc=0.
7. test_combinational_tc_and_zero:
   - Keep count steady and manipulate en, load, up, and max_val combinational inputs.
   - Check immediate (within 1ns, no clock edge) response of tc and zero.
8. test_corner_cases_max_val:
   - Test boundary values max_val = 0 and max_val = 255.
9. test_random_stress:
   - Constrained-random test running for 2,000 cycles with fixed seed (random.Random(1)).
   - Checks reference model predictions on every cycle.
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, ReadOnly, Timer
import random


class UpDownCounterModel:
    """Python reference model of the updown_counter specification."""

    def __init__(self):
        self.count = 0

    def reset(self):
        self.count = 0

    def get_zero(self):
        return 1 if self.count == 0 else 0

    def get_tc(self, en, up, load, max_val):
        if en and not load:
            if up and (self.count >= max_val):
                return 1
            elif (not up) and (self.count == 0):
                return 1
        return 0

    def step(self, en, up, load, d, max_val):
        if load:
            self.count = min(d, max_val)
        elif en and up:
            if self.count >= max_val:
                self.count = 0
            else:
                self.count = (self.count + 1) & 0xFF
        elif en and (not up):
            if self.count == 0:
                self.count = max_val
            else:
                self.count = (self.count - 1) & 0xFF
        # else count holds
        return self.count


async def init_and_reset(dut, model):
    """Start clock, initialize all inputs, apply and release reset."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    dut.rst_n.value = 0
    dut.en.value = 0
    dut.up.value = 0
    dut.load.value = 0
    dut.d.value = 0
    dut.max_val.value = 0
    model.reset()

    await Timer(2, "ns")
    assert int(dut.count.value) == 0, f"Async reset: expected count=0, got {dut.count.value}"
    assert int(dut.zero.value) == 1, f"Async reset: expected zero=1, got {dut.zero.value}"

    await FallingEdge(dut.clk)
    dut.rst_n.value = 1
    await FallingEdge(dut.clk)


async def step_and_check(dut, model, en, up, load, d, max_val, msg=""):
    """Drive inputs on falling edge, check comb signals, clock, and check registered outputs."""
    dut.en.value = en
    dut.up.value = up
    dut.load.value = load
    dut.d.value = d
    dut.max_val.value = max_val

    # Check combinational responses to input change after 1 ns
    await Timer(1, "ns")
    exp_tc_comb = model.get_tc(en, up, load, max_val)
    exp_zero_comb = model.get_zero()
    assert int(dut.tc.value) == exp_tc_comb, (
        f"Comb TC mismatch on inputs change: {msg} | "
        f"expected {exp_tc_comb}, got {int(dut.tc.value)}"
    )
    assert int(dut.zero.value) == exp_zero_comb, (
        f"Comb Zero mismatch on inputs change: {msg} | "
        f"expected {exp_zero_comb}, got {int(dut.zero.value)}"
    )

    # Rising edge triggers state update
    await RisingEdge(dut.clk)
    await ReadOnly()
    model.step(en, up, load, d, max_val)

    exp_count = model.count
    exp_zero = model.get_zero()
    exp_tc = model.get_tc(en, up, load, max_val)

    assert int(dut.count.value) == exp_count, (
        f"Count mismatch: {msg} | expected {exp_count}, got {int(dut.count.value)}"
    )
    assert int(dut.zero.value) == exp_zero, (
        f"Zero mismatch: {msg} | expected {exp_zero}, got {int(dut.zero.value)}"
    )
    assert int(dut.tc.value) == exp_tc, (
        f"TC mismatch: {msg} | expected {exp_tc}, got {int(dut.tc.value)}"
    )

    # Return to falling edge to leave ReadOnly phase for caller
    await FallingEdge(dut.clk)


@cocotb.test()
async def test_async_reset(dut):
    """Test asynchronous assertion of rst_n and recovery."""
    model = UpDownCounterModel()
    await init_and_reset(dut, model)

    # Count up to 5
    for _ in range(5):
        await step_and_check(dut, model, en=1, up=1, load=0, d=0, max_val=10, msg="Count to 5")

    # Assert async reset asynchronously (not on clock edge)
    await Timer(3, "ns")
    dut.rst_n.value = 0
    model.reset()
    await Timer(1, "ns")

    assert int(dut.count.value) == 0, f"Async reset failed: count is {dut.count.value}, expected 0"
    assert int(dut.zero.value) == 1, f"Async reset failed: zero is {dut.zero.value}, expected 1"

    # Hold reset across a clock edge
    await RisingEdge(dut.clk)
    await ReadOnly()
    assert int(dut.count.value) == 0, "Count did not stay 0 while rst_n is low"
    assert int(dut.zero.value) == 1, "Zero did not stay 1 while rst_n is low"

    await FallingEdge(dut.clk)
    dut.rst_n.value = 1
    # Check that normal operation resumes
    await step_and_check(dut, model, en=1, up=1, load=0, d=0, max_val=10, msg="Resume after reset")


@cocotb.test()
async def test_count_up_and_wrap(dut):
    """Test counting up and wrapping at max_val."""
    model = UpDownCounterModel()
    await init_and_reset(dut, model)

    max_v = 4
    # Run through 2 complete cycles of 0 -> 1 -> 2 -> 3 -> 4 -> 0
    for cycle in range(2 * (max_v + 1)):
        await step_and_check(
            dut, model, en=1, up=1, load=0, d=0, max_val=max_v,
            msg=f"Count up step {cycle}"
        )


@cocotb.test()
async def test_count_down_and_wrap(dut):
    """Test counting down and wrapping at 0 to max_val."""
    model = UpDownCounterModel()
    await init_and_reset(dut, model)

    max_v = 5
    # From 0, counting down should wrap directly to max_v, then 4, 3, 2, 1, 0, wrap to max_v
    for cycle in range(2 * (max_v + 1)):
        await step_and_check(
            dut, model, en=1, up=0, load=0, d=0, max_val=max_v,
            msg=f"Count down step {cycle}"
        )


@cocotb.test()
async def test_enable_and_hold(dut):
    """Test enable signal: en=0 holds count and suppresses tc."""
    model = UpDownCounterModel()
    await init_and_reset(dut, model)

    # Count to 3
    for _ in range(3):
        await step_and_check(dut, model, en=1, up=1, load=0, d=0, max_val=10, msg="Count to 3")

    # Disable for 4 cycles
    for i in range(4):
        await step_and_check(dut, model, en=0, up=1, load=0, d=0, max_val=10, msg=f"Hold count {i}")

    # Count at wrap point (count = 0) with en=0, tc must be 0
    await step_and_check(dut, model, en=1, up=0, load=0, d=0, max_val=3, msg="Count down to 2")
    await step_and_check(dut, model, en=1, up=0, load=0, d=0, max_val=3, msg="Count down to 1")
    await step_and_check(dut, model, en=1, up=0, load=0, d=0, max_val=3, msg="Count down to 0")

    # Now at count=0, if en=0, tc must be 0
    await step_and_check(dut, model, en=0, up=0, load=0, d=0, max_val=3, msg="Count=0 with en=0")


@cocotb.test()
async def test_load_and_clamping(dut):
    """Test synchronous load, clamping when d > max_val, and load priority."""
    model = UpDownCounterModel()
    await init_and_reset(dut, model)

    # Normal load: d <= max_val
    await step_and_check(dut, model, en=1, up=1, load=1, d=15, max_val=50, msg="Load 15 (max 50)")

    # Clamped load: d > max_val should clamp to max_val
    await step_and_check(dut, model, en=1, up=1, load=1, d=80, max_val=50, msg="Load 80 clamped to 50")

    # Load with en=0: load still works (load takes priority)
    await step_and_check(dut, model, en=0, up=0, load=1, d=25, max_val=50, msg="Load 25 with en=0")

    # Clamped load with en=0
    await step_and_check(dut, model, en=0, up=1, load=1, d=100, max_val=40, msg="Load 100 clamped to 40")


@cocotb.test()
async def test_dynamic_max_val_and_out_of_bounds(dut):
    """Test changing max_val dynamically and handling count > max_val."""
    model = UpDownCounterModel()
    await init_and_reset(dut, model)

    # Load count = 100 with max_val = 150
    await step_and_check(dut, model, en=0, up=1, load=1, d=100, max_val=150, msg="Load 100")

    # Lower max_val to 50; count is now 100 (> max_val 50)
    # When counting up: count >= max_val (100 >= 50), tc should be 1, next step wraps to 0
    await step_and_check(dut, model, en=1, up=1, load=0, d=0, max_val=50, msg="Count up with count > max_val")
    assert model.count == 0

    # Load count = 100 with max_val = 150 again
    await step_and_check(dut, model, en=0, up=1, load=1, d=100, max_val=150, msg="Load 100 again")

    # Lower max_val to 50, but count down with en=1, up=0
    # Spec: "if count == 0, count becomes max_val (wrap); otherwise count decrements by 1"
    # So count should decrement to 99, tc should be 0 (count != 0)
    await step_and_check(dut, model, en=1, up=0, load=0, d=0, max_val=50, msg="Count down with count > max_val")
    assert model.count == 99


@cocotb.test()
async def test_combinational_tc_and_zero(dut):
    """Verify combinational behavior of tc and zero without clock edges."""
    model = UpDownCounterModel()
    await init_and_reset(dut, model)

    # Load count = 5 with max_val = 5
    await step_and_check(dut, model, en=0, up=1, load=1, d=5, max_val=5, msg="Load 5")

    # Now count = 5. Do NOT clock, just alter combinational inputs
    # en=1, load=0, up=1, max_val=5 -> tc should be 1
    dut.en.value = 1
    dut.load.value = 0
    dut.up.value = 1
    dut.max_val.value = 5
    await Timer(1, "ns")
    assert int(dut.tc.value) == 1, "tc should be 1 when en=1, load=0, up=1, count>=max_val"
    assert int(dut.zero.value) == 0, "zero should be 0 when count=5"

    # Toggle load=1 combinational -> tc must drop to 0
    dut.load.value = 1
    await Timer(1, "ns")
    assert int(dut.tc.value) == 0, "tc should drop to 0 when load=1"

    # Toggle load=0, en=0 -> tc must drop to 0
    dut.load.value = 0
    dut.en.value = 0
    await Timer(1, "ns")
    assert int(dut.tc.value) == 0, "tc should drop to 0 when en=0"

    # en=1, but up=0 (down) while count=5 -> tc should be 0
    dut.en.value = 1
    dut.up.value = 0
    await Timer(1, "ns")
    assert int(dut.tc.value) == 0, "tc should be 0 when counting down and count != 0"

    # Increase max_val to 6 while up=1 -> tc should drop to 0 (count 5 < 6)
    dut.up.value = 1
    dut.max_val.value = 6
    await Timer(1, "ns")
    assert int(dut.tc.value) == 0, "tc should be 0 when max_val increased beyond count"

    # Decrease max_val back to 5 -> tc should be 1 again
    dut.max_val.value = 5
    await Timer(1, "ns")
    assert int(dut.tc.value) == 1, "tc should be 1 when max_val == count"

    # Align back to falling edge before test finish
    await FallingEdge(dut.clk)


@cocotb.test()
async def test_corner_cases_max_val(dut):
    """Test corner max_val boundaries: 0 and 255."""
    model = UpDownCounterModel()
    await init_and_reset(dut, model)

    # max_val = 0: counting up wraps continuously at 0, tc always 1 when enabled
    for i in range(4):
        await step_and_check(
            dut, model, en=1, up=1, load=0, d=0, max_val=0,
            msg=f"max_val=0 count up cycle {i}"
        )
        assert model.count == 0

    # max_val = 0: counting down wraps continuously at 0, tc always 1 when enabled
    for i in range(4):
        await step_and_check(
            dut, model, en=1, up=0, load=0, d=0, max_val=0,
            msg=f"max_val=0 count down cycle {i}"
        )
        assert model.count == 0

    # max_val = 255: load 254, count up to 255 (tc=1), wrap to 0
    await step_and_check(dut, model, en=0, up=1, load=1, d=254, max_val=255, msg="Load 254")
    await step_and_check(dut, model, en=1, up=1, load=0, d=0, max_val=255, msg="Count to 255")
    assert model.count == 255
    await step_and_check(dut, model, en=1, up=1, load=0, d=0, max_val=255, msg="Wrap 255 to 0")
    assert model.count == 0


@cocotb.test()
async def test_random_stress(dut):
    """Constrained-random test covering interleaved operations over 2000 cycles."""
    model = UpDownCounterModel()
    await init_and_reset(dut, model)

    rng = random.Random(1)

    for cycle in range(2000):
        en = rng.choice([0, 1, 1, 1])  # Bias towards enabled
        up = rng.choice([0, 1])
        load = 1 if rng.random() < 0.1 else 0  # 10% load operations
        d = rng.randint(0, 255)
        max_val = rng.choice([0, 1, 2, 5, 10, 127, 254, 255, rng.randint(0, 255)])

        await step_and_check(
            dut, model,
            en=en, up=up, load=load, d=d, max_val=max_val,
            msg=f"Random cycle {cycle}: en={en}, up={up}, load={load}, d={d}, max_val={max_val}"
        )
