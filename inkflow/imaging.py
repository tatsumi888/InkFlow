"""電子ペーパー向けの画像整形。

処理順は
``余白トリム → コマの切り出し → 縦横比維持リサイズ → 階調調整 → 白パディング → 量子化``。
リサイズ後にシャープをかけるのは、縮小でぼけた輪郭を戻すため。パディングを階調
調整の後に行うのは、白い余白がヒストグラムを歪めてコントラスト補正を鈍らせない
ようにするため。
"""

from __future__ import annotations

import io

from PIL import Image, ImageFilter, ImageOps

from .models import ROTATION_CCW, ROTATION_CW, ImageOptions

Rect = tuple[float, float, float, float]

# 回転（時計回りの角度）→ Pillow の transpose 操作。
# Pillow の ROTATE_90 は**反時計回り**なので、時計回り90°には ROTATE_270 を使う。
# 取り違えやすいので表にして、テストで両方向を固定している。
_TRANSPOSE_BY_ROTATION = {
    ROTATION_CW: Image.Transpose.ROTATE_270,
    ROTATION_CCW: Image.Transpose.ROTATE_90,
}

WHITE = 255

# 余白とみなす明るさの既定しきい値。
DEFAULT_TRIM_THRESHOLD = 245
# トリム後に残す余裕（短辺に対する比率）。
TRIM_MARGIN_RATIO = 0.006
# トリム結果がこれより小さければ誤検出とみなし、ページ全面に戻す。
MIN_TRIM_AREA_RATIO = 0.10

UNSHARP = ImageFilter.UnsharpMask(radius=1.0, percent=120, threshold=3)

MEDIA_TYPES = {"png": "image/png", "jpeg": "image/jpeg"}
EXTENSIONS = {"png": ".png", "jpeg": ".jpg"}


def to_grayscale(image: Image.Image) -> Image.Image:
    return image if image.mode == "L" else image.convert("L")


def find_content_bbox(
    image: Image.Image,
    threshold: int = DEFAULT_TRIM_THRESHOLD,
    margin_ratio: float = TRIM_MARGIN_RATIO,
) -> Rect:
    """白余白を除いた本文領域を相対矩形で返す。

    真っ白なページや、検出結果が極端に小さい（＝ノンブルや汚れだけを拾った）場合は
    ページ全面を返す。誤トリムで本文を切り落とすより、余白が残る方が安全なため。
    """
    gray = to_grayscale(image)
    width, height = gray.size
    if width == 0 or height == 0:
        return (0.0, 0.0, 1.0, 1.0)

    mask = gray.point(lambda value: 255 if value < threshold else 0)
    bbox = mask.getbbox()
    if bbox is None:
        return (0.0, 0.0, 1.0, 1.0)

    left, top, right, bottom = bbox
    if (right - left) * (bottom - top) < MIN_TRIM_AREA_RATIO * width * height:
        return (0.0, 0.0, 1.0, 1.0)

    margin = max(1.0, min(width, height) * margin_ratio)
    return (
        max(0.0, (left - margin) / width),
        max(0.0, (top - margin) / height),
        min(1.0, (right + margin) / width),
        min(1.0, (bottom + margin) / height),
    )


def crop_relative(image: Image.Image, rect: Rect) -> Image.Image:
    """相対矩形で切り出す。幅・高さは最低1pxを保証する。"""
    width, height = image.size
    x0, y0, x1, y1 = rect
    left = max(0, min(width - 1, int(round(x0 * width))))
    top = max(0, min(height - 1, int(round(y0 * height))))
    right = max(left + 1, min(width, int(round(x1 * width))))
    bottom = max(top + 1, min(height, int(round(y1 * height))))
    return image.crop((left, top, right, bottom))


def rotate_image(image: Image.Image, degrees: int) -> Image.Image:
    """コマを90°単位で回転する（``degrees`` は時計回り）。

    横長のコマは、縦長の画面にそのまま収めると上下が大きく余って文字が小さくなる。
    回して端末を横向きに持てば画面をほぼ使い切れる。

    ``Image.rotate()`` ではなく ``transpose()`` を使うのは、90°単位なら画素の並べ替え
    だけで済み、再サンプリングによる劣化もコストも生じないため。
    """
    operation = _TRANSPOSE_BY_ROTATION.get(degrees)
    if operation is None:
        return image
    return image.transpose(operation)


