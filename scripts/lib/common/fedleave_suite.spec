# -*- mode: python ; coding: utf-8 -*-
"""Build all FedLeave entry points into one shared onedir collection."""

import argparse
import json
from pathlib import Path

from PyInstaller.utils.hooks import collect_all


parser = argparse.ArgumentParser()
parser.add_argument("--config", required=True)
options = parser.parse_args()
config = json.loads(Path(options.config).read_text(encoding="utf-8"))

builds = []
for target in config["targets"]:
    datas = [tuple(item) for item in target["datas"]]
    binaries = []
    hidden_imports = list(target["hidden_imports"])
    for package in target["collect_all"]:
        package_datas, package_binaries, package_imports = collect_all(package)
        datas.extend(package_datas)
        binaries.extend(package_binaries)
        hidden_imports.extend(package_imports)

    analysis = Analysis(
        [target["entry"]],
        pathex=[config["repo_root"]],
        binaries=binaries,
        datas=datas,
        hiddenimports=hidden_imports,
        hookspath=[],
        hooksconfig={},
        runtime_hooks=[],
        excludes=config["excludes"],
        noarchive=False,
        optimize=1,
    )
    pyz = PYZ(analysis.pure)
    executable = EXE(
        pyz,
        analysis.scripts,
        [],
        exclude_binaries=True,
        name=target["name"],
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=target["console"],
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=[target["icon"]] if target["icon"] else None,
    )
    builds.append((analysis, executable))

collection_inputs = []
for analysis, executable in builds:
    collection_inputs.extend((executable, analysis.binaries, analysis.datas))

suite = COLLECT(
    *collection_inputs,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=config["suite_name"],
)
