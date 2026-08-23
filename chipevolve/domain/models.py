from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class GenerationStage(str, Enum):
    IDLE = "idle"
    ANALYZING = "analyzing"
    RECALLING_MEMORY = "recalling_memory"
    PLANNING_MUTATION = "planning_mutation"
    EDITING = "editing"
    REVIEWING = "reviewing"
    LINTING = "linting"
    SIMULATING = "simulating"
    SYNTHESIZING = "synthesizing"
    PHYSICAL_ANALYSIS = "physical_analysis"
    SCORING = "scoring"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    FAILED = "failed"
    MEMORIZING = "memorizing"
    COMPLETE = "complete"


class GenerationStatus(str, Enum):
    RUNNING = "running"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    FAILED = "failed"


class ToolStatus(str, Enum):
    CONNECTED = "connected"
    UNAVAILABLE = "unavailable"
    OPTIONAL = "optional"


class Metrics(BaseModel):
    power_mw: float | None = None
    area_um2: float | None = None
    cell_count: int | None = None
    register_count: int | None = None
    # Longest topological path from Yosys `ltp`. A PROXY for delay, not timing.
    # Used as the delay term whenever no real fmax is available.
    logic_depth: int | None = None
    worst_slack_ns: float | None = None
    total_negative_slack_ns: float | None = None
    fmax_mhz: float | None = None
    congestion: float | None = None
    wirelength: float | None = None
    runtime_seconds: float | None = None


class VerificationResult(BaseModel):
    protected_files_intact: bool = True
    lint_passed: bool | None = None
    simulation_passed: bool | None = None
    synthesis_passed: bool | None = None
    equivalence_passed: bool | None = None
    findings: list[str] = Field(default_factory=list)

    @property
    def hard_gates_passed(self) -> bool:
        required = (self.protected_files_intact, self.lint_passed, self.simulation_passed, self.synthesis_passed)
        return all(value is True for value in required)


class ToolExecution(BaseModel):
    tool: str
    command: list[str]
    started_at: datetime
    completed_at: datetime | None = None
    exit_code: int | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None
    success: bool = False
    unavailable_reason: str | None = None


class MutationPlan(BaseModel):
    target_module: str
    mutation_type: str
    hypothesis: str
    expected_effects: dict[str, str]
    risk: str
    memory_used: list[str] = Field(default_factory=list)
    files_to_modify: list[str]


class MemoryReference(BaseModel):
    generation_id: str
    summary: str
    decision: str


class MemoryObservation(BaseModel):
    project: str
    generation: int
    module: str
    objective: str
    hypothesis: str
    mutation_type: str
    files_changed: list[str]
    baseline: Metrics
    candidate: Metrics | None
    verification: VerificationResult
    decision: str
    lesson: str
    created_at: datetime = Field(default_factory=utc_now)


class FitnessResult(BaseModel):
    valid: bool
    baseline_cost: float = 1.0
    candidate_cost: float | None = None
    improvement_percent: float | None = None
    ratios: dict[str, float] = Field(default_factory=dict)
    reason: str


class Generation(BaseModel):
    # "codex" or "offline" — surfaced in the UI so a canned run is never
    # mistaken for a real one.
    agent: str = "codex"
    id: str
    generation_number: int
    parent_id: str | None = None
    status: GenerationStatus = GenerationStatus.RUNNING
    stage: GenerationStage = GenerationStage.IDLE
    hypothesis: str
    mutation_type: str
    rationale: str
    files_changed: list[str] = Field(default_factory=list)
    metrics_before: Metrics
    metrics_after: Metrics | None = None
    verification: VerificationResult = Field(default_factory=VerificationResult)
    memory_refs: list[MemoryReference] = Field(default_factory=list)
    fitness: FitnessResult | None = None
    decision_reason: str | None = None
    diff: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ObjectiveWeights(BaseModel):
    power: float = 0.30
    area: float = 0.30
    delay: float = 0.25
    congestion: float = 0.15

    @model_validator(mode="after")
    def weights_sum_to_one(self) -> "ObjectiveWeights":
        if abs(sum((self.power, self.area, self.delay, self.congestion)) - 1.0) > 1e-6:
            raise ValueError("objective weights must sum to 1.0")
        return self


class ProjectConfig(BaseModel):
    name: str
    top: str
    root: Path
    rtl: list[str]
    testbench_command: list[str]
    clock_name: str = "clk"
    clock_period_ns: float = 10.0
    objective: Literal["balanced", "performance", "low_power", "compact"] = "balanced"
    max_generations: int = Field(default=5, ge=1, le=50)
    # Paths Codex is permitted to edit. Enforced in agent/codex.py before any
    # patch is trusted, independently of the CLI sandbox.
    mutable: list[str] = Field(default_factory=lambda: ["rtl/**"])
    protected: list[str] = Field(default_factory=lambda: ["tb/**", "constraints/**", "scripts/evaluation/**", "golden/**"])


class ProjectSnapshot(BaseModel):
    config: ProjectConfig
    source_files: dict[str, str]
    baseline: Metrics | None = None
    best: Metrics | None = None
    generations: list[Generation] = Field(default_factory=list)
    tool_status: dict[str, ToolStatus] = Field(default_factory=dict)


class EvolutionEvent(BaseModel):
    type: str
    generation: int | None = None
    stage: GenerationStage | None = None
    message: str | None = None
    payload: dict = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=utc_now)
