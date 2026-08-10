# 設計書

## アーキテクチャ概要

**コア（純粋ロジック）とUI（PySide6 / CLI）を分離したレイヤ構成**を採用する。分割・画像生成・EPUB書き出しはGUIに依存せず、CLIからもテストからも同一経路で呼べる。Clipper（PySide6 + Pillow）と同じ構えにし、GUIはヘッドレス（`QT_QPA_PLATFORM=offscreen`）でテストできるようにする。

```
┌───────────────────────────────────────────────┐
│ UI 層                                          │
│  inkflow/gui/  (PySide6)      inkflow/cli.py   │
└───────────────┬───────────────────────────────┘
                │ Project (dataclass)
┌───────────────▼───────────────────────────────┐
│ アプリケーション層                              │
│  composer.py   Project → 出力ページ列を生成      │
│  builder.py    composer + epub_writer の統合    │
└───────────────┬───────────────────────────────┘
                │
┌───────────────▼───────────────────────────────┐
│ ドメイン / インフラ層                           │
│  models.py    Project / Article / PageSpec     │
│  layouts.py   分割レイアウト定義（純粋関数）      │
│  devices.py   端末プリセット                    │
│  renderer.py  PDF → PIL Image  (PyMuPDF)       │
│  imaging.py   トリム/整形/量子化 (Pillow)        │
│  cover.py     表紙画像生成 (Pillow)             │
│  epub_writer.py 固定レイアウトEPUB (zipfile)     │
└───────────────────────────────────────────────┘
```

依存の向きは常に上→下。`layouts.py` / `models.py` は Pillow・PyMuPDF・Qt に依存しない純粋モジュールとし、単体テストを軽量に保つ。

## コンポーネント設計

### 1. layouts.py（分割レイアウト定義）

**責務**:
- 分割レイアウトを「相対矩形（x0,y0,x1,y1 ∈ [0,1]）の**読み順リスト**」として定義する。
- オーバーラップを加味した実効矩形を計算する。

**実装の要点**:
- レイアウトは `Layout(id, label, key, rects)` の不変データ。`rects` の並びがそのまま読み順になる。
- 既定は `quad_2col`（二段組4分割）= 左上 → 左下 → 右上 → 右下。原稿が2段組のとき、左段を上から下へ読み切ってから右段へ移るため。
- `quad_1col`（一段組4分割）= 左上 → 右上 → 左下 → 右下。段組がない誌面向け。
- 他に `full`（全体のみ）、`half_v`（上→下）、`half_h`（左→右）、`six_2col`（2段組6分割）、`third_v`（上→中→下）を用意する。
- オーバーラップは各矩形を `overlap`（**矩形自身のサイズに対する比率**、片側あたり）ぶん膨らませ、[0,1] にクリップして実現する。ページ端の矩形は外側に広がらない。
- **膨らませるのは「行を断つ向き」だけ**（`Layout.overlap_axes`）。2段組の段間方向へ広げても隣の段の文字が混ざって画面が無駄になるため、`quad_2col` などは縦方向にしか広げない。（実装中に出力を目視して判明したため、当初設計から変更）
- 「ページ全体を先頭に含めるか」はレイアウトの一部ではなく `PageSpec.include_overview` で持つ。`full` レイアウトのときは俯瞰と分割が同一なので、重複出力しないよう1枚に畳む。
- 縦組み（右→左）は将来 `rects` の並び順違いのレイアウトを追加するだけで対応できる。

### 2. models.py（プロジェクトモデル）

**責務**:
- `PageSpec` / `Article` / `Project` を保持し、JSON へのシリアライズ・デシリアライズを行う。

**実装の要点**:
- `PageSpec(layout_id, include_overview)` — ページ1枚ぶんの設定。
- `Article(path, title, pages: list[PageSpec])` — 記事1本 ＝ PDF 1ファイル ＝ しおり1項目。
- `Project(title, issue, device_id, defaults, image_options, articles, cover_image)`。
- PDFパスはプロジェクトファイルからの**相対パス**で保存し、読み込み時に絶対化する。プロジェクトごと別マシンへ移しても壊れないようにする。
- 未知のキーは無視し、欠けたキーは既定値で補う（前方・後方互換）。`version` フィールドを持つ。

### 3. devices.py（端末プリセット）

**責務**:
- 出力解像度のプリセットを提供する。

**実装の要点**:
- `paperwhite_11`(1236×1648, 既定) / `paperwhite_10`(1072×1448) / `kindle_11`(1072×1448) / `oasis`(1264×1680) / `scribe`(1860×2480) / `custom:WxH`。
- Paperwhite の実効表示領域は端末UIのぶんわずかに狭いが、原寸を採用しKindle側の等倍表示に委ねる。

