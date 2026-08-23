/**
 * A way to run Lane B's tools by hand and see what they say.
 *
 *   npm run compile
 *   node out/eda/try-it.js <path to a project folder>
 *
 * The folder needs an rtl/ and a tb/ inside it — see examples/alu.
 */

import { runVerilator } from './verilator';
import { runYosys } from './yosys';
import { checkAvailability } from './availability';

async function main(): Promise<void> {
  const dir = process.argv[2];
  if (!dir) {
    console.log('Usage: node out/eda/try-it.js <project folder>');
    process.exit(1);
  }

  console.log('Are the tools installed?');
  console.log(' ', await checkAvailability(), '\n');

  console.log('Does the design still work?');
  const { result } = await runVerilator(dir);
  console.log('  lint passed:      ', result.lintPassed);
  console.log('  simulation passed:', result.simulationPassed);
  console.log('  tests:            ', result.testsPassed, '/', result.testsTotal);
  if (result.failureReason) {
    console.log('  why it failed:    ', result.failureReason);
  }

  console.log('\nHow big is it?');
  const { metrics } = await runYosys(dir);
  console.log('  gates (cellCount):', metrics.cellCount);
  console.log('  flip-flops:       ', metrics.registerCount);
  console.log('  logic depth:      ', metrics.logicDepth, '(a rough speed estimate, not a timing number)');
  console.log('  area:             ', metrics.areaUm2, '(always null — we do not measure this)');
  console.log('  took:             ', metrics.runtimeSeconds, 'seconds');
}

main();
