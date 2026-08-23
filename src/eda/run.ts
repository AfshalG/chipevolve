/**
 * Lane B — running EDA tools.
 *
 * The extension runs on Windows; yosys and verilator live inside WSL. Every
 * command therefore goes through wsl.exe:
 *
 *   wsl.exe -d Ubuntu --cd "C:\path\to\project" -- yosys -s script.ys
 *
 * Three rules, learned by getting them wrong first:
 *   1. --cd takes a WINDOWS path. WSL translates it for us, so we never write
 *      any path-conversion code of our own.
 *   2. --cd must come after -d.
 *   3. Never hand wsl.exe a shell string ("cd x && tool"). Dollar signs get
 *      eaten and argument boundaries break. Always pass a plain argv array.
 */

import { spawn } from 'child_process';
import * as path from 'path';
import type { ToolExecution } from '../types';

/** The WSL distribution holding yosys and verilator. */
export const DISTRO = 'Ubuntu';

export interface RunRequest {
  tool: ToolExecution['tool'];
  /** The Linux command, e.g. ['yosys', '-s', 'synth.ys']. */
  argv: string[];
  /** Working directory, as a Windows path. */
  dir: string;
  timeoutMs: number;
}

/**
 * Runs one command and always resolves — never rejects. Lane C's loop calls
 * this repeatedly and must always get an object back, even when the tool is
 * missing or hangs.
 */
export function runTool(req: RunRequest): Promise<ToolExecution> {
  const winDir = path.resolve(req.dir);
  const command = ['wsl.exe', '-d', DISTRO, '--cd', winDir, '--', ...req.argv];
  const startedAt = new Date().toISOString();

  return new Promise((resolve) => {
    let stdout = '';
    let stderr = '';
    let timedOut = false;
    let settled = false;

    const finish = (exitCode: number | null): void => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve({
        tool: req.tool,
        command,
        startedAt,
        completedAt: new Date().toISOString(),
        exitCode,
        stdout,
        stderr,
        success: exitCode === 0 && !timedOut,
        timedOut,
      });
    };

    const child = spawn(command[0], command.slice(1), { windowsHide: true });

    const timer = setTimeout(() => {
      timedOut = true;
      child.kill('SIGKILL');
      finish(null);
    }, req.timeoutMs);

    child.stdout.on('data', (chunk: Buffer) => { stdout += chunk.toString(); });
    child.stderr.on('data', (chunk: Buffer) => { stderr += chunk.toString(); });

    // The binary is missing, or wsl.exe itself could not start.
    child.on('error', (err: Error) => {
      stderr += `\n${err.message}`;
      finish(null);
    });

    child.on('close', (code: number | null) => finish(code));
  });
}

/**
 * Infrastructure failures (tool missing, hung) get one retry. A tool that ran
 * and reported bad RTL is a real answer — never retried.
 */
export async function runToolWithRetry(req: RunRequest): Promise<ToolExecution> {
  const first = await runTool(req);
  if (first.success) return first;

  // exitCode === null means the tool never ran or was killed. A real exit code
  // (even a failing one) means the tool worked and is telling us something.
  const infrastructureFailure = first.exitCode === null;
  if (!infrastructureFailure) return first;

  return runTool(req);
}
