# Lane D — Extension & UI

You own what the judges actually see. **Build entirely against fixture data** —
you are never blocked by anyone.

## Files you own

```
src/extension.ts
src/webview/**
media/**
```

## Start here

```ts
const FIXTURES: Generation[] = [ /* baseline + 3 accepted + 2 rejected */ ];
```

Render those. Swap to C's live event stream at 15:45.

## Extension shell

- Command: `chipevolve.evolve` → "ChipEvolve: Evolve"
- Webview panel, `retainContextWhenHidden: true`
- Subscribe to `EvolveEvent` via `postMessage`

## The three views

### Evolution — the hero view

A lineage that a judge understands with zero explanation:

```
BASELINE
   │
 GEN 01  ✓  area -4.2%
   │
 GEN 02  ✕  simulation failed
   │
 GEN 03  ✓  area -5.4%  depth -8.3%
   │
 GEN 04  ★  BEST
```

Rejected generations render as dimmed side branches — **never hidden.** "It
rejected three of seven" is the credibility of the whole product.

Click any generation → detail panel: hypothesis, memory recalled, diff,
verification, metric deltas, decision reason.

### Memory

```
Observations        7
Recalls this run    6
Repeats avoided     2      ← make this the largest number on screen
```

Plus a searchable experiment timeline. Claude-Mem is a sponsor and they will
look at this view specifically.

### Activity — live log

Engineering events, not chat bubbles:

```
15:14:08  Analyzing ALU critical path
15:14:10  Recalled 2 related experiments
15:14:11  Proposed mux restructuring
15:14:15  Verilator 42/42 passed
15:14:19  Yosys complete — 12,410 cells
15:14:33  Area -5.4%  Depth -8.3%
15:14:34  ACCEPTED
```

Auto-scroll. This is what fills the dead air during a 30-second synthesis, and
dead air is what kills demos.

## Visual direction

Dark, dense, technical. Linear or a real EDA workstation — not ChatGPT.

- JetBrains Mono for all numbers and identifiers
- Thin borders, tight spacing, small status dots
- Animate accepted generations into the lineage; fade rejected ones to a side branch
- Animate metric numbers counting to their new value
- Green accept / red reject / amber running

Avoid: gradient blobs, sparkle icons, giant rounded cards, chat bubbles,
onboarding screens.

## Non-negotiables

- **`null` renders as `N/A`, never as `0`.** Silently showing zero for an
  unmeasured metric is the one thing that makes the whole product look fake.
- Label logic depth as a **proxy**, not timing.
- Integration status row — real state only, no fake green dots:
  ```
  Yosys ●  Verilator ●  Codex ●  Claude-Mem ●  OpenROAD ○ not configured
  ```

## Results screen

Make it screenshot-worthy — this is the last thing on screen at judging.

```
EVOLUTION COMPLETE          7 generations · 4 accepted · 3 rejected

                 BASELINE      BEST        CHANGE
Cells            13,120        11,840      ↓ 9.8%
Logic depth      24            21          ↓ 12.5%  (proxy)
Area             N/A           N/A
Verification     PASS
Protected files  UNCHANGED
Repeats avoided  2
```

## After 16:30

You are the demo driver. Run it end to end three times on the machine that will
actually be plugged in. Nothing else.
