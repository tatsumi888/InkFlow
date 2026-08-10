# 設計書

## アーキテクチャ概要

既存の3層（純粋ロジック / インフラ / アプリ層）にそのまま追加する。新モジュールは作らない。

```
imaging.find_divider_offset()      余白帯の探索（純粋な画像処理。Pillowのみ）
        ↓
layouts.internal_dividers()        レイアウトの内部分割線位置を rects から逆算
layouts.apply_divider_offsets()    分割線位置をずらした rects を作る
        ↓
composer.resolve_divider_offsets() 自動検出＋手動バイアスを統合し、
                                    「実際に使う分割線位置」を1つに決める
        ↓
composer._compose_page()           reading_rects() に反映してクロップ
gui/main_window.py                 プレビューでも同じ resolve_divider_offsets() を使う
```

## なぜ「分割線の内部位置」を rects から逆算するか

`Layout.rects` は「読み順の矩形リスト」として既に定義されている（`quad_2col` なら4つの矩形）。分割線の位置を別途ハードコードして二重管理にすると、レイアウト定義を変えたときに同期が崩れる。矩形の境界値（0.0 と 1.0 を除く）を集合として取り出せば、追加の定義なしに「このレイアウトにはどの位置に分割線があるか」が求まる。

```python
def internal_dividers(layout_id: str) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """(x方向の分割線位置の一覧, y方向の分割線位置の一覧)。ページ端(0.0/1.0)は含まない。"""
    layout = get_layout(layout_id)
    xs = sorted({round(v, 6) for x0, _, x1, _ in layout.rects for v in (x0, x1)
                 if 1e-6 < v < 1 - 1e-6})
    ys = sorted({round(v, 6) for _, y0, _, y1 in layout.rects for v in (y0, y1)
                 if 1e-6 < v < 1 - 1e-6})
    return (tuple(xs), tuple(ys))
```

`quad_2col` なら `xs=(0.5,)`, `ys=(0.5,)`。`six_2col` なら `xs=(0.5,)`, `ys=(1/3, 2/3)`。`full` なら両方空。

## 余白帯の探索（`imaging.find_divider_offset`）

**方針**: Pillowの `Image.resize()` を1×高さ（または幅×1）に BOX フィルタで縮小すると、各列（または各行）の平均輝度が1回の呼び出しで求まる。ピクセルごとに Python ループを回すより桁違いに速く、numpy 等の新規依存も不要。既存の `find_content_bbox()`（外側の余白を見つける）と対になる、内側の余白（ノド）を見つける処理として `imaging.py` に置く。

```python
def find_divider_offset(
    image: Image.Image,
    axis: str,               # "x"（縦の分割線） or "y"（横の分割線）
    nominal: float,           # 既定位置（0..1）
    search_ratio: float = 0.12,
    min_band_ratio: float = 0.01,
    whiteness_threshold: int = 250,
) -> float | None:
    """nominal近傍で最も余白の多い帯を探し、nominalからの相対オフセットを返す。
    見つからなければ None（呼び出し側は既定位置のまま使う）。
    """
```

**アルゴリズム**:
1. `axis="x"` なら `image.convert("L").resize((width, 1), Image.Resampling.BOX)` で列ごとの平均輝度プロファイルを得る（`axis="y"` は `(1, height)`）。
2. `nominal ± search_ratio` の範囲だけを見る。既定位置から離れた場所を「ノド」と誤認しないための安全策。
3. その範囲内で `whiteness_threshold` 以上（ほぼ白）が連続する最長区間を探す。
4. 区間の幅が `min_band_ratio × size` 未満なら「余白帯なし」として `None`（写真や図でページが埋まっている場合の安全弁）。
5. 見つかった区間の中央位置を新しい分割線位置とし、`nominal` からの差分を返す。

**探索窓を絞る理由**: ページ全体から最大の余白を探すと、本文と無関係な場所（ページ上下の完全な余白など）を誤って選びかねない。「元々ここに分割線を引くつもりだった」という位置の近傍だけを見ることで、既存の意図（レイアウト選択）を尊重しながら微修正するにとどめる。

## レイアウトへの適用（`layouts.py`）

```python
def apply_divider_offsets(
    layout_id: str,
    x_offsets: dict[float, float],
    y_offsets: dict[float, float],
) -> tuple[Rect, ...]:
    """検出/指定したオフセットで分割線をずらした矩形列を返す（読み順は変えない）。"""
```

`reading_rects()` に `x_offsets` / `y_offsets`（既定 `None`）を追加し、指定があれば `apply_divider_offsets()` を経由してからオーバーラップ（`expand_rect`）を適用する。**適用順序は「分割線をずらす→オーバーラップを広げる」。** 逆にするとオーバーラップの基準矩形がズレる。

## 自動検出と手動指定の統合（`composer.py`）

新しいデータクラス `PageSpec.column_bias: float | None = None` / `PageSpec.row_bias: float | None = None` を追加する。`None` は「自動検出に任せる」を意味する（`rotate_overview` の `None`=「分割コマと同じ」と同じ考え方）。

