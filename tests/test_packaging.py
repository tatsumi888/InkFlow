"""ビルドスクリプトの純粋な部分のテスト。

実ビルドそのものはテストに含めない（数分かかるため）。ビルドの成否は
`packaging/build.py` が生成物を実際に起動して確認する。
"""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def load_build_module():
    """`packaging/build.py` をモジュールとして読み込む（パッケージではないため）。"""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location(
        "inkflow_build", ROOT / "packaging" / "build.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build = load_build_module()


# ---- バージョンリソース -------------------------------------------------


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("1.0.0", (1, 0, 0, 0)),
        ("2.13.5", (2, 13, 5, 0)),
        ("1.2.3.4", (1, 2, 3, 4)),
        ("1.0", (1, 0, 0, 0)),
        ("1.0.0rc1", (1, 0, 0, 0)),  # 接尾辞の数字を拾って正式版より新しくしない
        ("2.0.0b3", (2, 0, 0, 0)),
        ("", (0, 0, 0, 0)),
    ],
)
def test_version_tuple(version, expected):
    assert build.version_tuple(version) == expected


def test_version_resource_contains_version():
    text = build.version_resource("3.1.4", "InkFlow.exe")
    assert "filevers=(3, 1, 4, 0)" in text
    assert "'FileVersion', '3.1.4'" in text
    assert "'ProductVersion', '3.1.4'" in text


def test_version_resource_uses_the_exe_name():
    assert "'OriginalFilename', 'InkFlow-cli.exe'" in build.version_resource(
        "1.0.0", "InkFlow-cli.exe"
    )


def test_version_resource_is_japanese_unicode():
    assert "041104b0" in build.version_resource("1.0.0", "InkFlow.exe")
    assert "[1041, 1200]" in build.version_resource("1.0.0", "InkFlow.exe")


def test_version_resource_is_valid_python_expression():
    """PyInstaller はこのファイルを Python として評価する。構文が壊れていないこと。"""
    import ast

    ast.parse(build.version_resource("1.0.0", "InkFlow.exe"))


# ---- 成果物のパス -------------------------------------------------------


def test_artifact_paths_onedir(tmp_path):
    paths = build.artifact_paths(onefile=False, dist_dir=tmp_path)
    assert paths["bundle"] == tmp_path / "InkFlow"
    assert paths["gui"] == tmp_path / "InkFlow" / "InkFlow.exe"
    assert paths["cli"] == tmp_path / "InkFlow" / "InkFlow-cli.exe"


def test_artifact_paths_onefile(tmp_path):
    paths = build.artifact_paths(onefile=True, dist_dir=tmp_path)
    assert paths["gui"] == tmp_path / "InkFlow.exe"
    assert paths["cli"] == tmp_path / "InkFlow-cli.exe"
    assert paths["bundle"] == tmp_path


def test_artifact_paths_differ_by_mode(tmp_path):
    onedir = build.artifact_paths(onefile=False, dist_dir=tmp_path)
    onefile = build.artifact_paths(onefile=True, dist_dir=tmp_path)
    assert onedir["gui"] != onefile["gui"]


# ---- サイズ -------------------------------------------------------------


@pytest.mark.parametrize(
    ("num_bytes", "expected"),
    [
        (0, "0 B"),
        (512, "512 B"),
        (1024, "1.0 KB"),
        (1536, "1.5 KB"),
        (1024 * 1024, "1.0 MB"),
        (int(1024 * 1024 * 12.34), "12.3 MB"),
    ],
)
def test_format_size(num_bytes, expected):
    assert build.format_size(num_bytes) == expected


def test_directory_size_of_file(tmp_path):
    target = tmp_path / "a.bin"
    target.write_bytes(b"x" * 100)
    assert build.directory_size(target) == 100


