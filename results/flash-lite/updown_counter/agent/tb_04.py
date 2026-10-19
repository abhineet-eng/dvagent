"""
Verification Plan for updown_counter:
1. Asynchronous active-low reset: `rst_n` forces `count` to 0 immediately.
2. Synchronous load with clamping: `load` sets `count` to `min(d, max_val)`, taking priority over counting.
3. Up counting and wrapping: increments normally, wraps to 0 when `count >= max_val`.
4. Down counting and wrapping: decrements normally, wraps to `max_val` when `count == 0`.
5. Hold state: when `en` = 0 and `load` = 0, `count` remains unchanged.
6. Dynamic `max_val` changes: handles `max_val` alterations correctly, including when `count > max_val`.
7. Combinational outputs (`zero` and `tc`): checked against specification on every cycle using a reference model.
8. Constrained-random stimulus: long randomized test vectors to uncover corner cases.
"""

import random
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, ReadOnly, Timer, ClockCycles


class CounterRefModel:
    def __init__(self):
        self.count = 0

    def step(self, rst_n, en, up, load, d, max_val):
        if not rst_n:
            self.count = 0
            zero = 1 if self.count == 0 else 0
            tc = 0
            return self.count, tc, zero

        # Combinatorial outputs depend on current self.count and inputs *before* state update
        if en and not load:
            if up:
                tc = 1 if self.count >= max_val else 0
            else:
                tc = 1 if self.count == 0 else 0
        else:
            tc = 0

        # State update logic (priority order)
        if load:
            self.count = d if d <= max_val else max_val
        elif en:
            if up:
                if self.count >= max_val:
                    self.count = 0
                else:
                    self.count = self.count + 1
            else:
                if self.count == 0:
                    self.count = max_val
                else:
                    self.count = self.count - 1
        else:
            # hold
            pass

        # Keep within 8 bits
        self.count &= 0xFF
        
        # zero depends on the newly updated count (registered output)
        zero = 1 if self.count == 0 else 0
        
        return self.count, tc, zero


async def run_cycle(dut, ref, rst_n, en, up, load, d, max_val):
    # 1. Capture current inputs before falling edge
    curr_rst_n = int(dut.rst_n.value) if dut.rst_n.value.is_resolvable else 0
    curr_en = int(dut.en.value) if dut.en.value.is_resolvable else 0
    curr_up = int(dut.up.value) if dut.up.value.is_resolvable else 0
    curr_load = int(dut.load.value) if dut.load.value.is_resolvable else 0
    curr_d = int(dut.d.value) if dut.d.value.is_resolvable else 0
    curr_max = int(dut.max_val.value) if dut.max_val.value.is_resolvable else 0

    # Get expected outputs for current cycle using model before update
    expected_count, expected_tc, expected_zero = ref.step(
        curr_rst_n, curr_en, curr_up, curr_load, curr_d, curr_max
    )

    # Check combinational outputs and previous cycle's registered count during ReadOnly phase
    await ReadOnly()
    got_count = int(dut.count.value)
    got_tc = int(dut.tc.value)
    got_zero = int(dut.zero.value)

    assert got_count == expected_count, f"Count mismatch: got {got_count}, expected {expected_count}"
    assert got_zero == expected_zero, f"Zero mismatch: got {got_zero}, expected {expected_zero}"
    assert got_tc == expected_tc, f"TC mismatch: got {got_tc}, expected {expected_tc} (count={got_count}, max_val={curr_max}, en={curr_en}, up={curr_up}, load={curr_load})"

    # 2. Drive new inputs at falling edge
    await FallingEdge(dut.clk)
    dut.rst_n.value = rst_n
    dut.en.value = en
    dut.up.value = up
    dut.load.value = load
    dut.d.value = d
    dut.max_val.value = max_val


@cocotb.test()
async def test_reset_and_hold(dut):
    """Test asynchronous reset and hold behavior."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    ref = CounterRefModel()

    # Apply async reset
    dut.rst_n.value = 0
    dut.en.value = 0
    dut.up.value = 1
    dut.load.value = 0
    dut.d.value = 50
    dut.max_val.value = 10
    await Timer(15, units="ns")

    # Check reset state
    await ReadOnly()
    assert int(dut.count.value) == 0
    assert int(dut.zero.value) == 1

    # Release reset, en=0, load=0 -> should hold at 0
    for _ in range(5):
        await run_cycle(dut, ref, rst_n=1, en=0, up=1, load=0, d=0, max_val=10)
    await ClockCycles(dut.clk, 1)


@cocotb.test()
async def test_load_and_clamping(dut):
    """Test synchronous load and max_val clamping."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    ref = CounterRefModel()

    # Reset
    dut.rst_n.value = 0
    dut.en.value = 0
    dut.up.value = 1
    dut.load.value = 0
    dut.d.value = 0
    dut.max_val.value = 100
    await Timer(15, units="ns")

    # Release reset and load valid value (d <= max_val)
    await run_cycle(dut, ref, rst_n=1, en=0, up=1, load=1, d=45, max_val=100)
    # Load with d > max_val (should clamp to max_val)
    await run_cycle(dut, ref, rst_n=1, en=0, up=1, load=1, d=200, max_val=50)
    # Load with max_val changing dynamically
    await run_cycle(dut, ref, rst_n=1, en=0, up=1, load=1, d=30, max_val=20) # clamps to 20
    await ClockCycles(dut.clk, 1)


