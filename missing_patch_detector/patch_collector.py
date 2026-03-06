from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

import requests
from unidiff import PatchSet


class PatchCollectionError(Exception):
    """Base error for patch collection failures."""


class PatchDownloadError(PatchCollectionError):
    """Raised when patch content cannot be downloaded."""


class PatchParseError(PatchCollectionError):
    """Raised when patch content cannot be parsed."""


@dataclass(slots=True)
class DiffFileData:
    """Structured representation of one file's diff block."""

    file_path: str
    source_file: str
    target_file: str
    removed_lines: list[str]
    added_lines: list[str]
    context_lines: list[str]


class PatchCollector:
    """Download and parse upstream patch data into machine-readable features."""

    def __init__(self, timeout: int = 20, user_agent: str = "MissingPatchDetector/0.1") -> None:
        self.timeout = timeout
        self.user_agent = user_agent

    def download_patch(self, commit_url: str) -> str:
        """Download patch text from a commit URL or direct .patch endpoint."""
        patch_url = commit_url if commit_url.endswith(".patch") else f"{commit_url}.patch"
        headers = {"User-Agent": self.user_agent, "Accept": "text/plain"}

        try:
            response = requests.get(patch_url, timeout=self.timeout, headers=headers)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise PatchDownloadError(f"Failed to download patch from {patch_url}: {exc}") from exc

        if not response.text.strip():
            raise PatchDownloadError(f"Downloaded patch from {patch_url} is empty")
        return response.text

    def parse_diff(self, patch_text: str) -> list[DiffFileData]:
        """Parse unified diff text into per-file structures."""
        if not patch_text.strip():
            raise PatchParseError("patch_text is empty")

        try:
            patch_set = PatchSet(patch_text)
        except Exception as exc:  # unidiff can raise multiple parser exceptions
            raise PatchParseError(f"Failed to parse patch content: {exc}") from exc

        parsed_files: list[DiffFileData] = []
        for patched_file in patch_set:
            removed_lines: list[str] = []
            added_lines: list[str] = []
            context_lines: list[str] = []

            for hunk in patched_file:
                for line in hunk:
                    if line.is_removed:
                        removed_lines.append(line.value.rstrip("\n"))
                    elif line.is_added:
                        added_lines.append(line.value.rstrip("\n"))
                    elif line.is_context:
                        context_lines.append(line.value.rstrip("\n"))

            parsed_files.append(
                DiffFileData(
                    file_path=patched_file.path,
                    source_file=patched_file.source_file,
                    target_file=patched_file.target_file,
                    removed_lines=removed_lines,
                    added_lines=added_lines,
                    context_lines=context_lines,
                )
            )

        if not parsed_files:
            raise PatchParseError("No file diffs detected in patch")
        return parsed_files

    def generate_llm_signature(
        self,
        diff_data: Iterable[DiffFileData],
        summarizer: Callable[[str], str] | None = None,
    ) -> str:
        """Generate semantic patch signature by calling provided summarizer callback.

        This keeps vendor SDK usage decoupled from parsing logic; pass a callable that
        sends prompt text to Gemini/OpenAI and returns a concise summary.
        """
        if summarizer is None:
            raise ValueError("summarizer callback is required for generate_llm_signature")

        sections: list[str] = []
        for item in diff_data:
            section = (
                f"File: {item.file_path}\n"
                f"Added lines:\n" + "\n".join(item.added_lines[:80]) + "\n"
                f"Removed lines:\n" + "\n".join(item.removed_lines[:80]) + "\n"
            )
            sections.append(section)

        prompt = (
            "Summarize the security-relevant intent of this patch in one paragraph and "
            "list concrete detection clues:\n\n" + "\n---\n".join(sections)
        )
        return summarizer(prompt)
