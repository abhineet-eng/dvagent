"""
Verification Plan for rr_arbiter:
1. Reset Behavior: Verify that after reset, grant = 0, owner = 0, busy = 0, and internal 'last' = 3.
2. Single Requester: Verify that any single requester gets the grant and keeps it as long as req is high.
3. Round-Robin Ordering: Verify proper round-robin priority order (last + 1, last + 2, last + 3, last + 4 modulo 4) when multiple requests are active simultaneously.
4. Retention (Keep): Verify that an owner keeps the bus as long as its request remains high, even if higher priority requests appear.
5. Hand-Over: Verify seamless hand-over with no idle cycle when the current owner drops its request and another request is pending.
6. Drop to Idle: Verify that when all requests drop, grant goes to 0, busy goes to 0, while owner and last retain their values.
7. Constrained-Random Test: Drive randomized request patterns across multiple cycles and verify against the Python reference model.
"""

import random
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, ReadOnly, Timer, ClockCycles

class RefModel:
    def __init__(self):
        self.last = 3
        self.grant = 0
        self.owner = 0
        self.busy = 0

    def step(self, rst, req):
        if rst:
            self.last = 3
            self.grant = 0
            self.owner = 0
            self.busy = 0
            return

        # 1. Keep: if grant is non-zero and req[owner] == 1
        keep = False
        if self.grant != 0:
            owner_bit = (self.grant >> self.owner) & 1
            if owner_bit == 1 and ((req >> self.owner) & 1) == 1:
                keep = True

        if keep:
            # Nothing changes for grant, owner, last
            pass
        else:
            # 2. Arbitrate: search order (last+1, last+2, last+3, last+4) % 4
            winner = None
            for offset in range(1, 5):
                idx = (self.last + offset) % 4
                if (req >> idx) & 1:
                    winner = idx
                    break

            if winner is not None:
                self.owner = winner
                self.last = winner
                self.grant = 1 << winner
            else:
                # 3. No requester
                self.grant = 0
                # owner and last keep their values

        self.busy = 1 if self.grant != 0 else 0

async def initialize(dut):
    dut.rst.value = 1
    dut.req.value = 0
    await FallingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.rst.value = 0
    await ReadOnly()

@cocotb.test()
async def test_reset(dut):
    """Test reset conditions and initial state."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    
    dut.rst.value = 1
    dut.req.value = 0x5
    await ClockCycles(dut.clk, 2)
    
    await ReadOnly()
    assert int(dut.grant.value) == 0, f"Expected grant=0 after reset, got {int(dut.grant.value)}"
    assert int(dut.owner.value) == 0, f"Expected owner=0 after reset, got {int(dut.owner.value)}"
    assert int(dut.busy.value) == 0, f"Expected busy=0 after reset, got {int(dut.busy.value)}"

@cocotb.test()
async def test_single_requester(dut):
    """Test single requester behavior and bus retention."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    ref = RefModel()
    await initialize(dut)

    # Request from requester 2
    for req_val in [0x4, 0x4, 0x4, 0x0, 0x2, 0x2, 0x0]:
        await FallingEdge(dut.clk)
        dut.req.value = req_val
        ref.step(0, req_val)
        
        await RisingEdge(dut.clk)
        await ReadOnly()
        
        assert int(dut.grant.value) == ref.grant, f"req={req_val:04b}: expected grant={ref.grant:04b}, got {int(dut.grant.value):04b}"
        assert int(dut.owner.value) == ref.owner, f"req={req_val:04b}: expected owner={ref.owner}, got {int(dut.owner.value)}"
        assert int(dut.busy.value) == ref.busy, f"req={req_val:04b}: expected busy={ref.busy}, got {int(dut.busy.value)}"

@cocotb.test()
async def test_round_robin_order(dut):
    """Test round-robin priority order when multiple requesters are active."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    ref = RefModel()
    await initialize(dut)

    # Assert all requests simultaneously: 0xF
    # After reset, last = 3, so priority order should be 0, 1, 2, 3
    # Cycle 1: req=0xF -> grants 0
    # Cycle 2: req=0xF -> keeps 0 (req[0]==1)
    # Let's drop req[0] to test round robin hand-over to 1, then 2, then 3
    req_sequence = [0xF, 0xE, 0xC, 0x8, 0x0, 0xF, 0xF, 0xF, 0xF]
    
    for req_val in req_sequence:
        await FallingEdge(dut.clk)
        dut.req.value = req_val
        ref.step(0, req_val)
        
        await RisingEdge(dut.clk)
        await ReadOnly()
        
        assert int(dut.grant.value) == ref.grant, f"req={req_val:04b}: expected grant={ref.grant:04b}, got {int(dut.grant.value):04b}"
        assert int(dut.owner.value) == ref.owner, f"req={req_val:04b}: expected owner={ref.owner}, got {int(dut.owner.value)}"
        assert int(dut.busy.value) == ref.busy, f"req={req_val:04b}: expected busy={ref.busy}, got {int(dut.busy.value)}"

@cocotb.test()
async def test_retention_and_handover(dut):
    """Test keep condition vs new higher/lower priority requests."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    ref = RefModel()
    await initialize(dut)

    # Sequence to test owner keeping bus even when other requests arrive
    req_sequence = [
        0x2, # req[1] -> grant 1
        0x3, # req[1] and req[0] -> owner is 1, req[1] is high -> keep 1
        0x1, # drop req[1], keep req[0] -> hand over to 0 immediately
        0x1, # keep 0
        0xD, # req[0], req[2], req[3] active, owner is 0. req[0] is high -> keep 0
        0xC, # drop req[0], req[2], req[3] active, last=0 -> next is 1,2,3 -> grants 2 (since last=0, order is 1,2,3,0 -> index 2 is first set)
        0x0  # drop all
    ]

    for req_val in req_sequence:
        await FallingEdge(dut.clk)
        dut.req.value = req_val
        ref.step(0, req_val)
        
        await RisingEdge(dut.clk)
        await ReadOnly()
        
        assert int(dut.grant.value) == ref.grant, f"req={req_val:04b}: expected grant={ref.grant:04b}, got {int(dut.grant.value):04b}"
        assert int(dut.owner.value) == ref.owner, f"req={req_val:04b}: expected owner={ref.owner}, got {int(dut.owner.value)}"
        assert int(dut.busy.value) == ref.busy, f"req={req_val:04b}: expected busy={ref.busy}, got {int(dut.busy.value)}"

@cocotb.test()
async def test_constrained_random(dut):
    """Run constrained-random testing over 1000 cycles and check against reference model."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    ref = RefModel()
    await initialize(dut)

    rng = random.Random(42)

    for _ in range(1000):
        req_val = rng.randint(0, 15)
        rst_val = 1 if rng.random() < 0.02 else 0 # occasional random reset

        await FallingEdge(dut.clk)
        dut.req.value = req_val
        dut.rst.value = rst_val
        ref.step(rst_val, req_val)

        await RisingEdge(dut.clk)
        await ReadOnly()

        assert int(dut.grant.value) == ref.grant, f"Random test fail: rst={rst_val}, req={req_val:04b}, expected grant={ref.grant:04b}, got {int(dut.grant.value):04b}"
        assert int(dut.owner.value) == ref.owner, f"Random test fail: rst={rst_val}, req={req_val:04b}, expected owner={ref.owner}, got {int(dut.owner.value)}"
        assert int(dut.busy.value) == ref.busy, f"Random test fail: rst={rst_val}, req={req_val:04b}, expected busy={ref.busy}, got {int(dut.busy.value)}"
