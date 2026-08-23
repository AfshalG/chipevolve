# Engineering memory

Memory is part of the optimization algorithm. It is **not** a chat transcript.

## What gets remembered

One structured experiment per generation — accepted *and* rejected. Failures are
the more valuable half.

```json
{
  "id": "mem-004",
  "project": "demo-alu",
  "generationId": "gen-004",
  "module": "alu",
  "mutationType": "mux_restructure",
  "hypothesis": "Priority-chain muxing is inflating logic depth",
  "metricsBefore": { "cellCount": 13120, "logicDepth": 24, "...": null },
  "metricsAfter":  { "cellCount": 12410, "logicDepth": 22, "...": null },
  "verification": { "lintPassed": true, "simulationPassed": true, "...": false },
  "decision": "accepted",
  "lesson": "Parallel mux on ALU output select: area -5.4%, depth -8.3%",
  "createdAt": "2026-08-23T15:12:04Z"
}
```

## The loop that makes it matter

Before proposing anything, the engine recalls by `module` + `mutationType` and
injects the lessons into Codex's prompt:

```
Agent plans:   "Replace multiplier with shift/add"

Memory says:   GEN 03 — shift/add on this datapath.
               area -11%, depth +18%. REJECTED.

Agent adapts:  proposes operand-width reduction instead
               repeatsAvoided += 1
```

**`repeatsAvoided` is the headline number.** It is direct evidence that the
system learned rather than re-rolled the dice. Surface it in the UI and say it
out loud in the demo.

## Implementation

`MemoryStore` (see `src/types.ts`) has exactly three methods: `recall`,
`record`, `stats`. Two implementations:

### `memory/local.ts` — build this first
JSON file at `.chipevolve/memory.json`. Recall filters by module + mutationType,
sorts most-recent-first. Roughly 40 lines. **Ships regardless of anything else.**

### `memory/claudeMem.ts` — Claude-Mem adapter
Same interface, backed by Claude-Mem.

> **Do not guess the API.** Check the actual claude-mem package surface before
> writing this — installed version, real method names, real return shapes. If it
> doesn't come together quickly, `local.ts` carries the entire memory story and
> nothing is lost.

Select via env var, defaulting to local:

```ts
const store: MemoryStore = process.env.CHIPEVOLVE_MEMORY === 'claude-mem'
  ? new ClaudeMemStore()
  : new LocalMemoryStore();
```

Surface which one is live in the integration status row. Real integration or
honest `not configured` — never a fake green dot.

## What the UI shows

```
MEMORY

Observations        7
Accepted lessons    4
Rejected lessons    3
Recalls this run    6
Repeats avoided     2      ← the one that matters
```

Plus a searchable timeline of experiments, each with its lesson.
