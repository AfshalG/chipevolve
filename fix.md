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

Read as an early proof of shape, it does its job — a full loop runs and events
flow. The items below are what stands between it and a demo.

## Blocker 1 — the agent is not actually there

`temp/backend/chipevolve/services/mutation.py` contains this:

```python
BASELINE_BLOCK  = """...the before version of the code..."""
OPTIMIZED_BLOCK = """...the after version..."""
```

and then swaps one for the other. The improved design was written by hand in
advance; the program pastes it in.

Consequences:

- **Only one change is possible** — the one already written in.
- **It can only run once.** After the swap the "before" text is gone, so
  generation 2 fails with `refusing a broad rewrite`. But repeated generations
  getting better is the entire pitch.
- **It cannot work on the real chip.** It carries its own 33-line ALU that
  matches those strings exactly. Lane A's real one is 119 lines with different
  signal names and no `OP_SLT` — verified. Point it at Lane A's design and it
  stops immediately.

**Fix:** replace the hard-coded swap with a real agent call that returns a
`MutationPlan`, validate the plan before applying it, and confirm every file it
wants to touch is inside the allowed list.

## Blocker 2 — the example chip does not match Lane A's

Two different ALUs exist: `temp/examples/alu/rtl/alu.sv` (33 lines) and
`examples/alu/rtl/alu.sv` on `lane-a-rtl` (119 lines, tested, 230 test cases).

**Fix:** delete the toy one. Use Lane A's. It is the verified one.

## Blocker 3 — the scoring formula mostly evaporates

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
5. Replace the hard-coded swap with a real agent call ← the big one
6. Fix Lane A's two search patterns
7. Delete the committed build junk

Items 1–4 are small and make what already exists honest. Item 5 is the real
work.

---

# One caveat on Part 2

This is a read of the code only — nobody who wrote it has been asked about it.
There may be a plan to replace the hard-coded swap with a real agent call that
simply is not in the branch yet. Worth checking before treating any of it as
settled.
