// seq_detector - detects the serial pattern 1011 (overlapping) and counts matches
module seq_detector (
    input  wire       clk,
    input  wire       rst,
    input  wire       din,
    input  wire       din_valid,
    output reg        match,
    output reg  [7:0] count
);

    localparam S0 = 2'd0;   // nothing matched
    localparam S1 = 2'd1;   // "1"
    localparam S2 = 2'd2;   // "10"
    localparam S3 = 2'd3;   // "101"

    reg [1:0] state;
    reg [1:0] next;
    wire      hit = din_valid && (state == S3) && din;

    always @(*) begin
        case (state)
            S0:      next = din ? S1 : S0;
            S1:      next = din ? S1 : S2;
            S2:      next = din ? S3 : S0;
            default: next = din ? S1 : S2;
        endcase
    end

    always @(posedge clk) begin
        if (rst) begin
            state <= S0;
            match <= 1'b0;
            count <= 8'd0;
        end else begin
            match <= hit;
            if (din_valid)
                state <= next;
            if (hit && count != 8'hFF)
                count <= count + 8'd1;
        end
    end

endmodule
