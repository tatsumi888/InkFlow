"""ページ分割設定のショートカットキー割り当て（左手キーのみ、5スロット）。

特定のページに適用した分割設定（layout_id / include_overview / rotate /
rotate_overview / column_bias / row_bias、つまり PageSpec そのもの）を、
キー1つでスロットへ保存し、キー1つで別ページへ適用できるようにする。

右手をマウスに置いたまま左手だけで操作できることを前提に、キーはすべて
QWERTY配列の左手側（ホームロー「A S D F G」と、その真下の「Z X C V B」）
から選んでいる。列を揃えているのは対応関係を覚えやすくするため
（例: A で適用する設定は Z で上書き保存する）。Shift 等の修飾キーを使わない
のは、片手だけで「保存」と「適用」を押し分けられるようにするため
（Shift+A は左手小指だけでは現実的に押しにくい）。

割り当ては %APPDATA%\\InkFlow\\config.json に保存し、アプリを再起動しても
前回の内容を引き継ぐ。姉妹プロジェクト Clipper の config.py と同じ方針
（壊れていても既定値＝全スロット空で起動を続ける）に合わせている。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .. import APP_NAME
from ..models import PageSpec

# 適用キーと保存キーは同じ列で対応させる（A で適用する内容は Z で上書きする）。
APPLY_KEYS: tuple[str, ...] = ("A", "S", "D", "F", "G")
SAVE_KEYS: tuple[str, ...] = ("Z", "X", "C", "V", "B")

CONFIG_VERSION = 1


def config_path() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / APP_NAME / "config.json"


def load_presets() -> dict[str, PageSpec | None]:
    """保存済みのキー割り当てを読み込む。壊れていても全スロット空のまま返す。"""
    presets: dict[str, PageSpec | None] = dict.fromkeys(APPLY_KEYS)
    try:
        raw = json.loads(config_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return presets
    if not isinstance(raw, dict):
        return presets
    stored = raw.get("shortcut_presets")
    if not isinstance(stored, dict):
        return presets
    for key in APPLY_KEYS:
        data = stored.get(key)
        if isinstance(data, dict):
            presets[key] = PageSpec.from_dict(data)
    return presets


def save_presets(presets: dict[str, PageSpec | None]) -> None:
    """キー割り当てを保存する。

    ``config.json`` に将来ほかの設定が同居してもここで消さないよう、既存の
    内容を読み込んでからマージして書き戻す（読み込みに失敗した場合は
    このキー割り当てだけの新規ファイルとして書く）。書き込み自体の失敗は
    黙って諦める（設定保存の失敗でアプリを止めるほどではないため）。
    """
    path = config_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raw = {}
    except (OSError, ValueError):
        raw = {}

    raw["version"] = CONFIG_VERSION
    raw["shortcut_presets"] = {
        key: (spec.to_dict() if spec is not None else None) for key, spec in presets.items()
    }

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass
