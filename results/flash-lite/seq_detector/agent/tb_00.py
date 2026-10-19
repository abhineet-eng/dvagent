"""
Verification Plan for seq_detector:
1. Reset behavior: Verify that 'rst' active-high clears 'match' and 'count' to 0 and resets state.
2. Din_valid gating: Verify that when 'din_valid' = 0, bits are ignored (don't affect matching or break sequences).
3. Basic pattern detection: Verify simple "1011" sequence detection and 'match' pulse generation (1 cycle).
4. Overlapping patterns: Verify that "1011011" correctly generates two matches.
5. Consecutive overlapping patterns: Verify "10111011" yields two matches.
6. Count saturation: Verify that 'count' increments correctly on each match and saturates at 255.
7. Random stimulus testing: Use a constrained-random bit stream with variable 'din_valid' toggling,
   compared cycle-by-cycle against a Python reference model.
"""

import random
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, ReadOnly, ClockCycles

class SeqDetectorRefModel:
    def __init__(self):
        self.state = 0  # number of matched bits in "1011" (0 to 3)
        self.count = 0
        self.match = 0

    def step(self, rst, din, din_valid):
        if rst:
            self.state = 0
            self.count = 0
            self.match = 0
            return self.match, self.count

        # match is a registered output for one cycle
        self.match = 0

        if din_valid:
            bit = din & 1
            if self.state == 0:
                if bit == 1:
                    self.state = 1
                else:
                    self.state = 0
            elif self.state == 1:
                if bit == 0:
                    self.state = 2
                else:
                    self.state = 1  # remaining in state 1 if bit is 1 (e.g. 11)
            elif self.state == 2:
                if bit == 1:
                    self.state = 3
                else:
                    self.state = 0
            elif self.state == 3:
                if bit == 1:
                    # Match completed! Overlap: trailing '1' is the first bit of next occurrence
                    self.match = 1
                    if self.count < 255:
                        self.count += 1
                    self.state = 1
                else:
                    if bit == 0:
                        self.state = 2
                    else:
                        self.state = 1

        return self.match, self.count


async def reset_dut(dut):
    dut.rst.value = 1
    dut.din.value = 0
    dut.din_valid.value = 0
    await FallingEdge(dut.clk)
    await RisingEdge(dut.clk)
    await ReadOnly()
    dut.rst.value = 0
    await FallingEdge(dut.clk)


@cocotb.test()
async def test_reset(dut):
    """Test reset clears outputs and internal state."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    
    # Initialize
    dut.rst.value = 1
    dut.din.value = 0
    dut.din_valid.value = 0
    await ClockCycles(dut.clk, 2)
    
    await ReadOnly()
    assert int(dut.match.value) == 0, f"Match not 0 after reset: got {int(dut.match.value)}"
    assert int(dut.count.value) == 0, f"Count not 0 after reset: got {int(dut.count.value)}"


@cocotb.test()
async def test_din_valid_gating(dut):
    """Test that din_valid=0 ignores inputs completely."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    ref = SeqDetectorRefModel()
    await reset_dut(dut)

    # Send "1011" with din_valid=0 sprinkled around
    stream = [
        (1, 0),  # ignored
        (1, 1),  # part of 1011 (state 1)
        (0, 0),  # ignored
        (0, 1),  # part of 1011 (state 2)
        (1, 0),  # ignored
        (1, 1),  # part of 1011 (state 3)
        (1, 1),  # completes 1011 -> match
    ]

    for din, valid in stream:
        await FallingEdge(dut.clk)
        dut.din.value = din
        dut.din_valid.value = valid
        
        expected_match, expected_count = ref.step(0, din, valid)
        await RisingEdge(dut.clk)
        await ReadOnly()

        assert int(dut.match.value) == expected_match, f"Match mismatch on stream element ({din}, valid={valid}). Expected {expected_match}, got {int(dut.match.value)}"
        assert int(dut.count.value) == expected_count, f"Count mismatch on stream element ({din}, valid={valid}). Expected {expected_count}, got {int(dut.count.value)}"


@cocotb.test()
async def test_basic_and_overlapping(dut):
    """Test basic 1011 pattern and overlapping occurrences like 1011011."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    ref = SeqDetectorRefModel()
    await reset_dut(dut)

    # "1011011"
    bits = [1, 0, 1, 1, 0, 1, 1]

    for b in bits:
        await FallingEdge(dut.clk)
        dut.din.value = b
        dut.din_valid.value = 1

        expected_match, expected_count = ref.step(0, b, 1)
        await RisingEdge(dut.clk)
        await ReadOnly()

        assert int(dut.match.value) == expected_match, f"Match mismatch for bit {b}. Expected {expected_match}, got {int(dut.match.value)}"
        assert int(dut.count.value) == expected_count, f"Count mismatch for bit {b}. Expected {expected_count}, got {int(dut.count.value)}"


@cocotb.test()
async def test_count_saturation(dut):
    """Test that count saturates at 255 and never wraps."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    ref = SeqDetectorRefModel()
    await reset_dut(dut)

    # We need 260 matches. Each match can be achieved with "1011".
    # To chain them efficiently with overlap: "1011" followed by repeating "011" gives matches.
    # Actually, each "011" after "1011" completes another "1011" due to overlap!
    # e.g., 1011 011 011 011 ...
    sequence = [1, 0, 1, 1] + [0, 1, 1] * 260

    for idx, b in enumerate(sequence):
        await FallingEdge(dut.clk)
        dut.din.value = b
        dut.din_valid.value = 1

        expected_match, expected_count = ref.step(0, b, 1)
        await RisingEdge(dut.clk)
        await ReadOnly()

        assert int(dut.match.value) == expected_match, f"Match mismatch at index {idx} (bit {b}). Expected {expected_match}, got {int(dut.match.value)}"
        assert int(dut.count.value) == expected_count, f"Count mismatch at index {idx} (bit {b}). Expected {expected_count}, got {int(dut.count.value)}"

    assert int(dut.count.value) == 255, f"Count did not saturate at 255, got {int(dut.count.value)}"


@cocotb.test()
async def test_constrained_random(dut):
    """Constrained-random test of bit streams and valid flags with reference model check."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    ref = SeqDetectorRefModel()
    await reset_dut(dut)

    rng = random.Random(42)

    # Run 5000 random cycles
    for cycle in range(5000):
        # Periodically reset to test reset robustness during random operation
        if cycle == 2500:
            await FallingEdge(dut.clk)
            dut.rst.value = 1
            dut.din.value = 0
            dut.din_valid.value = 0
            ref.step(1, 0, 0)
            await RisingEdge(dut.clk)
            await ReadOnly()
            await FallingEdge(dut.clk)
            dut.rst.value = 0
            continue

        din = rng.choice([0, 1])
        din_valid = rng.choices([0, 1], weights=[3, 7])[0] # 70% valid rate

        await FallingEdge(dut.clk)
        dut.din.value = din
        dut.din_valid.value = din_valid

        expected_match, expected_count = ref.step(0, din, din_valid)
        await RisingEdge(dut.clk)
        await ReadOnly()

        assert int(dut.match.value) == expected_match, \
            f"Cycle {cycle}: Match mismatch (din={din}, valid={din_valid}). Expected {expected_match}, got {int(dut.match.value)}"
        assert int(dut.count.value) == expected_count, \
            f"Cycle {cycle}: Count mismatch (din={din}, valid={din_valid}). Expected {expected_count}, got {int(dut.count.value)}"
