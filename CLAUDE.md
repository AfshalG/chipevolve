# ChipEvolve — plain-language guide

## What this project is

A VS Code extension that tries to make a chip design smaller and faster,
automatically, over and over, until it can't do better.

The chip design is written in a language called Verilog (files ending in
`.sv`). Think of it as code that describes wires and logic gates instead of
software.

The loop is:

1. An AI (Codex) reads the Verilog and suggests one change.
2. We apply that change in a throwaway copy of the project.
3. We run real chip tools on it to check two things:
   - **Does it still work?** (tests must still pass)
   - **Is it smaller/shorter?** (count the gates)
4. If it broke, we throw the change away. If it works AND the numbers got
   better, we keep it.
5. Write down what we learned, then repeat.

Each round is called a **generation**.

The whole point of the demo: **the numbers are real.** They come from actual
chip tools reading actual output, not from the AI saying "I think this is
better." The AI never gets to judge itself.

## How the code is split

Everything runs inside the VS Code extension, in TypeScript. There is no
Python server and no separate backend. We just run the chip tools as
command-line programs and read what they print.

| Lane | Who does what | Folders |
|---|---|---|
| A | Writes the example chip + its test | `examples/alu/`, `scripts/synth.ys` |
| **B (us)** | **Runs the chip tools, reads their output, turns it into numbers** | **`src/eda/`** |
| C | The loop, the AI calls, the keep/throw-away decision | `src/engine/`, `src/agent/`, `src/memory/` |
| D | The extension window and the visuals | `src/extension.ts`, `src/webview/` |

`src/types.ts` is the shared agreement between all four lanes. **Don't edit
it.** If you think it needs a change, say so out loud first.

---

## What Lane B (our job) actually does

We are the part that talks to the chip tools and reports honest numbers.

Nobody else in the project runs a command-line tool. They all just call our
three functions and trust whatever we hand back.

### The two tools we drive

**Verilator** — the "does it still work?" tool. Two jobs:

- *Lint*: does the Verilog even make sense? (catches typos, bad syntax)
- *Simulate*: build the design, run the test file against it, and read the
  line it prints: `TESTS: 230/230 PASSED`

**Yosys** — the "how big is it?" tool. It compiles the Verilog down into
actual logic gates, then prints a report. We read two things from it:

- `cellCount` — how many gates. This is the main number. Smaller is better.
  Everything downstream scores on this.
- `logicDepth` — the longest chain of gates a signal has to travel through.
  A rough stand-in for "how slow is it." Shorter is better.

### The three functions we own

```ts
runVerilator(dir) -> { exec, result }   // works? tests passed?
runYosys(dir)     -> { exec, metrics }  // how many gates? how deep?
checkAvailability()                     // are the tools even installed?
```

`exec` is a record of the command we ran — what we typed, what it printed,
what the exit code was, whether it timed out. Every single run produces one.

### The rules we must not break

**Never make up a number.** If a tool didn't run, or didn't print the value,
the answer is `null`. The UI shows `N/A`. A guessed number would poison every
decision downstream and quietly ruin the whole demo.

Specifically: `areaUm2` is **always** `null`. Real area needs a cell library
file we aren't using. Leave it null. Tell Lane C so they don't build scoring
on it.

**Never crash.** Lane C's loop calls us in a loop. If a tool hangs or the
binary is missing, we kill it and return a normal result object saying it
failed. We never throw an error up into their loop.

**Timeouts, always:**

| What | Limit |
|---|---|
| Lint | 10 seconds |
| Simulation | 20 seconds |
| Synthesis (Yosys) | 30 seconds |

**When to retry:** if the tool itself broke (missing binary, hung, timed
out) → try once more. If the *Verilog* is broken (syntax error, test failed)
→ never retry. That's a real answer, not a glitch. Hand it back so the AI can
learn from it.

**`failureReason` is the money shot.** When something fails, don't write
"command exited 1". Write the actual error with file and line:

```
✗ tb/alu_tb.sv:118 — opcode SUB: expected 8'hF3, got 8'h00
```

This string shows up on screen, word for word, every time a change gets
rejected. It's what proves to a judge that the checking is real. Spend real
time on it.

**Never call `logicDepth` a timing number.** It's a proxy, an estimate. Not
in field names, not in output, not in anything we hand to Lane D.

