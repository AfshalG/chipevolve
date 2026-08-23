from __future__ import annotations

import difflib
import fnmatch
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from chipevolve.domain.models import (
    MemoryObservation,
    Metrics,
    ProjectConfig,
    VerificationResult,
)
from chipevolve.eda.providers import Toolchain
from chipevolve.memory.local import EngineeringMemory
from chipevolve.scoring.fitness import calculate_fitness
from chipevolve.storage.repository import Repository


READ = "read"
EDIT = "edit"
RUN = "run"


@dataclass
class ToolOutcome:
    """What a tool returns: text for the model, plus a summary the UI can render."""

    text: str
    ok: bool = True
    summary: str = ""
    detail: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolSpec:
    name: str
    description: str
    schema: dict[str, Any]
    approval: str | None
    modes: tuple[str, ...]
    handler: Callable[["ToolContext", dict[str, Any]], Awaitable[ToolOutcome]]

    def definition(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "input_schema": self.schema}


class ProtectedPathError(Exception):
    """Raised when the agent tries to write somewhere the evaluation depends on."""


@dataclass
class ToolContext:
    project: ProjectConfig
    workspace: Path
    repository: Repository
    toolchain: Toolchain
    memory: EngineeringMemory
    # Populated as the agent runs so score_candidate can see real gate results.
    lint_passed: bool | None = None
    simulation_passed: bool | None = None
    synthesis_passed: bool | None = None
    candidate: Metrics | None = None
    findings: list[str] = field(default_factory=list)
    edited_files: list[str] = field(default_factory=list)
    originals: dict[str, str] = field(default_factory=dict)
    protection_violations: list[str] = field(default_factory=list)

    def resolve(self, relative: str, *, for_write: bool) -> Path:
        candidate = (self.workspace / relative).resolve()
        try:
            candidate.relative_to(self.workspace.resolve())
        except ValueError:
            raise ProtectedPathError(f"{relative} escapes the project directory.") from None
        if for_write and self.is_protected(relative):
            self.protection_violations.append(relative)
            raise ProtectedPathError(
                f"{relative} is a protected evaluation path. Tests, constraints, evaluation "
                "scripts, and golden references cannot be modified - change the design instead."
            )
        return candidate

    def is_protected(self, relative: str) -> bool:
        normalized = Path(relative).as_posix()
        for pattern in self.project.protected:
            if fnmatch.fnmatch(normalized, pattern):
                return True
            if fnmatch.fnmatch(normalized, pattern.rstrip("/*") + "/*"):
                return True
        return False

    def verification(self) -> VerificationResult:
        return VerificationResult(
            protected_files_intact=not self.protection_violations,
            lint_passed=self.lint_passed,
            simulation_passed=self.simulation_passed,
            synthesis_passed=self.synthesis_passed,
            findings=list(self.findings),
        )


