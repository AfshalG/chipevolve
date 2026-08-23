# Demo script — 3 minutes

Rehearse this three times after the 16:30 freeze. On the machine that will
actually be plugged in.

## Before you start

- [ ] `.chipevolve/` wiped, baseline pre-run (don't burn demo time on baseline)
- [ ] Memory pre-seeded with 2–3 real experiments from earlier runs — the recall
      moment needs history to recall
- [ ] Terminal font size up
- [ ] Wifi irrelevant: everything but Codex runs locally
- [ ] Fallback recording of a full successful run, in case Codex hangs

## The script

**0:00 — The problem** (20s)

> Hardware engineers run the same loop all day: read RTL, guess at an
> optimization, edit, simulate, synthesize, read the area and timing numbers,
> decide, revert, try again. It's a search loop, and it's done by hand.

**0:20 — The claim** (15s)

> ChipEvolve closes that loop. Codex proposes the transformation — but Codex
> doesn't get to decide whether it worked. Verilator and Yosys do.

Open VS Code, ALU on screen. Point at the priority mux.

**0:35 — Hit EVOLVE** (60s)

Narrate the stages as they stream:

> It's recalling prior experiments on this module... proposing one focused
> mutation, with a hypothesis... applying the patch in an isolated workspace...
> Verilator, 42 of 42 passing... Yosys, cell count down 5.4%.
>
> Accepted — because the numbers say so, not because the model claims so.

**1:35 — The rejection** (30s)

This is the most important 30 seconds. Show a rejected generation.

> Here it tried a shift/add decomposition. Area improved 11%. Logic depth
> regressed 18%. Rejected. The agent doesn't get a vote.

**2:05 — Memory** (30s)

Open the Memory view.

> Every experiment is recorded, failures included. Before proposing anything it
> recalls related work on the same module. Twice this run it was about to repeat
> a transformation that already failed, and memory stopped it.
>
> Generation 7 is smarter than generation 1. That's the point.

**2:35 — Results** (25s)

Results screen up and leave it there.

> Seven generations, four accepted, three rejected. Cells down 9.8%, logic depth
> down 12.5%, testbench still fully passing, protected files unchanged.

## Questions you will get

**"What stops it from just editing the tests to pass?"**
Protected files are SHA-256 hashed before and after every generation. Any change
is an automatic reject. Enforced in the tool layer, not in the prompt. Show the
`Protected files: UNCHANGED` row.

**"Did you hardcode the optimized RTL?"**
No — and the git history shows every candidate, including the rejected ones. Show
a diff.

**"Is that real timing?"**
No, and we're explicit about it. Logic depth is a proxy from ABC and it's
labeled as a proxy everywhere in the UI. Real slack needs OpenROAD, which is
[running / marked N/A].

**"Why not just ask an LLM to optimize the Verilog?"**
Because it will tell you it improved things and be wrong. Three of our seven
generations regressed. Only measurement catches that.

**"Where did Codex do the work?"**
It proposes every mutation as a structured plan with a hypothesis, and applies
the patch. Show `src/agent/codex.ts` and a plan JSON.

## If something breaks mid-demo

Keep talking, switch to the Results screen and the git history. A rejected
generation caused by a real tool failure is *on-thesis* — say so out loud:

> That's the system working. The tools rejected it, and it got recorded as a
> failed experiment.
