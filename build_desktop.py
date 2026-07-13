#!/usr/bin/env python3
"""
build_desktop.py — Produce a standalone build of the desktop app with PyInstaller.

    source .venv/bin/activate
    python build_desktop.py

The finished program lands in  dist/EpubMaker/  (a folder you can zip and hand
to anyone on the SAME operating system — build on Windows for a Windows build,
on macOS for a macOS build, on Linux for a Linux build).

Notes
-----
* We use --onedir (a folder) rather than --onefile: it starts faster and is
  more reliable with Qt. Zip the whole dist/EpubMaker folder to distribute.
* ebooklib ships data files that must be bundled explicitly (--collect-data).
"""
from __future__ import annotations

import PyInstaller.__main__

PyInstaller.__main__.run([
    "desktop_app.py",
    "--name", "EpubMaker",
    "--windowed",              # no console window (GUI app)
    "--noconfirm",             # overwrite a previous build without prompting
    "--clean",
    "--collect-data", "ebooklib",   # bundle ebooklib's template/data files
    "--collect-submodules", "docx",
])
