from __future__ import annotations

import asyncio
import inspect
import os
import shutil
import uuid
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from chipevolve.agents import prompts, tools
from chipevolve.agents.tools import ProtectedPathError, ToolContext, ToolOutcome
from chipevolve.domain.models import EvolutionEvent, ProjectConfig
from chipevolve.eda.providers import Toolchain
from chipevolve.memory.local import EngineeringMemory
from chipevolve.services.events import EventBus
from chipevolve.services.workspace import WorkspaceManager
from chipevolve.storage.repository import Repository


DEFAULT_MODEL = "claude-opus-5"
MAX_TOKENS = 64000
MAX_TURNS = 40

# USD per million tokens, used only to show a running cost in the sidebar.
PRICING = {
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}


class AgentUnavailable(RuntimeError):
    """Raised when the Anthropic SDK or an API key is missing."""


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0

    def cost(self, model: str) -> float:
        rate_in, rate_out = PRICING.get(model, PRICING[DEFAULT_MODEL])
        return (self.input_tokens * rate_in + self.output_tokens * rate_out) / 1_000_000


@dataclass
class PendingApproval:
    tool_use_id: str
    name: str
    arguments: dict[str, Any]
    future: asyncio.Future[dict[str, Any]]


@dataclass
class AgentSession:
    """One Cline-style task: a mode, a conversation, and a live tool loop."""

    id: str
    mode: str
    project: ProjectConfig
    repository: Repository
    toolchain: Toolchain
    events: EventBus
    workspace: Path
    workspace_label: str
    model: str = DEFAULT_MODEL
    auto_approve: set[str] = field(default_factory=set)
    messages: list[dict[str, Any]] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    pending: dict[str, PendingApproval] = field(default_factory=dict)
    task: asyncio.Task | None = None
    context: ToolContext | None = None
    # Rendered description of what the user has open in VS Code.
    editor_note: str = ""

    @property
    def edited_files(self) -> list[str]:
        return list(self.context.edited_files) if self.context else []

    # ------------------------------------------------------------------ events

    async def emit(self, type_: str, **payload: Any) -> None:
        await self.events.publish(
            EvolutionEvent(type=type_, message=payload.pop("message", None), payload={"session": self.id, **payload})
        )

    # ------------------------------------------------------------- approvals

    def requires_approval(self, name: str) -> bool:
        spec = tools.BY_NAME.get(name)
        if spec is None or spec.approval is None:
            return False
        return spec.approval not in self.auto_approve

    def resolve_approval(self, tool_use_id: str, approved: bool, feedback: str = "") -> bool:
        entry = self.pending.pop(tool_use_id, None)
        if entry is None or entry.future.done():
            return False
        entry.future.set_result({"approved": approved, "feedback": feedback})
        return True

    async def _await_approval(self, tool_use_id: str, name: str, arguments: dict) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        entry = PendingApproval(tool_use_id, name, arguments, loop.create_future())
        self.pending[tool_use_id] = entry
        await self.emit(
            "chat.approval_required",
            tool_use_id=tool_use_id,
            name=name,
            input=arguments,
            preview=self._preview(name, arguments),
            approval_class=tools.BY_NAME[name].approval,
        )
        try:
            return await entry.future
        except asyncio.CancelledError:
            self.pending.pop(tool_use_id, None)
            raise

    def _preview(self, name: str, arguments: dict) -> dict[str, Any]:
        """Show the user what an edit would do before it is written."""
        if self.context is None or name not in {"write_file", "replace_in_file"}:
            return {}
        relative = arguments.get("path", "")
        try:
            path = self.context.resolve(relative, for_write=False)
        except ProtectedPathError as error:
            return {"error": str(error)}
        before = path.read_text(encoding="utf-8") if path.is_file() else ""
        if name == "write_file":
            after = arguments.get("content", "")
        else:
            search = arguments.get("search", "")
            if before.count(search) != 1:
                return {"path": relative, "error": "search block does not match exactly one location"}
            after = before.replace(search, arguments.get("replace", ""), 1)
        diff = tools._diff(before, after, relative)
        added = sum(1 for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++"))
        removed = sum(1 for line in diff.splitlines() if line.startswith("-") and not line.startswith("---"))
        return {"path": relative, "diff": diff, "added": added, "removed": removed}

    # ----------------------------------------------------------------- tools

    async def _execute(self, name: str, arguments: dict) -> ToolOutcome:
        spec = tools.BY_NAME.get(name)
        if spec is None or self.mode not in spec.modes:
            return ToolOutcome(
                text=f"{name} is not available in {self.mode} mode.", ok=False, summary="tool unavailable"
            )
        assert self.context is not None
        try:
            return await spec.handler(self.context, arguments)
        except ProtectedPathError as error:
            await self.emit("chat.integrity_violation", message=str(error), path=arguments.get("path"))
            return ToolOutcome(text=str(error), ok=False, summary="blocked: protected path")
        except Exception as error:  # a tool crash must not kill the task
            return ToolOutcome(text=f"{name} failed: {error}", ok=False, summary=f"error: {error}")

    # ------------------------------------------------------------------- run

    async def run(self, user_message: str) -> None:
        try:
            client = _client()
        except AgentUnavailable as error:
            await self.emit("chat.error", message=str(error))
            await self.emit("chat.done", reason="error")
            return

        self.context = ToolContext(
            project=self.project,
            workspace=self.workspace,
            repository=self.repository,
            toolchain=self.toolchain,
            memory=EngineeringMemory(self.repository),
        )
        opening = f"{user_message}\n{self.editor_note}" if self.editor_note else user_message
        self.messages.append({"role": "user", "content": opening})
        system = prompts.system_prompt(self.mode, self.project, self.workspace_label)
        definitions = tools.definitions_for(self.mode)

        await self.emit(
            "chat.started",
            mode=self.mode,
            workspace=self.workspace_label,
            workspace_path=str(self.workspace),
            model=self.model,
        )
        try:
            await self._loop(client, system, definitions)
        except asyncio.CancelledError:
            await self.emit("chat.done", reason="cancelled", message="Task cancelled.")
            raise
        except Exception as error:
            await self.emit("chat.error", message=f"{type(error).__name__}: {error}")
            await self.emit("chat.done", reason="error")

    async def _loop(self, client, system: str, definitions: list[dict]) -> None:
        for _ in range(MAX_TURNS):
            final = await self._stream_turn(client, system, definitions)
            self.messages.append({"role": "assistant", "content": final.content})

            if final.stop_reason == "refusal":
                await self.emit("chat.error", message="The model declined this request.")
                await self.emit("chat.done", reason="refusal")
                return
            if final.stop_reason != "tool_use":
                await self.emit(
                    "chat.done",
                    reason=final.stop_reason or "end_turn",
                    edited=self.edited_files,
                    detached=self.workspace != self.project.root,
                )
                return

            results = []
            for block in final.content:
                if block.type != "tool_use":
                    continue
                results.append(await self._handle_tool_use(block))
            self.messages.append({"role": "user", "content": results})

        await self.emit("chat.error", message=f"Stopped after {MAX_TURNS} turns without finishing.")
        await self.emit("chat.done", reason="max_turns")

    async def _stream_turn(self, client, system: str, definitions: list[dict]):
        request: dict[str, Any] = {
            "model": self.model,
            "max_tokens": MAX_TOKENS,
            "system": system,
            "tools": definitions,
            "messages": self.messages,
            "thinking": {"type": "adaptive", "display": "summarized"},
        }
        # output_config (reasoning effort) only exists on newer SDKs; older ones
        # reject the keyword outright, so only send it when it is supported.
        if _supports_output_config(client):
            request["output_config"] = {"effort": "high"}
        async with client.messages.stream(**request) as stream:
            async for event in stream:
                if event.type == "content_block_start" and event.content_block.type == "tool_use":
                    await self.emit("chat.tool_pending", name=event.content_block.name)
                elif event.type == "content_block_delta":
                    if event.delta.type == "text_delta":
                        await self.emit("chat.text", text=event.delta.text)
                    elif event.delta.type == "thinking_delta":
                        await self.emit("chat.thinking", text=event.delta.thinking)
                elif event.type == "content_block_stop":
                    await self.emit("chat.block_end")
            final = await stream.get_final_message()

        self.usage.input_tokens += final.usage.input_tokens or 0
        self.usage.output_tokens += final.usage.output_tokens or 0
        self.usage.cache_read_tokens += getattr(final.usage, "cache_read_input_tokens", 0) or 0
        await self.emit(
            "chat.usage",
            input_tokens=self.usage.input_tokens,
            output_tokens=self.usage.output_tokens,
            cache_read_tokens=self.usage.cache_read_tokens,
            cost_usd=round(self.usage.cost(self.model), 4),
        )
        return final

    async def _handle_tool_use(self, block) -> dict[str, Any]:
        arguments = dict(block.input or {})
        await self.emit("chat.tool_start", tool_use_id=block.id, name=block.name, input=arguments)

        if self.requires_approval(block.name):
            decision = await self._await_approval(block.id, block.name, arguments)
            if not decision["approved"]:
                note = decision.get("feedback") or "The user rejected this action."
                await self.emit(
                    "chat.tool_result", tool_use_id=block.id, name=block.name, ok=False, summary="rejected by user"
                )
                return {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": f"The user rejected this action. {note}",
                    "is_error": True,
                }
            await self.emit("chat.tool_approved", tool_use_id=block.id, name=block.name)

        outcome = await self._execute(block.name, arguments)
        await self.emit(
            "chat.tool_result",
            tool_use_id=block.id,
            name=block.name,
            ok=outcome.ok,
            summary=outcome.summary,
            detail=outcome.detail,
            meta=outcome.meta,
        )
        return {
            "type": "tool_result",
            "tool_use_id": block.id,
            "content": outcome.text or "(no output)",
            "is_error": not outcome.ok,
        }


@lru_cache(maxsize=4)
def _stream_accepts(kind: type, name: str) -> bool:
    try:
        return name in inspect.signature(kind.stream).parameters
    except (TypeError, ValueError):
        return False


def _supports_output_config(client) -> bool:
    return _stream_accepts(type(client.messages), "output_config")


def _client():
    try:
        import anthropic
    except ImportError as error:
        raise AgentUnavailable(
            "The anthropic package is not installed in the backend environment. "
            "Run: pip install 'anthropic>=0.70'"
        ) from error
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        raise AgentUnavailable(
            "No Anthropic credentials found. Set ANTHROPIC_API_KEY in the environment "
            "the backend runs in, or set chipevolve.anthropicApiKey in VS Code settings."
        )
    return anthropic.AsyncAnthropic()


class SessionManager:
    """Owns the live task for a project, Cline-style: one task at a time."""

    def __init__(self, project: ProjectConfig, repository: Repository, toolchain: Toolchain, events: EventBus) -> None:
        self.project = project
        self.repository = repository
        self.toolchain = toolchain
        self.events = events
        self.workspaces = WorkspaceManager(project.root)
        self.current: AgentSession | None = None

    def _workspace_for(self, mode: str) -> tuple[Path, str]:
        if mode != "optimize":
            return self.project.root, "the project working tree"
        existing = self.repository.generations()
        number = max((item.generation_number for item in existing), default=0) + 1
        return self.workspaces.create(number), f"generation workspace gen-{number:03d}"

    async def start(
        self,
        mode: str,
        message: str,
        model: str,
        auto_approve: list[str],
        editor_note: str = "",
    ) -> AgentSession:
        if self.busy:
            raise RuntimeError("A task is already running. Cancel it before starting another.")
        workspace, label = self._workspace_for(mode)
        session = AgentSession(
            id=str(uuid.uuid4()),
            mode=mode,
            project=self.project,
            repository=self.repository,
            toolchain=self.toolchain,
            events=self.events,
            workspace=workspace,
            workspace_label=label,
            model=model or DEFAULT_MODEL,
            auto_approve=set(auto_approve or []),
            editor_note=editor_note,
        )
        self.current = session
        session.task = asyncio.create_task(session.run(message))
        return session

    @property
    def busy(self) -> bool:
        return self.current is not None and self.current.task is not None and not self.current.task.done()

    def approve(self, tool_use_id: str, approved: bool, feedback: str = "") -> bool:
        if self.current is None:
            return False
        return self.current.resolve_approval(tool_use_id, approved, feedback)

    def apply(self) -> list[str]:
        """Copy the finished task's edits out of its generation workspace into the project."""
        if self.busy:
            raise RuntimeError("The task is still running.")
        session = self.current
        if session is None or not session.edited_files:
            return []
        applied: list[str] = []
        for relative in session.edited_files:
            source = session.workspace / relative
            if not source.is_file():
                continue
            destination = self.project.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            applied.append(relative)
        return applied

    async def cancel(self) -> bool:
        if not self.busy or self.current is None or self.current.task is None:
            return False
        self.current.task.cancel()
        try:
            await self.current.task
        except asyncio.CancelledError:
            pass
        return True
