# Lane A — Design & ground truth

**You are the critical path.** Nothing downstream is real until your baseline
runs. Target: done by **14:15**.

## Goal

One RTL module that synthesizes cleanly, has a testbench that genuinely passes,
and contains **at least one optimization a competent engineer would actually
find**.

## Files you own

```
examples/alu/rtl/alu.sv
examples/alu/tb/alu_tb.sv
examples/alu/constraints/
examples/alu/project.yaml
scripts/synth.ys
```

Nobody else touches these.

## Done when

```bash
verilator --lint-only examples/alu/rtl/alu.sv          # clean
verilator --binary examples/alu/tb/alu_tb.sv && ./obj_dir/Valu_tb   # all pass
yosys -s scripts/synth.ys                              # prints cell stats
```

All three green → announce it, B starts parsing real output.

## The design

An ALU is the right pick: small, synthesizes in seconds, everyone understands it.

**Build in a real inefficiency.** The best candidate is a priority-chain mux on
output select — a long `if/else if/else if` chain where a flat `case` would do.
It inflates logic depth, it's a transformation Codex can genuinely find, and the
improvement is measurable in cell count and depth.

Others worth seeding:
- an operation computed unconditionally then discarded (operand isolation)
- a register wider than its value range (bit-width reduction)
- the same subexpression computed twice (resource sharing)

Two or three seeded opportunities is right. That's several real generations.

> **Do not hardcode the optimized version anywhere.** Codex has to find it. If a
> judge asks whether the result was pre-baked — and they will — the answer must
> be a clean no.

## Testbench

This is your real job. The testbench is the correctness oracle for the whole
system.

- Cover every opcode, plus edge cases: zero, all-ones, overflow, carry
- Must **fail loudly** if a mutation breaks semantics — that's what makes
  rejection demoable
- Print a machine-parseable summary line for B:
  ```
  TESTS: 42/42 PASSED
  ```
- Non-zero exit on any failure

Sanity check: hand-break the priority encoder and confirm the testbench catches
it. If it doesn't, the gate is theatre.

## project.yaml

```yaml
project:
  name: demo-alu
  top: alu
rtl:
  - rtl/alu.sv
testbench:
  command: verilator --binary tb/alu_tb.sv && ./obj_dir/Valu_tb
clock:
  name: clk
  period_ns: 10
mutable:
  - rtl/**
protected:
  - tb/**
  - constraints/**
```

`mutable` vs `protected` is enforced by C's tool layer. Get the globs right.

## Gotchas

- Verilator is stricter than most tools. Fix warnings now, not at 16:00.
- Yosys needs `read_verilog -sv` for SystemVerilog.
- Keep it to one or two files. Multi-file hierarchy costs you time you don't have.
