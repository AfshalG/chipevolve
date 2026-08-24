from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from chipevolve.agents import prompts as agent_prompts
from chipevolve.agents import tools as agent_tools
from chipevolve.agents.session import DEFAULT_MODEL, SessionManager
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
sessions = SessionManager(config, repository, toolchain, events)


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


def _activate(root: Path) -> None:
    """Point the whole backend at a different project directory."""
    global config, state_root, repository, runner, toolchain, evolution, sessions
    config = load_project_config(root)
    state_root = root / ".chipevolve"
    repository = Repository(state_root / "chipevolve.sqlite3")
    runner = CommandRunner(state_root / "logs", distro=os.environ.get("CHIPEVOLVE_WSL_DISTRO", "Ubuntu"))
    toolchain = Toolchain(runner)
    evolution = EvolutionService(config, repository, toolchain, events)
    sessions = SessionManager(config, repository, toolchain, events)


@app.get("/api/health")
async def health() -> dict:
    return {
        "status": "ok",
        "project": config.name,
        "root": str(config.root),
        "tools": await toolchain.status(),
    }


@app.post("/api/project/open")
async def open_project(payload: dict = Body(...)) -> dict:
    raw = (payload.get("root") or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="A project root is required.")
    root = Path(raw).expanduser()
    if not root.is_dir():
        raise HTTPException(status_code=400, detail=f"{root} is not a directory.")
    root = root.resolve()
    if root == config.root:
        return {"root": str(root), "project": config.name, "changed": False}
    if sessions.busy or evolution_lock.locked():
        raise HTTPException(status_code=409, detail="Finish or cancel the running task before switching projects.")
    try:
        _activate(root)
    except (KeyError, ValueError, OSError) as error:
        raise HTTPException(status_code=400, detail=f"Could not open {root}: {error}") from error
    return {
        "root": str(config.root),
        "project": config.name,
        "changed": True,
        "rtl": config.rtl,
        "top": config.top,
    }


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


@app.get("/api/agent/capabilities")
async def agent_capabilities() -> dict:
    return {
        "default_model": DEFAULT_MODEL,
        "modes": {
            mode: [
                {"name": spec.name, "approval": spec.approval, "description": spec.description}
                for spec in agent_tools.SPECS
                if mode in spec.modes
            ]
            for mode in ("generate", "review", "optimize")
        },
        "protected": config.protected,
        "busy": sessions.busy,
    }


@app.post("/api/agent/task")
async def start_task(payload: dict = Body(...)) -> dict:
    mode = payload.get("mode", "optimize")
    if mode not in {"generate", "review", "optimize"}:
        raise HTTPException(status_code=400, detail=f"Unknown mode: {mode}")
    message = (payload.get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="A task description is required.")
    selection = payload.get("selection")
    note = agent_prompts.editor_context(
        payload.get("focus_path"),
        list(payload.get("open_files") or []),
        (int(selection[0]), int(selection[1])) if selection else None,
    )
    try:
        session = await sessions.start(
            mode=mode,
            message=message,
            model=payload.get("model") or DEFAULT_MODEL,
            auto_approve=payload.get("auto_approve") or [],
            editor_note=note,
        )
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {
        "session": session.id,
        "mode": mode,
        "workspace": session.workspace_label,
        "workspace_path": str(session.workspace),
    }


@app.post("/api/agent/approve")
async def approve_tool(payload: dict = Body(...)) -> dict:
    tool_use_id = payload.get("tool_use_id")
    if not tool_use_id:
        raise HTTPException(status_code=400, detail="tool_use_id is required.")
    resolved = sessions.approve(tool_use_id, bool(payload.get("approved")), payload.get("feedback", ""))
    if not resolved:
        raise HTTPException(status_code=404, detail="No approval is pending for that tool call.")
    return {"status": "resolved"}


@app.post("/api/agent/cancel")
async def cancel_task() -> dict:
    return {"cancelled": await sessions.cancel()}


@app.post("/api/agent/apply")
async def apply_task_edits() -> dict:
    try:
        applied = sessions.apply()
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {"applied": applied}


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

