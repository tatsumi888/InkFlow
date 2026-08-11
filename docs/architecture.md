# アーキテクチャ設計書

## 1. 全体構成

コア（純粋ロジック）と UI（PySide6 / CLI）を分離したレイヤ構成。分割・画像生成・EPUB書き出しは GUI に依存せず、CLI からもテストからも同一経路で呼べる。

```
┌──────────────────────────────────────────────────┐
│ UI 層                                             │
│   inkflow/gui/  (PySide6)        inkflow/cli.py   │
└────────────────────┬─────────────────────────────┘
                     │ Project (dataclass)
┌────────────────────▼─────────────────────────────┐
│ アプリケーション層                                  │
│   composer.py   Project → 出力ページ列（ジェネレータ）│
│   builder.py    composer + epub_writer の統合       │
└────────────────────┬─────────────────────────────┘
                     │
┌────────────────────▼─────────────────────────────┐
│ ドメイン / インフラ層                               │
│   models.py    Project / Article / PageSpec        │
│   layouts.py   分割レイアウト（純粋関数）             │  ← 外部ライブラリに依存しない
│   devices.py   端末プリセット                       │
│   renderer.py  PDF → PIL Image  (PyMuPDF)          │
│   imaging.py   トリム/整形/量子化/分割線検出 (Pillow) │
│   cover.py     表紙生成 (Pillow)                    │
│   epub_writer.py 固定レイアウトEPUB (zipfile)        │
│   errors.py    例外階層                             │
└──────────────────────────────────────────────────┘
```

依存の向きは常に上→下。`layouts.py` / `models.py` / `devices.py` は Pillow・PyMuPDF・Qt に依存しない純粋モジュールとし、単体テストを軽量に保つ。

**CLI と GUI が同じ出力になるのは `builder.build_epub()` を共有しているため。** ここを迂回する経路を新設してはならない。`tests/test_cli.py::test_cli_and_gui_paths_produce_identical_pages` が両者の一致を守っている。

## 2. データモデル

```
Project
 ├ title / issue            雑誌名・号（表紙とタイトルになる）
 ├ device_id                出力解像度のプリセットID
 ├ cover_image              任意指定の表紙画像（未指定なら自動生成）
 ├ defaults: PageDefaults   新規ページの既定値 ＋ 分割の共通パラメータ
 │   ├ layout_id / include_overview / rotate
 │   ├ column_bias / row_bias  分割線のオフセット一括設定。既定0.0（既定位置固定）。None なら自動検出
 │   ├ overlap              コマ間の重なり（矩形自身のサイズ比）
 │   └ auto_trim / trim_threshold
 ├ image: ImageOptions      format / jpeg_quality / gray_levels / gamma /
 │                          contrast_cutoff / sharpen
 └ articles: [Article]      並び順がそのまま本の順序
     ├ path                 PDF（1記事 = 1ファイル = しおり1項目）
     ├ title                しおり名
     └ pages: [PageSpec]    原稿ページごとの分割設定
         ├ layout_id
         ├ include_overview
         ├ rotate           分割コマの縦横入替（0 / 90=右 / 270=左、時計回り）
         ├ rotate_overview  俯瞰の縦横入替。None なら分割コマと同じ
         └ column_bias / row_bias  分割線のオフセット（±0.2）。既定0.0（既定位置固定）。None なら自動検出
```

永続化は JSON（`*.inkflow.json`）。PDFパスは**プロジェクトファイルからの相対パス**で保存し、読み込み時に絶対化する。プロジェクトごと別ディレクトリへ移しても壊れない。未知のキーは無視し、欠けたキーは既定値で補う。

## 3. 分割レイアウト

レイアウトは「相対矩形 `(x0, y0, x1, y1) ∈ [0,1]` の**読み順リスト**」として表す。リストの並びがそのまま Kindle 上でのページ送り順になる。