def contain_resize(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    """縦横比を保ったまま、指定サイズに収まる最大寸法へリサイズする。"""
    target_w, target_h = size
    width, height = image.size
    if width == 0 or height == 0:
        return Image.new("L", (1, 1), WHITE)
    scale = min(target_w / width, target_h / height)
    new_size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
    if new_size == (width, height):
        return image
    return image.resize(new_size, Image.Resampling.LANCZOS)


def pad_to_center(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    """白いキャンバスの中央に貼り付けて、寸法をちょうど ``size`` にする。"""
    if image.size == size:
        return image
    canvas = Image.new("L", size, WHITE)
    offset = ((size[0] - image.width) // 2, (size[1] - image.height) // 2)
    canvas.paste(image, offset)
    return canvas


def apply_gamma(image: Image.Image, gamma: float) -> Image.Image:
    """ガンマ補正。1.0 で無変換、1.0 より大きいと全体が濃くなる。"""
    if abs(gamma - 1.0) < 1e-3:
        return image
    lut = [min(255, max(0, round(255.0 * ((index / 255.0) ** gamma)))) for index in range(256)]
    return image.point(lut)


def enhance(
    image: Image.Image,
    gamma: float = 1.0,
    contrast_cutoff: float = 0.5,
    sharpen: bool = True,
) -> Image.Image:
    """電子ペーパーでの視認性を上げる階調調整。

    ``contrast_cutoff`` は自動コントラストで切り捨てるヒストグラムの割合(%)。
    ``0`` を渡すとコントラスト補正そのものを行わない。
    """
    result = to_grayscale(image)
    if contrast_cutoff > 0:
        result = ImageOps.autocontrast(result, cutoff=contrast_cutoff)
    result = apply_gamma(result, gamma)
    if sharpen:
        result = result.filter(UNSHARP)
    return result


def quantize_gray(image: Image.Image, levels: int) -> Image.Image:
    """グレー ``levels`` 階調のパレット画像へ量子化する。

    16 階調ならパレットが 16 色になり、Pillow は PNG を 4bit 深度で書き出す。
    文字主体の誌面では、階調を落としても見た目はほぼ変わらずサイズだけが縮む。
    """
    gray = to_grayscale(image)
    if levels >= 256:
        return gray
    levels = max(2, min(256, levels))

    step = 255.0 / (levels - 1)
    index_lut = [min(levels - 1, int(round(value / step))) for value in range(256)]
    indexed = gray.point(index_lut)

    palette: list[int] = []
    for index in range(levels):
        value = min(255, int(round(index * step)))
        palette.extend((value, value, value))

    result = Image.frombytes("P", gray.size, indexed.tobytes())
    result.putpalette(palette)
    return result


def finalize_page(
    image: Image.Image,
    size: tuple[int, int],
    options: ImageOptions,
) -> Image.Image:
    """コマ画像を端末解像度ちょうどの出力画像に仕上げる。"""
    resized = contain_resize(to_grayscale(image), size)
    adjusted = enhance(
        resized,
        gamma=options.gamma,
        contrast_cutoff=options.contrast_cutoff,
        sharpen=options.sharpen,
    )
    padded = pad_to_center(adjusted, size)
    if options.format == "png":
        return quantize_gray(padded, options.gray_levels)
    # JPEG は連続階調で符号化するため、量子化するとかえって
    # モスキートノイズが増えてサイズも膨らむ。ここでは行わない。
    return padded


def encode_image(image: Image.Image, options: ImageOptions) -> bytes:
    """出力形式に合わせてバイト列へ符号化する。"""
    buffer = io.BytesIO()
    if options.format == "jpeg":
        to_grayscale(image).save(
            buffer, format="JPEG", quality=options.jpeg_quality, optimize=True
        )
    else:
        image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def extension_for(options: ImageOptions) -> str:
    return EXTENSIONS.get(options.format, ".png")


def media_type_for(options: ImageOptions) -> str:
    return MEDIA_TYPES.get(options.format, "image/png")
