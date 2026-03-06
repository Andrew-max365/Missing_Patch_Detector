from __future__ import annotations

import pytest

pytest.importorskip("unidiff")
pytest.importorskip("git")

from pathlib import Path

from git import Repo

from missing_patch_detector.patch_collector import DiffFileData
from missing_patch_detector.patch_presence_detector import (
    PatchPresenceDetector,
    PatchPresenceResult,
)
from missing_patch_detector.repo_scanner import RepoScanner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PATCHED_SOURCE = """\
def parse_size(size):
    if size < 0:
        raise ValueError("invalid size")
    return int(size)
"""

UNPATCHED_SOURCE = """\
def parse_size(size):
    return int(size)
"""

DIFF_DATA = DiffFileData(
    file_path="app.py",
    source_file="a/app.py",
    target_file="b/app.py",
    removed_lines=[],
    added_lines=['if size < 0:', '    raise ValueError("invalid size")'],
    context_lines=["def parse_size(size):", "    return int(size)"],
)


def _make_repo(path: Path, source: str) -> Repo:
    """Create a minimal repo with one file containing *source*."""
    repo = Repo.init(path)
    app = path / "app.py"
    app.write_text(source, encoding="utf-8")
    repo.index.add(["app.py"])
    repo.index.commit("initial commit")
    return repo


# ---------------------------------------------------------------------------
# Unit tests: is_patch_applied_to_file
# ---------------------------------------------------------------------------


def test_is_patch_applied_to_file_detects_patched_source() -> None:
    detector = PatchPresenceDetector()
    applied, confidence = detector.is_patch_applied_to_file(DIFF_DATA, PATCHED_SOURCE)
    assert applied is True
    assert confidence == 1.0


def test_is_patch_applied_to_file_detects_unpatched_source() -> None:
    detector = PatchPresenceDetector()
    applied, confidence = detector.is_patch_applied_to_file(DIFF_DATA, UNPATCHED_SOURCE)
    assert applied is False
    assert confidence == 0.0


def test_is_patch_applied_no_added_lines_is_trivially_true() -> None:
    diff = DiffFileData(
        file_path="readme.md",
        source_file="a/readme.md",
        target_file="b/readme.md",
        removed_lines=["old line"],
        added_lines=[],
        context_lines=[],
    )
    detector = PatchPresenceDetector()
    applied, confidence = detector.is_patch_applied_to_file(diff, "some content")
    assert applied is True
    assert confidence == 1.0


def test_match_threshold_controls_decision() -> None:
    # Partial match: only one of two added lines present
    source = "if size < 0:\n    return 0\n"
    detector_strict = PatchPresenceDetector(match_threshold=1.0)
    detector_lenient = PatchPresenceDetector(match_threshold=0.4)

    applied_strict, _ = detector_strict.is_patch_applied_to_file(DIFF_DATA, source)
    applied_lenient, _ = detector_lenient.is_patch_applied_to_file(DIFF_DATA, source)

    assert applied_strict is False
    assert applied_lenient is True


def test_invalid_threshold_raises() -> None:
    with pytest.raises(ValueError):
        PatchPresenceDetector(match_threshold=1.5)


# ---------------------------------------------------------------------------
# Integration tests: check_branch using a real git repo
# ---------------------------------------------------------------------------


def test_check_branch_patched(tmp_path: Path) -> None:
    _make_repo(tmp_path / "repo", PATCHED_SOURCE)
    scanner = RepoScanner()
    scanner.init_repo(str(tmp_path / "repo"), str(tmp_path / "repo"))

    detector = PatchPresenceDetector()
    result = detector.check_branch([DIFF_DATA], "master", scanner)

    assert isinstance(result, PatchPresenceResult)
    assert result.patch_applied is True
    assert "app.py" in result.matched_files
    assert result.missing_files == []
    assert result.confidence == 1.0


def test_check_branch_unpatched(tmp_path: Path) -> None:
    _make_repo(tmp_path / "repo", UNPATCHED_SOURCE)
    scanner = RepoScanner()
    scanner.init_repo(str(tmp_path / "repo"), str(tmp_path / "repo"))

    detector = PatchPresenceDetector()
    result = detector.check_branch([DIFF_DATA], "master", scanner)

    assert result.patch_applied is False
    assert "app.py" in result.missing_files
    assert result.matched_files == []
    assert result.confidence == 0.0


def test_check_branch_missing_file(tmp_path: Path) -> None:
    """If the file does not exist on the branch, it is counted as missing."""
    repo = Repo.init(tmp_path / "repo")
    other = tmp_path / "repo" / "other.py"
    other.write_text("x = 1\n", encoding="utf-8")
    repo.index.add(["other.py"])
    repo.index.commit("only other.py")

    scanner = RepoScanner()
    scanner.init_repo(str(tmp_path / "repo"), str(tmp_path / "repo"))

    detector = PatchPresenceDetector()
    result = detector.check_branch([DIFF_DATA], "master", scanner)

    assert result.patch_applied is False
    assert result.missing_files == ["app.py"]


def test_check_branch_multiple_files(tmp_path: Path) -> None:
    """Patch covering two files: one patched, one not → branch reported missing."""
    repo_path = tmp_path / "repo"
    repo = Repo.init(repo_path)

    (repo_path / "app.py").write_text(PATCHED_SOURCE, encoding="utf-8")
    (repo_path / "util.py").write_text("x = 1\n", encoding="utf-8")
    repo.index.add(["app.py", "util.py"])
    repo.index.commit("initial")

    diff_util = DiffFileData(
        file_path="util.py",
        source_file="a/util.py",
        target_file="b/util.py",
        removed_lines=[],
        added_lines=["SENTINEL_LINE_NOT_PRESENT"],
        context_lines=[],
    )

    scanner = RepoScanner()
    scanner.init_repo(str(repo_path), str(repo_path))

    detector = PatchPresenceDetector()
    result = detector.check_branch([DIFF_DATA, diff_util], "master", scanner)

    assert result.patch_applied is False
    assert "app.py" in result.matched_files
    assert "util.py" in result.missing_files
