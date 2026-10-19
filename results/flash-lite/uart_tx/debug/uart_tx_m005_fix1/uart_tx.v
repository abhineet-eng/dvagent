// uart_tx - UART transmitter: 1 start bit, 8 data bits LSB first, optional parity, 1 stop bit
module uart_tx #(
    parameter CLKS_PER_BIT = 4
) (
    input  wire       clk,
    input  wire       rst,
    input  wire       start,
    input  wire [7:0] data,
    input  wire       parity_en,
    input  wire       parity_odd,
    output reg        tx,
    output wire       busy,
    output reg        done
);

    localparam IDLE   = 3'd0;
    localparam START  = 3'd1;
    localparam DATA   = 3'd2;
    localparam PARITY = 3'd3;
    localparam STOP   = 3'd4;

    reg [2:0]  state;
    reg [7:0]  shreg;
    reg [2:0]  bit_idx;
    reg [15:0] tick;
    reg        par_en;
    reg        par_bit;

    localparam integer LAST = CLKS_PER_BIT - 1;
    wire last_tick = (tick == LAST[15:0]);

    assign busy = (state != IDLE);

    always @(posedge clk) begin
        if (rst) begin
            state   <= IDLE;
            tx      <= 1'b1;
            done    <= 1'b0;
            tick    <= 16'd0;
            bit_idx <= 3'd0;
            shreg   <= 8'd0;
            par_en  <= 1'b0;
            par_bit <= 1'b0;
        end else begin
            done <= 1'b0;
            case (state)
                IDLE: begin
                    tx <= 1'b1;
                    if (start) begin
                        shreg   <= data;
                        par_en  <= parity_en;
                        par_bit <= (^data) ^ parity_odd;
                        tx      <= 1'b0;
                        tick    <= 16'd0;
                        state   <= START;
                    end
                end
                START: begin
                    if (last_tick) begin
                        tick    <= 16'd0;
                        tx      <= shreg[0];
                        bit_idx <= 3'd0;
                        state   <= DATA;
                    end else begin
                        tick <= tick + 16'd1;
                    end
                end
                DATA: begin
                    if (last_tick) begin
                        tick <= 16'd0;
                        if (bit_idx != 3'd7) begin
                            if (par_en) begin
                                tx    <= par_bit;
                                state <= PARITY;
                            end else begin
                                tx    <= 1'b1;
                                state <= STOP;
                            end
                        end else begin
                            bit_idx <= bit_idx + 3'd1;
                            tx      <= shreg[bit_idx];
                        end
                    end else begin
                        tick <= tick + 16'd1;
                    end
                end
                PARITY: begin
                    if (last_tick) begin
                        tick  <= 16'd0;
                        tx    <= 1'b1;
                        state <= STOP;
                    end else begin
                        tick <= tick + 16'd1;
                    end
                end
                default: begin   // STOP
                    if (last_tick) begin
                        tick  <= 16'd0;
                        done  <= 1'b1;
                        state <= IDLE;
                    end else begin
                        tick <= tick + 16'd1;
                    end
                end
            endcase
        end
    end

endmodule
