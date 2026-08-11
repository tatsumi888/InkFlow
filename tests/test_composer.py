from pathlib import Path

import pytest

from inkflow import composer, devices, imaging, layouts
from inkflow.builder import project_from_pdfs
from inkflow.models import PageDefaults, PageSpec, Project

DEVICE = devices.get_device("paperwhite_11")


def make_project(pdfs, **kwargs) -> Project:
    return project_from_pdfs(pdfs, title="テスト誌", issue="2026年8月号", **kwargs)


def test_default_layout_produces_five_pages_per_source_page(single_page_pdf):
    project = make_project([single_page_pdf])
    pages = list(composer.compose(project))
    assert len(pages) == 5


def test_reading_order_is_overview_then_four_quadrants(single_page_pdf):
    project = make_project([single_page_pdf])
    pages = list(composer.compose(project))
    assert [p.is_overview for p in pages] == [True, False, False, False, False]
    assert [p.part_index for p in pages] == [-1, 0, 1, 2, 3]


def test_overview_can_be_disabled(single_page_pdf):
    project = make_project([single_page_pdf])
    project.apply_layout_to_all(PageSpec("quad_2col", include_overview=False))
    pages = list(composer.compose(project))
    assert len(pages) == 4
    assert not any(p.is_overview for p in pages)


def test_full_layout_yields_single_page(single_page_pdf):
    project = make_project([single_page_pdf])
    project.apply_layout_to_all(PageSpec("full", include_overview=True))
    pages = list(composer.compose(project))
    assert len(pages) == 1
    assert pages[0].is_overview is True


def test_mixed_layouts_across_pages(sample_pdf):
    project = make_project([sample_pdf])
    project.articles[0].pages[0] = PageSpec("full")
    project.articles[0].pages[1] = PageSpec("half_v", include_overview=True)
    pages = list(composer.compose(project))
    # 1枚 + (俯瞰1 + 上下2) = 4枚
    assert len(pages) == 4
    assert [p.source_page_index for p in pages] == [0, 1, 1, 1]


def test_all_output_images_match_device_resolution(single_page_pdf):
    project = make_project([single_page_pdf])
    for page in composer.compose(project):
        assert page.image.size == DEVICE.size


def test_output_images_are_16_level_palette_for_png(single_page_pdf):
    project = make_project([single_page_pdf])
    page = next(composer.compose(project))
    assert page.image.mode == "P"
    assert len(page.image.getcolors(maxcolors=300)) <= 16


def test_article_start_flag_marks_first_page_of_each_article(article_pdfs):
    project = make_project(article_pdfs)
    pages = list(composer.compose(project))
    starts = [index for index, page in enumerate(pages) if page.is_article_start]
    # 2ページ記事(10枚) → 1ページ記事(5枚) → 3ページ記事(15枚)
    assert starts == [0, 10, 15]
    assert [pages[i].article_title for i in starts] == [
        "01_巻頭特集",
        "02_インタビュー",
        "03_連載",
    ]


def test_article_index_is_sequential(article_pdfs):
    project = make_project(article_pdfs)
    indices = sorted({page.article_index for page in composer.compose(project)})
    assert indices == [0, 1, 2]


def test_total_output_pages_matches_composed_count(article_pdfs):
    project = make_project(article_pdfs)
    assert composer.total_output_pages(project) == len(list(composer.compose(project)))


def test_total_output_pages_for_forty_source_pages(tmp_path):
    from .conftest import make_pdf

    pdf = make_pdf(tmp_path / "big.pdf", page_count=8)
    project = make_project([pdf])
    # 8ページ x 5 = 40枚
    assert composer.total_output_pages(project) == 40


def test_progress_callback_reports_monotonic_progress(article_pdfs):
    project = make_project(article_pdfs)
    events: list[tuple[int, int]] = []
    list(composer.compose(project, on_progress=lambda done, total: events.append((done, total))))
    assert events[0][0] == 1
    assert events[-1][0] == events[-1][1] == len(events)
    assert [done for done, _ in events] == sorted(done for done, _ in events)


