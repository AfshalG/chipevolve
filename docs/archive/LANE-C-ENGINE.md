# Lane C — Evolution engine

You own the loop and the decision. **The agent never decides whether it
succeeded — you do, from B's numbers.**

## Files you own

```
src/engine/evolution.ts    the generation loop
src/engine/workspace.ts    isolated dirs + git
src/engine/protect.ts      protected-file hashing
src/engine/fitness.ts      scoring
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

## The loop

```ts
for (let n = 1; n <= maxGenerations; n++) {
  emit({ type: 'generation.stage', stage: 'recalling_memory' });
  const memories = await memory.recall({ module, limit: 5 });

  emit({ type: 'generation.stage', stage: 'planning_mutation' });
  const plan = await proposeMutation(rtl, currentMetrics, memories);

  if (alreadyTried(plan, memories)) { repeatsAvoided++; continue; }

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
area 30% and breaks the testbench is rejected without the area number entering
the conversation.

`decisionReason` is always a concrete sentence. It goes straight on screen.

## Protected-file hashing

SHA-256 every file matching `protected` globs, before and after. Any delta →
immediate reject.

This is not prompting — it's enforcement, and it's the answer to the question a
judge *will* ask: "what stops it from just editing the tests?"

Also intersect `plan.filesToModify` with the `mutable` globs and reject
out-of-bounds plans **before** running Codex's edit.

## Codex

Ask for a `MutationPlan` as strict JSON. Validate before applying — unparseable
or out-of-bounds fails the generation rather than being improvised around.

Prompt must include: the RTL, current metrics, and **recalled lessons**. The
memory injection is what makes generation 5 smarter than generation 1.

> Verify the actual Codex CLI invocation and flags before writing this — check
> `codex --help` rather than assuming. Wrap it so a failure is a rejected
> generation, not a crashed extension.

## Fitness

```ts
cost = 0.55 * (area / baseArea) + 0.45 * (depth / baseDepth)   // lower better
```

Track **three** comparisons — a candidate can beat its parent while losing to
the global best:

```
baseline · parent · best-known
```

## Memory

`local.ts` first — JSON at `.chipevolve/memory.json`, ~40 lines, ships
regardless. `claudeMem.ts` last, behind the same interface. See
[MEMORY.md](../MEMORY.md).

## Emit events constantly

Lane D renders your `EvolveEvent` stream and nothing else. Emit on every stage
change and every meaningful log line. A silent 30-second synthesis looks broken.
