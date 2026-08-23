from __future__ import annotations

from chipevolve.domain.models import MemoryObservation, MemoryReference
from chipevolve.storage.repository import Repository


class EngineeringMemory:
    def __init__(self, repository: Repository) -> None:
        self.repository = repository

    def recall(self, mutation_type: str, limit: int = 3) -> list[MemoryReference]:
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

