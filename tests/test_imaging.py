import pytest
from PIL import Image, ImageDraw

from inkflow import imaging
from inkflow.models import ImageOptions

DEVICE_SIZE = (1236, 1648)


def bordered_page(size=(400, 600), margin=50) -> Image.Image:
    """周囲に白余白、中央に黒い矩形がある画像。"""
    image = Image.new("L", size, 255)
    draw = ImageDraw.Draw(image)
    draw.rectangle(
        (margin, margin, size[0] - margin - 1, size[1] - margin - 1),
        fill=0,
    )
    return image


# ---- トリム -----------------------------------------------------------


def test_find_content_bbox_detects_margins():
    image = bordered_page(size=(400, 600), margin=50)
    x0, y0, x1, y1 = imaging.find_content_bbox(image, margin_ratio=0.0)
    assert x0 == pytest.approx(50 / 400, abs=0.01)
    assert y0 == pytest.approx(50 / 600, abs=0.01)
    assert x1 == pytest.approx(350 / 400, abs=0.01)
    assert y1 == pytest.approx(550 / 600, abs=0.01)


def test_find_content_bbox_adds_margin_ratio():
    image = bordered_page()
    tight = imaging.find_content_bbox(image, margin_ratio=0.0)
    loose = imaging.find_content_bbox(image, margin_ratio=0.02)
    assert loose[0] < tight[0]
    assert loose[2] > tight[2]


def test_find_content_bbox_blank_page_returns_full():
    blank = Image.new("L", (200, 300), 255)
    assert imaging.find_content_bbox(blank) == (0.0, 0.0, 1.0, 1.0)


def test_find_content_bbox_ignores_tiny_speck():
    """ノンブルだけを拾って本文を切り落とさない。"""
    image = Image.new("L", (400, 600), 255)
    ImageDraw.Draw(image).rectangle((10, 10, 20, 20), fill=0)
    assert imaging.find_content_bbox(image) == (0.0, 0.0, 1.0, 1.0)


def test_find_content_bbox_threshold_controls_sensitivity():
    image = Image.new("L", (200, 200), 255)
    ImageDraw.Draw(image).rectangle((50, 50, 150, 150), fill=230)
    detected = imaging.find_content_bbox(image, threshold=245, margin_ratio=0.0)
    ignored = imaging.find_content_bbox(image, threshold=200, margin_ratio=0.0)
    assert detected != (0.0, 0.0, 1.0, 1.0)
    assert ignored == (0.0, 0.0, 1.0, 1.0)


def test_find_content_bbox_handles_all_black():
    black = Image.new("L", (100, 100), 0)
    assert imaging.find_content_bbox(black) == (0.0, 0.0, 1.0, 1.0)


# ---- クロップ・リサイズ -------------------------------------------------


def test_crop_relative_dimensions():
    image = Image.new("L", (400, 600), 255)
    cropped = imaging.crop_relative(image, (0.0, 0.5, 0.5, 1.0))
    assert cropped.size == (200, 300)


def test_crop_relative_never_returns_empty():
    image = Image.new("L", (400, 600), 255)
    cropped = imaging.crop_relative(image, (0.5, 0.5, 0.5, 0.5))
    assert cropped.width >= 1 and cropped.height >= 1


# ---- 回転 -------------------------------------------------------------


def corner_marked_image() -> Image.Image:
    """左上だけが黒い、向きの分かる画像。"""
    image = Image.new("L", (40, 20), 255)
    ImageDraw.Draw(image).rectangle((0, 0, 9, 4), fill=0)
    return image


def test_rotate_image_swaps_dimensions():
    image = Image.new("L", (40, 20), 255)
    assert imaging.rotate_image(image, 90).size == (20, 40)
    assert imaging.rotate_image(image, 270).size == (20, 40)


def test_rotate_image_none_is_untouched():
    image = corner_marked_image()
    assert imaging.rotate_image(image, 0) is image


