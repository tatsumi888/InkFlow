"""ビルド時刻・ソースバージョンの取得。

パッケージ版（PyInstallerで固めた実行ファイル）は、ビルド時に
``packaging/build.py`` が書き出す ``_generated_build_info.py`` からコミット・
ビルド日時を読む。実行ファイルには ``.git`` が同梱されないため。

ソースから実行しているときは、その場で git を呼んで現在のコミット・作業ツリーの
状態を調べる。バージョン番号（``__version__``）だけでは、開発中に何度もビルドし
直した実行ファイルを区別できないため、これらの情報で補う。
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

from . import APP_NAME, __version__

# PyInstallerのブートローダーが設定する属性。生成ファイルの有無ではなくこちらで
# 判定する。ビルド直後に生成ファイルの削除を忘れてソースツリーに残っていても、
# ソース実行時に誤ってパッケージ版のビルド情報を表示しないようにするため。
FROZEN = getattr(sys, "frozen", False)

if FROZEN:
    try:
        from ._generated_build_info import BUILD_COMMIT, BUILD_DIRTY, BUILD_TIME
    except ImportError:
        BUILD_COMMIT = None
        BUILD_DIRTY = None
        BUILD_TIME = None
else:
    BUILD_COMMIT = None
    BUILD_DIRTY = None
    BUILD_TIME = None

_GIT_TIMEOUT = 5


def _run_git(args: list[str]) -> str | None:
    """git を呼ぶ。失敗しても例外を投げず None を返す（診断用の付加情報のため）。"""
    root = Path(__file__).resolve().parent.parent
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            timeout=_GIT_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.decode("utf-8", errors="replace").strip()


def source_commit() -> str | None:
    """このプロセスが依っているソースの短縮コミットハッシュ。

    パッケージ版はビルド時に埋め込んだ値、ソース実行時はその場でgitに聞く。
    """
    if FROZEN:
        return BUILD_COMMIT
    return _run_git(["rev-parse", "--short", "HEAD"])


def source_dirty() -> bool | None:
    """作業ツリーに未コミットの変更があるか。分からなければ None。"""
    if FROZEN:
        return BUILD_DIRTY
    status = _run_git(["status", "--porcelain"])
    if status is None:
        return None
    return bool(status)


def build_time() -> str | None:
    """パッケージ版のビルド日時（ISO8601、UTC）。ソース実行なら None。"""
    return BUILD_TIME


def format_build_time(iso_string: str) -> str:
    """ISO8601文字列を表示用に整える。解釈できなければそのまま返す。"""
    try:
        moment = datetime.fromisoformat(iso_string)
    except ValueError:
        return iso_string
    return moment.strftime("%Y-%m-%d %H:%M UTC")


def describe() -> str:
    """GUI/CLI共通のバージョン情報文言（複数行）。"""
    lines = [f"{APP_NAME} {__version__}"]

    commit = source_commit()
    if commit:
        dirty = source_dirty()
        suffix = "（未コミットの変更あり）" if dirty else ""
        lines.append(f"ソース: {commit}{suffix}")
    else:
        lines.append("ソース: 不明（gitで確認できません）")

    time = build_time()
    lines.append(
        f"ビルド: {format_build_time(time)}" if time else "ビルド: ソース実行（パッケージ版ではない）"
    )

    return "\n".join(lines)
