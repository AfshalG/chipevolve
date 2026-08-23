/**
 * Lane B — the "how big is it?" measurement.
 *
 * One yosys run produces every number we report. The script (scripts/synth.ys)
 * ends with `stat` and `ltp -noff`, which is where the numbers come from.
 */

import type { Metrics, ToolExecution } from '../types';
import { runToolWithRetry } from './run';
import {
  parseCellCount,
  parseRegisterCount,
  parseLogicDepth,
} from './parsers/yosys';

/** Relative to the project directory, matching examples/alu/project.yaml. */
const SYNTH_SCRIPT = '../../scripts/synth.ys';

const YOSYS_TIMEOUT_MS = 30_000;

export async function runYosys(
  dir: string,
): Promise<{ exec: ToolExecution; metrics: Metrics }> {
  const started = Date.now();

  const exec = await runToolWithRetry({
    tool: 'yosys',
    dir,
    timeoutMs: YOSYS_TIMEOUT_MS,
    argv: ['yosys', '-s', SYNTH_SCRIPT],
  });

  const runtimeSeconds = Number(((Date.now() - started) / 1000).toFixed(3));

  // A failed run yields no numbers at all. Every field stays null rather than
  // being guessed — the UI shows N/A and Lane C skips scoring.
  if (!exec.success) {
    return { exec, metrics: emptyMetrics(runtimeSeconds) };
  }

  return {
    exec,
    metrics: {
      cellCount: parseCellCount(exec.stdout),
      registerCount: parseRegisterCount(exec.stdout),

      // LANE C — PLEASE READ: this is ALWAYS null, on every run, forever.
      //
      // Gate count and physical size are different things: different gate
      // types take different amounts of silicon. Converting one to the other
      // needs a liberty file (a size table from the foundry) and we do not
      // have one. Yosys can honestly count gates but cannot measure area, so
      // "unknown" is the only truthful answer. null is the contract's way of
      // saying that — see `areaUm2: number | null` in src/types.ts.
      //
      // Do NOT put this in the fitness formula. The original spec said
      // `area / baseArea`, which is null / null and breaks the moment our
      // real implementation replaces the stub. Score on cellCount instead.
      areaUm2: null,

      logicDepth: parseLogicDepth(exec.stdout),

      // OpenROAD is cut from scope, so these never get values.
      worstSlackNs: null,
      congestion: null,
      wirelengthUm: null,

      source: 'yosys',
      runtimeSeconds,
    },
  };
}

function emptyMetrics(runtimeSeconds: number): Metrics {
  return {
    cellCount: null,
    registerCount: null,
    areaUm2: null,
    logicDepth: null,
    worstSlackNs: null,
    congestion: null,
    wirelengthUm: null,
    source: 'yosys',
    runtimeSeconds,
  };
}
