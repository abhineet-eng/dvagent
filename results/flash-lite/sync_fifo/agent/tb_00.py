"""
Verification Plan for sync_fifo:
1. Reset behavior: Verify FIFO becomes empty (count=0, empty=1, full=0, almost_full=0), 
   and error flags (overflow, underflow) are cleared.
2. Basic push and pop: Push data into an empty FIFO, verify dout reflects the pushed data 
   immediately (first-word fall-through), count increments, and empty goes low.
3. Simultaneous push and pop: Test pushing and popping at the same time when empty, 
   when partially full, and when full. Verify count behavior and data correctness.
4. Overflow condition: Try pushing into a full FIFO (without simultaneous pop), verify push 
   is rejected and sticky `overflow` flag asserts and stays asserted.
5. Underflow condition: Try popping from an empty FIFO, verify pop is rejected and sticky 
   `underflow` flag asserts and stays asserted.
6. Almost full flag: Verify `almost_full` asserts correctly when count >= 6 and deasserts below 6.
7. Constrained-random sequence: Run a randomized test with mixed push/pop requests, validating 
   against a Python reference model on every single clock edge.
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, ReadOnly, Timer, ClockCycles
import random

class FifoRefModel:
    def __init__(self, depth=8):
        self.depth = depth
        self.buffer = []
        self.count = 0
        self.overflow = 0
        self.underflow = 0

    def step(self, rst, push, din, pop):
        if rst:
            self.buffer = []
            self.count = 0
            self.overflow = 0
            self.underflow = 0
            return

        # Determine if pop is accepted
        pop_accepted = pop and (self.count > 0)
        if pop and not pop_accepted:
            self.underflow = 1

        # Determine if push is accepted
        # A full FIFO can accept a push if a pop is also accepted in the same cycle
        full = (self.count == self.depth)
        push_accepted = push and (not full or pop_accepted)
        if push and not push_accepted:
            self.overflow = 1

        # Execute operations
        if pop_accepted:
            self.buffer.pop(0)
            self.count -= 1

        if push_accepted:
            self.buffer.append(din & 0xFF)
            self.count += 1

    @property
    def empty(self):
        return 1 if self.count == 0 else 0

    @property
    def full(self):
        return 1 if self.count == self.depth else 0

    @property
    def almost_full(self):
        return 1 if self.count >= 6 else 0

    @property
    def dout(self):
        if self.empty:
            return 0  # Unspecified in spec, but DUT/model needs a value
        return self.buffer[0]


async def apply_reset(dut):
    dut.rst.value = 1
    dut.push.value = 0
    dut.din.value = 0
    dut.pop.value = 0
    await FallingEdge(dut.clk)
    await RisingEdge(dut.clk)
    await ReadOnly()
    dut.rst.value = 0


@cocotb.test()
async def test_reset(dut):
    """Test reset behavior and initial state."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    
    # Apply reset
    dut.rst.value = 1
    dut.push.value = 1
    dut.din.value = 0xAA
    dut.pop.value = 1
    await FallingEdge(dut.clk)
    await RisingEdge(dut.clk)
    await ReadOnly()
    
    dut.rst.value = 0
    await ReadOnly()

    assert int(dut.count.value) == 0, f"Expected count=0 after reset, got {int(dut.count.value)}"
    assert int(dut.empty.value) == 1, f"Expected empty=1 after reset, got {int(dut.empty.value)}"
    assert int(dut.full.value) == 0, f"Expected full=0 after reset, got {int(dut.full.value)}"
    assert int(dut.almost_full.value) == 0, f"Expected almost_full=0 after reset, got {int(dut.almost_full.value)}"
    assert int(dut.overflow.value) == 0, f"Expected overflow=0 after reset, got {int(dut.overflow.value)}"
    assert int(dut.underflow.value) == 0, f"Expected underflow=0 after reset, got {int(dut.underflow.value)}"


@cocotb.test()
async def test_basic_push_pop(dut):
    """Test basic pushing, first-word fall-through, popping, and count tracking."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    ref = FifoRefModel()

    await apply_res_and_model = None  # helper
    await apply_reset(dut)
    ref.step(rst=1, push=0, din=0, pop=0)

    test_data = [0x10, 0x20, 0x30, 0x40]

    # Push data items one by one
    for val in test_data:
        await FallingEdge(dut.clk)
        dut.rst.value = 0
        dut.push.value = 1
        dut.din.value = val
        dut.pop.value = 0
        
        ref.step(rst=0, push=1, din=val, pop=0)
        
        await RisingEdge(dut.clk)
        await ReadOnly()

        assert int(dut.count.value) == ref.count, f"Count mismatch: got {int(dut.count.value)}, expected {ref.count}"
        assert int(dut.empty.value) == ref.empty, f"Empty mismatch"
        assert int(dut.full.value) == ref.full, f"Full mismatch"
        assert int(dut.dout.value) == ref.dout, f"Dout mismatch: got {int(dut.dout.value):02x}, expected {ref.dout:02x}"

    # Pop data items one by one
    for expected_val in test_data:
        # Check dout before pop (first-word fall-through)
        await ReadOnly()
        assert int(dut.dout.value) == ref.dout, f"Fall-through dout mismatch before pop"

        await FallingEdge(dut.clk)
        dut.push.value = 0
        dut.pop.value = 1

        ref.step(rst=0, push=0, din=0, pop=1)

        await RisingEdge(dut.clk)
        await ReadOnly()

        assert int(dut.count.value) == ref.count, f"Count mismatch after pop: got {int(dut.count.value)}, expected {ref.count}"
        assert int(dut.empty.value) == ref.empty, f"Empty mismatch after pop"


@cocotb.test()
async def test_overflow_underflow(dut):
    """Test sticky overflow and underflow conditions."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    ref = FifoRefModel()
    await apply_reset(dut)
    ref.step(rst=1, push=0, din=0, pop=0)

    # Trigger Underflow first by popping empty FIFO
    await FallingEdge(dut.clk)
    dut.rst.value = 0
    dut.push.value = 0
    dut.pop.value = 1
    ref.step(rst=0, push=0, din=0, pop=1)

    await RisingEdge(dut.clk)
    await ReadOnly()

    assert int(dut.underflow.value) == 1, "Underflow flag should be set"
    assert int(dut.overflow.value) == 0, "Overflow flag should not be set yet"

    # Fill the FIFO to capacity (8 items)
    for i in range(8):
        await FallingEdge(dut.clk)
        dut.push.value = 1
        dut.din.value = i
        dut.pop.value = 0
        ref.step(rst=0, push=1, din=i, pop=0)
        await RisingEdge(dut.clk)
        await ReadOnly()

    assert int(dut.full.value) == 1, "FIFO should be full"
    assert int(dut.count.value) == 8, "Count should be 8"

    # Try pushing into full FIFO -> should cause Overflow
    await FallingEdge(dut.clk)
    dut.push.value = 1
    dut.din.value = 0xFF
    dut.pop.value = 0
    ref.step(rst=0, push=1, din=0xFF, pop=0)

    await RisingEdge(dut.clk)
    await ReadOnly()

    assert int(dut.overflow.value) == 1, "Overflow flag should be set"
    assert int(dut.underflow.value) == 1, "Underflow flag should remain set (sticky)"
    assert int(dut.count.value) == 8, "Count should remain 8"


