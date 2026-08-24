from __future__ import annotations

import os
import shlex
from pathlib import Path

import yaml

from chipevolve.domain.models import ProjectConfig


RTL_SUFFIXES = (".sv", ".v")

# Directories that never contain project RTL but can contain hundreds of
# thousands of files. Walking into them turns project discovery into a
# multi-minute scan, and a Linux venv on a Windows share can even raise
# WinError 1920 on its dangling lib64 symlink.
PRUNED_DIRS = frozenset(
    {
        ".chipevolve", ".git", ".hg", ".svn", ".venv", "venv", "env",
        "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache",
        "obj_dir", "dist", "build", "target", "out", ".tox", ".idea", ".vscode",
        "site-packages",
    }
)

MAX_SCANNED_FILES = 20000


def iter_source_files(root: Path, suffixes: tuple[str, ...] | frozenset[str] = RTL_SUFFIXES) -> list[str]:
    """
    Project-relative source paths under `root`, pruning vendor and build trees.

    Uses os.walk so directories can be pruned in place rather than discovered
    and then filtered, and tolerates entries the OS refuses to stat.
    """
    found: list[str] = []
    scanned = 0
    for current, dirnames, filenames in os.walk(root, onerror=lambda _: None, followlinks=False):
        dirnames[:] = [name for name in dirnames if name not in PRUNED_DIRS and not name.startswith(".")]
        for name in filenames:
            scanned += 1
            if scanned > MAX_SCANNED_FILES:
                return sorted(found)
            if not name.lower().endswith(tuple(suffixes)):
                continue
            try:
                relative = (Path(current) / name).relative_to(root)
            except ValueError:
                continue
            found.append(relative.as_posix())
    return sorted(found)


def discover_config(root: Path) -> ProjectConfig:
    """
    Build a usable config for a plain folder that has no project.yaml.

    This is what makes "open any directory and generate RTL into it" work: the
    user should not have to author a project file before writing their first
    module. Synthesis and lint still run; simulation is only wired up if the
    folder already has something that looks like a testbench.
    """
    root = root.resolve()
    sources = iter_source_files(root)
    design = [item for item in sources if not _looks_like_testbench(item)]
    # With no design files there is no top module yet. Leave it blank rather
    # than sanitising the directory name: the agent would otherwise name a
    # generated module after whatever folder happens to be open.
    top = Path(design[0]).stem if design else ""
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

