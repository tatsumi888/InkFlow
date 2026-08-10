import pytest

from inkflow import layouts
from inkflow.errors import InkFlowError


def test_default_layout_is_two_column_quad():
    layout = layouts.default_layout()
    assert layout.id == "quad_2col"
    assert layout.part_count == 4


def test_quad_2col_reading_order_is_left_top_left_bottom_right_top_right_bottom():
    rects = layouts.get_layout("quad_2col").rects
    assert rects == (
        (0.0, 0.0, 0.5, 0.5),  # 左上
        (0.0, 0.5, 0.5, 1.0),  # 左下
        (0.5, 0.0, 1.0, 0.5),  # 右上
        (0.5, 0.5, 1.0, 1.0),  # 右下
    )


def test_quad_1col_reading_order_is_row_major():
    rects = layouts.get_layout("quad_1col").rects
    assert rects == (
        (0.0, 0.0, 0.5, 0.5),  # 左上
        (0.5, 0.0, 1.0, 0.5),  # 右上
        (0.0, 0.5, 0.5, 1.0),  # 左下
        (0.5, 0.5, 1.0, 1.0),  # 右下
    )


def test_full_layout_has_single_whole_page_rect():
    layout = layouts.get_layout("full")
    assert layout.rects == ((0.0, 0.0, 1.0, 1.0),)
    assert layout.part_count == 1


@pytest.mark.parametrize("layout", layouts.LAYOUTS, ids=lambda l: l.id)
def test_rects_cover_the_page_without_gaps(layout):
    """各レイアウトの矩形は、重なりなくページ全面を覆う。"""
    area = sum((x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in layout.rects)
    assert area == pytest.approx(1.0)
    for x0, y0, x1, y1 in layout.rects:
        assert 0.0 <= x0 < x1 <= 1.0
        assert 0.0 <= y0 < y1 <= 1.0


def test_expand_rect_grows_on_all_sides():
    expanded = layouts.expand_rect((0.25, 0.25, 0.75, 0.75), 0.1)
    assert expanded == pytest.approx((0.2, 0.2, 0.8, 0.8))


def test_expand_rect_clips_at_page_edges():
    expanded = layouts.expand_rect((0.0, 0.0, 0.5, 0.5), 0.1)
    # 外側（左・上）へは広がらず、内側（右・下）だけ広がる。
    assert expanded == pytest.approx((0.0, 0.0, 0.55, 0.55))


def test_expand_rect_noop_when_overlap_is_zero():
    rect = (0.0, 0.5, 0.5, 1.0)
    assert layouts.expand_rect(rect, 0.0) == rect


def test_expand_rect_respects_axes():
    rect = (0.25, 0.25, 0.75, 0.75)
    assert layouts.expand_rect(rect, 0.1, axes=("y",)) == pytest.approx((0.25, 0.2, 0.75, 0.8))
    assert layouts.expand_rect(rect, 0.1, axes=("x",)) == pytest.approx((0.2, 0.25, 0.8, 0.75))
    assert layouts.expand_rect(rect, 0.1, axes=()) == rect


def test_reading_rects_applies_overlap():
    plain = layouts.reading_rects("quad_2col", overlap=0.0)
    wide = layouts.reading_rects("quad_2col", overlap=0.1)
    # 左上コマは下方向に広がる（行を断つのは横の切れ目だけ）。
    assert wide[0][3] > plain[0][3]


def test_two_column_layout_does_not_bleed_across_the_gutter():
    """2段組では、段間の向きに広げない（隣の段の文字が混ざらない）。"""
    plain = layouts.reading_rects("quad_2col", overlap=0.0)
    wide = layouts.reading_rects("quad_2col", overlap=0.12)
    for tight_rect, wide_rect in zip(plain, wide):
        assert wide_rect[0] == pytest.approx(tight_rect[0])
        assert wide_rect[2] == pytest.approx(tight_rect[2])


def test_single_column_layout_overlaps_in_both_directions():
    """1段組は行が左右に伸びるので、縦の切れ目でも広げる。"""
    plain = layouts.reading_rects("quad_1col", overlap=0.0)
    wide = layouts.reading_rects("quad_1col", overlap=0.1)
    assert wide[0][2] > plain[0][2]
    assert wide[0][3] > plain[0][3]


def test_column_only_layouts_ignore_overlap():
    """段まるごとを切り出すレイアウトは、広げる必要がない。"""
    assert layouts.reading_rects("half_h", overlap=0.12) == layouts.get_layout("half_h").rects


def test_reading_rects_overlap_is_monotonic():
    small = layouts.reading_rects("quad_2col", overlap=0.02)
    large = layouts.reading_rects("quad_2col", overlap=0.08)
    for small_rect, large_rect in zip(small, large):
        small_area = (small_rect[2] - small_rect[0]) * (small_rect[3] - small_rect[1])
        large_area = (large_rect[2] - large_rect[0]) * (large_rect[3] - large_rect[1])
        assert large_area > small_area


def test_overlap_axes_are_valid():
    for layout in layouts.LAYOUTS:
        assert set(layout.overlap_axes) <= {"x", "y"}


def test_full_layout_ignores_overlap():
    assert layouts.reading_rects("full", overlap=0.1) == ((0.0, 0.0, 1.0, 1.0),)


def test_clamp_overlap():
    assert layouts.clamp_overlap(-1.0) == 0.0
    assert layouts.clamp_overlap(0.05) == pytest.approx(0.05)
    assert layouts.clamp_overlap(99.0) == layouts.MAX_OVERLAP


def test_min_relative_size():
    assert layouts.min_relative_size("quad_2col") == pytest.approx((0.5, 0.5))
    assert layouts.min_relative_size("full") == pytest.approx((1.0, 1.0))
    assert layouts.min_relative_size("six_2col") == pytest.approx((0.5, 1 / 3))


def test_get_layout_unknown_id():
    with pytest.raises(InkFlowError, match="未知のレイアウトID"):
        layouts.get_layout("nope")


def test_layout_ids_are_unique():
    ids = layouts.layout_ids()
    assert len(ids) == len(set(ids)) == len(layouts.LAYOUTS)
