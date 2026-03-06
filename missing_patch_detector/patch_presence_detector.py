from __future__ import annotations

from dataclasses import dataclass, field
import random
import threading
import time
from typing import Callable

from .patch_collector import DiffFileData
from .repo_scanner import RepoScanner


@dataclass(slots=True)
class PatchPresenceResult:
    """Result of checking whether a patch is applied on a single branch."""

    branch: str
    patch_applied: bool
    matched_files: list[str]
    missing_files: list[str]
    confidence: float
    llm_assisted: bool = False


class PatchPresenceDetector:
    """Check whether a parsed patch is present in each branch of a repository.

    Detection strategy
    ------------------
    For every file touched by the patch, the corresponding source file on the
    branch is read.  Each *added* line from the patch is looked up (stripped) in
    the set of stripped source lines.  The ratio of matched added lines gives a
    per-file confidence score.  A file is considered patched when that ratio is
    at or above ``match_threshold`` (default 0.8).  A branch is considered fully
    patched only when *all* patch files pass the threshold.

    LLM fallback (Phase 2)
    ----------------------
    When *llm_summarizer* is provided and text-matching confidence falls below
    ``llm_threshold``, the detector sends the patch diff and the relevant source
    code to the LLM callback for a semantic verdict.  The callback must accept a
    ``str`` prompt and return ``"YES"`` or ``"NO"`` (case-insensitive) optionally
    followed by an explanation.
    """

    def __init__(
        self,
        match_threshold: float = 0.8,
        llm_summarizer: Callable[[str], str] | None = None,
        llm_threshold: float = 0.5,
        llm_max_concurrency: int = 2,
        llm_max_retries: int = 3,
        llm_initial_backoff: float = 0.5,
    ) -> None:
        if not (0.0 <= match_threshold <= 1.0):
            raise ValueError("match_threshold must be between 0.0 and 1.0")
        if not (0.0 <= llm_threshold <= 1.0):
            raise ValueError("llm_threshold must be between 0.0 and 1.0")
        if llm_max_concurrency <= 0:
            raise ValueError("llm_max_concurrency must be >= 1")
        if llm_max_retries < 0:
            raise ValueError("llm_max_retries must be >= 0")
        if llm_initial_backoff <= 0:
            raise ValueError("llm_initial_backoff must be > 0")
        self.match_threshold = match_threshold
        self.llm_summarizer = llm_summarizer
        self.llm_threshold = llm_threshold
        self.llm_max_retries = llm_max_retries
        self.llm_initial_backoff = llm_initial_backoff
        self._llm_semaphore = threading.BoundedSemaphore(value=llm_max_concurrency)

    # ------------------------------------------------------------------
    # Per-file helpers
    # ------------------------------------------------------------------

    def is_patch_applied_to_file(
        self, diff_data: DiffFileData, source_code: str
    ) -> tuple[bool, float]:
        """Return *(applied, confidence)* for a single file.

        *confidence* is the fraction of the patch's added lines that appear
        (stripped) in *source_code*.  When the patch adds no lines the file is
        trivially considered patched (confidence = 1.0).
        """
        added_lines = diff_data.added_lines
        if not added_lines:
            return True, 1.0

        source_line_set = {line.strip() for line in source_code.splitlines()}
        matched = sum(
            1 for line in added_lines if line.strip() in source_line_set
        )
        confidence = matched / len(added_lines)
        return confidence >= self.match_threshold, confidence

    def _ask_llm_for_file(
        self, diff_data: DiffFileData, source_code: str
    ) -> bool:
        """Use the LLM callback to decide whether a patch is applied to a file.

        Sends a structured prompt containing the patch diff and the current
        source and expects a ``"YES"`` / ``"NO"`` answer.  Returns ``True`` if
        the LLM answer starts with ``"yes"`` (case-insensitive).
        """
        assert self.llm_summarizer is not None  # caller's responsibility

        diff_section = (
            f"File: {diff_data.file_path}\n"
            f"Added lines:\n" + "\n".join(diff_data.added_lines[:80]) + "\n"
            f"Removed lines:\n" + "\n".join(diff_data.removed_lines[:80]) + "\n"
        )
        source_section = f"Current source:\n{source_code[:3000]}\n"

        prompt = (
            "You are a security patch analyst.\n"
            "Determine whether the following security patch has already been applied "
            "to the source code shown below.\n"
            "Answer exactly 'YES' if the patch is applied or 'NO' if it is missing, "
            "followed by a one-sentence explanation.\n\n"
            f"=== PATCH ===\n{diff_section}\n"
            f"=== SOURCE ===\n{source_section}"
        )
        answer = self._call_llm_with_retry(prompt)
        return answer.strip().upper().startswith("YES")


    def _call_llm_with_retry(self, prompt: str) -> str:
        """Call LLM callback with concurrency throttling and retry backoff."""
        assert self.llm_summarizer is not None

        with self._llm_semaphore:
            attempt = 0
            while True:
                try:
                    return self.llm_summarizer(prompt)
                except Exception:
                    if attempt >= self.llm_max_retries:
                        raise
                    sleep_seconds = self.llm_initial_backoff * (2**attempt)
                    sleep_seconds += random.uniform(0.0, 0.1)
                    time.sleep(sleep_seconds)
                    attempt += 1

    # ------------------------------------------------------------------
    # Branch-level check
    # ------------------------------------------------------------------

    def check_branch(
        self,
        diff_files: list[DiffFileData],
        branch: str,
        scanner: RepoScanner,
    ) -> PatchPresenceResult:
        """Check whether all files in *diff_files* are patched on *branch*.

        Uses *scanner* to read each relevant file on the branch.  Files that
        cannot be located are treated as unpatched.

        When a ``llm_summarizer`` was provided and text-matching confidence is
        below ``llm_threshold``, the LLM is queried as a fallback for that file.
        """
        matched_files: list[str] = []
        missing_files: list[str] = []
        confidence_scores: list[float] = []
        llm_assisted = False

        for diff_data in diff_files:
            snapshot = scanner.checkout_and_read(branch, diff_data.file_path)

            if snapshot.source_code is None:
                missing_files.append(diff_data.file_path)
                confidence_scores.append(0.0)
                continue

            applied, confidence = self.is_patch_applied_to_file(
                diff_data, snapshot.source_code
            )

            # LLM fallback: if text matching is inconclusive and a summarizer is available
            if not applied and self.llm_summarizer is not None and confidence < self.llm_threshold:
                applied = self._ask_llm_for_file(diff_data, snapshot.source_code)
                llm_assisted = True
                # Treat LLM confirmation as high-confidence
                if applied:
                    confidence = max(confidence, self.match_threshold)

            confidence_scores.append(confidence)
            if applied:
                matched_files.append(diff_data.file_path)
            else:
                missing_files.append(diff_data.file_path)

        avg_confidence = (
            sum(confidence_scores) / len(confidence_scores)
            if confidence_scores
            else 0.0
        )
        patch_applied = len(missing_files) == 0

        return PatchPresenceResult(
            branch=branch,
            patch_applied=patch_applied,
            matched_files=matched_files,
            missing_files=missing_files,
            confidence=avg_confidence,
            llm_assisted=llm_assisted,
        )
