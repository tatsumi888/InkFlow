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


# ---- 分割線の抽出とオフセット適用 ----------------------------------------


def test_internal_dividers_quad_2col():
    xs, ys = layouts.internal_dividers("quad_2col")
    assert xs == (0.5,)
    assert ys == (0.5,)


def test_internal_dividers_six_2col():
    xs, ys = layouts.internal_dividers("six_2col")
    assert xs == (0.5,)
    assert ys == pytest.approx((layouts._1_3, layouts._2_3))


def test_internal_dividers_full_layout_has_none():
    xs, ys = layouts.internal_dividers("full")
    assert xs == ()
    assert ys == ()


def test_internal_dividers_half_v_only_y():
    xs, ys = layouts.internal_dividers("half_v")
    assert xs == ()
    assert ys == (0.5,)


def test_internal_dividers_half_h_only_x():
    xs, ys = layouts.internal_dividers("half_h")
    assert xs == (0.5,)
    assert ys == ()


@pytest.mark.parametrize("layout", layouts.LAYOUTS, ids=lambda l: l.id)
def test_internal_dividers_are_strictly_inside_the_page(layout):
    xs, ys = layouts.internal_dividers(layout.id)
    for v in xs + ys:
        assert 0.0 < v < 1.0


def test_apply_divider_offsets_without_offsets_returns_original_rects():
    assert layouts.apply_divider_offsets("quad_2col") == layouts.get_layout("quad_2col").rects


def test_apply_divider_offsets_shifts_the_x_divider():
    rects = layouts.apply_divider_offsets("quad_2col", x_offsets={0.5: 0.05})
    xs = sorted({x0 for x0, _, _, _ in rects} | {x1 for _, _, x1, _ in rects})
    assert xs == pytest.approx([0.0, 0.55, 1.0])


def test_apply_divider_offsets_shifts_the_y_divider():
    rects = layouts.apply_divider_offsets("quad_2col", y_offsets={0.5: -0.08})
    ys = sorted({y0 for _, y0, _, _ in rects} | {y1 for _, _, _, y1 in rects})
    assert ys == pytest.approx([0.0, 0.42, 1.0])


def test_apply_divider_offsets_does_not_move_page_edges():
    rects = layouts.apply_divider_offsets("quad_2col", x_offsets={0.0: 0.9, 1.0: -0.9})
    xs = {x0 for x0, _, _, _ in rects} | {x1 for _, _, x1, _ in rects}
    assert xs == {0.0, 0.5, 1.0}


def test_apply_divider_offsets_clamps_within_page():
    rects = layouts.apply_divider_offsets("quad_2col", x_offsets={0.5: 5.0})
    assert all(0.0 <= x0 <= 1.0 and 0.0 <= x1 <= 1.0 for x0, _, x1, _ in rects)


@pytest.mark.parametrize("layout", layouts.LAYOUTS, ids=lambda l: l.id)
def test_apply_divider_offsets_preserves_total_area(layout):
    xs, ys = layouts.internal_dividers(layout.id)
    x_offsets = {x: 0.03 for x in xs}
    y_offsets = {y: -0.02 for y in ys}
    rects = layouts.apply_divider_offsets(layout.id, x_offsets, y_offsets)
    area = sum((x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in rects)
    assert area == pytest.approx(1.0)


def test_apply_divider_offsets_moves_dividers_shared_by_multiple_rects_together():
    """六分割の同じ分割線を参照する矩形は、揃って動く（隙間や重なりが出ない）。"""
    rects = layouts.apply_divider_offsets("six_2col", y_offsets={layouts._1_3: 0.05})
    # 左列3コマ・右列3コマとも、動かした境界を共有しているはず。
    boundaries_left = sorted(r[1] for r in rects if r[0] == 0.0) + [rects[2][3]]
    boundaries_right = sorted(r[1] for r in rects if r[0] == 0.5) + [rects[5][3]]
    assert boundaries_left == pytest.approx(boundaries_right)


def test_reading_rects_applies_offsets_before_overlap():
    plain = layouts.reading_rects("quad_2col", overlap=0.0)
    shifted = layouts.reading_rects("quad_2col", overlap=0.0, x_offsets={0.5: 0.1})
    assert shifted[0][2] == pytest.approx(0.6)  # 左上コマの右端が動いている
    assert shifted != plain


def test_reading_rects_offsets_and_overlap_compose():
    """オフセットとオーバーラップを両方指定しても、オフセット後の矩形が基準になる。"""
    shifted_only = layouts.reading_rects("quad_2col", overlap=0.0, y_offsets={0.5: 0.05})
    with_overlap = layouts.reading_rects("quad_2col", overlap=0.05, y_offsets={0.5: 0.05})
    # 左上コマ（インデックス0）の下端は、オーバーラップの分だけさらに広がる。
    assert with_overlap[0][3] > shifted_only[0][3]


def test_reading_rects_without_offsets_matches_default_behaviour():
    assert layouts.reading_rects("quad_2col", overlap=0.03) == layouts.reading_rects(
        "quad_2col", overlap=0.03, x_offsets=None, y_offsets=None
    )
