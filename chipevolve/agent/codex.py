"""Real Codex-backed RTL mutation.

Codex proposes the transformation and edits the RTL. It does NOT decide whether
the result is good — Verilator and Yosys do that, downstream of here.

Invocation uses `codex exec` (verified against codex-cli 0.149.0):

    codex exec -C <workspace> -s workspace-write
               --output-schema <schema> -o <plan.json> --json "<prompt>"

`--output-schema` constrains the model's final response to MutationPlan, so the
plan comes back as validated JSON rather than prose we have to scrape.

Safety is layered deliberately:
  * `-s workspace-write` stops Codex touching anything outside the generation dir
  * `files_to_modify` is intersected with the project's mutable globs HERE,
    before any patch is trusted
  * integrity.py re-hashes protected files downstream regardless of both of the
    above — the testbench lives inside the sandbox, so the sandbox alone is not
    a sufficient defense against reward hacking.
"""

from __future__ import annotations

import asyncio
import fnmatch
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from chipevolve.domain.models import MemoryReference, Metrics, MutationPlan, ProjectConfig

SCHEMA_PATH = Path(__file__).with_name("mutation_plan.schema.json")

DEFAULT_TIMEOUT = 420


class CodexUnavailable(RuntimeError):
    """Codex CLI missing, unauthenticated, or it failed to produce a plan."""


@dataclass(frozen=True)
class MutationResult:
    plan: MutationPlan
    changed_files: list[str]


def codex_available() -> bool:
    return shutil.which("codex") is not None


def _build_prompt(
    project: ProjectConfig,
    rtl_source: str,
    rtl_path: str,
    metrics: Metrics,
    recalls: list[MemoryReference],
    dead_ends: list[str] | None = None,
) -> str:
    if recalls:
        lessons = "\n".join(f"  - [{item.generation_id}] {item.summary}" for item in recalls)
        memory_block = (
            "Prior experiments on this design. Do NOT repeat a transformation that\n"
            "already regressed — propose something different instead:\n" + lessons
        )
    else:
        memory_block = "No prior experiments recorded yet. This is the first generation."

    if dead_ends:
        banned = "\n".join(f"  - {name}" for name in sorted(set(dead_ends)))
        memory_block += (
            "\n\nALREADY MEASURED, PRODUCED ZERO IMPROVEMENT. Proposing any of these\n"
            "will be rejected by the engine before it is even measured:\n" + banned +
            "\n\nPick a DIFFERENT transformation. Look at the operation decode, the\n"
            "duplicated adder, and the unconditionally-evaluated multiplier."
        )

    return f"""You are ChipEvolve's RTL optimization agent.

Your goal: make ONE focused, technically justified transformation to the RTL
below that reduces synthesized cell count and/or logic depth, while preserving
functional behaviour exactly.

You do NOT determine whether you succeeded. After your edit, Verilator will run
lint and a 230-vector testbench, and Yosys will synthesize the result. The
measured numbers decide whether your change is kept or reverted. An edit that
breaks the testbench is worthless no matter how much smaller it is.

CURRENT MEASURED METRICS (from real synthesis):
  cell count    : {metrics.cell_count}
  register count: {metrics.register_count}
  logic depth   : {metrics.logic_depth}   (longest topological path)

{memory_block}

FILE YOU MAY EDIT: {rtl_path}
```systemverilog
{rtl_source}
```

RULES — violating any of these fails the generation:
  * Edit ONLY {rtl_path}. Do not touch the testbench, constraints, or scripts.
  * Make ONE conceptual transformation, not a broad rewrite.
  * Preserve the module port list and behaviour for every opcode.
  * Do not delete assertions, weaken checks, or modify anything under tb/.

Apply your edit directly to the file, then return the mutation plan as JSON
matching the required schema. `files_to_modify` must list exactly the files you
actually changed.
"""


def _validate_paths(plan: MutationPlan, project: ProjectConfig) -> None:
    """Reject a plan that targets anything outside the mutable globs."""
    for candidate in plan.files_to_modify:
        normalized = candidate.replace("\\", "/").lstrip("./")
        if not any(fnmatch.fnmatch(normalized, pattern) for pattern in project.mutable):
            raise CodexUnavailable(
                f"Plan targets '{candidate}', which is outside the project's mutable paths "
                f"({', '.join(project.mutable)}). Refusing to trust this mutation."
            )


