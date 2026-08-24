# Archive — hackathon-era planning docs

These are the documents the four lanes were built against on 2026-08-23.
They are kept because they record why the project is shaped the way it is,
**not** because they describe the code as it stands.

Two things in them are now wrong, and knowing that up front saves you the
confusion:

- **The file paths are from an abandoned design.** They describe a
  TypeScript implementation — `src/eda/`, `src/engine/`, `src/agent/codex.ts`,
  `src/memory/local.ts`. The project moved to Python. The equivalents live in
  `chipevolve/eda/`, `chipevolve/services/evolution.py`,
  `chipevolve/agent/codex.py` and `chipevolve/memory/local.py`.
- **`SPLIT.md` is a timetable for a day that has passed.** "Freeze at 16:30"
  refers to 2026-08-23. It is not a live process.

## What replaced them

| Archived | Read instead |
|---|---|
| `SPLIT.md` | `docs/ARCHITECTURE.md` for how the pieces fit today |
| `LANE-A-RTL.md`, `UpgradedLane/lane-a-*` | `docs/BASELINE.md` — the measured 510 / 9 / 18 baseline |
| `LANE-B-EDA.md`, `UpgradedLane/lane-b-*` | `chipevolve/eda/providers.py` |
| `LANE-C-ENGINE.md`, `UpgradedLane/lane-c-*` | `chipevolve/services/evolution.py`, `chipevolve/scoring/fitness.py` |
| `LANE-D-UI.md`, `UpgradedLane/lane-d-*` | `extension/src/extension.js`, `extension/media/` |

The frozen type contract referenced throughout is still at `src/types.ts`.
