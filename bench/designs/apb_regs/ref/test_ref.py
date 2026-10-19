"""Reference testbench for apb_regs (hidden from the agent)."""
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge, Timer

ID = 0xA5B00001


class Model:
    def __init__(self):
        self.reset()

    def reset(self):
        self.ctrl = 0
        self.data = 0
        self.wr = 0

    def read(self, addr):
        return {0x00: self.ctrl, 0x04: self.data, 0x08: self.wr, 0x0C: ID}.get(addr, 0)

    def error(self, addr, write):
        return int(addr not in (0x00, 0x04, 0x08, 0x0C) or (write and addr in (0x08, 0x0C)))

    def write(self, addr, value):
        if self.error(addr, 1):
            return
        if addr == 0x00:
            self.ctrl = value & 0xFF
        else:
            self.data = value
        self.wr = (self.wr + 1) & 0xFFFF


async def start_tb(dut):
    cocotb.start_soon(Clock(dut.pclk, 10, units="ns").start())
    dut.psel.value = 0
    dut.penable.value = 0
    dut.pwrite.value = 0
    dut.paddr.value = 0
    dut.pwdata.value = 0
    dut.presetn.value = 0
    await Timer(25, "ns")
    await FallingEdge(dut.pclk)
    dut.presetn.value = 1
    return Model()


async def idle_cycle(dut):
    await FallingEdge(dut.pclk)
    dut.psel.value = 0
    dut.penable.value = 0
    await Timer(1, "ns")
    assert int(dut.pready.value) == 1 and int(dut.pslverr.value) == 0, "idle: pready must be 1, pslverr 0"


async def transfer(dut, m, write, addr, wdata=0):
    await FallingEdge(dut.pclk)                         # SETUP
    dut.psel.value, dut.penable.value = 1, 0
    dut.pwrite.value, dut.paddr.value, dut.pwdata.value = write, addr, wdata
    await Timer(1, "ns")
    assert int(dut.pslverr.value) == 0, "pslverr must be 0 in the SETUP phase"
    await FallingEdge(dut.pclk)                         # ACCESS
    dut.penable.value = 1
    waits = 0
    while True:
        await Timer(1, "ns")
        ready = int(dut.pready.value)
        if ready:
            break
        assert int(dut.pslverr.value) == 0, "pslverr must be 0 while pready is 0"
        waits += 1
        assert waits < 3, f"too many wait states at addr {addr:#04x}"
        await FallingEdge(dut.pclk)
    exp_waits = 1 if addr == 0x04 else 0
    assert waits == exp_waits, f"addr {addr:#04x}: {waits} wait states, expected {exp_waits}"
    err = m.error(addr, write)
    assert int(dut.pslverr.value) == err, f"{'write' if write else 'read'} {addr:#04x}: pslverr={int(dut.pslverr.value)} expected {err}"
    if not write:
        got = int(dut.prdata.value)
        assert got == m.read(addr), f"read {addr:#04x}: prdata={got:#010x} expected {m.read(addr):#010x}"
    await RisingEdge(dut.pclk)
    await ReadOnly()
    if write:
        m.write(addr, wdata)


@cocotb.test()
async def reset_values(dut):
    m = await start_tb(dut)
    for addr in (0x00, 0x04, 0x08, 0x0C):
        await transfer(dut, m, 0, addr)
    await idle_cycle(dut)


@cocotb.test()
async def write_read_back(dut):
    m = await start_tb(dut)
    for v in (0xFFFFFFFF, 0x12345678, 0x0, 0xA5A5A5A5, 0x800000FF):
        await transfer(dut, m, 1, 0x00, v)
        await transfer(dut, m, 0, 0x00)
        await transfer(dut, m, 1, 0x04, v ^ 0x0F0F0F0F)
        await transfer(dut, m, 0, 0x04)
        await transfer(dut, m, 0, 0x08)
        await idle_cycle(dut)


@cocotb.test()
async def error_responses(dut):
    m = await start_tb(dut)
    await transfer(dut, m, 1, 0x00, 0x77)
    for addr in (0x08, 0x0C):
        await transfer(dut, m, 1, addr, 0xDEADBEEF)   # write to read-only
        await transfer(dut, m, 0, addr)
    for addr in (0x01, 0x02, 0x03, 0x05, 0x10, 0x40, 0x80, 0xFC, 0xFF):
        await transfer(dut, m, 1, addr, 0x1234)
        await transfer(dut, m, 0, addr)
    await transfer(dut, m, 0, 0x00)
    await transfer(dut, m, 0, 0x04)
    await transfer(dut, m, 0, 0x08)


@cocotb.test()
async def back_to_back_data_accesses(dut):
    m = await start_tb(dut)
    for i in range(10):
        await transfer(dut, m, 1, 0x04, i * 0x01010101)
        await transfer(dut, m, 0, 0x04)
    await transfer(dut, m, 0, 0x08)


@cocotb.test()
async def random_traffic(dut):
    m = await start_tb(dut)
    rng = random.Random(16)
    addrs = [0x00, 0x04, 0x08, 0x0C, 0x00, 0x04, 0x10, 0x02, rng.randrange(256)]
    for _ in range(1500):
        if rng.random() < 0.15:
            await idle_cycle(dut)
        await transfer(dut, m, rng.randrange(2), rng.choice(addrs), rng.getrandbits(32))


@cocotb.test()
async def async_reset(dut):
    m = await start_tb(dut)
    await transfer(dut, m, 1, 0x00, 0xAB)
    await transfer(dut, m, 1, 0x04, 0xCAFEF00D)
    await FallingEdge(dut.pclk)
    dut.psel.value = 0
    dut.penable.value = 0
    await Timer(2, "ns")
    dut.presetn.value = 0
    await Timer(1, "ns")
    m.reset()
    dut.presetn.value = 1
    for addr in (0x00, 0x04, 0x08):
        await transfer(dut, m, 0, addr)
