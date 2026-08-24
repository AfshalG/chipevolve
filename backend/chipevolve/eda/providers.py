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
        command = ["verilator", "--lint-only", "-Wall", "-Wno-fatal", "--top-module", project.top, *project.rtl]
        return (await self.runner.run("verilator", command, workspace, timeout=project.lint_timeout_s)).execution

    async def simulate(self, project: ProjectConfig, workspace: Path) -> ToolExecution:
        result = await self.runner.run("verilator", project.testbench_command, workspace, timeout=project.simulation_timeout_s)
        return result.execution

    async def synthesize(self, project: ProjectConfig, workspace: Path) -> tuple[Metrics | None, ToolExecution]:
        started = time.monotonic()
        sources = " ".join(project.rtl)
        command = [
            "yosys",
            "-p",
            f"read_verilog -sv {sources}; hierarchy -check -top {project.top}; proc; opt; synth -top {project.top}; tee -o yosys-stat.json stat -json",
        ]
        result = await self.runner.run("yosys", command, workspace, timeout=project.synthesis_timeout_s)
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
                runtime_seconds=round(time.monotonic() - started, 3),
            )
            return metrics, result.execution
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            match = re.search(r"Number of cells:\s+(\d+)", result.stdout)
            if not match:
                return None, result.execution
            return Metrics(cell_count=int(match.group(1)), runtime_seconds=round(time.monotonic() - started, 3)), result.execution

