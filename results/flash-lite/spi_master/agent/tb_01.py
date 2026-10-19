"""
Verification Plan for spi_master:
1. Reset Behavior: Verify all outputs match reset state (cs_n=1, sclk=0, busy=0, done=0, rx_data=0, mosi=0).
2. Basic Transfer: Execute a standard 8-bit SPI transfer (CLK_DIV=2), checking sclk transitions, mosi data (MSB first), miso sampling on sclk rising edges, and done pulse at the end.
3. Reference Model Comparison: Use a cycle-accurate Python reference model mirroring the spec and check DUT against it every cycle during random tests.
4. Back-to-Back Transfers: Start a new transfer immediately on the cycle `done` is active.
5. Start Ignore: Assert `start` while `busy=1` and ensure it is ignored.
6. Parameter Variations: Test with different CLK_DIV values (e.g., CLK_DIV=1, CLK_DIV=4).
7. Constrained Random Test: Send random tx_data and provide random miso patterns, verifying full-duplex correctness.
"""

import random
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, ReadOnly, Timer, ClockCycles

class SpiMasterRefModel:
    def __init__(self, clk_div=2):
        self.clk_div = clk_div
        self.cs_n = 1
        self.sclk = 0
        self.busy = 0
        self.done = 0
        self.rx_data = 0
        self.mosi = 0
        
        self.state = "IDLE"
        self.counter = 0
        self.tx_shift = 0
        self.rx_shift = 0
        self.bit_idx = 0

    def step(self, start, tx_data, miso):
        # Sample inputs at rising edge of clk
        prev_done = self.done
        self.done = 0

        if self.state == "IDLE":
            self.cs_n = 1
            self.sclk = 0
            self.busy = 0
            if start:
                self.state = "TRANSFER"
                self.counter = 1
                self.tx_shift = tx_data
                self.rx_shift = 0
                self.bit_idx = 0
                self.busy = 1
                self.cs_n = 0
                self.sclk = 0
                self.mosi = (self.tx_shift >> 7) & 1

        elif self.state == "TRANSFER":
            D = self.clk_div
            # Check events based on counter from edge 0
            # k goes from 1 to 8
            # at edge (2k - 1)*D: sclk rises, sample miso
            # at edge 2k*D: sclk falls, mosi changes for k < 8
            # at edge 16*D: transfer ends

            for k in range(1, 9):
                rise_edge = (2 * k - 1) * D
                fall_edge = (2 * k) * D

                if self.counter == rise_edge:
                    self.sclk = 1
                    bit = miso & 1
                    self.rx_shift = ((self.rx_shift << 1) | bit) & 0xFF

                if self.counter == fall_edge:
                    self.sclk = 0
                    if k < 8:
                        self.mosi = (self.tx_shift >> (7 - k)) & 1

            if self.counter == 16 * D:
                self.cs_n = 1
                self.busy = 0
                self.rx_data = self.rx_shift
                self.done = 1
                self.state = "IDLE"
            else:
                self.counter += 1

        return {
            "cs_n": self.cs_n,
            "sclk": self.sclk,
            "busy": self.busy,
            "done": prev_done,
            "rx_data": self.rx_data,
            "mosi": self.mosi
        }

async def reset_dut(dut):
    dut.rst.value = 1
    dut.start.value = 0
    dut.tx_data.value = 0
    dut.miso.value = 0
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.rst.value = 0
    await ReadOnly()

