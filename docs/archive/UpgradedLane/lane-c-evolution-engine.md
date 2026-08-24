# Lane C — Evolution engine

You own the loop and the decision. **The agent never decides whether it
succeeded — you do, from B's numbers.**

## Files you own

```
src/engine/evolution.ts    the generation loop
src/engine/workspace.ts    isolated dirs + git
src/engine/protect.ts      protected-file hashing
src/engine/fitness.ts      scoring
src/engine/replay.ts       NEW — persist the event stream
src/agent/codex.ts         mutation proposal
src/agent/prompt.ts        prompt construction
src/memory/local.ts        JSON store — build first
src/memory/claudeMem.ts    adapter — build last
```

## Start against a stub

```ts
const runYosys = async () => ({ metrics: { cellCount: 13120, logicDepth: 24 } });
```

Swap in B's real implementation at 15:00. Never wait.

---

## Fitness — use `cellCount`, not `area`

The original spec said:

```ts
cost = 0.55 * (area / baseArea) + 0.45 * (depth / baseDepth)
```

**This crashes.** B is not passing a liberty file to Yosys, so `areaUm2` is
`null` on every run. Use:

```ts
cost = 0.55 * (cellCount / baseCellCount) + 0.45 * (logicDepth / baseLogicDepth)
```

Lower is better. `areaUm2` stays a field on `Metrics` but nothing consumes it.

Track **three** comparisons — a candidate can beat its parent while losing to
the global best:

```
baseline · parent · best-known
```

---

## The loop

```ts
for (let n = 1; n <= maxGenerations; n++) {
  emit({ type: 'generation.stage', stage: 'recalling_memory' });
  const memories = await memory.recall({ module, limit: 5 });

  emit({ type: 'generation.stage', stage: 'planning_mutation' });
  const plan = await proposeMutation(rtl, currentMetrics, memories);

  if (alreadyTried(plan, memories)) { repeatsAvoided++; continue; }
  if (!withinMutableGlobs(plan.filesToModify)) { reject('Out-of-bounds plan'); continue; }

  const ws = await createWorkspace(n);        // copy + git checkpoint
  const before = await hashProtected(ws);
  await applyMutation(ws, plan);              // Codex edits
  const after = await hashProtected(ws);

  const verification = await verify(ws, before, after);
  const decision = decide(verification, candidateMetrics, bestMetrics);

  await memory.record(toObservation(plan, verification, decision));
  emit({ type: 'generation.decision', generation });
}
```

Note the glob check happens **before** the workspace is created and before
Codex runs — an out-of-bounds plan costs you nothing.

---

## MutationPlan schema — the `strategy` enum is load-bearing

Ask Codex for strict JSON. Validate before applying — unparseable or
out-of-bounds fails the generation rather than being improvised around.

```ts
type Strategy =
  | 'comparator_rewrite'
  | 'width_reduction'
  | 'resource_sharing'
  | 'mux_flattening'
  | 'operand_isolation'
  | 'constant_folding';

interface MutationPlan {
  strategy: Strategy;        // REQUIRED — must be one of the above
  targetSignal: string;      // e.g. "result", "carry_chain"
  hypothesis: string;        // free text, for the UI only
  filesToModify: string[];
}
```

### Why this matters

`alreadyTried()` compares plans against recalled memory. **If you compare
`hypothesis` strings, it will never fire** — Codex phrases the same idea
differently every time, so "repeats avoided" shows **0** on screen.

D's memory view makes that number the largest thing on the panel, and Claude-Mem
is a sponsor who will look at exactly that view. A zero there is worse than not
having the feature.

Match on the tuple instead:

```ts
const alreadyTried = (plan, memories) =>
  memories.some(m => m.strategy === plan.strategy
                  && m.targetSignal === plan.targetSignal);
```

String equality. It actually fires.

Put the enum in the prompt as a hard constraint: *"strategy must be exactly one
of these six values."*

---

## Gate order is the product

```ts
function decide(v, candidate, best) {
  if (v.protectedFilesModified) return reject('Protected files modified');
  if (!v.lintPassed)            return reject(v.failureReason);
  if (!v.simulationPassed)      return reject(v.failureReason);
  return fitness(candidate) < fitness(best)
    ? accept(...)
    : reject(`Fitness regressed: ${fitness(candidate)} vs ${fitness(best)}`);
}
```

Fitness is **never** computed before the gates pass. A candidate that improves
cell count 30% and breaks the testbench is rejected without the cell-count
number entering the conversation.

`decisionReason` is always a concrete sentence. It goes straight on screen.

---

## Protected-file hashing

SHA-256 every file matching `protected` globs, before and after. Any delta →
immediate reject.

**The protected set is now:**

```
tb/**
constraints/**
scripts/**        ← new
project.yaml      ← new
```

`scripts/**` covers `synth.ys`. Without it, Codex can edit the synthesis script
— change `synth -top alu` and you can "improve" cell count 40% with a one-line
diff that optimizes nothing. `project.yaml` protects the testbench command.

Also: confine Codex's working directory to the workspace copy so it can't reach
sibling directories at all.

This is not prompting — it's enforcement, and it's the answer to the question a
judge *will* ask: *"what stops it from just editing the tests?"*

---

## Replay — nobody owned this and the demo needs it

A generation takes roughly **60–90 seconds** (Codex call + lint + sim build and
run + synthesis). Seven generations is ~10 minutes. That is fine as a
background run and completely wrong for a live pitch.

**Persist the full `EvolveEvent` stream to JSON** as it runs:

```
.chipevolve/runs/<timestamp>.json
```

D loads it and replays at 4× speed. Then the demo is: kick off a live run at
minute zero, narrate a replay of last night's run while it churns, return to the
live one at the end. **If the live run dies on stage you lose nothing.**

This is ~30 lines. Do it by 15:30 and tell D the file path and shape.

---

## Codex

> Verify the actual Codex CLI invocation and flags before writing this — check
> `codex --help` rather than assuming. Wrap it so a failure is a rejected
> generation, not a crashed extension.

Prompt must include: the RTL, current metrics, **the strategy enum**, and
**recalled lessons**. The memory injection is what makes generation 5 smarter
than generation 1 — it's the reason this isn't a for-loop around a chatbot.

---

## Memory

`local.ts` first — JSON at `.chipevolve/memory.json`, ~40 lines, ships
regardless. `claudeMem.ts` last, behind the same interface. See
[MEMORY.md](MEMORY.md).

Every observation records: `strategy`, `targetSignal`, `hypothesis`,
`verification`, `decision`, `metrics`.

---

## Emit events constantly

Lane D renders your `EvolveEvent` stream and nothing else. Emit on every stage
change and every meaningful log line. A silent 30-second synthesis looks broken.
