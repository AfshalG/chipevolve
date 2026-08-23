# Lane B — EDA runners & metrics

You turn terminal noise into typed `Metrics`. Everything downstream trusts your
numbers, so **never invent one** — absent is `null`, and the UI shows `N/A`.

## Files you own

```
src/eda/verilator.ts
src/eda/yosys.ts
src/eda/parsers/
src/eda/availability.ts
```

`src/eda/openroad.ts` is cut — see the bottom of this doc.

## Contract

```ts
runVerilator(dir: string): Promise<{ exec: ToolExecution; result: VerificationResult }>
runYosys(dir: string):     Promise<{ exec: ToolExecution; metrics: Metrics }>
checkAvailability():       Promise<Record<string, boolean>>
```

Types are in `src/types.ts`. Don't change them — announce if you need to.

## Start now, don't wait for A

Write the runners and parsers against any throwaway `.sv` you write yourself.
Swap in A's real design at 14:15. You lose nothing by starting cold.

---

## Yosys

```tcl
read_verilog -sv rtl/alu.sv
synth -top alu
stat
ltp -noff
```

### Parsing `stat`

| Field | Source line | Notes |
|---|---|---|
| `cellCount` | `Number of cells` | **This is the primary fitness input.** C's scoring depends on it. |
| `registerCount` | sum of `$_DFF_*` / `$dff` rows | Zero if A's ALU is combinational — that's fine, not a bug |
| `areaUm2` | `Chip area for module` | Only appears with `-liberty`. **You are not passing a liberty file, so this is always `null`.** Leave it null. Don't fake it. |

### Parsing `ltp -noff`

For `logicDepth`, use Yosys's built-in `ltp -noff` (longest topological path).
It prints a line like `Longest topological path ... (length=21)`. One regex.

**Do not try to parse ABC's output for this.** It's fiddly and you have enough
to do. `ltp` gives you the same signal for a tenth of the effort.

> **This is a proxy for delay, not a timing number.** Never label it as timing
> anywhere in your output, your field names, or anything you hand to D.

---

## Verilator

Two calls:

1. `verilator --lint-only -Wall` → `lintPassed`
2. `verilator --binary --timing tb/alu_tb.sv && ./obj_dir/Valu_tb` →
   `simulationPassed`, plus parse `TESTS: n/m PASSED`

Confirm the exact command with A — if their testbench is combinational they may
drop `--timing`.

### `failureReason` is a demo asset, not a log field

On failure, put the **actual error** in `failureReason` — file, line, expected
vs received. This string renders verbatim in the UI during rejected
generations, and rejections are the credibility of the whole product.

```
✗ tb/alu_tb.sv:118 — opcode SUB: expected 8'hF3, got 8'h00
```

...sells the verification gate. `Command exited 1` is a wasted demo moment.

Budget real time for this. It is the highest-visibility thing you produce.

---

## Every invocation returns a ToolExecution

Timeouts, non-negotiable — a hung tool must not hang the demo:

| Tool | Timeout |
|---|---|
| Verilator lint | 10s |
| Simulation | 20s |
| Yosys | 30s |

On timeout: set `timedOut: true`, kill the process, return cleanly.
**Never throw into the engine.** C's loop must always get a result object back.

## Retry policy

- Infrastructure failure (binary missing, timeout) → one retry, then give up
- **Invalid RTL (syntax error, sim mismatch) → never retry.** That's a real
  result. Return it and let the agent learn from it.

---

## OpenROAD — cut

Previously scoped as "one hero generation at the end via
`docker run openroad/orfs`." Dropping it.

Reason: a full ORFS place-and-route flow under emulation on Apple Silicon takes
minutes, not the 120s timeout. It will time out, return `null`, and render
`N/A` — which is exactly what you get by not building it, minus four to six
hours of your time.

Spend those hours on `failureReason` quality instead.

If you somehow finish everything by 15:00 and want it: build it returning
`null` on any problem, never throwing, never retrying, never blocking. But
don't start it before then.

---

## Handoff

- **14:15** — A announces green. Swap their `alu.sv` in for your throwaway.
- **15:00** — C swaps your real `runYosys` in for their stub. Make sure
  `cellCount` and `logicDepth` are populated and `areaUm2` is `null` by then.
  Tell C explicitly that `areaUm2` is null so they don't build fitness on it.
