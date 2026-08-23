module alu_tb;
  logic [7:0] a;
  logic [7:0] b;
  logic [2:0] op;
  logic [7:0] y;
  logic [7:0] expected;

  alu dut (.*);

  function automatic logic [7:0] reference(input logic [7:0] lhs, input logic [7:0] rhs, input logic [2:0] operation);
    case (operation)
      3'd0: reference = lhs + rhs;
      3'd1: reference = lhs - rhs;
      3'd2: reference = lhs & rhs;
      3'd3: reference = lhs | rhs;
      3'd4: reference = lhs ^ rhs;
      3'd5: reference = $signed(lhs) < $signed(rhs);
      default: reference = '0;
    endcase
  endfunction

  initial begin
    for (int operation = 0; operation < 8; operation++) begin
      for (int lhs = 0; lhs < 256; lhs++) begin
        for (int rhs = 0; rhs < 256; rhs++) begin
          a = lhs[7:0];
          b = rhs[7:0];
          op = operation[2:0];
          expected = reference(a, b, op);
          #1;
          if (y !== expected)
            $fatal(1, "Mismatch op=%0d a=%0h b=%0h expected=%0h got=%0h", op, a, b, expected, y);
        end
      end
    end
    $display("PASS: 524288 ALU vectors");
    $finish;
  end
endmodule

