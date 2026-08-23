/**
 * Lane B — the "does it still work?" gate.
 *
 * Two steps: lint the RTL, then build and run the testbench. If lint fails we
 * stop there, because a design that will not compile cannot be simulated.
 *
 * Commands match examples/alu/project.yaml. -Wno-UNUSEDSIGNAL is deliberate:
 * the unused bits it warns about are seeded optimisation opportunities, and
 * without the flag the starting design fails its own gate.
 *
 * -------------------------------------------------------------------------
 * LANE C — PLEASE READ: protectedFilesModified is NOT answered here.
 *
 * That field asks "did the agent cheat by editing the testbench?". We cannot
 * answer it. We are handed one folder and asked to measure it; we never see
 * what the files looked like before the mutation, so we have no before/after
 * to compare. Only the lane that copies the workspace and applies the edit
 * can know.
 *
 * The type is a plain `boolean` with no null option, so there is no way for
 * us to say "unknown". We are forced to write `false`, which READS like
 * "checked, no cheating" but MEANS "not checked, not our job".
 *
 * Overwrite it after hashing the protected files. If you take our `false` at
 * face value, the anti-cheat gate silently never runs.
 * -------------------------------------------------------------------------
 */

import type { ToolExecution, VerificationResult } from '../types';
import { runTool, runToolWithRetry } from './run';
import {
  parseTestCounts,
  parseLintError,
  parseFirstTestFailure,
} from './parsers/verilator';

const TOP = 'alu';
const TB_TOP = 'alu_tb';
const RTL = 'rtl/alu.sv';
const TB = 'tb/alu_tb.sv';
const SIM_BINARY = './obj_dir/alu_tb';

const LINT_TIMEOUT_MS = 10_000;
/**
 * The docs budget 20s for simulation, but that was written before anyone
 * measured. A fresh build here takes ~14s, because the project files sit on
 * the Windows drive and WSL reads that slowly. 20s would reject good designs
 * for being slow to compile, which is the worst possible failure. Building and
 * running are timed separately so a genuine hang is still caught quickly.
 */
const BUILD_TIMEOUT_MS = 60_000;
const RUN_TIMEOUT_MS = 20_000;

export async function runVerilator(
  dir: string,
): Promise<{ exec: ToolExecution; result: VerificationResult }> {
  const lint = await runToolWithRetry({
    tool: 'verilator',
    dir,
    timeoutMs: LINT_TIMEOUT_MS,
    argv: ['verilator', '--lint-only', '-Wall', '-Wno-UNUSEDSIGNAL', '--top-module', TOP, RTL],
  });

  // Judge lint by exit code, not by whether it printed anything — verilator
  // prints a summary report even on a completely clean run.
  if (!lint.success) {
    return { exec: lint, result: failed(lint, 'lint') };
  }

  const build = await runToolWithRetry({
    tool: 'verilator',
    dir,
    timeoutMs: BUILD_TIMEOUT_MS,
    argv: [
      'verilator', '--binary', '--timing',
      '-Wno-UNUSEDSIGNAL', '-Wno-fatal',
      '--top-module', TB_TOP, TB, RTL,
      '-o', TB_TOP,
    ],
  });

  if (!build.success) {
    return { exec: build, result: { ...failed(build, 'build'), lintPassed: true } };
  }

  const sim = await runTool({
    tool: 'verilator',
    dir,
    timeoutMs: RUN_TIMEOUT_MS,
    argv: [SIM_BINARY],
  });

  const counts = parseTestCounts(sim.stdout);
  const allPassed = sim.success && counts !== null && counts.passed === counts.total;

  return {
    exec: sim,
    result: {
      lintPassed: true,
      simulationPassed: allPassed,
      testsPassed: counts ? counts.passed : null,
      testsTotal: counts ? counts.total : null,
      // NOT a real answer — see the note at the top of this file.
      // Means "we did not check", not "nobody cheated". Lane C overwrites it.
      protectedFilesModified: false,
      failureReason: allPassed ? null : simulationFailureReason(sim, counts),
    },
  };
}

/** Lint or build never got far enough to produce test numbers. */
function failed(exec: ToolExecution, stage: 'lint' | 'build'): VerificationResult {
  return {
    lintPassed: false,
    simulationPassed: false,
    testsPassed: null,
    testsTotal: null,
    // Placeholder, not a finding — see the note at the top of this file.
    protectedFilesModified: false,
    failureReason: describeToolFailure(exec, stage),
  };
}

/**
 * The failure text is shown to the user word for word every time a change is
 * rejected, so it has to name the actual problem — file, line, what was wrong.
 * "Command exited 1" is a wasted moment.
 */
function describeToolFailure(exec: ToolExecution, stage: 'lint' | 'build'): string {
  if (exec.timedOut) {
    return `Verilator ${stage} timed out — the tool was killed, no result.`;
  }
  const error = parseLintError(exec.stderr) ?? parseLintError(exec.stdout);
  if (error) return error;
  return `Verilator ${stage} failed with exit code ${exec.exitCode ?? 'none'}.`;
}

function simulationFailureReason(
  exec: ToolExecution,
  counts: { passed: number; total: number } | null,
): string {
  if (exec.timedOut) {
    return 'Simulation timed out — the design may have an infinite loop.';
  }

  const firstFailure = parseFirstTestFailure(exec.stdout);
  if (firstFailure && counts) {
    const failedCount = counts.total - counts.passed;
    return `${firstFailure}  (${failedCount} of ${counts.total} tests failed)`;
  }
  if (firstFailure) return firstFailure;

  if (!counts) {
    return 'Simulation produced no TESTS: line — the testbench did not finish.';
  }
  return `${counts.total - counts.passed} of ${counts.total} tests failed.`;
}
