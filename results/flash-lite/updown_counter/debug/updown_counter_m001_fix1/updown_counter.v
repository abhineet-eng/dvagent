// updown_counter - 8-bit loadable up/down counter with a programmable wrap value
module updown_counter (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       en,
    input  wire       up,
    input  wire       load,
    input  wire [7:0] d,
    input  wire [7:0] max_val,
    output reg  [7:0] count,
    output wire       tc,
    output wire       zero
);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            count <= 8'd0;
        end else if (load) begin
            count <= (d > max_val) ? max_val : d;
        end else if (en) begin
            if (up)
                count <= (count >= max_val) ? 8'd0 : count + 8'd1;
            else
                count <= (count == 8'd0) ? max_val : count - 8'd1;
        end
    end

    assign tc   = en && !load && (up ? (count >= max_val) : (count == 8'd0));
    assign zero = (count == 8'd0);

endmodule
