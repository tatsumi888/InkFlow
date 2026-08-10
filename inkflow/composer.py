"""再ページ化（原稿ページ → 出力ページ列）。

1ページにつき
``下見レンダリング → 余白トリム位置の決定 → 必要DPIの算出 → 本レンダリング1回``
だけを行い、俯瞰ページと各コマはその1枚からのクロップで作る。40ページ×5コマ＝
200枚を作る場合でも、レンダリング自体は40回で済む。

出力はジェネレータにしてある。200枚ぶんの生画像（1枚あたり約2MB）を同時に抱え
込まないようにするため。
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from pathlib import Path

from PIL import Image

from . import imaging, layouts, renderer
from .models import Article, PageDefaults, PageSpec, Project

ProgressCallback = Callable[[int, int], None]


@dataclass(frozen=True)
class ComposedPage:
    """出力ページ1枚。"""

    image: Image.Image
    article_index: int
    article_title: str
    source_page_index: int
    part_index: int
    is_overview: bool
    is_article_start: bool


def page_specs_for(article: Article, page_count: int, defaults: PageDefaults) -> list[PageSpec]:
    """実PDFのページ数に合わせた PageSpec 列を返す（プロジェクトは変更しない）。"""
    specs = [replace(spec) for spec in article.pages[:page_count]]
    while len(specs) < page_count:
        specs.append(defaults.to_page_spec())
    return specs


def sync_page_counts(project: Project) -> None:
    """各記事の PageSpec 数を、実PDFのページ数に合わせる。"""
    for article in project.articles:
        page_count = renderer.probe_page_count(article.path)
        article.sync_page_count(page_count, project.defaults)


def total_output_pages(project: Project, sync: bool = True) -> int:
    """表紙を除いた総出力ページ数を求める。"""
    total = 0
    for article in project.articles:
        page_count = (
            renderer.probe_page_count(article.path) if sync else len(article.pages)
        )
        for spec in page_specs_for(article, page_count, project.defaults):
            total += spec.output_page_count()
    return total


def compose(
    project: Project,
    on_progress: ProgressCallback | None = None,
) -> Iterator[ComposedPage]:
    """プロジェクト全体を出力ページ列に展開する。"""
    device = project.device()
    defaults = project.defaults
    options = project.image
    total = total_output_pages(project)
    done = 0

    for article_index, article in enumerate(project.articles):
        is_article_start = True
        with renderer.PdfDocument(article.path) as document:
            specs = page_specs_for(article, document.page_count, defaults)
            for page_index, spec in enumerate(specs):
                for image, part_index, is_overview in _compose_page(
                    document, page_index, spec, defaults, device, options
                ):
                    composed = ComposedPage(
                        image=image,
                        article_index=article_index,
                        article_title=article.title,
                        source_page_index=page_index,
                        part_index=part_index,
                        is_overview=is_overview,
                        is_article_start=is_article_start,
                    )
                    is_article_start = False
                    done += 1
                    # 生成できた時点で進捗を報告する（消費を待たない）。
                    if on_progress is not None:
                        on_progress(done, total)
                    yield composed


def _compose_page(
    document: renderer.PdfDocument,
    page_index: int,
    spec: PageSpec,
    defaults: PageDefaults,
    device,
    options,
) -> Iterator[tuple[Image.Image, int, bool]]:
    """1ページぶんのコマを (画像, コマ番号, 俯瞰か) で返す。"""
    layout = layouts.get_layout(spec.layout_id)
    geometry = document.geometry(page_index)

    content_rect = (0.0, 0.0, 1.0, 1.0)
    if defaults.auto_trim:
        probe = document.render(page_index, renderer.PROBE_DPI)
        content_rect = imaging.find_content_bbox(probe, threshold=defaults.trim_threshold)

    content_width_in = geometry.width_in * (content_rect[2] - content_rect[0])
    content_height_in = geometry.height_in * (content_rect[3] - content_rect[1])

    overview_rotation = spec.effective_overview_rotation()
    has_overview = layout.id == "full" or spec.include_overview

    dpi = _required_dpi_for_page(
        content_width_in,
        content_height_in,
        spec,
        layout,
        device,
        has_overview=has_overview,
        overview_rotation=overview_rotation,
    )

    page_image = document.render(page_index, dpi)
    content = imaging.crop_relative(page_image, content_rect)

    def to_output(image: Image.Image, rotation: int) -> Image.Image:
        # 回転は finalize_page の**前**に行う。あとから回すと、白パディング込みで
        # 回ってしまい端末解像度に収まらなくなる。
        return imaging.finalize_page(
            imaging.rotate_image(image, rotation), device.size, options
        )

    if layout.id == "full":
        # 俯瞰と分割が同じ絵になるので1枚に畳む。向きは俯瞰側の設定に従う。
        yield (to_output(content, overview_rotation), 0, True)
        return

    if spec.include_overview:
        yield (to_output(content, overview_rotation), -1, True)

    x_offsets, y_offsets = resolve_divider_offsets(
        content, spec.layout_id, spec.column_bias, spec.row_bias
    )
    rects = layouts.reading_rects(spec.layout_id, defaults.overlap, x_offsets, y_offsets)
    for part_index, rect in enumerate(rects):
        yield (to_output(imaging.crop_relative(content, rect), spec.rotate), part_index, False)


def resolve_divider_offsets(
    content_image: Image.Image,
    layout_id: str,
    column_bias: float | None,
    row_bias: float | None,
) -> tuple[dict[float, float], dict[float, float]]:
    """このページで実際に使う分割線オフセットを決める。

    軸ごとに、手動指定（``column_bias``/``row_bias``）があればそれを全ての分割線に
    一律適用し、自動検出は行わない。手動指定が無ければ分割線ごとに自動検出する
    （見つからなければオフセット無し＝既定位置のまま。安全側のフォールバック）。
    """
    xs, ys = layouts.internal_dividers(layout_id)

    if column_bias is not None:
        x_offsets = dict.fromkeys(xs, column_bias)
    else:
        x_offsets = {
            x: offset
            for x in xs
            if (offset := imaging.find_divider_offset(content_image, "x", x)) is not None
        }

    if row_bias is not None:
        y_offsets = dict.fromkeys(ys, row_bias)
    else:
        y_offsets = {
            y: offset
            for y in ys
            if (offset := imaging.find_divider_offset(content_image, "y", y)) is not None
        }

    return (x_offsets, y_offsets)


def _required_dpi_for_page(
    content_width_in: float,
    content_height_in: float,
    spec: PageSpec,
    layout: layouts.Layout,
    device,
    *,
    has_overview: bool,
    overview_rotation: int,
) -> float:
    """そのページの出力すべてを拡大せずに賄える解像度を返す。

    俯瞰と分割コマで回転が違うと、必要な解像度も別々になる。1ページにつき
    レンダリングは1回という原則を保つため、**両方の要求を満たす大きい方**を採る。

    出力しない側は計算に入れない（俯瞰なしの設定で無駄に高い解像度を使わないため）。
    """
    requirements: list[float] = []

    if has_overview:
        # 俯瞰はページ全面なので、最小コマの相対サイズは (1.0, 1.0)。
        requirements.append(
            renderer.required_dpi(
                content_width_in,
                content_height_in,
                (1.0, 1.0),
                device,
                rotated=overview_rotation != 0,
            )
        )

    if layout.id != "full":
        requirements.append(
            renderer.required_dpi(
                content_width_in,
                content_height_in,
                layouts.min_relative_size(spec.layout_id),
                device,
                rotated=spec.rotate != 0,
            )
        )

    return max(requirements)


def preview_rects(
    spec: PageSpec,
    defaults: PageDefaults,
    x_offsets: dict[float, float] | None = None,
    y_offsets: dict[float, float] | None = None,
) -> tuple[tuple[float, ...], ...]:
    """GUI が枠を描くための矩形列（本文領域を基準とした相対座標）。

    ``x_offsets``/``y_offsets`` を渡すと、実際の出力と同じ位置（自動検出 or 手動
    微調整の結果）で枠を描ける。省略時はレイアウトの既定位置のまま。
    """
    return layouts.reading_rects(spec.layout_id, defaults.overlap, x_offsets, y_offsets)


def content_rect_for(
    cache: renderer.PreviewCache,
    path: Path,
    page_index: int,
    defaults: PageDefaults,
) -> tuple[float, float, float, float]:
    """GUI プレビュー用に、余白トリム後の本文領域を求める。"""
    if not defaults.auto_trim:
        return (0.0, 0.0, 1.0, 1.0)
    probe = cache.render(path, page_index, renderer.PROBE_DPI)
    return imaging.find_content_bbox(probe, threshold=defaults.trim_threshold)
