from __future__ import annotations

import json
import re
import time
from pathlib import Path

from chipevolve.domain.models import Metrics, ProjectConfig, ToolExecution, ToolStatus
from chipevolve.eda.runner import CommandRunner


class Toolchain:
    def __init__(self, runner: CommandRunner) -> None:
        self.runner = runner

    async def status(self) -> dict[str, ToolStatus]:
        tools = {"yosys": "yosys", "verilator": "verilator", "openroad": "openroad"}
        result: dict[str, ToolStatus] = {}
        for label, binary in tools.items():
            available, _ = await self.runner.available(binary)
            result[label] = ToolStatus.CONNECTED if available else ToolStatus.UNAVAILABLE
        result["formal"] = ToolStatus.OPTIONAL
        result["greptile"] = ToolStatus.UNAVAILABLE
        result["engineering_memory"] = ToolStatus.CONNECTED
        return result

    async def lint(self, project: ProjectConfig, workspace: Path) -> ToolExecution:
        # -Wno-fatal would make lint exit 0 on ANY warning, so the gate could
        # never fail. -Wno-UNUSEDSIGNAL is the targeted exclusion the baseline
        # needs: the unused upper bits of mul_result/acc_reg ARE seeded
        # optimization opportunities, not defects.
        command = [
            "verilator", "--lint-only", "-Wall", "-Wno-UNUSEDSIGNAL",
            "--top-module", project.top, *project.rtl,
        ]
        return (await self.runner.run("verilator", command, workspace, timeout=10)).execution

    async def simulate(self, project: ProjectConfig, workspace: Path) -> ToolExecution:
        result = await self.runner.run("verilator", project.testbench_command, workspace, timeout=20)
        return result.execution

    async def synthesize(self, project: ProjectConfig, workspace: Path) -> tuple[Metrics | None, ToolExecution]:
        started = time.monotonic()
        sources = " ".join(project.rtl)
        # Mirrors scripts/synth.ys exactly. A bare `synth -top` produces
        # different cell counts and will not reproduce docs/BASELINE.md
        # (510 cells / 9 registers / depth 18).
        script = (
            f"read_verilog -sv {sources}; "
            f"hierarchy -check -top {project.top}; "
            "proc; opt; fsm; opt; memory; opt; techmap; opt; "
            "abc -g AND,OR,XOR,NAND,NOR,XNOR; opt -purge; "
            "tee -o yosys-stat.json stat -json; "
            "stat; ltp -noff"
        )
        command = ["yosys", "-p", script]
        result = await self.runner.run("yosys", command, workspace, timeout=30)
        if not result.execution.success:
            return None, result.execution
        stat_path = workspace / "yosys-stat.json"
        try:
            payload = json.loads(stat_path.read_text(encoding="utf-8"))
            top_key = project.top if project.top in payload.get("modules", {}) else f"\\{project.top}"
            module = payload["modules"][top_key]
            cells = int(module.get("num_cells", 0))
            area = module.get("area")
            metrics = Metrics(
                area_um2=float(area) if area is not None else None,
                cell_count=cells,
                register_count=_parse_registers(result.stdout),
                logic_depth=_parse_logic_depth(result.stdout),
                runtime_seconds=round(time.monotonic() - started, 3),
            )
            return metrics, result.execution
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            match = re.search(r"Number of cells:\s+(\d+)", result.stdout)
            if not match:
                return None, result.execution
            return Metrics(
                cell_count=int(match.group(1)),
                register_count=_parse_registers(result.stdout),
                logic_depth=_parse_logic_depth(result.stdout),
                runtime_seconds=round(time.monotonic() - started, 3),
            ), result.execution



def _parse_logic_depth(stdout: str) -> int | None:
    """Yosys `ltp` prints: `Longest topological path in alu (length=18):`

    This is a topological depth, a PROXY for delay. Never surface it as timing.
    """
    match = re.search(r"Longest topological path in \S+ \(length=(\d+)\)", stdout)
    return int(match.group(1)) if match else None


def _parse_registers(stdout: str) -> int | None:
    """Sum every $_DFF_* / $dff row in the `stat` table."""
    rows = re.findall(r"^\s+(\d+)\s+\$_?[Dd][Ff][Ff]\w*\s*$", stdout, re.MULTILINE)
    return sum(int(r) for r in rows) if rows else None
