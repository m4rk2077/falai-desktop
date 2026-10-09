# -*- mode: python ; coding: utf-8 -*-

import glob
import os
import sys


def _collect_vc_runtime_binaries():
    """Bundle VC runtime DLLs for better portability on tester machines."""
    out = []
    base = getattr(sys, "base_prefix", "") or sys.prefix
    candidates = []

    # Python installer typically ships these in the root of base_prefix.
    for pat in ("vcruntime140*.dll", "msvcp140*.dll", "concrt140.dll"):
        candidates += glob.glob(os.path.join(base, pat))

    # Some environments keep them under the executable dir.
    try:
        exe_dir = os.path.dirname(sys.executable)
        for pat in ("vcruntime140*.dll", "msvcp140*.dll", "concrt140.dll"):
            candidates += glob.glob(os.path.join(exe_dir, pat))
    except Exception:
        pass

    seen = set()
    for p in candidates:
        try:
            lp = os.path.normcase(os.path.normpath(p))
        except Exception:
            lp = p
        if lp in seen:
            continue
        seen.add(lp)
        if os.path.isfile(p):
            out.append((p, "."))
    return out


a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=_collect_vc_runtime_binaries(),
    # Include runtime assets (icons, fonts, sounds) and UI logos.
    datas=[
        ("assets", "assets"),
        ("logos e files design/ui logos", "logos e files design/ui logos"),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# onedir build (EXE + COLLECT) to avoid _MEI temp extraction failures on some machines.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FALAI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=["assets\\icons\\app.ico"],
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="FALAI",
)
