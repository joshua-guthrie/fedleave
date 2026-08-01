"""Compare the installed build identity with the published rolling installer."""

from __future__ import annotations

import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from . import __build_commit__, __version__
from .project_info import OFFICIAL_PROJECT_URL

PUBLISHED_BUILD_URL = "https://raw.githubusercontent.com/joshua-guthrie/fedleave/master/installers/BUILD.txt"


def _parse_build_metadata(content: str) -> tuple[str, str]:
    fields: dict[str, str] = {}
    for line in content.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            fields[key.strip()] = value.strip()
    version = fields.get("version", "")
    source_commit = fields.get("source_commit", "").lower()
    if not version:
        raise ValueError("The published installer metadata did not include a version.")
    if not re.fullmatch(r"[0-9a-f]{7,64}", source_commit):
        raise ValueError("The published installer metadata did not include a valid source commit.")
    return version, source_commit


def check_for_updates(
    *,
    current_version: str = __version__,
    current_build: str = __build_commit__,
    opener=urlopen,
    timeout: float = 5.0,
) -> dict[str, Any]:
    """Return update metadata without allowing network failures to escape.

    The injectable opener keeps the network boundary deterministic in tests and
    lets callers treat an unavailable check as a normal result.
    """
    request = Request(
        PUBLISHED_BUILD_URL,
        headers={
            "Accept": "text/plain",
            "User-Agent": f"FedLeave/{current_version} ({current_build[:12] or 'legacy'})",
        },
    )
    try:
        with opener(request, timeout=timeout) as response:
            build_file = response.read().decode("utf-8")
        latest_version, latest_build = _parse_build_metadata(build_file)
        normalized_current_build = current_build.strip().lower()
        # Releases without an embedded build identity predate rolling-build
        # detection and need one upgrade. Thereafter, BUILD.txt changes only
        # after both platform installers have successfully published.
        update_available = not normalized_current_build or latest_build != normalized_current_build
        return {
            "status": "ok",
            "current_version": current_version,
            "current_build": normalized_current_build or None,
            "latest_version": latest_version,
            "latest_build": latest_build,
            "update_available": update_available,
            "release_url": OFFICIAL_PROJECT_URL,
            "assets": [],
            "instructions": (
                "Visit the official FedLeave project webpage for the current Windows and Linux "
                "installation instructions. Close all FedLeave applications before upgrading. "
                "Your leave data directory is preserved during an upgrade."
            ),
        }
    except (HTTPError, URLError, OSError, UnicodeDecodeError, ValueError) as exc:
        return {
            "status": "unavailable",
            "current_version": current_version,
            "current_build": current_build.strip().lower() or None,
            "latest_version": None,
            "latest_build": None,
            "update_available": False,
            "release_url": OFFICIAL_PROJECT_URL,
            "message": f"Could not check for updates: {exc}",
        }
