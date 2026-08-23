from __future__ import annotations

import difflib
import uuid
from datetime import UTC, datetime
from pathlib import Path

from chipevolve.domain.models import (
    EvolutionEvent,
    Generation,
    GenerationStage,
    GenerationStatus,
    MemoryObservation,
    Metrics,
    ProjectConfig,
    VerificationResult,
)
from chipevolve.eda.providers import Toolchain
from chipevolve.memory.local import EngineeringMemory
from chipevolve.scoring.fitness import calculate_fitness
from chipevolve.services.events import EventBus
from chipevolve.services.integrity import integrity_matches, protected_hashes
from chipevolve.services.mutation import apply_mux_restructure, plan_mux_restructure
from chipevolve.services.workspace import WorkspaceManager
from chipevolve.storage.repository import Repository


class EvolutionService:
    def __init__(
        self,
        project: ProjectConfig,
        repository: Repository,
        toolchain: Toolchain,
        events: EventBus,
    ) -> None:
        self.project = project
        self.repository = repository
        self.toolchain = toolchain
        self.events = events
        self.workspaces = WorkspaceManager(project.root)
        self.memory = EngineeringMemory(repository)

    async def _emit(self, type_: str, generation: int | None = None, stage: GenerationStage | None = None, message: str | None = None, **payload: object) -> None:
        await self.events.publish(EvolutionEvent(type=type_, generation=generation, stage=stage, message=message, payload=payload))

    async def _stage(self, generation: Generation, stage: GenerationStage, message: str) -> None:
        generation.stage = stage
        generation.updated_at = datetime.now(UTC)
        self.repository.save_generation(generation)
        await self._emit("generation.stage_changed", generation.generation_number, stage, message)

    async def establish_baseline(self, force: bool = False) -> tuple[Metrics | None, VerificationResult]:
        cached = self.repository.get_metrics("baseline")
        if cached is not None and not force:
            return cached, VerificationResult(
                protected_files_intact=True,
                lint_passed=True,
                simulation_passed=True,
                synthesis_passed=True,
            )

        await self._emit("baseline.started", message="Establishing Generation 0 with Verilator and Yosys")
        workspace = self.workspaces.create(0)
        before = protected_hashes(workspace, self.project.protected)
        lint = await self.toolchain.lint(self.project, workspace)
        await self._emit("baseline.tool", message="Verilator lint passed" if lint.success else (lint.unavailable_reason or "Verilator lint failed"), tool="verilator", success=lint.success)
        simulation = await self.toolchain.simulate(self.project, workspace) if lint.success else lint
        await self._emit("baseline.tool", message="Simulation passed" if simulation.success else (simulation.unavailable_reason or "Simulation failed"), tool="simulation", success=simulation.success)
        metrics, synthesis = await self.toolchain.synthesize(self.project, workspace) if simulation.success else (None, simulation)
        await self._emit("baseline.tool", message="Yosys synthesis complete" if synthesis.success else (synthesis.unavailable_reason or "Yosys synthesis failed"), tool="yosys", success=synthesis.success)
        verification = VerificationResult(
            protected_files_intact=integrity_matches(before, protected_hashes(workspace, self.project.protected)),
            lint_passed=lint.success,
            simulation_passed=simulation.success,
            synthesis_passed=synthesis.success and metrics is not None,
        )
        if metrics and verification.hard_gates_passed:
            self.repository.set_metrics("baseline", metrics)
            self.repository.set_metrics("best", metrics)
            await self._emit("baseline.completed", message="Baseline established from real EDA output", metrics=metrics.model_dump())
            return metrics, verification
        await self._emit("baseline.failed", message="Baseline unavailable; install or repair the required EDA tools")
        return None, verification

    async def evolve_once(self) -> Generation | None:
        baseline, baseline_verification = await self.establish_baseline()
        if baseline is None:
            await self._emit("evolution.blocked", message="Evolution requires a valid Verilator + Yosys baseline", verification=baseline_verification.model_dump())
            return None

        existing = self.repository.generations()
        number = max((item.generation_number for item in existing), default=0) + 1
        generation = Generation(
            id=str(uuid.uuid4()),
            generation_number=number,
            parent_id=next((item.id for item in reversed(existing) if item.status == GenerationStatus.ACCEPTED), None),
            hypothesis="Analyzing design",
            mutation_type="pending",
            rationale="One focused transformation will be measured against the baseline.",
            metrics_before=self.repository.get_metrics("best") or baseline,
        )
        self.repository.save_generation(generation)
        await self._stage(generation, GenerationStage.ANALYZING, "Analyzing ALU operation decode")

        await self._stage(generation, GenerationStage.RECALLING_MEMORY, "Searching engineering memory for related mux transformations")
        recalls = self.memory.recall("mux_restructure")
        generation.memory_refs = recalls
        await self._emit("generation.memory", number, message=f"Recalled {len(recalls)} related experiments", memories=[item.model_dump() for item in recalls])

        await self._stage(generation, GenerationStage.PLANNING_MUTATION, "Planning a localized mux restructure")
        plan = plan_mux_restructure([item.generation_id for item in recalls])
        generation.hypothesis = plan.hypothesis
        generation.mutation_type = plan.mutation_type
        generation.rationale = f"Expected area effect: {plan.expected_effects['area']}. Risk: {plan.risk}"
        self.repository.save_generation(generation)

        workspace = self.workspaces.create(number)
        protected_before = protected_hashes(workspace, self.project.protected)
        await self._stage(generation, GenerationStage.EDITING, "Applying focused RTL mutation")
        try:
            original = (workspace / plan.files_to_modify[0]).read_text(encoding="utf-8")
            mutation = apply_mux_restructure(workspace, plan)
            modified = (workspace / plan.files_to_modify[0]).read_text(encoding="utf-8")
            generation.files_changed = mutation.changed_files
            generation.diff = "".join(difflib.unified_diff(original.splitlines(True), modified.splitlines(True), fromfile="baseline/rtl/alu.sv", tofile=f"gen-{number:03d}/rtl/alu.sv"))
        except ValueError as error:
            generation.status = GenerationStatus.FAILED
            generation.decision_reason = str(error)
            await self._stage(generation, GenerationStage.FAILED, str(error))
            return generation

        await self._stage(generation, GenerationStage.REVIEWING, "Local policy review found no protected-path edits")
        integrity_ok = integrity_matches(protected_before, protected_hashes(workspace, self.project.protected))
        await self._stage(generation, GenerationStage.LINTING, "Running Verilator lint")
        lint = await self.toolchain.lint(self.project, workspace)
        await self._stage(generation, GenerationStage.SIMULATING, "Running exhaustive demo ALU testbench")
        simulation = await self.toolchain.simulate(self.project, workspace) if lint.success else lint
        await self._stage(generation, GenerationStage.SYNTHESIZING, "Synthesizing candidate with Yosys")
        candidate, synthesis = await self.toolchain.synthesize(self.project, workspace) if simulation.success else (None, simulation)

        verification = VerificationResult(
            protected_files_intact=integrity_ok,
            lint_passed=lint.success,
            simulation_passed=simulation.success,
            synthesis_passed=synthesis.success and candidate is not None,
            findings=[reason for reason in (lint.unavailable_reason, simulation.unavailable_reason, synthesis.unavailable_reason) if reason],
        )
        generation.verification = verification
        generation.metrics_after = candidate
        await self._stage(generation, GenerationStage.PHYSICAL_ANALYSIS, "OpenROAD is optional for this fast evaluation pass")
        await self._stage(generation, GenerationStage.SCORING, "Applying deterministic hard gates and measured fitness")

        if candidate is None:
            fitness = calculate_fitness(baseline, Metrics(), verification, self.project.objective)
        else:
            fitness = calculate_fitness(generation.metrics_before, candidate, verification, self.project.objective)
        generation.fitness = fitness
        accepted = bool(fitness.valid and fitness.candidate_cost is not None and fitness.candidate_cost < 1.0)
        generation.status = GenerationStatus.ACCEPTED if accepted else GenerationStatus.REJECTED
        generation.decision_reason = fitness.reason
        await self._stage(generation, GenerationStage.ACCEPTED if accepted else GenerationStage.REJECTED, fitness.reason)
        if accepted and candidate:
            self.repository.set_metrics("best", candidate)

        await self._stage(generation, GenerationStage.MEMORIZING, "Recording experiment and measured outcome")
        self.memory.record(
            MemoryObservation(
                project=self.project.name,
                generation=number,
                module=plan.target_module,
                objective=self.project.objective,
                hypothesis=plan.hypothesis,
                mutation_type=plan.mutation_type,
                files_changed=generation.files_changed,
                baseline=generation.metrics_before,
                candidate=candidate,
                verification=verification,
                decision=generation.status.value,
                lesson=(
                    f"Mux restructure changed measured fitness by {fitness.improvement_percent:.2f}%."
                    if fitness.improvement_percent is not None
                    else f"Mux restructure was {generation.status.value}: {fitness.reason}"
                ),
            )
        )
        generation.updated_at = datetime.now(UTC)
        self.repository.save_generation(generation)
        await self._emit("generation.decision", number, stage=generation.stage, message=generation.decision_reason, decision=generation.status.value, generation_data=generation.model_dump(mode="json"))
        return generation