### What we are NOT doing

**OpenROAD is cut.** It was going to give real physical numbers, but a full
run takes minutes and would just time out and return `null` anyway. Skip it.
`src/eda/openroad.ts` doesn't need to exist.

---

## The real numbers, measured on this machine

We ran Lane A's design through the actual tools here. These are the values our
parsers have to produce:

| What | This machine | Lane A's machine | Match? |
|---|---|---|---|
| `cellCount` | **521** | 510 | ✗ — different Yosys version |
| `registerCount` | 9 | 9 | ✓ |
| `logicDepth` | 18 | 18 | ✓ (same critical path) |
| `areaUm2` | null | null | ✓ |
| tests | 230/230 | 230/230 | ✓ |

**The 521 vs 510 gap is fine and expected.** Yosys 0.52 here vs 0.68 on Lane
A's Mac; different versions optimize slightly differently. It doesn't matter,
because scoring compares a candidate against *our own* baseline measured on
*this* machine — it's a ratio, not an absolute. Just don't hard-code 510
anywhere, and tell Lane C the baseline is measured at runtime, never
hard-coded.

### Careful — two of the documented regexes are wrong

`docs/BASELINE.md` lists parser regexes with the **number before the name**.
Real Yosys output has the **name before the number**. These two do not match
anything:

```
✗ /^\s*(\d+)\s+cells\s*$/m            never matches
✗ /^\s*(\d+)\s+\$_DFF_\w+\s*$/gm      never matches
```

The actual lines Yosys prints are:

```
   Number of cells:                521
     $_AND_                        167
     $_DFF_PN0_                      9
     $_NAND_                       191
```

So the four regexes we should actually use:

```ts
/^\s*Number of cells:\s+(\d+)\s*$/m              // cellCount
/^\s*(\$\S*[Dd][Ff][Ff]\S*)\s+(\d+)\s*$/gm       // registerCount: sum group 2
/Longest topological path in \w+ \(length=(\d+)\)/  // logicDepth  (this one is fine)
/TESTS:\s*(\d+)\/(\d+)\s+PASSED/                 // tests        (this one is fine)
```

Worth telling Lane A so `docs/BASELINE.md` gets fixed.

### Other things we learned by actually running it

**Lint success is not "no output."** Verilator 5.032 prints a report even when
everything is fine. Judge lint by the **exit code**, not by whether stderr is
empty. Verified: clean design → exit 0, syntax error → exit 1.

**Exit codes are trustworthy.** A design that fails its tests aborts with a
non-zero code (we measured 6). But still parse `TESTS:` and `RESULT:` too —
belt and braces, and we need the numbers for the UI anyway.

**Failure output is exactly what we want for `failureReason`.** We broke the
AND operation on purpose and the testbench printed:

```
FAIL  op=2 a=0x0f b=0x03  expected=0x03  got=0x0f
...
TESTS: 213/230 PASSED
RESULT: FAILED
```

That first FAIL line, plus the count, is our `failureReason`. It's already in
the perfect shape — we just have to grab it instead of writing "exit 1".

**Yosys is fast, simulation is slow.** Yosys finishes in under half a second,
nowhere near its 30s limit. But building the simulation took **~14 seconds**,
against a 20s limit. That's tight. The cause is that the files live on the
Windows drive, which WSL reads slowly. If it becomes a problem, either raise
the timeout or copy the working folder into WSL's own filesystem first.

### Saved sample output

Real tool output is saved in the scratchpad at `fixtures/` — clean lint, clean
sim, clean synthesis, and a failing sim. We can build and test every parser
against these files without running a tool at all.

---

## State of the branches (checked 2026-08-23)

- `main` — just docs, `src/types.ts`, `package.json`, `tsconfig.json`.
- `lane-a-rtl` — **done and verified.** The example chip, its test, the
  synthesis script, and `docs/BASELINE.md` with real measured numbers.
- `laneb` — our branch. Currently same as main. Nothing built yet.
- `extension` — a VS Code extension written in plain JavaScript under
  `extension/`. Heads up: it was written for the *old* plan, where a Python
  server ran at `127.0.0.1:8000`. The current plan has no Python server.
- `development` — has an older Python version of the whole thing
  (`chipevolve/` folder, FastAPI, WSL wrappers). This is the pre-pivot
  design. The current docs say TypeScript only. **Don't build on it.**