def test_compose_is_lazy(article_pdfs):
    """ジェネレータなので、最初の1枚を取り出しただけでは全部を作らない。"""
    project = make_project(article_pdfs)
    events: list[int] = []
    iterator = composer.compose(project, on_progress=lambda done, _: events.append(done))
    next(iterator)
    assert events == [1]
    iterator.close()


def test_sync_page_counts_matches_real_pdf(article_pdfs):
    project = make_project(article_pdfs)
    project.articles[0].pages.clear()
    composer.sync_page_counts(project)
    assert [len(a.pages) for a in project.articles] == [2, 1, 3]


def test_page_specs_for_pads_missing_specs_without_mutating(article_pdfs):
    project = make_project(article_pdfs)
    article = project.articles[0]
    article.pages.clear()
    specs = composer.page_specs_for(article, 4, PageDefaults())
    assert len(specs) == 4
    assert article.pages == []


def test_page_specs_for_truncates_extra_specs(article_pdfs):
    project = make_project(article_pdfs)
    article = project.articles[2]
    specs = composer.page_specs_for(article, 1, PageDefaults())
    assert len(specs) == 1


def test_auto_trim_enlarges_content(tmp_path):
    """余白トリックを有効にすると、同じコマの本文がより大きく描かれる。"""
    from .conftest import make_pdf

    pdf = make_pdf(tmp_path / "wide-margin.pdf", page_count=1, margin_pt=140)

    trimmed_project = make_project([pdf], defaults=PageDefaults(auto_trim=True))
    plain_project = make_project([pdf], defaults=PageDefaults(auto_trim=False))

    trimmed = next(composer.compose(trimmed_project)).image.convert("L")
    plain = next(composer.compose(plain_project)).image.convert("L")

    # 黒い（＝文字の）画素が多いほど、本文が大きく描かれている。
    trimmed_ink = sum(1 for value in trimmed.getdata() if value < 128)
    plain_ink = sum(1 for value in plain.getdata() if value < 128)
    assert trimmed_ink > plain_ink


def test_overlap_widens_the_crop(single_page_pdf):
    """オーバーラップを増やすと、左上コマに隣の内容が入り込む。"""
    tight = make_project([single_page_pdf], defaults=PageDefaults(overlap=0.0))
    wide = make_project([single_page_pdf], defaults=PageDefaults(overlap=0.12))

    tight_pages = list(composer.compose(tight))
    wide_pages = list(composer.compose(wide))
    assert tight_pages[1].image.tobytes() != wide_pages[1].image.tobytes()


# ---- 回転 -------------------------------------------------------------


def ink_pixels(image) -> int:
    """黒い画素の数。多いほど本文が大きく描かれている。"""
    return sum(1 for value in image.convert("L").getdata() if value < 128)


def test_rotation_keeps_output_page_count(single_page_pdf):
    project = make_project([single_page_pdf])
    project.apply_layout_to_all(PageSpec("half_v", rotate=90))
    pages = list(composer.compose(project))
    assert len(pages) == 3  # 俯瞰1 + 上下2
    assert [p.part_index for p in pages] == [-1, 0, 1]


def test_rotated_output_still_matches_device_resolution(single_page_pdf):
    project = make_project([single_page_pdf])
    project.apply_layout_to_all(PageSpec("half_v", rotate=90))
    for page in composer.compose(project):
        assert page.image.size == DEVICE.size


def test_rotation_applies_to_the_overview_page_too(single_page_pdf):
    """1ページ分を読む間に端末を持ち替えずに済むよう、俯瞰も同じ向きに回す。"""
    upright = make_project([single_page_pdf])
    upright.apply_layout_to_all(PageSpec("half_v", rotate=0))
    rotated = make_project([single_page_pdf])
    rotated.apply_layout_to_all(PageSpec("half_v", rotate=90))

    upright_overview = next(composer.compose(upright))
    rotated_overview = next(composer.compose(rotated))
    assert upright_overview.is_overview and rotated_overview.is_overview
    assert upright_overview.image.tobytes() != rotated_overview.image.tobytes()


def test_clockwise_and_counterclockwise_produce_different_pages(single_page_pdf):
    clockwise = make_project([single_page_pdf])
    clockwise.apply_layout_to_all(PageSpec("half_v", rotate=90))
    counter = make_project([single_page_pdf])
    counter.apply_layout_to_all(PageSpec("half_v", rotate=270))

    cw_pages = list(composer.compose(clockwise))
    ccw_pages = list(composer.compose(counter))
    assert cw_pages[1].image.tobytes() != ccw_pages[1].image.tobytes()


