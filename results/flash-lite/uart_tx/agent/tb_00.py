"""
Verification Plan for uart_tx:
1. Reset behavior: Verify tx=1, busy=0, done=0 immediately after reset.
2. Idle behavior: Verify tx remains 1 and busy=0 when start=0.
3. Single frame transmission (No Parity):
   - Check start bit (0), 8 data bits LSB-first, stop bit (1).
   - Check bit duration (CLKS_PER_BIT cycles per bit).
   - Check busy high during transmission, low when idle.
   - Check done pulses for exactly 1 cycle upon completion.
4. Single frame transmission (Even Parity):
   - Check parity bit correctness when parity_en=1 and parity_odd=0.
5. Single frame transmission (Odd Parity):
   - Check parity bit correctness when parity_en=1 and parity_odd=1.
6. Back-to-back transmissions:
   - Issue a new start pulse during the cycle where done=1.
   - Verify seamless transition with no idle gaps.
7. Constrained-random testing:
   - Stream multiple random bytes with random parity settings and random gaps between frames.
"""

import random
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, ReadOnly, ClockCycles

CLKS_PER_BIT = 4

class UartTxRefModel:
    def __init__(self, clks_per_bit=4):
        self.clks_per_bit = clks_per_bit
        self.tx = 1
        self.busy = 0
        self.done = 0
        
        self.state = "IDLE"
        self.bit_counter = 0
        self.clk_counter = 0
        self.shift_reg = []
        self.latched_data = 0
        self.latched_parity_en = 0
        self.latched_parity_odd = 0

    def step(self, start, data, parity_en, parity_odd):
        # Outputs are registered / updated on the rising edge
        # Determine next state and outputs based on current state
        
        old_done = self.done
        self.done = 0  # done is a 1-cycle pulse

        if self.state == "IDLE":
            self.tx = 1
            if start:
                self.busy = 1
                self.latched_data = data
                self.latched_parity_en = parity_en
                self.latched_parity_odd = parity_odd
                
                # Build frame bits: Start bit (0), 8 data bits LSB-first, optional parity, stop bit (1)
                bits = [0]
                for i in range(8):
                    bits.append((data >> i) & 1)
                
                if parity_en:
                    # Even parity: XOR of data bits. Odd parity: inverse of even.
                    data_xor = 0
                    for i in range(8):
                        data_xor ^= ((data >> i) & 1)
                    p_bit = data_xor if parity_odd == 0 else (1 - data_xor)
                    bits.append(p_bit)
                
                bits.append(1)  # Stop bit
                
                self.shift_reg = bits
                self.bit_counter = 0
                self.clk_counter = 0
                self.state = "SENDING"
                self.tx = self.shift_reg[0]
            else:
                self.busy = 0

        elif self.state == "SENDING":
            self.busy = 1
            self.clk_counter += 1
            if self.clk_counter >= self.clks_per_bit:
                self.clk_counter = 0
                self.bit_counter += 1
                if self.bit_counter < len(self.shift_reg):
                    self.tx = self.shift_reg[self.bit_counter]
                else:
                    # Frame finished at the end of the stop bit
                    self.busy = 0
                    self.done = 1
                    self.tx = 1
                    
                    # Check if back-to-back start is requested right now
                    if start:
                        self.busy = 1
                        self.latched_data = data
                        self.latched_parity_en = parity_en
                        self.latched_parity_odd = parity_odd
                        
                        bits = [0]
                        for i in range(8):
                            bits.append((data >> i) & 1)
                        if parity_en:
                            data_xor = 0
                            for i in range(8):
                                data_xor ^= ((data >> i) & 1)
                            p_bit = data_xor if parity_odd == 0 else (1 - data_xor)
                            bits.append(p_bit)
                        bits.append(1)
                        
                        self.shift_reg = bits
                        self.bit_counter = 0
                        self.clk_counter = 0
                        self.state = "SENDING"
                        self.tx = self.shift_reg[0]
                    else:
                        self.state = "IDLE"

        return self.tx, self.busy, self.done


async def reset_dut(dut):
    dut.rst.value = 1
    dut.start.value = 0
    dut.data.value = 0
    dut.parity_en.value = 0
    dut.parity_odd.value = 0
    await ClockCycles(dut.clk, 3)
    await FallingEdge(dut.clk)
    dut.rst.value = 0
    await RisingEdge(dut.clk)
    await ReadOnly()


