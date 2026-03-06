from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from git import Repo
from git.exc import GitCommandError, InvalidGitRepositoryError, NoSuchPathError


class RepoScannerError(Exception):
    """Base error raised by RepoScanner."""


@dataclass(slots=True)
class BranchFileSnapshot:
    branch: str
    requested_path: str
    resolved_path: str | None
    source_code: str | None
    status: str


class RepoScanner:
    """Initialize repositories, enumerate active branches, and read source files."""

    def __init__(self) -> None:
        self.repo: Repo | None = None

    def init_repo(self, repo_url: str, local_path: str) -> Repo:
        repo_path = Path(local_path)
        if repo_path.exists() and (repo_path / ".git").exists():
            try:
                self.repo = Repo(str(repo_path))
                return self.repo
            except (InvalidGitRepositoryError, NoSuchPathError) as exc:
                raise RepoScannerError(f"Invalid local repository at {local_path}: {exc}") from exc

        try:
            self.repo = Repo.clone_from(repo_url, str(repo_path))
            return self.repo
        except GitCommandError as exc:
            raise RepoScannerError(f"Failed to clone repo {repo_url} -> {local_path}: {exc}") from exc

    def get_active_branches(self, max_age_days: int = 365, include_local: bool = False) -> list[str]:
        if self.repo is None:
            raise RepoScannerError("Repository not initialized")

        threshold = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        branches: list[str] = []

        if include_local:
            for branch in self.repo.branches:
                commit_dt = branch.commit.committed_datetime.astimezone(timezone.utc)
                if commit_dt >= threshold:
                    branches.append(branch.name)

        if "origin" in [r.name for r in self.repo.remotes]:
            for ref in self.repo.remotes.origin.refs:
                if ref.remote_head == "HEAD":
                    continue
                commit_dt = ref.commit.committed_datetime.astimezone(timezone.utc)
                if commit_dt >= threshold:
                    branches.append(ref.name)

        return sorted(set(branches))

    def checkout_and_read(self, branch_name: str, file_path: str) -> BranchFileSnapshot:
        if self.repo is None:
            raise RepoScannerError("Repository not initialized")

        try:
            self.repo.git.checkout(branch_name)
        except GitCommandError as exc:
            raise RepoScannerError(f"Failed to checkout branch {branch_name}: {exc}") from exc

        repo_root = Path(self.repo.working_tree_dir or ".")
        target = repo_root / file_path
        if target.exists():
            return BranchFileSnapshot(
                branch=branch_name,
                requested_path=file_path,
                resolved_path=file_path,
                source_code=target.read_text(encoding="utf-8", errors="ignore"),
                status="found",
            )

        resolved = self._best_effort_locate(repo_root, file_path)
        if resolved is None:
            return BranchFileSnapshot(
                branch=branch_name,
                requested_path=file_path,
                resolved_path=None,
                source_code=None,
                status="missing",
            )

        return BranchFileSnapshot(
            branch=branch_name,
            requested_path=file_path,
            resolved_path=str(resolved.relative_to(repo_root)),
            source_code=resolved.read_text(encoding="utf-8", errors="ignore"),
            status="renamed_or_moved",
        )

    def _best_effort_locate(self, repo_root: Path, original_path: str) -> Path | None:
        """Fallback lookup for renamed/moved files by matching filename in repo."""
        original_name = Path(original_path).name
        candidates = list(repo_root.rglob(original_name))
        if not candidates:
            return None
        # Prefer shortest path depth as a simple heuristic.
        candidates.sort(key=lambda p: len(p.parts))
        return candidates[0]
