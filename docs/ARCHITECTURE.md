# Architecture

> **Updated 2026-08-23 15:45 — this doc previously described a TypeScript-only
> engine. That is not what was built.** The engine is Python; the VS Code
> extension is a thin client. `src/types.ts` survives as the wire format.

```
┌─ VS Code extension (JS) ─────────────────────────────────────┐
│  extension/src/extension.js   9 commands, sidebar view        │
│  extension/media/dashboard.js lineage, metrics, activity      │
│  extension/media/chat.js      agent chat + approval prompts   │
└───────────────────────┬──────────────────────────────────────┘
                        │ HTTP — 127.0.0.1:8000
┌───────────────────────┴──────────────────────────────────────┐
│  chipevolve/  (Python 3.10+, pydantic v2, FastAPI)           │
│                                                              │
│  api/main.py            FastAPI surface                      │
│  cli.py                 analyze | evolve | status [--offline] │
│                                                              │
│  services/evolution.py  the generation loop                  │
│  agents/session.py      interactive chat (Claude, 3 modes)   │
│  agents/tools.py        13 tools, approval + path guards     │
│  services/workspace.py  isolated gen-N dirs                  │
│  services/integrity.py  SHA-256 protected-file gate          │
│  services/mutation.py   canned fallback (offline only)       │
│  agent/codex.py         REAL mutation — `codex exec`          │
│  eda/providers.py       verilator + yosys                    │
│  scoring/fitness.py     deterministic scoring                │
│  memory/local.py        experiment recall                    │
│  storage/repository.py  SQLite persistence                   │
└──────────────────────────────────────────────────────────────┘
                        │  subprocess
                 yosys · verilator · codex
```

## How a mutation is actually proposed

`agent/codex.py` shells out to the Codex CLI (verified against 0.149.0):

```bash
codex exec -C <workspace> -s workspace-write --skip-git-repo-check \
  --ignore-user-config \
  --output-schema chipevolve/agent/mutation_plan.schema.json \
  -o .codex-plan.json --json "<prompt>"
```

- `--output-schema` constrains Codex's final response to `MutationPlan`, so the
  plan arrives as validated JSON instead of prose we have to scrape.
- `--ignore-user-config` skips `~/.codex/config.toml`. A broken MCP server there
  kills the exec worker before it starts, and every teammate's config differs.
  Auth still resolves from `CODEX_HOME`.
- `-s workspace-write` confines edits to the generation directory.

The prompt carries the RTL, the current measured metrics, and recalled memory
lessons ("gen-2 tried shift/add, depth regressed 18%, rejected").

## Two agents, two jobs — don't confuse them

| | drives | provider |
|---|---|---|
| `agent/codex.py` | the automated **evolve** loop — proposes and applies one mutation per generation | **Codex CLI** |
| `agents/session.py` | the interactive **chat** panel — generate / review / optimize, human in the loop | Anthropic SDK |

Codex is the optimizer. The chat is an assistive panel beside it. They share
the tool layer's protected-path rules but nothing else.

## Three independent defenses against reward hacking

Deliberately redundant, because the testbench lives *inside* the sandbox:

1. `-s workspace-write` — Codex cannot reach outside the generation dir.
2. `agent/codex.py::_validate_paths` — every `files_to_modify` entry is matched
   against the project's `mutable` globs before the patch is trusted.
3. `services/integrity.py` — protected files are SHA-256 hashed before and
   after, and any delta rejects the generation. **This runs regardless of what
   the sandbox allowed or what Codex claimed.**

> **Historical bug worth knowing about.** This used `Path.glob(pattern)`, and
> `glob("tb/**")` returns only the *directory* `tb`, which the `is_file()`
> filter dropped. `protected_hashes()` therefore returned `{}` for every
> pattern and `integrity_matches({}, {})` was always `True` — the gate was
> inert. It now uses `fnmatch`, matching `agents/tools.py::is_protected`
> exactly, and an empty protected set counts as a failure to verify rather than
> a pass. Regression tests in `tests/test_integrity.py`.

## Gate order is the product

```python
if not verification.hard_gates_passed:   # protected · lint · sim · synth
    return REJECT
# only now is comparing numbers meaningful
```

A candidate that improves cell count 30% and breaks the testbench is rejected
without the cell count ever entering the decision.

## Fitness

```python
cost = Σ (candidate/baseline) × weight   # lower is better
```

Terms are included only when both sides have a real value. Area falls back to
cell count when no liberty file is configured; **delay falls back to Yosys logic
depth when there is no fmax**. Without that fallback the delay term drops out
entirely and fitness collapses to cell count alone — which would make the
priority-mux restructure (a depth win) score as noise.

## Provenance

`Generation.agent` is `"codex"` or `"offline"`. The `--offline` flag uses the
canned mutation in `services/mutation.py` as a demo-safety fallback only. **The
UI must show which one ran** — a canned run must never be mistaken for a real
one.

## What `src/types.ts` is now

Not a TypeScript engine contract — the wire format between the Python API and
the extension. Field names there are camelCase; the Python models are
snake_case. The extension is responsible for the mapping.
