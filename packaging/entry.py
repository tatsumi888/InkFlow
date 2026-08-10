"""PyInstaller で固める実行ファイルの入口。

GUI と CLI を**同じスクリプト**から起動する。こうしておくと PyInstaller の
``Analysis`` を1つで済ませられ、GUI用（コンソールなし）とCLI用（コンソールあり）の
2つの実行ファイルが、同じ解析結果とライブラリを共有できる。違いは Windows の
サブシステム（コンソールの有無）だけになる。

第1引数が CLI のサブコマンド名そのものだったときだけ CLI として動く。エクスプローラ
からPDFやフォルダをドロップすると引数は**絶対パス**になるので、取り違えは起きない。
"""

from __future__ import annotations

import os
import sys

CLI_COMMANDS = frozenset({"build", "init", "layouts", "devices", "selftest"})

# パス区切りやドライブ指定を含むならコマンド名ではない。
PATH_MARKERS = ("\\", "/", ":")

# CLI 用に固めた実行ファイルの名前の接尾辞。
CLI_EXECUTABLE_SUFFIX = "-cli"


def _ensure_standard_streams() -> None:
    """コンソールなしで固めた実行ファイルでは ``sys.stdout`` が ``None`` になる。

    そのまま ``print()` すると AttributeError で落ちるので、捨て先を用意しておく。
    GUI 実行ファイルに CLI 引数が渡された場合の保険。
    """
    for name in ("stdout", "stderr"):
        if getattr(sys, name, None) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))


def _is_cli_invocation(argv: list[str]) -> bool:
    """第1引数を CLI のサブコマンドとみなすか。

    「同名のファイル・フォルダが存在したらコマンドとみなさない」という判定にしては
    **いけない**。カレントディレクトリに `build` というフォルダがあるだけで
    `InkFlow-cli.exe build ...` が GUI 起動に化けてしまう（このリポジトリ自身が
    PyInstaller の作業用 `build/` を持つため、実際に踏んだ）。

    ドロップされたパスは常に絶対パスなので、区切り文字の有無で見分ければ十分で、
    カレントディレクトリにも左右されない。
    """
    if not argv:
        return False
    first = argv[0]
    if any(marker in first for marker in PATH_MARKERS):
        return False
    return first in CLI_COMMANDS


def _is_cli_executable(executable: str) -> bool:
    """CLI 用に固めた実行ファイルか（名前で見分ける）。

    2つの実行ファイルは同じスクリプトを共有しているので、引数だけで振り分けると
    ``InkFlow-cli.exe`` を引数なしで起動したときに GUI が立ち上がってしまう
    （背後にコンソール窓が残ったまま）。CLI 版は引数が無ければ使い方を出すべき。
    """
    stem = os.path.splitext(os.path.basename(executable))[0]
    return stem.lower().endswith(CLI_EXECUTABLE_SUFFIX)


def main() -> int:
    _ensure_standard_streams()
    arguments = sys.argv[1:]

    if _is_cli_executable(sys.executable) or _is_cli_invocation(arguments):
        from inkflow.cli import main as cli_main

        return cli_main(arguments)

    from inkflow.gui.app import run

    return run(arguments)


if __name__ == "__main__":
    sys.exit(main())
