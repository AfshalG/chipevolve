// 8x8 -> 16 unsigned multiplier.
// 4 register stages: latency 4 clocks, initiation interval 1 (new operand pair
// every cycle, no stalls). Partial-product tree is compressed 8 -> 4 -> 2, then
// the final 16-bit add is split into a low byte / high byte carry chain so that
// stage 4 does real work instead of being a retiming buffer.
module mul8_pipe4 (
  input  logic        clk,
  input  logic        rst_n,      // synchronous, active low; clears valid chain only
  input  logic        valid_in,
  input  logic [7:0]  a,
  input  logic [7:0]  b,
  output logic        valid_out,
  output logic [15:0] p
);
  localparam int W = 8;

  // ---------------------------------------------------------------------
  // Stage 1: partial-product generation + first compression (8 -> 4)
  // pp_s1[i] carries binary weight 2**(2*i)
  // ---------------------------------------------------------------------
  logic [9:0] pp_c  [4];
  logic [9:0] pp_s1 [4];

  always_comb begin
    for (int i = 0; i < 4; i++) begin
      pp_c[i] = {2'b0, (b[2*i]   ? a : {W{1'b0}})}          // a * b[2i]
              + {1'b0, (b[2*i+1] ? a : {W{1'b0}}), 1'b0};   // a * b[2i+1] << 1
    end
  end

  always_ff @(posedge clk) begin
    for (int i = 0; i < 4; i++) begin
      pp_s1[i] <= pp_c[i];
    end
  end

  // ---------------------------------------------------------------------
  // Stage 2: second compression (4 -> 2)
  // sum_s2[j] carries binary weight 2**(4*j)
  // ---------------------------------------------------------------------
  logic [11:0] sum_c  [2];
  logic [11:0] sum_s2 [2];

  always_comb begin
    sum_c[0] = {2'b0, pp_s1[0]} + {pp_s1[1], 2'b0};
    sum_c[1] = {2'b0, pp_s1[2]} + {pp_s1[3], 2'b0};
  end

  always_ff @(posedge clk) begin
    sum_s2[0] <= sum_c[0];
    sum_s2[1] <= sum_c[1];
  end

  // ---------------------------------------------------------------------
  // Stage 3: low half of the final add (8 bits + carry out)
  // ---------------------------------------------------------------------
  logic [8:0] lo_c;
  logic [7:0] lo_s3;
  logic       carry_s3;
  logic [7:0] hi_a_s3, hi_b_s3;

  always_comb begin
    lo_c = {1'b0, sum_s2[0][7:0]} + {1'b0, sum_s2[1][3:0], 4'b0};
  end

  always_ff @(posedge clk) begin
    lo_s3    <= lo_c[7:0];
    carry_s3 <= lo_c[8];
    hi_a_s3  <= {4'b0, sum_s2[0][11:8]};
    hi_b_s3  <= sum_s2[1][11:4];
  end

  // ---------------------------------------------------------------------
  // Stage 4: high half of the final add. Max product 255*255 = 16'hFE01,
  // so this add cannot carry out of bit 15; the 8-bit sum is exact.
  // ---------------------------------------------------------------------
  logic [15:0] p_s4;

  always_ff @(posedge clk) begin
    p_s4 <= {(hi_a_s3 + hi_b_s3 + {7'b0, carry_s3}), lo_s3};
  end

  assign p = p_s4;

  // ---------------------------------------------------------------------
  // Control: 4-deep valid shift register, the only reset flops in the design
  // ---------------------------------------------------------------------
  logic [3:0] vld_q;

  always_ff @(posedge clk) begin
    if (!rst_n)
      vld_q <= 4'b0;
    else
      vld_q <= {vld_q[2:0], valid_in};
  end

  assign valid_out = vld_q[3];
endmodule
