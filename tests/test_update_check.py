from __future__ import annotations

import json

from fedleave.update_check import check_for_updates


class _Response:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_update_check_reports_new_release_and_instructions() -> None:
    requests = []

    def opener(request, timeout):
        requests.append((request, timeout))
        return _Response({"tag_name": "v0.3.0", "html_url": "https://github.com/example/release", "assets": []})

    result = check_for_updates(current_version="0.2.0", opener=opener)

    assert result["status"] == "ok"
    assert result["update_available"] is True
    assert result["latest_version"] == "0.3.0"
    assert "LinuxInstall.sh" in result["instructions"]
    assert requests[0][0].get_header("User-agent") == "FedLeave/0.2.0"


def test_update_check_handles_offline_without_raising() -> None:
    def opener(request, timeout):
        raise OSError("offline")

    result = check_for_updates(current_version="0.2.0", opener=opener)

    assert result["status"] == "unavailable"
    assert result["update_available"] is False
    assert "offline" in result["message"]