@cocotb.test()
async def test_up_counting_and_wrapping(dut):
    """Test up counting and wrapping at max_val, plus tc generation."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    ref = CounterRefModel()

    # Reset
    dut.rst_n.value = 0
    dut.en.value = 0
    dut.up.value = 1
    dut.load.value = 0
    dut.d.value = 0
    dut.max_val.value = 5
    await Timer(15, units="ns")

    # Release reset and load 3
    await run_cycle(dut, ref, rst_n=1, en=0, up=1, load=1, d=3, max_val=5)
    
    # Enable up counting from 3 to 5, wrap to 0, then 1
    # Count = 3, en=1, up=1, max=5 -> tc=0
    await run_cycle(dut, ref, rst_n=1, en=1, up=1, load=0, d=0, max_val=5)
    # Count = 4, en=1, up=1, max=5 -> tc=0
    await run_cycle(dut, ref, rst_n=1, en=1, up=1, load=0, d=0, max_val=5)
    # Count = 5, en=1, up=1, max=5 -> tc should be 1 (about to wrap)
    await run_cycle(dut, ref, rst_n=1, en=1, up=1, load=0, d=0, max_val=5)
    # Count wraps to 0
    await run_cycle(dut, ref, rst_n=1, en=1, up=1, load=0, d=0, max_val=5)
    # Count = 1
    await run_cycle(dut, ref, rst_n=1, en=0, up=1, load=0, d=0, max_val=5)
    await ClockCycles(dut.clk, 1)


@cocotb.test()
async def test_down_counting_and_wrapping(dut):
    """Test down counting and wrapping to max_val when count == 0."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    ref = CounterRefModel()

    # Reset
    dut.rst_n.value = 0
    dut.en.value = 0
    dut.up.value = 0
    dut.load.value = 0
    dut.d.value = 0
    dut.max_val.value = 3
    await Timer(15, units="ns")

    # Load 2
    await run_cycle(dut, ref, rst_n=1, en=0, up=0, load=1, d=2, max_val=3)
    # Count = 2, down count to 0, wrap to max_val (3)
    await run_cycle(dut, ref, rst_n=1, en=1, up=0, load=0, d=0, max_val=3) # count -> 1
    await run_cycle(dut, ref, rst_n=1, en=1, up=0, load=0, d=0, max_val=3) # count -> 0, tc should be 1
    await run_cycle(dut, ref, rst_n=1, en=1, up=0, load=0, d=0, max_val=3) # count wraps to 3
    await run_cycle(dut, ref, rst_n=1, en=0, up=0, load=0, d=0, max_val=3) # hold at 3
    await ClockCycles(dut.clk, 1)


@cocotb.test()
async def test_dynamic_max_val_overflow(dut):
    """Test lowering max_val below current count and subsequent counting up."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    ref = CounterRefModel()

    # Reset
    dut.rst_n.value = 0
    dut.en.value = 0
    dut.up.value = 1
    dut.load.value = 0
    dut.d.value = 0
    dut.max_val.value = 10
    await Timer(15, units="ns")

    # Load 8
    await run_cycle(dut, ref, rst_n=1, en=0, up=1, load=1, d=8, max_val=10)
    # Lower max_val to 5 while count is 8 (count > max_val)
    await run_cycle(dut, ref, rst_n=1, en=0, up=1, load=0, d=0, max_val=5)
    # Enable up counting: since count (8) >= max_val (5), next step should wrap to 0 immediately
    await run_cycle(dut, ref, rst_n=1, en=1, up=1, load=0, d=0, max_val=5)
    await ClockCycles(dut.clk, 1)


@cocotb.test()
async def test_constrained_random(dut):
    """Constrained-random verification test over multiple cycles."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    ref = CounterRefModel()
    rng = random.Random(42)

    # Reset
    dut.rst_n.value = 0
    dut.en.value = 0
    dut.up.value = 0
    dut.load.value = 0
    dut.d.value = 0
    dut.max_val.value = 10
    await Timer(15, units="ns")

    for _ in range(1500):
        rst_n = rng.choices([0, 1], weights=[1, 99])[0] # rare reset
        en = rng.choice([0, 1])
        up = rng.choice([0, 1])
        load = rng.choices([0, 1], weights=[85, 15])[0]
        d = rng.randint(0, 255)
        max_val = rng.randint(1, 255)

        await run_cycle(dut, ref, rst_n, en, up, load, d, max_val)

    await ClockCycles(dut.clk, 5)
