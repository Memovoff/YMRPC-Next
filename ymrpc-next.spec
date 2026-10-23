# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller: portable-сборка YMRPC Next одним файлом."""

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve()
ASSETS = ROOT / "src" / "ymrpc" / "assets"
NO_WEBENGINE = os.environ.get("YMRPC_BUILD_NO_WEBENGINE") == "1"

hiddenimports = collect_submodules("winrt")
hiddenimports += ["yandex_music"]

excludes = ["tkinter", "unittest", "pytest", "_pytest", "pydoc_data"]
if NO_WEBENGINE:
    excludes += [
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineQuick",
        "PySide6.QtWebChannel",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtQuickWidgets",
    ]

a = Analysis(
    [str(ROOT / "run.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=[(str(ASSETS), "ymrpc/assets")],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="YMRPC-Next",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ASSETS / "icon.ico"),
    version=str(ROOT / "packaging" / "version_info.txt"),
)
