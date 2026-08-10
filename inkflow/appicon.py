"""アプリアイコンの生成。

バイナリ資産をリポジトリに置かない方針なので、アイコンもコードから描く
（表紙を `cover.py` で生成しているのと同じ考え方）。

図柄は InkFlow の機能そのもの——縦長の版面が4分割され、いま読んでいる左上のコマ
だけが濃い——を、線と塗りだけで表す。16px でも潰れないよう、細部を持たせない。

Qt には依存させない。QIcon への変換は GUI 側（`gui/app.py`）で行う。
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

# Windows のタスクバー・エクスプローラ・Alt+Tab が使い分けるサイズ。
ICO_SIZES: tuple[int, ...] = (16, 32, 48, 256)

BACKGROUND = (255, 255, 255, 0)
PAGE_FILL = (255, 255, 255, 255)
PAGE_EDGE = (33, 37, 41, 255)
ACTIVE_FILL = (28, 126, 214, 255)
DIVIDER = (108, 117, 125, 255)


def render_icon(size: int = 256) -> Image.Image:
    """1サイズぶんのアイコンを描く（RGBA）。"""
    size = max(8, int(size))
    image = Image.new("RGBA", (size, size), BACKGROUND)
    draw = ImageDraw.Draw(image)

    # 紙面（B5 に近い縦横比）を中央に置く。
    page_h = size * 0.86
    page_w = page_h * 0.72
    left = (size - page_w) / 2
    top = (size - page_h) / 2
    right = left + page_w
    bottom = top + page_h

    edge = max(1, round(size / 32))
    draw.rectangle((left, top, right, bottom), fill=PAGE_FILL, outline=PAGE_EDGE, width=edge)

    middle_x = left + page_w / 2
    middle_y = top + page_h / 2

    # 読み始めのコマ（左上）だけを塗って、読み順の起点を示す。
    draw.rectangle((left + edge, top + edge, middle_x, middle_y), fill=ACTIVE_FILL)

    # 分割線。
    divider = max(1, round(size / 48))
    draw.line((middle_x, top + edge, middle_x, bottom - edge), fill=DIVIDER, width=divider)
    draw.line((left + edge, middle_y, right - edge, middle_y), fill=DIVIDER, width=divider)

    return image


def write_ico(path: Path, sizes: tuple[int, ...] = ICO_SIZES) -> Path:
    """複数サイズを1つの ``.ico`` にまとめて書き出す。"""
    path = Path(path)
    if not sizes:
        raise ValueError("sizes には少なくとも1つのサイズを指定してください。")
    path.parent.mkdir(parents=True, exist_ok=True)

    ordered = tuple(sorted({max(8, int(s)) for s in sizes}))
    largest = render_icon(max(ordered))
    # Pillow は sizes を渡すと各サイズを内部で縮小して同梱してくれる。
    largest.save(path, format="ICO", sizes=[(s, s) for s in ordered])
    return path


def write_png(path: Path, size: int = 256) -> Path:
    """1枚の PNG として書き出す（ドキュメントや確認用）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    render_icon(size).save(path, format="PNG")
    return path
