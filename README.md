# ChipEvolve

**Your chip gets better every generation.**

ChipEvolve is a VS Code extension that autonomously improves RTL designs. Codex
proposes a hardware transformation; real EDA tools decide whether it survives.

> Every AI tool can generate Verilog. None of them prove the Verilog is better.
> ChipEvolve does — with Yosys and Verilator, not with an LLM's opinion.

---

## The thesis

Hardware optimization is a search loop that engineers run by hand: read RTL,
form a hypothesis, edit, simulate, synthesize, read the PPA numbers, decide,
revert, try again.

ChipEvolve closes that loop.

```
RTL
 ↓
Memory recall  ──── "we already tried shift/add here, timing regressed 18%"
 ↓
Codex proposes ONE focused mutation
 ↓
Apply patch (isolated workspace, git checkpoint)
 ↓
Verilator   — lint + testbench          ← correctness gate
 ↓
Yosys       — synthesis + cell stats    ← area + depth
 ↓
OpenROAD    — placement + routing       ← optional, real physical metrics
 ↓
Deterministic fitness
 ↓
ACCEPT or REJECT
 ↓
Record experiment as engineering memory
 ↓
Next generation
```

**The LLM proposes. The tools judge.** The agent never gets to declare its own
success.

---

## Three modes

The extension is a chat sidebar. Which tools the agent is handed depends on
the mode you pick, and that is enforced by the tool list itself — not by asking
the model nicely.

| Mode | What it does | Safe? |
|---|---|---|
| **Review** | Reads your design, reports problems. Has no editing tools at all. | Yes — start here |
| **Generate** | Writes new Verilog to your description | Edits files |
| **Optimize** | One full round: recall → change → lint → simulate → measure → score | Works in a copy |

Every edit shows you a diff and waits for you to approve or reject it.

Optimize runs in a generation workspace under `.chipevolve/generations/`. Your
working tree is untouched until you press **Apply to project**.

---

## What is actually measured

We do not fabricate numbers. Every metric below is either real, a labeled
proxy, or absent.

| Metric | Source | Status |
|---|---|---|
| Cell count | Yosys `stat` | Real |
| Register count | Yosys `stat` | Real |
| Area (µm²) | Yosys `stat -liberty` | Real when a liberty file is configured |
| Logic depth | Yosys / ABC longest path | **Proxy for delay — labeled as such in the UI** |
| Lint / simulation | Verilator | Real |
| Worst slack | OpenROAD | Real when the ORFS stage runs, otherwise `N/A` |
| Congestion | OpenROAD | Real when the ORFS stage runs, otherwise `N/A` |
| Power | — | **Not measured.** Honest dynamic power needs switching activity we don't have. |

Measured baseline on the demo ALU: `cellCount 510 · registerCount 9 ·
logicDepth 18 · areaUm2 null · 230/230 tests`.

Anything unavailable renders as `N/A`. That is a feature, not a gap.

---

## Anti-reward-hacking

An optimization agent will discover it can improve its score by changing the
benchmark instead of the design. We block that technically, not by prompting.

Protected paths — `tb/**`, `constraints/**`, `scripts/**` for the demo project,
set per project in `project.yaml` — are defended twice:

- **In the tool layer.** `write_file` and `replace_in_file` raise
  `ProtectedPathError` before touching the disk, so an agent edit to a
  testbench never happens rather than being detected afterwards.
- **By hashing.** Every protected file is SHA-256'd before and after each
  generation. Any change → generation rejected, no exceptions, no LLM
  involvement in the decision.

The UI shows `Protected evaluation integrity: PASS` on every accepted run.

---

## Engineering memory

Memory is part of the optimization algorithm, not a chat transcript.

Each generation records a structured experiment: module, mutation type,
hypothesis, before/after metrics, verification result, decision, and a one-line
lesson. Before proposing anything, the agent recalls related experiments on the
same module and mutation type.

