# Architecture

Everything runs in the VS Code extension host as TypeScript. **No Python, no
FastAPI, no WebSocket server.** We shell out to EDA binaries directly. This
removes an entire process boundary and roughly 90 minutes of plumbing that buys
the demo nothing.

```
┌─ VS Code Extension Host (TypeScript) ────────────────────────┐
│                                                              │
│  extension.ts          command registration, webview panel   │
│         │                                                    │
│         ▼                                                    │
│  engine/evolution.ts   the generation loop  ── Lane C        │
│         │                                                    │
│         ├── agent/codex.ts      propose mutation (JSON plan) │
│         ├── engine/workspace.ts isolated gen-N dir + git     │
│         ├── engine/protect.ts   hash protected files         │
│         ├── engine/fitness.ts   deterministic scoring        │
│         ├── memory/*.ts         recall + record              │
│         │                                                    │
│         ▼                                                    │
│  eda/{verilator,yosys,openroad}.ts   ── Lane B               │
│         │  child_process.spawn, timeouts, log capture        │
│         ▼                                                    │
│  eda/parsers/*.ts      stdout ──► Metrics                    │
│                                                              │
│  EvolveEvent stream ──► webview (postMessage)  ── Lane D     │
└──────────────────────────────────────────────────────────────┘
                              │
                    examples/alu/  ── Lane A
```

## Generation lifecycle

```
analyzing → recalling_memory → planning_mutation → editing
  → linting → simulating → synthesizing → [physical_analysis] → scoring
  → accepted | rejected → done
```

Every transition emits `generation.stage`. The webview animates off that stream
and nothing else.

## Workspace isolation

Each candidate runs in its own directory. The source project is never mutated.

```
.chipevolve/
  baseline/
  generations/
    gen-001/    ← full copy + patch applied
    gen-002/
  logs/
  memory.json
```

Git checkpoint per candidate. **Rejected generations are never deleted** — their
diffs and metrics are the memory corpus.

## The gate order matters

Fitness is computed **only** after every hard gate passes:

```ts
if (verification.protectedFilesModified) return REJECT; // reward hacking
if (!verification.lintPassed)            return REJECT;
if (!verification.simulationPassed)      return REJECT;
// only now is it meaningful to compare numbers
return fitness(candidate) < fitness(best) ? ACCEPT : REJECT;
```

A candidate that improves area by 30% and breaks the testbench is rejected
without the area number ever being considered. This ordering is the product.

## Fitness

Normalized against baseline, lower is better:

```ts
cost = 0.55 * (area / baseArea) + 0.45 * (depth / baseDepth)
```

Two terms, because area and logic depth are what we can measure honestly from
Yosys. When OpenROAD data exists, slack and congestion terms are added and the
UI labels the score as physically-backed.

## Codex integration

Codex returns a `MutationPlan` as structured JSON, which is **validated before
any patch is applied**. An unparseable or out-of-bounds plan fails the
generation rather than being improvised around.

`filesToModify` is intersected with the project's mutable RTL set. A plan that
targets anything outside it is rejected at the tool layer, before Codex's edit
is ever run.
