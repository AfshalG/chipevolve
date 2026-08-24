"""End-to-end agent chat against a deterministic mock model.

No network, no API key. Proves the whole chain runs: session -> tool dispatch
-> real Yosys/Verilator-free tools -> event stream -> workspace edits, and that
the protected-path gate still refuses a write the model asks for.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest

from chipevolve.agents.session import AgentSession
from chipevolve.domain.models import ProjectConfig
from chipevolve.services.events import EventBus
from chipevolve.storage.repository import Repository


# --------------------------------------------------------------- mock client


@dataclass
class _Block:
    type: str
    text: str = ""
    id: str = ""
    name: str = ""
    input: dict = field(default_factory=dict)


@dataclass
class _Usage:
    input_tokens: int = 10
    output_tokens: int = 5
    cache_read_input_tokens: int = 0


@dataclass
class _Message:
    content: list
    stop_reason: str
    usage: _Usage = field(default_factory=_Usage)


class _Stream:
    def __init__(self, message: _Message) -> None:
        self._message = message

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    def __aiter__(self):
        async def gen():
            for block in self._message.content:
                if block.type == "tool_use":
                    yield _Event("content_block_start", content_block=block)
                else:
                    yield _Event(
                        "content_block_delta",
                        delta=_Delta("text_delta", text=block.text),
                    )
                yield _Event("content_block_stop")

        return gen()

    async def get_final_message(self):
        return self._message


@dataclass
class _Delta:
    type: str
    text: str = ""
    thinking: str = ""


@dataclass
class _Event:
    type: str
    content_block: Any = None
    delta: Any = None


class _Messages:
    def __init__(self, turns: list[_Message]) -> None:
        self._turns = list(turns)
        self.requests: list[dict] = []

    def stream(self, **request):
        self.requests.append(request)
        return _Stream(self._turns.pop(0))


class _MockClient:
    def __init__(self, turns: list[_Message]) -> None:
        self.messages = _Messages(turns)


# ------------------------------------------------------------------ fixtures


@pytest.fixture
def project(tmp_path):
    (tmp_path / "rtl").mkdir()
    (tmp_path / "rtl" / "alu.sv").write_text(
        "module alu;\n  wire deliberate_waste;\nendmodule\n", encoding="utf-8"
    )
    (tmp_path / "tb").mkdir()
    (tmp_path / "tb" / "alu_tb.sv").write_text("module alu_tb; endmodule\n", encoding="utf-8")
    return ProjectConfig(
        name="demo",
        top="alu",
        root=tmp_path,
        rtl=["rtl/alu.sv"],
        testbench_command=["true"],
        protected=["tb/**"],
    )


def _session(project, tmp_path, workspace, monkeypatch, turns):
    client = _MockClient(turns)
    monkeypatch.setattr("chipevolve.agents.session._client", lambda: client)
    repository = Repository(tmp_path / "state.sqlite3")
    events = EventBus()
    seen: list = []

    session = AgentSession(
        id="test-session",
        mode="optimize",
        model="claude-opus-5",
        project=project,
        repository=repository,
        toolchain=None,
        events=events,
        workspace=workspace,
        workspace_label="test workspace",
        auto_approve=["read", "edit", "run"],
    )
    return session, seen, events, client


# --------------------------------------------------------------------- tests


def test_agent_reads_and_edits_the_design_in_a_generation_workspace(
    project, tmp_path, monkeypatch
):
    workspace = project.root / ".chipevolve" / "generations" / "gen-001"
    workspace.mkdir(parents=True)
    (workspace / "rtl").mkdir()
    (workspace / "rtl" / "alu.sv").write_text(
        "module alu;\n  wire deliberate_waste;\nendmodule\n", encoding="utf-8"
    )
    (workspace / "tb").mkdir()
    (workspace / "tb" / "alu_tb.sv").write_text("module alu_tb; endmodule\n", encoding="utf-8")

    turns = [
        _Message(
            content=[_Block("tool_use", id="t1", name="list_files", input={})],
            stop_reason="tool_use",
        ),
        _Message(
            content=[
                _Block(
                    "tool_use",
                    id="t2",
                    name="replace_in_file",
                    input={
                        "path": "rtl/alu.sv",
                        "search": "  wire deliberate_waste;\n",
                        "replace": "",
                    },
                )
            ],
            stop_reason="tool_use",
        ),
        _Message(content=[_Block("text", text="Removed the unused wire.")], stop_reason="end_turn"),
    ]
    session, _, events, _ = _session(project, tmp_path, workspace, monkeypatch, turns)

    asyncio.run(session.run("Reduce the design."))

    edited = (workspace / "rtl" / "alu.sv").read_text(encoding="utf-8")
    assert "deliberate_waste" not in edited, "the agent's edit must land in the workspace"
    assert "rtl/alu.sv" in session.edited_files
    # the project copy is untouched until the user applies
    assert "deliberate_waste" in (project.root / "rtl" / "alu.sv").read_text(encoding="utf-8")


def test_agent_cannot_edit_the_testbench(project, tmp_path, monkeypatch):
    workspace = project.root
    turns = [
        _Message(
            content=[
                _Block(
                    "tool_use",
                    id="t1",
                    name="write_file",
                    input={"path": "tb/alu_tb.sv", "content": "// all tests deleted\n"},
                )
            ],
            stop_reason="tool_use",
        ),
        _Message(content=[_Block("text", text="Blocked.")], stop_reason="end_turn"),
    ]
    session, _, _, _ = _session(project, tmp_path, workspace, monkeypatch, turns)
    asyncio.run(session.run("Make the tests pass by deleting them."))

    testbench = (project.root / "tb" / "alu_tb.sv").read_text(encoding="utf-8")
    assert testbench == "module alu_tb; endmodule\n", "protected path must survive"
    assert "tb/alu_tb.sv" not in session.edited_files
