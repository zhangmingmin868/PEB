# PyInstaller spec for LabDream Version 1.0 (Windows and macOS)
# Build:  pyinstaller --noconfirm --clean labdream.spec
import sys

block_cipher = None
ICON = "assets/labdream.ico" if sys.platform == "win32" else "assets/labdream.icns"
import os
if not os.path.exists(ICON):
    ICON = None

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[("assets/labdream.png", "assets")],
    hiddenimports=["PySide6.QtPrintSupport"],
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtQml", "PySide6.QtQuick",
              "PySide6.Qt3DCore", "PySide6.QtMultimedia"],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LabDream",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=ICON,
    version="version_info.txt" if sys.platform == "win32" else None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="LabDream")

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="LabDream.app",
        icon=ICON,
        bundle_identifier="com.labdream.app",
        info_plist={
            "CFBundleName": "LabDream",
            "CFBundleDisplayName": "LabDream",
            "CFBundleShortVersionString": "1.0",
            "CFBundleVersion": "1.0",
            "NSHighResolutionCapable": True,
        },
    )
