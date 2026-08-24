// -----------------------------------------------------------------------------
// alu_tb — correctness oracle for ChipEvolve.
//
// This file is PROTECTED. The engine SHA-256 hashes it before and after every
// generation; any modification rejects the candidate outright. If a mutation
// breaks ALU semantics, this testbench is what catches it.
//
// Contract with Lane B: prints exactly one summary line
//     TESTS: <passed>/<total> PASSED
// and exits non-zero if any check fails.
// -----------------------------------------------------------------------------

module alu_tb;

    localparam int WIDTH = 8;

    logic             clk = 1'b0;
    logic             rst_n = 1'b0;
    logic [WIDTH-1:0] a, b;
    logic [3:0]       opcode;
    logic [WIDTH-1:0] result;
    logic             zero, carry;

    int passed = 0;
    int total  = 0;

    alu #(.WIDTH(WIDTH)) dut (
        .clk(clk), .rst_n(rst_n),
        .a(a), .b(b), .opcode(opcode),
        .result(result), .zero(zero), .carry(carry)
    );

    always #5 clk = ~clk;

    // Golden model — independent of the DUT implementation.
    function automatic logic [WIDTH-1:0] golden(
        input logic [WIDTH-1:0] ga,
        input logic [WIDTH-1:0] gb,
        input logic [3:0]       gop
    );
        logic [2*WIDTH-1:0] m;
        m = ga * gb;
        case (gop)
            4'd0:  golden = ga + gb;
            4'd1:  golden = ga - gb;
            4'd2:  golden = ga & gb;
            4'd3:  golden = ga | gb;
            4'd4:  golden = ga ^ gb;
            4'd5:  golden = ~ga;
            4'd6:  golden = ga << 1;
            4'd7:  golden = ga >> 1;
            4'd8:  golden = m[WIDTH-1:0];
            4'd9:  golden = {{(WIDTH-1){1'b0}}, (ga < gb)};
            4'd10: golden = {{(WIDTH-1){1'b0}}, (ga == gb)};
            4'd11: golden = ga;
            4'd12: golden = gb;
            4'd13: golden = ga + 8'd1;
            4'd14: golden = ga - 8'd1;
            default: golden = '0;
        endcase
    endfunction

    task automatic check(
        input logic [WIDTH-1:0] ta,
        input logic [WIDTH-1:0] tb_in,
        input logic [3:0]       top
    );
        logic [WIDTH-1:0] expected;
        begin
            @(negedge clk);
            a = ta; b = tb_in; opcode = top;
            @(posedge clk);
            @(negedge clk);          // result is registered — settle one cycle
            expected = golden(ta, tb_in, top);
            total++;
            if (result === expected) begin
                passed++;
            end else begin
                $display("FAIL  op=%0d a=0x%02h b=0x%02h  expected=0x%02h  got=0x%02h",
                         top, ta, tb_in, expected, result);
            end
        end
    endtask

    initial begin
        a = '0; b = '0; opcode = '0;
        repeat (2) @(posedge clk);
        rst_n = 1'b1;
        @(negedge clk);

        // Every opcode on a representative vector
        for (int op = 0; op < 15; op++) begin
            check(8'h0F, 8'h03, op[3:0]);
        end

        // Edge cases: zero, all-ones, overflow, borrow, equality
        check(8'h00, 8'h00, 4'd0);   // 0 + 0
        check(8'hFF, 8'h01, 4'd0);   // carry out
        check(8'h00, 8'h01, 4'd1);   // borrow
        check(8'hFF, 8'hFF, 4'd2);   // AND all-ones
        check(8'hAA, 8'h55, 4'd3);   // OR complementary
        check(8'hAA, 8'hAA, 4'd4);   // XOR self -> 0
        check(8'h80, 8'h00, 4'd6);   // SHL out of range
        check(8'h01, 8'h00, 4'd7);   // SHR to zero
        check(8'h10, 8'h10, 4'd8);   // MUL truncation
        check(8'h05, 8'h05, 4'd10);  // EQ true
        check(8'h05, 8'h06, 4'd10);  // EQ false
        check(8'h05, 8'h06, 4'd9);   // LT true
        check(8'h06, 8'h05, 4'd9);   // LT false
        check(8'hFF, 8'h00, 4'd13);  // INC wrap
        check(8'h00, 8'h00, 4'd14);  // DEC wrap

        // Randomized sweep — catches subtle mutation damage
        for (int i = 0; i < 200; i++) begin
            check($urandom_range(0, 255), $urandom_range(0, 255),
                  $urandom_range(0, 14));
        end

        $display("TESTS: %0d/%0d PASSED", passed, total);
        if (passed != total) begin
            $display("RESULT: FAILED");
            $fatal(1, "testbench failed");
        end else begin
            $display("RESULT: OK");
        end
        $finish;
    end

endmodule
