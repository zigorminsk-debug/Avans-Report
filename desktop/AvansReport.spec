# -*- mode: python ; coding: utf-8 -*-
"""Сборка настольной версии (PyInstaller)."""

import os
import sys

from PyInstaller.utils.hooks import collect_submodules

root = os.path.abspath(os.path.join(SPECPATH, ".."))
icon_path = os.path.join(root, "installer", "windows", "app.ico")

datas = [
    (os.path.join(root, "app", "static"), os.path.join("app", "static")),
    (os.path.join(root, "app", "assets"), os.path.join("app", "assets")),
]

hiddenimports = collect_submodules("uvicorn") + [
    "app.main",
    "app.updates",
    "app.excel_export",
    "app.pdf_export",
    "email.mime.multipart",
    "email.mime.base",
]

a = Analysis(
    [os.path.join(root, "desktop", "launcher.py")],
    pathex=[root],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # PIL (Pillow) нужен reportlab — исключать нельзя.
    excludes=["tkinter", "matplotlib", "numpy", "pandas", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AvansReport",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=icon_path if os.path.exists(icon_path) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="AvansReport",
)
