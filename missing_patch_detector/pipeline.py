from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from .cve_resolver import CommitRef, CVEResolver
from .patch_collector import PatchCollector
from .patch_presence_detector import PatchPresenceDetector, PatchPresenceResult
from .repo_scanner import RepoScanner


@dataclass
class DetectionReport:
    """Aggregated result of the full missing-patch detection pipeline.

    Attributes
    ----------
    patched_branches:
        Branches where every file in the patch was detected.
    missing_branches:
        Branches where one or more patch files were not detected.
    branch_results:
        Detailed per-branch results including confidence scores.
    cve_id:
        CVE identifier when the report was triggered via :meth:`MissingPatchPipeline.run_for_cve`.
    commit_url:
        The upstream fix commit URL that was analysed.
    generated_at:
        ISO-8601 UTC timestamp of when the report was created.
    """

    patched_branches: list[str]
    missing_branches: list[str]
    branch_results: list[PatchPresenceResult] = field(default_factory=list)
    cve_id: str | None = None
    commit_url: str | None = None
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    # ------------------------------------------------------------------
    # Export helpers (Phase 3)
    # ------------------------------------------------------------------

    def to_json(self, indent: int = 2) -> str:
        """Serialise the report to a JSON string.

        Returns
        -------
        str
            Pretty-printed JSON representation of the report.
        """
        data: dict = {
            "cve_id": self.cve_id,
            "commit_url": self.commit_url,
            "generated_at": self.generated_at,
            "summary": {
                "patched_branches": self.patched_branches,
                "missing_branches": self.missing_branches,
                "total_branches_scanned": len(self.branch_results),
            },
            "branch_results": [
                {
                    "branch": r.branch,
                    "patch_applied": r.patch_applied,
                    "confidence": round(r.confidence, 4),
                    "llm_assisted": r.llm_assisted,
                    "matched_files": r.matched_files,
                    "missing_files": r.missing_files,
                }
                for r in self.branch_results
            ],
        }
        return json.dumps(data, indent=indent, ensure_ascii=False)

    def to_markdown(self) -> str:
        """Render the report as a human-readable Markdown string.

        Returns
        -------
        str
            Markdown text suitable for writing to a ``.md`` file or printing.
        """
        lines: list[str] = []

        title = f"## Missing Patch Detection Report"
        if self.cve_id:
            title += f" – {self.cve_id}"
        lines.append(title)
        lines.append("")

        lines.append(f"**Generated:** {self.generated_at}")
        if self.commit_url:
            lines.append(f"**Commit:** {self.commit_url}")
        lines.append("")

        lines.append("### Summary")
        lines.append("")
        patched_count = len(self.patched_branches)
        missing_count = len(self.missing_branches)
        total = len(self.branch_results)
        lines.append(f"| Metric | Count |")
        lines.append(f"|--------|-------|")
        lines.append(f"| Branches scanned | {total} |")
        lines.append(f"| ✅ Patched | {patched_count} |")
        lines.append(f"| ❌ Missing patch | {missing_count} |")
        lines.append("")

        lines.append("### Branch Results")
        lines.append("")
        lines.append("| Branch | Status | Confidence | LLM Assisted | Missing Files |")
        lines.append("|--------|--------|-----------|--------------|---------------|")
        for r in self.branch_results:
            status = "✅ Patched" if r.patch_applied else "❌ Missing"
            llm = "Yes" if r.llm_assisted else "No"
            missing = ", ".join(r.missing_files) if r.missing_files else "—"
            lines.append(
                f"| `{r.branch}` | {status} | {r.confidence:.2f} | {llm} | {missing} |"
            )
        lines.append("")

        if self.missing_branches:
            lines.append("### ⚠️ Branches Missing the Patch")
            lines.append("")
            for b in self.missing_branches:
                lines.append(f"- `{b}`")
            lines.append("")

        return "\n".join(lines)