| ID | 矩形数 | 読み順 | オーバーラップ軸 |
|---|---|---|---|
| `full` | 1 | 全面 | なし |
| `quad_2col` | 4 | 左上 → 左下 → 右上 → 右下 | `y` のみ |
| `quad_1col` | 4 | 左上 → 右上 → 左下 → 右下 | `x`, `y` |
| `half_v` | 2 | 上 → 下 | `y` のみ |
| `half_h` | 2 | 左 → 右 | なし |
| `six_2col` | 6 | 左3段 → 右3段 | `y` のみ |
| `third_v` | 3 | 上 → 中 → 下 | `y` のみ |

**オーバーラップは「行を断つ向き」にだけ効かせる。** 2段組の段間方向へ広げても隣の段の文字が混ざって画面が無駄になるだけなので、`Layout.overlap_axes` で軸を限定している。新しいレイアウトを追加するときは必ず設定する。

「ページ全体（俯瞰）を含めるか」はレイアウトの一部ではなく `PageSpec.include_overview` が持つ。`full` のときは俯瞰と分割が同じ絵になるので1枚に畳む。

同じく「縦横入替」もレイアウトではなく `PageSpec.rotate` が持つ。横長のコマ（`half_v` / `third_v`）では回すと文字が1.33倍になるが、縦長のコマ（`quad_2col`）では0.75倍に悪化する。誌面依存なので自動判定はせず、ページ単位の人手選択とする。

分割線の位置は既定では固定（レイアウト定義どおり、オフセット無し）だが、ページ単位で自動検出や手動値に切り替えられる。`layouts.internal_dividers()` が rects から内部分割線（0/1を除く境界値）を逆算し、`composer.resolve_divider_offsets()` が `PageSpec.column_bias`/`row_bias` の値（既定 `0.0`）をそのまま適用する。`None`（GUIで明示的に自動を選んだ場合のみ）のときだけ本文の余白帯を自動検出してその位置へ寄せる（見つからなければ既定位置のまま）。自動検出は既定で無効: 版面によっては過大な補正をしてしまうため、オプトイン方式にしてある。詳細は `docs/functional-design.md` の「分割線の位置調整」を参照。

縦組み（右→左）は、矩形の並び順が違うレイアウトを追加し、spine の `page-progression-direction` を `rtl` に切り替えるだけで対応できる設計にしてある。

## 4. 再ページ化のパイプライン

原稿1ページあたり、次の順で処理する。

```
1. 下見レンダリング（72dpi）
2. 余白トリム位置の決定       imaging.find_content_bbox()
3. 必要DPIの算出              renderer.required_dpi()
4. 本レンダリング（1回だけ）    renderer.PdfDocument.render()
5. 本文領域でクロップ
6. 俯瞰ページを1枚（任意）
7. 分割線オフセットの決定       composer.resolve_divider_offsets()（自動検出 or 手動指定）
8. レイアウト矩形ごとにクロップ  layouts.reading_rects()
9. 縦横入替（指定時）           imaging.rotate_image()
10. 各コマを仕上げ              imaging.finalize_page()
```

**高解像度レンダリングは1ページにつき1回**。俯瞰も各コマも同じラスタからのクロップで賄うため、40ページ×5コマ＝200枚を作る場合でもレンダリングは40回で済む。

必要DPIを余白トリム**後**のサイズから決める必要があるので、72dpi の下見レンダリングを先に1回だけ挟む二段構えにしている。この順序を崩すと、トリム後に拡大が入って文字が滲む。

必要DPI = `min(端末幅 / コマ幅[inch], 端末高 / コマ高[inch])`、72〜600 でクランプ。B5の4分割なら約326dpi。

**`max` ではなく `min` を採る**のは、コマを縦横比を保ったまま画面に収める（contain）以上、実際に効くのは縦横どちらか一方の制約だけだから。`max` にすると使われない解像度まで刻むことになり、無駄なうえ縮小の再サンプリングでぼける。`min` なら収めたあとの倍率がちょうど 1.0 になり、リサイズ自体が起きない。

### 縦横入替（回転）

