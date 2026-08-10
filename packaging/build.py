"""配布用の実行ファイルをビルドする。

    .venv\\Scripts\\python.exe packaging\\build.py            # 1フォルダ（既定）
    .venv\\Scripts\\python.exe packaging\\build.py --onefile  # 1ファイル

GUI用（コンソールなし）と CLI用（コンソールあり）の2つを作る。GUI をコンソール付きに
すると黒い窓が残り、CLI をコンソールなしにすると出力が一切見えないため、1つの実行
ファイルでは両立できない。

ビルド後に**実際に実行ファイルを起動して動作を確認する**。パッケージングで最も
起きやすい失敗は「隠れた依存の取りこぼし」で、これは起動してみるまで分からない。

注意: このディレクトリに ``__init__.py`` を置かないこと。PyPI の ``packaging``
（PyInstaller の依存）と名前が衝突し、``python -m PyInstaller`` を実行するときに
``sys.path`` の先頭へ入るこのディレクトリが本物のライブラリを覆い隠してしまう。
"""

from __future__ import annotations

import argparse
import locale
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from inkflow import APP_NAME, __version__  # noqa: E402

PACKAGING_DIR = ROOT / "packaging"
SPEC_PATH = PACKAGING_DIR / "inkflow.spec"
BUILD_DIR = ROOT / "build"
DIST_DIR = ROOT / "dist"

GUI_NAME = "InkFlow"
CLI_NAME = "InkFlow-cli"
BUNDLE_NAME = "InkFlow"

DESCRIPTION = "雑誌記事PDFをKindle向けに再ページ化するツール"

# ビルド後の動作確認。`selftest` は PDF読み込み・画像処理・EPUB書き出し・Qt初期化まで
# 実際に通すので、依存の取りこぼし（特に spec で除外した Qt DLL）を検出できる。
#
# 判定は終了コードと ASCII のマーカーで行う。凍結した実行ファイルの出力は
# コンソールのコードページ（日本語Windowsなら cp932）で書かれるので、日本語の文字列で
# 一致を見るとデコード次第で falseになる。
VERIFY_COMMAND = "selftest"
VERIFY_FAILURE_MARKER = "[NG]"
VERIFY_TIMEOUT = 300

PYINSTALLER_TIMEOUT = 1800


# ---- 純粋な補助関数（テスト対象） ---------------------------------------


def version_tuple(version: str) -> tuple[int, int, int, int]:
    """``1.2.3`` を Windows のバージョンリソース用の4要素に整える。

    ``1.0.0rc1`` のような接尾辞は数字の**先頭部分だけ**を見る。全部の数字を拾うと
    ``(1, 0, 1, 0)`` になり、正式版 ``1.0.0`` より新しい版として比較されてしまう。
    """
    numbers: list[int] = []
    for part in version.split("."):
        matched = re.match(r"\d+", part)
        numbers.append(int(matched.group()) if matched else 0)
    numbers = (numbers + [0, 0, 0, 0])[:4]
    return (numbers[0], numbers[1], numbers[2], numbers[3])


