"""テスト共通のフィクスチャ。

実物の雑誌PDFは持ち込めないので、PyMuPDF で「2段組の本文が余白付きで組まれた
B5ページ」を合成し、それを入力として使う。
"""

from __future__ import annotations

import os
from pathlib import Path

# GUI テストをヘッドレスで走らせる。Qt を import する前に設定する必要がある。
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pymupdf  # noqa: E402
import pytest  # noqa: E402

# B5（182mm x 257mm）をポイントに換算した値。
B5_WIDTH_PT = 515.9
B5_HEIGHT_PT = 728.5


FILLER = "the quick brown fox jumps over the lazy dog 0123456789. "


def _fill_column(rect, page, page_index: int, column: int, fontsize: float = 9.0) -> None:
    """段の矩形いっぱいに本文を流し込む。

    ``insert_textbox`` は入り切らないと**何も描かない**（戻り値が負になる）ので、
    収まる長さが見つかるまで短くしていく。版面が余白いっぱいに広がっていないと、
    余白トリムや回転の効果を実物どおりに再現できない。
    """
    head = f"page {page_index + 1} column {column + 1}. "
    repeats = 80
    while repeats > 0:
        overflow = page.insert_textbox(
            rect, head + FILLER * repeats, fontsize=fontsize, fontname="helv", align=3
        )
        if overflow >= 0:
            return
        repeats -= 4
    raise RuntimeError("段に本文を流し込めませんでした（矩形が小さすぎます）")


def make_pdf(
    path: Path,
    page_count: int = 1,
    width_pt: float = B5_WIDTH_PT,
    height_pt: float = B5_HEIGHT_PT,
    columns: int = 2,
    margin_pt: float = 50.0,
    blank: bool = False,
) -> Path:
    """合成PDFを書き出してパスを返す。"""
    doc = pymupdf.open()
    for page_index in range(page_count):
        page = doc.new_page(width=width_pt, height=height_pt)
        if blank:
            continue

        usable_width = width_pt - margin_pt * 2
        gutter = 16.0
        column_width = (usable_width - gutter * (columns - 1)) / columns
        for column in range(columns):
            x = margin_pt + column * (column_width + gutter)
            rect = pymupdf.Rect(x, margin_pt, x + column_width, height_pt - margin_pt)
            _fill_column(rect, page, page_index, column)
    doc.save(str(path))
    doc.close()
    return path


def make_asymmetric_pdf(
    path: Path,
    gutter_center_ratio: float = 0.35,
    page_count: int = 1,
    width_pt: float = B5_WIDTH_PT,
    height_pt: float = B5_HEIGHT_PT,
    margin_pt: float = 50.0,
) -> Path:
    """左右の段幅が非対称な2段組PDF。ノドの中心が ``gutter_center_ratio`` の位置にある。

    ``quad_2col`` の固定50%分割がノドからズレて本文を切ってしまう状況
    （実サンプルで実際に踏んだ不具合）を再現するために使う。
    """
    doc = pymupdf.open()
    gutter_half_pt = 8.0
    usable_left = margin_pt
    usable_right = width_pt - margin_pt
    gutter_center_pt = usable_left + (usable_right - usable_left) * gutter_center_ratio
    for page_index in range(page_count):
        page = doc.new_page(width=width_pt, height=height_pt)
        left_rect = pymupdf.Rect(
            usable_left, margin_pt, gutter_center_pt - gutter_half_pt, height_pt - margin_pt
        )
        right_rect = pymupdf.Rect(
            gutter_center_pt + gutter_half_pt, margin_pt, usable_right, height_pt - margin_pt
        )
        _fill_column(left_rect, page, page_index, 0)
        _fill_column(right_rect, page, page_index, 1)
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    """2ページ・2段組の合成PDF。"""
    return make_pdf(tmp_path / "sample.pdf", page_count=2)


@pytest.fixture
def single_page_pdf(tmp_path: Path) -> Path:
    return make_pdf(tmp_path / "single.pdf", page_count=1)


@pytest.fixture
def blank_pdf(tmp_path: Path) -> Path:
    return make_pdf(tmp_path / "blank.pdf", page_count=1, blank=True)


@pytest.fixture
def article_pdfs(tmp_path: Path) -> list[Path]:
    """記事3本ぶんのPDF（2ページ・1ページ・3ページ）。"""
    directory = tmp_path / "articles"
    directory.mkdir(parents=True, exist_ok=True)
    return [
        make_pdf(directory / "01_巻頭特集.pdf", page_count=2),
        make_pdf(directory / "02_インタビュー.pdf", page_count=1),
        make_pdf(directory / "03_連載.pdf", page_count=3),
    ]