回転が 0 以外なら、**クロップ直後・`finalize_page()` の前**に `imaging.rotate_image()` を通す。あとから回すと白パディング込みで回ってしまい、端末解像度に収まらなくなる。

回転は 90°単位なので `Image.transpose()` を使い、再サンプリングを起こさない（無劣化・低コスト）。Pillow の `ROTATE_90` は反時計回りなので、時計回り90°には `ROTATE_270` を使う。

**俯瞰と分割コマは別々の角度を持つ**（`rotate_overview` が `None` なら分割コマに従う）。横長の原稿では望ましい向きが逆になるため。A4横を `half_h` で割った実測では、俯瞰だけ回すと俯瞰・分割コマとも画面使用率 91% になる（既定では俯瞰が51%、両方回すと分割コマが51%）。

向きが違うと必要なレンダリング解像度も別々になる。**1ページにつきレンダリングは1回**という原則を保つため、`composer._required_dpi_for_page()` が両方の要求を求めて大きい方を採る。出力しない側（俯瞰なしの設定など）は計算に入れない。

`required_dpi()` は「ある1つのコマを収めるのに必要な解像度」を求める純粋な関数のままにしてある。複数の要求をまとめるのは再ページ化の都合なので composer 側の関心事。

### 仕上げ（`imaging.finalize_page`）

```
グレースケール化 → contain リサイズ(Lanczos) → 自動コントラスト → ガンマ
 → アンシャープマスク → 白パディング → 16階調量子化
```

- リサイズ**後**にシャープをかけるのは、縮小でぼけた輪郭を戻すため。
- パディングを階調調整の**後**に行うのは、白い余白がヒストグラムを歪めてコントラスト補正を鈍らせないため。
- 縦横比は必ず維持する（引き伸ばさない）。余りは白で埋め、コマは中央に置く。
- 16階調の量子化はパレット画像への変換で行い、PNG を4bit深度で書かせる。

## 5. EPUB の構造

```
mimetype                    ← 先頭・無圧縮（EPUB の要件）
META-INF/container.xml
OEBPS/
  content.opf
  nav.xhtml                 ← EPUB3 の目次
  toc.ncx                   ← 互換の目次
  css/style.css
  images/cover.png, p0000.png, ...
  text/cover.xhtml, p0000.xhtml, ...
```

`content.opf` に付与するメタデータ:

| 種別 | 項目 |
|---|---|
| EPUB3標準 | `rendition:layout=pre-paginated` / `rendition:spread=none` / `rendition:orientation=portrait` |
| Kindle固有 | `fixed-layout=true` / `original-resolution=WxH` / `book-type=comic` / `zero-gutter` / `zero-margin` / `region-mag=false` / `primary-writing-mode=horizontal-lr` |

各ページ XHTML は `<meta name="viewport" content="width=W, height=H"/>` と、`width`/`height` を明示した `<img>` 1枚のみ。CSS で `margin:0; padding:0` を徹底する。

**目次を2種類とも書き出すのは、Send to Kindle の変換系によって見る先が異なるため。**

画像は既に圧縮済みなので ZIP には `ZIP_STORED` で入れる（再圧縮は無駄）。

## 6. 並行処理

EPUB出力は `QThread`（`gui/worker.py`）で実行し、進捗をシグナルで UI へ返す。ワーカーは `Project` の**ディープコピー**を持つので、生成中に UI 側で編集されても出力に影響しない。中断・失敗時は書きかけのEPUBを削除する。

GUI のプレビューは低DPI（110dpi）レンダリング＋LRUキャッシュ（既定8ページ）でページ送りを軽くしている。

## 7. エラーハンドリング

```
InkFlowError
 ├ PdfLoadError       PDFが開けない・破損・暗号化
 ├ ProjectFormatError プロジェクトJSONが不正・参照PDFが無い
 ├ RenderError        ラスタライズ失敗
 └ EpubWriteError     書き出し失敗
```

