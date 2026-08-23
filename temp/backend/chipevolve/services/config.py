from __future__ import annotations

import shlex
from pathlib import Path

import yaml

from chipevolve.domain.models import ProjectConfig


RTL_SUFFIXES = (".sv", ".v")


def discover_config(root: Path) -> ProjectConfig:
    """
    Build a usable config for a plain folder that has no project.yaml.

    This is what makes "open any directory and generate RTL into it" work: the
    user should not have to author a project file before writing their first
    module. Synthesis and lint still run; simulation is only wired up if the
    folder already has something that looks like a testbench.
    """
    root = root.resolve()
    sources = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix in RTL_SUFFIXES
        and ".chipevolve" not in path.relative_to(root).parts
        and "obj_dir" not in path.relative_to(root).parts
    )
    design = [item for item in sources if not _looks_like_testbench(item)]
    top = Path(design[0]).stem if design else root.name.replace("-", "_")
    return ProjectConfig(
        name=root.name,
        top=top,
        root=root,
        rtl=design,
        testbench_command=["true"],
        protected=["tb/**", "constraints/**", "scripts/evaluation/**", "golden/**"],
    )


def _looks_like_testbench(relative: str) -> bool:
    lowered = relative.lower()
    return lowered.startswith("tb/") or "_tb." in lowered or lowered.endswith("_tb.sv")


def load_project_config(root: Path) -> ProjectConfig:
    config_path = root / "project.yaml"
    if not config_path.is_file():
        return discover_config(root)
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    project = raw["project"]
    testbench = raw.get("testbench", {})
    clock = raw.get("clock", {})
    optimization = raw.get("optimization", {})
    timeouts = raw.get("timeouts", {})
    command = testbench.get("command", ["make", "test"])
    if isinstance(command, str):
        command = shlex.split(command)
    return ProjectConfig(
        name=project["name"],
        top=project["top"],
        root=root.resolve(),
        rtl=list(raw.get("rtl", [])),
        testbench_command=list(command),
        clock_name=clock.get("name", "clk"),
        clock_period_ns=float(clock.get("period_ns", 10.0)),
        objective=optimization.get("objective", "balanced"),
        max_generations=int(optimization.get("max_generations", 5)),
        protected=list(raw.get("protected", ["tb/**", "constraints/**", "scripts/evaluation/**", "golden/**"])),
        lint_timeout_s=float(timeouts.get("lint_s", 60.0)),
        simulation_timeout_s=float(timeouts.get("simulation_s", 300.0)),
        synthesis_timeout_s=float(timeouts.get("synthesis_s", 180.0)),
    )