def test_rotate_image_ignores_unsupported_angles():
    image = corner_marked_image()
    assert imaging.rotate_image(image, 45) is image
    assert imaging.rotate_image(image, 180) is image


def test_rotate_clockwise_moves_top_left_to_top_right():
    """時計回り90°: 左上の印は右上へ移る。"""
    rotated = imaging.rotate_image(corner_marked_image(), 90)
    assert rotated.getpixel((rotated.width - 2, 2)) == 0
    assert rotated.getpixel((2, 2)) == 255


def test_rotate_counterclockwise_moves_top_left_to_bottom_left():
    """反時計回り90°: 左上の印は左下へ移る。"""
    rotated = imaging.rotate_image(corner_marked_image(), 270)
    assert rotated.getpixel((2, rotated.height - 2)) == 0
    assert rotated.getpixel((2, 2)) == 255


def test_clockwise_and_counterclockwise_differ_by_180_degrees():
    image = corner_marked_image()
    clockwise = imaging.rotate_image(image, 90)
    counter = imaging.rotate_image(image, 270)
    assert clockwise.tobytes() != counter.tobytes()
    assert clockwise.transpose(Image.Transpose.ROTATE_180).tobytes() == counter.tobytes()


def test_rotating_twice_returns_to_original():
    image = corner_marked_image()
    round_trip = imaging.rotate_image(imaging.rotate_image(image, 90), 270)
    assert round_trip.tobytes() == image.tobytes()


def test_rotation_is_lossless():
    """90°単位の回転では階調が一切変わらない。"""
    gradient = Image.linear_gradient("L").resize((60, 30))
    rotated = imaging.rotate_image(gradient, 90)
    assert sorted(rotated.getdata()) == sorted(gradient.getdata())


def test_contain_resize_preserves_aspect_ratio():
    image = Image.new("L", (1000, 500), 255)
    resized = imaging.contain_resize(image, DEVICE_SIZE)
    assert resized.width <= DEVICE_SIZE[0]
    assert resized.height <= DEVICE_SIZE[1]
    assert resized.width / resized.height == pytest.approx(2.0, rel=0.01)


def test_contain_resize_upscales_small_images():
    image = Image.new("L", (100, 133), 255)
    resized = imaging.contain_resize(image, DEVICE_SIZE)
    assert resized.width > 100


def test_pad_to_center_produces_exact_size_with_white():
    image = Image.new("L", (600, 1648), 0)
    padded = imaging.pad_to_center(image, DEVICE_SIZE)
    assert padded.size == DEVICE_SIZE
    assert padded.getpixel((2, 824)) == 255  # 左端の余白は白
    assert padded.getpixel((618, 824)) == 0  # 中央は元画像


# ---- 階調調整 ---------------------------------------------------------


def test_apply_gamma_identity():
    image = Image.new("L", (4, 4), 128)
    assert imaging.apply_gamma(image, 1.0).getpixel((0, 0)) == 128


def test_apply_gamma_above_one_darkens():
    image = Image.new("L", (4, 4), 128)
    assert imaging.apply_gamma(image, 2.0).getpixel((0, 0)) < 128


def test_apply_gamma_below_one_brightens():
    image = Image.new("L", (4, 4), 128)
    assert imaging.apply_gamma(image, 0.5).getpixel((0, 0)) > 128


def test_enhance_increases_contrast():
    image = Image.new("L", (50, 50), 200)
    ImageDraw.Draw(image).rectangle((10, 10, 40, 40), fill=120)
    enhanced = imaging.enhance(image, contrast_cutoff=0.5, sharpen=False)
    assert enhanced.getextrema() == (0, 255)


def test_enhance_cutoff_zero_disables_contrast_correction():
    image = Image.new("L", (50, 50), 200)
    ImageDraw.Draw(image).rectangle((10, 10, 40, 40), fill=120)
    enhanced = imaging.enhance(image, contrast_cutoff=0.0, sharpen=False)
    assert enhanced.getextrema() == (120, 200)


