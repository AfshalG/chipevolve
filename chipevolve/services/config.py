from __future__ import annotations

import shlex
from pathlib import Path

import yaml

from chipevolve.domain.models import ProjectConfig


def load_project_config(root: Path) -> ProjectConfig:
    config_path = root / "project.yaml"
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    project = raw["project"]
    testbench = raw.get("testbench", {})
    clock = raw.get("clock", {})
    optimization = raw.get("optimization", {})
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
        mutable=list(raw.get("mutable", ["rtl/**"])),
        protected=list(raw.get("protected", ["tb/**", "constraints/**", "scripts/evaluation/**", "golden/**"])),
    )

