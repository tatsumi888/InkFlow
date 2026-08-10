# リポジトリ構造定義書 (Repository Structure Document)

Python単一パッケージのデスクトップアプリであり、TypeScript系の一般的なレイヤ分割（`src/services/` `src/repositories/` 等）とは構成が異なる。ここでは実際のディレクトリ構成をそのまま定義する。

## プロジェクト構造

```
InkFlow/
├── inkflow/                # アプリ本体（唯一のPythonパッケージ）
│   ├── gui/                # PySide6 UI層
│   ├── errors.py           # 例外階層
│   ├── devices.py          # 純粋ロジック: 端末プリセット
│   ├── layouts.py          # 純粋ロジック: 分割レイアウト定義
│   ├── models.py           # 純粋ロジック: Project/Article/PageSpec
│   ├── renderer.py         # インフラ: PDF→画像 (PyMuPDF)
│   ├── imaging.py          # インフラ: 画像整形 (Pillow)
│   ├── cover.py            # インフラ: 表紙生成 (Pillow)
│   ├── appicon.py          # インフラ: アプリアイコン生成 (Pillow)
│   ├── composer.py         # アプリ層: 再ページ化
│   ├── epub_writer.py      # インフラ: 固定レイアウトEPUB出力 (zipfile)
│   ├── builder.py          # アプリ層: composer+epub_writerの統合。CLI/GUI共通の唯一の入口
│   └── cli.py               # UI層: コマンドライン
├── packaging/               # 配布物ビルド（アプリ本体から独立）
│   ├── entry.py             # PyInstallerの実行入口（GUI/CLI振り分け）
│   ├── inkflow.spec         # PyInstaller仕様
│   └── build.py             # ビルドの入口スクリプト
├── tests/                   # テストコード（単一階層、対象モジュールと1:1対応）
├── docs/                    # 永続ドキュメント（本書を含む）
├── .steering/                # 作業単位のステアリング記録（gitで追跡する）
├── .github/workflows/        # GitHub Actions（配布物ビルド）
├── requirements.txt          # 実行時依存
├── requirements-dev.txt      # ビルド時依存（PyInstaller）
├── pytest.ini
├── run.bat                   # GUIをコンソールなしで起動
├── README.md
└── CLAUDE.md
```

## ディレクトリ詳細

### `inkflow/`（アプリ本体）

**役割**: InkFlowの全機能。GUI・CLI・ドメインロジック・インフラをすべて含む単一パッケージ。

**内部のレイヤ分割**（ディレクトリではなく依存関係で表現される。詳細は `docs/architecture.md` §1）:

| 区分 | ファイル | 外部依存 |
|---|---|---|
| 純粋ロジック | `models.py` `layouts.py` `devices.py` | なし（Pillow/PyMuPDF/Qt非依存） |
| インフラ | `renderer.py` `imaging.py` `cover.py` `appicon.py` `epub_writer.py` | PyMuPDF / Pillow / zipfile |
| アプリ層 | `composer.py` `builder.py` | 上記すべて |
| UI層 | `cli.py` `gui/` | `builder.py` のみ |

**命名規則**:
- モジュール名は snake_case、責務1つにつき1ファイル（例: 画像処理は `imaging.py` に集約し、GUI用と CLI用で分けない）
- クラス名は PascalCase（`PageSpec`, `Project`, `MainWindow`）、関数・変数は snake_case（Python標準）

**依存関係**:
- 依存可能: 下位レイヤ（UI → アプリ層 → インフラ → 純粋ロジック）
- 依存禁止: 純粋ロジックからインフラ・UIへの依存、インフラ間の相互依存（例: `cover.py` が `epub_writer.py` を呼ぶことはない）
- `packaging/` から `inkflow/` への依存は許可（PyInstallerがパッケージを解析するため）。逆方向（`inkflow/` から `packaging/` へ）は禁止。パッケージング方式を変えてもアプリ本体に影響しないようにするため

### `inkflow/gui/`（PySide6 UI層）

**役割**: デスクトップGUI。`inkflow/` 内の唯一のサブパッケージ。

**配置ファイル**:
- `app.py`: `QApplication` の起動、起動引数の解釈、ウィンドウアイコン設定
- `main_window.py`: メインウィンドウ全体（記事ツリー・プレビュー・操作パネル・メニュー・EPUB出力）
- `page_view.py`: プレビュー描画（分割枠・読み順番号・回転バッジのオーバーレイ）
- `settings_dialog.py`: 「本の設定」ダイアログ（雑誌名・号・端末・画像品質）
- `worker.py`: EPUB出力を担う `QThread` ワーカー