So the Python code on `development` and the extension on `extension` are
both from the older plan. Our lane follows the current docs: TypeScript,
in `src/eda/`.

---

## Toolchain setup on this machine (done 2026-08-23)

The chip tools only run properly on Linux, so they live in WSL:

- **WSL Ubuntu 26.04 LTS** — installed as the `Ubuntu` distro
- **Yosys 0.52**
- **Verilator 5.032**

All three commands were run against Lane A's design and produce correct
results. See the numbers section above.

### How we call them from our code

The extension runs on Windows; the tools run in Linux. So every command goes
through `wsl.exe`. The pattern that works:

```
wsl.exe -d Ubuntu --cd "<WINDOWS path>" -- <tool> <arg> <arg> ...
```

In Node, spawn that as an **array of arguments** with no shell:

```ts
spawn("wsl.exe", ["-d", "Ubuntu", "--cd", winDir, "--", "yosys", "-s", script])
```

Three rules, all learned the hard way:

1. **`--cd` needs a Windows path** (`C:\Users\...`). Give it a `/mnt/c/...`
   path and it fails with `ERROR_PATH_NOT_FOUND`. WSL converts it for us —
   so we never have to write path-translation code at all.
2. **`--cd` must come after `-d Ubuntu`.** The other order fails.
3. **Never pass a shell command as one big string.** Things like
   `bash -c "cd x && tool $VAR"` get mangled going through `wsl.exe` — `$`
   signs get eaten and argument boundaries break. Pass a plain argument
   array and skip the shell entirely.

Rule 3 is why we don't need the path-translating wrapper the old Python
branch had. This is simpler and less breakable.

Exit codes come back correctly through all of this — verified.
---

## What we built (Lane B)

```
src/eda/index.ts              the three functions everyone else calls
src/eda/run.ts                runs one command, always returns a result
src/eda/verilator.ts          the "does it still work?" gate
src/eda/yosys.ts              the "how big is it?" measurement
src/eda/parsers/verilator.ts  reads test counts and error lines
src/eda/parsers/yosys.ts      reads gate count, flip-flops, depth
src/eda/availability.ts       are the tools installed?
```

The three functions, exactly as the contract specifies:

```ts
runVerilator(dir) -> { exec, result }   // works? tests passed?
runYosys(dir)     -> { exec, metrics }  // how many gates? how deep?
checkAvailability()                     // are the tools installed?
```

### Things worth knowing about the code

**`runVerilator` does three steps, not two:** lint, then build the simulation,
then run it. If lint fails we stop — a design that will not compile cannot be
simulated. The contract returns a single `exec`, so we return whichever step
was the deciding one.

**Simulation timeouts are split.** The docs say 20s for simulation, but that
was written before anyone measured. Building takes ~14s here, so a single 20s
budget would throw away good designs for being slow to compile — the worst
possible failure. Building gets 60s, running gets 20s. A genuine hang is still
caught.

**Nothing ever throws.** Missing tool, timeout, crash — it all comes back as a
normal result object, because Lane C's loop must always get one.

**Retries follow the rule:** if the tool never ran (missing, killed, hung) we
try once more. If the tool ran and reported bad Verilog, that is a real answer
and we return it untouched.

**`protectedFilesModified` is always `false` here.** We cannot know it — Lane C
hashes the files and fills it in.

### Checked against the real tools

18 checks pass, run from a cold start with no leftover build files. They cover
the parsers against saved output, plus real runs of both tools on a good
design, a design with a deliberate logic bug, and one with a syntax error.

The check script and the saved tool output live in the scratchpad
(`check.js`, `fixtures/`). Worth moving into the repo if we want to keep them.

Real results from the failing cases — this is what the UI will show:

```
FAIL  op=2 a=0x0f b=0x03  expected=0x03  got=0x0f  (17 of 230 tests failed)
%Error: rtl/alu.sv:119:1: syntax error, unexpected end of file
```


## How we work in this lane

- **Only touch `src/eda/`.** Everything else belongs to somebody else.
- **Keep it simple.** No frameworks, no abstraction layers, no clever
  patterns. This is a hackathon. A function that spawns a process and a
  function with a regex in it is the right amount of engineering.
- **No made-up numbers, ever.** This is the one rule the whole product rests
  on.
