# PyInstaller build spec for Claude Tidy.
#
# --onedir, not --onefile: the T22 spike measured onefile cold-start at
# 3.6-5.4s (unpacking into %TEMP%\_MEIxxxx on every launch) against onedir's
# ~1-2.2s, crossing the >3s threshold the roadmap set for switching (see
# plans/2026-09-25-ttkbootstrap-ui-migration-planning.md, Risk 3 / Q2).
#
# Build: .venv/Scripts/pyinstaller claude-tidy.spec
# Output: dist/claude-tidy/claude-tidy.exe (ship the whole claude-tidy/ folder)

from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=collect_data_files("ttkbootstrap"),
    hiddenimports=[],
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
    console=False,  # --windowed: no console window behind the Tk UI
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
