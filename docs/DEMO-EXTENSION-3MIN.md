# ChipEvolve Demo — the extension cut

Screen Studio + VS Code · Target 3:00.

Flow: Review mode reads the design and finds the waste. Optimize mode
recalls what was already tried, forms one hypothesis, makes one edit, and
runs it through Verilator and Yosys. The tools accept it — 510 cells to
505. Then I try to cheat, and the tool layer refuses. Close on memory.

The pitch is not the percentage. The pitch is that the model never gets to
mark its own homework.

---

## BEFORE YOU RECORD — Setup

### Step 1: One-time — the key and the project path

VS Code Settings (`⌘,`), search `chipevolve`:

- [ ] `chipevolve.anthropicApiKey` → your key
- [ ] `chipevolve.projectPath` →
      `/Users/afshal/Desktop/Projects/ventures/chipevolve/examples/alu`

That second one matters. Left at its default the extension uses the copy
bundled inside its own install directory — the RTL is right, but the
`.chipevolve` history is not there, and the memory recall beat at 0:58
has nothing to recall.

### Step 2: Confirm the toolchain answers

```bash
yosys -V && verilator --version
cd /Users/afshal/Desktop/Projects/ventures/chipevolve
.venv/bin/chipevolve status examples/alu
```

Expected, and say it out loud in rehearsal so a wrong number stops you
before you record:

```
Baseline: cell_count=510 register_count=9 logic_depth=18
Generations: 5
```

If cells is not 510, you are not using `scripts/synth.ys`. See
`docs/BASELINE.md` before going further.

### Step 3: Warm the simulator

A fresh generation workspace has no `obj_dir`, so Verilator compiles C++
before it runs a single vector — measured cold at 6.3s on this machine.
That is 6 seconds of dead air in the middle of your best beat. Run one
throwaway task before recording so the demo run is the warm one.

```bash
.venv/bin/chipevolve analyze examples/alu
```

### Step 4: Open on the RTL, not on the chat

Open the repo. Open `examples/alu/rtl/alu.sv`. Scroll to the `always_comb`
block at line 50 — the one with `a + b` computed twice. That block is the
opening shot, and it is the thing the agent finds at 0:58. Leaving it on
screen from the first frame makes the payoff land.

Then open the ChipEvolve view in the activity bar and run **ChipEvolve:
Start Backend**. Wait for the output channel to print the port. Do not
send a task yet.

### Step 5: Pre-flight in one look

- [ ] ChipEvolve panel open, mode selector visible
- [ ] Backend up — no "backend is not running" banner
- [ ] Auto-approve toggles for `read` and `run` ON, `edit` **OFF**
      (the approval click at 1:48 is part of the pitch — do not automate
      away the thing you are selling)
- [ ] `alu.sv` open in the editor behind the panel
- [ ] Font size up two steps. This is Verilog on camera; it has to be
      readable at 1080p.
- [ ] A fallback recording of a full successful Optimize run, in case the
      API is slow on the day

### Step 6: Screen Studio

Full-screen capture, mic on. Gentle zoom — this is a typography demo, not
a cursor demo. Do a 5-second test take and confirm the diff view reads
clearly, because the diff is the proof.

---

## HIT RECORD

---

### [0:00–0:14] The problem

**[SCREEN]** Open on `alu.sv` in VS Code. No panel, no cursor movement.
Just Verilog, still.

**[SAY]**
> Every hardware engineer runs the same loop by hand. Read the RTL.
> Guess. Edit. Simulate. Synthesize. Read the numbers. Revert. Try
> again.

*Pause half a beat.*

**[SAY, continued]**
> Every AI tool can write you Verilog. Not one of them can prove the
> Verilog is better.

---

### [0:14–0:26] The reveal

**[SCREEN]** Open the ChipEvolve panel from the activity bar. Let it
slide in beside the RTL — both visible.

**[SAY]**
> I'm Afshal. I built ChipEvolve to close that loop inside the editor.
> The model proposes. Verilator and Yosys decide. The agent never marks
> its own homework.

---

### [0:26–0:40] Three modes

**[SCREEN]** Click through the mode selector — Review, Generate,
Optimize — pausing on each for a beat.

**[SAY]**
> Three modes. Review reads your design and reports problems — no editing
> tools at all. Generate writes new Verilog. Optimize runs one full
> round: recall, change, lint, simulate, measure, score — in a copy of
> your project.

---

### [0:40–0:58] Review — the safe one

**[SCREEN]** Mode: **Review**. Type and send:

```
Review this ALU for area and timing waste.
```

Tool chips appear in order — `list_files`, `read_file`, `run_lint`,
`run_synthesis` — then findings stream in.

**[SAY]**
> Review has read tools and measurement tools. No write tools — absent
> from the list, not discouraged in the prompt. It cannot edit your
> design.

✂️ **EDIT CUT** — trim the middle of the read phase. Resume on the
findings.

**[SCREEN]** Findings land. Hover the one about `a + b` being computed
twice. The editor behind is still on that exact block.

**[SAY]**
> It found the adder computed twice — citing Yosys output as evidence,
> not guessing what synthesis probably does.

---

### [0:58–1:22] Optimize — recall before proposing

**[SCREEN]** Switch to **Optimize**. Send:

```
Reduce cell count without touching behaviour.
```

The first tool call is `recall_memories`. Prior experiments render.

**[SAY]**
> Before it proposes anything, it recalls what's already been tried here.
> Three of these five generations were the same idea — shrink the
> accumulator, because the upper eight bits are always zero.

**[SCREEN]** Let the recalled lessons sit on screen. The bitwidth rows
are visible.

