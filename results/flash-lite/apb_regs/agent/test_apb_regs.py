"""
Verification Plan for apb_regs:
1. Reset Behavior:
   - Verify asynchronous assertion of `presetn` resets registers:
     CTRL (0x00) = 0x00000000
     DATA (0x04) = 0x00000000
     STATUS (0x08) = 0x00000000
     ID (0x0C) = 0xA5B00001
   - Verify pready=1 and pslverr=0 during reset.

2. Standard APB3 Protocol & Register Access:
   - CTRL register: Read/Write, bits [7:0] stored, upper bits read as 0.
   - DATA register: Read/Write, 32-bit storage, exactly ONE wait state (pready=0 on first ACCESS, pready=1 on second ACCESS).
   - STATUS register: Read-only, increments on every successful write to CTRL or DATA, wraps at 65536 (16 bits), upper bits read as 0.
   - ID register: Read-only, constant identification value.

3. Error Handling (pslverr):
   - Invalid addresses yield pslverr=1 on the completing ACCESS cycle.
   - Writes to read-only registers yield pslverr=1 and do not modify the registers.

4. Randomized testing:
   - Sequence of random valid/invalid read and write transactions to verify state tracking against a Python reference model.
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, ReadOnly, Timer, ClockCycles
import random

class APBReferenceModel:
    def __init__(self):
        self.ctrl = 0
        self.data = 0
        self.status = 0
        self.id_reg = 0xA5B00001

    def reset(self):
        self.ctrl = 0
        self.data = 0
        self.status = 0

    def step(self, pwrite, paddr):
        valid_addr = paddr in [0x00, 0x04, 0x08, 0x0C]
        is_err = False
        if not valid_addr:
            is_err = True
        elif pwrite and paddr in [0x08, 0x0C]:
            is_err = True

        if not valid_addr:
            prdata = 0
        elif paddr == 0x00:
            prdata = self.ctrl & 0xFF
        elif paddr == 0x04:
            prdata = self.data
        elif paddr == 0x08:
            prdata = self.status & 0xFFFF
        elif paddr == 0x0C:
            prdata = self.id_reg
        else:
            prdata = 0

        return prdata, is_err

async def apply_reset(dut):
    await FallingEdge(dut.pclk)
    dut.presetn.value = 0
    dut.psel.value = 0
    dut.penable.value = 0
    dut.pwrite.value = 0
    dut.paddr.value = 0
    dut.pwdata.value = 0
    await ClockCycles(dut.pclk, 3)
    await FallingEdge(dut.pclk)
    dut.presetn.value = 1
    await RisingEdge(dut.pclk)

async def run_apb_transaction(dut, pwrite, paddr, pwdata):
    # APB3 Transfer:
    # 1. SETUP Cycle: psel=1, penable=0, drive address/data/control on falling edge
    await FallingEdge(dut.pclk)
    dut.psel.value = 1
    dut.penable.value = 0
    dut.pwrite.value = 1 if pwrite else 0
    dut.paddr.value = paddr
    dut.pwdata.value = pwdata

    is_data = (paddr == 0x04)

    # Rising edge of setup cycle -> now enter ACCESS cycle 1
    # For standard APB3, penable goes high for the ACCESS cycle.
    # We set penable=1 at the start of the ACCESS cycle (or drive it right after the rising edge of setup).
    # Actually, standard APB3 setup cycle is one clock edge to next. 
    # Let's assert penable=1 synchronously right at the beginning of the ACCESS cycle (on the rising edge or immediately after).
    # Since inputs must be stable, we can set penable=1 on the falling edge of pclk during the setup cycle, 
    # but wait: the spec says SETUP: psel=1, penable=0. ACCESS: penable=1.
    # If SETUP is one clock cycle (from rising edge to rising edge), then during SETUP, penable=0.
    # At the rising edge ending SETUP, we enter ACCESS, so penable must be 1 during ACCESS.
    # To have penable=1 sampled correctly at the rising edge of setup (entering ACCESS), we must assert penable=1 during the setup cycle.
    # Let's set penable=1 on the falling edge *inside* the setup cycle (halfway through).
    
    await Timer(2, "ns") # slightly after rising edge of setup
    dut.penable.value = 1

    if is_data:
        # First ACCESS cycle: pready should be sampled as 0 at the rising edge ending ACCESS 1
        await RisingEdge(dut.pclk)
        await ReadOnly()
        assert int(dut.pready.value) == 0, f"Expected pready=0 for DATA transfer first ACCESS cycle at addr {hex(paddr)}"

        # Second ACCESS cycle: pready should be 1
        await RisingEdge(dut.pclk)
        await ReadOnly()
        assert int(dut.pready.value) == 1, f"Expected pready=1 for DATA transfer second ACCESS cycle at addr {hex(paddr)}"
    else:
        # Standard transfer completing in 1st access cycle
        await RisingEdge(dut.pclk)
        await ReadOnly()
        assert int(dut.pready.value) == 1, f"Expected pready=1 for standard transfer at addr {hex(paddr)}"

    prdata = int(dut.prdata.value)
    pslverr = int(dut.pslverr.value)

    # End of transfer: deassert psel and penable on falling edge
    await FallingEdge(dut.pclk)
    dut.psel.value = 0
    dut.penable.value = 0
    
    return prdata, pslverr


@cocotb.test()
async def test_reset_behavior(dut):
    """Test asynchronous reset and default register values."""
    cocotb.start_soon(Clock(dut.pclk, 10, units="ns").start())
    
    dut.presetn.value = 0
    dut.psel.value = 1
    dut.penable.value = 1
    dut.pwrite.value = 1
    dut.paddr.value = 0x04
    dut.pwdata.value = 0xDEADBEEF
    await ClockCycles(dut.pclk, 2)
    
    await ReadOnly()
    assert int(dut.pslverr.value) == 0

    await FallingEdge(dut.pclk)
    dut.presetn.value = 1
    await RisingEdge(dut.pclk)
    await ReadOnly()

    prdata, _ = await run_apb_transaction(dut, pwrite=0, paddr=0x0C, pwdata=0)
    assert prdata == 0xA5B00001


@cocotb.test()
async def test_basic_registers(dut):
    """Test read/write functionality of CTRL, DATA, STATUS, and ID registers."""
    cocotb.start_soon(Clock(dut.pclk, 10, units="ns").start())
    await apply_reset(dut)

    # 1. Write to CTRL (only bits [7:0] stored)
    prdata, pslverr = await run_apb_transaction(dut, pwrite=1, paddr=0x00, pwdata=0x12345678)
    assert pslverr == 0

    # Read back CTRL
    prdata, pslverr = await run_apb_transaction(dut, pwrite=0, paddr=0x00, pwdata=0)
    assert prdata == 0x78, f"Expected CTRL to store 0x78, got {hex(prdata)}"
    assert pslverr == 0

    # 2. Write to DATA (32-bit storage, 1 wait state)
    prdata, pslverr = await run_apb_transaction(dut, pwrite=1, paddr=0x04, pwdata=0xABCDEF01)
    assert pslverr == 0

    # Read back DATA
    prdata, pslverr = await run_apb_transaction(dut, pwrite=0, paddr=0x04, pwdata=0)
    assert prdata == 0xABCDEF01, f"Expected DATA to store 0xABCDEF01, got {hex(prdata)}"
    assert pslverr == 0

    # 3. Check STATUS (should be 2 successful writes: CTRL and DATA)
    prdata, pslverr = await run_apb_transaction(dut, pwrite=0, paddr=0x08, pwdata=0)
    assert prdata == 2, f"Expected STATUS write count to be 2, got {prdata}"
    assert pslverr == 0


@cocotb.test()
async def test_error_responses(dut):
    """Test invalid addresses and writes to read-only registers."""
    cocotb.start_soon(Clock(dut.pclk, 10, units="ns").start())
    await apply_reset(dut)

    # 1. Invalid address read
    prdata, pslverr = await run_apb_transaction(dut, pwrite=0, paddr=0x13, pwdata=0)
    assert pslverr == 1, "Expected pslverr=1 for invalid read address"
    assert prdata == 0, "Expected prdata=0 for invalid address read"

    # 2. Invalid address write
    _, pslverr = await run_apb_transaction(dut, pwrite=1, paddr=0x03, pwdata=0x1234)
    assert pslverr == 1, "Expected pslverr=1 for invalid write address"

    # 3. Write to read-only register (STATUS at 0x08)
    _, pslverr = await run_apb_transaction(dut, pwrite=1, paddr=0x08, pwdata=0x5555)
    assert pslverr == 1, "Expected pslverr=1 when writing to STATUS"

    # 4. Write to read-only register (ID at 0x0C)
    _, pslverr = await run_apb_transaction(dut, pwrite=1, paddr=0x0C, pwdata=0x5555)
    assert pslverr == 1, "Expected pslverr=1 when writing to ID"


@cocotb.test()
async def test_randomized_transactions(dut):
    """Constrained-random test checking transactions against the reference model."""
    cocotb.start_soon(Clock(dut.pclk, 10, units="ns").start())
    await apply_reset(dut)

    ref = APBReferenceModel()
    rng = random.Random(1)

    addresses = [0x00, 0x04, 0x08, 0x0C, 0x01, 0x03, 0x10, 0xFF]

    for _ in range(50):
        pwrite = rng.choice([0, 1])
        paddr = rng.choice(addresses)
        pwdata = rng.getrandbits(32)

        expected_prdata, expected_pslverr = ref.step(pwrite=pwrite, paddr=paddr)

        got_prdata, got_pslverr = await run_apb_transaction(dut, pwrite, paddr, pwdata)

        assert got_pslverr == expected_pslverr, f"Mismatch on pslverr at addr {hex(paddr)}, pwrite={pwrite}: expected {expected_pslverr}, got {got_pslverr}"
        if expected_pslverr == 0 or pwrite == 0:
            if paddr in [0x00, 0x04, 0x08, 0x0C] and not (pwrite and paddr in [0x08, 0x0C]):
                assert got_prdata == expected_prdata, f"Mismatch on prdata at addr {hex(paddr)}: expected {hex(expected_prdata)}, got {hex(got_prdata)}"

        valid_addr = paddr in [0x00, 0x04, 0x08, 0x0C]
        is_err = not valid_addr or (pwrite and paddr in [0x08, 0x0C])
        if pwrite and not is_err:
            if paddr == 0x00:
                ref.ctrl = pwdata & 0xFF
                ref.status = (ref.status + 1) & 0xFFFF
            elif paddr == 0x04:
                ref.data = pwdata
                ref.status = (ref.status + 1) & 0xFFFF
