// alu8 - 8-bit combinational ALU with carry, overflow, zero and negative flags
module alu8 (
    input  wire [7:0] a,
    input  wire [7:0] b,
    input  wire [2:0] op,
    output reg  [7:0] y,
    output reg        carry,
    output reg        overflow,
    output wire       zero,
    output wire       negative
);

    wire [8:0] sum  = {1'b0, a} + {1'b0, b};
    wire [8:0] diff = {1'b0, a} - {1'b0, b};
    wire [2:0] sh   = b[2:0];

    always @(*) begin
        y        = 8'd0;
        carry    = 1'b0;
        overflow = 1'b0;
        case (op)
            3'd0: begin                                   // ADD
                y        = sum[7:0];
                carry    = sum[8];
                overflow = (a[7] == b[7]) && (sum[7] != a[7]);
            end
            3'd1: begin                                   // SUB
                y        = diff[7:0];
                carry    = diff[8];                       // borrow
                overflow = (a[7] != b[7]) && (diff[7] != a[7]);
            end
            3'd2: y = a & b;                              // AND
            3'd3: y = a | b;                              // OR
            3'd4: y = a ^ b;                              // XOR
            3'd5: {carry, y} = {1'b0, a} << sh;           // SHL
            3'd6: {y, carry} = {a, 1'b0} >> sh;           // SHR (logical)
            default: y = {7'd0, $signed(a) < $signed(b)}; // SLT (signed)
        endcase
    end

    assign zero     = (y == 8'd0);
    assign negative = y[7];

endmodule
