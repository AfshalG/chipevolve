from __future__ import annotations

import asyncio
import os
import shlex
import shutil
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from chipevolve.domain.models import ToolExecution


@dataclass(frozen=True)
class CommandResult:
    execution: ToolExecution
    stdout: str
    stderr: str


class CommandRunner:
    """Runs EDA commands natively or through a named WSL distribution."""

    def __init__(self, logs_dir: Path, distro: str = "Ubuntu", force_wsl: bool | None = None) -> None:
        self.logs_dir = logs_dir
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.distro = distro
        self.use_wsl = (sys.platform == "win32") if force_wsl is None else force_wsl

    @staticmethod
    def _stamp() -> str:
        return datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")

    def _wsl_path(self, path: Path) -> str:
        resolved = path.resolve()
        drive = resolved.drive.rstrip(":").lower()
        tail = resolved.as_posix().split(":", 1)[-1]
        return f"/mnt/{drive}{tail}"

    def _wrap(self, command: list[str], cwd: Path) -> list[str]:
        if not self.use_wsl:
            return command
        linux_cwd = self._wsl_path(cwd)
        shell_command = " ".join(shlex.quote(part) for part in command)
        return ["wsl.exe", "-d", self.distro, "--", "bash", "-lc", f"cd {shlex.quote(linux_cwd)} && {shell_command}"]

    async def available(self, tool: str) -> tuple[bool, str | None]:
        if self.use_wsl:
            if shutil.which("wsl.exe") is None:
                return False, "WSL is not installed."
            process = await asyncio.create_subprocess_exec(
                "wsl.exe", "-d", self.distro, "--", "bash", "-lc", f"command -v {shlex.quote(tool)}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
            if process.returncode != 0:
                detail = stderr.decode(errors="replace").strip()
                return False, detail or f"{tool} is not installed in WSL distribution {self.distro}."
            return True, stdout.decode(errors="replace").strip()
        found = shutil.which(tool)
        return (bool(found), found or f"{tool} is not installed.")

    async def run(self, tool: str, command: list[str], cwd: Path, timeout: float) -> CommandResult:
        started = datetime.now(UTC)
        stamp = self._stamp()
        stdout_path = self.logs_dir / f"{stamp}-{tool}.stdout.log"
        stderr_path = self.logs_dir / f"{stamp}-{tool}.stderr.log"
        is_available, reason = await self.available(tool)
        if not is_available:
            execution = ToolExecution(
                tool=tool,
                command=command,
                started_at=started,
                completed_at=datetime.now(UTC),
                exit_code=None,
                success=False,
                unavailable_reason=reason,
            )
            return CommandResult(execution, "", reason or "Tool unavailable")

        wrapped = self._wrap(command, cwd)
        process = await asyncio.create_subprocess_exec(
            *wrapped,
            cwd=None if self.use_wsl else cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=os.environ.copy(),
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except TimeoutError:
            process.kill()
            await process.communicate()
            stdout_bytes, stderr_bytes = b"", f"Timed out after {timeout:.0f}s".encode()

        stdout = stdout_bytes.decode(errors="replace")
        stderr = stderr_bytes.decode(errors="replace")
        stdout_path.write_text(stdout, encoding="utf-8")
        stderr_path.write_text(stderr, encoding="utf-8")
        execution = ToolExecution(
            tool=tool,
            command=command,
            started_at=started,
            completed_at=datetime.now(UTC),
            exit_code=process.returncode,
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            success=process.returncode == 0,
        )
        return CommandResult(execution, stdout, stderr)

