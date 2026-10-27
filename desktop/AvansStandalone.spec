# -*- mode: python ; coding: utf-8 -*-
"""Сборка автономной версии (PyInstaller).

Автономная программа не использует базу данных и вход в систему:
запуск → заполнение → PDF и печать.
"""

import os

from PyInstaller.utils.hooks import collect_submodules

root = os.path.abspath(os.path.join(SPECPATH, ".."))
icon_path = os.path.join(root, "installer", "windows", "standalone.ico")

datas = [
    (os.path.join(root, "standalone", "static"), os.path.join("standalone", "static")),
    (os.path.join(root, "app", "static"), os.path.join("app", "static")),
    (os.path.join(root, "app", "assets", "fonts"), os.path.join("app", "assets", "fonts")),
]

hiddenimports = collect_submodules("uvicorn") + [
    "standalone.server",
    "app.pdf_export",
    "app.updates",
    "app.numberwords",
    "app.reports",
    "reportlab.pdfbase._fontdata",
    "reportlab.platypus",
    "email.mime.multipart",
    "email.mime.base",
]

a = Analysis(
    [os.path.join(root, "standalone", "launcher.py")],
    pathex=[root],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # fastapi и pydantic нужны самому приложению — их исключать нельзя.
    excludes=["tkinter", "matplotlib", "numpy", "pandas", "PIL", "pytest",
              "openpyxl", "sqlalchemy", "PyQt5", "PySide6"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AvansStandalone",
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
    name="AvansStandalone",
)
