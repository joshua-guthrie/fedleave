from importlib.metadata import version

import pytest
from packaging.version import Version


@pytest.mark.parametrize(
    "name,minimum", [("Pillow", "13.0.0"), ("icalendar", "7.1.3"), ("opentelemetry-api", "1.45.2")]
)
def test_loaded_environment_excludes_audited_vulnerable_versions(name, minimum):
    assert Version(version(name)) >= Version(minimum)
