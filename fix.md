# Fix list

Written 2026-08-23 after reading every branch and testing Lane B against the
real tools.

Three parts:

1. **Lane B is finished** — how to plug it in (skip if you already have)
2. **The `backend` branch** — what needs fixing before it can be demoed
3. **Two small fixes** elsewhere

---

# Part 1 — Lane B is done, here is how to use it

On branch `laneb`, commit `035a363`. Already pushed.

## What you need installed

The two measuring tools only run on Linux. On Windows they live inside WSL:

```bash
wsl --install -d Ubuntu --no-launch
wsl -d Ubuntu -u root -- apt-get update
wsl -d Ubuntu -u root -- apt-get install -y yosys verilator build-essential
```

Versions confirmed working: Yosys 0.52, Verilator 5.032.

## Try it by hand first

```bash
npm install
npm run compile
node out/eda/try-it.js <folder containing rtl/ and tb/>
```

Against Lane A's ALU you should see:

```
lint passed:       true
simulation passed: true
tests:             230 / 230
gates (cellCount): 521
logic depth:       18
```

If you get a different gate count, that is fine — a different Yosys version
packs things slightly differently. Nothing depends on the absolute number, only
on comparing a candidate against a baseline measured on the same machine.

## Plugging it into the loop

Delete the fake:

```ts
// remove this
const runYosys = async () => ({ metrics: { cellCount: 13120, logicDepth: 24 } });
```

Add the real one:

```ts
import { runVerilator, runYosys } from '../eda';
```

Nothing else changes. Same shapes, same field names.

```ts
runVerilator(dir) -> { exec, result }   // works? tests passed?
runYosys(dir)     -> { exec, metrics }  // how many gates? how deep?
checkAvailability()                     // are the tools installed?
```

## Three things to know before you wire it up

### 1. `areaUm2` is always null. Do not score on it.

Gate count and physical size are different things. Converting between them
needs a size table from a chip factory, which we do not have. So the honest
answer is always "unknown".

The original scoring formula was:

```ts
cost = 0.55 * (area / baseArea) + 0.45 * (depth / baseDepth)   // BREAKS
```

That is `null / null`. Use gate count instead:

```ts
cost = 0.55 * (cellCount / baseCellCount) + 0.45 * (logicDepth / baseLogicDepth)
```

### 2. `protectedFilesModified` is always `false` from Lane B, and that is NOT an answer

That field asks "did the agent cheat by editing the test file?" — because if it
can edit the tests, it can delete the failing ones and declare victory.

Lane B cannot answer it. Lane B is handed one folder and asked to measure it;
it never sees what the files looked like before the change, so it has no before
and after to compare. Only whoever copies the workspace and applies the edit
can know.

The type is a plain `boolean` with no "unknown" option, so `false` is the only
value that can be written. **It means "not checked", not "nobody cheated."**

You must overwrite it. There is working code for this already — see Part 2.

**If you take that `false` at face value, the anti-cheat gate silently never
runs, and nothing anywhere will tell you.**

### 3. Timeouts were adjusted after measuring

The docs budget 20 seconds for simulation. Building it actually takes about 14
seconds, because the files sit on the Windows drive and Linux reads that
slowly. A single 20s budget would throw away *good* designs for compiling
slowly, which looks exactly like the agent failing when it succeeded.

Now split: 60s to build, 20s to run. A genuine hang is still caught.