### 4. renderer.py（PDF → 画像）

**責務**:
- PyMuPDF で PDF ページをラスタライズし、PIL Image を返す。
- 分割後のコマが端末解像度を下回らないよう、必要DPIを算出する。

**実装の要点**:
- 必要DPI = `device_width / (最小コマの相対幅 × ページ幅[inch])` を縦横で求め、大きい方を採用。上限600dpi・下限72dpiでクランプする。既定4分割・B5なら約345dpi。
- ページ単位で**1回だけ**高解像度レンダリングし、俯瞰・各コマはその画像からのクロップで賄う（再レンダリングしない）。
- `fitz.Matrix(zoom, zoom)` の zoom は `dpi/72`。
- PDFは「単純に画像として扱う」方針のため、テキスト層の有無を問わず同一経路。
- ページ回転（`/Rotate`）は PyMuPDF が適用済みの見た目で返すため、追加処理は不要。

### 5. imaging.py（画像整形）

**責務**:
- 白余白の自動トリム、クロップ、端末解像度への正規化、電子ペーパー向け階調調整。

**実装の要点**:
- パイプライン: `グレースケール化 → 自動トリム → クロップ → contain リサイズ(Lanczos) → 自動コントラスト → ガンマ → アンシャープマスク → 白パディング → 16階調量子化`。白パディングを階調調整の**後**に置くのは、白い余白がヒストグラムを歪めてコントラスト補正を鈍らせないため。
- 自動トリムは輝度しきい値（既定245）で二値化し `getbbox()` を取る。全面が白／全面が黒など bbox が異常なときは元の全面を返す（安全側）。トリム結果には数px のマージンを残す。
- 正規化は必ず**アスペクト比維持（contain）**。引き伸ばさない。余りは白（255）で埋め、コマは中央に配置する。
- コマが端末解像度より小さい場合も拡大して画面いっぱいに使う（読みやすさ優先）。
- 16階調量子化は 'L' から 16 色グレーパレットの 'P' へ変換し、PNG を 4bit 深度で保存する。テキスト主体の誌面では JPEG よりも小さく、かつリンギングが出ない。
- JPEG 出力もオプションで選べるようにする（写真主体号でサイズを詰めたい場合）。

### 6. composer.py（再ページ化）

**責務**:
- `Project` を走査し、出力ページ列（画像＋所属記事＋しおり位置）を生成する。

**実装の要点**:
- 出力は `ComposedPage(image, article_index, page_index, part_index, is_overview)` のイテレータ。全ページをメモリに溜めない**ジェネレータ**にして、200ページ規模でもメモリを圧迫しないようにする。
- 進捗コールバック `on_progress(done, total)` を受け取り、GUI のプログレスバーへ橋渡しする。
- 記事の先頭出力ページの通し番号を記録し、EPUB のしおり位置として返す。

### 7. cover.py（表紙生成）

**責務**:
- 雑誌名＋号から表紙画像を生成する。ユーザー指定画像があればそれを整形して使う。

**実装の要点**:
- Windows のシステムフォントを優先順で探索（`meiryo.ttc` → `YuGothM.ttc` → `msgothic.ttc` → `msmincho.ttc`）。見つからなければ Pillow の既定ビットマップフォントにフォールバックし、生成自体は必ず成功させる。
- 端末解像度ちょうど・グレースケールで生成し、本文ページと同じ正規化を通す。
- 長いタイトルは幅に収まるよう折り返し、フォントサイズを自動縮小する。

### 8. epub_writer.py（固定レイアウトEPUB）

**責務**:
- 画像列 ＋ しおり情報から、Kindle が固定レイアウトとして解釈するEPUB3を書き出す。

**実装の要点**:
- ZIP構造: `mimetype`（**先頭・無圧縮**）→ `META-INF/container.xml` → `OEBPS/{content.opf, nav.xhtml, toc.ncx, css/style.css, images/*, text/*.xhtml}`。
- `content.opf` に以下を付与する。
  - EPUB3標準: `rendition:layout=pre-paginated`, `rendition:spread=none`, `rendition:orientation=portrait`
  - Kindle固有: `fixed-layout=true`, `original-resolution=WxH`, `book-type=comic`, `zero-gutter=true`, `zero-margin=true`, `region-mag=false`, `primary-writing-mode=horizontal-lr`
  - `<meta name="cover" content="cover-img"/>` と、cover 画像アイテムへの `properties="cover-image"`
