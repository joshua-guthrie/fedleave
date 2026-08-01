from __future__ import annotations

from fedleave.project_info import OFFICIAL_PROJECT_URL
from fedleave.update_check import check_for_updates

CURRENT_BUILD = "a" * 40
LATEST_BUILD = "b" * 40


class _Response:
    def __init__(self, content: str) -> None:
        self.content = content

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self) -> bytes:
        return self.content.encode("utf-8")


def _build_file(version: str = "0.2.1.dev0+gbbbbbbbb", source_commit: str = LATEST_BUILD) -> str:
    return f"source_commit={source_commit}\nversion={version}\n"


def test_update_check_reports_new_published_build_and_instructions() -> None:
    requests = []

    def opener(request, timeout):
        requests.append((request, timeout))
        return _Response(_build_file())

    result = check_for_updates(
        current_version="0.2.1.dev0+gaaaaaaaa",
        current_build=CURRENT_BUILD,
        opener=opener,
    )

    assert result["status"] == "ok"
    assert result["update_available"] is True
    assert result["current_build"] == CURRENT_BUILD
    assert result["latest_version"] == "0.2.1.dev0+gbbbbbbbb"
    assert result["latest_build"] == LATEST_BUILD
    assert result["release_url"] == OFFICIAL_PROJECT_URL
    assert "official FedLeave project webpage" in result["instructions"]
    assert requests[0][0].full_url.endswith("/installers/BUILD.txt")
    assert requests[0][0].get_header("User-agent") == f"FedLeave/0.2.1.dev0+gaaaaaaaa ({CURRENT_BUILD[:12]})"


def test_update_check_reports_matching_published_build_as_current() -> None:
    def opener(request, timeout):
        return _Response(_build_file(source_commit=CURRENT_BUILD))

    result = check_for_updates(current_version="0.2.1.dev0+gaaaaaaaa", current_build=CURRENT_BUILD, opener=opener)

    assert result["status"] == "ok"
    assert result["update_available"] is False


def test_update_check_upgrades_legacy_installation_without_build_identity() -> None:
    def opener(request, timeout):
        return _Response(_build_file())

    result = check_for_updates(current_version="0.2.1", current_build="", opener=opener)

    assert result["status"] == "ok"
    assert result["current_build"] is None
    assert result["update_available"] is True


def test_update_check_handles_offline_without_raising() -> None:
    def opener(request, timeout):
        raise OSError("offline")

    result = check_for_updates(current_version="0.2.0", current_build=CURRENT_BUILD, opener=opener)

    assert result["status"] == "unavailable"
    assert result["update_available"] is False
    assert result["release_url"] == OFFICIAL_PROJECT_URL
    assert "offline" in result["message"]
