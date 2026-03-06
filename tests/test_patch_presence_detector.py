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


# ---------------------------------------------------------------------------
# LLM fallback tests (Phase 2)
# ---------------------------------------------------------------------------


def test_llm_fallback_invoked_when_confidence_low(tmp_path: Path) -> None:
    """LLM is called when text confidence < llm_threshold and patch not text-matched."""
    _make_repo(tmp_path / "repo", UNPATCHED_SOURCE)
    scanner = RepoScanner()
    scanner.init_repo(str(tmp_path / "repo"), str(tmp_path / "repo"))

    prompts_seen: list[str] = []

    def fake_llm(prompt: str) -> str:
        prompts_seen.append(prompt)
        return "YES – the patch guards are already present semantically"

    detector = PatchPresenceDetector(
        match_threshold=0.8,
        llm_summarizer=fake_llm,
        llm_threshold=0.5,
    )
    result = detector.check_branch([DIFF_DATA], "master", scanner)

    assert result.patch_applied is True
    assert result.llm_assisted is True
    assert len(prompts_seen) == 1
    assert "app.py" in prompts_seen[0]
    assert "PATCH" in prompts_seen[0]


def test_llm_fallback_not_invoked_when_confidence_above_threshold(tmp_path: Path) -> None:
    """LLM must NOT be called when text confidence already meets match_threshold."""
    _make_repo(tmp_path / "repo", PATCHED_SOURCE)
    scanner = RepoScanner()
    scanner.init_repo(str(tmp_path / "repo"), str(tmp_path / "repo"))

    llm_called: list[bool] = []

    def fake_llm(prompt: str) -> str:
        llm_called.append(True)
        return "YES"

    detector = PatchPresenceDetector(
        match_threshold=0.8,
        llm_summarizer=fake_llm,
        llm_threshold=0.5,
    )
    result = detector.check_branch([DIFF_DATA], "master", scanner)

    assert result.patch_applied is True
    assert result.llm_assisted is False
    assert llm_called == []


def test_llm_fallback_no_when_llm_says_no(tmp_path: Path) -> None:
    """If LLM says NO, the file should remain marked as missing."""
    _make_repo(tmp_path / "repo", UNPATCHED_SOURCE)
    scanner = RepoScanner()
    scanner.init_repo(str(tmp_path / "repo"), str(tmp_path / "repo"))

    detector = PatchPresenceDetector(
        match_threshold=0.8,
        llm_summarizer=lambda _: "NO – the guard is not present",
        llm_threshold=0.5,
    )
    result = detector.check_branch([DIFF_DATA], "master", scanner)

    assert result.patch_applied is False
    assert result.llm_assisted is True
    assert "app.py" in result.missing_files


def test_llm_threshold_not_triggered_when_confidence_above_llm_threshold(
    tmp_path: Path,
) -> None:
    """Even if text match fails, LLM is only invoked when confidence < llm_threshold."""
    # Partial match: confidence will be 0.5 (one of two lines matches)
    partial_source = "if size < 0:\n    return 0\n"
    repo = Repo.init(tmp_path / "repo")
    (tmp_path / "repo" / "app.py").write_text(partial_source, encoding="utf-8")
    repo.index.add(["app.py"])
    repo.index.commit("partial")

    scanner = RepoScanner()
    scanner.init_repo(str(tmp_path / "repo"), str(tmp_path / "repo"))

    llm_called: list[bool] = []

    def fake_llm(prompt: str) -> str:
        llm_called.append(True)
        return "YES"

    # llm_threshold=0.4 means LLM fires only when confidence < 0.4
    # confidence here is 0.5, so LLM should NOT fire
    detector = PatchPresenceDetector(
        match_threshold=1.0,  # strict – partial match fails
        llm_summarizer=fake_llm,
        llm_threshold=0.4,
    )
    result = detector.check_branch([DIFF_DATA], "master", scanner)

    # Text matching fails, but LLM was not consulted (confidence >= llm_threshold)
    assert result.patch_applied is False
    assert llm_called == []


def test_invalid_llm_threshold_raises() -> None:
    with pytest.raises(ValueError, match="llm_threshold"):
        PatchPresenceDetector(llm_threshold=-0.1)


def test_llm_assisted_false_when_no_llm_summarizer(tmp_path: Path) -> None:
    """Without a summarizer, llm_assisted must always be False."""
    _make_repo(tmp_path / "repo", UNPATCHED_SOURCE)
    scanner = RepoScanner()
    scanner.init_repo(str(tmp_path / "repo"), str(tmp_path / "repo"))

    detector = PatchPresenceDetector()
    result = detector.check_branch([DIFF_DATA], "master", scanner)

    assert result.llm_assisted is False


def test_llm_retry_on_transient_failure(tmp_path: Path) -> None:
    _make_repo(tmp_path / "repo", UNPATCHED_SOURCE)
    scanner = RepoScanner()
    scanner.init_repo(str(tmp_path / "repo"), str(tmp_path / "repo"))

    attempts = {"count": 0}

    def flaky_llm(_: str) -> str:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("429")
        return "YES"

    detector = PatchPresenceDetector(
        llm_summarizer=flaky_llm,
        llm_threshold=1.0,
        llm_max_retries=3,
        llm_initial_backoff=0.001,
    )

    result = detector.check_branch([DIFF_DATA], "master", scanner)

    assert result.patch_applied is True
    assert result.llm_assisted is True
    assert attempts["count"] == 3


def test_extract_relevant_source_window_prefers_context_near_patch() -> None:
    filler = "\n".join([f"# filler {i}" for i in range(500)])
    vulnerable_tail = "\n".join(
        [
            "def parse_size(size):",
            "    # guard starts here",
            "    if size < 0:",
            "        raise ValueError(\"invalid size\")",
            "    return int(size)",
        ]
    )
    source = f"{filler}\n{vulnerable_tail}\n"

    detector = PatchPresenceDetector()
    snippet = detector._extract_relevant_source_window(DIFF_DATA, source)

    assert "if size < 0:" in snippet
    assert "raise ValueError(\"invalid size\")" in snippet
    # Ensure we are no longer just feeding the start of file to the LLM.
    assert "# filler 0" not in snippet


def test_llm_prompt_includes_relevant_tail_context_not_prefix(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    repo = Repo.init(repo_path)
    source = "\n".join(
        [
            *[f"# filler {i}" for i in range(700)],
            "def parse_size(size):",
            "    if size < 0:",
            "        raise ValueError(\"invalid size\")",
            "    return int(size)",
        ]
    )
    (repo_path / "app.py").write_text(source + "\n", encoding="utf-8")
    repo.index.add(["app.py"])
    repo.index.commit("large source")

    scanner = RepoScanner()
    scanner.init_repo(str(repo_path), str(repo_path))

    prompts_seen: list[str] = []

    def fake_llm(prompt: str) -> str:
        prompts_seen.append(prompt)
        return "YES"

    diff_for_llm = DiffFileData(
        file_path="app.py",
        source_file="a/app.py",
        target_file="b/app.py",
        removed_lines=[],
        added_lines=["if size <= 0:", '    raise ValueError("invalid size")'],
        context_lines=["def parse_size(size):", "    return int(size)"],
    )

    detector = PatchPresenceDetector(
        match_threshold=1.0,
        llm_summarizer=fake_llm,
        llm_threshold=1.0,
    )
    detector.check_branch([diff_for_llm], "master", scanner)

    assert len(prompts_seen) == 1
    assert "if size < 0:" in prompts_seen[0]
    assert "raise ValueError(\"invalid size\")" in prompts_seen[0]
    assert "# filler 0" not in prompts_seen[0]