class CodexMutator:
    def __init__(self, timeout: int = DEFAULT_TIMEOUT, model: str | None = None) -> None:
        self.timeout = timeout
        self.model = model

    async def propose(
        self,
        workspace: Path,
        project: ProjectConfig,
        metrics: Metrics,
        recalls: list[MemoryReference],
        on_log=None,
        dead_ends: list[str] | None = None,
    ) -> MutationResult:
        if not codex_available():
            raise CodexUnavailable("codex CLI not found on PATH. Install it or run with --offline.")

        rtl_path = project.rtl[0]
        source_file = workspace / rtl_path
        if not source_file.exists():
            raise CodexUnavailable(f"RTL file {rtl_path} missing from workspace {workspace}")

        before = source_file.read_text(encoding="utf-8")
        prompt = _build_prompt(project, before, rtl_path, metrics, recalls, dead_ends)

        plan, _ = await self._invoke(workspace, project, prompt, recalls, on_log)
        after = source_file.read_text(encoding="utf-8")
        if after == before:
            raise CodexUnavailable("Codex returned a plan but left the RTL unchanged.")
        return MutationResult(plan=plan, changed_files=plan.files_to_modify)

    async def repair(
        self,
        workspace: Path,
        project: ProjectConfig,
        plan: MutationPlan,
        error_output: str,
        on_log=None,
    ) -> MutationResult:
        """One repair attempt after a failed lint/simulation.

        Codex frequently produces a partially-applied edit — e.g. converting
        half an if/else chain to a case and leaving a dangling `end ... else`.
        Feeding the tool error straight back fixes that class of slip. Exactly
        ONE attempt: an invalid-RTL result is a real experimental outcome, and
        retrying forever would turn the search into a loop.
        """
        rtl_path = project.rtl[0]
        prompt = f"""Your previous edit to {rtl_path} does not compile.

You attempted: {plan.mutation_type} — {plan.hypothesis}

The tool reported:
```
{error_output.strip()[-2000:]}
```

Fix the file so it compiles and behaves identically to the original for every
opcode. Keep the same optimization intent. Do not revert to the original
implementation, and do not touch anything except {rtl_path}.

Then return the mutation plan JSON again, describing the same transformation.
"""
        plan, _ = await self._invoke(workspace, project, prompt, [], on_log)
        return MutationResult(plan=plan, changed_files=plan.files_to_modify)

    async def _invoke(
        self,
        workspace: Path,
        project: ProjectConfig,
        prompt: str,
        recalls: list[MemoryReference],
        on_log,
    ) -> tuple[MutationPlan, str]:
        plan_file = workspace / ".codex-plan.json"
        command = [
            "codex", "exec",
            "-C", str(workspace),
            "-s", "workspace-write",
            "--skip-git-repo-check",
            # Ignore ~/.codex/config.toml. A broken MCP server there (e.g. one
            # returning 401) kills the exec worker before it starts, and every
            # teammate has a different config. Auth still comes from CODEX_HOME.
            "--ignore-user-config",
            "--output-schema", str(SCHEMA_PATH),
            "-o", str(plan_file),
            "--json",
        ]
        if self.model:
            command += ["-m", self.model]
        command.append(prompt)

        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(workspace),
            # DEVNULL is required. codex exec appends piped stdin to the prompt,
            # so an inherited non-TTY stdin makes it block forever waiting for
            # EOF ("Reading additional input from stdin...").
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # Stream JSONL events so the UI shows progress instead of a dead panel.
        errors: list[str] = []

        async def pump() -> None:
            assert process.stdout is not None
            async for raw in process.stdout:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("type") in {"error", "turn.failed"}:
                    errors.append(_extract_error(event))
                    continue
                if on_log is None:
                    continue
                text = _summarize_event(event)
                if text:
                    on_log(text)

        try:
            await asyncio.wait_for(asyncio.gather(pump(), process.wait()), timeout=self.timeout)
        except asyncio.TimeoutError:
            process.kill()
            raise CodexUnavailable(f"Codex exceeded {self.timeout}s and was terminated.")

        if process.returncode != 0:
            if errors:
                raise CodexUnavailable(f"Codex failed: {errors[-1]}")
            stderr = (await process.stderr.read()).decode("utf-8", errors="replace") if process.stderr else ""
            raise CodexUnavailable(f"codex exec exited {process.returncode}: {stderr[-400:]}")

        if not plan_file.exists():
            raise CodexUnavailable("Codex produced no mutation plan.")

        try:
            payload = json.loads(plan_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise CodexUnavailable(f"Mutation plan was not valid JSON: {error}") from error

        payload.setdefault("memory_used", [item.generation_id for item in recalls])
        try:
            plan = MutationPlan.model_validate(payload)
        except Exception as error:  # pydantic ValidationError
            raise CodexUnavailable(f"Mutation plan did not match the schema: {error}") from error

        _validate_paths(plan, project)
        plan_file.unlink(missing_ok=True)
        return plan, prompt


def _summarize_event(event: dict) -> str | None:
    """Turn a Codex JSONL event into one short engineering log line."""
    kind = event.get("type") or event.get("msg", {}).get("type")
    if kind in {"agent_reasoning", "agent_reasoning_delta"}:
        return None
    if kind in {"exec_command_begin", "command_started"}:
        argv = event.get("command") or event.get("msg", {}).get("command") or []
        if isinstance(argv, list) and argv:
            return f"Codex running: {' '.join(str(a) for a in argv[:4])}"
    if kind in {"patch_apply_begin", "apply_patch_begin"}:
        return "Codex editing RTL"
    if kind in {"task_started", "session_configured"}:
        return "Codex analyzing design"
    return None


def _extract_error(event: dict) -> str:
    """Pull a human-readable message out of a Codex error/turn.failed event.

    The payload is often a JSON string nested inside `message`, so unwrap once.
    """
    raw = event.get("message") or event.get("error", {}).get("message") or str(event)
    try:
        inner = json.loads(raw)
        return inner.get("error", {}).get("message") or raw
    except (json.JSONDecodeError, TypeError):
        return str(raw)