**既知の逸脱**: `main_window.py` は約960行あり、本書のファイルサイズ目安（500行以上で分割推奨）を超えている。メインウィンドウが記事操作・ページ操作・レイアウト操作・保存/読込・EPUB出力のすべてを受け持つ設計上、自然に肥大化している。分割する場合は「記事ツリー操作」「ページ/レイアウト操作」「ファイル操作」を個別の `QObject`（コントローラ的な役割）に切り出す案が考えられるが、現時点では実施していない（動作に支障がなく、テストで担保されているため優先度は低い）。

**依存関係**:
- 依存可能: `inkflow.builder` `inkflow.composer` `inkflow.layouts` `inkflow.renderer` `inkflow.models` `inkflow.appicon` `inkflow.errors`
- 依存禁止: `inkflow.epub_writer` を直接呼ばない（`builder` 経由に統一し、CLIと出力を分岐させないため）

### `packaging/`（配布物ビルド）

**役割**: PyInstallerで単独実行可能な `.exe` を作る。アプリ本体から独立しており、`inkflow/` はこのディレクトリの存在を知らない。

**配置ファイル**:
- `entry.py`: 実行ファイルの起動入口。ファイル名（`InkFlow.exe` / `InkFlow-cli.exe`）と第1引数からGUI/CLIを振り分ける
- `inkflow.spec`: `Analysis` 1つ・`EXE` 2つ（GUI=コンソールなし、CLI=コンソールあり）
- `build.py`: アイコン生成・バージョンリソース生成・PyInstaller実行・動作確認・ZIP化までを行う入口スクリプト

**注意**: このディレクトリに `__init__.py` を置かない。PyPIの `packaging`（PyInstallerの依存）と名前が衝突するため（`CLAUDE.md` 参照）。

### `tests/`（テストディレクトリ）

**役割**: 全テストをフラットに配置する。TypeScript系プロジェクトにある `unit/` `integration/` `e2e/` のようなテスト種別ディレクトリは設けていない。対象モジュールと1対1に対応させ、統合的な検証（例: `test_builder.py` はEPUB生成の統合テストを兼ねる）も同じファイル内に含める。

**構造**:
```
tests/
├── conftest.py          # 合成PDF生成フィクスチャ、offscreen platform設定
├── test_devices.py      # inkflow/devices.py に対応
├── test_layouts.py      # inkflow/layouts.py に対応
├── test_models.py       # inkflow/models.py に対応
├── test_renderer.py     # inkflow/renderer.py に対応
├── test_imaging.py      # inkflow/imaging.py に対応
├── test_cover.py        # inkflow/cover.py に対応
├── test_appicon.py      # inkflow/appicon.py に対応
├── test_composer.py     # inkflow/composer.py に対応（回転・俯瞰の組み合わせも含む）
├── test_epub_writer.py  # inkflow/epub_writer.py に対応
├── test_builder.py      # inkflow/builder.py に対応（統合テストを兼ねる）
├── test_cli.py          # inkflow/cli.py に対応（CLI/GUI出力の一致検証を含む）
├── test_gui.py          # inkflow/gui/ 全体に対応（ヘッドレス）
└── test_packaging.py    # packaging/build.py と packaging/entry.py の純粋関数部分
```

**命名規則**:
- パターン: `test_[対象モジュール名].py`
- 例: `imaging.py` → `test_imaging.py`
- テスト関数名は `test_` で始まる英語のスネークケース。意図が読めるよう長めの名前を許容する（例: `test_two_column_layout_does_not_bleed_across_the_gutter`）

### `docs/`（永続ドキュメントディレクトリ）

**配置ドキュメント**:
- `product-requirements.md`: プロダクト要求定義書
- `functional-design.md`: 機能設計書
- `architecture.md`: アーキテクチャ設計書
- `repository-structure.md`: リポジトリ構造定義書（本書）
- `development-guidelines.md`: 開発ガイドライン（**検証コマンドの正典**）

**未作成**: `glossary.md`（用語集）は別途作成する。

### `.steering/`（ステアリングファイル）

**役割**: 作業単位ごとの要求・設計・タスク進捗の記録。

**構造**:
```
.steering/
└── [YYYYMMDD]-[NN]-[機能名]/
    ├── requirements.md
    ├── design.md
    └── tasklist.md          # 進捗の正。振り返りも末尾に記録する
```

**命名規則**: `20260810-01-kindle-repaginate-epub` のように、日付＋その日の連番（2桁）＋機能名（kebab-case）。

**重要**: 一般的なテンプレート（本スキルの既定ガイド）は `.steering/` を `.gitignore` 対象とする例を挙げているが、**このプロジェクトでは `.steering/` をgit管理する**。実装の意思決定の経緯（なぜその設計を選んだか、何が計画とズレたか）を記録として残す方針のため。BullGraph・ETFTracker・owQRなど姉妹プロジェクトも同様。

### `.github/workflows/`（GitHub Actions）

