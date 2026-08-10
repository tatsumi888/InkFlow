import pytest
from PIL import Image

from inkflow import devices, layouts, renderer
from inkflow.errors import PdfLoadError, RenderError

from .conftest import B5_HEIGHT_PT, B5_WIDTH_PT, make_pdf


def test_open_and_page_count(sample_pdf):
    with renderer.PdfDocument(sample_pdf) as doc:
        assert doc.page_count == 2


def test_geometry_matches_b5(sample_pdf):
    with renderer.PdfDocument(sample_pdf) as doc:
        geometry = doc.geometry(0)
    assert geometry.width_pt == pytest.approx(B5_WIDTH_PT, abs=1.0)
    assert geometry.height_pt == pytest.approx(B5_HEIGHT_PT, abs=1.0)
    assert geometry.width_in == pytest.approx(B5_WIDTH_PT / 72.0)


def test_render_returns_grayscale_image(sample_pdf):
    with renderer.PdfDocument(sample_pdf) as doc:
        image = doc.render(0, dpi=72)
    assert isinstance(image, Image.Image)
    assert image.mode == "L"


def test_render_size_scales_with_dpi(sample_pdf):
    with renderer.PdfDocument(sample_pdf) as doc:
        low = doc.render(0, dpi=72)
        high = doc.render(0, dpi=144)
    assert high.width == pytest.approx(low.width * 2, abs=2)
    assert high.height == pytest.approx(low.height * 2, abs=2)


def test_render_dpi_is_clamped(sample_pdf):
    with renderer.PdfDocument(sample_pdf) as doc:
        huge = doc.render(0, dpi=99999)
        expected = doc.geometry(0).width_in * renderer.MAX_DPI
    assert huge.width == pytest.approx(expected, abs=2)


def test_render_out_of_range_page(sample_pdf):
    with renderer.PdfDocument(sample_pdf) as doc:
        with pytest.raises(RenderError, match="範囲外"):
            doc.render(5, dpi=72)


def test_open_missing_file(tmp_path):
    with pytest.raises(PdfLoadError, match="見つかりません"):
        renderer.PdfDocument(tmp_path / "nope.pdf")


def test_open_broken_file(tmp_path):
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"this is not a pdf at all")
    with pytest.raises(PdfLoadError):
        renderer.PdfDocument(broken)


def test_probe_page_count(tmp_path):
    path = make_pdf(tmp_path / "three.pdf", page_count=3)
    assert renderer.probe_page_count(path) == 3


# ---- 必要DPIの算出 -----------------------------------------------------


def test_required_dpi_for_b5_quad_split():
    device = devices.get_device("paperwhite_11")
    dpi = renderer.required_dpi(
        B5_WIDTH_PT / 72.0,
        B5_HEIGHT_PT / 72.0,
        layouts.min_relative_size("quad_2col"),
        device,
    )
    # 1236 / (7.165in * 0.5) ≒ 345、1648 / (10.12in * 0.5) ≒ 326 → 効くのは小さい方
    assert dpi == pytest.approx(326, abs=3)


def test_required_dpi_is_the_binding_constraint_only():
    """縦横比を保って収めるので、効くのは縦横どちらか一方の制約だけ。"""
    device = devices.get_device("paperwhite_11")
    dpi = renderer.required_dpi(4.0, 8.0, (1.0, 1.0), device)
    assert dpi == pytest.approx(min(1236 / 4.0, 1648 / 8.0), abs=0.5)


def test_required_dpi_is_higher_for_finer_split():
    device = devices.get_device("paperwhite_11")
    quad = renderer.required_dpi(
        7.165, 10.118, layouts.min_relative_size("quad_2col"), device
    )
    six = renderer.required_dpi(
        7.165, 10.118, layouts.min_relative_size("six_2col"), device
    )
    assert six > quad


def test_required_dpi_full_layout_is_lowest():
    device = devices.get_device("paperwhite_11")
    full = renderer.required_dpi(7.165, 10.118, layouts.min_relative_size("full"), device)
    quad = renderer.required_dpi(7.165, 10.118, layouts.min_relative_size("quad_2col"), device)
    assert full < quad


