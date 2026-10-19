// spi_master - SPI mode 0 master (CPOL = 0, CPHA = 0), 8-bit transfers, MSB first
module spi_master #(
    parameter CLK_DIV = 2
) (
    input  wire       clk,
    input  wire       rst,
    input  wire       start,
    input  wire [7:0] tx_data,
    output reg  [7:0] rx_data,
    output wire       busy,
    output reg        done,
    output reg        sclk,
    output reg        mosi,
    input  wire       miso,
    output reg        cs_n
);

    localparam integer LAST = CLK_DIV - 1;

    reg        active;
    reg [7:0]  tx_sh;
    reg [7:0]  rx_sh;
    reg [2:0]  nbit;
    reg [7:0]  div;

    wire half_done = (div == LAST);

    assign busy = active;

    always @(posedge clk) begin
        if (rst) begin
            active  <= 1'b0;
            done    <= 1'b0;
            sclk    <= 1'b0;
            mosi    <= 1'b0;
            cs_n    <= 1'b1;
            rx_data <= 8'd0;
            tx_sh   <= 8'd0;
            rx_sh   <= 8'd0;
            nbit    <= 3'd0;
            div     <= 8'd0;
        end else begin
            done <= 1'b0;
            if (!active) begin
                if (start) begin
                    active <= 1'b1;
                    cs_n   <= 1'b0;
                    mosi   <= tx_data[7];
                    tx_sh  <= {tx_data[6:0], 1'b0};
                    nbit   <= 3'd0;
                    div    <= 8'd0;
                end
            end else if (!half_done) begin
                div <= div - 8'd1;
            end else begin
                div <= 8'd0;
                if (!sclk) begin
                    sclk  <= 1'b1;                       // rising edge: sample MISO
                    rx_sh <= {rx_sh[6:0], miso};
                end else begin
                    sclk <= 1'b0;                        // falling edge: shift MOSI
                    if (nbit == 3'd7) begin
                        active  <= 1'b0;
                        cs_n    <= 1'b1;
                        done    <= 1'b1;
                        rx_data <= rx_sh;
                    end else begin
                        nbit  <= nbit + 3'd1;
                        mosi  <= tx_sh[7];
                        tx_sh <= {tx_sh[6:0], 1'b0};
                    end
                end
            end
        end
    end

endmodule
