# ChipEvolve

**Your chip gets better every generation.**

ChipEvolve is a VS Code extension for hardware engineers. It generates, reviews, and optimizes
RTL from a chat sidebar — and every claim it makes is checked by real EDA tools before it reaches
you. The model proposes; Verilator, Yosys, and a deterministic fitness function decide.

## Three modes

| Mode | What it does | Tools it gets |
|---|---|---|
| **Generate** | Writes new synthesizable SystemVerilog to your spec, then lints it and fixes what lint reports. | read, write, lint, simulate, synthesize |
| **Review** | Reads your RTL as a design reviewer would and reports findings by severity, citing lint and synthesis output as evidence. Read-only — it has no editing tools at all. | read, lint, synthesize, memory |
| **Optimize** | Runs one generation of the evolution loop: recall prior experiments, form one hypothesis, make one focused edit, then lint → simulate → synthesize → score. | everything, plus fitness scoring and memory |

## How it stays honest

- **Tools decide, not the model.** Acceptance comes from `score_candidate`, a deterministic
  fitness function over measured cell count and area. The agent cannot override it.
- **Protected paths are enforced in code.** Testbenches, constraints, evaluation scripts, and
  golden references are unwritable. An attempt is blocked at the tool layer, surfaced in the UI,
  and recorded as a failed integrity gate — not merely discouraged by the prompt.
- **Optimize runs in a generation workspace.** Your working tree is untouched until you press
  *Apply to project*.
- **Missing tools are reported, never skipped.** If Verilator or Yosys is not installed, the run
  says so instead of quietly scoring a candidate it could not measure.

## Requirements

- VS Code 1.95 or newer.
- Python 3.10+ for the backend.
- Verilator and Yosys. On Windows these run through WSL; set `chipevolve.wslDistro` to your
  distribution. On Linux and macOS they are called directly.
- An Anthropic API key.

## Setup

```bash
# Backend dependencies
cd backend
python -m venv .venv
.venv/bin/pip install -e .          # Windows: .venv\Scripts\pip install -e .

# EDA tools (Ubuntu / WSL)
sudo apt install verilator yosys
```

Then set your key — either export `ANTHROPIC_API_KEY` in the environment the backend runs in, or
set `chipevolve.anthropicApiKey` in VS Code settings.

## Using it

1. Open the ChipEvolve view in the activity bar.
2. Pick a mode, describe the task, press Enter.
3. Approve or reject each edit. Auto-approve toggles for `read` / `edit` / `run` sit above the
   composer; **Open diff** shows a proposed change in VS Code's native diff view before you decide.
4. In Optimize mode, review the measured verdict and press *Apply to project* to keep it.

The **Dashboard** (toolbar icon) shows generation lineage and measured PPA over time.

## Settings

| Setting | Default | Purpose |
|---|---|---|
| `chipevolve.backendUrl` | `http://127.0.0.1:8000` | Where the FastAPI backend listens. |
| `chipevolve.wslDistro` | `Ubuntu` | WSL distribution holding Python and the EDA tools. |
| `chipevolve.projectPath` | `examples/alu` | Project root, relative to the extension or absolute. |
| `chipevolve.model` | `claude-opus-5` | Claude model driving the agent. |
| `chipevolve.anthropicApiKey` | *(empty)* | API key passed to the backend; falls back to the environment. |

## Layout

```
apps/extension/     VS Code extension — chat webview and host wiring
backend/chipevolve/
  agents/           prompts, tool layer, streaming agent loop
  eda/              Verilator and Yosys adapters (native or WSL)
  scoring/          deterministic PPAC fitness
  memory/           engineering memory over past experiments
  services/         evolution loop, workspaces, integrity hashing
examples/alu/       demo project with RTL, testbench, and constraints
```

## License

MIT
