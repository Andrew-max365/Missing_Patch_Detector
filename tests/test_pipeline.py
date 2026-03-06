from __future__ import annotations

import json
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
@@ -1,2 +1,4 @@
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


def test_pipeline_run_preserves_branch_order_with_parallel_scan() -> None:
    """Parallel scan should keep branch_results aligned with branch enumeration order."""
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

    ordered_branches = ["release/1.0", "release/2.0", "main"]
    mock_collector.download_patch.return_value = "raw patch"
    mock_collector.parse_diff.return_value = [diff]
    mock_scanner.get_active_branches.return_value = ordered_branches

    def _result_for_branch(
        _diff_files: list[DiffFileData],
        branch: str,
        _scanner: RepoScanner,
    ) -> PatchPresenceResult:
        return PatchPresenceResult(
            branch=branch,
            patch_applied=branch != "release/1.0",
            matched_files=["f.py"] if branch != "release/1.0" else [],
            missing_files=[] if branch != "release/1.0" else ["f.py"],
            confidence=1.0 if branch != "release/1.0" else 0.0,
        )

    mock_detector.check_branch.side_effect = _result_for_branch

    pipeline = MissingPatchPipeline(
        collector=mock_collector,
        scanner=mock_scanner,
        detector=mock_detector,
    )

    report = pipeline.run(
        commit_url="https://example.com/commit/xyz",
        repo_url="https://example.com/repo.git",
        local_path="/tmp/repo",
        max_workers=3,
    )

    assert [r.branch for r in report.branch_results] == ordered_branches
    assert report.patched_branches == ["release/2.0", "main"]
    assert report.missing_branches == ["release/1.0"]


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


# ---------------------------------------------------------------------------
# DetectionReport export tests (Phase 3)
# ---------------------------------------------------------------------------


def _make_report(patched: list[str], missing: list[str]) -> DetectionReport:
    results = [
        PatchPresenceResult(
            branch=b,
            patch_applied=True,
            matched_files=["app.py"],
            missing_files=[],
            confidence=1.0,
            llm_assisted=False,
        )
        for b in patched
    ] + [
        PatchPresenceResult(
            branch=b,
            patch_applied=False,
            matched_files=[],
            missing_files=["app.py"],
            confidence=0.0,
            llm_assisted=False,
        )
        for b in missing
    ]
    return DetectionReport(
        patched_branches=patched,
        missing_branches=missing,
        branch_results=results,
        cve_id="CVE-2021-99999",
        commit_url="https://github.com/example/repo/commit/abc123",
    )


def test_to_json_structure() -> None:
    report = _make_report(["main"], ["legacy"])
    data = json.loads(report.to_json())

    assert data["cve_id"] == "CVE-2021-99999"
    assert data["commit_url"] == "https://github.com/example/repo/commit/abc123"
    assert "generated_at" in data
    assert data["summary"]["patched_branches"] == ["main"]
    assert data["summary"]["missing_branches"] == ["legacy"]
    assert data["summary"]["total_branches_scanned"] == 2
    assert len(data["branch_results"]) == 2
    # Verify branch result shape
    main_result = next(r for r in data["branch_results"] if r["branch"] == "main")
    assert main_result["patch_applied"] is True
    assert main_result["confidence"] == 1.0
    assert main_result["llm_assisted"] is False


def test_to_markdown_contains_key_sections() -> None:
    report = _make_report(["main"], ["legacy"])
    md = report.to_markdown()

    assert "CVE-2021-99999" in md
    assert "main" in md
    assert "legacy" in md
    assert "✅ Patched" in md
    assert "❌ Missing" in md
    # Table headers
    assert "Branch" in md
    assert "Confidence" in md


def test_to_markdown_no_cve_id() -> None:
    report = DetectionReport(
        patched_branches=["main"],
        missing_branches=[],
        branch_results=[],
    )
    md = report.to_markdown()
    assert "Missing Patch Detection Report" in md
    # No CVE dash appended
    assert "–" not in md