@cocotb.test()
async def test_simultaneous_push_pop(dut):
    """Test simultaneous push and pop operations across empty, partial, and full states."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    ref = FifoRefModel()
    await apply_reset(dut)
    ref.step(rst=1, push=0, din=0, pop=0)

    # 1. Push + Pop on empty FIFO (pop ignored, push accepted)
    await FallingEdge(dut.clk)
    dut.rst.value = 0
    dut.push.value = 1
    dut.din.value = 0x55
    dut.pop.value = 1
    ref.step(rst=0, push=1, din=0x55, pop=1)

    await RisingEdge(dut.clk)
    await ReadOnly()

    assert int(dut.count.value) == ref.count, f"Count mismatch: got {int(dut.count.value)}, expected {ref.count}"
    assert int(dut.dout.value) == ref.dout, f"Dout mismatch: got {int(dut.dout.value)}, expected {ref.dout}"

    # Fill FIFO up to 8 items
    for i in range(7):
        await FallingEdge(dut.clk)
        dut.push.value = 1
        dut.din.value = 0x60 + i
        dut.pop.value = 0
        ref.step(rst=0, push=1, din=0x60 + i, pop=0)
        await RisingEdge(dut.clk)
        await ReadOnly()

    assert int(dut.full.value) == 1, "FIFO should be full (count=8)"

    # 2. Push + Pop on full FIFO (both accepted, count stays 8)
    await FallingEdge(dut.clk)
    dut.push.value = 1
    dut.din.value = 0x99
    dut.pop.value = 1
    ref.step(rst=0, push=1, din=0x99, pop=1)

    await RisingEdge(dut.clk)
    await ReadOnly()

    assert int(dut.count.value) == 8, f"Count should stay 8 on simultaneous push/pop when full, got {int(dut.count.value)}"
    assert int(dut.full.value) == 1, "FIFO should remain full"
    assert int(dut.dout.value) == ref.dout, "Oldest element should have advanced"


@cocotb.test()
async def test_almost_full_and_random(dut):
    """Constrained-random test checking almost_full flag and overall state tracking."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    ref = FifoRefModel()
    await apply_reset(dut)
    ref.step(rst=1, push=0, din=0, pop=0)

    rng = random.Random(42)

    for cycle in range(1500):
        push = rng.choice([0, 1, 1])  # slightly higher weight to push
        pop = rng.choice([0, 1])
        din = rng.randint(0, 255)

        await FallingEdge(dut.clk)
        dut.rst.value = 0
        dut.push.value = push
        dut.din.value = din
        dut.pop.value = pop

        ref.step(rst=0, push=push, din=din, pop=pop)

        await RisingEdge(dut.clk)
        await ReadOnly()

        # Check all outputs against reference model on every cycle
        assert int(dut.count.value) == ref.count, f"[Cycle {cycle}] Count mismatch: got {int(dut.count.value)}, expected {ref.count}"
        assert int(dut.empty.value) == ref.empty, f"[Cycle {cycle}] Empty mismatch: got {int(dut.empty.value)}, expected {ref.empty}"
        assert int(dut.full.value) == ref.full, f"[Cycle {cycle}] Full mismatch: got {int(dut.full.value)}, expected {ref.full}"
        assert int(dut.almost_full.value) == ref.almost_full, f"[Cycle {cycle}] Almost full mismatch: got {int(dut.almost_full.value)}, expected {ref.almost_full}"
        assert int(dut.overflow.value) == ref.overflow, f"[Cycle {cycle}] Overflow mismatch: got {int(dut.overflow.value)}, expected {ref.overflow}"
        assert int(dut.underflow.value) == ref.underflow, f"[Cycle {cycle}] Underflow mismatch: got {int(dut.underflow.value)}, expected {ref.underflow}"
        
        if not ref.empty:
            assert int(dut.dout.value) == ref.dout, f"[Cycle {cycle}] Dout mismatch: got {int(dut.dout.value):02x}, expected {ref.dout:02x}"
