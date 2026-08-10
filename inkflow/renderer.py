"""PDF のラスタライズ（PyMuPDF）。

PDF は「単純に画像として扱う」方針のため、テキスト層の有無に関わらず同じ経路を
通る。1ページにつき高解像度レンダリングは**1回だけ**行い、俯瞰ページも各コマも
その1枚からのクロップで賄う。
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

import pymupdf
from PIL import Image

from .devices import Device
from .errors import PdfLoadError, RenderError

# 余白トリム位置を調べるための下見レンダリング解像度。
PROBE_DPI = 72

MIN_DPI = 72
MAX_DPI = 600

PDF_UNITS_PER_INCH = 72.0


@dataclass(frozen=True)
class PageGeometry:
    """PDF ページの物理サイズ（ポイント単位）。"""

    width_pt: float
    height_pt: float

    @property
    def width_in(self) -> float:
        return self.width_pt / PDF_UNITS_PER_INCH

    @property
    def height_in(self) -> float:
        return self.height_pt / PDF_UNITS_PER_INCH


class PdfDocument:
    """PDF 1ファイル。with 文で使う。"""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        if not self.path.is_file():
            raise PdfLoadError(f"PDFが見つかりません: {self.path}")
        try:
            self._doc = pymupdf.open(str(self.path))
        except Exception as e:  # noqa: BLE001 - MuPDF の例外を一律に変換する
            raise PdfLoadError(f"PDFを開けません: {self.path}（{e}）") from e
        if self._doc.needs_pass:
            self._doc.close()
            raise PdfLoadError(f"パスワード保護されたPDFには対応していません: {self.path}")
        if self._doc.page_count == 0:
            self._doc.close()
            raise PdfLoadError(f"ページが1枚もありません: {self.path}")

    # ---- 情報 ---------------------------------------------------------

    @property
    def page_count(self) -> int:
        return self._doc.page_count

    def geometry(self, index: int) -> PageGeometry:
        page = self._load_page(index)
        rect = page.rect
        return PageGeometry(width_pt=rect.width, height_pt=rect.height)

    # ---- レンダリング -------------------------------------------------

    def render(self, index: int, dpi: float) -> Image.Image:
        """ページをグレースケール画像としてラスタライズする。

        MuPDF 側で直接グレースケール出力させることで、RGB を経由するより
        メモリを 1/3 に抑える。
        """
        page = self._load_page(index)
        zoom = max(MIN_DPI, min(MAX_DPI, float(dpi))) / PDF_UNITS_PER_INCH
        try:
            pixmap = page.get_pixmap(
                matrix=pymupdf.Matrix(zoom, zoom),
                colorspace=pymupdf.csGRAY,
                alpha=False,
            )
            return Image.frombytes("L", (pixmap.width, pixmap.height), pixmap.samples)
        except Exception as e:  # noqa: BLE001
            raise RenderError(
                f"ページのレンダリングに失敗しました: {self.path} の {index + 1} ページ目（{e}）"
            ) from e

    # ---- 後始末 -------------------------------------------------------

    def close(self) -> None:
        if getattr(self, "_doc", None) is not None and not self._doc.is_closed:
            self._doc.close()

    def __enter__(self) -> "PdfDocument":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ---- 内部 ---------------------------------------------------------

    def _load_page(self, index: int):
        if not 0 <= index < self._doc.page_count:
            raise RenderError(
                f"ページ番号が範囲外です: {self.path} の {index + 1} ページ目"
                f"（全 {self._doc.page_count} ページ）"
            )
        try:
            return self._doc.load_page(index)
        except Exception as e:  # noqa: BLE001
            raise RenderError(
                f"ページを読み込めません: {self.path} の {index + 1} ページ目（{e}）"
            ) from e


def probe_page_count(path: Path) -> int:
    """PDF のページ数だけを取得する。"""
    with PdfDocument(path) as doc:
        return doc.page_count


def required_dpi(
    content_width_in: float,
    content_height_in: float,
    min_rel: tuple[float, float],
    device: Device,
    rotated: bool = False,
) -> float:
    """コマが拡大されずに画面いっぱいへ収まる、必要十分なレンダリング解像度を返す。

    ``content_*_in`` は余白トリム後の本文領域の物理サイズ、``min_rel`` はレイアウト
    中で最も小さいコマの相対幅・相対高さ。

    縦横それぞれの「1インチあたり何画素あれば画面を埋められるか」を求め、**小さい方**
    を採る。コマは縦横比を保ったまま画面に収める（contain）ので、実際に効くのは縦横
    どちらか一方の制約だけであり、大きい方に合わせると使われない解像度まで刻むことに
    なる。小さい方を採ると、収めたあとの倍率がちょうど 1.0 になり、拡大による滲みも
    縮小による再サンプリングも起きない。

    ``rotated=True`` のときは端末の幅と高さを入れ替える。コマを90°回すと、コマの幅が
    端末の高さに、高さが幅に対応するため。
    """
    min_rel_w, min_rel_h = min_rel
    crop_w_in = max(1e-6, content_width_in * max(1e-6, min_rel_w))
    crop_h_in = max(1e-6, content_height_in * max(1e-6, min_rel_h))
    target_w, target_h = (device.height, device.width) if rotated else device.size
    dpi = min(target_w / crop_w_in, target_h / crop_h_in)
    return max(MIN_DPI, min(MAX_DPI, dpi))


class PreviewCache:
    """GUI プレビュー用の LRU キャッシュ。

    開いた PdfDocument とレンダリング済み画像の双方を保持し、ページ送りを軽くする。
    """

    def __init__(self, max_images: int = 8, max_documents: int = 4) -> None:
        self._max_images = max_images
        self._max_documents = max_documents
        self._images: OrderedDict[tuple[str, int, int], Image.Image] = OrderedDict()
        self._documents: OrderedDict[str, PdfDocument] = OrderedDict()

    def render(self, path: Path, index: int, dpi: float) -> Image.Image:
        key = (str(Path(path).resolve()), index, int(round(dpi)))
        cached = self._images.get(key)
        if cached is not None:
            self._images.move_to_end(key)
            return cached

        image = self._document(path).render(index, dpi)
        self._images[key] = image
        self._images.move_to_end(key)
        while len(self._images) > self._max_images:
            self._images.popitem(last=False)
        return image

    def page_count(self, path: Path) -> int:
        return self._document(path).page_count

    def geometry(self, path: Path, index: int) -> PageGeometry:
        return self._document(path).geometry(index)

    def invalidate(self, path: Path | None = None) -> None:
        if path is None:
            self._images.clear()
            for doc in self._documents.values():
                doc.close()
            self._documents.clear()
            return
        key = str(Path(path).resolve())
        for image_key in [k for k in self._images if k[0] == key]:
            del self._images[image_key]
        doc = self._documents.pop(key, None)
        if doc is not None:
            doc.close()

    def close(self) -> None:
        self.invalidate()

    def _document(self, path: Path) -> PdfDocument:
        key = str(Path(path).resolve())
        doc = self._documents.get(key)
        if doc is not None:
            self._documents.move_to_end(key)
            return doc
        doc = PdfDocument(path)
        self._documents[key] = doc
        while len(self._documents) > self._max_documents:
            _, evicted = self._documents.popitem(last=False)
            evicted.close()
        return doc
