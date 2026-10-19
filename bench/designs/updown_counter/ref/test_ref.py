"""Reference testbench for updown_counter (hidden from the agent)."""
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge, Timer


class Model:
    def __init__(self):
        self.count = 0

    def tc(self, en, up, load, mx):
        if not en or load:
            return 0
        return int(self.count >= mx) if up else int(self.count == 0)

    def step(self, en, up, load, d, mx):
        if load:
            self.count = mx if d > mx else d
        elif en and up:
            self.count = 0 if self.count >= mx else self.count + 1
        elif en:
            self.count = mx if self.count == 0 else self.count - 1


async def start(dut):
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    dut.en.value = 0
    dut.up.value = 1
    dut.load.value = 0
    dut.d.value = 0
    dut.max_val.value = 255
    dut.rst_n.value = 0
    await Timer(23, "ns")
    assert int(dut.count.value) == 0
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1


async def cycle(dut, m, en, up, load, d, mx):
    await FallingEdge(dut.clk)
    dut.en.value, dut.up.value, dut.load.value = en, up, load
    dut.d.value, dut.max_val.value = d, mx
    await Timer(1, "ns")
    exp_tc = m.tc(en, up, load, mx)
    assert int(dut.tc.value) == exp_tc, (
        f"tc={int(dut.tc.value)} expected {exp_tc} (count={m.count} en={en} up={up} load={load} max={mx})")
    assert int(dut.zero.value) == int(m.count == 0), f"zero wrong at count={m.count}"
    await RisingEdge(dut.clk)
    await ReadOnly()
    m.step(en, up, load, d, mx)
    got = int(dut.count.value)
    assert got == m.count, (
        f"count={got} expected {m.count} after en={en} up={up} load={load} d={d} max={mx}")


@cocotb.test()
async def wrap_up_and_down(dut):
    await start(dut)
    m = Model()
    for mx in (5, 0, 1, 255):
        await cycle(dut, m, 0, 1, 1, 0, mx)
        for _ in range(mx + 3 if mx < 20 else 300):
            await cycle(dut, m, 1, 1, 0, 0, mx)
        for _ in range(mx + 3 if mx < 20 else 300):
            await cycle(dut, m, 1, 0, 0, 0, mx)


@cocotb.test()
async def load_clamp_and_priority(dut):
    await start(dut)
    m = Model()
    for d, mx in ((7, 9), (9, 9), (10, 9), (255, 0), (0, 0), (200, 100), (100, 200)):
        await cycle(dut, m, 1, 1, 1, d, mx)      # load wins over count
        await cycle(dut, m, 1, 0, 1, d, mx)
        await cycle(dut, m, 0, 0, 0, 3, mx)      # hold
        await cycle(dut, m, 1, 1, 0, 0, mx)


@cocotb.test()
async def max_lowered_below_count(dut):
    await start(dut)
    m = Model()
    await cycle(dut, m, 0, 1, 1, 50, 60)
    await cycle(dut, m, 1, 1, 0, 0, 20)          # count 50 > max 20 -> wraps to 0
    await cycle(dut, m, 0, 1, 1, 50, 60)
    await cycle(dut, m, 1, 0, 0, 0, 20)          # down from 50 with max 20 -> 49
    await cycle(dut, m, 1, 1, 0, 0, 49)          # count 49 == max -> wrap


@cocotb.test()
async def random_traffic(dut):
    await start(dut)
    m = Model()
    rng = random.Random(7)
    for _ in range(3000):
        mx = rng.choice([rng.randrange(256), rng.randrange(12), 255, 0])
        await cycle(dut, m, int(rng.random() < 0.8), rng.randrange(2),
                    int(rng.random() < 0.08), rng.randrange(256), mx)


@cocotb.test()
async def async_reset(dut):
    await start(dut)
    m = Model()
    for _ in range(5):
        await cycle(dut, m, 1, 1, 0, 0, 100)
    await FallingEdge(dut.clk)
    await Timer(2, "ns")
    dut.rst_n.value = 0
    await Timer(1, "ns")
    assert int(dut.count.value) == 0, "reset must clear count without a clock edge"
    await RisingEdge(dut.clk)
    await ReadOnly()
    assert int(dut.count.value) == 0
