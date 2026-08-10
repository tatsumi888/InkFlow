import pytest
from PIL import Image

from inkflow import appicon


def test_render_icon_default_size():
    icon = appicon.render_icon()
    assert icon.size == (256, 256)
    assert icon.mode == "RGBA"


@pytest.mark.parametrize("size", [16, 32, 48, 64, 256, 512])
def test_render_icon_various_sizes(size):
    assert appicon.render_icon(size).size == (size, size)


def test_render_icon_clamps_tiny_sizes():
    """極端に小さい指定でも落ちず、線幅が0にならない。"""
    icon = appicon.render_icon(1)
    assert icon.size == (8, 8)


def test_render_icon_draws_something():
    icon = appicon.render_icon(64)
    colors = {pixel for pixel in icon.convert("RGBA").getdata()}
    assert len(colors) > 1, "何も描かれていない"


def test_render_icon_marks_the_first_frame():
    """左上のコマが塗られている（読み順の起点を示す図柄）。"""
    icon = appicon.render_icon(256)
    upper_left = icon.getpixel((100, 70))
    lower_right = icon.getpixel((156, 186))
    assert upper_left[:3] == appicon.ACTIVE_FILL[:3]
    assert lower_right[:3] != appicon.ACTIVE_FILL[:3]


def test_render_icon_background_is_transparent():
    icon = appicon.render_icon(256)
    assert icon.getpixel((1, 1))[3] == 0


def test_write_ico_creates_file(tmp_path):
    path = appicon.write_ico(tmp_path / "app.ico")
    assert path.is_file()
    assert path.stat().st_size > 0


def test_write_ico_contains_multiple_sizes(tmp_path):
    path = appicon.write_ico(tmp_path / "app.ico", sizes=(16, 32, 48, 256))
    with Image.open(path) as image:
        assert {size for size in image.info["sizes"]} >= {(16, 16), (32, 32), (256, 256)}


def test_write_ico_creates_parent_directory(tmp_path):
    path = appicon.write_ico(tmp_path / "deep" / "nested" / "app.ico")
    assert path.is_file()


def test_write_ico_deduplicates_and_sorts_sizes(tmp_path):
    path = appicon.write_ico(tmp_path / "app.ico", sizes=(32, 16, 32))
    with Image.open(path) as image:
        assert sorted(image.info["sizes"]) == [(16, 16), (32, 32)]


def test_write_ico_rejects_empty_sizes(tmp_path):
    with pytest.raises(ValueError, match="少なくとも1つ"):
        appicon.write_ico(tmp_path / "app.ico", sizes=())


def test_write_png(tmp_path):
    path = appicon.write_png(tmp_path / "app.png", size=128)
    with Image.open(path) as image:
        assert image.size == (128, 128)


def test_ico_sizes_are_the_windows_set():
    assert appicon.ICO_SIZES == (16, 32, 48, 256)
