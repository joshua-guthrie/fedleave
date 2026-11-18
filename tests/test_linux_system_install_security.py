"""Root-only isolated deployment check, invoked explicitly by Distribution CI."""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from test_release_packaging import BOOTSTRAP, _fake_bundle, _load_packaging_module, _rolling_linux_assets


@pytest.mark.skipif(
    os.name != "posix" or not hasattr(os, "geteuid") or os.geteuid() != 0,
    reason="Distribution runs this test explicitly with sudo in an isolated directory",
)
def test_privileged_bootstrap_removes_ordinary_user_write_access():
    uid = int(os.environ["FEDLEAVE_TEST_UID"])
    gid = int(os.environ["FEDLEAVE_TEST_GID"])
    assert uid != 0
    for command in ("setpriv", "sudo", "setfacl", "getfacl"):
        assert shutil.which(command), command
    with tempfile.TemporaryDirectory(prefix="fedleave-security-test-", dir="/var/lib") as directory:
        root = Path(directory)
        root.chmod(0o755)
        package = _load_packaging_module()
        bundle = _fake_bundle(package, root / "bundle")
        (bundle / "shared-runtime").symlink_to("_internal/runtime.dat")
        assets = root / "assets"
        _rolling_linux_assets(package, bundle, assets, "0.2.0")
        for mode in ("user", "root"):
            target = root / mode
            command = [
                str(BOOTSTRAP),
                "--unattended",
                "--asset-base-url",
                assets.as_uri(),
                "--install-root",
                str(target),
                "--bin-dir",
                str(root / (mode + "-bin")),
            ]
            if mode == "user":
                command = ["setpriv", "--reuid", str(uid), "--regid", str(gid), "--clear-groups", *command]
            result = subprocess.run(command, capture_output=True, text=True, timeout=90)
            assert result.returncode == 0, result.stdout + result.stderr
            release = (target / "current").resolve()
            for path in [release, *release.rglob("*")]:
                metadata = path.lstat()
                assert metadata.st_uid == metadata.st_gid == 0, path
                if not path.is_symlink():
                    assert metadata.st_mode & 0o6022 == 0, path
            probe = subprocess.run(
                [
                    "setpriv",
                    "--reuid",
                    str(uid),
                    "--regid",
                    str(gid),
                    "--clear-groups",
                    "test",
                    "-w",
                    str(release / "fedleave"),
                ]
            )
            assert probe.returncode != 0
            assert (release / "shared-runtime").read_bytes() == b"embedded runtime"
            acl = subprocess.check_output(["getfacl", "-cp", str(release)], text=True)
            assert not any(line.startswith(("default:", f"user:{uid}:")) for line in acl.splitlines())
