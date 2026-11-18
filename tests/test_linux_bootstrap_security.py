"""Exercise bootstrap trust boundaries without touching an installed suite."""

import os
import subprocess

import pytest

from test_release_packaging import BOOTSTRAP, _fake_bundle, _load_packaging_module, _rolling_linux_assets


@pytest.mark.skipif(os.name == "nt", reason="Linux bootstrap")
def test_bootstrap_reinstalls_verified_bytes_before_running_existing_release(tmp_path):
    package = _load_packaging_module()
    bundle = _fake_bundle(package, tmp_path / "bundle")
    assets = tmp_path / "assets"
    _rolling_linux_assets(package, bundle, assets, "0.2.0")
    install = tmp_path / "install"
    existing = install / "releases" / "0.2.0"
    existing.mkdir(parents=True)
    marker = tmp_path / "untrusted-cli-ran"
    cli = existing / "fedleave"
    cli.write_text(f"#!/bin/bash\ntouch '{marker}'\n")
    cli.chmod(0o755)
    result = subprocess.run(
        [
            str(BOOTSTRAP),
            "--unattended",
            "--asset-base-url",
            assets.as_uri(),
            "--install-root",
            str(install),
            "--bin-dir",
            str(tmp_path / "bin"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert not marker.exists()
    assert (install / "current" / "fedleave").read_bytes() == (bundle / "fedleave").read_bytes()


@pytest.mark.skipif(os.name == "nt", reason="Linux bootstrap")
def test_bootstrap_rejects_escaping_bundle_link_before_installation(tmp_path):
    package = _load_packaging_module()
    bundle = _fake_bundle(package, tmp_path / "bundle")
    outside = tmp_path / "outside"
    outside.write_text("untouched")
    (bundle / "escape").symlink_to(outside)
    assets = tmp_path / "assets"
    _rolling_linux_assets(package, bundle, assets, "0.2.0")
    install = tmp_path / "install"
    result = subprocess.run(
        [
            str(BOOTSTRAP),
            "--unattended",
            "--asset-base-url",
            assets.as_uri(),
            "--install-root",
            str(install),
            "--bin-dir",
            str(tmp_path / "bin"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert not (install / "current").exists()
    assert outside.read_text() == "untouched"