- spine は `page-progression-direction="ltr"`、各 itemref に `properties="rendition:layout-pre-paginated"`。
- 各XHTMLは `<meta name="viewport" content="width=W, height=H"/>` と、`width`/`height` 属性を明示した `<img>` 1枚のみ。CSSで `margin:0; padding:0` を徹底する。
- 目次は `nav.xhtml`（EPUB3）と `toc.ncx`（互換）の**両方**を出す。Send to Kindle の変換系によってどちらを見るかが異なるため。
- 画像は書き出し時にストリーミングで ZIP へ追加し、全画像を同時に保持しない。

### 9. gui/（PySide6）

**責務**:
- 記事の追加・並べ替え・タイトル編集、ページごとのレイアウト選択、プレビュー、出力。

**実装の要点**:
- `MainWindow` は3ペイン: 左=記事ツリー（記事→ページ）、中央=プレビュー、右=レイアウト選択と一括操作。
- `PageView` は QWidget を継承し、`paintEvent` でサムネイル画像の上に分割枠と読み順番号を描画する。半透明の塗り＋番号バッジで読み順を明示する。
- プレビューは低DPI（既定110dpi程度）でレンダリングし、`renderer` のキャッシュ（LRU）を介してページ送りを高速化する。
- ショートカット: `←/→` ページ移動、`1`〜`9` レイアウト選択、`Enter` 前ページと同じを適用して次へ、`O` 俯瞰ページのON/OFF。40ページを手早く流せることを最優先にする。
- 既定レイアウトは新規追加ページすべてに自動適用されるので、**例外ページだけ触る**運用になる。
- EPUB出力は `QThread` ワーカーで実行し、進捗をシグナルでUIへ返す。UIスレッドをブロックしない。

## データフロー

### 月刊誌1号ぶんをEPUB化する
```
1. GUIで記事PDFを追加（読む順に並べる）
2. Project.defaults のレイアウト（既定: quad_2col + 俯瞰あり）が全ページに適用される
3. ユーザーがページを送りながら例外ページのレイアウトだけ変更する
4. 雑誌名・号を入力 → 表紙プレビュー
5. 「EPUB出力」→ ワーカースレッドで builder.build_epub() を実行
   5-1. composer が各PDFページを必要DPIでレンダリング
   5-2. 自動トリム → レイアウト矩形でクロップ（オーバーラップ込み）
   5-3. 端末解像度へ正規化 → 階調調整 → 16階調量子化
   5-4. epub_writer が画像を順次ZIPへ追加、記事境界をしおりに記録
6. EPUBファイルを Send to Kindle（メール or USB）で端末へ
```

### CLIバッチ
```
1. python -m inkflow.cli build project.inkflow.json -o out.epub
   （または python -m inkflow.cli build ./articles -o out.epub --title "雑誌名" --issue "2026年8月号"）
2. builder.build_epub() を同一経路で実行し、標準出力に進捗を表示
```

## エラーハンドリング戦略

### カスタムエラークラス

`inkflow/errors.py` に以下を定義する。

- `InkFlowError` — 基底クラス。
- `PdfLoadError` — PDFが開けない／破損／暗号化されている。
- `ProjectFormatError` — プロジェクトJSONの構造が不正、参照PDFが見つからない。
- `RenderError` — ページのラスタライズに失敗した。
- `EpubWriteError` — 出力先に書き込めない、ディスク不足など。

### エラーハンドリングパターン

- 下位モジュールは PyMuPDF / Pillow / OS の例外を捕捉し、上記のカスタムエラーへ**原因を保ったまま**（`raise ... from e`）変換する。UI 層が扱う例外型を限定するため。
- CLI は `InkFlowError` を捕捉して日本語メッセージを標準エラーへ出し、終了コード1で終わる。スタックトレースは `--verbose` 指定時のみ表示する。
- GUI は `QMessageBox` でユーザーに提示し、アプリは落とさない。ワーカースレッド内の例外はシグナルでUIスレッドへ運ぶ。
- 1記事のレンダリングに失敗しても、**どの記事のどのページか**を必ずメッセージに含める。40ページの中から問題箇所を特定できることが重要。

## テスト戦略

### ユニットテスト
- `layouts.py`: 各レイアウトの矩形数・読み順・オーバーラップ適用後の座標とクリップ。
- `models.py`: JSONラウンドトリップ、相対パス解決、欠損キーの既定値補完、不正JSONで `ProjectFormatError`。
- `imaging.py`: 白余白トリックのbbox、contain リサイズで縦横比が保たれること、出力寸法が端末解像度ちょうど、16階調以下であること。
- `devices.py`: プリセットの解像度。
- `cover.py`: 表紙画像の寸法とモード。フォント不在時にフォールバックすること。
- `renderer.py`: 必要DPIの計算、レンダリング結果の寸法。