def test_required_dpi_swaps_device_dimensions_when_rotated():
    device = devices.get_device("paperwhite_11")
    upright = renderer.required_dpi(4.0, 8.0, (1.0, 1.0), device)
    rotated = renderer.required_dpi(4.0, 8.0, (1.0, 1.0), device, rotated=True)
    # 回転なし: min(1236/4, 1648/8) = 206
    # 回転あり: min(1648/4, 1236/8) = 154.5
    assert upright == pytest.approx(206, abs=1)
    assert rotated == pytest.approx(154.5, abs=1)


def test_required_dpi_rotation_is_higher_for_landscape_crops():
    """横長のコマは回転すると画面を使い切るぶん、より高い解像度が要る。"""
    device = devices.get_device("paperwhite_11")
    # B5 の上下2分割 = 7.165 x 5.059 inch（横長）
    upright = renderer.required_dpi(7.165, 10.118, layouts.min_relative_size("half_v"), device)
    rotated = renderer.required_dpi(
        7.165, 10.118, layouts.min_relative_size("half_v"), device, rotated=True
    )
    assert rotated > upright


def test_required_dpi_default_argument_keeps_previous_behaviour():
    device = devices.get_device("paperwhite_11")
    assert renderer.required_dpi(7.165, 10.118, (0.5, 0.5), device) == renderer.required_dpi(
        7.165, 10.118, (0.5, 0.5), device, rotated=False
    )


def test_required_dpi_clamped_to_bounds():
    device = devices.get_device("scribe")
    tiny = renderer.required_dpi(0.01, 0.01, (0.1, 0.1), device)
    huge = renderer.required_dpi(1000.0, 1000.0, (1.0, 1.0), device)
    assert tiny == renderer.MAX_DPI
    assert huge == renderer.MIN_DPI


def test_rendered_crop_needs_no_upscaling_and_no_waste(sample_pdf):
    """算出したDPIでレンダリングすれば、コマは拡大も縮小もなく画面に収まる。"""
    device = devices.get_device("paperwhite_11")
    with renderer.PdfDocument(sample_pdf) as doc:
        geometry = doc.geometry(0)
        dpi = renderer.required_dpi(
            geometry.width_in,
            geometry.height_in,
            layouts.min_relative_size("quad_2col"),
            device,
        )
        image = doc.render(0, dpi)

    crop_w, crop_h = image.width * 0.5, image.height * 0.5
    scale = min(device.width / crop_w, device.height / crop_h)
    assert scale == pytest.approx(1.0, abs=0.01)


def test_rendered_crop_fills_at_least_one_screen_dimension(sample_pdf):
    device = devices.get_device("paperwhite_11")
    with renderer.PdfDocument(sample_pdf) as doc:
        geometry = doc.geometry(0)
        dpi = renderer.required_dpi(
            geometry.width_in,
            geometry.height_in,
            layouts.min_relative_size("quad_2col"),
            device,
        )
        image = doc.render(0, dpi)

    crop_w, crop_h = image.width * 0.5, image.height * 0.5
    assert crop_w >= device.width - 2 or crop_h >= device.height - 2


# ---- プレビューキャッシュ -----------------------------------------------


def test_preview_cache_returns_same_object(sample_pdf):
    cache = renderer.PreviewCache()
    try:
        first = cache.render(sample_pdf, 0, 72)
        second = cache.render(sample_pdf, 0, 72)
        assert first is second
    finally:
        cache.close()


def test_preview_cache_evicts_oldest(sample_pdf):
    cache = renderer.PreviewCache(max_images=2)
    try:
        first = cache.render(sample_pdf, 0, 72)
        cache.render(sample_pdf, 1, 72)
        cache.render(sample_pdf, 0, 96)  # ここで最初のエントリが落ちる
        assert cache.render(sample_pdf, 0, 72) is not first
    finally:
        cache.close()


def test_preview_cache_page_count_and_invalidate(sample_pdf):
    cache = renderer.PreviewCache()
    try:
        assert cache.page_count(sample_pdf) == 2
        first = cache.render(sample_pdf, 0, 72)
        cache.invalidate(sample_pdf)
        assert cache.render(sample_pdf, 0, 72) is not first
    finally:
        cache.close()


def test_preview_cache_geometry(sample_pdf):
    cache = renderer.PreviewCache()
    try:
        assert cache.geometry(sample_pdf, 0).width_pt == pytest.approx(B5_WIDTH_PT, abs=1.0)
    finally:
        cache.close()
