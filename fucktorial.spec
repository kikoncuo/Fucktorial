# PyInstaller spec for Fucktorial GUI.
# Builds:
#   * macOS: dist/Fucktorial.app
#   * Windows: dist/Fucktorial/Fucktorial.exe
# Playwright browsers are NOT bundled — on first run of the "Log In" flow,
# if chromium is missing, the user (or our post-install) runs:
#     python -m playwright install chromium

# ruff: noqa
import sys
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None
is_mac = sys.platform == "darwin"
is_win = sys.platform == "win32"

hidden = []
hidden += collect_submodules("playwright")
hidden += collect_submodules("requests")

datas = []
datas += collect_data_files("playwright", includes=["driver/**"])

a = Analysis(
    ["gui.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Fucktorial",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=is_mac,
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
    name="Fucktorial",
)

if is_mac:
    app = BUNDLE(
        coll,
        name="Fucktorial.app",
        icon=None,
        bundle_identifier="com.kikoncuo.fucktorial",
        info_plist={
            "CFBundleDisplayName": "Fucktorial",
            "CFBundleShortVersionString": "0.1.0",
            "CFBundleVersion": "0.1.0",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
        },
    )
