from __future__ import annotations

import hashlib
from pathlib import Path


def protected_hashes(root: Path, patterns: list[str]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for pattern in patterns:
        for path in sorted(root.glob(pattern)):
            if path.is_file():
                relative = path.relative_to(root).as_posix()
                hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def integrity_matches(before: dict[str, str], after: dict[str, str]) -> bool:
    return before == after

