from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import cast

from git import Repo
from git.objects import Blob, Tree
from git.exc import BadName, GitCommandError, InvalidGitRepositoryError, NoSuchPathError


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
        """Read *file_path* from *branch_name* without mutating worktree state.

        Historically this method checked out each branch and then read files from disk.
        That approach is correct but too slow when scanning many branches and cannot be
        safely parallelised on one repository checkout.  The implementation now reads
        directly from the branch commit tree (Git object database), so it remains
        backward compatible while enabling concurrent branch scanning.
        """
        if self.repo is None:
            raise RepoScannerError("Repository not initialized")

        try:
            commit = self.repo.commit(branch_name)
        except (ValueError, GitCommandError, BadName) as exc:
            raise RepoScannerError(f"Failed to resolve branch {branch_name}: {exc}") from exc

        source_code = self._read_blob_text(commit.tree, file_path)
        if source_code is not None:
            return BranchFileSnapshot(
                branch=branch_name,
                requested_path=file_path,
                resolved_path=file_path,
                source_code=source_code,
                status="found",
            )

        resolved = self._best_effort_locate_in_tree(commit.tree, file_path)
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
            resolved_path=resolved,
            source_code=self._read_blob_text(commit.tree, resolved),
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

    def _read_blob_text(self, tree: Tree, file_path: str) -> str | None:
        """Return UTF-8 text for *file_path* in *tree* when present."""
        try:
            obj = tree / file_path
        except KeyError:
            return None

        if not isinstance(obj, Blob):
            return None
        return obj.data_stream.read().decode("utf-8", errors="ignore")

    def _best_effort_locate_in_tree(self, tree: Tree, original_path: str) -> str | None:
        """Fallback lookup for renamed/moved files by filename within one commit tree."""
        original_name = Path(original_path).name
        matches: list[str] = []

        stack: list[tuple[str, Tree]] = [("", tree)]
        while stack:
            prefix, current_tree = stack.pop()
            for item in current_tree:
                item_path = f"{prefix}{item.name}" if not prefix else f"{prefix}/{item.name}"
                if isinstance(item, Tree):
                    stack.append((item_path, cast(Tree, item)))
                    continue
                if isinstance(item, Blob) and Path(item_path).name == original_name:
                    matches.append(item_path)

        if not matches:
            return None

        matches.sort(key=lambda p: len(Path(p).parts))
        return matches[0]
