"""分割レイアウトの定義。

各レイアウトは「相対矩形 (x0, y0, x1, y1) ∈ [0,1] の**読み順リスト**」として表す。
リストの並びがそのまま Kindle 上でのページ送り順になる。

このモジュールは Pillow / PyMuPDF / Qt に依存しない純粋ロジックとして保つ。
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import InkFlowError

# 相対矩形 (x0, y0, x1, y1)。原点は左上。
Rect = tuple[float, float, float, float]

_1_3 = 1.0 / 3.0
_2_3 = 2.0 / 3.0


@dataclass(frozen=True)
class Layout:
    """1ページをどう切り分けるかの定義。"""

    id: str
    label: str
    hint: str
    rects: tuple[Rect, ...]
    overlap_axes: tuple[str, ...] = ("x", "y")

    @property
    def part_count(self) -> int:
        return len(self.rects)


# オーバーラップは「行を断ち切る向き」にだけ効かせる。2段組の段間（ノド）方向へ
# 広げても隣の段の文字が混ざるだけで、画面が無駄になるため。
LAYOUTS: tuple[Layout, ...] = (
    Layout(
        id="full",
        label="全体のみ（分割なし）",
        hint="全面写真や図版のページ向け。出力は1枚。",
        rects=((0.0, 0.0, 1.0, 1.0),),
        overlap_axes=(),
    ),
    Layout(
        id="quad_2col",
        label="二段組4分割（左上→左下→右上→右下）",
        hint="2段組の本文ページ向け。左段を上から下に読み切ってから右段へ移る。",
        rects=(
            (0.0, 0.0, 0.5, 0.5),
            (0.0, 0.5, 0.5, 1.0),
            (0.5, 0.0, 1.0, 0.5),
            (0.5, 0.5, 1.0, 1.0),
        ),
        # 縦の切れ目は段間なので広げない。横の切れ目は行を断つので広げる。
        overlap_axes=("y",),
    ),
    Layout(
        id="quad_1col",
        label="一段組4分割（左上→右上→左下→右下）",
        hint="段組のない横書きページ向け。行が左右いっぱいに伸びる誌面。",
        rects=(
            (0.0, 0.0, 0.5, 0.5),
            (0.5, 0.0, 1.0, 0.5),
            (0.0, 0.5, 0.5, 1.0),
            (0.5, 0.5, 1.0, 1.0),
        ),
        # 行が左右に伸びるので、縦の切れ目も行の途中を断つ。
        overlap_axes=("x", "y"),
    ),
    Layout(
        id="half_v",
        label="上下2分割（上→下）",
        hint="行が横いっぱいに伸びる誌面で、4分割では細かすぎる場合。",
        rects=(
            (0.0, 0.0, 1.0, 0.5),
            (0.0, 0.5, 1.0, 1.0),
        ),
        overlap_axes=("y",),
    ),
    Layout(
        id="half_h",
        label="左右2分割（左→右）",
        hint="2段組で、1段まるごとが1画面に収まる場合。",
        rects=(
            (0.0, 0.0, 0.5, 1.0),
            (0.5, 0.0, 1.0, 1.0),
        ),
        # 段まるごとを切り出すので、どちらの向きにも広げる必要がない。
        overlap_axes=(),
    ),
    Layout(
        id="six_2col",
        label="二段組6分割（左3→右3）",
        hint="文字が小さい2段組。4分割でも読みにくいページ向け。",
        rects=(
            (0.0, 0.0, 0.5, _1_3),
            (0.0, _1_3, 0.5, _2_3),
            (0.0, _2_3, 0.5, 1.0),
            (0.5, 0.0, 1.0, _1_3),
            (0.5, _1_3, 1.0, _2_3),
            (0.5, _2_3, 1.0, 1.0),
        ),
        overlap_axes=("y",),
    ),
    Layout(
        id="third_v",
        label="上中下3分割（上→中→下）",
        hint="横長の図表が続くページ向け。",
        rects=(
            (0.0, 0.0, 1.0, _1_3),
            (0.0, _1_3, 1.0, _2_3),
            (0.0, _2_3, 1.0, 1.0),
        ),
        overlap_axes=("y",),
    ),
)

DEFAULT_LAYOUT_ID = "quad_2col"

# オーバーラップの既定値。矩形自身のサイズに対する比率（片側あたり）。
DEFAULT_OVERLAP = 0.03
MAX_OVERLAP = 0.15

_BY_ID = {layout.id: layout for layout in LAYOUTS}


def get_layout(layout_id: str) -> Layout:
    try:
        return _BY_ID[layout_id]
    except KeyError as e:
        known = ", ".join(_BY_ID)
        raise InkFlowError(f"未知のレイアウトIDです: {layout_id!r}（利用可能: {known}）") from e


def layout_ids() -> tuple[str, ...]:
    return tuple(_BY_ID)


def default_layout() -> Layout:
    return _BY_ID[DEFAULT_LAYOUT_ID]


def expand_rect(rect: Rect, overlap: float, axes: tuple[str, ...] = ("x", "y")) -> Rect:
    """矩形を膨らませる。

    ``overlap`` は矩形自身の幅・高さに対する比率（片側あたり）。``axes`` で指定した
    向きにだけ広げ、ページ端を越えないよう [0,1] にクリップする（端の矩形は外側に
    広がらない）。分割線上にかかった行が、隣のコマ側で必ず読めるようにするための
    処理なので、行を断たない向き（2段組の段間など）には広げない。
    """
    if overlap <= 0.0 or not axes:
        return rect

    x0, y0, x1, y1 = rect
    dx = (x1 - x0) * overlap if "x" in axes else 0.0
    dy = (y1 - y0) * overlap if "y" in axes else 0.0
    return (
        max(0.0, x0 - dx),
        max(0.0, y0 - dy),
        min(1.0, x1 + dx),
        min(1.0, y1 + dy),
    )


def internal_dividers(layout_id: str) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """レイアウト内部の分割線位置を (x方向の一覧, y方向の一覧) で返す。

    追加の定義を持たず、``Layout.rects`` の境界値から逆算する。レイアウト定義を
    変えたときに分割線位置の一覧が二重管理でズレることがないようにするため。
    ページ端（0.0 / 1.0）は分割線ではないので含めない。
    """
    layout = get_layout(layout_id)
    xs = sorted(
        {round(v, 6) for x0, _, x1, _ in layout.rects for v in (x0, x1) if 1e-6 < v < 1 - 1e-6}
    )
    ys = sorted(
        {round(v, 6) for _, y0, _, y1 in layout.rects for v in (y0, y1) if 1e-6 < v < 1 - 1e-6}
    )
    return (tuple(xs), tuple(ys))


def apply_divider_offsets(
    layout_id: str,
    x_offsets: dict[float, float] | None = None,
    y_offsets: dict[float, float] | None = None,
) -> tuple[Rect, ...]:
    """検出/指定したオフセットで分割線をずらした矩形列を返す（読み順は変えない）。

    ページ端（0.0 / 1.0）は動かさない。オフセットが無い分割線はそのまま。
    """
    layout = get_layout(layout_id)
    if not x_offsets and not y_offsets:
        return layout.rects

    def shift(value: float, offsets: dict[float, float] | None) -> float:
        if not offsets or value <= 1e-6 or value >= 1 - 1e-6:
            return value
        return min(1.0, max(0.0, value + offsets.get(round(value, 6), 0.0)))

    return tuple(
        (shift(x0, x_offsets), shift(y0, y_offsets), shift(x1, x_offsets), shift(y1, y_offsets))
        for x0, y0, x1, y1 in layout.rects
    )


def reading_rects(
    layout_id: str,
    overlap: float = DEFAULT_OVERLAP,
    x_offsets: dict[float, float] | None = None,
    y_offsets: dict[float, float] | None = None,
) -> tuple[Rect, ...]:
    """レイアウトの矩形を読み順で返す（分割線オフセット→オーバーラップの順に適用）。

    オフセットを先に適用してからオーバーラップを広げる。逆にすると、オーバーラップの
    基準となる矩形そのものがズレてしまう。
    """
    layout = get_layout(layout_id)
    overlap = clamp_overlap(overlap)
    base_rects = apply_divider_offsets(layout_id, x_offsets, y_offsets)
    return tuple(expand_rect(r, overlap, layout.overlap_axes) for r in base_rects)


def clamp_overlap(overlap: float) -> float:
    return min(MAX_OVERLAP, max(0.0, float(overlap)))


def min_relative_size(layout_id: str) -> tuple[float, float]:
    """レイアウト中で最も小さいコマの相対幅・相対高さを返す。

    レンダリング解像度を決めるために使う。オーバーラップは解像度を上げる方向に
    しか働かないので、ここでは適用しない（安全側）。
    """
    layout = get_layout(layout_id)
    min_w = min(x1 - x0 for x0, _, x1, _ in layout.rects)
    min_h = min(y1 - y0 for _, y0, _, y1 in layout.rects)
    return (min_w, min_h)
