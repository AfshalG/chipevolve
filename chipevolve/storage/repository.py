from __future__ import annotations

import sqlite3
from pathlib import Path

from chipevolve.domain.models import Generation, MemoryObservation, Metrics


class Repository:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS generations (
                    id TEXT PRIMARY KEY,
                    generation_number INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    generation_number INTEGER NOT NULL,
                    mutation_type TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS project_state (
                    key TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                );
                """
            )

    def save_generation(self, generation: Generation) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO generations (id, generation_number, status, payload, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET status=excluded.status, payload=excluded.payload, updated_at=excluded.updated_at""",
                (
                    generation.id,
                    generation.generation_number,
                    generation.status.value,
                    generation.model_dump_json(),
                    generation.updated_at.isoformat(),
                ),
            )

    def generations(self) -> list[Generation]:
        with self._connect() as connection:
            rows = connection.execute("SELECT payload FROM generations ORDER BY generation_number").fetchall()
        return [Generation.model_validate_json(row["payload"]) for row in rows]

    def save_memory(self, observation: MemoryObservation) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO memories (generation_number, mutation_type, decision, payload, created_at) VALUES (?, ?, ?, ?, ?)",
                (
                    observation.generation,
                    observation.mutation_type,
                    observation.decision,
                    observation.model_dump_json(),
                    observation.created_at.isoformat(),
                ),
            )

    def memories(self, mutation_type: str | None = None, limit: int = 8) -> list[MemoryObservation]:
        query = "SELECT payload FROM memories"
        params: list[object] = []
        if mutation_type:
            query += " WHERE mutation_type = ?"
            params.append(mutation_type)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [MemoryObservation.model_validate_json(row["payload"]) for row in rows]

    def bump_counter(self, key: str) -> int:
        """Increment a named counter (e.g. repeats_avoided) and return it."""
        current = self.counter(key) + 1
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO project_state (key, payload) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET payload=excluded.payload",
                (f"counter:{key}", str(current)),
            )
        return current

    def counter(self, key: str) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT payload FROM project_state WHERE key = ?", (f"counter:{key}",)).fetchone()
        try:
            return int(row["payload"]) if row else 0
        except (TypeError, ValueError):
            return 0

    def set_metrics(self, key: str, metrics: Metrics) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO project_state (key, payload) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET payload=excluded.payload",
                (key, metrics.model_dump_json()),
            )

    def get_metrics(self, key: str) -> Metrics | None:
        with self._connect() as connection:
            row = connection.execute("SELECT payload FROM project_state WHERE key = ?", (key,)).fetchone()
        return Metrics.model_validate_json(row["payload"]) if row else None

