# Verified baseline

Reproduced 2026-08-23 on macOS / Apple Silicon.
Verilator 5.050, Yosys 0.68+post (both `brew install`).

## Reproduce

```bash
cd examples/alu

verilator --lint-only -Wall -Wno-UNUSEDSIGNAL --top-module alu rtl/alu.sv
# exit 0, no output

verilator --binary --timing -Wno-UNUSEDSIGNAL -Wno-fatal \
  --top-module alu_tb tb/alu_tb.sv rtl/alu.sv -o alu_tb
./obj_dir/alu_tb
# TESTS: 230/230 PASSED

yosys -s ../../scripts/synth.ys
```

## Measured numbers — Lane B parses exactly these

| Metric | Value | Parse from |
|---|---|---|
| `cellCount` | **510** | `stat` → `510 cells` |
| `registerCount` | **9** | `stat` → `9 $_DFF_PN0_` |
| `logicDepth` | **18** | `ltp` → `Longest topological path in alu (length=18)` |
| `areaUm2` | `null` | no liberty file — stays `N/A` |
| tests | **230/230** | `TESTS: 230/230 PASSED` |

Cell breakdown at baseline: 188 `$_NAND_`, 166 `$_AND_`, 43 `$_XOR_`,
40 `$_OR_`, 35 `$_XNOR_`, 15 `$_NOT_`, 14 `$_NOR_`, 9 `$_DFF_PN0_`.

## Parser regexes

```ts
/^\s*(\d+)\s+cells\s*$/m                                    // cellCount
/^\s*(\d+)\s+\$_DFF_\w+\s*$/gm                              // sum -> registerCount
/Longest topological path in \w+ \(length=(\d+)\)/          // logicDepth
/TESTS:\s*(\d+)\/(\d+)\s+PASSED/                            // tests
```

`ltp` prints the full path after that line — match the header only, ignore the rest.

## State of the seeded opportunities

Verified against real synthesis, not assumed:

| # | Opportunity | Status |
|---|---|---|
| 1 | Priority if/else-if chain | **Strong.** Depth 18 with the critical path running `a[1]` → 17 ABC nodes → `next_result[7]`. This is the headline generation. |
| 2 | Duplicated `a + b` | **Live.** Two adders present in the netlist. |
| 3 | Unconditional multiplier | **Live.** Dominates the AND/NAND count. |
| 4 | 16-bit `acc_reg` | **Weak — don't count on it.** Yosys already pruned the unused upper bits (9 DFFs, not 17). Bit-width reduction will show little or no cell delta. |

Opportunity 1 is where the demo lives. 2 and 3 are real follow-ups.

## Note on the lint flag

`-Wno-UNUSEDSIGNAL` is deliberate. Verilator flags the unused upper bits of
`mul_result` and `acc_reg` — which are opportunities 3 and 4. Without the flag
the baseline fails its own lint gate at generation 0.

If Codex fixes those, the warnings disappear on their own. Consider surfacing
them to the agent as hints rather than as gate failures.