```python
def resolve_divider_offsets(
    content_image: Image.Image,
    layout_id: str,
    column_bias: float | None,
    row_bias: float | None,
) -> tuple[dict[float, float], dict[float, float]]:
    """このページで実際に使う分割線オフセットを決める。

    軸ごとに、手動指定（column_bias/row_bias）があればそれを全ての分割線に
    一律適用し、無ければ分割線ごとに自動検出する（見つからなければそのまま
    ＝オフセット0）。
    """
    xs, ys = layouts.internal_dividers(layout_id)
    x_offsets = (
        {x: column_bias for x in xs} if column_bias is not None
        else {x: off for x in xs if (off := imaging.find_divider_offset(content_image, "x", x)) is not None}
    )
    y_offsets = (
        {y: row_bias for y in ys} if row_bias is not None
        else {y: off for y in ys if (off := imaging.find_divider_offset(content_image, "y", y)) is not None}
    )
    return (x_offsets, y_offsets)
```

`_compose_page()` は、本文領域（`content`）を切り出した直後にこれを呼び、結果を `layouts.reading_rects(layout_id, overlap, x_offsets, y_offsets)` に渡す。

**GUIのプレビューも同じ `resolve_divider_offsets()` を呼ぶ。** ここを共有することで、プレビューに表示される枠と実際の出力が一致することを保証する（CLI/GUIの出力を一致させている既存方針と同じ考え方）。

## 手動微調整のUI

- 既存の「縦横入替」パネルの下に「分割位置の微調整」を追加する。
- 「左右のノド位置」「上下の分割位置」それぞれに `[－] [自動] [＋]` の3ボタン。クリックで `column_bias`/`row_bias` を ±1%（0.01）ずつ動かす。「自動」を押すと `None` に戻す（自動検出へ戻す）。
- 現在値（自動検出結果 or 手動値）をラベルで表示する（例: 「自動（-2.3%）」「手動 +4.0%」）。
- プレビュー（`page_view.py`）は、`resolve_divider_offsets()` を通した実際の矩形で分割枠を描く。ズレの大きいページでは枠が視覚的に動くので、微調整の効果がその場で分かる。

## エラーハンドリング戦略

新しい例外は追加しない。`find_divider_offset()` は失敗（見つからない）を `None` で表現し、例外を投げない。診断的な補正機能であり、失敗しても出力自体は既定位置で成立するため。

## テスト戦略

### ユニットテスト（`imaging.find_divider_offset`）
- 意図的に余白帯を作った合成画像で、正しい位置を検出する（縦・横両方）。
- 余白帯が探索窓の外にある場合、検出しない（`None`）。
- 余白が全く無い（全面に文字/画像がある）場合、`None`。
- 見つかった帯が細すぎる場合、`None`。
- 探索窓の境界での挙動（既定位置ちょうどに余白がある場合）。

### ユニットテスト（`layouts.internal_dividers` / `apply_divider_offsets`）
- 各レイアウトで期待される分割線位置が取れる。
- オフセット適用後も矩形の面積合計が1.0のまま（重なり・隙間が生じない）ことを確認。
- オフセットを与えなければ元の `rects` と一致する。

### 統合テスト（`composer`）
- **実際に確認したい性質は「本文の途中で切れない」こと**なので、合成PDFで意図的に非対称な2段組（左列が狭い・右列が広い、実際のノドが50%からズレている）を作り、
  - 自動検出ありの出力では、分割線付近の黒画素（文字）が自動検出なしより減っている（＝文字を避けている）ことを確認する。
  - 手動バイアスを指定すると、その位置が使われることを確認する。
  - 手動バイアスを指定した軸では自動検出が働かない（意図的に悪いバイアスを与えて、それがそのまま反映されることを確認）。
- 全面画像・余白の無いページでは、オフセットが適用されず出力が変わらないことを確認する。
- 出力枚数が変わらないことを確認する。
- 新フィールドを持たない旧プロジェクト（`column_bias`/`row_bias` 無し）を読み込んでも出力が変わらないことを確認する。

### 実サンプルでの確認（自動テストには含めない）
- `sample/IPSJ-MGN6708Whole.pdf` の107・108ページを実際に処理し、分割線が文字を避けていることを目視で確認する。プロジェクトの既存方針（実物PDFはテストに持ち込まない）に従い、確認はスクラッチスクリプトで行い、自動テストへは組み込まない。

## 依存ライブラリ

追加なし（Pillowの `resize` を使う）。

## パフォーマンス考慮事項

- BOXフィルタでの1行/1列への縮小はPillowのC実装で行われるため、ページサイズによらず高速（既存のトリム処理と同程度のコスト）。
- 探索はレイアウトごとに高々数本の分割線（多くて3本）のみで、ページごとに数回のプロファイル計算で済む。40ページ規模でも体感できる遅延は生じない見込み。

## 将来の拡張性

- 分割線ごとに独立した手動値を持たせたい場合、`column_bias`/`row_bias` を「軸ごとの単一値」から「分割線位置をキーにした辞書」へ拡張できる（`resolve_divider_offsets` のインターフェースは既にこの形に近い）。
- 探索アルゴリズム自体を差し替えたい場合（例: 最大余白ではなく中央に最も近い余白を優先する等）も `find_divider_offset` の内部だけ変更すればよい。
