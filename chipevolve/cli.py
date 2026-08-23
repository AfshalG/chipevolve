from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from chipevolve.eda.providers import Toolchain
from chipevolve.eda.runner import CommandRunner
from chipevolve.services.config import load_project_config
from chipevolve.services.events import EventBus
from chipevolve.services.evolution import EvolutionService
from chipevolve.storage.repository import Repository


async def run(command: str, root: Path, offline: bool = False) -> int:
    config = load_project_config(root)
    state = root / ".chipevolve"
    repository = Repository(state / "chipevolve.sqlite3")
    service = EvolutionService(config, repository, Toolchain(CommandRunner(state / "logs")), EventBus(), offline=offline)
    if command == "evolve":
        print(f"[chipevolve] mutation agent: {'OFFLINE (canned)' if service.offline else 'codex'}")
    if command == "analyze":
        metrics, verification = await service.establish_baseline(force=True)
        print(metrics.model_dump_json(indent=2) if metrics else verification.model_dump_json(indent=2))
        return 0 if metrics else 1
    if command == "evolve":
        generation = await service.evolve_once()
        print(generation.model_dump_json(indent=2) if generation else "Evolution blocked: baseline failed.")
        return 0 if generation else 1
    if command == "status":
        print(f"Baseline: {repository.get_metrics('baseline') or 'not established'}")
        print(f"Generations: {len(repository.generations())}")
        return 0
    raise ValueError(command)


def main() -> None:
    parser = argparse.ArgumentParser(prog="chipevolve")
    parser.add_argument("command", choices=["analyze", "evolve", "status"])
    parser.add_argument("project", nargs="?", default=".")
    parser.add_argument("--offline", action="store_true",
                        help="Use the canned mutation instead of Codex. Demo fallback only.")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args.command, Path(args.project).resolve(), args.offline)))


if __name__ == "__main__":
    main()
