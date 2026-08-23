# Lane B — EDA runners & metrics

You turn terminal noise into typed `Metrics`. Everything downstream trusts your
numbers, so **never invent one** — absent is `null`, and the UI shows `N/A`.

## Files you own

```
src/eda/verilator.ts
src/eda/yosys.ts
src/eda/openroad.ts
src/eda/parsers/
src/eda/availability.ts
```

## Contract

```ts
runVerilator(dir: string): Promise<{ exec: ToolExecution; result: VerificationResult }>
runYosys(dir: string):     Promise<{ exec: ToolExecution; metrics: Metrics }>
runOpenROAD(dir: string):  Promise<{ exec: ToolExecution; metrics: Metrics } | null>
checkAvailability():       Promise<Record<string, boolean>>
```

Types are in `src/types.ts`. Don't change them — announce if you need to.

## Start now, don't wait for A

Write the runners and parsers against any throwaway `.sv`. Swap in A's design at
14:15. You lose nothing.

## Yosys

```tcl
read_verilog -sv rtl/alu.sv
synth -top alu
stat
```

Parse from `stat`:

| Field | Line |
|---|---|
| `cellCount` | `Number of cells` |
| `registerCount` | sum of `$_DFF_*` / `$dff` rows |
| `areaUm2` | `Chip area for module` — **only with `-liberty`, else `null`** |

For `logicDepth`, run ABC and parse the longest path. **This is a proxy for
delay, not a timing number** — B must never label it as timing anywhere.

## Verilator

Two calls:
1. `verilator --lint-only -Wall` → `lintPassed`
2. build + run testbench → `simulationPassed`, plus `TESTS: n/m PASSED`

On failure, put the actual error in `failureReason` — file, line, expected vs
received. This shows verbatim in the UI, and "Command exited 1" is a wasted
demo moment.

## Every invocation returns a ToolExecution

Timeouts, non-negotiable — a hung tool must not hang the demo:

| Tool | Timeout |
|---|---|
| Verilator lint | 10s |
| Simulation | 20s |
| Yosys | 30s |
| OpenROAD | 120s |

On timeout: `timedOut: true`, kill the process, return cleanly. Never throw into
the engine.

## OpenROAD — last, and only if 15:00 hits

Runs via `docker run openroad/orfs`, emulated on Apple Silicon, so it is **not**
in the inner loop. One hero generation at the end.

Returns `null` if Docker or the image is unavailable. The engine handles null by
leaving those fields absent. Don't throw, don't retry, don't block.

## Retry policy

- Infrastructure failure (binary missing, timeout) → one retry, then give up
- **Invalid RTL (syntax error, sim mismatch) → never retry.** That's a real
  result. Return it and let the agent learn from it.
