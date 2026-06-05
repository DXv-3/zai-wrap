"""Project and filesystem path policy."""
from __future__ import annotations

import os
from pathlib import Path

from bw.security import is_path_under, sanitize_snapshot_name


class PathPolicy:
    """All file access goes through this policy."""

    def __init__(self, project: Path, watch: Path) -> None:
        self.project = project.resolve()
        self.watch = watch.resolve()
        self.grok_home = (Path.home() / ".grok").resolve()

    def safe_project_file(self, rel: str, *, must_exist: bool = True) -> Path | None:
        rel = rel.lstrip("/").replace("\\", "/")
        if not rel or "\x00" in rel or ".." in rel.split("/"):
            return None
        target = (self.project / rel).resolve()
        try:
            target.relative_to(self.project)
        except ValueError:
            return None
        if target.is_symlink():
            return None
        if must_exist and not target.is_file():
            return None
        if not must_exist and target.is_symlink():
            return None
        return target

    def safe_new_file(self, rel: str) -> Path | None:
        rel = rel.lstrip("/").replace("\\", "/")
        if not rel or "\x00" in rel or ".." in rel.split("/"):
            return None
        target = (self.project / rel).resolve()
        try:
            target.relative_to(self.project)
        except ValueError:
            return None
        if target.is_symlink():
            return None
        return target

    def allowed_terminal(self, path: Path) -> bool:
        path = path.resolve()
        if path.is_symlink():
            return False
        return is_path_under(self.grok_home, path) or is_path_under(self.watch, path)

    def allowed_watch_file(self, path: Path) -> bool:
        path = path.resolve()
        return not path.is_symlink() and is_path_under(self.watch, path)

    def snapshot_path(self, name: str) -> Path | None:
        safe = sanitize_snapshot_name(name)
        target = (self.watch / safe).resolve()
        return target if self.allowed_watch_file(target) else None


def resolve_project() -> Path:
    if raw := os.environ.get("BUILD_WATCH_PROJECT"):
        return Path(raw).resolve()
    d = Path.cwd().resolve()
    for _ in range(12):
        if (d / ".build-watch").is_dir() or (d / ".git").is_dir():
            return d
        if d.parent == d:
            break
        d = d.parent
    return Path.cwd().resolve()


def allowed_terminal_path(path: Path, watch_dir: Path) -> bool:
    """Compatibility helper for terminal pin checks."""
    project = resolve_project()
    w = watch_dir if watch_dir.is_absolute() else resolve_watch(project)
    return PathPolicy(project, w).allowed_terminal(path)


def resolve_watch(project: Path) -> Path:
    if raw := os.environ.get("BUILD_WATCH_DIR"):
        p = Path(raw)
        return p.resolve() if p.is_absolute() else (project / p).resolve()
    return (project / ".build-watch").resolve()