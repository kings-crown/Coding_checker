from __future__ import annotations

from pathlib import Path

from config import WORKSPACE

ALLOWED_SUFFIXES = {".py", ".rs", ".toml", ".lock", ".md", ".txt"}


def _safe_ws_path(rel_path: str) -> Path:
    p = Path(rel_path)

    if p.is_absolute() or p.drive:
        raise ValueError("Absolute/drive paths are not allowed.")
    if ".." in p.parts:
        raise ValueError("Path traversal ('..') is not allowed.")
    if not p.suffix:
        raise ValueError("Path must include a file extension.")
    if p.suffix.lower() not in ALLOWED_SUFFIXES:
        raise ValueError(f"File type not allowed: {p.suffix}")

    resolved = (WORKSPACE / p).resolve()
    try:
        resolved.relative_to(WORKSPACE)
    except ValueError:
        raise ValueError("Path escapes workspace.")
    return resolved


def _safe_ws_dir(rel_dir: str) -> Path:
    p = Path(rel_dir)

    if p.is_absolute() or p.drive:
        raise ValueError("Absolute/drive paths are not allowed.")
    if ".." in p.parts:
        raise ValueError("Path traversal ('..') is not allowed.")

    resolved = (WORKSPACE / p).resolve()
    try:
        resolved.relative_to(WORKSPACE)
    except ValueError:
        raise ValueError("Path escapes workspace.")
    return resolved
