"""Reference testbench for rr_arbiter (hidden from the agent)."""
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge


class Model:
    def __init__(self):
        self.reset()

    def reset(self):
        self.grant = 0
        self.owner = 0
        self.last = 3

    def step(self, req, rst):
        if rst:
            self.reset()
            return
        if self.grant and (req >> self.owner) & 1:
            return
        for k in range(1, 5):
            i = (self.last + k) % 4
            if (req >> i) & 1:
                self.grant, self.owner, self.last = 1 << i, i, i
                return
        self.grant = 0


async def start(dut):
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    dut.req.value = 0
    dut.rst.value = 1
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst.value = 0
    return Model()


async def cycle(dut, m, req, rst=0):
    await FallingEdge(dut.clk)
    dut.req.value, dut.rst.value = req, rst
    await RisingEdge(dut.clk)
    await ReadOnly()
    m.step(req, rst)
    got = (int(dut.grant.value), int(dut.owner.value), int(dut.busy.value))
    exp = (m.grant, m.owner, int(m.grant != 0))
    assert got == exp, f"(grant,owner,busy)={got} expected {exp} after req={req:04b} rst={rst}"


@cocotb.test()
async def rotation_all_requesting(dut):
    m = await start(dut)
    for _ in range(12):
        await cycle(dut, m, 0b1111)
        await cycle(dut, m, 0b1111 & ~m.grant)   # owner drops its request -> hand over


@cocotb.test()
async def single_requesters(dut):
    m = await start(dut)
    for i in [0, 1, 2, 3, 3, 2, 1, 0, 2, 0, 3, 1]:
        await cycle(dut, m, 1 << i)
        await cycle(dut, m, 1 << i)
        await cycle(dut, m, 0)


@cocotb.test()
async def owner_keeps_bus(dut):
    m = await start(dut)
    await cycle(dut, m, 0b0100)
    for _ in range(6):
        await cycle(dut, m, 0b1111)                 # owner 2 keeps it
    await cycle(dut, m, 0b1011)                     # releases -> 3
    await cycle(dut, m, 0b0011)                     # 3 releases -> 0
    await cycle(dut, m, 0b0110)                     # 0 releases -> 1


@cocotb.test()
async def random_bus_traffic(dut):
    m = await start(dut)
    rng = random.Random(8)
    hold = [0, 0, 0, 0]
    for _ in range(3000):
        req = 0
        for i in range(4):
            if hold[i] == 0 and rng.random() < 0.3:
                hold[i] = rng.randrange(1, 6)
            if hold[i]:
                req |= 1 << i
                hold[i] -= 1
        await cycle(dut, m, req, int(rng.random() < 0.004))


@cocotb.test()
async def random_toggling(dut):
    m = await start(dut)
    rng = random.Random(9)
    for _ in range(2000):
        await cycle(dut, m, rng.randrange(16))
