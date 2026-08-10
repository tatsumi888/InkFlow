# InkFlow

B5〜A4サイズの雑誌記事PDFを、**Kindle Paperwhite でパン操作なしに読める固定レイアウトEPUB**へ再ページ化するWindowsデスクトップアプリ。

原稿1ページを「ページ全体（俯瞰）＋分割コマ」の複数ページに展開し、月刊誌1号分をまとめた1冊として出力する。記事ごとにしおりが付く。

## 何を解決するか

雑誌PDFをそのまま Kindle に送ると、次のどちらかになる。

- **ページ全体表示** — B5〜A4の版面が6インチ級の画面に収まるので、本文が小さすぎて読めない。
- **拡大表示** — 読めるサイズにすると1画面に収まらず、パン（スクロール）が必要になる。電子ペーパーは再描画が遅くタッチ追従も悪いので、パン主体の操作は実用に耐えない。

InkFlow は**拡大とパンを、あらかじめ「ページ送り」に変換しておく**。版面を読み順に切り分け、各コマを端末の画面いっぱいに割り付けたEPUBを事前生成するので、端末上ではページを送るだけで読み進められる。

画像として扱うためレイアウトは100%保持される（テキスト抽出＋リフローのような崩れが起きない）。

## 必要なもの

- Windows 11 / Python 3.12
- 依存: PyMuPDF, Pillow, PySide6

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 使い方（GUI）

```powershell
.\run.bat                                   # 通常起動（コンソールなし）
.venv\Scripts\python.exe -m inkflow         # コンソール付きで起動
```

起動引数にプロジェクトファイル・PDFフォルダ・PDF（複数可）を渡せる。エクスプローラからのD&D起動にも対応。

### 画面

| ペイン | 役割 |
|---|---|
| 左 | 記事の一覧。この順で1冊になる。追加・削除・並べ替え・しおり名の変更 |
| 中央 | ページのプレビュー。分割枠と**読み順の番号**、余白トリム位置（緑の破線）を重ねて表示 |
| 右 | このページの分割レイアウト、俯瞰ページの有無、まとめて適用、EPUB出力 |

### 操作の流れ

1. 月が変わったら［ファイル］→［新規プロジェクト…］（`Ctrl+N`）で前号のプロジェクトから作り直す。雑誌名・号・端末を入力すると白紙のプロジェクトになる
2. 記事PDFをドラッグ＆ドロップで追加し、読む順に並べる
3. 既定レイアウト（二段組4分割＋俯瞰）が全ページに入っているので、**例外ページだけ**直す
4. ［EPUBを出力］
5. できたEPUBを Send to Kindle（メール添付 or USB）で端末へ

40ページ分でも、既定のままなら操作ゼロ。全面写真のページを「全体のみ」にする程度の手当てで済む。

「新規プロジェクト」は未保存の変更があれば確認してから白紙に戻す。設定ダイアログをキャンセルすれば、いま開いているプロジェクトは変更されない。

### キー操作

| キー | 動作 |
|---|---|
| `←` / `Backspace` | 前のページ |
| `→` / `Space` | 次のページ |
| `1`〜`7` | 分割レイアウトを選ぶ |
| `Enter` | 前ページと同じ設定にして次へ |
| `O` | ページ全体（俯瞰）の有無を切り替え |
| `R` | 分割コマの縦横入替（なし → 右90° → 左90°） |
| `Shift+R` | 俯瞰ページの縦横入替（分割と同じ → なし → 右90° → 左90°） |
| `Ctrl+N` / `Ctrl+O` / `Ctrl+S` / `Ctrl+E` | 新規プロジェクト / PDF追加 / 保存 / EPUB出力 |
| `F1` | キー操作の一覧 |

## 使い方（CLI）

```powershell
# フォルダ内のPDFをまとめて1冊に
.venv\Scripts\python.exe -m inkflow.cli build .\2026-08 -o "月刊誌 2026年8月号.epub" --title "月刊誌" --issue "2026年8月号"

# 先にプロジェクトを作り、GUIで調整してから出力
.venv\Scripts\python.exe -m inkflow.cli init .\2026-08 --title "月刊誌" --issue "2026年8月号"
.venv\Scripts\python.exe -m inkflow.cli build .\2026-08\2026-08.inkflow.json

# 一覧
.venv\Scripts\python.exe -m inkflow.cli layouts
.venv\Scripts\python.exe -m inkflow.cli devices
```

主なオプション: `--layout` `--no-overview` `--rotate` `--rotate-overview` `--overlap` `--no-trim` `--device` `--format` `--gray-levels` `--gamma` `--cover`

