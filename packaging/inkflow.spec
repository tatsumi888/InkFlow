# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller の仕様。

``packaging/build.py`` から呼ばれる。設定は環境変数で受け取る（spec は Python
スクリプトとして評価されるだけで、引数を直接受け取る手段がないため）。

**Analysis は1つ、EXE は2つ。** GUI用（コンソールなし）とCLI用（コンソールあり）は
同じ ``packaging/entry.py`` から起動するので、解析もライブラリも共有できる。
"""

import os
from pathlib import Path

SPEC_DIR = Path(SPECPATH)  # noqa: F821 - PyInstaller が注入する
ROOT = SPEC_DIR.parent

ONEFILE = os.environ.get("INKFLOW_ONEFILE") == "1"
ICON = os.environ.get("INKFLOW_ICON") or None
VERSION_GUI = os.environ.get("INKFLOW_VERSION_GUI") or None
VERSION_CLI = os.environ.get("INKFLOW_VERSION_CLI") or None
GUI_NAME = os.environ.get("INKFLOW_GUI_NAME", "InkFlow")
CLI_NAME = os.environ.get("INKFLOW_CLI_NAME", "InkFlow-cli")
BUNDLE_NAME = os.environ.get("INKFLOW_BUNDLE_NAME", "InkFlow")

# 使っていない Qt モジュールと開発用パッケージを外してサイズを削る。
# 外しすぎると実行時に落ちるので、ビルド後の動作確認（build.py の verify）で必ず検証する。
EXCLUDES = [
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickWidgets",
    "PySide6.QtQml",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DExtras",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtBluetooth",
    "PySide6.QtPositioning",
    "PySide6.QtSerialPort",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtDesigner",
    "PySide6.QtHelp",
    # 扱うのは PDF と PNG/JPEG だけ。AVIF のデコーダは 7MB あるので外す。
    # Pillow はプラグインの import 失敗を握りつぶすので、外しても壊れない。
    "PIL.AvifImagePlugin",
    "tkinter",
    "unittest",
    "pytest",
    "_pytest",
    "pydoc_data",
]

# Qt の DLL は PySide6 のフックが Python モジュールの除外とは無関係に集めてくるので、
# 解析結果から名前で落とす。落としすぎると実行時に壊れるが、build.py の動作確認が
# `selftest`（Qt を実際に初期化して EPUB まで作る）を走らせるので、そこで検出できる。
#
# opengl32sw.dll は GPU ドライバが使えない環境（一部のVM・RDP）向けのソフトウェア
# OpenGL。QtWidgets は描画に OpenGL を使わないため外している。もし特殊な環境で
# 画面が出ない場合は、この行を消して作り直せば戻る。
EXCLUDED_BINARIES = (
    "opengl32sw.dll",
    "Qt6Quick",
    "Qt6Qml",
    "Qt6Pdf",
    "Qt6Network",
    "Qt63D",
    "Qt6Charts",
    "Qt6DataVisualization",
    "Qt6Multimedia",
    "Qt6WebEngine",
    "Qt6Sql",
    "Qt6Test",
    "Qt6Designer",
    "Qt6Help",
    "Qt6Bluetooth",
    "Qt6Positioning",
    "Qt6SerialPort",
    "Qt6Sensors",
    "Qt6SpatialAudio",
    "_avif",
)


def _is_excluded_binary(destination: str) -> bool:
    name = Path(destination).name
    return any(name.startswith(prefix) or name == prefix for prefix in EXCLUDED_BINARIES)


analysis = Analysis(  # noqa: F821
    [str(SPEC_DIR / "entry.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=0,
)

analysis.binaries = TOC(  # noqa: F821
    entry for entry in analysis.binaries if not _is_excluded_binary(entry[0])
)
analysis.datas = TOC(  # noqa: F821
    entry for entry in analysis.datas if not _is_excluded_binary(entry[0])
)

pyz = PYZ(analysis.pure)  # noqa: F821

if ONEFILE:
    exe_gui = EXE(  # noqa: F821
        pyz,
        analysis.scripts,
        analysis.binaries,
        analysis.datas,
        [],
        name=GUI_NAME,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        runtime_tmpdir=None,
        console=False,
        icon=ICON,
        version=VERSION_GUI,
    )
    exe_cli = EXE(  # noqa: F821
        pyz,
        analysis.scripts,
        analysis.binaries,
        analysis.datas,
        [],
        name=CLI_NAME,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        runtime_tmpdir=None,
        console=True,
        icon=ICON,
        version=VERSION_CLI,
    )
else:
    exe_gui = EXE(  # noqa: F821
        pyz,
        analysis.scripts,
        [],
        exclude_binaries=True,
        name=GUI_NAME,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        icon=ICON,
        version=VERSION_GUI,
    )
    exe_cli = EXE(  # noqa: F821
        pyz,
        analysis.scripts,
        [],
        exclude_binaries=True,
        name=CLI_NAME,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=True,
        icon=ICON,
        version=VERSION_CLI,
    )
    # 2つの EXE を1つの COLLECT に渡すことで、ライブラリを共有した1フォルダになる。
    collected = COLLECT(  # noqa: F821
        exe_gui,
        exe_cli,
        analysis.binaries,
        analysis.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name=BUNDLE_NAME,
    )