下位モジュールは PyMuPDF / Pillow / OS の例外を上記へ `raise ... from e` で変換する。UI 層が扱う例外型を限定するため。CLI は `InkFlowError` を捕捉して日本語メッセージを標準エラーへ出し、終了コード1で終わる（`--verbose` 指定時のみスタックトレース）。GUI は `QMessageBox` で提示し、アプリは落とさない。

エラーメッセージには**どの記事のどのページか**を必ず含める。40ページの中から問題箇所を特定できることが重要なため。

## 8. パフォーマンス設計

| 施策 | 効果 |
|---|---|
| 1ページ1回レンダリング | 200枚生成でもレンダリングは40回 |
| `composer.compose()` をジェネレータ化 | 生画像（1枚約2MB）を同時に保持しない |
| MuPDF 側で直接グレースケール出力 | RGB 経由よりメモリ 1/3 |
| 4bit PNG（16階調） | 1枚あたり約165KB、200枚で32MB |
| プレビューのLRUキャッシュ | ページ送りが即応 |

実測（B5・原稿40ページ・1236×1648）: 出力201ページ、32.2MB、44秒。

## 8-2. パッケージング

配布物の作り方は**アプリ本体の外側**（`packaging/`）に閉じる。`inkflow/` は PyInstaller の存在を知らない。唯一の例外がアイコンで、GUI のウィンドウアイコンとしても使うため `inkflow/appicon.py` に置く。

```
packaging/
  build.py        ビルドの入口（アイコン・バージョンリソース生成 → PyInstaller → 動作確認 → ZIP）
  entry.py        実行ファイルの入口（GUI/CLI の振り分け）
  inkflow.spec    PyInstaller の仕様
```

- **`Analysis` は1つ、`EXE` は2つ。** GUI（コンソールなし）と CLI（コンソールあり）は同じ `entry.py` から起動するので、解析もライブラリも共有できる。onedir では `COLLECT` が1フォルダにまとめる。
- **振り分けは実行ファイル名と第1引数で行う。** 「同名のパスが存在するか」で判定してはいけない（カレントの `build/` で GUI 起動に化ける）。
- **未使用の Qt DLL などを spec で除外**してサイズを 170MB → 124MB にしている。落としすぎは起動するまで分からないので、`build.py` の動作確認が `cli selftest`（PDF読み込み → 画像処理 → EPUB書き出し → Qt初期化 → アイコン生成）を実際に走らせて検証する。
- 実測（B5・原稿1ページ）: onedir 起動 0.46秒／フォルダ124MB・ZIP 55MB、onefile 起動 2.43秒／各51MB。onefile は起動のたびに展開するため既定は onedir。

`packaging/` に `__init__.py` は置かない。PyPI の `packaging`（PyInstaller の依存）と衝突するため。

## 9. 依存ライブラリ

```
PyMuPDF>=1.24    PDFラスタライズ
Pillow>=10.0     画像処理・表紙生成
PySide6>=6.6     GUI
pytest>=8.0      テスト
```

EPUB は仕様が単純な固定レイアウトしか扱わないため、`ebooklib` 等は導入せず `zipfile` で直接組み立てる。依存を減らし、Kindle固有メタデータを完全に制御するため。

## 10. 拡張ポイント

| やりたいこと | 触る場所 |
|---|---|
| 分割パターンの追加 | `layouts.LAYOUTS` に1エントリ（`overlap_axes` を忘れずに） |
| 回転の自動提案 | コマと端末の縦横比を比べて `PageSpec.rotate` を提案する層を上に足す。`composer` 以下は変更不要 |
| 対応端末の追加 | `devices.DEVICES` に1エントリ |
| 縦組み対応 | 読み順を入れ替えたレイアウト＋`page-progression-direction=rtl` |
| 出力形式の追加（PDF等） | `epub_writer` と同じ入力（画像列）を受ける writer を追加。`composer` の出力は形式非依存 |
| 段組の自動判定 | `composer` の入力は `PageSpec` に閉じているので、`PageSpec` を提案する層を上に差し込める |
