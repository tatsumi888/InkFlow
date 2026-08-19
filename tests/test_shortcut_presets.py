"""inkflow.gui.shortcut_presets の永続化ロジックの単体テスト。

MainWindow を経由しない分、Qt のセットアップ無しで速く検証できる。
"""

import json

import pytest

from inkflow.gui import shortcut_presets
from inkflow.models import PageSpec


@pytest.fixture(autouse=True)
def isolated_config_path(tmp_path, monkeypatch):
    monkeypatch.setattr(shortcut_presets, "config_path", lambda: tmp_path / "config.json")
    return tmp_path / "config.json"


def test_apply_and_save_keys_have_matching_length_and_no_overlap():
    assert len(shortcut_presets.APPLY_KEYS) == len(shortcut_presets.SAVE_KEYS)
    assert len(shortcut_presets.APPLY_KEYS) >= 3  # 要件: 3個以上
    assert set(shortcut_presets.APPLY_KEYS).isdisjoint(shortcut_presets.SAVE_KEYS)


def test_load_without_file_returns_all_none():
    presets = shortcut_presets.load_presets()
    assert set(presets.keys()) == set(shortcut_presets.APPLY_KEYS)
    assert all(value is None for value in presets.values())


def test_save_then_load_round_trips():
    spec = PageSpec("quad_2col", include_overview=False, rotate=90, column_bias=0.05)
    presets = dict.fromkeys(shortcut_presets.APPLY_KEYS)
    presets["A"] = spec

    shortcut_presets.save_presets(presets)
    loaded = shortcut_presets.load_presets()

    assert loaded["A"] == spec
    assert all(loaded[key] is None for key in shortcut_presets.APPLY_KEYS if key != "A")


def test_load_ignores_corrupted_file(isolated_config_path):
    isolated_config_path.parent.mkdir(parents=True, exist_ok=True)
    isolated_config_path.write_text("{not valid json", encoding="utf-8")
    presets = shortcut_presets.load_presets()
    assert all(value is None for value in presets.values())


def test_load_ignores_non_dict_json(isolated_config_path):
    isolated_config_path.parent.mkdir(parents=True, exist_ok=True)
    isolated_config_path.write_text("[1, 2, 3]", encoding="utf-8")
    presets = shortcut_presets.load_presets()
    assert all(value is None for value in presets.values())


def test_load_ignores_unknown_keys_in_stored_presets(isolated_config_path):
    isolated_config_path.parent.mkdir(parents=True, exist_ok=True)
    isolated_config_path.write_text(
        json.dumps({"shortcut_presets": {"Q": {"layout": "full"}}}), encoding="utf-8"
    )
    presets = shortcut_presets.load_presets()
    assert "Q" not in presets  # APPLY_KEYS に無いキーは無視される
    assert all(value is None for value in presets.values())


def test_save_preserves_unrelated_keys_in_config_file(isolated_config_path):
    isolated_config_path.parent.mkdir(parents=True, exist_ok=True)
    isolated_config_path.write_text(
        json.dumps({"some_future_setting": "keep-me"}), encoding="utf-8"
    )

    presets = dict.fromkeys(shortcut_presets.APPLY_KEYS)
    presets["S"] = PageSpec("half_v")
    shortcut_presets.save_presets(presets)

    raw = json.loads(isolated_config_path.read_text(encoding="utf-8"))
    assert raw["some_future_setting"] == "keep-me"
    assert raw["shortcut_presets"]["S"]["layout"] == "half_v"


def test_save_overwrites_previous_slot_contents():
    presets = dict.fromkeys(shortcut_presets.APPLY_KEYS)
    presets["D"] = PageSpec("full")
    shortcut_presets.save_presets(presets)

    presets["D"] = PageSpec("six_2col", rotate=270)
    shortcut_presets.save_presets(presets)

    loaded = shortcut_presets.load_presets()
    assert loaded["D"].layout_id == "six_2col"
    assert loaded["D"].rotate == 270


def test_save_can_clear_a_slot_back_to_none():
    presets = dict.fromkeys(shortcut_presets.APPLY_KEYS)
    presets["F"] = PageSpec("full")
    shortcut_presets.save_presets(presets)

    presets["F"] = None
    shortcut_presets.save_presets(presets)

    assert shortcut_presets.load_presets()["F"] is None
