from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("git")

from git import Repo

from missing_patch_detector.repo_scanner import RepoScanner


def _init_demo_repo(path: Path) -> Repo:
    repo = Repo.init(path)
    file_path = path / "src" / "module.py"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("print('main')\n", encoding="utf-8")
    repo.index.add([str(file_path.relative_to(path))])
    repo.index.commit("initial commit")

    repo.git.checkout("-b", "legacy")
    moved = path / "module.py"
    moved.write_text("print('legacy')\n", encoding="utf-8")
    file_path.unlink()
    repo.index.add(["module.py"])
    repo.index.remove(["src/module.py"])
    repo.index.commit("move file")

    repo.git.checkout("master")
    return repo


def test_checkout_and_read_handles_found_and_renamed(tmp_path: Path) -> None:
    local_repo = tmp_path / "demo"
    _init_demo_repo(local_repo)

    scanner = RepoScanner()
    scanner.init_repo(str(local_repo), str(local_repo))

    master_snapshot = scanner.checkout_and_read("master", "src/module.py")
    assert master_snapshot.status == "found"
    assert master_snapshot.source_code is not None

    legacy_snapshot = scanner.checkout_and_read("legacy", "src/module.py")
    assert legacy_snapshot.status == "renamed_or_moved"
    assert legacy_snapshot.resolved_path == "module.py"


def test_get_active_branches_for_local_repo(tmp_path: Path) -> None:
    local_repo = tmp_path / "demo"
    _init_demo_repo(local_repo)

    scanner = RepoScanner()
    scanner.init_repo(str(local_repo), str(local_repo))

    branches = scanner.get_active_branches(include_local=True)
    assert "master" in branches
    assert "legacy" in branches
