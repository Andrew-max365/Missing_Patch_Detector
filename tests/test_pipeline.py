from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("unidiff")
pytest.importorskip("git")

from git import Repo

from missing_patch_detector.patch_collector import DiffFileData, PatchCollector
from missing_patch_detector.patch_presence_detector import (
    PatchPresenceDetector,
    PatchPresenceResult,
)
from missing_patch_detector.pipeline import DetectionReport, MissingPatchPipeline
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

SAMPLE_PATCH = """\
diff --git a/app.py b/app.py
index 1111111..2222222 100644
--- a/app.py
+++ b/app.py
@@ -1,3 +1,5 @@
 def parse_size(size):
+    if size < 0:
+        raise ValueError(\"invalid size\")
     return int(size)
"""


def _make_two_branch_repo(path: Path) -> Repo:
    """Create a repo with two branches: master (patched), legacy (unpatched)."""
    repo = Repo.init(path)

    (path / "app.py").write_text(PATCHED_SOURCE, encoding="utf-8")
    repo.index.add(["app.py"])
    repo.index.commit("patched version")

    repo.git.checkout("-b", "legacy")
    (path / "app.py").write_text(UNPATCHED_SOURCE, encoding="utf-8")
    repo.index.add(["app.py"])
    repo.index.commit("unpatched version")

    repo.git.checkout("master")
    return repo


# ---------------------------------------------------------------------------
# DetectionReport tests
# ---------------------------------------------------------------------------


def test_detection_report_attributes() -> None:
    report = DetectionReport(
        patched_branches=["main"],
        missing_branches=["legacy"],
        branch_results=[],
    )
    assert report.patched_branches == ["main"]
    assert report.missing_branches == ["legacy"]
    assert report.branch_results == []


# ---------------------------------------------------------------------------
# MissingPatchPipeline integration tests (mocked network)
# ---------------------------------------------------------------------------


def test_pipeline_run_identifies_patched_and_missing(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    _make_two_branch_repo(repo_path)

    # Mock the collector so no real HTTP request is made
    mock_collector = MagicMock(spec=PatchCollector)
    mock_collector.download_patch.return_value = SAMPLE_PATCH
    mock_collector.parse_diff.return_value = [
        DiffFileData(
            file_path="app.py",
            source_file="a/app.py",
            target_file="b/app.py",
            removed_lines=[],
            added_lines=['if size < 0:', '    raise ValueError("invalid size")'],
            context_lines=["def parse_size(size):", "    return int(size)"],
        )
    ]

    pipeline = MissingPatchPipeline(
        collector=mock_collector,
        detector=PatchPresenceDetector(),
    )
    report = pipeline.run(
        commit_url="https://example.com/commit/abc",
        repo_url=str(repo_path),
        local_path=str(repo_path),
        include_local_branches=True,
    )

    assert isinstance(report, DetectionReport)
    assert "master" in report.patched_branches
    assert "legacy" in report.missing_branches
    assert len(report.branch_results) == 2


def test_pipeline_uses_injected_dependencies() -> None:
    """Verify that injected collector/scanner/detector are actually used."""
    mock_collector = MagicMock(spec=PatchCollector)
    mock_scanner = MagicMock(spec=RepoScanner)
    mock_detector = MagicMock(spec=PatchPresenceDetector)

    diff = DiffFileData(
        file_path="f.py",
        source_file="a/f.py",
        target_file="b/f.py",
        removed_lines=[],
        added_lines=["x = 1"],
        context_lines=[],
    )
    mock_collector.download_patch.return_value = "raw patch"
    mock_collector.parse_diff.return_value = [diff]
    mock_scanner.get_active_branches.return_value = ["main"]
    mock_detector.check_branch.return_value = PatchPresenceResult(
        branch="main",
        patch_applied=True,
        matched_files=["f.py"],
        missing_files=[],
        confidence=1.0,
    )

    pipeline = MissingPatchPipeline(
        collector=mock_collector,
        scanner=mock_scanner,
        detector=mock_detector,
    )
    report = pipeline.run(
        commit_url="https://example.com/commit/xyz",
        repo_url="https://example.com/repo.git",
        local_path="/tmp/repo",
    )

    mock_collector.download_patch.assert_called_once_with(
        "https://example.com/commit/xyz"
    )
    mock_scanner.init_repo.assert_called_once()
    mock_detector.check_branch.assert_called_once_with([diff], "main", mock_scanner)

    assert report.patched_branches == ["main"]
    assert report.missing_branches == []


def test_pipeline_all_missing(tmp_path: Path) -> None:
    """All branches unpatched → patched_branches is empty."""
    repo_path = tmp_path / "repo"
    repo = Repo.init(repo_path)
    (repo_path / "app.py").write_text(UNPATCHED_SOURCE, encoding="utf-8")
    repo.index.add(["app.py"])
    repo.index.commit("unpatched")

    mock_collector = MagicMock(spec=PatchCollector)
    mock_collector.download_patch.return_value = SAMPLE_PATCH
    mock_collector.parse_diff.return_value = [
        DiffFileData(
            file_path="app.py",
            source_file="a/app.py",
            target_file="b/app.py",
            removed_lines=[],
            added_lines=['if size < 0:', '    raise ValueError("invalid size")'],
            context_lines=[],
        )
    ]

    pipeline = MissingPatchPipeline(
        collector=mock_collector,
        detector=PatchPresenceDetector(),
    )
    report = pipeline.run(
        commit_url="https://example.com/commit/abc",
        repo_url=str(repo_path),
        local_path=str(repo_path),
        include_local_branches=True,
    )

    assert report.patched_branches == []
    assert "master" in report.missing_branches
