from importlib.metadata import version

import pytest
from packaging.version import Version


@pytest.mark.parametrize("name,minimum", [("opentelemetry-api", "1.45.2")])
def test_loaded_environment_excludes_audited_vulnerable_versions(name, minimum):
    assert Version(version(name)) >= Version(minimum)