### 統合テスト
- 合成PDF（PyMuPDF で生成した2段組テキストページ）から EPUB を生成し、
  - ZIPとして開けて `mimetype` が先頭・無圧縮
  - spine 数 = 表紙1 + 総コマ数
  - `nav.xhtml` / `toc.ncx` のしおり数 = 記事数、リンク先が各記事の先頭ページ
  - `content.opf` に固定レイアウトのメタデータが揃っている
  - 画像がすべて端末解像度ちょうど
- GUI: `QT_QPA_PLATFORM=offscreen` で MainWindow を生成し、PDF追加 → レイアウト変更 → 「前ページと同じ」→ プロジェクト保存/読込 のラウンドトリップを検証する。

## 依存ライブラリ

```
PyMuPDF>=1.24    # PDFラスタライズ
Pillow>=10.0     # 画像処理・表紙生成
PySide6>=6.6     # GUI
pytest>=8.0      # テスト
```

EPUBは仕様が単純な固定レイアウトのみを扱うため、`ebooklib` 等は導入せず `zipfile` で直接組み立てる。依存を減らし、Kindle固有メタデータを完全に制御するため。

## ディレクトリ構造

```
InkFlow/
  .steering/20260810-01-kindle-repaginate-epub/
  docs/
    product-requirements.md
    architecture.md
    development-guidelines.md
  inkflow/
    __init__.py
    __main__.py          # python -m inkflow → GUI起動
    errors.py
    devices.py
    layouts.py
    models.py
    renderer.py
    imaging.py
    cover.py
    composer.py
    epub_writer.py
    builder.py
    cli.py
    gui/
      __init__.py
      app.py
      main_window.py
      page_view.py
      worker.py
  tests/
    conftest.py
    test_layouts.py
    test_models.py
    test_devices.py
    test_imaging.py
    test_renderer.py
    test_cover.py
    test_composer.py
    test_epub_writer.py
    test_builder.py
    test_gui.py
  requirements.txt
  pytest.ini
  run.bat
  README.md
  CLAUDE.md
```

## 実装の順序

1. プロジェクト基盤（venv・requirements・pytest設定・パッケージ雛形・errors）
2. 純粋ロジック（devices → layouts → models）とそのテスト
3. 画像パイプライン（renderer → imaging → cover）とそのテスト
4. 再ページ化と出力（composer → epub_writer → builder）とそのテスト
5. CLI
6. GUI（page_view → main_window → worker）とヘッドレステスト
7. ドキュメント（README / CLAUDE.md / docs 一式）

## セキュリティ考慮事項

- 完全ローカル処理。ネットワーク通信・外部送信は一切行わない。
- プロジェクトJSONは信頼できる入力とみなすが、`eval` 等は使わず `json` のみでパースする。
- パスワード保護PDFは復号を試みず、`PdfLoadError` として明示的に拒否する。
- 出力先パスはユーザー選択のみ。プロジェクトファイル内のパスは、読み込み時にプロジェクトディレクトリ基準で解決し、書き出しは常にユーザー指定先へ行う。

## パフォーマンス考慮事項

- 1ページあたりのレンダリングは1回のみ。俯瞰・各コマは同一ラスタからのクロップで賄う。40ページ×5コマ＝200枚の生成でも、レンダリング回数は40回に留まる。
- 出力画像はジェネレータで逐次ZIPへ流し込み、200枚を同時にメモリ保持しない（1枚あたり約2MBの生データ、200枚で400MB相当を回避する）。
- GUIプレビューは低DPIレンダリング＋LRUキャッシュ（既定8ページ）でページ送りを軽くする。
- 16階調4bit PNG により、テキスト主体ページで1枚100〜300KB程度に収める。200枚で20〜60MB、目標の50MB以内が現実的な範囲に入る。JPEG指定でさらに縮小できる。

## 将来の拡張性

- **縦組み対応**: `layouts.py` に読み順を入れ替えたレイアウトを追加し、`page-progression-direction` を `rtl` に切り替えるだけで対応できる設計にする。
- **自動レイアウト判定**: 現状は人手選択だが、`composer` の入力が `PageSpec` に閉じているため、後から「テキストブロック解析で `PageSpec` を提案する」層を差し込める。
- **出力形式の追加**: `epub_writer` と同じインターフェースで「端末サイズにクロップしたPDF」ライターを追加できる。`composer` の出力（画像列）は形式非依存。
- **他端末プロファイル**: `devices.py` にエントリを足すだけで対応できる。
