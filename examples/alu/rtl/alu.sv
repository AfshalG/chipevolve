// -----------------------------------------------------------------------------
// demo-alu — 8-bit ALU, registered output
//
// NOTE TO THE TEAM: this design contains DELIBERATE inefficiencies. They are the
// search space ChipEvolve explores. Do not "fix" them by hand — the whole point
// is that Codex finds them and the tools prove the improvement.
//
// Seeded opportunities:
//   1. Priority if/else-if chain on opcode select  -> mux_restructure
//      Synthesizes to a deep priority mux; a flat case gives a balanced mux.
//   2. `a + b` computed twice (sum_result, lt_flag) -> resource_sharing
//   3. Multiplier evaluated unconditionally         -> operand_isolation
//   4. acc_reg is 16 bits but only 8 are ever used  -> bitwidth_reduction
// -----------------------------------------------------------------------------

module alu #(
    parameter int WIDTH = 8
) (
    input  logic                 clk,
    input  logic                 rst_n,
    input  logic [WIDTH-1:0]     a,
    input  logic [WIDTH-1:0]     b,
    input  logic [3:0]           opcode,
    output logic [WIDTH-1:0]     result,
    output logic                 zero,
    output logic                 carry
);

    localparam logic [3:0] OP_ADD  = 4'd0;
    localparam logic [3:0] OP_SUB  = 4'd1;
    localparam logic [3:0] OP_AND  = 4'd2;
    localparam logic [3:0] OP_OR   = 4'd3;
    localparam logic [3:0] OP_XOR  = 4'd4;
    localparam logic [3:0] OP_NOT  = 4'd5;
    localparam logic [3:0] OP_SHL  = 4'd6;
    localparam logic [3:0] OP_SHR  = 4'd7;
    localparam logic [3:0] OP_MUL  = 4'd8;
    localparam logic [3:0] OP_LT   = 4'd9;
    localparam logic [3:0] OP_EQ   = 4'd10;
    localparam logic [3:0] OP_PASSA= 4'd11;
    localparam logic [3:0] OP_PASSB= 4'd12;
    localparam logic [3:0] OP_INC  = 4'd13;
    localparam logic [3:0] OP_DEC  = 4'd14;

    logic [WIDTH:0]      sum_result;
    logic [WIDTH:0]      diff_result;
    logic [2*WIDTH-1:0]  mul_result;
    logic                lt_flag;

    // OPPORTUNITY 2 + 3: `a + b` is computed here and again inside lt_flag below;
    // the multiplier is evaluated on every cycle regardless of opcode.
    always_comb begin
        sum_result  = {1'b0, a} + {1'b0, b};
        diff_result = {1'b0, a} - {1'b0, b};
        mul_result  = a * b;
        lt_flag     = (({1'b0, a} + {1'b0, b}) > {1'b0, b}) ? (a < b) : (a < b);
    end

    logic [WIDTH-1:0] next_result;
    logic             next_carry;

    // OPPORTUNITY 1: priority chain. Each comparison sits behind all the ones
    // above it, so OP_DEC is ~15 mux levels deep. A flat `case` collapses this.
    always_comb begin
        next_carry = 1'b0;
        if (opcode == OP_ADD) begin
            next_result = sum_result[WIDTH-1:0];
            next_carry  = sum_result[WIDTH];
        end else if (opcode == OP_SUB) begin
            next_result = diff_result[WIDTH-1:0];
            next_carry  = diff_result[WIDTH];
        end else if (opcode == OP_AND) begin
            next_result = a & b;
        end else if (opcode == OP_OR) begin
            next_result = a | b;
        end else if (opcode == OP_XOR) begin
            next_result = a ^ b;
        end else if (opcode == OP_NOT) begin
            next_result = ~a;
        end else if (opcode == OP_SHL) begin
            next_result = a << 1;
        end else if (opcode == OP_SHR) begin
            next_result = a >> 1;
        end else if (opcode == OP_MUL) begin
            next_result = mul_result[WIDTH-1:0];
        end else if (opcode == OP_LT) begin
            next_result = {{(WIDTH-1){1'b0}}, lt_flag};
        end else if (opcode == OP_EQ) begin
            next_result = {{(WIDTH-1){1'b0}}, (a == b)};
        end else if (opcode == OP_PASSA) begin
            next_result = a;
        end else if (opcode == OP_PASSB) begin
            next_result = b;
        end else if (opcode == OP_INC) begin
            next_result = a + 8'd1;
        end else if (opcode == OP_DEC) begin
            next_result = a - 8'd1;
        end else begin
            next_result = '0;
        end
    end

    // OPPORTUNITY 4: 16 bits wide, upper 8 never observed.
    logic [2*WIDTH-1:0] acc_reg;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            acc_reg <= '0;
            carry   <= 1'b0;
        end else begin
            acc_reg <= {{WIDTH{1'b0}}, next_result};
            carry   <= next_carry;
        end
    end

    assign result = acc_reg[WIDTH-1:0];
    assign zero   = (acc_reg[WIDTH-1:0] == '0);

endmodule