def test_rotation_enlarges_text_for_landscape_crops(single_page_pdf):
    """上下2分割のような横長のコマは、回転すると本文が大きく描かれる。"""
    upright = make_project([single_page_pdf])
    upright.apply_layout_to_all(PageSpec("half_v", include_overview=False, rotate=0))
    rotated = make_project([single_page_pdf])
    rotated.apply_layout_to_all(PageSpec("half_v", include_overview=False, rotate=90))

    upright_ink = ink_pixels(next(composer.compose(upright)).image)
    rotated_ink = ink_pixels(next(composer.compose(rotated)).image)
    # 画面使用率 53% → 94%（文字は約1.33倍）を期待する。
    assert rotated_ink > upright_ink * 1.4


def test_rotation_shrinks_text_for_portrait_crops(single_page_pdf):
    """縦長のコマ（二段組4分割）では回転は不利になる。だから自動化せず人手で選ぶ。"""
    upright = make_project([single_page_pdf])
    upright.apply_layout_to_all(PageSpec("quad_2col", include_overview=False, rotate=0))
    rotated = make_project([single_page_pdf])
    rotated.apply_layout_to_all(PageSpec("quad_2col", include_overview=False, rotate=90))

    upright_ink = ink_pixels(next(composer.compose(upright)).image)
    rotated_ink = ink_pixels(next(composer.compose(rotated)).image)
    assert rotated_ink < upright_ink


def test_rotation_can_differ_per_page(sample_pdf):
    project = make_project([sample_pdf])
    project.articles[0].pages[0] = PageSpec("half_v", include_overview=False, rotate=0)
    project.articles[0].pages[1] = PageSpec("half_v", include_overview=False, rotate=90)
    pages = list(composer.compose(project))
    assert len(pages) == 4
    assert ink_pixels(pages[2].image) > ink_pixels(pages[0].image) * 1.4


def test_no_rotation_leaves_existing_output_unchanged(single_page_pdf):
    """回転機能の追加が、回転なしの出力に影響していないこと。"""
    explicit = make_project([single_page_pdf])
    explicit.apply_layout_to_all(PageSpec("quad_2col", include_overview=True, rotate=0))
    default = make_project([single_page_pdf])

    for left, right in zip(composer.compose(explicit), composer.compose(default)):
        assert left.image.tobytes() == right.image.tobytes()


# ---- 俯瞰と分割コマで別々の向き -----------------------------------------


def content_aspect(image) -> float:
    """描かれている領域（白い余白を除いた部分）の 幅/高さ。

    出力画像はどれも端末解像度ちょうどなので、寸法では向きを判定できない。
    余白を除いた中身の縦横比を見れば、回っているかどうかが分かる。
    """
    gray = image.convert("L")
    mask = gray.point(lambda value: 255 if value < 250 else 0)
    left, top, right, bottom = mask.getbbox()
    return (right - left) / (bottom - top)


@pytest.mark.parametrize(
    ("rotate", "rotate_overview", "overview_landscape", "part_landscape"),
    [
        # B5縦を上下2分割: 俯瞰は縦長、コマは横長。回すと向きが入れ替わる。
        (0, 0, False, True),  # どちらも回さない
        (0, 90, True, True),  # 俯瞰だけ回す
        (90, 0, False, False),  # 分割コマだけ回す
        (90, 90, True, False),  # どちらも回す
    ],
)
def test_overview_and_parts_rotate_independently(
    single_page_pdf, rotate, rotate_overview, overview_landscape, part_landscape
):
    project = make_project([single_page_pdf])
    project.apply_layout_to_all(
        PageSpec(
            "half_v", include_overview=True, rotate=rotate, rotate_overview=rotate_overview
        )
    )
    pages = list(composer.compose(project))

    assert pages[0].is_overview
    assert (content_aspect(pages[0].image) > 1.0) is overview_landscape
    assert (content_aspect(pages[1].image) > 1.0) is part_landscape


