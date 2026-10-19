// sync_fifo - 8-entry synchronous FIFO, first-word fall-through, sticky error flags
module sync_fifo (
    input  wire       clk,
    input  wire       rst,
    input  wire       push,
    input  wire [7:0] din,
    input  wire       pop,
    output wire [7:0] dout,
    output wire       full,
    output wire       empty,
    output wire       almost_full,
    output reg  [3:0] count,
    output reg        overflow,
    output reg        underflow
);

    reg  [7:0] mem [0:7];
    reg  [2:0] wr_ptr;
    reg  [2:0] rd_ptr;

    wire do_pop  = pop && !empty;
    wire do_push = push && (!full || do_pop);

    assign full        = (count == 4'd8);
    assign empty       = (count == 4'd0);
    assign almost_full = (count >= 4'd6);
    assign dout        = mem[rd_ptr];

    always @(posedge clk) begin
        if (do_push)
            mem[wr_ptr] <= din;
    end

    always @(posedge clk) begin
        if (rst) begin
            wr_ptr    <= 3'd0;
            rd_ptr    <= 3'd0;
            count     <= 4'd0;
            overflow  <= 1'b0;
            underflow <= 1'b0;
        end else begin
            if (do_push)
                wr_ptr <= wr_ptr + 3'd1;
            if (do_pop)
                rd_ptr <= rd_ptr + 3'd1;
            if (do_push && !do_pop)
                count <= count + 4'd1;
            else if (do_pop && !do_push)
                count <= count - 4'd1;
            if (push && !do_push)
                overflow <= 1'b1;
            if (pop && !do_pop)
                underflow <= 1'b1;
        end
    end

endmodule