@cocotb.test()
async def test_reset_and_idle(dut):
    """Test reset conditions and idle state."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    
    dut.rst.value = 1
    dut.start.value = 0
    dut.data.value = 0x55
    dut.parity_en.value = 0
    dut.parity_odd.value = 0
    
    await ClockCycles(dut.clk, 2)
    await ReadOnly()
    
    assert int(dut.tx.value) == 1, f"Reset tx expected 1, got {int(dut.tx.value)}"
    assert int(dut.busy.value) == 0, f"Reset busy expected 0, got {int(dut.busy.value)}"
    assert int(dut.done.value) == 0, f"Reset done expected 0, got {int(dut.done.value)}"
    
    # Release reset
    await FallingEdge(dut.clk)
    dut.rst.value = 0
    await RisingEdge(dut.clk)
    await ReadOnly()
    
    # Keep idle for a few cycles
    ref = UartTxRefModel(CLKS_PER_BIT)
    for _ in range(5):
        await FallingEdge(dut.clk)
        dut.start.value = 0
        dut.data.value = 0xAA
        dut.parity_en.value = 0
        dut.parity_odd.value = 0
        await RisingEdge(dut.clk)
        await ReadOnly()
        
        exp_tx, exp_busy, exp_done = ref.step(0, 0xAA, 0, 0)
        assert int(dut.tx.value) == exp_tx, f"Idle tx mismatch: got {int(dut.tx.value)}, exp {exp_tx}"
        assert int(dut.busy.value) == exp_busy, f"Idle busy mismatch: got {int(dut.busy.value)}, exp {exp_busy}"
        assert int(dut.done.value) == exp_done, f"Idle done mismatch: got {int(dut.done.value)}, exp {exp_done}"


@cocotb.test()
async def test_single_frame_no_parity(dut):
    """Test single frame transmission without parity."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset_dut(dut)
    
    ref = UartTxRefModel(CLKS_PER_BIT)
    test_data = 0xA5  # 10100101
    
    # Send start
    await FallingEdge(dut.clk)
    dut.start.value = 1
    dut.data.value = test_data
    dut.parity_en.value = 0
    dut.parity_odd.value = 0
    
    # Total cycles = 10 bits * 4 clks/bit = 40 cycles
    total_cycles = 10 * CLKS_PER_BIT
    
    for cycle in range(total_cycles):
        await RisingEdge(dut.clk)
        await ReadOnly()
        
        # Check against reference model
        exp_tx, exp_busy, exp_done = ref.step(int(dut.start.value), int(dut.data.value), int(dut.parity_en.value), int(dut.parity_odd.value))
        
        assert int(dut.tx.value) == exp_tx, f"Cycle {cycle}: tx mismatch. Got {int(dut.tx.value)}, exp {exp_tx}"
        assert int(dut.busy.value) == exp_busy, f"Cycle {cycle}: busy mismatch. Got {int(dut.busy.value)}, exp {exp_busy}"
        assert int(dut.done.value) == exp_done, f"Cycle {cycle}: done mismatch. Got {int(dut.done.value)}, exp {exp_done}"
        
        await FallingEdge(dut.clk)
        # Drop start after 1 cycle
        if cycle == 0:
            dut.start.value = 0


@cocotb.test()
async def test_single_frame_even_parity(dut):
    """Test single frame transmission with even parity."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset_dut(dut)
    
    ref = UartTxRefModel(CLKS_PER_BIT)
    test_data = 0x3C  # 00111100 (four 1s -> even parity bit should be 0)
    
    await FallingEdge(dut.clk)
    dut.start.value = 1
    dut.data.value = test_data
    dut.parity_en.value = 1
    dut.parity_odd.value = 0
    
    # Total cycles = 11 bits * 4 clks/bit = 44 cycles
    total_cycles = 11 * CLKS_PER_BIT
    
    for cycle in range(total_cycles):
        await RisingEdge(dut.clk)
        await ReadOnly()
        
        exp_tx, exp_busy, exp_done = ref.step(int(dut.start.value), int(dut.data.value), int(dut.parity_en.value), int(dut.parity_odd.value))
        
        assert int(dut.tx.value) == exp_tx, f"Cycle {cycle}: tx mismatch. Got {int(dut.tx.value)}, exp {exp_tx}"
        assert int(dut.busy.value) == exp_busy, f"Cycle {cycle}: busy mismatch. Got {int(dut.busy.value)}, exp {exp_busy}"
        assert int(dut.done.value) == exp_done, f"Cycle {cycle}: done mismatch. Got {int(dut.done.value)}, exp {exp_done}"
        
        await FallingEdge(dut.clk)
        if cycle == 0:
            dut.start.value = 0


@cocotb.test()
async def test_single_frame_odd_parity(dut):
    """Test single frame transmission with odd parity."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset_dut(dut)
    
    ref = UartTxRefModel(CLKS_PER_BIT)
    test_data = 0x3C  # 00111100 (four 1s -> even parity is 0, odd parity should be 1)
    
    await FallingEdge(dut.clk)
    dut.start.value = 1
    dut.data.value = test_data
    dut.parity_en.value = 1
    dut.parity_odd.value = 1
    
    total_cycles = 11 * CLKS_PER_BIT
    
    for cycle in range(total_cycles):
        await RisingEdge(dut.clk)
        await ReadOnly()
        
        exp_tx, exp_busy, exp_done = ref.step(int(dut.start.value), int(dut.data.value), int(dut.parity_en.value), int(dut.parity_odd.value))
        
        assert int(dut.tx.value) == exp_tx, f"Cycle {cycle}: tx mismatch. Got {int(dut.tx.value)}, exp {exp_tx}"
        assert int(dut.busy.value) == exp_busy, f"Cycle {cycle}: busy mismatch. Got {int(dut.busy.value)}, exp {exp_busy}"
        assert int(dut.done.value) == exp_done, f"Cycle {cycle}: done mismatch. Got {int(dut.done.value)}, exp {exp_done}"
        
        await FallingEdge(dut.clk)
        if cycle == 0:
            dut.start.value = 0