def _diff(before: str, after: str, path: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(True),
            after.splitlines(True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )


def _tail(text: str, limit: int = 4000) -> str:
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped
    return "...(truncated)...\n" + stripped[-limit:]


def _read_log(path: str | None) -> str:
    if not path:
        return ""
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


# --------------------------------------------------------------------------- read


async def _list_files(ctx: ToolContext, _: dict) -> ToolOutcome:
    keep = {".sv", ".v", ".svh", ".vh", ".sdc", ".yaml", ".yml", ".tcl"}
    rows: list[str] = []
    for path in sorted(ctx.workspace.rglob("*")):
        if not path.is_file() or ".chipevolve" in path.parts or ".git" in path.parts:
            continue
        if path.suffix not in keep:
            continue
        relative = path.relative_to(ctx.workspace).as_posix()
        if ctx.is_protected(relative):
            role = "protected"
        elif relative in ctx.project.rtl:
            role = "rtl"
        else:
            role = "editable"
        rows.append(f"{relative}  [{role}]  {path.stat().st_size} bytes")
    return ToolOutcome(text="\n".join(rows) or "No source files found.", summary=f"{len(rows)} files")


async def _read_file(ctx: ToolContext, args: dict) -> ToolOutcome:
    relative = args["path"]
    path = ctx.resolve(relative, for_write=False)
    if not path.is_file():
        return ToolOutcome(text=f"{relative} does not exist.", ok=False, summary="not found")
    content = path.read_text(encoding="utf-8")
    numbered = "\n".join(f"{i:4d} | {line}" for i, line in enumerate(content.splitlines(), 1))
    return ToolOutcome(
        text=f"{relative}\n{numbered}",
        summary=f"{len(content.splitlines())} lines",
        detail=content,
        meta={"path": relative},
    )


async def _search_rtl(ctx: ToolContext, args: dict) -> ToolOutcome:
    pattern = args["pattern"]
    try:
        regex = re.compile(pattern)
    except re.error as error:
        return ToolOutcome(text=f"Invalid regex: {error}", ok=False, summary="bad pattern")
    hits: list[str] = []
    for relative in ctx.project.rtl:
        path = ctx.workspace / relative
        if not path.is_file():
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if regex.search(line):
                hits.append(f"{relative}:{number}: {line.strip()}")
    body = "\n".join(hits) if hits else f"No match for {pattern} in the RTL sources."
    return ToolOutcome(text=body, summary=f"{len(hits)} matches", meta={"pattern": pattern})


async def _get_metrics(ctx: ToolContext, _: dict) -> ToolOutcome:
    baseline = ctx.repository.get_metrics("baseline")
    best = ctx.repository.get_metrics("best")
    if baseline is None:
        return ToolOutcome(
            text="No baseline has been measured yet. Run synthesis to establish one before scoring.",
            summary="no baseline",
        )
    lines = ["baseline: " + baseline.model_dump_json(exclude_none=True)]
    if best is not None:
        lines.append("best so far: " + best.model_dump_json(exclude_none=True))
    lines.append(f"objective profile: {ctx.project.objective}")
    return ToolOutcome(
        text="\n".join(lines),
        summary="metrics loaded",
        meta={"baseline": baseline.model_dump(), "best": best.model_dump() if best else None},
    )


async def _recall_memories(ctx: ToolContext, args: dict) -> ToolOutcome:
    query = args.get("mutation_type") or ""
    observations = ctx.repository.memories(query or None, limit=int(args.get("limit", 5)))
    if not observations:
        subject = query or "any transformation"
        return ToolOutcome(
            text=f"No prior experiments recorded for {subject}. This is new ground.",
            summary="0 recalls",
        )
    rows = [
        f"gen-{item.generation:03d} - {item.mutation_type} - {item.decision.upper()}\n"
        f"  hypothesis: {item.hypothesis}\n"
        f"  lesson: {item.lesson}"
        for item in observations
    ]
    return ToolOutcome(
        text="\n".join(rows),
        summary=f"{len(observations)} prior experiments",
        meta={"memories": [item.model_dump(mode="json") for item in observations]},
    )


# --------------------------------------------------------------------------- edit


async def _write_file(ctx: ToolContext, args: dict) -> ToolOutcome:
    relative, content = args["path"], args["content"]
    path = ctx.resolve(relative, for_write=True)
    before = path.read_text(encoding="utf-8") if path.is_file() else ""
    ctx.originals.setdefault(relative, before)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if relative not in ctx.edited_files:
        ctx.edited_files.append(relative)
    verb = "Created" if not before else "Rewrote"
    diff = _diff(before, content, relative)
    return ToolOutcome(
        text=f"{verb} {relative} ({len(content.splitlines())} lines).",
        summary=f"{verb.lower()} {relative}",
        detail=diff,
        meta={"path": relative, "diff": diff},
    )


async def _replace_in_file(ctx: ToolContext, args: dict) -> ToolOutcome:
    relative, search, replace = args["path"], args["search"], args["replace"]
    path = ctx.resolve(relative, for_write=True)
    if not path.is_file():
        return ToolOutcome(text=f"{relative} does not exist.", ok=False, summary="not found")
    before = path.read_text(encoding="utf-8")
    occurrences = before.count(search)
    if occurrences == 0:
        return ToolOutcome(
            text=(
                f"The search block was not found in {relative}. Re-read the file and copy the "
                "exact text, including indentation, rather than retyping it."
            ),
            ok=False,
            summary="anchor not found",
        )
    if occurrences > 1:
        return ToolOutcome(
            text=(
                f"The search block matches {occurrences} places in {relative}. Extend it with "
                "surrounding lines so it identifies exactly one location."
            ),
            ok=False,
            summary=f"{occurrences} ambiguous matches",
        )
    after = before.replace(search, replace, 1)
    ctx.originals.setdefault(relative, before)
    path.write_text(after, encoding="utf-8")
    if relative not in ctx.edited_files:
        ctx.edited_files.append(relative)
    diff = _diff(before, after, relative)
    added = sum(1 for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in diff.splitlines() if line.startswith("-") and not line.startswith("---"))
    return ToolOutcome(
        text=f"Applied edit to {relative}: +{added} / -{removed} lines.\n{diff}",
        summary=f"+{added} -{removed} in {relative}",
        detail=diff,
        meta={"path": relative, "diff": diff, "added": added, "removed": removed},
    )


# ---------------------------------------------------------------------------- run


async def _run_lint(ctx: ToolContext, _: dict) -> ToolOutcome:
    execution = await ctx.toolchain.lint(ctx.project, ctx.workspace)
    if execution.unavailable_reason:
        ctx.lint_passed = None
        return ToolOutcome(
            text=f"Verilator is unavailable: {execution.unavailable_reason}",
            ok=False,
            summary="verilator unavailable",
        )
    ctx.lint_passed = execution.success
    output = _tail(_read_log(execution.stderr_path) or _read_log(execution.stdout_path))
    verdict = "Lint passed." if execution.success else "Lint failed."
    return ToolOutcome(
        text=f"{verdict}\n{output or '(no diagnostics)'}",
        ok=execution.success,
        summary=verdict,
        detail=output,
        meta={"exit_code": execution.exit_code},
    )


async def _run_simulation(ctx: ToolContext, _: dict) -> ToolOutcome:
    execution = await ctx.toolchain.simulate(ctx.project, ctx.workspace)
    if execution.unavailable_reason:
        ctx.simulation_passed = None
        return ToolOutcome(
            text=f"Simulator is unavailable: {execution.unavailable_reason}",
            ok=False,
            summary="simulator unavailable",
        )
    ctx.simulation_passed = execution.success
    output = _tail(_read_log(execution.stdout_path) or _read_log(execution.stderr_path))
    verdict = "Testbench passed." if execution.success else "Testbench FAILED."
    return ToolOutcome(
        text=f"{verdict}\n{output or '(no output)'}",
        ok=execution.success,
        summary=verdict,
        detail=output,
        meta={"exit_code": execution.exit_code},
    )


async def _run_synthesis(ctx: ToolContext, _: dict) -> ToolOutcome:
    metrics, execution = await ctx.toolchain.synthesize(ctx.project, ctx.workspace)
    if execution.unavailable_reason:
        ctx.synthesis_passed = None
        return ToolOutcome(
            text=f"Yosys is unavailable: {execution.unavailable_reason}",
            ok=False,
            summary="yosys unavailable",
        )
    ctx.synthesis_passed = execution.success and metrics is not None
    ctx.candidate = metrics
    if metrics is None:
        output = _tail(_read_log(execution.stderr_path) or _read_log(execution.stdout_path))
        return ToolOutcome(
            text=f"Synthesis failed; no metrics were produced.\n{output}",
            ok=False,
            summary="synthesis failed",
            detail=output,
        )
    baseline = ctx.repository.get_metrics("baseline")
    delta = ""
    if baseline and baseline.cell_count and metrics.cell_count:
        change = (metrics.cell_count - baseline.cell_count) / baseline.cell_count * 100
        delta = f" ({change:+.1f}% vs baseline)"
    return ToolOutcome(
        text=f"Synthesis succeeded. {metrics.model_dump_json(exclude_none=True)}{delta}",
        summary=f"{metrics.cell_count} cells{delta}",
        meta={"metrics": metrics.model_dump(), "baseline": baseline.model_dump() if baseline else None},
    )


# ------------------------------------------------------------------------ scoring


async def _score_candidate(ctx: ToolContext, _: dict) -> ToolOutcome:
    baseline = ctx.repository.get_metrics("best") or ctx.repository.get_metrics("baseline")
    if baseline is None:
        return ToolOutcome(
            text="There is no measured baseline to score against. Establish one first.",
            ok=False,
            summary="no baseline",
        )
    if ctx.candidate is None:
        return ToolOutcome(
            text="No candidate metrics exist yet. Run synthesis before asking for a score.",
            ok=False,
            summary="no candidate",
        )
    verification = ctx.verification()
    fitness = calculate_fitness(baseline, ctx.candidate, verification, ctx.project.objective)
    accepted = bool(fitness.valid and fitness.candidate_cost is not None and fitness.candidate_cost < 1.0)
    if accepted:
        ctx.repository.set_metrics("best", ctx.candidate)
    lines = [
        f"decision: {'ACCEPTED' if accepted else 'REJECTED'}",
        f"reason: {fitness.reason}",
        f"protected files intact: {verification.protected_files_intact}",
        f"lint: {verification.lint_passed} / simulation: {verification.simulation_passed} "
        f"/ synthesis: {verification.synthesis_passed}",
    ]
    if fitness.improvement_percent is not None:
        lines.append(f"measured fitness change: {fitness.improvement_percent:+.2f}%")
    if fitness.ratios:
        lines.append("ratios: " + ", ".join(f"{k} {v:.4f}" for k, v in fitness.ratios.items()))
    if fitness.improvement_percent is not None:
        headline = ("ACCEPTED " if accepted else "REJECTED ") + f"{fitness.improvement_percent:+.2f}%"
    else:
        headline = ("ACCEPTED " if accepted else "REJECTED ") + fitness.reason
    return ToolOutcome(
        text="\n".join(lines),
        ok=accepted,
        summary=headline,
        meta={
            "accepted": accepted,
            "fitness": fitness.model_dump(),
            "verification": verification.model_dump(),
            "candidate": ctx.candidate.model_dump(),
            "baseline": baseline.model_dump(),
        },
    )


async def _record_experiment(ctx: ToolContext, args: dict) -> ToolOutcome:
    baseline = ctx.repository.get_metrics("baseline") or Metrics()
    generation = max((item.generation_number for item in ctx.repository.generations()), default=0)
    observation = MemoryObservation(
        project=ctx.project.name,
        generation=generation,
        module=args.get("module", ctx.project.top),
        objective=ctx.project.objective,
        hypothesis=args["hypothesis"],
        mutation_type=args["mutation_type"],
        files_changed=list(ctx.edited_files),
        baseline=baseline,
        candidate=ctx.candidate,
        verification=ctx.verification(),
        decision=args["decision"],
        lesson=args["lesson"],
    )
    ctx.memory.record(observation)
    return ToolOutcome(
        text=f"Recorded {args['mutation_type']} as {args['decision']}.",
        summary=f"remembered - {args['decision']}",
        meta={"observation": observation.model_dump(mode="json")},
    )


async def _report_findings(ctx: ToolContext, args: dict) -> ToolOutcome:
    findings = list(args.get("findings", []))
    ctx.findings = [f"{item['severity']}: {item['title']}" for item in findings]
    if not findings:
        return ToolOutcome(text="Recorded a clean review with no findings.", summary="no findings")
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    findings.sort(key=lambda item: order.get(item.get("severity", "low"), 4))
    counts: dict[str, int] = {}
    for item in findings:
        severity = item.get("severity", "low")
        counts[severity] = counts.get(severity, 0) + 1
    summary = ", ".join(f"{count} {severity}" for severity, count in counts.items())
    return ToolOutcome(
        text=f"Recorded {len(findings)} findings ({summary}).",
        summary=f"{len(findings)} findings - {summary}",
        meta={"findings": findings},
    )


# ------------------------------------------------------------------------ registry

_PATH = {"type": "string", "description": "Project-relative path, e.g. rtl/alu.sv"}

SPECS: list[ToolSpec] = [
    ToolSpec(
        name="list_files",
        description="List the project's source files with their role: rtl, editable, or protected.",
        schema={"type": "object", "properties": {}, "required": []},
        approval=READ,
        modes=("generate", "review", "optimize"),
        handler=_list_files,
    ),
    ToolSpec(
        name="read_file",
        description="Read a file with line numbers. Read before editing.",
        schema={"type": "object", "properties": {"path": _PATH}, "required": ["path"]},
        approval=READ,
        modes=("generate", "review", "optimize"),
        handler=_read_file,
    ),
    ToolSpec(
        name="search_rtl",
        description="Regex search across the declared RTL sources. Returns path:line matches.",
        schema={
            "type": "object",
            "properties": {"pattern": {"type": "string", "description": "Python regular expression"}},
            "required": ["pattern"],
        },
        approval=READ,
        modes=("generate", "review", "optimize"),
        handler=_search_rtl,
    ),
    ToolSpec(
        name="get_metrics",
        description="Measured baseline and best-so-far PPA metrics for this project.",
        schema={"type": "object", "properties": {}, "required": []},
        approval=None,
        modes=("generate", "review", "optimize"),
        handler=_get_metrics,
    ),
    ToolSpec(
        name="recall_memories",
        description=(
            "Recall prior experiments on this design. Call before proposing a transformation so "
            "you do not repeat one that was already measured and rejected."
        ),
        schema={
            "type": "object",
            "properties": {
                "mutation_type": {
                    "type": "string",
                    "description": "Transformation category to filter by, e.g. mux_restructure. Omit for all.",
                },
                "limit": {"type": "integer", "description": "Maximum experiments to return (default 5)."},
            },
            "required": [],
        },
        approval=None,
        modes=("review", "optimize"),
        handler=_recall_memories,
    ),
    ToolSpec(
        name="write_file",
        description=(
            "Create a new file or fully replace one. Use for new modules; prefer replace_in_file "
            "when changing existing code."
        ),
        schema={
            "type": "object",
            "properties": {"path": _PATH, "content": {"type": "string", "description": "Complete file contents"}},
            "required": ["path", "content"],
        },
        approval=EDIT,
        modes=("generate", "optimize"),
        handler=_write_file,
    ),
    ToolSpec(
        name="replace_in_file",
        description=(
            "Replace one exact block of text in a file. The search text must appear exactly once "
            "and must be copied verbatim from a read_file result, indentation included."
        ),
        schema={
            "type": "object",
            "properties": {
                "path": _PATH,
                "search": {"type": "string", "description": "Exact existing text to replace"},
                "replace": {"type": "string", "description": "Replacement text"},
            },
            "required": ["path", "search", "replace"],
        },
        approval=EDIT,
        modes=("generate", "optimize"),
        handler=_replace_in_file,
    ),
    ToolSpec(
        name="run_lint",
        description="Run Verilator lint over the RTL. Authoritative on syntax and structural warnings.",
        schema={"type": "object", "properties": {}, "required": []},
        approval=RUN,
        modes=("generate", "review", "optimize"),
        handler=_run_lint,
    ),
    ToolSpec(
        name="run_simulation",
        description="Run the project's testbench. Authoritative on functional correctness.",
        schema={"type": "object", "properties": {}, "required": []},
        approval=RUN,
        modes=("generate", "optimize"),
        handler=_run_simulation,
    ),
    ToolSpec(
        name="run_synthesis",
        description="Synthesize with Yosys and return measured cell count and area.",
        schema={"type": "object", "properties": {}, "required": []},
        approval=RUN,
        modes=("generate", "review", "optimize"),
        handler=_run_synthesis,
    ),
    ToolSpec(
        name="score_candidate",
        description=(
            "Apply the deterministic hard gates and fitness function to the synthesized candidate. "
            "This decides accept or reject - you do not."
        ),
        schema={"type": "object", "properties": {}, "required": []},
        approval=None,
        modes=("optimize",),
        handler=_score_candidate,
    ),
    ToolSpec(
        name="record_experiment",
        description="Write this generation's hypothesis, outcome, and lesson into engineering memory.",
        schema={
            "type": "object",
            "properties": {
                "module": {"type": "string"},
                "mutation_type": {
                    "type": "string",
                    "description": "Transformation category, e.g. mux_restructure",
                },
                "hypothesis": {"type": "string"},
                "decision": {"type": "string", "enum": ["accepted", "rejected", "failed"]},
                "lesson": {"type": "string", "description": "What a future generation should take from this."},
            },
            "required": ["mutation_type", "hypothesis", "decision", "lesson"],
        },
        approval=None,
        modes=("optimize",),
        handler=_record_experiment,
    ),
    ToolSpec(
        name="report_findings",
        description="Submit the structured review findings. Call exactly once, at the end of a review.",
        schema={
            "type": "object",
            "properties": {
                "findings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "severity": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
                            "title": {"type": "string", "description": "One line, states the defect"},
                            "path": _PATH,
                            "line": {"type": "integer"},
                            "detail": {"type": "string", "description": "Why it is wrong and what it costs"},
                            "suggestion": {"type": "string", "description": "The concrete fix"},
                        },
                        "required": ["severity", "title", "path", "detail"],
                    },
                }
            },
            "required": ["findings"],
        },
        approval=None,
        modes=("review",),
        handler=_report_findings,
    ),
]

BY_NAME = {spec.name: spec for spec in SPECS}


def definitions_for(mode: str) -> list[dict[str, Any]]:
    return [spec.definition() for spec in SPECS if mode in spec.modes]
