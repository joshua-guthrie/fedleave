from __future__ import annotations

import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from . import __version__
from .project_info import OFFICIAL_PROJECT_URL


MASTER_VERSION_URL = "https://raw.githubusercontent.com/joshua-guthrie/fedleave/master/pyproject.toml"


def _version_parts(value: str) -> tuple[int, ...]:
    match = re.match(r"^v?(\d+(?:\.\d+)*)", value.strip())
    if not match:
        raise ValueError(f"Unrecognized version: {value}")
    return tuple(int(part) for part in match.group(1).split("."))


def check_for_updates(*, current_version: str = __version__, opener=urlopen, timeout: float = 5.0) -> dict[str, Any]:
    request = Request(
        MASTER_VERSION_URL,
        headers={
            "Accept": "text/plain",
            "User-Agent": f"FedLeave/{current_version}",
        },
    )
    try:
        with opener(request, timeout=timeout) as response:
            project_file = response.read().decode("utf-8")
        match = re.search(r'^version\s*=\s*"([^"]+)"', project_file, re.MULTILINE)
        if not match:
            raise ValueError("The master branch project file did not include a version.")
        latest = match.group(1)
        update_available = _version_parts(latest) > _version_parts(current_version)
        return {
            "status": "ok",
            "current_version": current_version,
            "latest_version": latest,
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
            "latest_version": None,
            "update_available": False,
            "release_url": OFFICIAL_PROJECT_URL,
            "message": f"Could not check for updates: {exc}",
        }
