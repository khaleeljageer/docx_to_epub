#!/usr/bin/env python3
"""
build_desktop.py — Produce a standalone build of the desktop app with PyInstaller.

    source .venv/bin/activate
    python build_desktop.py

The finished program is a SINGLE file:
    Windows -> dist/EpubMaker.exe
    Linux   -> dist/EpubMaker
    macOS   -> dist/EpubMaker

Hand that one file to anyone on the SAME operating system (build on Windows for a
Windows build, macOS for macOS, Linux for Linux) — nothing else to install.

Notes
-----
* --onefile bundles everything into one executable, so there is no separate
  dependency folder that could be moved or deleted. Trade-off: a onefile app
  unpacks to a temp folder on launch, so it starts a few seconds slower.
* ebooklib ships data files that must be bundled explicitly (--collect-data).
"""
from __future__ import annotations

import PyInstaller.__main__

PyInstaller.__main__.run([
    "desktop_app.py",
    "--name", "EpubMaker",
    "--onefile",              # one self-contained executable, no side folder
    "--windowed",             # no console window (GUI app)
    "--noconfirm",            # overwrite a previous build without prompting
    "--clean",
    "--collect-data", "ebooklib",   # bundle ebooklib's template/data files
    "--collect-submodules", "docx",
])
