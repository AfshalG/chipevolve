# Four-way split

**Freeze at 16:30. Judging at 17:00.** Everything below works backwards from that.

## Before anyone writes code (10 minutes, all four)

Read [`src/types.ts`](../../src/types.ts) together. It is the contract between all
four lanes. **Frozen at 13:45** — after that, nobody edits it without saying so
out loud.

Then every lane codes against those types with fake data, and nobody blocks on
anybody.

---

## Lanes

| Lane | Owner | Owns these paths |
|---|---|---|
| **A — Design & ground truth** | strongest Verilog person | `examples/alu/**`, `scripts/synth.ys` |
| **B — EDA runners & metrics** | systems person | `src/eda/**` |
| **C — Evolution engine** | agent/backend person | `src/engine/**`, `src/agent/**`, `src/memory/**` |
| **D — Extension & UI** | frontend person | `src/extension.ts`, `src/webview/**` |

Directory ownership is deliberate: four people, three hours, near-zero merge
conflicts.

**A is the critical path.** B needs A's design to parse real output. C and D are
never blocked — they stub.

---

## Checkpoints

Everyone stops and integrates. These are not optional.

### 14:15 — baseline is real
- A: demo RTL synthesizes, testbench passes, one deliberate inefficiency present
- B: parsing real `yosys stat` output into `Metrics`
- C: workspace isolation + git checkpoint working on fake metrics
- D: extension loads, webview opens, renders fixture generations

**If A slips here, cut RTL scope immediately** — a smaller module with one
obvious optimization beats an ambitious one that doesn't synthesize.

### 15:00 — one real generation, end to end
- B ↔ C wired: real metrics → real fitness → real accept/reject
- One complete generation runs in a terminal. No UI yet. It genuinely accepts or
  rejects based on measured numbers.

**This is the go/no-go on OpenROAD.** If 15:00 slips, drop OpenROAD, say it out
loud, and everyone stops thinking about it.

### 15:45 — it's a product
- D subscribes to C's `EvolveEvent` stream
- Real generations rendering live in the webview
- Memory recall visible in the UI

### 16:30 — FREEZE
No commits. No "quick fixes." Rehearsal only.

The most common way a hackathon demo dies is a commit at 16:52.

---

## Roles beyond code

**Demo driver — assign now.** Probably D. After 16:30 they own one thing:
running the demo start to finish, three times, on the machine that will be
plugged in. Not the machine that might be.

**Codex is a judging criterion, not a formality.** All four of you drive Codex.
Keep commit history legible enough to show it did meaningful work.

**OpenROAD pull runs in background from minute zero.** Whoever has a spare
terminal. It costs no attention.

---

## Git

```bash
git checkout -b lane-a-rtl      # or lane-b-eda / lane-c-engine / lane-d-ui
```

Branch off `development`. Merge at each checkpoint, not at the end.

## If you fall behind

Cut in this order:
1. OpenROAD → `N/A` everywhere. Costs nothing, demo still works.
2. Claude-Mem adapter → local JSON only. Memory story fully intact.
3. Diff view in UI → show hypothesis + metrics only.
4. Multiple generations → three good ones beat eight flaky ones.

**Never cut:** the accept/reject gate, protected-file hashing, or the fact that
the numbers are real. Those are the entire product.
