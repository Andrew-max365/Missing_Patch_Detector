"""Tests for cve_resolver.py – all network calls are mocked."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from missing_patch_detector.cve_resolver import (
    CVEFetchError,
    CVENotFoundError,
    CVEResolver,
    CommitRef,
)

# ---------------------------------------------------------------------------
# Sample OSV API response for a fictional CVE
# ---------------------------------------------------------------------------

OSV_SAMPLE = {
    "id": "CVE-2021-99999",
    "summary": "Remote code execution via crafted input",
    "affected": [
        {
            "package": {"ecosystem": "PyPI", "name": "example-lib"},
            "ranges": [
                {
                    "type": "GIT",
                    "repo": "https://github.com/example/example-lib",
                    "events": [
                        {"introduced": "0"},
                        {"fixed": "abc1234def5678"},
                    ],
                }
            ],
        }
    ],
}

OSV_MULTI_FIX = {
    "id": "CVE-2022-00001",
    "summary": "Buffer overflow",
    "affected": [
        {
            "package": {"ecosystem": "npm", "name": "some-pkg"},
            "ranges": [
                {
                    "type": "GIT",
                    "repo": "https://github.com/example/some-pkg.git",
                    "events": [
                        {"introduced": "0"},
                        {"fixed": "aabbcc1"},
                        {"fixed": "ddeeff2"},
                    ],
                }
            ],
        }
    ],
}

OSV_NO_GIT = {
    "id": "CVE-2023-11111",
    "summary": "Only semver ranges, no git commits",
    "affected": [
        {
            "package": {"ecosystem": "PyPI", "name": "other-lib"},
            "ranges": [
                {
                    "type": "SEMVER",
                    "events": [{"introduced": "0"}, {"fixed": "1.2.3"}],
                }
            ],
        }
    ],
}


# ---------------------------------------------------------------------------
# _build_commit_url
# ---------------------------------------------------------------------------


def test_build_commit_url_github() -> None:
    url = CVEResolver._build_commit_url(
        "https://github.com/example/example-lib", "abc1234"
    )
    assert url == "https://github.com/example/example-lib/commit/abc1234"


def test_build_commit_url_strips_dot_git() -> None:
    url = CVEResolver._build_commit_url(
        "https://github.com/example/some-pkg.git", "ddeeff2"
    )
    assert url == "https://github.com/example/some-pkg/commit/ddeeff2"


def test_build_commit_url_trailing_slash() -> None:
    url = CVEResolver._build_commit_url(
        "https://gitlab.com/example/repo/", "cafebabe"
    )
    assert url == "https://gitlab.com/example/repo/commit/cafebabe"


# ---------------------------------------------------------------------------
# _extract_commit_refs
# ---------------------------------------------------------------------------


def test_extract_commit_refs_single_fix() -> None:
    refs = CVEResolver._extract_commit_refs(
        "CVE-2021-99999",
        "Remote code execution via crafted input",
        OSV_SAMPLE["affected"],
    )
    assert len(refs) == 1
    ref = refs[0]
    assert isinstance(ref, CommitRef)
    assert ref.cve_id == "CVE-2021-99999"
    assert ref.commit_hash == "abc1234def5678"
    assert ref.repo_url == "https://github.com/example/example-lib"
    assert ref.commit_url == "https://github.com/example/example-lib/commit/abc1234def5678"
    assert ref.ecosystem == "PyPI"
    assert ref.package == "example-lib"
    assert ref.summary == "Remote code execution via crafted input"


def test_extract_commit_refs_multiple_fixes() -> None:
    refs = CVEResolver._extract_commit_refs(
        "CVE-2022-00001", "Buffer overflow", OSV_MULTI_FIX["affected"]
    )
    assert len(refs) == 2
    hashes = {r.commit_hash for r in refs}
    assert hashes == {"aabbcc1", "ddeeff2"}
    # .git suffix should be stripped in commit_url
    for ref in refs:
        assert ".git/commit/" not in ref.commit_url


def test_extract_commit_refs_no_git_ranges_returns_empty() -> None:
    refs = CVEResolver._extract_commit_refs(
        "CVE-2023-11111", "semver only", OSV_NO_GIT["affected"]
    )
    assert refs == []


def test_extract_commit_refs_empty_affected() -> None:
    refs = CVEResolver._extract_commit_refs("CVE-0000-00000", "", [])
    assert refs == []


# ---------------------------------------------------------------------------
# resolve() – full method with mocked HTTP
# ---------------------------------------------------------------------------


def _mock_response(status_code: int, body: dict) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        from requests import HTTPError

        resp.raise_for_status.side_effect = HTTPError(response=resp)
    return resp


def test_resolve_returns_commit_refs() -> None:
    with patch("requests.get", return_value=_mock_response(200, OSV_SAMPLE)):
        resolver = CVEResolver()
        refs = resolver.resolve("CVE-2021-99999")

    assert len(refs) == 1
    assert refs[0].commit_hash == "abc1234def5678"


def test_resolve_404_raises_cve_not_found() -> None:
    not_found = MagicMock()
    not_found.status_code = 404

    with patch("requests.get", return_value=not_found):
        resolver = CVEResolver()
        with pytest.raises(CVENotFoundError, match="CVE-9999-9999"):
            resolver.resolve("CVE-9999-9999")


def test_resolve_500_raises_cve_fetch_error() -> None:
    with patch("requests.get", return_value=_mock_response(500, {})):
        resolver = CVEResolver()
        with pytest.raises(CVEFetchError):
            resolver.resolve("CVE-2021-99999")


def test_resolve_network_error_raises_cve_fetch_error() -> None:
    import requests as req_module

    with patch("requests.get", side_effect=req_module.RequestException("timeout")):
        resolver = CVEResolver()
        with pytest.raises(CVEFetchError, match="timeout"):
            resolver.resolve("CVE-2021-99999")


def test_resolve_invalid_json_raises_cve_fetch_error() -> None:
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.side_effect = ValueError("bad json")

    with patch("requests.get", return_value=resp):
        resolver = CVEResolver()
        with pytest.raises(CVEFetchError, match="Invalid JSON"):
            resolver.resolve("CVE-2021-99999")


def test_resolve_no_git_refs_returns_empty() -> None:
    with patch("requests.get", return_value=_mock_response(200, OSV_NO_GIT)):
        resolver = CVEResolver()
        refs = resolver.resolve("CVE-2023-11111")

    assert refs == []
