"""Reference testbench for seq_detector (hidden from the agent)."""
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge


class Model:
    def __init__(self):
        self.reset()

    def reset(self):
        self.hist = []
        self.match = 0
        self.count = 0

    def step(self, rst, din, valid):
        if rst:
            self.reset()
            return
        hit = 0
        if valid:
            self.hist = (self.hist + [din])[-4:]
            hit = int(self.hist == [1, 0, 1, 1])
        self.match = hit
        if hit and self.count < 255:
            self.count += 1


async def start(dut):
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    dut.din.value = 0
    dut.din_valid.value = 0
    dut.rst.value = 1
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst.value = 0
    return Model()


async def cycle(dut, m, din, valid, rst=0):
    await FallingEdge(dut.clk)
    dut.din.value, dut.din_valid.value, dut.rst.value = din, valid, rst
    await RisingEdge(dut.clk)
    await ReadOnly()
    m.step(rst, din, valid)
    got = (int(dut.match.value), int(dut.count.value))
    assert got == (m.match, m.count), (
        f"(match,count)={got} expected {(m.match, m.count)} after din={din} valid={valid} rst={rst}")


async def stream(dut, m, bits, gap_prob=0.0, rng=None):
    for b in bits:
        while rng is not None and rng.random() < gap_prob:
            await cycle(dut, m, rng.randrange(2), 0)
        await cycle(dut, m, b, 1)


@cocotb.test()
async def overlap_patterns(dut):
    m = await start(dut)
    for pat in ("1011011", "10111011", "1011", "0101101011", "111011", "1010110"):
        await stream(dut, m, [int(c) for c in pat])
        await stream(dut, m, [0, 0, 0, 0])


@cocotb.test()
async def valid_gaps_do_not_break_pattern(dut):
    m = await start(dut)
    rng = random.Random(3)
    for _ in range(40):
        await stream(dut, m, [1, 0, 1, 1], gap_prob=0.5, rng=rng)


@cocotb.test()
async def random_stream(dut):
    m = await start(dut)
    rng = random.Random(4)
    for _ in range(4000):
        await cycle(dut, m, rng.randrange(2), int(rng.random() < 0.7))


@cocotb.test()
async def count_saturates(dut):
    m = await start(dut)
    for _ in range(260):
        await stream(dut, m, [1, 0, 1, 1])
    assert m.count == 255


@cocotb.test()
async def reset_clears_partial_match(dut):
    m = await start(dut)
    await stream(dut, m, [1, 0, 1, 1, 0, 1])
    await cycle(dut, m, 1, 1, rst=1)
    await stream(dut, m, [1, 0, 1, 1])
    await stream(dut, m, [1, 0, 1])
    await cycle(dut, m, 0, 0, rst=1)
    await stream(dut, m, [1, 1, 0, 1, 1])
