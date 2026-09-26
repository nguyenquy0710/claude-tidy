# PyInstaller build spec for Claude Tidy.
#
# --onedir, not --onefile: the T22 spike measured onefile cold-start at
# 3.6-5.4s (unpacking into %TEMP%\_MEIxxxx on every launch) against onedir's
# ~1-2.2s, crossing the >3s threshold the roadmap set for switching (see
# plans/2026-09-25-ttkbootstrap-ui-migration-planning.md, Risk 3 / Q2). The
# T33 pywebview spike (plans/2026-09-25-pywebview-ui-migration-planning.md)
# re-confirmed onedir works with the pywebview/pythonnet/clr_loader stack
# before switching the UI over.
#
# pywebview on Windows uses WinForms via pythonnet (clr_loader locates the
# .NET runtime) — collect_all() is required for all three, not just
# collect_data_files(), because the native Python.Runtime.dll and
# WebView2Loader.dll binaries must be bundled alongside the Python-level data.
#
# Build: .venv/Scripts/pyinstaller claude-tidy.spec
# Output: dist/claude-tidy/claude-tidy.exe (ship the whole claude-tidy/ folder)

from PyInstaller.utils.hooks import collect_all

block_cipher = None

datas = [("claude_tidy/webui/static", "claude_tidy/webui/static")]
binaries = []
hiddenimports = []
for pkg in ("webview", "clr_loader", "pythonnet"):
    pkg_datas, pkg_binaries, pkg_hiddenimports = collect_all(pkg)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hiddenimports

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="claude-tidy",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # --windowed: no console window behind the pywebview UI
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="claude-tidy",
)