def test_enhance_handles_uniform_image():
    uniform = Image.new("L", (20, 20), 200)
    assert imaging.enhance(uniform).size == (20, 20)


# ---- 量子化・符号化 ---------------------------------------------------


def test_quantize_gray_limits_levels():
    gradient = Image.linear_gradient("L")
    quantized = imaging.quantize_gray(gradient, 16)
    assert quantized.mode == "P"
    assert len(quantized.getcolors(maxcolors=300)) <= 16


def test_quantize_gray_keeps_black_and_white():
    image = Image.new("L", (2, 1))
    image.putpixel((0, 0), 0)
    image.putpixel((1, 0), 255)
    palette = imaging.quantize_gray(image, 16).convert("L")
    assert palette.getpixel((0, 0)) == 0
    assert palette.getpixel((1, 0)) == 255


def test_quantize_gray_passthrough_at_256_levels():
    gradient = Image.linear_gradient("L")
    assert imaging.quantize_gray(gradient, 256).mode == "L"


def test_png_uses_4bit_palette_for_16_levels():
    """16階調ならPNGは4bit深度で書かれる（＝ファイルが小さくなる）。"""
    image = imaging.quantize_gray(Image.linear_gradient("L"), 16)
    data = imaging.encode_image(image, ImageOptions(format="png"))
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    bit_depth = data[24]
    color_type = data[25]
    assert bit_depth == 4
    assert color_type == 3  # パレット


def test_jpeg_encoding_is_grayscale():
    image = Image.new("L", (100, 100), 128)
    data = imaging.encode_image(image, ImageOptions(format="jpeg", jpeg_quality=80))
    assert data[:2] == b"\xff\xd8"
    import io

    with Image.open(io.BytesIO(data)) as decoded:
        assert decoded.mode == "L"


def test_extension_and_media_type():
    assert imaging.extension_for(ImageOptions(format="png")) == ".png"
    assert imaging.extension_for(ImageOptions(format="jpeg")) == ".jpg"
    assert imaging.media_type_for(ImageOptions(format="png")) == "image/png"
    assert imaging.media_type_for(ImageOptions(format="jpeg")) == "image/jpeg"


# ---- finalize_page ----------------------------------------------------


def test_finalize_page_matches_device_size_exactly():
    image = bordered_page(size=(900, 1400))
    result = imaging.finalize_page(image, DEVICE_SIZE, ImageOptions())
    assert result.size == DEVICE_SIZE


def test_finalize_page_does_not_stretch():
    """極端に横長のコマでも縦横比は保たれ、余りは白で埋まる。"""
    image = Image.new("L", (1000, 200), 0)
    result = imaging.finalize_page(image, DEVICE_SIZE, ImageOptions()).convert("L")
    assert result.size == DEVICE_SIZE
    assert result.getpixel((618, 10)) == 255  # 上端は余白
    assert result.getpixel((618, 824)) == 0  # 中央に原画


def test_finalize_page_png_is_quantized():
    image = Image.linear_gradient("L").resize((600, 800))
    result = imaging.finalize_page(image, DEVICE_SIZE, ImageOptions(format="png"))
    assert result.mode == "P"
    assert len(result.getcolors(maxcolors=300)) <= 16


def test_finalize_page_jpeg_stays_continuous_tone():
    image = Image.linear_gradient("L").resize((600, 800))
    result = imaging.finalize_page(image, DEVICE_SIZE, ImageOptions(format="jpeg"))
    assert result.mode == "L"


def test_finalize_page_accepts_rgb_input():
    image = Image.new("RGB", (600, 800), (10, 200, 90))
    result = imaging.finalize_page(image, DEVICE_SIZE, ImageOptions())
    assert result.size == DEVICE_SIZE
