module alu #(
  parameter int WIDTH = 8
) (
  input  logic [WIDTH-1:0] a,
  input  logic [WIDTH-1:0] b,
  input  logic [2:0]       op,
  output logic [WIDTH-1:0] y
);
  localparam logic [2:0] OP_ADD = 3'd0;
  localparam logic [2:0] OP_SUB = 3'd1;
  localparam logic [2:0] OP_AND = 3'd2;
  localparam logic [2:0] OP_OR  = 3'd3;
  localparam logic [2:0] OP_XOR = 3'd4;
  localparam logic [2:0] OP_SLT = 3'd5;

  // Deliberately expressed as a priority chain so ChipEvolve has a focused demo target.
  always_comb begin
    y = '0;
    if (op == OP_ADD)
      y = a + b;
    else if (op == OP_SUB)
      y = a - b;
    else if (op == OP_AND)
      y = a & b;
    else if (op == OP_OR)
      y = a | b;
    else if (op == OP_XOR)
      y = a ^ b;
    else if (op == OP_SLT)
      y = {{(WIDTH-1){1'b0}}, ($signed(a) < $signed(b))};
  end
endmodule

