from __future__ import annotations

import shutil
from pathlib import Path


class WorkspaceManager:
    def __init__(self, source_root: Path) -> None:
        self.source_root = source_root.resolve()
        self.state_root = self.source_root / ".chipevolve"
        self.generations_root = self.state_root / "generations"
        self.logs_root = self.state_root / "logs"
        self.generations_root.mkdir(parents=True, exist_ok=True)
        self.logs_root.mkdir(parents=True, exist_ok=True)

    def create(self, generation: int, parent: Path | None = None) -> Path:
        destination = self.generations_root / f"gen-{generation:03d}"
        if destination.exists():
            shutil.rmtree(destination)
        source = parent or self.source_root

        def ignore(path: str, names: list[str]) -> set[str]:
            return {name for name in names if name in {".chipevolve", ".git", "__pycache__"}}

        shutil.copytree(source, destination, ignore=ignore)
        return destination