def test_directory_size_recurses(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.bin").write_bytes(b"x" * 100)
    (tmp_path / "sub" / "b.bin").write_bytes(b"y" * 50)
    assert build.directory_size(tmp_path) == 150


def test_zip_name_includes_version():
    from inkflow import __version__

    assert build.zip_name() == f"InkFlow-{__version__}-win64.zip"
    assert build.zip_name("9.9.9") == "InkFlow-9.9.9-win64.zip"


# ---- 引数 ---------------------------------------------------------------


def test_default_mode_is_onedir():
    assert build.parse_args([]).onefile is False


def test_onefile_flag():
    assert build.parse_args(["--onefile"]).onefile is True


def test_onedir_flag():
    assert build.parse_args(["--onedir"]).onefile is False


def test_modes_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        build.parse_args(["--onefile", "--onedir"])


def test_optional_flags():
    args = build.parse_args(["--no-zip", "--no-verify", "--clean"])
    assert args.no_zip is True
    assert args.no_verify is True
    assert args.clean is True


# ---- spec に渡す環境変数 ------------------------------------------------


def test_spec_environment_onefile_flag(tmp_path):
    versions = (tmp_path / "gui.txt", tmp_path / "cli.txt")
    onefile = build.spec_environment(True, None, versions)
    onedir = build.spec_environment(False, None, versions)
    assert onefile["INKFLOW_ONEFILE"] == "1"
    assert onedir["INKFLOW_ONEFILE"] == "0"


def test_spec_environment_without_icon(tmp_path):
    versions = (tmp_path / "gui.txt", tmp_path / "cli.txt")
    assert build.spec_environment(False, None, versions)["INKFLOW_ICON"] == ""


def test_spec_environment_passes_names(tmp_path):
    versions = (tmp_path / "gui.txt", tmp_path / "cli.txt")
    environment = build.spec_environment(False, tmp_path / "i.ico", versions)
    assert environment["INKFLOW_GUI_NAME"] == "InkFlow"
    assert environment["INKFLOW_CLI_NAME"] == "InkFlow-cli"
    assert environment["INKFLOW_ICON"].endswith("i.ico")


# ---- ZIP ----------------------------------------------------------------


def test_make_zip_puts_files_under_the_bundle_name(tmp_path, monkeypatch):
    bundle = tmp_path / "InkFlow"
    (bundle / "_internal").mkdir(parents=True)
    (bundle / "InkFlow.exe").write_bytes(b"exe")
    (bundle / "_internal" / "lib.dll").write_bytes(b"dll")

    monkeypatch.setattr(build, "DIST_DIR", tmp_path)
    archive = build.make_zip(bundle)

    import zipfile

    with zipfile.ZipFile(archive) as zf:
        names = set(zf.namelist())
    assert names == {"InkFlow/InkFlow.exe", "InkFlow/_internal/lib.dll"}


# ---- エントリスクリプト -------------------------------------------------


def load_entry_module():
    spec = importlib.util.spec_from_file_location(
        "inkflow_entry", ROOT / "packaging" / "entry.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


entry = load_entry_module()


@pytest.mark.parametrize("command", ["build", "init", "layouts", "devices", "selftest"])
def test_entry_detects_cli_commands(command):
    assert entry._is_cli_invocation([command]) is True


def test_entry_commands_match_the_cli():
    """エントリの振り分け表と CLI のサブコマンドがずれていないこと。"""
    from inkflow.cli import build_parser

    subparsers = [
        action
        for action in build_parser()._actions
        if isinstance(action, __import__("argparse")._SubParsersAction)
    ]
    assert entry.CLI_COMMANDS == set(subparsers[0].choices)


def test_entry_treats_no_arguments_as_gui():
    assert entry._is_cli_invocation([]) is False


def test_entry_treats_paths_as_gui(tmp_path):
    assert entry._is_cli_invocation([str(tmp_path / "article.pdf")]) is False


@pytest.mark.parametrize(
    "dropped",
    [
        r"C:\articles\build",  # ドロップされたパスは常に絶対パス
        r"D:\ClaudeCode\InkFlow\build",
        "/home/user/build",
        r".\build",
    ],
)
def test_entry_treats_dropped_paths_as_gui(dropped):
    assert entry._is_cli_invocation([dropped]) is False


def test_entry_command_is_not_affected_by_the_current_directory(tmp_path, monkeypatch):
    """カレントに同名フォルダがあってもサブコマンドとして扱う。

    ここを「存在したらコマンドではない」と判定すると、PyInstaller の作業用 `build/`
    があるだけで `InkFlow-cli.exe build ...` が GUI 起動に化ける。実際に踏んだ不具合。
    """
    (tmp_path / "build").mkdir()
    monkeypatch.chdir(tmp_path)
    assert entry._is_cli_invocation(["build"]) is True


@pytest.mark.parametrize(
    "executable",
    [r"C:\Apps\InkFlow\InkFlow-cli.exe", "InkFlow-cli.exe", "/opt/inkflow/inkflow-cli"],
)
def test_entry_detects_the_cli_executable(executable):
    assert entry._is_cli_executable(executable) is True


@pytest.mark.parametrize(
    "executable",
    [r"C:\Apps\InkFlow\InkFlow.exe", "InkFlow.exe", "python.exe"],
)
def test_entry_detects_the_gui_executable(executable):
    assert entry._is_cli_executable(executable) is False


def test_cli_executable_without_arguments_still_uses_the_cli(monkeypatch):
    """`InkFlow-cli.exe` をダブルクリックしても GUI が立ち上がらないこと。

    引数だけで振り分けると、CLI用に固めた実行ファイルなのに GUI が起動し、
    背後にコンソール窓が残る。
    """
    assert entry._is_cli_invocation([]) is False  # 引数だけでは判定できない
    assert entry._is_cli_executable("InkFlow-cli.exe") is True  # 名前で補える


def test_entry_ensures_standard_streams(monkeypatch):
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    entry._ensure_standard_streams()
    assert sys.stdout is not None
    assert sys.stderr is not None
    print("落ちないこと")