def version_resource(version: str, exe_filename: str, description: str = DESCRIPTION) -> str:
    """PyInstaller が読む Windows バージョンリソースを組み立てる。

    ``041104b0`` は日本語(1041) + Unicode(1200) の組。実行ファイルのプロパティに
    日本語の説明を出すため。
    """
    numbers = version_tuple(version)
    return f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={numbers},
    prodvers={numbers},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('041104b0', [
        StringStruct('FileDescription', '{description}'),
        StringStruct('FileVersion', '{version}'),
        StringStruct('InternalName', '{APP_NAME}'),
        StringStruct('OriginalFilename', '{exe_filename}'),
        StringStruct('ProductName', '{APP_NAME}'),
        StringStruct('ProductVersion', '{version}')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1041, 1200])])
  ]
)
"""


def artifact_paths(onefile: bool, dist_dir: Path = DIST_DIR) -> dict[str, Path]:
    """モードごとの成果物の位置を返す。"""
    if onefile:
        return {
            "gui": dist_dir / f"{GUI_NAME}.exe",
            "cli": dist_dir / f"{CLI_NAME}.exe",
            "bundle": dist_dir,
        }
    bundle = dist_dir / BUNDLE_NAME
    return {
        "gui": bundle / f"{GUI_NAME}.exe",
        "cli": bundle / f"{CLI_NAME}.exe",
        "bundle": bundle,
    }


def format_size(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    return f"{num_bytes / (1024 * 1024):.1f} MB"


def decode_console(data: bytes) -> str:
    """子プロセスの出力を復号する。

    凍結した実行ファイルはコンソールのコードページ（日本語Windowsなら cp932）で
    書き出す。PyInstaller のランタイムは ``PYTHONIOENCODING`` を無視するので、
    こちら側で合わせる。
    """
    for encoding in (locale.getpreferredencoding(False), "utf-8"):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


def directory_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def zip_name(version: str = __version__) -> str:
    return f"{BUNDLE_NAME}-{version}-win64.zip"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="build.py", description="InkFlow の配布用実行ファイルをビルドする。"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--onedir",
        dest="onefile",
        action="store_false",
        help="1フォルダにまとめる（既定。起動が速い）",
    )
    mode.add_argument(
        "--onefile",
        dest="onefile",
        action="store_true",
        help="1ファイルにまとめる（コピーは簡単だが、起動のたびに展開するので遅い）",
    )
    parser.set_defaults(onefile=False)
    parser.add_argument("--no-zip", action="store_true", help="配布用ZIPを作らない")
    parser.add_argument("--no-verify", action="store_true", help="ビルド後の動作確認を省く")
    parser.add_argument(
        "--clean", action="store_true", help="build/ と dist/ を消してからビルドする"
    )
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


# ---- ビルド手順 ---------------------------------------------------------


def check_pyinstaller() -> str:
    """PyInstaller の版を返す。無ければ導入方法を示して終了する。"""
    try:
        import PyInstaller
    except ImportError:
        raise SystemExit(
            "PyInstaller が見つかりません。次のコマンドで導入してください:\n"
            "  .venv\\Scripts\\python.exe -m pip install -r requirements-dev.txt"
        ) from None
    return PyInstaller.__version__


def generate_icon() -> Path | None:
    """アイコンを生成する。失敗してもビルドは止めない（装飾のため）。"""
    try:
        from inkflow import appicon

        return appicon.write_ico(BUILD_DIR / "inkflow.ico")
    except Exception as e:  # noqa: BLE001
        print(f"警告: アイコンを生成できませんでした（アイコンなしで続行）: {e}", file=sys.stderr)
        return None


def write_version_files() -> tuple[Path, Path]:
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    gui_path = BUILD_DIR / "version_gui.txt"
    cli_path = BUILD_DIR / "version_cli.txt"
    gui_path.write_text(version_resource(__version__, f"{GUI_NAME}.exe"), encoding="utf-8")
    cli_path.write_text(version_resource(__version__, f"{CLI_NAME}.exe"), encoding="utf-8")
    return (gui_path, cli_path)


def spec_environment(onefile: bool, icon: Path | None, versions: tuple[Path, Path]) -> dict[str, str]:
    environment = dict(os.environ)
    environment["INKFLOW_ONEFILE"] = "1" if onefile else "0"
    environment["INKFLOW_ICON"] = str(icon) if icon else ""
    environment["INKFLOW_VERSION_GUI"] = str(versions[0])
    environment["INKFLOW_VERSION_CLI"] = str(versions[1])
    environment["INKFLOW_GUI_NAME"] = GUI_NAME
    environment["INKFLOW_CLI_NAME"] = CLI_NAME
    environment["INKFLOW_BUNDLE_NAME"] = BUNDLE_NAME
    return environment


def run_pyinstaller(onefile: bool, icon: Path | None, versions: tuple[Path, Path]) -> None:
    """PyInstaller をサブプロセスで実行する。

    同一プロセスで ``PyInstaller.__main__.run()`` を呼ぶと、解析対象の inkflow を
    import 済みの状態で走ることになり、副作用が読みにくい。
    """
    # spec を渡すときは makespec 系のオプション（--specpath など）を併用できない。
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--distpath",
        str(DIST_DIR),
        "--workpath",
        str(BUILD_DIR / "pyinstaller"),
        str(SPEC_PATH),
    ]
    print(f"$ {' '.join(command)}\n")
    result = subprocess.run(
        command,
        cwd=str(ROOT),
        env=spec_environment(onefile, icon, versions),
        timeout=PYINSTALLER_TIMEOUT,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"PyInstaller が失敗しました（終了コード {result.returncode}）")


def verify_executables(paths: dict[str, Path]) -> None:
    """生成した実行ファイルを実際に起動して確認する。"""
    cli_exe = paths["cli"]
    gui_exe = paths["gui"]
    for exe in (cli_exe, gui_exe):
        if not exe.is_file():
            raise SystemExit(f"実行ファイルが生成されていません: {exe}")

    print(f"動作確認: {cli_exe.name} {VERIFY_COMMAND}")
    result = subprocess.run(
        [str(cli_exe), VERIFY_COMMAND],
        capture_output=True,
        timeout=VERIFY_TIMEOUT,
        check=False,
    )
    output = decode_console(result.stdout) + decode_console(result.stderr)
    print("\n".join(f"  | {line}" for line in output.splitlines() if line.strip()))

    if result.returncode != 0:
        raise SystemExit(
            f"CLI 実行ファイルの自己診断が失敗しました（終了コード {result.returncode}）"
        )
    if VERIFY_FAILURE_MARKER in output:
        raise SystemExit("CLI 実行ファイルの自己診断に失敗した項目があります")

    # GUI 版はコンソールを持たないので出力は見えない。起動して正常終了すれば、
    # 依存の取りこぼしが無いことは確かめられる。
    print(f"動作確認: {gui_exe.name}（コンソールなし・終了コードのみ確認）")
    gui_result = subprocess.run(
        [str(gui_exe), VERIFY_COMMAND],
        capture_output=True,
        timeout=VERIFY_TIMEOUT,
        check=False,
    )
    if gui_result.returncode != 0:
        raise SystemExit(
            f"GUI 実行ファイルが異常終了しました（終了コード {gui_result.returncode}）"
        )
    print("動作確認: OK\n")


def make_zip(bundle_dir: Path) -> Path:
    archive = DIST_DIR / zip_name()
    if archive.exists():
        archive.unlink()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in sorted(bundle_dir.rglob("*")):
            if item.is_file():
                zf.write(item, Path(BUNDLE_NAME) / item.relative_to(bundle_dir))
    return archive


def clean() -> None:
    for directory in (BUILD_DIR, DIST_DIR):
        if directory.exists():
            shutil.rmtree(directory)
            print(f"削除しました: {directory}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    pyinstaller_version = check_pyinstaller()
    print(f"{APP_NAME} {__version__} をビルドします")
    print(f"  モード      : {'onefile（1ファイル）' if args.onefile else 'onedir（1フォルダ）'}")
    print(f"  PyInstaller : {pyinstaller_version}")
    print(f"  Python      : {sys.version.split()[0]}\n")

    if args.clean:
        clean()

    icon = generate_icon()
    versions = write_version_files()
    run_pyinstaller(args.onefile, icon, versions)

    paths = artifact_paths(args.onefile)
    if not args.no_verify:
        verify_executables(paths)

    print("生成物:")
    for label, key in (("GUI", "gui"), ("CLI", "cli")):
        path = paths[key]
        print(f"  {label}: {path}  ({format_size(directory_size(path))})")
    if not args.onefile:
        print(f"  合計: {paths['bundle']}  ({format_size(directory_size(paths['bundle']))})")

    if not args.onefile and not args.no_zip:
        archive = make_zip(paths["bundle"])
        print(f"  ZIP : {archive}  ({format_size(directory_size(archive))})")

    print("\n完了しました。")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit as e:
        if isinstance(e.code, str):
            print(f"エラー: {e.code}", file=sys.stderr)
            sys.exit(1)
        raise
