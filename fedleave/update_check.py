from __future__ import annotations

import json
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from . import __version__


REPOSITORY_URL = "https://github.com/joshua-guthrie/fedleave"
LATEST_RELEASE_API = f"https://api.github.com/repos/joshua-guthrie/fedleave/releases/latest"
LATEST_RELEASE_URL = f"{REPOSITORY_URL}/releases/latest"


def _version_parts(value: str) -> tuple[int, ...]:
    match = re.match(r"^v?(\d+(?:\.\d+)*)", value.strip())
    if not match:
        raise ValueError(f"Unrecognized version: {value}")
    return tuple(int(part) for part in match.group(1).split("."))


def check_for_updates(*, current_version: str = __version__, opener=urlopen, timeout: float = 5.0) -> dict[str, Any]:
    request = Request(
        LATEST_RELEASE_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"FedLeave/{current_version}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with opener(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        latest = str(payload.get("tag_name") or "").lstrip("v")
        if not latest:
            raise ValueError("The latest release did not include a version tag.")
        update_available = _version_parts(latest) > _version_parts(current_version)
        release_url = str(payload.get("html_url") or LATEST_RELEASE_URL)
        assets = [
            {"name": str(asset.get("name", "")), "url": str(asset.get("browser_download_url", ""))}
            for asset in payload.get("assets", [])
            if isinstance(asset, dict) and asset.get("browser_download_url")
        ]
        return {
            "status": "ok",
            "current_version": current_version,
            "latest_version": latest,
            "update_available": update_available,
            "release_url": release_url,
            "assets": assets,
            "instructions": (
                "Open the release page, download the package for your operating system, close all "
                "FedLeave applications, and run the included LinuxInstall.sh or WindowsInstall.bat installer. "
                "Your leave data directory is preserved during an upgrade."
            ),
        }
    except (HTTPError, URLError, OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "status": "unavailable",
            "current_version": current_version,
            "latest_version": None,
            "update_available": False,
            "release_url": LATEST_RELEASE_URL,
            "message": f"Could not check GitHub for updates: {exc}",
        }