CLI と GUI は同じ `builder.build_epub()` を通るので、出力は完全に一致する。

## 分割レイアウト

読み順は矩形の並び順そのもの。

| ID | 分割 | 読み順 | 向いている誌面 |
|---|---|---|---|
| `full` | なし | — | 全面写真・図版 |
| `quad_2col` | 4（既定） | 左上 → 左下 → 右上 → 右下 | 2段組の本文 |
| `quad_1col` | 4 | 左上 → 右上 → 左下 → 右下 | 段組なしの本文 |
| `half_v` | 2 | 上 → 下 | 行が横いっぱいに伸びる誌面 |
| `half_h` | 2 | 左 → 右 | 2段組で1段が1画面に収まる |
| `six_2col` | 6 | 左3段 → 右3段 | 文字が小さい2段組 |
| `third_v` | 3 | 上 → 中 → 下 | 横長の図表が続くページ |

「ページ全体（俯瞰）」を有効にすると、分割コマの前にページ全体が1枚入る。既定レイアウトなら **1ページ → 5ページ**（全体＋4分割）。

### オーバーラップ

分割線上にかかった行が読めなくなるのを防ぐため、隣のコマと少し重ねる（既定3%）。ただし**行を断つ向きにだけ**効かせる。2段組の段間方向へ広げても隣の段の文字が混ざって画面が無駄になるだけなので、`quad_2col` などでは縦方向にしか広げない。

### 縦横入替（回転）

横長のコマは、縦長の画面にそのまま収めると上下が大きく余って文字が小さくなる。90°回して**端末を横向きに持てば画面をほぼ使い切れる**。ページ単位で「なし／右90°／左90°」を選べる（GUIは `R` キー、CLIは `--rotate cw|ccw`）。

B5・1236×1648 での効果:

| レイアウト | コマの縦横比 | 回転なし | 回転あり | 文字サイズ |
|---|---|---|---|---|
| `half_v`（上下2分割） | 1.42（横長） | 画面の53% | 画面の94% | **1.33倍** |
| `third_v`（上中下3分割） | 2.13（横長） | 画面の35% | 画面の94% | **1.33倍** |
| `quad_2col`（二段組4分割） | 0.71（縦長） | 画面の94% | 画面の71% | 0.75倍（悪化） |

**縦長のコマでは逆効果**なので、自動判定はせずページごとに選ぶ。

#### 俯瞰ページの向きは別に指定できる

既定では俯瞰ページも分割コマと同じ向きになる。1ページ分を読む間に端末を持ち替えずに済むため。

ただし**横長の原稿では俯瞰と分割コマで望ましい向きが逆になる**。A4横を `half_h`（左右2分割）で割った実測値:

| 設定 | 俯瞰の画面使用率 | 分割コマの画面使用率 |
|---|---|---|
| 既定（どちらも回さない） | 51% | 91% |
| **俯瞰だけ右90°** | **91%** | **91%** |
| どちらも右90° | 91% | 51% |

このため俯瞰の向きは「分割と同じ／なし／右90°／左90°」から別に選べる（GUIは `Shift+R`、CLIは `--rotate-overview same|none|cw|ccw`）。既定は「分割と同じ」。

## 出力されるEPUB

- EPUB3 の固定レイアウト（`rendition:layout=pre-paginated`）。1画像＝1ページ
- Kindle 向けメタデータ（`fixed-layout` / `original-resolution` / `book-type=comic` / `zero-margin` など）を付与
- 目次は `nav.xhtml`（EPUB3）と `toc.ncx`（互換）の**両方**。Send to Kindle の変換系によって見る先が違うため
- 画像は端末解像度ちょうど・グレースケール16階調・4bit PNG

### ファイルサイズの目安

B5・原稿40ページ（出力201ページ）・1236×1648 での実測値。

| 設定 | サイズ |
|---|---|
| 既定（PNG 16階調） | 32 MB |
| 8階調 | 31 MB |
| **4階調** | **17 MB** |
| 俯瞰ページなし | 24 MB |
| 旧Paperwhite解像度 (1072×1448) | 21 MB |
| JPEG (q85) | 106 MB |

Send to Kindle のメール添付は50MBまで。超えるときは**階調数を4に下げる**のが最も効く（文字主体ならほぼ見た目は変わらない）。**JPEGは逆効果**で、文字の輪郭が多い誌面では3倍以上に膨らむ。

生成時間は原稿1ページあたり約1.1秒（40ページで45秒程度）。

## 配布用の実行ファイルを作る

