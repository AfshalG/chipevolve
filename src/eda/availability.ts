/**
 * Lane B — are the tools actually installed?
 *
 * Called once at startup so the UI can say "yosys not found" instead of
 * failing mysteriously on the first generation.
 */

import { runTool } from './run';

/**
 * Generous on purpose. This is usually the first WSL command of the session,
 * and starting the Linux side from cold takes several seconds. A short budget
 * here reports the tools as missing when they are simply still waking up.
 */
const CHECK_TIMEOUT_MS = 20_000;

/** openroad is cut from scope; it is reported so the UI can show it as absent. */
const TOOLS = ['yosys', 'verilator'] as const;

export async function checkAvailability(): Promise<Record<string, boolean>> {
  const found: Record<string, boolean> = { openroad: false };

  // Sequential, not parallel: two cold starts at once race each other.
  for (const tool of TOOLS) {
    const exec = await runTool({
      tool,
      dir: process.cwd(),
      timeoutMs: CHECK_TIMEOUT_MS,
      argv: ['which', tool],
    });
    found[tool] = exec.success;
  }

  return found;
}
