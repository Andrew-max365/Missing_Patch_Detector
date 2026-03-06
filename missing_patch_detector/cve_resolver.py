"""CVE resolver: map CVE identifiers to upstream fix commit URLs via the OSV API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests


class CVEResolverError(Exception):
    """Base error raised by CVEResolver."""


class CVENotFoundError(CVEResolverError):
    """Raised when the CVE ID is not found in the OSV database."""


class CVEFetchError(CVEResolverError):
    """Raised when the OSV API call fails."""


@dataclass(slots=True)
class CommitRef:
    """A single fix commit associated with a CVE.

    Attributes
    ----------
    cve_id:
        The CVE identifier (e.g. ``"CVE-2021-44228"``).
    repo_url:
        Base URL of the affected repository.
    commit_hash:
        The full SHA of the fixing commit.
    commit_url:
        Fully-qualified URL that can be passed to :class:`~missing_patch_detector.PatchCollector`.
    ecosystem:
        Package ecosystem (e.g. ``"PyPI"``, ``"Go"``, ``"npm"``).
    package:
        Package name within that ecosystem.
    summary:
        Short summary of the vulnerability, if provided by OSV.
    """

    cve_id: str
    repo_url: str
    commit_hash: str
    commit_url: str
    ecosystem: str
    package: str
    summary: str


class CVEResolver:
    """Resolve a CVE ID to a list of fix :class:`CommitRef` objects using the OSV API.

    The `Open Source Vulnerability (OSV) database <https://osv.dev/>`_ aggregates
    vulnerability data for most major open-source ecosystems and provides a clean
    REST API at ``https://api.osv.dev/v1/vulns/{id}``.

    Parameters
    ----------
    timeout:
        HTTP request timeout in seconds (default: 20).
    user_agent:
        ``User-Agent`` header sent to the OSV API.

    Example
    -------
    ::

        resolver = CVEResolver()
        refs = resolver.resolve("CVE-2021-44228")
        for ref in refs:
            print(ref.commit_url)   # pass to MissingPatchPipeline
    """

    OSV_API_URL = "https://api.osv.dev/v1/vulns/{}"

    def __init__(
        self,
        timeout: int = 20,
        user_agent: str = "MissingPatchDetector/0.1",
    ) -> None:
        self.timeout = timeout
        self.user_agent = user_agent

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(self, cve_id: str) -> list[CommitRef]:
        """Return all fix commits referenced by *cve_id*.

        Parameters
        ----------
        cve_id:
            A CVE identifier such as ``"CVE-2021-44228"``.  OSV also accepts
            GHSA IDs and ecosystem-specific IDs.

        Returns
        -------
        list[CommitRef]
            One entry per GIT-type range × fixing event combination.  May be
            empty if the CVE has no GIT fix-commit references.

        Raises
        ------
        CVENotFoundError
            When OSV returns HTTP 404.
        CVEFetchError
            On any other network or HTTP error.
        """
        data = self._fetch_osv(cve_id)
        summary = data.get("summary", "")
        return self._extract_commit_refs(cve_id, summary, data.get("affected", []))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_osv(self, cve_id: str) -> dict[str, Any]:
        url = self.OSV_API_URL.format(cve_id)
        headers = {"User-Agent": self.user_agent, "Accept": "application/json"}
        try:
            response = requests.get(url, timeout=self.timeout, headers=headers)
        except requests.RequestException as exc:
            raise CVEFetchError(f"Network error fetching {cve_id} from OSV: {exc}") from exc

        if response.status_code == 404:
            raise CVENotFoundError(f"CVE not found in OSV database: {cve_id}")

        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise CVEFetchError(f"OSV API error for {cve_id}: {exc}") from exc

        try:
            return response.json()  # type: ignore[no-any-return]
        except ValueError as exc:
            raise CVEFetchError(f"Invalid JSON response from OSV for {cve_id}: {exc}") from exc

    @staticmethod
    def _extract_commit_refs(
        cve_id: str,
        summary: str,
        affected: list[dict[str, Any]],
    ) -> list[CommitRef]:
        """Walk the OSV *affected* array and collect all GIT fix commits."""
        refs: list[CommitRef] = []

        for entry in affected:
            pkg = entry.get("package", {})
            ecosystem = pkg.get("ecosystem", "")
            package = pkg.get("name", "")

            for rng in entry.get("ranges", []):
                if rng.get("type") != "GIT":
                    continue

                repo_url: str = rng.get("repo", "")

                for event in rng.get("events", []):
                    fixed_hash = event.get("fixed")
                    if not fixed_hash:
                        continue

                    commit_url = CVEResolver._build_commit_url(repo_url, fixed_hash)
                    refs.append(
                        CommitRef(
                            cve_id=cve_id,
                            repo_url=repo_url,
                            commit_hash=fixed_hash,
                            commit_url=commit_url,
                            ecosystem=ecosystem,
                            package=package,
                            summary=summary,
                        )
                    )

        return refs

    @staticmethod
    def _build_commit_url(repo_url: str, commit_hash: str) -> str:
        """Construct a browser-friendly commit URL from *repo_url* and *commit_hash*.

        Handles GitHub, GitLab, and generic forge URLs, stripping trailing
        ``.git`` suffixes when present.
        """
        base = repo_url.rstrip("/")
        if base.endswith(".git"):
            base = base[:-4]
        return f"{base}/commit/{commit_hash}"