If it feels slow, copy the working folder inside WSL's own filesystem instead
of running it off `C:\`.

The `backend` branch hit this independently and fixed it the same week —
its newest commit makes all three timeouts configurable and raises them
(lint 60s, simulation 300s, synthesis 180s), with a comment noting that
Verilator compiles C++ before running a single test. Two people finding the
same thing separately is a good sign it is real.

---

# Part 2 — The `backend` branch

To look at it:

```bash
git fetch origin
git switch backend
```

It is the older design: Python, running as a separate program the extension
talks to over a network connection. The current docs dropped that in favour of
everything living inside the extension. Everything sits in a folder called
`temp/`.

Latest commit read: `2b1744a` ("second intial"), 23 Aug 17:36.

There is more here than the folder name suggests. Read the next section before
forming a view — the headline finding is not what it looks like at first
glance.

## There are TWO systems in this branch, and both are switched on

This is the most important thing to understand before touching anything.

**Path A — the real agent.** `temp/backend/chipevolve/agents/` holds a proper
Claude agent: a streaming conversation loop, eleven tools it can call
(`read_file`, `write_file`, `replace_in_file`, `run_lint`, `run_simulation`,
`run_synthesis`, `score_candidate`, `recall_memories`, ...), per-tool user
approval with a diff preview before anything is written, and a turn limit.
This is substantial, real work. Reached via `POST /api/agent/task`.

**Path B — the scripted one.** `temp/backend/chipevolve/services/mutation.py`
has the before and after versions of the code typed directly into the source
and does a find-and-replace. Reached via `POST /api/evolve`.

Both are wired up in `api/main.py`. Which one the demo shows depends on which
button gets pressed.

### The agent path is good — protect it

Worth calling out because it is better than what the docs asked for: the agent
**physically cannot** write to a protected file. `tools.py` raises
`ProtectedPathError` inside the tool itself, so the edit never happens.

That is stronger than checking afterwards whether files changed. The docs
describe catching a cheat after the fact; this prevents it. Keep it.

### The scripted path is the risk

If `POST /api/evolve` is what runs in the demo, these all apply:

- **Only one change is possible** — the one already typed in.
- **It can only run once.** After the swap the "before" text is gone, so
  generation 2 fails with `refusing a broad rewrite`. But repeated generations
  getting better is the whole pitch.
- **It cannot work on the real chip.** It carries its own 33-line ALU that
  matches those strings exactly. Lane A's real one is 119 lines with different
  signal names and no `OP_SLT` — verified. Point it at Lane A's design and it
  stops immediately.

**Decide which path is the product.** If it is the agent, the scripted one is
dead weight that will be demoed by accident — delete it or take the endpoint
away. If the scripted one is intentional demo insurance for when the API is
down, that is defensible, but label it clearly so nobody presents it as the
agent working.

## Problem — the example chip does not match Lane A's

Two different ALUs exist: `temp/examples/alu/rtl/alu.sv` (33 lines) and
`examples/alu/rtl/alu.sv` on `lane-a-rtl` (119 lines, tested, 230 test cases).

**Fix:** delete the toy one. Use Lane A's. It is the verified one.

## Problem — the scoring formula mostly evaporates

`temp/backend/chipevolve/scoring/fitness.py` scores on four things: power,
area, speed, congestion. We measure none of power, speed, or congestion. The
code quietly drops whatever is missing, so all four weights collapse into one:
gate count. It runs, but the weights are decoration.

It also never uses logic depth, which is one of only two real numbers we have.

**Fix:** score on the two numbers that actually exist.

```
cost = 0.55 * (cellCount / baseCellCount) + 0.45 * (logicDepth / baseLogicDepth)
```

## Keep this bit — it is the best code on the branch

`temp/backend/chipevolve/services/integrity.py` is the anti-cheat. It
fingerprints the protected files before and after and compares. Short, correct,
does exactly the right job.

**This is the missing piece from Part 1 item 2.** Whatever else happens to that
branch, this idea should survive — it is about 15 lines:

```python
def protected_hashes(root, patterns):     # fingerprint every protected file
def integrity_matches(before, after):     # did any of them change?
```

Call it before and after the edit, and put the answer into
`protectedFilesModified`.

## Also on that branch

- Build junk is committed: `.pyc` files throughout, and `temp/chipevolve.vsix`.
  Delete them and add to `.gitignore`.
- Everything is under `temp/`, which reads as throwaway. If it is not
  throwaway, move it. If it is, say so.

## What is already right and should not be touched

The order of the checks is correct and it matters:

```
protected files touched?  -> reject
lint failed?              -> reject
tests failed?             -> reject
only now compare numbers  -> keep or reject
```

A design that is 4% smaller but fails a test gets thrown out **without its gate
count ever being considered.** That ordering is the product. Do not "optimise"
it.

We confirmed this is not hypothetical. A deliberately broken version of Lane
A's ALU measures **502 gates against the good version's 521** — it looks like
an improvement on the numbers, and it is wrong. It fails 17 of 230 tests.

---

# Part 3 — Two small fixes elsewhere

## Lane A: two search patterns in `docs/BASELINE.md` are backwards

These two are listed for pulling numbers out of Yosys, and they match nothing:

```
/^\s*(\d+)\s+cells\s*$/m          looks for:  521 cells
/^\s*(\d+)\s+\$_DFF_\w+\s*$/gm    looks for:  9 $_DFF_
```

Yosys prints the name first, then the number:

```
   Number of cells:                521
     $_DFF_PN0_                      9
```

Working versions (checked against real Yosys 0.52 output):

```ts
/^\s*Number of cells:\s+(\d+)\s*$/m                   // gate count
/^\s*(\$\S*[Dd][Ff][Ff]\S*)\s+(\d+)\s*$/gm            // flip-flops: add up group 2
/Longest topological path in \w+ \(length=(\d+)\)/    // depth — already correct
/TESTS:\s*(\d+)\/(\d+)\s+PASSED/                      // tests — already correct
```

This one is worth fixing quickly because **it fails silently.** Finding nothing
is not an error — it just reports "no number", so every design comes back
unmeasurable with no error message anywhere.

Lane B already uses the corrected versions.

## The shared contract has a gap

In `src/types.ts`:

```ts
protectedFilesModified: boolean;   // no "unknown" option
```

Every other uncertain field in that file can be `null`, meaning "we did not
find out". This one cannot, so whoever fills the form in is forced to state a
definite answer even when they have not checked.

If the contract is still open, `boolean | null` would remove the trap. If it is
frozen, leave it — but everyone touching that field needs to know that `false`
from Lane B means "not checked".

---

# Suggested order

1. Point everything at Lane A's real chip, delete the toy one
2. Wire in Lane B (Part 1) and confirm real numbers appear
3. Move the anti-cheat check in and fill `protectedFilesModified` properly
4. Fix the scoring formula to use gate count and depth
5. Decide which path is the product — the agent or the scripted swap — and
   remove or clearly label the other ← the important one
6. Fix Lane A's two search patterns
7. Delete the committed build junk

Items 1–4 are small and make what already exists honest. Item 5 is a decision,
not a build — the agent is already written.

---

# One caveat on Part 2

This is a read of the code only — nobody who wrote it has been asked about it.

An earlier draft of this document claimed the agent did not exist at all. That
was wrong: the first pass through the branch missed the `agents/` folder
entirely. The agent is real and it is the most substantial code on the branch.
Anyone who saw that earlier claim should disregard it.

The open question is not "is there an agent" but "which of the two paths is
the one being demoed" — and only the author can answer that.
