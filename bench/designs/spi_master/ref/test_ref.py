"""Reference testbench for spi_master (hidden from the agent)."""
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge

D = 2


class Master:
    """Cycle-accurate model of the master, written from the spec."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.active = self.done = self.sclk = self.mosi = 0
        self.cs_n = 1
        self.rx_data = self.tx_sh = self.rx_sh = self.nbit = self.div = 0

    def step(self, rst, start, tx, miso):
        if rst:
            self.reset()
            return
        self.done = 0
        if not self.active:
            if start:
                self.active, self.cs_n, self.mosi = 1, 0, (tx >> 7) & 1
                self.tx_sh, self.nbit, self.div = (tx << 1) & 0xFF, 0, 0
        elif self.div != D - 1:
            self.div += 1
        else:
            self.div = 0
            if not self.sclk:
                self.sclk = 1
                self.rx_sh = ((self.rx_sh << 1) | miso) & 0xFF
            else:
                self.sclk = 0
                if self.nbit == 7:
                    self.active, self.cs_n, self.done, self.rx_data = 0, 1, 1, self.rx_sh
                else:
                    self.nbit += 1
                    self.mosi = (self.tx_sh >> 7) & 1
                    self.tx_sh = (self.tx_sh << 1) & 0xFF


class Slave:
    """SPI mode-0 slave: drives MISO MSB first, records MOSI on SCLK rising edges."""

    def __init__(self):
        self.byte = 0
        self.idx = 0
        self.got = []
        self.prev_sclk = 0
        self.prev_cs = 1

    def observe(self, cs_n, sclk, mosi):
        if self.prev_cs and not cs_n:
            self.idx = 0
            self.got = []
        if not cs_n and sclk and not self.prev_sclk:
            self.got.append(mosi)
        if not cs_n and self.prev_sclk and not sclk:
            self.idx += 1
        self.prev_sclk, self.prev_cs = sclk, cs_n

    def miso(self, cs_n):
        if cs_n or self.idx > 7:
            return 0
        return (self.byte >> (7 - self.idx)) & 1


async def start_tb(dut):
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    dut.start.value = 0
    dut.tx_data.value = 0
    dut.miso.value = 0
    dut.rst.value = 1
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst.value = 0
    return Master(), Slave()


async def cycle(dut, m, s, start=0, tx=0, rst=0):
    await FallingEdge(dut.clk)
    miso = s.miso(m.cs_n)
    dut.start.value, dut.tx_data.value, dut.rst.value, dut.miso.value = start, tx, rst, miso
    await RisingEdge(dut.clk)
    await ReadOnly()
    m.step(rst, start, tx, miso)
    s.observe(m.cs_n, m.sclk, m.mosi)
    got = {k: int(getattr(dut, k).value) for k in ("cs_n", "sclk", "busy", "done", "rx_data")}
    exp = {"cs_n": m.cs_n, "sclk": m.sclk, "busy": m.active, "done": m.done, "rx_data": m.rx_data}
    assert got == exp, f"got {got} expected {exp} (start={start} tx={tx:#04x} miso={miso} rst={rst})"
    if not m.cs_n:
        assert int(dut.mosi.value) == m.mosi, f"mosi={int(dut.mosi.value)} expected {m.mosi} (bit {m.nbit})"


async def transfer(dut, m, s, tx, slave_byte, noise=None):
    s.byte = slave_byte
    await cycle(dut, m, s, 1, tx)
    while m.active:
        if noise:
            await cycle(dut, m, s, noise.randrange(2), noise.randrange(256))
        else:
            await cycle(dut, m, s)
    assert s.got == [(tx >> (7 - i)) & 1 for i in range(8)], f"slave saw MOSI bits {s.got} for tx {tx:#04x}"
    assert int(dut.rx_data.value) == slave_byte


@cocotb.test()
async def basic_transfers(dut):
    m, s = await start_tb(dut)
    for tx, sb in ((0xA5, 0x3C), (0x00, 0xFF), (0xFF, 0x00), (0x80, 0x01), (0x01, 0x80)):
        await transfer(dut, m, s, tx, sb)
        await cycle(dut, m, s)


@cocotb.test()
async def back_to_back_with_ignored_starts(dut):
    m, s = await start_tb(dut)
    rng = random.Random(14)
    for _ in range(20):
        await transfer(dut, m, s, rng.randrange(256), rng.randrange(256), noise=rng)


@cocotb.test()
async def reset_mid_transfer(dut):
    m, s = await start_tb(dut)
    s.byte = 0xF0
    await cycle(dut, m, s, 1, 0x0F)
    for _ in range(13):
        await cycle(dut, m, s)
    await cycle(dut, m, s, rst=1)
    await cycle(dut, m, s)
    await transfer(dut, m, s, 0x5A, 0xC3)


@cocotb.test()
async def random_traffic(dut):
    m, s = await start_tb(dut)
    rng = random.Random(15)
    for _ in range(3000):
        if not m.active and m.cs_n:
            s.byte = rng.randrange(256)
        await cycle(dut, m, s, int(rng.random() < 0.3), rng.randrange(256), int(rng.random() < 0.002))