Python が入っていない Windows PC でも動く形に固められる。

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt   # 初回のみ
.venv\Scripts\python.exe packaging\build.py                       # 1フォルダ（既定）
.venv\Scripts\python.exe packaging\build.py --onefile             # 1ファイル
```

生成物は `dist/` に出る。GUI用（コンソールなし）と CLI用（コンソールあり）の2つを作る。

| 形式 | 生成物 | サイズ | 起動時間 |
|---|---|---|---|
| **onedir（既定）** | `dist/InkFlow/` ＋ 配布用ZIP | フォルダ 124MB / ZIP **55MB** | **0.46 秒** |
| onefile | `dist/InkFlow.exe`, `dist/InkFlow-cli.exe` | 各 51MB | 2.43 秒 |

onefile は起動のたびに一時ディレクトリへ全体を展開するため**5倍以上遅い**。コピーの手軽さより起動の速さを取って、既定は onedir にしている。

ビルドの最後に生成物を実際に起動し、`selftest`（PDF読み込み → 画像処理 → EPUB書き出し → Qt初期化）が通ることを確認する。パッケージングで最も起きやすい「隠れた依存の取りこぼし」は、起動してみるまで分からないため。

### バージョン情報の確認

同じ `1.0.0` のまま何度もビルドし直すことがあるため、バージョン番号だけでは「いま動いているのはどのビルドか」を区別できない。GUIは［ヘルプ］→［バージョン情報…］、CLIは `--version`（`selftest` の見出しにも表示）で、以下を確認できる。

- ソースの短縮コミットハッシュ（未コミットの変更があればその旨も表示）
- ビルド日時（パッケージ版のみ。ソース実行時は「ソース実行（パッケージ版ではない）」）

パッケージ版はビルド時点の情報を埋め込む（`.git` は同梱されないため）。ソースから実行した場合は、その場でgitに問い合わせて**現在**の状態を表示する。

### GitHub Actions でビルドする

バージョンタグ（`v1.0.0` など）を push すると、`.github/workflows/build.yml` が Windows ランナー上でテスト → onedir → onefile の順にビルドし、**GitHub Release に配布用ZIPと実行ファイル2本を添付する**。手動実行（Actions タブから `workflow_dispatch`）もでき、そちらはアーティファクトとして取得できる（Release は作らない）。

```powershell
# inkflow/__init__.py の __version__ を更新してから
git tag v1.0.0
git push origin v1.0.0
```

タグのバージョンと `inkflow.__version__` が一致しないとビルドが失敗する（Release名とZIPのファイル名が食い違うのを防ぐため）。

### 配布したあと

- ZIP を展開したフォルダをそのままコピーすれば動く。インストール不要。
- **GUI は `InkFlow.exe`、CLI は `InkFlow-cli.exe`。** CLI 版は必ずサブコマンド付きで呼ぶ（引数なしだと使い方が出る）。
- 配布先で正しく動くかは `InkFlow-cli.exe selftest` で確認できる。
- 署名していないため、初回起動時に Windows SmartScreen が警告を出す。「詳細情報」→「実行」で起動できる。

## 開発

```powershell
.venv\Scripts\python.exe -m pytest -q                                   # 全テスト
.venv\Scripts\python.exe -m pytest tests/test_composer.py -q            # 単一ファイル
.venv\Scripts\python.exe -m pytest -k "overlap" -q                      # 名前で絞る
```

GUIテストは `tests/conftest.py` が `QT_QPA_PLATFORM=offscreen` を設定するのでヘッドレスで走る。テスト用のPDFは PyMuPDF で合成しているため、実物の雑誌PDFは不要。

詳細は [CLAUDE.md](CLAUDE.md) と以下のドキュメントを参照。

- [docs/product-requirements.md](docs/product-requirements.md) — プロダクト要求定義書
- [docs/functional-design.md](docs/functional-design.md) — 機能設計書（画面遷移・データ構造・アルゴリズム）
- [docs/architecture.md](docs/architecture.md) — アーキテクチャ設計書（レイヤ構成・依存関係）
- [docs/repository-structure.md](docs/repository-structure.md) — リポジトリ構造定義書
- [docs/development-guidelines.md](docs/development-guidelines.md) — 開発ガイドライン（検証コマンドの正典）
- [docs/glossary.md](docs/glossary.md) — 用語集

## スコープ外

- テキスト抽出によるリフロー型EPUB（雑誌ではレイアウトが崩れるため採用しない）
- OCR、段組の自動検出（レイアウトは人手で選ぶ）
- 縦組み（右→左）専用の読み順プリセット
- MOBI/AZW3 出力、端末への自動転送
