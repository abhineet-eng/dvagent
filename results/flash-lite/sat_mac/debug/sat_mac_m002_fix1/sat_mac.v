// sat_mac - signed 8x8 multiply-accumulate with a 16-bit saturating accumulator
module sat_mac (
    input  wire              clk,
    input  wire              rst,
    input  wire              valid,
    input  wire              clear,
    input  wire signed [7:0] a,
    input  wire signed [7:0] b,
    output reg  signed [15:0] acc,
    output reg               sat
);

    wire signed [15:0] prod = a * b;
    wire signed [16:0] base = clear ? 17'sd0 : {acc[15], acc};
    wire signed [16:0] sum  = base + {prod[15], prod};
    wire               hi   = (sum > 17'sd32767);
    wire               lo   = (sum < -17'sd32768);

    always @(posedge clk) begin
        if (rst) begin
            acc <= 16'sd0;
            sat <= 1'b0;
        end else if (valid) begin
            if (hi)
                acc <= 16'sh7FFF;
            else if (lo)
                acc <= 16'sh8000;
            else
                acc <= sum[15:0];
            sat <= (clear ? 1'b0 : sat) | hi | lo;
        end else if (clear) begin
            acc <= 16'sd0;
            sat <= 1'b0;
        end
    end

endmodule