```
MEMORY RECALL — 2 related experiments

GEN 03  shift/add decomposition     REJECTED
        area ↓11%  depth ↑18%
        lesson: avoid on this critical path

GEN 04  parallel mux                ACCEPTED
        area ↓5.4%  depth ↓7.6%
```

The evolve loop tracks **repeats avoided** — `_already_tried()` in
`chipevolve/services/evolution.py` compares a proposed mutation against prior
experiments of the same type and blocks it before spending a Codex call, then
bumps a `repeats_avoided` counter. That number is the point of memory, and it
is currently only in SQLite: no API field, no UI surface. Surfacing it is
outstanding work.

See [docs/MEMORY.md](docs/MEMORY.md).

---

## Prerequisites

```bash
brew install yosys verilator     # required — the inner loop
docker pull openroad/orfs        # optional — physical metrics, slow on Apple Silicon
```

macOS note: ORFS supports macOS via local build or Docker, but is the one
platform with **no prebuilt binaries**. Docker is the pragmatic path; it runs
emulated on Apple Silicon, so we use it for one hero generation, not the inner
loop.

## Quickstart

```bash
# 1. EDA toolchain
brew install yosys verilator

# 2. Engine (Python)
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# 3. Credentials
#    Codex drives the CLI evolve loop:
codex login status
#    Claude drives the chat sidebar — set this, or chipevolve.anthropicApiKey
#    in VS Code settings:
export ANTHROPIC_API_KEY=...

# 4. Establish the baseline, then evolve
.venv/bin/chipevolve analyze examples/alu
.venv/bin/chipevolve evolve  examples/alu
```

Expected baseline on the demo ALU: **510 cells · 9 registers · depth 18 ·
230/230 tests**. If you get different numbers, see `docs/BASELINE.md` — you are
probably not using `scripts/synth.ys`.

`--offline` swaps Codex for a canned mutation. Demo fallback only; the UI shows
which one ran.

### VS Code extension

```bash
# install the packaged build
npm run package
code --install-extension chipevolve.vsix

# or run from source
code .          # F5 → Extension Development Host
```

Then set two things in VS Code settings:

| Setting | Value |
|---|---|
| `chipevolve.anthropicApiKey` | your key, unless it is already in the backend's environment |
| `chipevolve.projectPath` | absolute path to `examples/alu`, so the agent sees the recorded generations |

Open the ChipEvolve view in the activity bar, run **ChipEvolve: Start Backend**,
pick a mode and send a task. The extension spawns the Python backend itself
(`.venv` on macOS/Linux, opt-in WSL on Windows via `chipevolve.useWsl`).

---

## Integration status

The UI shows live availability. Nothing is faked when unavailable.

| | |
|---|---|
| Yosys | required — cell count, register count, logic depth |
| Verilator | required — lint gate + 230-vector testbench |
| Codex | required for the CLI evolve loop — proposes and applies each mutation (`codex exec`) |
| Claude | required for the chat sidebar — Review, Generate and Optimize modes |
| Engineering memory | working — SQLite; recall, lessons, repeat blocking (counter not yet surfaced in the UI) |
| Claude-Mem | adapter slot, not yet wired — local store carries the feature |
| OpenROAD | not integrated — slack/congestion/power render `N/A` |

---

## For the team

| Doc | |
|---|---|
| [src/types.ts](src/types.ts) | **The frozen contract. Read this first.** |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | How the pieces fit |
| [docs/BASELINE.md](docs/BASELINE.md) | The measured baseline, and how to reproduce it |
| [docs/MEMORY.md](docs/MEMORY.md) | Memory schema + Claude-Mem adapter |
| [docs/DEMO-EXTENSION-3MIN.md](docs/DEMO-EXTENSION-3MIN.md) | The 3-minute script for the extension |
| [docs/DEMO.md](docs/DEMO.md) | The 3-minute script for the CLI loop |
| [docs/archive/](docs/archive/) | Hackathon-era planning docs — historical, paths are stale |
