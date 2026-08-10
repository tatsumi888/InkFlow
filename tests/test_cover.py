from pathlib import Path

from PIL import Image

from inkflow import cover, devices
from inkflow.models import ImageOptions, Project

DEVICE = devices.get_device("paperwhite_11")


def test_find_font_path_returns_existing_file_or_none():
    path = cover.find_font_path()
    assert path is None or Path(path).is_file()


def test_load_font_falls_back_without_truetype():
    font = cover._load_font(None, 40)
    assert font is not None


def test_load_font_falls_back_on_broken_path(tmp_path):
    broken = tmp_path / "not-a-font.ttf"
    broken.write_bytes(b"nope")
    assert cover._load_font(broken, 40) is not None


def test_generated_cover_matches_device_size():
    image = cover.render_generated_cover("テストマガジン", "2026年8月号", DEVICE)
    assert image.size == DEVICE.size
    assert image.mode == "L"


def test_generated_cover_draws_something():
    image = cover.render_generated_cover("テストマガジン", "2026年8月号", DEVICE)
    low, high = image.getextrema()
    assert low < 128 < high, "文字や枠が描かれていない"


def test_generated_cover_without_issue():
    image = cover.render_generated_cover("誌名のみ", "", DEVICE)
    assert image.size == DEVICE.size
    assert image.getextrema()[0] < 128


def test_generated_cover_wraps_long_title():
    long_title = "とても長い雑誌名がここに入ります" * 4
    image = cover.render_generated_cover(long_title, "2026年8月号", DEVICE)
    assert image.size == DEVICE.size


def test_generated_cover_handles_empty_title():
    image = cover.render_generated_cover("", "", DEVICE)
    assert image.size == DEVICE.size


def test_build_cover_generated_is_quantized_for_png():
    project = Project(title="月刊テスト", issue="2026年8月号")
    image = cover.build_cover(project, DEVICE, ImageOptions(format="png"))
    assert image.size == DEVICE.size
    assert image.mode == "P"
    assert len(image.getcolors(maxcolors=300)) <= 16


def test_build_cover_generated_stays_l_for_jpeg():
    project = Project(title="月刊テスト", issue="2026年8月号")
    image = cover.build_cover(project, DEVICE, ImageOptions(format="jpeg"))
    assert image.mode == "L"


def test_build_cover_uses_user_image(tmp_path):
    source = tmp_path / "cover.png"
    Image.new("RGB", (800, 1000), (20, 20, 20)).save(source)

    project = Project(title="無視される", cover_image=source)
    image = cover.build_cover(project, DEVICE, ImageOptions())
    assert image.size == DEVICE.size
    # 元画像が暗いので、中央は黒寄りになる。
    assert image.convert("L").getpixel((DEVICE.width // 2, DEVICE.height // 2)) < 60


def test_build_cover_falls_back_when_user_image_missing(tmp_path):
    project = Project(title="誌名", issue="号", cover_image=tmp_path / "missing.png")
    image = cover.build_cover(project, DEVICE, ImageOptions())
    assert image.size == DEVICE.size
