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

---

## Replay mode — new, and it's demo insurance

A single generation takes 60–90 seconds. Seven generations is ~10 minutes of
dead air, which is not a pitch.

C persists every run's full event stream to `.chipevolve/runs/<timestamp>.json`.
**Build a replay loader that reads that file and re-emits the events at 4×
speed.** Same rendering path, same components — you're just driving them from a
file instead of a live process.

Add a small control: `▶ Live` / `⏪ Replay <timestamp>`.

Demo shape this enables: start a live run at minute zero, narrate a replay of
last night's good run while it churns, cut back to the live one at the end. If
the live run dies on stage, nobody notices.

Get the file path and event shape from C by 15:30.

---

## The three views

### Evolution — the hero view

A lineage a judge understands with zero explanation:

```
BASELINE
   │
 GEN 01  ✓  cells -4.2%
   │
 GEN 02  ✕  simulation failed
   │
 GEN 03  ✓  cells -5.4%  depth -8.3%
   │
 GEN 04  ★  BEST
```

Rejected generations render as dimmed side branches — **never hidden.** "It
rejected three of seven" is the credibility of the whole product.

Click any generation → detail panel: hypothesis, strategy, memory recalled,
diff, verification, metric deltas, decision reason.

**Surface `failureReason` verbatim on rejected generations.** B is putting real
content there — `tb/alu_tb.sv:118 — opcode SUB: expected 8'hF3, got 8'h00`.
That string is what proves the gate is real. Don't truncate it into a badge.

### Memory

```
Observations        7
Recalls this run    6
Repeats avoided     2      ← make this the largest number on screen
```

Plus a searchable experiment timeline showing `strategy` and `targetSignal` per
observation. Claude-Mem is a sponsor and they will look at this view
specifically.

> If "repeats avoided" is showing 0 at 16:00, tell C immediately — it means the
> strategy-enum matching isn't firing. It is a two-line fix on their side, but
> only if they know.

### Activity — live log

Engineering events, not chat bubbles:

```
15:14:08  Analyzing ALU critical path
15:14:10  Recalled 2 related experiments
15:14:11  Proposed comparator_rewrite on result
15:14:15  Verilator 42/42 passed
15:14:19  Yosys complete — 12,410 cells
15:14:33  Cells -5.4%  Depth -8.3%
15:14:34  ACCEPTED
```

Auto-scroll. This fills dead air during a 30-second synthesis, and dead air is
what kills demos.

---

## Visual direction

Dark, dense, technical. Linear or a real EDA workstation — not ChatGPT.

- JetBrains Mono for all numbers and identifiers
- Thin borders, tight spacing, small status dots
- Animate accepted generations into the lineage; fade rejected ones to a side branch
- Animate metric numbers counting to their new value
- Green accept / red reject / amber running

Avoid: gradient blobs, sparkle icons, giant rounded cards, chat bubbles,
onboarding screens.

---

## Non-negotiables

- **`null` renders as `N/A`, never as `0`.** Silently showing zero for an
  unmeasured metric is the one thing that makes the whole product look fake.
- **Label logic depth as a proxy, not timing.** It comes from Yosys `ltp`
  (longest topological path), which correlates with delay but is not a timing
  analysis.
- Integration status row — real state only, no fake green dots:
  ```
  Yosys ●  Verilator ●  Codex ●  Claude-Mem ●
  ```
  OpenROAD is cut from scope — drop it from this row entirely rather than
  showing a permanently-grey dot.

---

## Results screen

Make it screenshot-worthy — this is the last thing on screen at judging.

```
EVOLUTION COMPLETE          7 generations · 4 accepted · 3 rejected

                 BASELINE      BEST        CHANGE
Cells            13,120        11,840      ↓ 9.8%
Logic depth      24            21          ↓ 12.5%  (proxy)
Verification     PASS
Protected files  UNCHANGED
Repeats avoided  2
```

**The `Area` row is gone.** It was always going to read `N/A` on both sides —
B isn't passing a liberty file to Yosys, so area is never measured. An
always-empty row on the hero screenshot is dead space and invites the question
"why is your main metric blank?" Keep `areaUm2` in the per-generation detail
panel as `N/A` if you like; keep it off the results screen.

### If A finishes their ablation, add this block

A is running one-shot Codex (no loop, no memory, no gate) against the same
baseline for comparison. If they get you numbers, add:

```
                 ONE-SHOT      EVOLVED
Cells            12,980        11,840
Verification     FAILED        PASS
```

This is the slide that answers *"why isn't this just prompting?"* Ask A for it
around 16:00.

---

## After 16:30

You are the demo driver. Run it end to end three times on the machine that will
actually be plugged in. Nothing else.

Rehearse the replay path too, not just the live one.
