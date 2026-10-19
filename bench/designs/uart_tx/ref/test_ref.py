"""Reference testbench for uart_tx (hidden from the agent)."""
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge

CPB = 4


class Model:
    def __init__(self):
        self.reset()

    def reset(self):
        self.seq = None
        self.pos = 0
        self.tx, self.busy, self.done = 1, 0, 0

    def step(self, rst, start, data, pe, po):
        if rst:
            self.reset()
            return
        self.done = 0
        if self.seq is not None:
            self.pos += 1
            if self.pos == len(self.seq):
                self.seq = None
                self.tx, self.busy, self.done = 1, 0, 1
            else:
                self.tx = self.seq[self.pos]
            return
        self.tx = 1
        if start:
            bits = [0] + [(data >> i) & 1 for i in range(8)]
            if pe:
                bits.append((bin(data).count("1") & 1) ^ po)
            bits.append(1)
            self.seq = [b for b in bits for _ in range(CPB)]
            self.pos = 0
            self.tx, self.busy = self.seq[0], 1


async def start_tb(dut):
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    for s in (dut.start, dut.data, dut.parity_en, dut.parity_odd):
        s.value = 0
    dut.rst.value = 1
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst.value = 0
    return Model()


async def cycle(dut, m, start=0, data=0, pe=0, po=0, rst=0):
    await FallingEdge(dut.clk)
    dut.start.value, dut.data.value, dut.parity_en.value = start, data, pe
    dut.parity_odd.value, dut.rst.value = po, rst
    await RisingEdge(dut.clk)
    await ReadOnly()
    m.step(rst, start, data, pe, po)
    got = (int(dut.tx.value), int(dut.busy.value), int(dut.done.value))
    exp = (m.tx, m.busy, m.done)
    assert got == exp, (f"(tx,busy,done)={got} expected {exp} "
                        f"(frame position {m.pos}, start={start} data={data:#04x} pe={pe} po={po} rst={rst})")


async def send(dut, m, data, pe=0, po=0, noise=None):
    await cycle(dut, m, 1, data, pe, po)
    while m.busy:
        if noise:
            await cycle(dut, m, noise.randrange(2), noise.randrange(256), noise.randrange(2), noise.randrange(2))
        else:
            await cycle(dut, m)


@cocotb.test()
async def frames_no_parity(dut):
    m = await start_tb(dut)
    for d in (0x00, 0xFF, 0x55, 0xAA, 0x01, 0x80, 0x3C):
        await send(dut, m, d)
        await cycle(dut, m)


@cocotb.test()
async def frames_with_parity(dut):
    m = await start_tb(dut)
    for d in (0x00, 0x01, 0x03, 0x07, 0xFE, 0xFF, 0x96):
        for po in (0, 1):
            await send(dut, m, d, 1, po)
            await cycle(dut, m)


@cocotb.test()
async def back_to_back_and_ignored_starts(dut):
    m = await start_tb(dut)
    rng = random.Random(12)
    for _ in range(12):
        await send(dut, m, rng.randrange(256), rng.randrange(2), rng.randrange(2), noise=rng)


@cocotb.test()
async def reset_mid_frame(dut):
    m = await start_tb(dut)
    await cycle(dut, m, 1, 0x00, 1, 1)
    for _ in range(17):
        await cycle(dut, m)
    await cycle(dut, m, rst=1)
    await cycle(dut, m)
    await send(dut, m, 0xC3, 1, 0)


@cocotb.test()
async def random_traffic(dut):
    m = await start_tb(dut)
    rng = random.Random(13)
    for _ in range(3000):
        await cycle(dut, m, int(rng.random() < 0.3), rng.randrange(256), rng.randrange(2),
                    rng.randrange(2), int(rng.random() < 0.002))
