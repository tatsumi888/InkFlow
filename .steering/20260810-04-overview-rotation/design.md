# 設計書

## アーキテクチャ概要

既存構成は変えない。`PageSpec` に俯瞰用の回転を1つ足し、`composer` が俯瞰と分割コマで別々の角度を使うようにする。

```
PageSpec.rotate            分割コマの回転（既存）
PageSpec.rotate_overview   俯瞰の回転。None なら分割コマに従う（新規）
        └─→ effective_overview_rotation() -> int
```

## 「分割と同じ」の表し方

`rotate_overview: int | None = None` とし、**`None` を「分割コマと同じ」の意味に使う**。

別解として「4つ目の値（`ROTATION_SAME = -1` のような番兵）」も考えられるが、採らない。`None` なら「値が無い＝上位の設定に従う」という Python の自然な読み方に載るうえ、JSON では `null` として素直に往復でき、キーが無い旧プロジェクトの読み込み結果（既定 `None`）と一致するため。

```python
def effective_overview_rotation(self) -> int:
    return self.rotate if self.rotate_overview is None else self.rotate_overview
```

## コンポーネント設計

### 1. models.py

- `PageSpec.rotate_overview: int | None = None` を追加。JSONキーは `"rotate_overview"`。
- 復元時は `None` をそのまま通し、それ以外は `normalize_rotation()` にかける。扱えない値は `None`（＝分割と同じ）へ落とす。既存の「未知の値は既定へ」という方針に合わせる。
- `PageDefaults.rotate_overview: int | None = None` を追加し、`to_page_spec()` で引き継ぐ。
- `effective_overview_rotation()` と `overview_rotation_label()` を追加。ラベルは `None` のとき「分割と同じ」。

### 2. renderer.py

必要DPIの算出で、俯瞰と分割コマの**両方を満たす**解像度を求める必要がある。

現状の `required_dpi(..., rotated: bool)` は1つの向きしか受け取れない。ここで分岐を増やすのではなく、**呼び出し側（composer）で2回計算して大きい方を採る**。

理由: `required_dpi` は「ある1つのコマを画面に収めるのに必要な解像度」を求める純粋な関数であり、その責務は明快なまま保ちたい。「複数のコマの要求をまとめる」のは再ページ化の都合なので composer 側の関心事。

- 俯瞰の要求: `required_dpi(content_w, content_h, (1.0, 1.0), device, rotated=俯瞰の回転≠0)`
  俯瞰はページ全面なので `min_rel` は `(1.0, 1.0)`。
- 分割コマの要求: 既存どおり `min_relative_size(layout_id)` を使う。
- 採用値は両者の `max`。上限（600dpi）は `required_dpi` 側で既にクランプ済み。

俯瞰を出力しない設定のときは俯瞰側を計算しない。無駄に高い解像度でレンダリングしないため。

### 3. composer.py

`_compose_page()` を次のように変える。

```
1. 俯瞰の回転 = spec.effective_overview_rotation()
2. 分割コマの回転 = spec.rotate
3. dpi = max(俯瞰の要求, 分割コマの要求)   ← 出力する側だけを見る
4. ページを1回レンダリング（原則は維持）
5. 俯瞰: 回転(俯瞰の角度) → finalize_page
6. 各コマ: 回転(分割の角度) → finalize_page
```

`full` レイアウトは俯瞰1枚に畳まれるので、俯瞰側の角度と `min_rel=(1.0,1.0)` を使う。

### 4. gui/

- `main_window.py`: 右パネルの「縦横入替」を2段にする。
  - 1段目（既存）: 分割コマ — なし／右90°／左90°、`R` で巡回
  - 2段目（新規）: 俯瞰 — 分割と同じ／なし／右90°／左90°、`Shift+R` で巡回
- 俯瞰の行は、俯瞰を出力しないとき（チェックOFF、または `full` 以外で `include_overview=False`）は無効化する。効かない設定を触れる状態にしておくと誤解を招くため。
- `page_view.py`: バッジの文言を「分割コマと俯瞰で向きが違う」ことが分かる形にする。同じなら従来どおり1つ、違うなら両方を出す。
- ツリーのページ行にも、異なる場合だけ俯瞰の向きを追記する。行が長くなりすぎないよう、同じときは出さない。

### 5. cli.py

- `--rotate-overview {same,none,cw,ccw}` を追加。`same` → `None`。
- `_defaults_from_args()` と `_override_project()` の両方に反映する（`--rotate` と同じ扱い）。

## データフロー

### A4横の原稿を「俯瞰だけ回転」で出力する
```
1. レイアウト「左右2分割」を選ぶ
2. 分割コマの回転 = なし、俯瞰の回転 = 右90°
3. 必要DPI = max(
     俯瞰の要求（回転あり・全面）,
     分割コマの要求（回転なし・左右半分）
   )
4. ページを1回レンダリング
5. 俯瞰: 右90°に回して出力（横長の誌面が画面いっぱいに）
6. 左右のコマ: 回さずに出力（縦長なのでそのまま画面いっぱいに）
```

## エラーハンドリング戦略

新しい例外は追加しない。不正な回転値は既存方針どおり既定へ落とす。

## テスト戦略

### ユニットテスト
- `models`: `effective_overview_rotation()` の解決、`None` のラウンドトリップ、キーが無い旧プロジェクト、不正値の既定落ち、ラベル。
- `renderer`: 変更なし（既存の `required_dpi` をそのまま使う）。

### 統合テスト
- `composer`:
  - 俯瞰だけ回転 → 俯瞰が回り、分割コマは回らない
  - 分割だけ回転 → その逆
  - 既定（`None`）で、明示的に同じ角度を指定した場合と**出力が一致**する
  - 回転が異なる場合でも、**両方の出力が拡大されない**（本文の描画量が、それぞれ単独で最適化した場合と同等）
  - `full` レイアウトで俯瞰側の設定が使われる
  - 出力枚数が変わらない

### GUI テスト
- 4択の選択・`Shift+R` の巡回・ツリー表示・無効化・保持と複製・保存と読み込み。

### CLI テスト
- `--rotate-overview` の反映とプロジェクトファイルへの上書き。

## 依存ライブラリ

追加なし。

## 実装の順序

1. `models.py`（＋テスト）
2. `composer.py` の解像度計算と回転の適用（＋テスト）
3. `cli.py`（＋テスト）
4. GUI（＋テスト）
5. 実物に近い合成PDFでの確認とドキュメント更新

## 将来の拡張性

`rotate_overview` を `None` 許容にしたことで、「上位の設定に従う」という表現が型として使えるようになった。今後 `PageDefaults` に別の任意設定を足すときも同じ形にできる。
