// apb_regs - APB3 slave with four registers, one wait state on DATA, error responses
module apb_regs (
    input  wire        pclk,
    input  wire        presetn,
    input  wire        psel,
    input  wire        penable,
    input  wire        pwrite,
    input  wire [7:0]  paddr,
    input  wire [31:0] pwdata,
    output reg  [31:0] prdata,
    output wire        pready,
    output wire        pslverr
);

    localparam [7:0]  A_CTRL   = 8'h00;
    localparam [7:0]  A_DATA   = 8'h04;
    localparam [7:0]  A_STATUS = 8'h08;
    localparam [7:0]  A_ID     = 8'h0C;
    localparam [31:0] ID_VALUE = 32'hA5B0_0001;

    reg [7:0]  ctrl;
    reg [31:0] data;
    reg [15:0] wr_count;
    reg        waited;

    wire access   = psel && penable;
    wire is_data  = (paddr == A_DATA);
    wire known    = (paddr == A_CTRL) || is_data || (paddr == A_STATUS) || (paddr == A_ID);
    wire ro       = (paddr == A_STATUS) || (paddr == A_ID);
    wire err      = !known || (pwrite && ro);

    assign pready  = !(access && is_data && !waited);
    assign pslverr = access && pready && err;

    wire done_ok_write = access && pready && pwrite && !err;

    always @(*) begin
        case (paddr)
            A_CTRL:   prdata = {24'd0, ctrl};
            A_DATA:   prdata = data;
            A_STATUS: prdata = {16'd0, wr_count};
            A_ID:     prdata = ID_VALUE;
            default:  prdata = 32'd0;
        endcase
    end

    always @(posedge pclk or negedge presetn) begin
        if (!presetn) begin
            ctrl     <= 8'd0;
            data     <= 32'd0;
            wr_count <= 16'd0;
            waited   <= 1'b0;
        end else begin
            waited <= access && is_data && !waited;
            if (done_ok_write) begin
                if (paddr == A_CTRL)
                    ctrl <= pwdata[7:0];
                else
                    data <= pwdata;
                wr_count <= wr_count + 16'd1;
            end
        end
    end

endmodule
