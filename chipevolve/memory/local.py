from __future__ import annotations

from chipevolve.domain.models import MemoryObservation, MemoryReference
from chipevolve.storage.repository import Repository


class EngineeringMemory:
    def __init__(self, repository: Repository) -> None:
        self.repository = repository

    def recall(self, mutation_type: str | None = None, limit: int = 5) -> list[MemoryReference]:
        """Recent experiments, newest first.

        mutation_type defaults to None (all types) because recall happens
        BEFORE the mutation is planned — filtering by a type Codex has not
        chosen yet is circular, and leaves memory permanently empty.
        """
        return [
            MemoryReference(
                generation_id=f"gen-{item.generation:03d}",
                summary=item.lesson,
                decision=item.decision,
            )
            for item in self.repository.memories(mutation_type, limit)
        ]

    def record(self, observation: MemoryObservation) -> None:
        self.repository.save_memory(observation)

