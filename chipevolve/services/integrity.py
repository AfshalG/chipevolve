from __future__ import annotations

import fnmatch
import hashlib
from pathlib import Path

# Never hash our own state directory; it changes every run by design.
_SKIP_DIRS = {".chipevolve", ".git", "obj_dir", "__pycache__", ".venv"}


def _matches(relative: str, pattern: str) -> bool:
    """Does a repo-relative path match a protected glob?

    Uses fnmatch rather than Path.glob so this agrees exactly with
    agents/tools.py::ToolContext.is_protected. Two layers enforcing the same
    rule must not disagree about what "tb/**" means.
    """
    if fnmatch.fnmatch(relative, pattern):
        return True
    # "tb/**" should cover "tb/alu_tb.sv" and anything deeper.
    return fnmatch.fnmatch(relative, pattern.rstrip("/*") + "/*")


def protected_hashes(root: Path, patterns: list[str]) -> dict[str, str]:
    """SHA-256 every file matching a protected pattern.

    NOTE: an earlier implementation used root.glob(pattern), which for "tb/**"
    yields only the DIRECTORY tb and was then dropped by the is_file() filter.
    That silently returned {} for every pattern, so integrity_matches({}, {})
    was always True and the reward-hacking gate never fired.
    """
    hashes: dict[str, str] = {}
    if not root.is_dir():
        return hashes
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError:
            continue
        if any(part in _SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if any(_matches(relative, pattern) for pattern in patterns):
            hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def integrity_matches(before: dict[str, str], after: dict[str, str]) -> bool:
    """Reject on ANY change, including files appearing or disappearing.

    An empty `before` means nothing protected was found — treat that as a
    failure to verify rather than a pass, so a misconfigured `protected` list
    can never look like a clean run.
    """
    return bool(before) and before == after
