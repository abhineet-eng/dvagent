"""Reference testbench for alu8 (hidden from the agent)."""
import random

import cocotb
from cocotb.triggers import Timer


def sgn(x):
    return x - 256 if x & 0x80 else x


def model(a, b, op):
    s = b & 7
    c = v = 0
    if op == 0:
        r = a + b
        y, c = r & 0xFF, int(r > 255)
        v = int((a >> 7) == (b >> 7) and (y >> 7) != (a >> 7))
    elif op == 1:
        y, c = (a - b) & 0xFF, int(a < b)
        v = int((a >> 7) != (b >> 7) and (y >> 7) != (a >> 7))
    elif op == 2:
        y = a & b
    elif op == 3:
        y = a | b
    elif op == 4:
        y = a ^ b
    elif op == 5:
        y = (a << s) & 0xFF
        c = (a >> (8 - s)) & 1 if s else 0
    elif op == 6:
        y = a >> s
        c = (a >> (s - 1)) & 1 if s else 0
    else:
        y = int(sgn(a) < sgn(b))
    return y, c, v, int(y == 0), y >> 7


async def check(dut, a, b, op):
    dut.a.value = a
    dut.b.value = b
    dut.op.value = op
    await Timer(1, "ns")
    exp = model(a, b, op)
    got = (int(dut.y.value), int(dut.carry.value), int(dut.overflow.value),
           int(dut.zero.value), int(dut.negative.value))
    assert got == exp, f"a={a:#04x} b={b:#04x} op={op}: got (y,c,v,z,n)={got} expected {exp}"


@cocotb.test()
async def corners(dut):
    vals = [0x00, 0x01, 0x02, 0x7E, 0x7F, 0x80, 0x81, 0xFE, 0xFF, 0x55, 0xAA, 0x0F, 0xF0]
    for op in range(8):
        for a in vals:
            for b in vals:
                await check(dut, a, b, op)


@cocotb.test()
async def shifts_exhaustive_amounts(dut):
    rng = random.Random(1)
    for op in (5, 6):
        for s in range(8):
            for _ in range(40):
                a = rng.randrange(256)
                b = (rng.randrange(32) << 3) | s
                await check(dut, a, b, op)


@cocotb.test()
async def random_all_ops(dut):
    rng = random.Random(2)
    for _ in range(4000):
        await check(dut, rng.randrange(256), rng.randrange(256), rng.randrange(8))