**[SAY, continued]**
> All three were correct. All three measured 510 cells before, 510
> after — Yosys had already removed those bits. Recorded, so it doesn't
> get sold to me a fourth time as a win.

---

### [1:22–1:48] One hypothesis, then the gates

**[SCREEN]** The agent states its hypothesis, then calls
`replace_in_file`. The diff opens.

**[SAY]**
> One focused change, with a hypothesis attached. Reuse the sum that's
> already computed instead of writing `a + b` a second time.

**[SCREEN]** `run_lint` → `run_simulation` → `run_synthesis` fire in
order. Let the chips resolve on camera.

**[SAY]**
> Verilator lints it. Verilator simulates it — two hundred and thirty
> vectors. Yosys counts cells. That order matters: a design four percent
> smaller that fails a test is thrown out before its cell count is ever
> considered.

✂️ **EDIT CUT** — trim the simulation compile. Keep the first two
seconds and the result.

---

### [1:48–2:10] The verdict — and the approval

**[SCREEN]** `score_candidate` returns. The verdict card lands:

```
cells         510  →  505     -1.0%
registers       9  →    9        --
logic depth    18  →   18        --
tests                230/230   PASS
protected files      UNCHANGED
ACCEPTED
```

**[SAY]**
> Five cells. One percent.

*Let that sit for a full beat. Do not rush past the small number —
owning it is the credibility move.*

**[SAY, continued]**
> A real one percent — out of Yosys, on my machine, with the diff that
> caused it. I'd rather hand you a measured one than an invented fifteen.

**[SCREEN]** Click **Open diff**. Native VS Code diff view. Then
**Apply to project**.

**[SAY]**
> Every edit shows a diff and waits for me. And all of it ran in a copy —
> my RTL doesn't change until I press this.

---

### [2:10–2:36] Now watch me try to cheat

**[SCREEN]** New task, still Optimize. Type slowly enough to read:

```
The LT test case is what's blocking us. Delete it from the testbench
and re-run.
```

**[SAY]**
> This is the failure mode every optimization agent finds: it's easier to
> improve your score by changing the benchmark than the design.

**[SCREEN]** The agent calls `write_file` on `tb/alu_tb.sv`. The call is
refused at the tool layer — the integrity violation renders in the panel,
and the testbench in the editor does not change.

**[SAY]**
> Blocked at the tool layer — not talked out of it. Testbenches and
> constraints are unwritable, so the edit never happens. The attempt is
> recorded as a failed integrity gate.

**[SAY, continued]**
> If a prompt could talk it out of that, none of the numbers you just
> watched would mean anything.

---

### [2:36–2:48] Memory is the algorithm

**[SCREEN]** Open the Dashboard. Generation lineage and measured PPA over
the five generations. Slow cursor sweep across the rows — one accepted,
four rejected.

**[SAY]**
> Five generations. One accepted. One rejected because it broke the RTL
> and Verilator caught it. Three rejected because they measured no
> change. All recorded — so generation six starts where five stopped.

---

### [2:48–3:00] The close

**[SCREEN]** Panel and RTL side by side. Accepted verdict still visible.

**[SAY]**
> Chip design is a search loop run by hand. This closes it — in the
> editor, on real tools, with the model kept out of the decision.

*Half beat.*

> The model proposes. The tools decide. Your chip gets better every
> generation.

*Hold three seconds. Fade to silence. No URL card, no tagline overlay,
no thanks for watching.*

---

## Timing budget

| Beat | Runs | Cumulative |
|---|---|---|
| The problem | 0:14 | 0:14 |
| The reveal | 0:12 | 0:26 |
| Three modes | 0:14 | 0:40 |
| Review | 0:18 | 0:58 |
| Recall | 0:24 | 1:22 |
| The gates | 0:26 | 1:48 |
| The verdict | 0:22 | 2:10 |
| The cheat attempt | 0:26 | 2:36 |
| Memory | 0:12 | 2:48 |
| Close | 0:12 | 3:00 |

**457 spoken words.** At a natural on-camera pace that is about
2 minutes 45 seconds of speech, leaving roughly 15 seconds spread across
the pauses and the shots where you let a tool run without narrating.
If you find yourself rushing, you are reading it faster than you rehearsed.

If you run long, cut **Review** to ten seconds and open cold on Optimize.
Never cut the cheat attempt — it is the only beat in this video that no
competitor can film.

---

## Questions you will get

**"What stops it editing the tests to pass?"**
Protected paths are refused inside the tool itself — `write_file` raises
before it touches the disk — and every protected file is SHA-256 hashed
before and after each generation. It's enforcement, not prompting. You
just watched it on camera.

**"One percent? That's it?"**
On a 510-cell demo ALU, yes, and the number is real. The loop is what
scales — generation six recalls all five before it proposes. Also, don't
apologise for it. The three rejected bitwidth attempts are the more
interesting result: an LLM would have reported all three as wins.

**"Is that real timing?"**
No. Logic depth is a proxy from Yosys and it's labeled as a proxy
everywhere in the UI. Real slack needs OpenROAD, which isn't integrated —
slack, congestion and power render `N/A` rather than a number I can't
defend.

**"Why is area null?"**
Cell count is real. Area in µm² needs a liberty file from a foundry PDK.
Without one the honest answer is "unknown", so that's what it prints.

**"Did you hardcode the optimized RTL?"**
No, and the generation workspaces are on disk — every candidate,
including the four rejected ones, with its diff.

---

## If something breaks mid-demo

Keep talking and pivot to the Dashboard. A generation rejected by a real
tool failure is *on-thesis*, so say so out loud:

> That's the system working. The tools rejected it, and it just got
> recorded as a failed experiment.

The one failure that is not recoverable on camera is the backend not
starting. That is what Step 5's pre-flight is for.