**配置ファイル**:
- `build.yml`: バージョンタグ push・手動実行で配布物をビルドし、タグ起動時はGitHub Releaseに添付する

## ファイル配置規則

### ソースファイル

| ファイル種別 | 配置先 | 命名規則 | 例 |
|------------|--------|---------|-----|
| 純粋ロジック | `inkflow/` 直下 | 責務を表す名詞（単数） | `layouts.py`, `devices.py` |
| インフラ層 | `inkflow/` 直下 | 扱う対象を表す名詞 | `renderer.py`, `imaging.py` |
| GUIウィジェット | `inkflow/gui/` | 役割＋種別 | `page_view.py`, `settings_dialog.py` |
| 例外クラス | `inkflow/errors.py` に集約 | `[名詞]Error` | `PdfLoadError` |

### テストファイル

| テスト種別 | 配置先 | 命名規則 | 例 |
|-----------|--------|---------|-----|
| モジュール対応テスト | `tests/` | `test_[対象].py` | `test_composer.py` |
| 統合テスト | 対応するモジュールのテストファイル内に同居 | 同上 | `test_builder.py` |
| GUIテスト | `tests/test_gui.py` に集約 | 同上（ヘッドレス実行） | — |

### 設定ファイル

| ファイル種別 | 配置先 | 命名規則 |
|------------|--------|---------|
| 依存関係 | リポジトリ直下 | `requirements.txt` / `requirements-dev.txt` |
| テスト設定 | リポジトリ直下 | `pytest.ini` |
| ビルド設定 | `packaging/` | `inkflow.spec` |
| CI設定 | `.github/workflows/` | `[目的].yml` |

## 依存関係のルール

### レイヤー間の依存

```
UI層 (cli.py, gui/)
    ↓ (OK)
アプリ層 (composer.py, builder.py)
    ↓ (OK)
インフラ層 (renderer.py, imaging.py, cover.py, appicon.py, epub_writer.py)
    ↓ (OK)
純粋ロジック (models.py, layouts.py, devices.py)
```

**禁止される依存**:
- 純粋ロジック → インフラ層／UI層 (❌ Pillow・PyMuPDF・Qtを持ち込まない)
- インフラ層 → アプリ層／UI層 (❌)
- UI層（CLI）→ UI層（GUI）、またはその逆 (❌ 相互に独立)
- `inkflow/` → `packaging/` (❌ アプリ本体はパッケージング方式を知らない)

### CLIとGUIの出力を分岐させない

`gui/main_window.py` も `cli.py` も、EPUB生成は必ず `builder.build_epub()` を経由する。`epub_writer.py` を直接呼ぶ経路を新設しない。これは一般的な「循環依存の禁止」とは別の、このプロジェクト固有のルールである（`tests/test_cli.py::test_cli_and_gui_paths_produce_identical_pages` が機械的に担保する）。

## スケーリング戦略

### 機能の追加

1. **分割レイアウトの追加**: `layouts.py` の `LAYOUTS` に1エントリ追加するだけ（`overlap_axes` を忘れずに設定）。新規ファイル不要。
2. **端末プリセットの追加**: `devices.py` の `DEVICES` に1エントリ追加。新規ファイル不要。
3. **出力形式の追加（PDF等）**: `epub_writer.py` と同じ入力（画像列）を受け取る新しいwriterモジュールを `inkflow/` に追加し、`builder.py` から選択的に呼べるようにする。`composer.py` は変更不要（出力は形式非依存）。
4. **回転の自動判定など、composerより上位の機能**: `composer.py` の入力が `PageSpec` に閉じているため、`PageSpec` を提案する層をUI層とアプリ層の間に追加できる。

### ファイルサイズの管理

**目安**: 1ファイル300行以下を推奨、500行を超えたら分割を検討する。

**現状の例外**: `inkflow/gui/main_window.py`（約960行）。理由と対応方針は前述の「既知の逸脱」を参照。新たに同様の逸脱が生じた場合も、この節に追記して可視化する。

## 特殊ディレクトリ

### `.steering/`

前述のとおり。「今回の作業」を記録し、gitで追跡する。

### `.venv/`（gitignore対象）

Windows専用の仮想環境。`.venv\Scripts\python.exe` を明示パスで呼ぶ（`activate` に依存しない）。

### `build/` / `dist/`（gitignore対象）

`packaging/build.py` の生成物。ビルドのたびに作り直される。

## 除外設定

### `.gitignore`

```
.venv/
__pycache__/
*.pyc
.pytest_cache/
build/
dist/
*.egg-info/

# 生成物
out/
*.epub
*.inkflow.json
```

`.steering/` は**意図的に除外していない**（前述のとおりgit管理する）。`*.inkflow.json` はユーザーが作業用に作るプロジェクトファイルを想定した除外であり、リポジトリ内のサンプル・テスト用途で必要な場合は個別に `git add -f` する。
