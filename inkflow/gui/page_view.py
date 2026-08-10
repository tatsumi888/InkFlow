"""分割枠を重ねて表示するページプレビュー。

「出力するとどうなるか」を一目で分かるようにするのがこのウィジェットの役割。
枠だけでなく**読み順の番号**を出すのが肝で、二段組4分割の「左上→左下→右上→右下」
が意図どおりかを目視で確かめられる。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QImage,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from PIL import Image

BACKDROP = QColor("#4a4d52")
PAGE_SHADOW = QColor(0, 0, 0, 60)
TRIM_PEN = QColor("#2f9e44")
PART_PEN = QColor("#1c7ed6")
PART_FILL = QColor(28, 126, 214, 26)
PART_FILL_ALT = QColor(28, 126, 214, 52)
BADGE_BG = QColor("#1c7ed6")
OVERVIEW_BADGE_BG = QColor("#e8590c")
ROTATION_BADGE_BG = QColor("#5f3dc4")
BADGE_FG = QColor("#ffffff")
HINT_COLOR = QColor("#e9ecef")

MARGIN = 16


@dataclass
class PageOverlay:
    """プレビューに重ねる情報。"""

    content_rect: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0)
    part_rects: tuple[tuple[float, float, float, float], ...] = ()
    include_overview: bool = True
    show_trim: bool = True
    labels: list[str] = field(default_factory=list)
    rotation_label: str = ""
    # 分割コマと向きが違うときだけ入る。
    overview_rotation_label: str = ""


def pil_to_qimage(image: Image.Image) -> QImage:
    """PIL の画像を QImage に変換する（グレースケール8bitで扱う）。"""
    gray = image if image.mode == "L" else image.convert("L")
    data = gray.tobytes()
    qimage = QImage(data, gray.width, gray.height, gray.width, QImage.Format.Format_Grayscale8)
    # QImage は渡したバッファを参照するだけなので、コピーして寿命を切り離す。
    return qimage.copy()


class PageView(QWidget):
    """1ページぶんのプレビュー。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self._overlay = PageOverlay()
        self._hint = "PDFを追加してください（ドラッグ＆ドロップでも追加できます）"
        self.setMinimumSize(320, 420)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    # ---- 表示内容の設定 -----------------------------------------------

    def set_page(self, image: Image.Image, overlay: PageOverlay) -> None:
        self._pixmap = QPixmap.fromImage(pil_to_qimage(image))
        self._overlay = overlay
        self.update()

    def set_overlay(self, overlay: PageOverlay) -> None:
        self._overlay = overlay
        self.update()

    def clear(self, hint: str | None = None) -> None:
        self._pixmap = None
        if hint is not None:
            self._hint = hint
        self.update()

    def has_page(self) -> bool:
        return self._pixmap is not None

    # ---- 描画 ---------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt の命名規則
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.fillRect(self.rect(), BACKDROP)

        if self._pixmap is None:
            self._paint_hint(painter)
            return

        page_rect = self._page_rect()
        painter.fillRect(page_rect.translated(3, 3), PAGE_SHADOW)
        painter.drawPixmap(page_rect, self._pixmap, QRectF(self._pixmap.rect()))

        content_rect = self._map_rect(page_rect, self._overlay.content_rect)
        if self._overlay.show_trim:
            self._paint_trim(painter, content_rect)
        self._paint_parts(painter, content_rect)
        if self._overlay.include_overview:
            self._paint_overview_badge(painter, page_rect)
        # プレビュー自体は回さない。回すと分割枠と読み順番号の位置関係が
        # 直感と合わなくなり、「どこで切れるか」を確かめるという役割を損なう。
        self._paint_rotation_badges(painter, page_rect)

    def _paint_hint(self, painter: QPainter) -> None:
        painter.setPen(QPen(HINT_COLOR))
        font = painter.font()
        font.setPointSizeF(max(9.0, font.pointSizeF()))
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._hint)

    def _paint_trim(self, painter: QPainter, content_rect: QRectF) -> None:
        pen = QPen(TRIM_PEN, 1.5, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(content_rect)

    def _paint_parts(self, painter: QPainter, content_rect: QRectF) -> None:
        for index, rect in enumerate(self._overlay.part_rects):
            mapped = self._map_rect(content_rect, rect)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(PART_FILL_ALT if index % 2 else PART_FILL)
            painter.drawRect(mapped)
            painter.setPen(QPen(PART_PEN, 1.6))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(mapped)
            label = (
                self._overlay.labels[index]
                if index < len(self._overlay.labels)
                else str(index + 1)
            )
            self._paint_badge(painter, mapped.topLeft() + QPointF(14, 14), label, BADGE_BG)

    def _paint_overview_badge(self, painter: QPainter, page_rect: QRectF) -> None:
        self._paint_badge(
            painter,
            page_rect.topRight() + QPointF(-16, 16),
            "全",
            OVERVIEW_BADGE_BG,
        )

    def _paint_rotation_badges(self, painter: QPainter, page_rect: QRectF) -> None:
        """回転の設定を、ページ左上の角丸ラベルで示す。

        円形バッジ（俯瞰の「全」・読み順の数字）とは形を変えて区別する。分割コマと
        俯瞰で向きが違うときは、どちらがどちらか分かるよう2つ並べる。
        """
        labels: list[str] = []
        if self._overlay.rotation_label:
            prefix = "分割 " if self._overlay.overview_rotation_label else ""
            labels.append(f"⟲ {prefix}{self._overlay.rotation_label}")
        if self._overlay.overview_rotation_label:
            labels.append(f"⟲ 俯瞰 {self._overlay.overview_rotation_label}")
        if not labels:
            return

        font = QFont(painter.font())
        font.setBold(True)
        font.setPointSizeF(10.0)
        painter.setFont(font)

        top = page_rect.y() + 8
        for label in labels:
            width = painter.fontMetrics().horizontalAdvance(label) + 18
            height = painter.fontMetrics().height() + 8
            box = QRectF(page_rect.x() + 8, top, width, height)

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(ROTATION_BADGE_BG)
            painter.drawRoundedRect(box, 6, 6)
            painter.setPen(QPen(BADGE_FG))
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, label)
            top += height + 4

    def _paint_badge(
        self, painter: QPainter, center: QPointF, text: str, color: QColor
    ) -> None:
        radius = 13.0
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(center, radius, radius)
        painter.setPen(QPen(BADGE_FG))
        font = QFont(painter.font())
        font.setBold(True)
        font.setPointSizeF(10.0)
        painter.setFont(font)
        painter.drawText(
            QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2),
            Qt.AlignmentFlag.AlignCenter,
            text,
        )

    # ---- 座標計算 -----------------------------------------------------

    def _page_rect(self) -> QRectF:
        """ウィジェット内に収まるようページ画像を配置する矩形。"""
        assert self._pixmap is not None
        available_w = max(1, self.width() - MARGIN * 2)
        available_h = max(1, self.height() - MARGIN * 2)
        scale = min(
            available_w / self._pixmap.width(),
            available_h / self._pixmap.height(),
        )
        width = self._pixmap.width() * scale
        height = self._pixmap.height() * scale
        return QRectF(
            (self.width() - width) / 2,
            (self.height() - height) / 2,
            width,
            height,
        )

    @staticmethod
    def _map_rect(base: QRectF, rect: tuple[float, float, float, float]) -> QRectF:
        x0, y0, x1, y1 = rect
        return QRectF(
            base.x() + x0 * base.width(),
            base.y() + y0 * base.height(),
            (x1 - x0) * base.width(),
            (y1 - y0) * base.height(),
        )
