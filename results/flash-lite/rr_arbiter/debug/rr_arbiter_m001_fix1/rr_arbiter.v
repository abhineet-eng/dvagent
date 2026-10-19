// rr_arbiter - 4-way round-robin bus arbiter; the owner keeps the bus while it requests
module rr_arbiter (
    input  wire       clk,
    input  wire       rst,
    input  wire [3:0] req,
    output reg  [3:0] grant,
    output reg  [1:0] owner,
    output wire       busy
);

    reg  [1:0] last;
    reg  [1:0] pick;
    reg        found;

    // rotate the requests so that bit j is requester (last + 1 + j) mod 4
    wire [7:0] req2 = {req, req};
    wire [2:0] sh   = {1'b0, last} + 3'd1;
    wire [3:0] rot  = req2[sh +: 4];

    // first requester after "last", searching last+1, last+2, last+3, last+4 (mod 4)
    always @(*) begin
        found = 1'b1;
        if (rot[0])
            pick = last + 2'd1;
        else if (rot[1])
            pick = last + 2'd2;
        else if (rot[2])
            pick = last + 2'd3;
        else if (rot[3])
            pick = last;
        else begin
            pick  = 2'd0;
            found = 1'b0;
        end
    end

    wire keep = busy && req[owner];

    always @(posedge clk) begin
        if (rst) begin
            grant <= 4'b0000;
            owner <= 2'd0;
            last  <= 2'd3;
        end else if (!keep) begin
            if (found) begin
                grant <= 4'b0001 << pick;
                owner <= pick;
                last  <= pick;
            end else begin
                grant <= 4'b0000;
            end
        end
    end

    assign busy = (grant != 4'b0000);

endmodule
