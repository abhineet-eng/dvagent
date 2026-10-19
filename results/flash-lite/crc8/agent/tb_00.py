"""
Verification Plan for crc8 (CRC-8 / SMBUS):
1. Reset Behavior: Verify synchronous active-high reset sets crc to 0x00 and nbytes to 0.
2. Init Behavior: Verify synchronous init signal resets crc to 0x00 and nbytes to 0.
3. Hold Behavior: Verify outputs hold their values when valid = 0 and no reset/init is active.
4. Single Byte Processing: Verify CRC calculation for a single byte against the reference model.
5. Stream Processing (ASCII "123456789"): Verify standard check value 0xF4 after processing "123456789".
6. Byte Counter Wrap-around: Verify nbytes wraps around from 255 to 0.
7. Constrained-Random Testing: Run a randomized stream of valid/invalid bytes, resets, and inits to ensure robustness.
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, ReadOnly, Timer
import random

class CRC8ReferenceModel:
    def __init__(self):
        self.crc = 0x00
        self.nbytes = 0

    def step(self, rst, init, valid, data):
        if rst or init:
            self.crc = 0x00
            self.nbytes = 0
        elif valid:
            r = self.crc ^ data
            for _ in range(8):
                if (r & 0x80) != 0:
                    r = ((r << 1) & 0xFF) ^ 0x07
                else:
                    r = (r << 1) & 0xFF
            self.crc = r
            self.nbytes = (self.nbytes + 1) & 0xFF
        # else hold

async def reset_dut(dut):
    dut.rst.value = 1
    dut.init.value = 0
    dut.valid.value = 0
    dut.data.value = 0
    await FallingEdge(dut.clk)
    await RisingEdge(dut.clk)
    await ReadOnly()

@cocotb.test()
async def test_reset_and_init(dut):
    """Test synchronous reset and init functionality."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    ref = CRC8ReferenceModel()

    await reset_dut(dut)
    
    # Release reset, drive some data
    await FallingEdge(dut.clk)
    dut.rst.value = 0
    dut.valid.value = 1
    dut.data.value = 0x55
    await RisingEdge(dut.clk)
    await ReadOnly()
    ref.step(rst=0, init=0, valid=1, data=0x55)
    
    assert int(dut.crc.value) == ref.crc, f"Mismatch after data: got {hex(int(dut.crc.value))}, expected {hex(ref.crc)}"
    assert int(dut.nbytes.value) == ref.nbytes, f"Mismatch nbytes: got {int(dut.nbytes.value)}, expected {ref.nbytes}"

    # Test init
    await FallingEdge(dut.clk)
    dut.init.value = 1
    dut.valid.value = 0
    await RisingEdge(dut.clk)
    await ReadOnly()
    ref.step(rst=0, init=1, valid=0, data=0)

    assert int(dut.crc.value) == 0x00, f"Init failed crc: {hex(int(dut.crc.value))}"
    assert int(dut.nbytes.value) == 0, f"Init failed nbytes: {int(dut.nbytes.value)}"

    # Test rst
    await FallingEdge(dut.clk)
    dut.init.value = 0
    dut.rst.value = 1
    await RisingEdge(dut.clk)
    await ReadOnly()
    ref.step(rst=1, init=0, valid=0, data=0)

    assert int(dut.crc.value) == 0x00, f"Rst failed crc: {hex(int(dut.crc.value))}"
    assert int(dut.nbytes.value) == 0, f"Rst failed nbytes: {int(dut.nbytes.value)}"


@cocotb.test()
async def test_hold_behavior(dut):
    """Test that outputs hold when valid=0."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    ref = CRC8ReferenceModel()

    await reset_dut(dut)
    dut.rst.value = 0

    # Send one byte
    await FallingEdge(dut.clk)
    dut.valid.value = 1
    dut.data.value = 0xAB
    await RisingEdge(dut.clk)
    await ReadOnly()
    ref.step(0, 0, 1, 0xAB)
    
    expected_crc = ref.crc
    expected_nbytes = ref.nbytes

    # Now deassert valid for a few cycles
    for _ in range(5):
        await FallingEdge(dut.clk)
        dut.valid.value = 0
        dut.data.value = random.randint(0, 255)
        await RisingEdge(dut.clk)
        await ReadOnly()
        ref.step(0, 0, 0, int(dut.data.value))

        assert int(dut.crc.value) == expected_crc, f"CRC changed on invalid cycle: got {hex(int(dut.crc.value))}, expected {hex(expected_crc)}"
        assert int(dut.nbytes.value) == expected_nbytes, f"nbytes changed on invalid cycle: got {int(dut.nbytes.value)}, expected {expected_nbytes}"


@cocotb.test()
async def test_ascii_123456789(dut):
    """Test CRC-8 check value 0xF4 for ASCII string '123456789'."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    ref = CRC8ReferenceModel()

    await reset_dut(dut)
    dut.rst.value = 0

    data_bytes = [ord(c) for c in "123456789"]

    for b in data_bytes:
        await FallingEdge(dut.clk)
        dut.valid.value = 1
        dut.data.value = b
        await RisingEdge(dut.clk)
        await ReadOnly()
        ref.step(0, 0, 1, b)

        assert int(dut.crc.value) == ref.crc
        assert int(dut.nbytes.value) == ref.nbytes

    assert int(dut.crc.value) == 0xF4, f"Check value mismatch: got {hex(int(dut.crc.value))}, expected 0xF4"
    assert int(dut.nbytes.value) == 9, f"nbytes mismatch: got {int(dut.nbytes.value)}, expected 9"


@cocotb.test()
async def test_nbytes_wrap(dut):
    """Test nbytes wrapping from 255 to 0."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    ref = CRC8ReferenceModel()

    await reset_dut(dut)
    dut.rst.value = 0

    # Feed 256 bytes
    for i in range(260):
        val = i & 0xFF
        await FallingEdge(dut.clk)
        dut.valid.value = 1
        dut.data.value = val
        await RisingEdge(dut.clk)
        await ReadOnly()
        ref.step(0, 0, 1, val)

        assert int(dut.crc.value) == ref.crc, f"Cycle {i}: crc got {hex(int(dut.crc.value))}, expected {hex(ref.crc)}"
        assert int(dut.nbytes.value) == ref.nbytes, f"Cycle {i}: nbytes got {int(dut.nbytes.value)}, expected {ref.nbytes}"


@cocotb.test()
async def test_constrained_random(dut):
    """Constrained-random test with mixed valid, invalid, init, rst, and data."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    ref = CRC8ReferenceModel()

    await reset_dut(dut)
    dut.rst.value = 0

    rng = random.Random(42)

    for cycle in range(1000):
        rst = 1 if rng.random() < 0.02 else 0
        init = 1 if (not rst and rng.random() < 0.02) else 0
        valid = rng.choice([0, 1])
        data = rng.randint(0, 255)

        await FallingEdge(dut.clk)
        dut.rst.value = rst
        dut.init.value = init
        dut.valid.value = valid
        dut.data.value = data
        await RisingEdge(dut.clk)
        await ReadOnly()

        ref.step(rst, init, valid, data)

        assert int(dut.crc.value) == ref.crc, f"Cycle {cycle}: CRC mismatch. Got {hex(int(dut.crc.value))}, Expected {hex(ref.crc)}"
        assert int(dut.nbytes.value) == ref.nbytes, f"Cycle {cycle}: nbytes mismatch. Got {int(dut.nbytes.value)}, Expected {ref.nbytes}"
