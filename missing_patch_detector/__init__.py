"""Missing Patch Detector core modules."""

from .patch_collector import DiffFileData, PatchCollector
from .patch_presence_detector import PatchPresenceDetector, PatchPresenceResult
from .pipeline import DetectionReport, MissingPatchPipeline
from .repo_scanner import BranchFileSnapshot, RepoScanner

__all__ = [
    "DiffFileData",
    "PatchCollector",
    "BranchFileSnapshot",
    "RepoScanner",
    "PatchPresenceDetector",
    "PatchPresenceResult",
    "DetectionReport",
    "MissingPatchPipeline",
]
