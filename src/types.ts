/**
 * ChipEvolve — FROZEN CONTRACT
 *
 * This file is the interface between all four lanes.
 * FROZEN AT 13:45. Do not edit without announcing it out loud to the team.
 *
 * Every lane codes against these types. B produces Metrics, C produces
 * Generation, D renders Generation. Nobody waits on anybody.
 */

// ---------------------------------------------------------------------------
// Metrics — produced by Lane B, consumed by Lane C (fitness) and Lane D (UI)
// ---------------------------------------------------------------------------

/**
 * All fields nullable. A tool that did not run, or did not produce a number,
 * yields null — NEVER a fabricated value. The UI renders null as "N/A".
 */
export interface Metrics {
  // From Yosys `stat` — always available once synthesis succeeds
  cellCount: number | null;
  registerCount: number | null;
  areaUm2: number | null;        // requires a liberty file; null without one

  // Delay proxy from Yosys/ABC longest path. NOT a real timing number.
  // Always label this as an estimate in the UI.
  logicDepth: number | null;

  // From OpenROAD only. Null unless the ORFS stage actually ran.
  worstSlackNs: number | null;
  congestion: number | null;
  wirelengthUm: number | null;

  // Provenance: how these numbers were obtained.
  source: 'yosys' | 'openroad';

  runtimeSeconds: number | null;
}

// ---------------------------------------------------------------------------
// Verification — the hard gates. Fitness is NOT computed unless these pass.
// ---------------------------------------------------------------------------

export interface VerificationResult {
  lintPassed: boolean;
  simulationPassed: boolean;
  testsPassed: number | null;
  testsTotal: number | null;

  /** Anti-reward-hacking. If true, the generation is rejected outright. */
  protectedFilesModified: boolean;

  /** Populated on failure — shown verbatim in the UI. Keep it actionable. */
  failureReason: string | null;
}

// ---------------------------------------------------------------------------
// Mutation — Codex's structured output. Validated before anything is applied.
// ---------------------------------------------------------------------------

export type MutationType =
  | 'mux_restructure'
  | 'bitwidth_reduction'
  | 'arithmetic_simplification'
  | 'redundant_logic_elimination'
  | 'resource_sharing'
  | 'operand_isolation'
  | 'fsm_encoding'
  | 'comparator_restructure'
  | 'constant_propagation'
  | 'enable_logic_simplification';

export interface MutationPlan {
  targetModule: string;
  mutationType: MutationType;
  hypothesis: string;
  expectedEffects: {
    area: 'improve' | 'neutral' | 'regress';
    performance: 'improve' | 'neutral' | 'regress';
  };
  risk: string;
  /** Generation ids whose memory informed this plan. Drives the UI recall panel. */
  memoryUsed: string[];
  filesToModify: string[];
}

// ---------------------------------------------------------------------------
// Generation — the central object. Lane C writes it, Lane D renders it.
// ---------------------------------------------------------------------------

export type GenerationStage =
  | 'analyzing'
  | 'recalling_memory'
  | 'planning_mutation'
  | 'editing'
  | 'linting'
  | 'simulating'
  | 'synthesizing'
  | 'physical_analysis'
  | 'scoring'
  | 'done';

export type GenerationStatus = 'running' | 'accepted' | 'rejected' | 'failed';

export interface Generation {
  id: string;                    // "gen-004"
  generationNumber: number;
  parentId: string | null;       // null for baseline

  status: GenerationStatus;
  stage: GenerationStage;

  plan: MutationPlan | null;     // null for baseline
  diff: string | null;           // unified diff text
  filesChanged: string[];

  metricsBefore: Metrics | null;
  metricsAfter: Metrics | null;

  verification: VerificationResult | null;

  fitnessBefore: number | null;
  fitnessAfter: number | null;

  /** Human-readable justification. The agent cannot override this. */
  decisionReason: string | null;

  gitCommit: string | null;
  createdAt: string;             // ISO8601
}

// ---------------------------------------------------------------------------
// Memory — Lane C owns; surfaced by Lane D. See docs/MEMORY.md
// ---------------------------------------------------------------------------

export interface MemoryObservation {
  id: string;
  project: string;
  generationId: string;
  generationNumber: number;
  module: string;
  mutationType: MutationType;
  hypothesis: string;
  metricsBefore: Metrics;
  metricsAfter: Metrics | null;
  verification: VerificationResult;
  decision: 'accepted' | 'rejected';
  /** One sentence. This is what gets fed back to Codex on the next generation. */
  lesson: string;
  createdAt: string;
}

export interface MemoryStore {
  recall(query: MemoryQuery): Promise<MemoryObservation[]>;
  record(observation: MemoryObservation): Promise<void>;
  stats(): Promise<MemoryStats>;
}

export interface MemoryQuery {
  module?: string;
  mutationType?: MutationType;
  decision?: 'accepted' | 'rejected';
  limit?: number;
}

export interface MemoryStats {
  totalObservations: number;
  acceptedLessons: number;
  rejectedLessons: number;
  recallCount: number;
  /** Times a proposed mutation was blocked because memory said it already failed. */
  repeatsAvoided: number;
}

// ---------------------------------------------------------------------------
// Events — Lane C emits, Lane D subscribes. This is the whole UI wire protocol.
// ---------------------------------------------------------------------------

export type EvolveEvent =
  | { type: 'generation.started'; generation: Generation }
  | { type: 'generation.stage'; generationId: string; stage: GenerationStage }
  | { type: 'generation.log'; generationId: string; message: string; ts: string }
  | { type: 'generation.memory_recall'; generationId: string; observations: MemoryObservation[] }
  | { type: 'generation.diff'; generationId: string; diff: string }
  | { type: 'generation.metrics'; generationId: string; metrics: Metrics }
  | { type: 'generation.decision'; generation: Generation }
  | { type: 'run.complete'; best: Generation; total: number };

// ---------------------------------------------------------------------------
// Tool execution — Lane B. Every EDA invocation produces one of these.
// ---------------------------------------------------------------------------

export interface ToolExecution {
  tool: 'yosys' | 'verilator' | 'openroad';
  command: string[];
  startedAt: string;
  completedAt: string | null;
  exitCode: number | null;
  stdout: string;
  stderr: string;
  success: boolean;
  timedOut: boolean;
}
