from __future__ import annotations

from dataclasses import dataclass, field

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
    """

    patched_branches: list[str]
    missing_branches: list[str]
    branch_results: list[PatchPresenceResult] = field(default_factory=list)


class MissingPatchPipeline:
    """End-to-end pipeline: fetch patch → scan repo branches → report.

    Usage
    -----
    ::

        pipeline = MissingPatchPipeline()
        report = pipeline.run(
            commit_url="https://github.com/torvalds/linux/commit/<sha>",
            repo_url="https://github.com/example/linux-fork",
            local_path="/tmp/linux-fork",
        )
        print("Patched:", report.patched_branches)
        print("Missing:", report.missing_branches)

    Dependency injection
    --------------------
    Pass custom *collector*, *scanner*, or *detector* instances to override
    defaults (useful for testing or applying non-default thresholds).
    """

    def __init__(
        self,
        collector: PatchCollector | None = None,
        scanner: RepoScanner | None = None,
        detector: PatchPresenceDetector | None = None,
    ) -> None:
        self.collector = collector or PatchCollector()
        self.scanner = scanner or RepoScanner()
        self.detector = detector or PatchPresenceDetector()

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(
        self,
        commit_url: str,
        repo_url: str,
        local_path: str,
        *,
        max_age_days: int = 365,
        include_local_branches: bool = True,
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
        )
