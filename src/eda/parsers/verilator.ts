/**
 * Reading results out of verilator output.
 *
 * The testbench prints a summary line and, on failure, one line per bad case:
 *
 *     FAIL  op=2 a=0x0f b=0x03  expected=0x03  got=0x0f
 *     TESTS: 213/230 PASSED
 *     RESULT: FAILED
 */

export interface TestCounts {
  passed: number;
  total: number;
}

export function parseTestCounts(stdout: string): TestCounts | null {
  const match = /TESTS:\s*(\d+)\/(\d+)\s+PASSED/.exec(stdout);
  if (!match) return null;
  return { passed: Number(match[1]), total: Number(match[2]) };
}

/**
 * First real error line from a lint or build run, e.g.
 *   %Error: rtl/alu.sv:119:1: syntax error, unexpected end of file
 *
 * We want the file and line, because this string is shown to the user verbatim.
 */
export function parseLintError(output: string): string | null {
  const match = /^%(?:Error|Warning)[^\n]*/m.exec(output);
  return match ? match[0].trim() : null;
}

/** First failing test case — the most useful single line we can show. */
export function parseFirstTestFailure(stdout: string): string | null {
  const match = /^\s*FAIL\b[^\n]*/m.exec(stdout);
  return match ? match[0].trim() : null;
}