def test_default_overview_rotation_matches_explicit(single_page_pdf):
    """既定（分割と同じ）は、同じ角度を明示した場合と1バイトも変わらない。"""
    implicit = make_project([single_page_pdf])
    implicit.apply_layout_to_all(PageSpec("half_v", rotate=90))
    explicit = make_project([single_page_pdf])
    explicit.apply_layout_to_all(PageSpec("half_v", rotate=90, rotate_overview=90))

    for left, right in zip(composer.compose(implicit), composer.compose(explicit)):
        assert left.image.tobytes() == right.image.tobytes()


def test_overview_rotation_does_not_change_page_count(single_page_pdf):
    project = make_project([single_page_pdf])
    project.apply_layout_to_all(PageSpec("half_v", rotate=0, rotate_overview=90))
    assert len(list(composer.compose(project))) == 3


def test_differing_rotations_keep_both_outputs_sharp(single_page_pdf):
    """俯瞰と分割で向きが違っても、どちらも拡大されない解像度でレンダリングされる。

    それぞれ単独で最適化した場合と同等の描画量になることで確かめる。
    """
    mixed = make_project([single_page_pdf])
    mixed.apply_layout_to_all(
        PageSpec("half_v", include_overview=True, rotate=90, rotate_overview=0)
    )
    mixed_pages = list(composer.compose(mixed))

    overview_alone = make_project([single_page_pdf])
    overview_alone.apply_layout_to_all(PageSpec("full", rotate=0, rotate_overview=0))
    parts_alone = make_project([single_page_pdf])
    parts_alone.apply_layout_to_all(
        PageSpec("half_v", include_overview=False, rotate=90)
    )

    overview_reference = ink_pixels(next(composer.compose(overview_alone)).image)
    parts_reference = ink_pixels(next(composer.compose(parts_alone)).image)

    assert ink_pixels(mixed_pages[0].image) >= overview_reference * 0.95
    assert ink_pixels(mixed_pages[1].image) >= parts_reference * 0.95


def test_full_layout_uses_the_overview_rotation(single_page_pdf):
    """full は俯瞰1枚に畳まれるので、俯瞰側の設定に従う。"""
    project = make_project([single_page_pdf])
    project.apply_layout_to_all(PageSpec("full", rotate=0, rotate_overview=90))
    assert content_aspect(next(composer.compose(project)).image) > 1.0

    upright = make_project([single_page_pdf])
    upright.apply_layout_to_all(PageSpec("full", rotate=0))
    assert content_aspect(next(composer.compose(upright)).image) < 1.0


def test_overview_rotation_is_ignored_when_overview_is_off(single_page_pdf):
    """俯瞰を出さない設定なら、俯瞰の向きは出力に影響しない。"""
    without = make_project([single_page_pdf])
    without.apply_layout_to_all(
        PageSpec("half_v", include_overview=False, rotate=0, rotate_overview=90)
    )
    plain = make_project([single_page_pdf])
    plain.apply_layout_to_all(PageSpec("half_v", include_overview=False, rotate=0))

    for left, right in zip(composer.compose(without), composer.compose(plain)):
        assert left.image.tobytes() == right.image.tobytes()


def test_compose_reports_missing_pdf(tmp_path, single_page_pdf):
    project = make_project([single_page_pdf])
    project.articles[0].path = tmp_path / "gone.pdf"
    with pytest.raises(Exception, match="見つかりません"):
        list(composer.compose(project))


def test_preview_rects_returns_reading_order():
    rects = composer.preview_rects(PageSpec("quad_2col"), PageDefaults(overlap=0.0))
    assert rects == (
        (0.0, 0.0, 0.5, 0.5),
        (0.0, 0.5, 0.5, 1.0),
        (0.5, 0.0, 1.0, 0.5),
        (0.5, 0.5, 1.0, 1.0),
    )


def test_content_rect_for_respects_auto_trim(single_page_pdf):
    from inkflow.renderer import PreviewCache

    cache = PreviewCache()
    try:
        off = composer.content_rect_for(
            cache, single_page_pdf, 0, PageDefaults(auto_trim=False)
        )
        on = composer.content_rect_for(cache, single_page_pdf, 0, PageDefaults(auto_trim=True))
    finally:
        cache.close()
    assert off == (0.0, 0.0, 1.0, 1.0)
    assert on[0] > 0.0 and on[2] < 1.0


