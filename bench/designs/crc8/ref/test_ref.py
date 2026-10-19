"""Reference testbench for crc8 (hidden from the agent)."""
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge


def crc_byte(c, d):
    r = c ^ d
    for _ in range(8):
        r = ((r << 1) & 0xFF) ^ 0x07 if r & 0x80 else (r << 1) & 0xFF
    return r


class Model:
    def __init__(self):
        self.crc = 0
        self.n = 0

    def step(self, rst, init, valid, data):
        if rst or init:
            self.crc, self.n = 0, 0
        elif valid:
            self.crc = crc_byte(self.crc, data)
            self.n = (self.n + 1) & 0xFF


async def start(dut):
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    dut.init.value = 0
    dut.valid.value = 0
    dut.data.value = 0
    dut.rst.value = 1
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst.value = 0
    return Model()


async def cycle(dut, m, valid, data, init=0, rst=0):
    await FallingEdge(dut.clk)
    dut.valid.value, dut.data.value, dut.init.value, dut.rst.value = valid, data, init, rst
    await RisingEdge(dut.clk)
    await ReadOnly()
    m.step(rst, init, valid, data)
    got = (int(dut.crc.value), int(dut.nbytes.value))
    assert got == (m.crc, m.n), (
        f"(crc,nbytes)=({got[0]:#04x},{got[1]}) expected ({m.crc:#04x},{m.n}) "
        f"after valid={valid} data={data:#04x} init={init} rst={rst}")


@cocotb.test()
async def check_value(dut):
    m = await start(dut)
    for ch in b"123456789":
        await cycle(dut, m, 1, ch)
    assert int(dut.crc.value) == 0xF4, f"CRC-8 of '123456789' is {int(dut.crc.value):#04x}, expected 0xf4"


@cocotb.test()
async def every_single_byte(dut):
    m = await start(dut)
    for d in range(256):
        await cycle(dut, m, 1, 0, init=1)
        await cycle(dut, m, 1, d)


@cocotb.test()
async def random_streams_with_gaps(dut):
    m = await start(dut)
    rng = random.Random(10)
    for _ in range(3000):
        await cycle(dut, m, int(rng.random() < 0.75), rng.randrange(256),
                    init=int(rng.random() < 0.02), rst=int(rng.random() < 0.005))


@cocotb.test()
async def byte_counter_wraps(dut):
    m = await start(dut)
    for i in range(300):
        await cycle(dut, m, 1, i & 0xFF)
    await cycle(dut, m, 1, 0x12, init=1)
    await cycle(dut, m, 0, 0x34)