def test_to_json_no_missing_branches() -> None:
    report = _make_report(["main", "dev"], [])
    data = json.loads(report.to_json())
    assert data["summary"]["missing_branches"] == []
    assert data["summary"]["patched_branches"] == ["main", "dev"]


# ---------------------------------------------------------------------------
# run_for_cve tests
# ---------------------------------------------------------------------------


def test_run_for_cve_uses_resolved_commit_url(tmp_path: Path) -> None:
    """run_for_cve should resolve the CVE and run once per fix commit."""
    from missing_patch_detector.cve_resolver import CommitRef, CVEResolver

    repo_path = tmp_path / "repo"
    # Create a trivial single-branch repo
    repo = Repo.init(repo_path)
    (repo_path / "app.py").write_text(PATCHED_SOURCE, encoding="utf-8")
    repo.index.add(["app.py"])
    repo.index.commit("patched")

    mock_resolver = MagicMock(spec=CVEResolver)
    mock_resolver.resolve.return_value = [
        CommitRef(
            cve_id="CVE-2021-99999",
            repo_url="https://github.com/example/repo",
            commit_hash="abc123",
            commit_url="https://github.com/example/repo/commit/abc123",
            ecosystem="PyPI",
            package="example-lib",
            summary="test",
        )
    ]

    mock_collector = MagicMock(spec=PatchCollector)
    mock_collector.download_patch.return_value = SAMPLE_PATCH
    mock_collector.parse_diff.return_value = [
        DiffFileData(
            file_path="app.py",
            source_file="a/app.py",
            target_file="b/app.py",
            removed_lines=[],
            added_lines=['    if size < 0:', '        raise ValueError("invalid size")'],
            context_lines=["def parse_size(size):", "    return int(size)"],
        )
    ]

    pipeline = MissingPatchPipeline(
        collector=mock_collector,
        detector=PatchPresenceDetector(),
        cve_resolver=mock_resolver,
    )
    reports = pipeline.run_for_cve(
        cve_id="CVE-2021-99999",
        repo_url=str(repo_path),
        local_path=str(repo_path),
        include_local_branches=True,
    )

    mock_resolver.resolve.assert_called_once_with("CVE-2021-99999")
    assert len(reports) == 1
    report = reports[0]
    assert report.cve_id == "CVE-2021-99999"
    assert report.commit_url == "https://github.com/example/repo/commit/abc123"


def test_run_for_cve_returns_empty_when_no_commits(tmp_path: Path) -> None:
    """run_for_cve returns [] when OSV has no GIT fix commits."""
    from missing_patch_detector.cve_resolver import CVEResolver

    mock_resolver = MagicMock(spec=CVEResolver)
    mock_resolver.resolve.return_value = []

    pipeline = MissingPatchPipeline(cve_resolver=mock_resolver)
    reports = pipeline.run_for_cve(
        cve_id="CVE-2023-00000",
        repo_url="https://example.com/repo.git",
        local_path="/tmp/noop",
    )
    assert reports == []


def test_run_cve_id_attached_to_report(tmp_path: Path) -> None:
    """The cve_id kwarg to run() must be stored in DetectionReport."""
    from missing_patch_detector.cve_resolver import CommitRef, CVEResolver

    repo_path = tmp_path / "repo"
    repo = Repo.init(repo_path)
    (repo_path / "app.py").write_text(PATCHED_SOURCE, encoding="utf-8")
    repo.index.add(["app.py"])
    repo.index.commit("initial")

    mock_collector = MagicMock(spec=PatchCollector)
    mock_collector.download_patch.return_value = SAMPLE_PATCH
    mock_collector.parse_diff.return_value = []

    pipeline = MissingPatchPipeline(collector=mock_collector, detector=PatchPresenceDetector())
    report = pipeline.run(
        commit_url="https://example.com/commit/xyz",
        repo_url=str(repo_path),
        local_path=str(repo_path),
        cve_id="CVE-2099-12345",
        include_local_branches=True,
    )
    assert report.cve_id == "CVE-2099-12345"
    assert report.commit_url == "https://example.com/commit/xyz"