# ---- 分割線の自動検出・手動微調整 -----------------------------------------


def edge_ink_ratio(image, side: str, band_px: int = 6) -> float:
    """クロップの指定した縁ぎりぎりの帯にどれだけ文字（黒画素）が写り込んでいるか。

    分割線が本当にノド（空白）に来ていれば、そのコマの縁は白いはず。段の途中で
    切れていれば、縁のすぐそばに文字の断片が写り込む。
    """
    gray = image.convert("L")
    width, height = gray.size
    if side == "left":
        box = (0, 0, band_px, height)
    elif side == "right":
        box = (width - band_px, 0, width, height)
    else:
        raise ValueError(side)
    band = gray.crop(box)
    pixels = list(band.getdata())
    return sum(1 for value in pixels if value < 200) / len(pixels)


def _raw_part_crops(
    pdf_path: Path,
    layout_id: str,
    column_bias: float | None = None,
    row_bias: float | None = None,
    dpi: float = 200.0,
):
    """finalize_page（端末フィット・パディング）を経由しない、素のコマ画像列。

    パディングが縁を白く塗りつぶしてしまい、実際の分割位置がノドに来ているか
    どうかを画像の縁で判定できなくなるため、テストでは常にこちらを使う。
    """
    from inkflow import renderer

    with renderer.PdfDocument(pdf_path) as document:
        page_image = document.render(0, dpi)
    content_rect = imaging.find_content_bbox(page_image)
    content = imaging.crop_relative(page_image, content_rect)

    x_offsets, y_offsets = composer.resolve_divider_offsets(
        content, layout_id, column_bias, row_bias
    )
    rects = layouts.reading_rects(layout_id, 0.0, x_offsets, y_offsets)
    return [imaging.crop_relative(content, rect) for rect in rects]


def test_auto_gutter_detection_reduces_text_bleed_at_the_split(tmp_path):
    """真のノドが50%からズレた誌面で、自動検出が文字の巻き込みを減らす。

    ずれ幅は既定の検索窓（±12%）に収まる 0.08 とする（窓の外は検出できない仕様）。
    """
    from .conftest import make_asymmetric_pdf

    pdf = make_asymmetric_pdf(tmp_path / "asym.pdf", gutter_center_ratio=0.42)

    auto_crops = _raw_part_crops(pdf, "quad_2col")
    forced_crops = _raw_part_crops(pdf, "quad_2col", column_bias=0.0)

    # 右上コマ（part_index 2）の左端が、自動検出では文字を避けている。
    auto_bleed = edge_ink_ratio(auto_crops[2], "left")
    forced_bleed = edge_ink_ratio(forced_crops[2], "left")
    assert auto_bleed < forced_bleed


def test_manual_column_bias_overrides_auto_detection(tmp_path):
    """手動でバイアスを指定した軸は自動検出を行わず、指定位置をそのまま使う。"""
    from .conftest import make_asymmetric_pdf

    pdf = make_asymmetric_pdf(tmp_path / "asym.pdf", gutter_center_ratio=0.35)

    # 本来のノド付近（-0.15）を手動指定 → 文字を避けられる。
    good_crops = _raw_part_crops(pdf, "quad_2col", column_bias=-0.15)
    # わざと逆方向にずらす → 文字を巻き込む。
    bad_crops = _raw_part_crops(pdf, "quad_2col", column_bias=0.15)

    assert edge_ink_ratio(good_crops[2], "left") < edge_ink_ratio(bad_crops[2], "left")


def test_row_bias_shifts_the_horizontal_split(single_page_pdf):
    project = make_project([single_page_pdf])
    project.apply_layout_to_all(PageSpec("half_v", include_overview=False, row_bias=0.15))
    pages = list(composer.compose(project))

    baseline = make_project([single_page_pdf])
    baseline.apply_layout_to_all(PageSpec("half_v", include_overview=False))
    baseline_pages = list(composer.compose(baseline))

    assert pages[0].image.tobytes() != baseline_pages[0].image.tobytes()


