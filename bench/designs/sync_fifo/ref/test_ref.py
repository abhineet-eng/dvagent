"""Reference testbench for sync_fifo (hidden from the agent)."""
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge


class Model:
    def __init__(self):
        self.reset()

    def reset(self):
        self.q = []
        self.ovf = 0
        self.udf = 0

    def step(self, push, din, pop, rst):
        if rst:
            self.reset()
            return
        do_pop = pop and len(self.q) > 0
        do_push = push and (len(self.q) < 8 or do_pop)
        if do_pop:
            self.q.pop(0)
        if do_push:
            self.q.append(din)
        if push and not do_push:
            self.ovf = 1
        if pop and not do_pop:
            self.udf = 1


def check(dut, m, where):
    n = len(m.q)
    got = {
        "count": int(dut.count.value), "full": int(dut.full.value), "empty": int(dut.empty.value),
        "almost_full": int(dut.almost_full.value), "overflow": int(dut.overflow.value),
        "underflow": int(dut.underflow.value),
    }
    exp = {"count": n, "full": int(n == 8), "empty": int(n == 0), "almost_full": int(n >= 6),
           "overflow": m.ovf, "underflow": m.udf}
    assert got == exp, f"{where}: got {got} expected {exp}"
    if n:
        assert int(dut.dout.value) == m.q[0], f"{where}: dout={int(dut.dout.value):#x} expected {m.q[0]:#x}"


async def start(dut):
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    dut.push.value = 0
    dut.pop.value = 0
    dut.din.value = 0
    dut.rst.value = 1
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst.value = 0
    m = Model()
    check(dut, m, "after reset")
    return m


async def cycle(dut, m, push, din, pop, rst=0):
    await FallingEdge(dut.clk)
    dut.push.value, dut.din.value, dut.pop.value, dut.rst.value = push, din, pop, rst
    await RisingEdge(dut.clk)
    await ReadOnly()
    m.step(push, din, pop, rst)
    check(dut, m, f"after push={push} din={din:#x} pop={pop} rst={rst}")


@cocotb.test()
async def fill_and_drain(dut):
    m = await start(dut)
    for i in range(8):
        await cycle(dut, m, 1, 0x10 + i, 0)
    await cycle(dut, m, 1, 0xEE, 0)           # rejected push -> overflow
    for _ in range(8):
        await cycle(dut, m, 0, 0, 1)
    await cycle(dut, m, 0, 0, 1)              # rejected pop -> underflow
    await cycle(dut, m, 0, 0, 0)


@cocotb.test()
async def simultaneous_push_pop(dut):
    m = await start(dut)
    await cycle(dut, m, 1, 0xA1, 1)           # empty: push accepted, pop rejected
    for i in range(7):
        await cycle(dut, m, 1, i, 0)
    for i in range(10):
        await cycle(dut, m, 1, 0x80 + i, 1)    # full: push and pop together
    for _ in range(8):
        await cycle(dut, m, 0, 0, 1)


@cocotb.test()
async def pointer_wraparound(dut):
    m = await start(dut)
    rng = random.Random(5)
    for _ in range(60):
        for _ in range(rng.randrange(1, 8)):
            await cycle(dut, m, 1, rng.randrange(256), 0)
        while m.q:
            await cycle(dut, m, 0, 0, 1)


@cocotb.test()
async def random_traffic(dut):
    m = await start(dut)
    rng = random.Random(6)
    for i in range(4000):
        bias = 0.7 if (i // 200) % 2 == 0 else 0.3
        await cycle(dut, m, int(rng.random() < bias), rng.randrange(256),
                    int(rng.random() < 1 - bias), int(rng.random() < 0.003))


@cocotb.test()
async def reset_clears_flags(dut):
    m = await start(dut)
    await cycle(dut, m, 0, 0, 1)
    for i in range(9):
        await cycle(dut, m, 1, i, 0)
    await cycle(dut, m, 1, 0x55, 1, rst=1)
    await cycle(dut, m, 1, 0x66, 0)
    await cycle(dut, m, 0, 0, 1)
