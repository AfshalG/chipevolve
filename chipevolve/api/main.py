from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from chipevolve.domain.models import ProjectSnapshot
from chipevolve.eda.providers import Toolchain
from chipevolve.eda.runner import CommandRunner
from chipevolve.services.config import load_project_config
from chipevolve.services.events import EventBus
from chipevolve.services.evolution import EvolutionService
from chipevolve.storage.repository import Repository


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEMO_ROOT = Path(os.environ.get("CHIPEVOLVE_PROJECT", REPOSITORY_ROOT / "examples" / "alu")).resolve()
config = load_project_config(DEMO_ROOT)
state_root = DEMO_ROOT / ".chipevolve"
repository = Repository(state_root / "chipevolve.sqlite3")
events = EventBus()
runner = CommandRunner(state_root / "logs", distro=os.environ.get("CHIPEVOLVE_WSL_DISTRO", "Ubuntu"))
toolchain = Toolchain(runner)
evolution = EvolutionService(config, repository, toolchain, events)
evolution_lock = asyncio.Lock()


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield


app = FastAPI(title="ChipEvolve API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "project": config.name, "tools": await toolchain.status()}


@app.get("/api/project", response_model=ProjectSnapshot)
async def project_snapshot() -> ProjectSnapshot:
    files = {path: (config.root / path).read_text(encoding="utf-8") for path in config.rtl}
    return ProjectSnapshot(
        config=config,
        source_files=files,
        baseline=repository.get_metrics("baseline"),
        best=repository.get_metrics("best"),
        generations=repository.generations(),
        tool_status=await toolchain.status(),
    )


@app.post("/api/baseline")
async def baseline(force: bool = False) -> dict:
    async with evolution_lock:
        metrics, verification = await evolution.establish_baseline(force=force)
    return {"metrics": metrics, "verification": verification}


@app.post("/api/evolve")
async def evolve() -> dict:
    if evolution_lock.locked():
        raise HTTPException(status_code=409, detail="An evolution run is already active.")

    async def run() -> None:
        async with evolution_lock:
            await evolution.evolve_once()

    asyncio.create_task(run())
    return {"status": "started"}


@app.get("/api/events")
async def event_stream() -> StreamingResponse:
    queue = events.subscribe()

    async def stream():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"data: {event.model_dump_json()}\n\n"
                except TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            events.unsubscribe(queue)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