def test_no_usable_whitespace_falls_back_to_nominal_position(tmp_path):
    """余白の無いページ（全面塗りつぶし）では、自動検出が働かず既定位置のまま。"""
    import pymupdf

    from .conftest import B5_HEIGHT_PT, B5_WIDTH_PT

    pdf_path = tmp_path / "solid.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=B5_WIDTH_PT, height=B5_HEIGHT_PT)
    page.draw_rect(page.rect, fill=(0, 0, 0), color=None)
    doc.save(str(pdf_path))
    doc.close()

    crops = _raw_part_crops(pdf_path, "quad_2col")

    # 既定（50%）どおりに切られていること＝どのコマも真っ黒（余白が写り込んでいない）。
    for crop in crops:
        assert edge_ink_ratio(crop, "left") == pytest.approx(1.0, abs=0.05)


def test_output_page_count_is_unaffected_by_bias(single_page_pdf):
    project = make_project([single_page_pdf])
    project.apply_layout_to_all(PageSpec("quad_2col", column_bias=0.05, row_bias=-0.05))
    assert len(list(composer.compose(project))) == 5


def test_projects_without_bias_fields_default_to_fixed_position(single_page_pdf):
    """バイアス未指定（既定値）は既定位置固定（0.0）であり、明示的に0.0を渡しても同じ。

    自動検出は誤検出が無視できない頻度で起きたため既定では無効。ページごとに
    ［自動］ボタン等で明示的に column_bias=None にしたときだけ自動検出が働く。
    """
    implicit = make_project([single_page_pdf])
    explicit = make_project([single_page_pdf])
    explicit.apply_layout_to_all(PageSpec("quad_2col", column_bias=0.0, row_bias=0.0))

    for left, right in zip(composer.compose(implicit), composer.compose(explicit)):
        assert left.image.tobytes() == right.image.tobytes()


def test_explicit_none_bias_enables_automatic_detection(tmp_path):
    """明示的に column_bias=None にしたページだけ、既定位置固定から自動検出へ切り替わる。"""
    from .conftest import make_asymmetric_pdf

    pdf = make_asymmetric_pdf(tmp_path / "asym.pdf", gutter_center_ratio=0.42)

    fixed = make_project([pdf])  # 既定のまま＝固定
    fixed.apply_layout_to_all(PageSpec("quad_2col", include_overview=False))
    fixed_pages = list(composer.compose(fixed))

    auto = make_project([pdf])
    auto.apply_layout_to_all(PageSpec("quad_2col", include_overview=False, column_bias=None))
    auto_pages = list(composer.compose(auto))

    assert fixed_pages[2].image.tobytes() != auto_pages[2].image.tobytes()


def test_resolve_divider_offsets_detects_the_true_gutter(tmp_path):
    """resolve_divider_offsets が、実際のレンダリング画像から正しいノド位置を導く。

    ずれ幅は既定の検索窓（±12%）に収まる範囲で検証する。
    """
    from inkflow import renderer

    from .conftest import make_asymmetric_pdf

    pdf = make_asymmetric_pdf(tmp_path / "asym.pdf", gutter_center_ratio=0.4)
    with renderer.PdfDocument(pdf) as document:
        page_image = document.render(0, 150)
        content_rect = imaging.find_content_bbox(page_image)
        content = imaging.crop_relative(page_image, content_rect)

    x_offsets, _ = composer.resolve_divider_offsets(content, "quad_2col", None, None)
    assert 0.5 in x_offsets
    assert 0.5 + x_offsets[0.5] == pytest.approx(0.4, abs=0.03)


def test_resolve_divider_offsets_full_layout_has_no_dividers(single_page_pdf):
    from inkflow import renderer

    with renderer.PdfDocument(single_page_pdf) as document:
        content = document.render(0, 100)
    x_offsets, y_offsets = composer.resolve_divider_offsets(content, "full", None, None)
    assert x_offsets == {}
    assert y_offsets == {}


def test_preview_rects_accepts_offsets():
    plain = composer.preview_rects(PageSpec("quad_2col"), PageDefaults(overlap=0.0))
    shifted = composer.preview_rects(
        PageSpec("quad_2col"), PageDefaults(overlap=0.0), x_offsets={0.5: 0.1}
    )
    assert shifted[0][2] == pytest.approx(0.6)
    assert shifted != plain
