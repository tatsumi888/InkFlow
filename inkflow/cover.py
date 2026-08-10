"""表紙画像の生成。

雑誌名と号から素朴な表紙を組む。ユーザーが画像を指定した場合はそれを整形して使う。
Kindle のライブラリではサムネイルが小さいので、情報は「誌名」と「号」の2つに絞る。
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import imaging
from .devices import Device
from .errors import InkFlowError
from .models import ImageOptions, Project

# 日本語が出せるフォントの探索順。太めのゴシックを優先する。
FONT_CANDIDATES: tuple[str, ...] = (
    r"C:\Windows\Fonts\meiryob.ttc",
    r"C:\Windows\Fonts\meiryo.ttc",
    r"C:\Windows\Fonts\YuGothB.ttc",
    r"C:\Windows\Fonts\YuGothM.ttc",
    r"C:\Windows\Fonts\BIZ-UDPGothicB.ttc",
    r"C:\Windows\Fonts\msgothic.ttc",
    r"C:\Windows\Fonts\msmincho.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
    "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
)

WHITE = 255
INK = 30
RULE = 90


def find_font_path() -> Path | None:
    """利用できる日本語フォントを1つ探す。見つからなければ None。"""
    for candidate in FONT_CANDIDATES:
        path = Path(candidate)
        if path.is_file():
            return path
    return None


def _load_font(font_path: Path | None, size: int) -> ImageFont.ImageFont:
    """指定サイズのフォントを読む。TrueType が無ければ既定ビットマップに落とす。"""
    if font_path is not None:
        try:
            return ImageFont.truetype(str(font_path), size)
        except OSError:
            pass
    # フォントが一切無い環境でも表紙生成そのものは成功させる。
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow 9 以前は size 引数を取らない
        return ImageFont.load_default()


def _text_size(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int]:
    if not text:
        return (0, 0)
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    return (right - left, bottom - top)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    """日本語向けの折り返し。単語区切りが無いので原則1文字ずつ詰める。

    ただし ASCII の単語は途中で割らず、直前の空白まで戻して改行する。
    """
    lines: list[str] = []
    for paragraph in text.splitlines() or [""]:
        current = ""
        for char in paragraph:
            candidate = current + char
            if current and _text_size(draw, candidate, font)[0] > max_width:
                if char.isascii() and char != " " and " " in current.rstrip():
                    head, _, tail = current.rstrip().rpartition(" ")
                    lines.append(head)
                    current = tail + char
                else:
                    lines.append(current)
                    current = char
            else:
                current = candidate
        lines.append(current)
    return lines or [""]


def _fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font_path: Path | None,
    max_width: int,
    max_height: int,
    max_size: int,
    min_size: int,
) -> tuple[object, list[str], int]:
    """枠に収まる最大のフォントサイズを探し、(font, lines, line_height) を返す。"""
    size = max(min_size, max_size)
    while size > min_size:
        font = _load_font(font_path, size)
        lines = _wrap(draw, text, font, max_width)
        line_height = int(size * 1.35)
        if len(lines) * line_height <= max_height:
            return (font, lines, line_height)
        size -= max(1, size // 12)

    font = _load_font(font_path, min_size)
    lines = _wrap(draw, text, font, max_width)
    return (font, lines, int(min_size * 1.35))


def render_generated_cover(title: str, issue: str, device: Device) -> Image.Image:
    """雑誌名＋号から表紙を描く。"""
    width, height = device.size
    canvas = Image.new("L", (width, height), WHITE)
    draw = ImageDraw.Draw(canvas)
    font_path = find_font_path()

    # 外枠
    inset = int(min(width, height) * 0.055)
    border = max(2, int(min(width, height) * 0.004))
    draw.rectangle(
        (inset, inset, width - inset - 1, height - inset - 1),
        outline=RULE,
        width=border,
    )

    content_width = width - inset * 2 - int(width * 0.10)
    left = (width - content_width) // 2

    title_font, title_lines, title_line_height = _fit_text(
        draw,
        title or "無題",
        font_path,
        max_width=content_width,
        max_height=int(height * 0.34),
        max_size=int(height * 0.10),
        min_size=max(16, int(height * 0.028)),
    )

    if issue:
        issue_font, issue_lines, issue_line_height = _fit_text(
            draw,
            issue,
            font_path,
            max_width=content_width,
            max_height=int(height * 0.12),
            max_size=int(height * 0.048),
            min_size=max(12, int(height * 0.02)),
        )
    else:
        issue_font, issue_lines, issue_line_height = None, [], 0

    title_block = len(title_lines) * title_line_height
    issue_block = len(issue_lines) * issue_line_height
    rule_gap = int(height * 0.045)
    total = title_block + (rule_gap * 2 + issue_block if issue_lines else 0)
    y = max(inset * 2, (height - total) // 2 - int(height * 0.04))

    for line in title_lines:
        line_width, _ = _text_size(draw, line, title_font)
        draw.text(
            (left + (content_width - line_width) // 2, y),
            line,
            font=title_font,
            fill=INK,
        )
        y += title_line_height

    if issue_lines:
        y += rule_gap
        rule_width = int(content_width * 0.42)
        rule_x = (width - rule_width) // 2
        draw.rectangle(
            (rule_x, y, rule_x + rule_width, y + max(1, border // 2)),
            fill=RULE,
        )
        y += rule_gap
        for line in issue_lines:
            line_width, _ = _text_size(draw, line, issue_font)
            draw.text(
                (left + (content_width - line_width) // 2, y),
                line,
                font=issue_font,
                fill=INK,
            )
            y += issue_line_height

    return canvas


def load_cover_image(path: Path, device: Device, options: ImageOptions) -> Image.Image:
    """ユーザー指定の画像を表紙として整形する。"""
    try:
        with Image.open(path) as source:
            source.load()
            image = source.copy()
    except OSError as e:
        raise InkFlowError(f"表紙画像を読み込めません: {path}") from e
    return imaging.finalize_page(image, device.size, options)


def build_cover(project: Project, device: Device, options: ImageOptions) -> Image.Image:
    """プロジェクトの設定に従って表紙画像を返す。"""
    if project.cover_image is not None and Path(project.cover_image).is_file():
        return load_cover_image(Path(project.cover_image), device, options)

    canvas = render_generated_cover(project.title, project.issue, device)
    if options.format == "png":
        # 生成した表紙は既に階調が単純なので、コントラスト補正やシャープは掛けない。
        return imaging.quantize_gray(canvas, options.gray_levels)
    return canvas
