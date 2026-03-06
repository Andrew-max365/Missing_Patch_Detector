"""Missing Patch Detector core modules."""

from .cve_resolver import CVEFetchError, CVENotFoundError, CVEResolver, CVEResolverError, CommitRef
from .patch_collector import DiffFileData, PatchCollector
from .patch_presence_detector import PatchPresenceDetector, PatchPresenceResult
from .pipeline import DetectionReport, MissingPatchPipeline
from .repo_scanner import BranchFileSnapshot, RepoScanner

__all__ = [
    "CommitRef",
    "CVEResolver",
    "CVEResolverError",
    "CVEFetchError",
    "CVENotFoundError",
    "DiffFileData",
    "PatchCollector",
    "BranchFileSnapshot",
    "RepoScanner",
    "PatchPresenceDetector",
    "PatchPresenceResult",
    "DetectionReport",
    "MissingPatchPipeline",
]