class MissingPatchPipeline:
    """End-to-end pipeline: fetch patch → scan repo branches → report.

    Usage
    -----
    ::

        pipeline = MissingPatchPipeline()

        # From a commit URL
        report = pipeline.run(
            commit_url="https://github.com/torvalds/linux/commit/<sha>",
            repo_url="https://github.com/example/linux-fork",
            local_path="/tmp/linux-fork",
        )

        # From a CVE ID (automatically resolves fix commits via OSV)
        reports = pipeline.run_for_cve(
            cve_id="CVE-2021-44228",
            repo_url="https://github.com/example/log4j-fork",
            local_path="/tmp/log4j-fork",
        )

        print("Patched:", report.patched_branches)
        print("Missing:", report.missing_branches)
        print(report.to_markdown())

    Dependency injection
    --------------------
    Pass custom *collector*, *scanner*, *detector*, or *cve_resolver* instances
    to override defaults (useful for testing or applying non-default thresholds).
    """

    def __init__(
        self,
        collector: PatchCollector | None = None,
        scanner: RepoScanner | None = None,
        detector: PatchPresenceDetector | None = None,
        cve_resolver: CVEResolver | None = None,
    ) -> None:
        self.collector = collector or PatchCollector()
        self.scanner = scanner or RepoScanner()
        self.detector = detector or PatchPresenceDetector()
        self.cve_resolver = cve_resolver or CVEResolver()

    # ------------------------------------------------------------------
    # Main entry points
    # ------------------------------------------------------------------

    def run(
        self,
        commit_url: str,
        repo_url: str,
        local_path: str,
        *,
        max_age_days: int = 365,
        include_local_branches: bool = True,
        cve_id: str | None = None,
    ) -> DetectionReport:
        """Run the full detection pipeline and return a :class:`DetectionReport`.

        Parameters
        ----------
        commit_url:
            URL of the upstream fix commit (GitHub, GitLab, etc.).  A ``.patch``
            suffix is appended automatically if not already present.
        repo_url:
            URL of the target repository to clone (or path if already local).
        local_path:
            Local filesystem path where the repository will be cloned or
            re-used if it already exists.
        max_age_days:
            Only consider branches with a commit younger than this many days.
        include_local_branches:
            When ``True`` (default) both local and remote-tracking branches are
            evaluated.
        cve_id:
            Optional CVE identifier to attach to the report for traceability.
        """
        # 1. Download and parse the upstream patch
        patch_text = self.collector.download_patch(commit_url)
        diff_files = self.collector.parse_diff(patch_text)

        # 2. Initialise (clone or reuse) the target repository
        self.scanner.init_repo(repo_url, local_path)

        # 3. Enumerate active branches
        branches = self.scanner.get_active_branches(
            max_age_days=max_age_days,
            include_local=include_local_branches,
        )

        # 4. Check each branch for patch presence
        branch_results: list[PatchPresenceResult] = []
        for branch in branches:
            result = self.detector.check_branch(diff_files, branch, self.scanner)
            branch_results.append(result)

        patched = [r.branch for r in branch_results if r.patch_applied]
        missing = [r.branch for r in branch_results if not r.patch_applied]

        return DetectionReport(
            patched_branches=patched,
            missing_branches=missing,
            branch_results=branch_results,
            cve_id=cve_id,
            commit_url=commit_url,
        )

    def run_for_cve(
        self,
        cve_id: str,
        repo_url: str,
        local_path: str,
        *,
        max_age_days: int = 365,
        include_local_branches: bool = True,
    ) -> list[DetectionReport]:
        """Resolve *cve_id* to fix commits and run the pipeline for each one.

        This is the high-level entry point for **true CVE-based missing-patch
        detection**: given only a CVE ID and the target repository, the method
        automatically looks up the fixing commit(s) from the OSV database and
        returns one :class:`DetectionReport` per fix commit found.

        Parameters
        ----------
        cve_id:
            A CVE identifier such as ``"CVE-2021-44228"``.
        repo_url:
            URL of the target repository to scan.
        local_path:
            Local path where the repository will be cloned or re-used.
        max_age_days:
            Activity threshold for branch filtering.
        include_local_branches:
            When ``True`` both local and remote-tracking branches are evaluated.

        Returns
        -------
        list[DetectionReport]
            One report per fix commit referenced by the CVE.  Returns an empty
            list when no GIT fix commits are found in the OSV record.

        Raises
        ------
        ~missing_patch_detector.cve_resolver.CVENotFoundError
            When the CVE ID is not known to OSV.
        ~missing_patch_detector.cve_resolver.CVEFetchError
            On any network failure contacting the OSV API.
        """
        commit_refs: list[CommitRef] = self.cve_resolver.resolve(cve_id)
        reports: list[DetectionReport] = []

        for ref in commit_refs:
            report = self.run(
                commit_url=ref.commit_url,
                repo_url=repo_url,
                local_path=local_path,
                max_age_days=max_age_days,
                include_local_branches=include_local_branches,
                cve_id=cve_id,
            )
            reports.append(report)

        return reports
