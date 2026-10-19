"""
Verification Plan for alu8:
1. Combinational verification model:
   - Python reference model that precisely mirrors the specification for all 8 operations (0 to 7).
2. Exhaustive corner-case checks:
   - ADD: zero inputs, max inputs, carry generation, overflow cases (positive+positive->negative, negative+negative->positive).
   - SUB: zero inputs, equal inputs, borrow generation (a < b), overflow cases (positive-negative->negative, negative-positive->positive).
   - Bitwise operations (AND, OR, XOR): pattern checks, mask operations, all zeros, all ones.
   - Shifts (SHL, SHR): shift amounts s from 0 to 7, verify shifted-out bits (carry) and results.
   - SLT (Signed Less Than): negative vs positive, positive vs negative, equal signed numbers, boundary values.
3. Zero and Negative flags:
   - Verify `zero` is active only when `y == 0`.
   - Verify `negative` matches `y[7]`.
4. Constrained-random verification:
   - Apply thousands of random test vectors across all operations using a fixed seed (`random.Random(1)`).
"""

import cocotb
from cocotb.triggers import Timer
import random

class ALU8RefModel:
    def step(self, a, b, op):
        # Ensure values are within 8-bit unsigned
        a_u = a & 0xFF
        b_u = b & 0xFF
        
        # Signed 8-bit interpretations (two's complement)
        a_s = a_u if a_u < 128 else a_u - 256
        b_s = b_u if b_u < 128 else b_u - 256
        
        s = b_u & 0x7
        
        carry = 0
        overflow = 0
        y = 0
        
        if op == 0:  # ADD
            full_sum = a_u + b_u
            y = full_sum & 0xFF
            carry = 1 if full_sum > 255 else 0
            # Overflow: same sign for a and b, different sign for y
            y_s = y if y < 128 else y - 256
            if (a_s >= 0 and b_s >= 0 and y_s < 0) or (a_s < 0 and b_s < 0 and y_s >= 0):
                overflow = 1
                
        elif op == 1:  # SUB
            full_sub = a_u - b_u
            y = full_sub & 0xFF
            carry = 1 if a_u < b_u else 0
            # Overflow: different signs for a and b, sign of y differs from a
            y_s = y if y < 128 else y - 256
            if (a_s >= 0 and b_s < 0 and y_s < 0) or (a_s < 0 and b_s >= 0 and y_s >= 0):
                overflow = 1
                
        elif op == 2:  # AND
            y = (a_u & b_u) & 0xFF
            carry = 0
            overflow = 0
            
        elif op == 3:  # OR
            y = (a_u | b_u) & 0xFF
            carry = 0
            overflow = 0
            
        elif op == 4:  # XOR
            y = (a_u ^ b_u) & 0xFF
            carry = 0
            overflow = 0
            
        elif op == 5:  # SHL
            if s == 0:
                y = a_u
                carry = 0
            else:
                y = (a_u << s) & 0xFF
                # last bit shifted out: bit a[8 - s]
                carry = (a_u >> (8 - s)) & 1
            overflow = 0
            
        elif op == 6:  # SHR
            if s == 0:
                y = a_u
                carry = 0
            else:
                y = (a_u >> s) & 0xFF
                # last bit shifted out: bit a[s - 1]
                carry = (a_u >> (s - 1)) & 1
            overflow = 0
            
        elif op == 7:  # SLT
            y = 1 if a_s < b_s else 0
            carry = 0
            overflow = 0
            
        zero = 1 if y == 0 else 0
        negative = 1 if (y & 0x80) else 0
        
        return y, carry, overflow, zero, negative

async def drive_and_check(dut, a, b, op, ref_model):
    dut.a.value = a
    dut.b.value = b
    dut.op.value = op
    
    # Combinational settling delay
    await Timer(1, units="ns")
    
    exp_y, exp_carry, exp_overflow, exp_zero, exp_negative = ref_model.step(a, b, op)
    
    got_y = int(dut.y.value)
    got_carry = int(dut.carry.value)
    got_overflow = int(dut.overflow.value)
    got_zero = int(dut.zero.value)
    got_negative = int(dut.negative.value)
    
    assert got_y == exp_y, f"Mismatch on OP {op} (a={a}, b={b}): y got {got_y}, expected {exp_y}"
    assert got_carry == exp_carry, f"Mismatch on OP {op} (a={a}, b={b}): carry got {got_carry}, expected {exp_carry}"
    assert got_overflow == exp_overflow, f"Mismatch on OP {op} (a={a}, b={b}): overflow got {got_overflow}, expected {exp_overflow}"
    assert got_zero == exp_zero, f"Mismatch on OP {op} (a={a}, b={b}): zero got {got_zero}, expected {exp_zero}"
    assert got_negative == exp_negative, f"Mismatch on OP {op} (a={a}, b={b}): negative got {got_negative}, expected {exp_negative}"

@cocotb.test()
async def test_alu_directed_corner_cases(dut):
    """Test specific corner cases for all operations."""
    ref = ALU8RefModel()
    
    corner_values = [0x00, 0x01, 0x7F, 0x80, 0xFF, 0x55, 0xAA]
    
    for op in range(8):
        for a in corner_values:
            for b in corner_values:
                await drive_and_check(dut, a, b, op, ref)

@cocotb.test()
async def test_alu_shift_edge_cases(dut):
    """Specifically test shift operations (SHL, SHR) with various shift amounts (s from 0 to 7)."""
    ref = ALU8RefModel()
    
    test_patterns = [0x01, 0x80, 0xAA, 0x55, 0xFF, 0x0F, 0xF0]
    for op in [5, 6]:
        for a in test_patterns:
            for b_val in range(8):
                await drive_and_check(dut, a, b_val, op, ref)

@cocotb.test()
async def test_alu_signed_comparison(dut):
    """Test SLT (Signed Less Than) thoroughly with positive and negative numbers."""
    ref = ALU8RefModel()
    
    # Test cases covering negative/positive boundaries
    signed_vals = [-128, -127, -1, 0, 1, 126, 127]
    for val_a in signed_vals:
        for val_b in signed_vals:
            # Convert to unsigned 8-bit for inputs
            a = val_a & 0xFF
            b = val_b & 0xFF
            await drive_and_check(dut, a, b, 7, ref)

@cocotb.test()
async def test_alu_random(dut):
    """Run constrained-random tests across all operations."""
    ref = ALU8RefModel()
    rng = random.Random(1)
    
    for _ in range(3000):
        a = rng.randint(0, 255)
        b = rng.randint(0, 255)
        op = rng.randint(0, 7)
        await drive_and_check(dut, a, b, op, ref)
