/**
 * Reading numbers out of yosys output.
 *
 * Yosys prints the cell name first and the count second:
 *
 *     Number of cells:                521
 *       $_AND_                        167
 *       $_DFF_PN0_                      9
 *       $_NAND_                       191
 *
 * (docs/BASELINE.md has these two regexes the other way round — number first.
 * Those never match. These are checked against real yosys 0.52 output.)
 */

/** Total gate count. This is the main number the whole project optimises. */
export function parseCellCount(stdout: string): number | null {
  const match = /^\s*Number of cells:\s+(\d+)\s*$/m.exec(stdout);
  return match ? Number(match[1]) : null;
}

/**
 * Flip-flops, summed across every DFF variant yosys emits ($_DFF_PN0_,
 * $_SDFF_..., $dff, ...). Zero is a legitimate answer for a design with no
 * registers — but we only report 0 if the stat block was actually present.
 */
export function parseRegisterCount(stdout: string): number | null {
  if (!/^\s*Number of cells:/m.test(stdout)) return null;

  let total = 0;
  const rows = /^\s*(\$\S*[Dd][Ff][Ff]\S*)\s+(\d+)\s*$/gm;
  let row: RegExpExecArray | null;
  while ((row = rows.exec(stdout)) !== null) {
    total += Number(row[2]);
  }
  return total;
}

/**
 * Longest chain of gates a signal passes through, from `ltp -noff`.
 *
 * This is a PROXY for speed, not a timing number. Never label it as timing
 * anywhere that reaches the UI.
 */
export function parseLogicDepth(stdout: string): number | null {
  const match = /Longest topological path in \w+ \(length=(\d+)\)/.exec(stdout);
  return match ? Number(match[1]) : null;
}
