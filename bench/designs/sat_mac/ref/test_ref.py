"""Reference testbench for sat_mac (hidden from the agent)."""
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge


class Model:
    def __init__(self):
        self.acc = 0
        self.sat = 0

    def step(self, rst, valid, clear, a, b):
        if rst:
            self.acc, self.sat = 0, 0
        elif valid:
            s = (0 if clear else self.acc) + a * b
            hit = s > 32767 or s < -32768
            self.acc = max(-32768, min(32767, s))
            self.sat = int(hit or (self.sat and not clear))
        elif clear:
            self.acc, self.sat = 0, 0


async def start(dut):
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    dut.valid.value = 0
    dut.clear.value = 0
    dut.a.value = 0
    dut.b.value = 0
    dut.rst.value = 1
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst.value = 0
    return Model()


async def cycle(dut, m, valid, a, b, clear=0, rst=0):
    await FallingEdge(dut.clk)
    dut.valid.value, dut.clear.value, dut.rst.value = valid, clear, rst
    dut.a.value = a & 0xFF
    dut.b.value = b & 0xFF
    await RisingEdge(dut.clk)
    await ReadOnly()
    m.step(rst, valid, clear, a, b)
    got = (dut.acc.value.signed_integer, int(dut.sat.value))
    assert got == (m.acc, m.sat), (
        f"(acc,sat)={got} expected {(m.acc, m.sat)} after valid={valid} clear={clear} a={a} b={b} rst={rst}")


@cocotb.test()
async def products_and_extremes(dut):
    m = await start(dut)
    vals = [-128, -127, -1, 0, 1, 2, 64, 127]
    for a in vals:
        for b in vals:
            await cycle(dut, m, 1, a, b, clear=1)


@cocotb.test()
async def positive_saturation(dut):
    m = await start(dut)
    for _ in range(4):
        await cycle(dut, m, 1, -128, -128)       # +16384 each time
    for _ in range(3):
        await cycle(dut, m, 1, -100, 100)        # comes back down, sat stays
    await cycle(dut, m, 0, 0, 0, clear=1)


@cocotb.test()
async def negative_saturation(dut):
    m = await start(dut)
    for _ in range(4):
        await cycle(dut, m, 1, -128, 127)
    await cycle(dut, m, 1, 5, 5, clear=1)        # clear+valid: acc = 25, sat = 0
    for _ in range(5):
        await cycle(dut, m, 1, 127, -128)


@cocotb.test()
async def clear_rules(dut):
    m = await start(dut)
    for _ in range(3):
        await cycle(dut, m, 1, -128, -128)
    await cycle(dut, m, 1, -128, -128, clear=1)  # new sum, no saturation this step
    await cycle(dut, m, 1, -128, -128)
    await cycle(dut, m, 1, -128, -128)
    await cycle(dut, m, 1, 100, 100, clear=1)
    await cycle(dut, m, 0, 3, 3)
    await cycle(dut, m, 0, 3, 3, clear=1)
    await cycle(dut, m, 1, 3, 3, rst=1)


@cocotb.test()
async def random_traffic(dut):
    m = await start(dut)
    rng = random.Random(11)
    for _ in range(4000):
        big = rng.random() < 0.5
        a = rng.choice([-128, 127]) if big else rng.randrange(-128, 128)
        b = rng.choice([-128, 127]) if big else rng.randrange(-128, 128)
        await cycle(dut, m, int(rng.random() < 0.85), a, b,
                    clear=int(rng.random() < 0.05), rst=int(rng.random() < 0.003))
