# Lane A — Design & ground truth

**You are the critical path.** Nothing downstream is real until your baseline
runs. Target: done by **14:15**.

## Goal

One RTL module that synthesizes cleanly, has a testbench that genuinely passes,
and contains **at least one optimization a competent engineer would actually
find** — where the optimization provably moves the cell count.

## Files you own

```
examples/alu/rtl/alu.sv
examples/alu/tb/alu_tb.sv
examples/alu/constraints/
examples/alu/project.yaml
scripts/synth.ys
```

Nobody else touches these.

---

## STEP 0 — Do this first. 30 minutes. Everything depends on it.

**Yosys will delete most "deliberate inefficiencies" before Codex ever sees
them.** That is literally what a synthesis tool is for. Its default `synth`
script runs `opt_expr`, `opt_clean`, `wreduce`, `share`, and hands the result to
ABC for logic restructuring. Dead code, duplicated subexpressions, and
priority-vs-flat-mux differences frequently vanish into an identical netlist.

If that happens on demo day: Codex proposes a real, correct optimization, the
testbench passes, and **the cell count doesn't move**. Every generation is
rejected on fitness. The lineage view is seven red branches. The demo is over.

So, before you write the real design:

1. Make a scratch directory **outside the repo** (`/tmp/probe/`).
2. Write the naive version and the optimized version of a candidate.
3. Synthesize both with `yosys -p "read_verilog -sv f.sv; synth -top alu; stat"`.
4. Compare `Number of cells`.

**You need a gap of at least ~5%.** If the two versions produce the same cell
count, that candidate is dead — move to the next one. Have four candidates
ready so at least one survives.

> This does **not** compromise the "was it pre-baked?" answer. The optimized
> file never enters the repo, and Codex still has to discover the transformation
> on its own. You are confirming that a delta *exists* — shipping a fitness
> function that can never improve is the actual failure.

Delete `/tmp/probe/` when you're done. Nothing from it goes in the repo.

### Candidates, ranked by likelihood of surviving Yosys

1. **Comparison implemented as arithmetic.** `if ((a - b) == 0)` where
   `if (a == b)` would do. A subtractor is a full carry chain; equality is an
   XOR tree plus a NOR. Yosys will not make that swap for you and the gap is
   large. **Start here.**
2. **Over-wide internal datapath.** Compute in 33 or 40 bits, truncate at the
   output. `wreduce` catches some of this, but not when intermediates feed
   multiple consumers.
3. **Register wider than its value range, whose bits reach an output port.**
   Port-visible bits can't be stripped, so they survive optimization.
4. **Duplicated arithmetic across separate `always_comb` blocks** feeding
   different outputs. Cross-block sharing is where Yosys's `share` pass is
   weakest.

Two or three confirmed opportunities is right. That's several real generations.

> **Do not hardcode the optimized version anywhere in the repo.** Codex has to
> find it. If a judge asks whether the result was pre-baked — and they will —
> the answer must be a clean no.

---

## Done when

```bash
verilator --lint-only -Wall examples/alu/rtl/alu.sv              # clean
verilator --binary --timing examples/alu/tb/alu_tb.sv && ./obj_dir/Valu_tb
yosys -s scripts/synth.ys                                        # prints cell stats
```

All three green → announce it, B swaps your design in for their throwaway file.

**Note the `--timing` flag.** If your testbench generates a clock with delay
statements (`always #5 clk = ~clk`), `--binary` fails without it. Alternative:
make the ALU purely combinational and drive it with a loop — but then
`registerCount` is 0 and the `clock:` block in `project.yaml` is decorative.
Either is fine; just decide before 13:00.

---

## Testbench — this is your real job

The testbench is the correctness oracle for the entire system. Treat it as a
**threat model**, not a nice-to-have.

**The attack you are defending against:** if any opcode lacks a test, the
highest-fitness move available to Codex is to delete that opcode's logic
entirely. Cell count drops, tests still pass, and you've "optimized" by removing
functionality. A judge who spots this sinks the project.

Therefore:

- Every opcode, with tests that fail loudly if the logic vanishes
- Edge cases: zero, all-ones, overflow, carry, both operands equal
- Non-zero exit on any failure
- Print a machine-parseable summary line for B:
  ```
  TESTS: 42/42 PASSED
  ```

**Sanity check before you announce:** hand-break one opcode, confirm the
testbench catches it, put it back. If it doesn't catch it, the gate is theatre.

---

## project.yaml

```yaml
project:
  name: demo-alu
  top: alu
rtl:
  - rtl/alu.sv
testbench:
  command: verilator --binary --timing tb/alu_tb.sv && ./obj_dir/Valu_tb
clock:
  name: clk
  period_ns: 10
mutable:
  - rtl/**
protected:
  - tb/**
  - constraints/**
  - scripts/**
  - project.yaml
```

**`scripts/**` and `project.yaml` are new and they matter.** Without them,
Codex can edit `synth.ys` — change the synthesis script and you can "improve"
cell count 40% with a one-line diff that optimizes nothing. Same for
`project.yaml`: editing the testbench command is a way to make verification
trivially pass. The judge who asks "what stops it editing the tests?" is the
same judge who asks about the toolchain config.

Get the globs right. C's tool layer enforces them by hashing.

---

## After 14:15 — you are not done

Two tasks, both high-leverage:

### 1. The ablation (do this first, ~1 hour)

Run **one-shot Codex** — no loop, no memory, no verification gate — against the
same baseline. Record what it produces: does it break the testbench? Is the win
smaller? Does it hallucinate a metric?

This is the slide that answers *"why isn't this just prompting?"* — which is the
question that separates first place from fourth. Give the numbers to D for the
results screen.

### 2. README and submission writeup (~16:00)

Nobody else owns this and it's due at the same time as everything else.

---

## Gotchas

- Verilator is stricter than most tools. Fix warnings at 13:00, not 16:00.
- Yosys needs `read_verilog -sv` for SystemVerilog.
- Keep it to one or two files. Multi-file hierarchy costs time you don't have.
