import asyncio

from chipevolve.agents import tools as agent_tools
from chipevolve.domain.models import ProjectConfig


def _context(root, workspace) -> agent_tools.ToolContext:
    """A ToolContext with only the fields _list_files needs.

    Repository/toolchain/memory are required by the dataclass but unused here,
    so None keeps the test focused on path handling.
    """
    config = ProjectConfig(
        name="demo",
        top="alu",
        root=root,
        rtl=["rtl/alu.sv"],
        testbench_command=["true"],
        protected=["tb/**"],
    )
    return agent_tools.ToolContext(
        project=config,
        workspace=workspace,
        repository=None,
        toolchain=None,
        memory=None,
    )


def _project(root) -> None:
    (root / "rtl").mkdir(parents=True)
    (root / "rtl" / "alu.sv").write_text("module alu; endmodule\n", encoding="utf-8")
    (root / "tb").mkdir()
    (root / "tb" / "alu_tb.sv").write_text("module alu_tb; endmodule\n", encoding="utf-8")


def test_list_files_sees_the_design_in_generate_mode(tmp_path) -> None:
    _project(tmp_path)
    outcome = asyncio.run(_list(tmp_path, tmp_path))
    assert "rtl/alu.sv  [rtl]" in outcome.text
    assert "tb/alu_tb.sv  [protected]" in outcome.text


def test_list_files_sees_the_design_inside_a_generation_workspace(tmp_path) -> None:
    """Regression: optimize-mode workspaces live under `.chipevolve/generations/`.

    _list_files filtered on the ABSOLUTE path's parts, so ".chipevolve" matched
    every file in the workspace and the agent was told "No source files found"
    for the very design it was asked to improve.
    """
    workspace = tmp_path / ".chipevolve" / "generations" / "gen-007"
    _project(workspace)
    outcome = asyncio.run(_list(tmp_path, workspace))
    assert "rtl/alu.sv  [rtl]" in outcome.text
    assert "tb/alu_tb.sv  [protected]" in outcome.text
    assert "No source files found." not in outcome.text


def test_list_files_still_hides_nested_state_and_git_directories(tmp_path) -> None:
    """The filter must keep working RELATIVE to the workspace."""
    _project(tmp_path)
    (tmp_path / ".chipevolve" / "generations" / "gen-001" / "rtl").mkdir(parents=True)
    (tmp_path / ".chipevolve" / "generations" / "gen-001" / "rtl" / "alu.sv").write_text("x", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config.yaml").write_text("x", encoding="utf-8")

    outcome = asyncio.run(_list(tmp_path, tmp_path))
    assert ".chipevolve" not in outcome.text
    assert ".git" not in outcome.text


async def _list(root, workspace):
    return await agent_tools._list_files(_context(root, workspace), {})