@cocotb.test()
async def test_reset_and_defaults(dut):
    """Test reset state matches specification."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    dut.rst.value = 1
    dut.start.value = 0
    dut.tx_data.value = 0
    dut.miso.value = 0
    await ClockCycles(dut.clk, 2)
    await ReadOnly()

    assert int(dut.cs_n.value) == 1, f"Reset cs_n expected 1, got {int(dut.cs_n.value)}"
    assert int(dut.sclk.value) == 0, f"Reset sclk expected 0, got {int(dut.sclk.value)}"
    assert int(dut.busy.value) == 0, f"Reset busy expected 0, got {int(dut.busy.value)}"
    assert int(dut.done.value) == 0, f"Reset done expected 0, got {int(dut.done.value)}"
    assert int(dut.rx_data.value) == 0, f"Reset rx_data expected 0, got {int(dut.rx_data.value)}"
    assert int(dut.mosi.value) == 0, f"Reset mosi expected 0, got {int(dut.mosi.value)}"

@cocotb.test()
async def test_basic_transfer(dut):
    """Test a single basic 8-bit transfer with CLK_DIV=2."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset_dut(dut)

    ref = SpiMasterRefModel(clk_div=2)
    tx_val = 0xA5
    miso_stream = [1, 0, 1, 1, 0, 0, 1, 0]
    
    # Start transfer
    await FallingEdge(dut.clk)
    dut.start.value = 1
    dut.tx_data.value = tx_val
    dut.miso.value = miso_stream[0]

    total_cycles = 16 * 2 + 3
    miso_idx = 0

    for cycle in range(total_cycles):
        await RisingEdge(dut.clk)
        await ReadOnly()

        start_val = int(dut.start.value)
        tx_val_val = int(dut.tx_data.value)
        miso_val = int(dut.miso.value)

        ref_out = ref.step(start_val, tx_val_val, miso_val)

        assert int(dut.cs_n.value) == ref_out["cs_n"], f"Cycle {cycle}: cs_n mismatch. Expected {ref_out['cs_n']}, got {int(dut.cs_n.value)}"
        assert int(dut.sclk.value) == ref_out["sclk"], f"Cycle {cycle}: sclk mismatch. Expected {ref_out['sclk']}, got {int(dut.sclk.value)}"
        assert int(dut.busy.value) == ref_out["busy"], f"Cycle {cycle}: busy mismatch. Expected {ref_out['busy']}, got {int(dut.busy.value)}"
        assert int(dut.done.value) == ref_out["done"], f"Cycle {cycle}: done mismatch. Expected {ref_out['done']}, got {int(dut.done.value)}"
        assert int(dut.rx_data.value) == ref_out["rx_data"], f"Cycle {cycle}: rx_data mismatch. Expected {ref_out['rx_data']}, got {int(dut.rx_data.value)}"
        if int(dut.cs_n.value) == 0:
            assert int(dut.mosi.value) == ref_out["mosi"], f"Cycle {cycle}: mosi mismatch. Expected {ref_out['mosi']}, got {int(dut.mosi.value)}"

        await FallingEdge(dut.clk)
        if cycle == 0:
            dut.start.value = 0

        miso_idx = (miso_idx + 1) % len(miso_stream)
        dut.miso.value = miso_stream[miso_idx]

@cocotb.test()
async def test_constrained_random(dut):
    """Constrained random transactions with reference model checking."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset_dut(dut)

    rng = random.Random(42)
    ref = SpiMasterRefModel(clk_div=2)

    current_miso = 0
    dut.miso.value = current_miso
    dut.start.value = 0
    dut.tx_data.value = 0

    for _ in range(3):
        tx_val = rng.randint(0, 255)
        
        await FallingEdge(dut.clk)
        dut.start.value = 1
        dut.tx_data.value = tx_val

        await RisingEdge(dut.clk)
        await ReadOnly()

        ref.step(1, tx_val, int(dut.miso.value))
        
        await FallingEdge(dut.clk)
        dut.start.value = 0

        while True:
            await RisingEdge(dut.clk)
            await ReadOnly()

            current_miso = rng.randint(0, 1)
            dut.miso.value = current_miso

            ref_out = ref.step(0, 0, current_miso)

            assert int(dut.cs_n.value) == ref_out["cs_n"]
            assert int(dut.sclk.value) == ref_out["sclk"]
            assert int(dut.busy.value) == ref_out["busy"]
            assert int(dut.done.value) == ref_out["done"]
            assert int(dut.rx_data.value) == ref_out["rx_data"]
            if int(dut.cs_n.value) == 0:
                assert int(dut.mosi.value) == ref_out["mosi"]

            if int(dut.done.value) == 1:
                await FallingEdge(dut.clk)
                break
            await FallingEdge(dut.clk)

@cocotb.test()
async def test_start_ignored_while_busy(dut):
    """Verify that start is ignored when busy=1."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset_dut(dut)

    ref = SpiMasterRefModel(clk_div=2)

    await FallingEdge(dut.clk)
    dut.start.value = 1
    dut.tx_data.value = 0x55
    dut.miso.value = 0

    await RisingEdge(dut.clk)
    await ReadOnly()
    ref.step(1, 0x55, 0)

    await FallingEdge(dut.clk)
    dut.start.value = 0

    for i in range(5):
        await RisingEdge(dut.clk)
        await ReadOnly()
        ref.step(0, 0, 0)
        await FallingEdge(dut.clk)

    await FallingEdge(dut.clk)
    dut.start.value = 1
    dut.tx_data.value = 0xAA

    await RisingEdge(dut.clk)
    await ReadOnly()
    ref_out = ref.step(1, 0xAA, 0)
    assert int(dut.busy.value) == 1
    assert int(dut.cs_n.value) == 0

    await FallingEdge(dut.clk)
    dut.start.value = 0

    while int(dut.busy.value) == 1:
        await RisingEdge(dut.clk)
        await ReadOnly()
        ref.step(0, 0, 0)
        await FallingEdge(dut.clk)
