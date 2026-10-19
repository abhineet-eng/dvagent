// crc8 - byte-wide CRC-8 engine, polynomial x^8 + x^2 + x + 1 (0x07), MSB first
module crc8 (
    input  wire       clk,
    input  wire       rst,
    input  wire       init,
    input  wire       valid,
    input  wire [7:0] data,
    output reg  [7:0] crc,
    output reg  [7:0] nbytes
);

    function [7:0] crc_byte;
        input [7:0] c;
        input [7:0] d;
        integer i;
        reg [7:0] r;
        begin
            r = c ^ d;
            for (i = 0; i < 8; i = i + 1)
                r = r[7] ? ((r << 1) ^ 8'h07) : (r << 1);
            crc_byte = r;
        end
    endfunction

    wire [7:0] next_crc = crc_byte(crc, data);

    always @(posedge clk) begin
        if (rst || init) begin
            crc    <= 8'h00;
            nbytes <= 8'd0;
        end else if (valid) begin
            crc    <= next_crc;
            nbytes <= nbytes + 8'd1;
        end
    end

endmodule