@cocotb.test()
async def test_back_to_back(dut):
    """Test back-to-back transmissions where start is asserted during the done cycle."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset_dut(dut)
    
    ref = UartTxRefModel(CLKS_PER_BIT)
    
    # We will orchestrate 2 consecutive frames
    data1 = 0xAA
    data2 = 0x55
    
    # Frame 1 start
    await FallingEdge(dut.clk)
    dut.start.value = 1
    dut.data.value = data1
    dut.parity_en.value = 0
    dut.parity_odd.value = 0
    
    total_cycles = (10 * CLKS_PER_BIT) + (10 * CLKS_PER_BIT)
    
    # Track when to assert second start
    frame1_done_cycle = 10 * CLKS_PER_BIT - 1
    
    for cycle in range(total_cycles):
        await RisingEdge(dut.clk)
        await ReadOnly()
        
        exp_tx, exp_busy, exp_done = ref.step(int(dut.start.value), int(dut.data.value), int(dut.parity_en.value), int(dut.parity_odd.value))
        
        assert int(dut.tx.value) == exp_tx, f"Cycle {cycle}: tx mismatch. Got {int(dut.tx.value)}, exp {exp_tx}"
        assert int(dut.busy.value) == exp_busy, f"Cycle {cycle}: busy mismatch. Got {int(dut.busy.value)}, exp {exp_busy}"
        assert int(dut.done.value) == exp_done, f"Cycle {cycle}: done mismatch. Got {int(dut.done.value)}, exp {exp_done}"
        
        await FallingEdge(dut.clk)
        if cycle == 0:
            dut.start.value = 0
        elif cycle == frame1_done_cycle - 1:
            # Assert start right before the done cycle so it's sampled when done=1
            dut.start.value = 1
            dut.data.value = data2
            dut.parity_en.value = 1
            dut.parity_odd.value = 1
        elif cycle == frame1_done_cycle:
            # Drop start after 1 cycle
            dut.start.value = 0


@cocotb.test()
async def test_constrained_random(dut):
    """Constrained-random test of multiple frames with random data, parity options, and gaps."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset_dut(dut)
    
    rng = random.Random(42)
    ref = UartTxRefModel(CLKS_PER_BIT)
    
    # We will simulate a sequence of events
    current_data = rng.randint(0, 255)
    current_parity_en = rng.randint(0, 1)
    current_parity_odd = rng.randint(0, 1)
    
    # Drive initial state
    await FallingEdge(dut.clk)
    dut.start.value = 1
    dut.data.value = current_data
    dut.parity_en.value = current_parity_en
    dut.parity_odd.value = current_parity_odd
    
    # We simulate for 500 cycles total
    start_asserted_this_cycle = True
    
    for cycle in range(500):
        await RisingEdge(dut.clk)
        await ReadOnly()
        
        exp_tx, exp_busy, exp_done = ref.step(int(dut.start.value), int(dut.data.value), int(dut.parity_en.value), int(dut.parity_odd.value))
        
        assert int(dut.tx.value) == exp_tx, f"Cycle {cycle}: tx mismatch. Got {int(dut.tx.value)}, exp {exp_tx}"
        assert int(dut.busy.value) == exp_busy, f"Cycle {cycle}: busy mismatch. Got {int(dut.busy.value)}, exp {exp_busy}"
        assert int(dut.done.value) == exp_done, f"Cycle {cycle}: done mismatch. Got {int(dut.done.value)}, exp {exp_done}"
        
        await FallingEdge(dut.clk)
        
        # If start was high, drop it after 1 cycle
        if start_asserted_this_cycle:
            dut.start.value = 0
            start_asserted_this_cycle = False
        
        # If we are idle, randomly decide whether to start a new transmission
        if exp_busy == 0:
            if rng.random() < 0.4:
                current_data = rng.randint(0, 255)
                current_parity_en = rng.randint(0, 1)
                current_parity_odd = rng.randint(0, 1)
                dut.start.value = 1
                dut.data.value = current_data
                dut.parity_en.value = current_parity_en
                dut.parity_odd.value = current_parity_odd
                start_asserted_this_cycle = True
