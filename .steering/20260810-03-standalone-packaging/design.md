# 設計書

## アーキテクチャ概要

パッケージングは**アプリ本体の外側**に置く。`inkflow/` パッケージは PyInstaller の存在を知らないままにし、ビルド手順は `packaging/` に閉じる。唯一の例外がアイコンで、これは GUI のウィンドウアイコンとしても使うため `inkflow/` 側に置く。

```
packaging/
  build.py        ビルドの入口（PyInstaller の起動・ZIP化・動作確認）
  inkflow.spec    PyInstaller の仕様（GUI用とCLI用の2実行ファイル）
inkflow/
  appicon.py      アイコン画像の生成（Pillow）。GUI とビルドの両方から使う
```

依存の向き:

```
packaging/build.py ──→ packaging/inkflow.spec ──→ inkflow/（解析対象）
        └──────────→ inkflow.appicon（.ico の書き出し）
inkflow/gui/app.py ──→ inkflow.appicon（ウィンドウアイコン）
```

`packaging/` は配布物には含まれない。`inkflow/` から `packaging/` を参照しないので、パッケージング方式を変えても本体には影響しない。

## コンポーネント設計

### 1. inkflow/appicon.py

**責務**: アプリのアイコン画像を生成する。

**実装の要点**:

- Pillow で描く。**バイナリ資産をリポジトリに置かない**方針にするため（`cover.py` が表紙を生成しているのと同じ考え方）。
- 図柄は「縦長の紙面が4分割され、左上のコマだけが濃い」という InkFlow の機能そのものを表す単純な図形にする。小さいサイズでも潰れないよう、線と塗りだけで構成する。
- `render_icon(size: int) -> Image.Image` が1サイズを返し、`write_ico(path, sizes)` が複数サイズを1つの `.ico` にまとめる。Windows のタスクバー・エクスプローラは 16/32/48/256 を使い分けるため、この4サイズを含める。
- `to_qicon()` は置かない。Qt への変換は GUI 側（`gui/app.py`）で行い、`appicon` は Qt に依存しない純粋な画像生成に留める。テストを軽く保つため。

### 2. packaging/inkflow.spec

**責務**: PyInstaller に何をどう固めるかを伝える。

**実装の要点**:

- **`Analysis` は1つ、`EXE` は2つ**。GUI（`console=False`）と CLI（`console=True`）で共通の解析結果を使い回す。同じ依存を2回解析するのは無駄なため。
  - GUI のエントリ: `packaging/entry_gui.py`（`inkflow.gui.app.run()` を呼ぶ）
  - CLI のエントリ: `packaging/entry_cli.py`（`inkflow.cli.main()` を呼ぶ）
  - `inkflow/__main__.py` を直接エントリにしないのは、PyInstaller が `__main__` という名前のモジュールを扱うと解析が紛らわしくなるため。薄い起動スクリプトを別に置く。
- onedir では `COLLECT` に2つの `EXE` を渡し、**ライブラリを共有する1フォルダ**にする。onefile では `EXE` それぞれに `binaries`/`datas` を含める。
- **除外モジュール**を明示する。PySide6 は既定で大量の Qt モジュールを引き込むので、使っていないもの（QtWebEngine / Qt3D / QtMultimedia / QtCharts など）と、`tkinter`・`unittest`・`pytest` を除外する。サイズを抑えるのが目的。
- モード（onedir/onefile）は `build.py` から環境変数で渡す。spec は Python スクリプトとして評価されるため、引数を直接渡す手段がないため。

### 3. packaging/build.py

**責務**: ビルドの入口。

**実装の要点**:

- 引数: `--onefile` / `--onedir`（既定）、`--no-zip`、`--no-verify`、`--clean`。
- 手順:
  1. PyInstaller の有無を確認する。無ければ導入コマンドを示して終了する（**勝手に `pip install` しない**。仮想環境を書き換えるのはユーザーの判断に属するため）。
  2. `inkflow.appicon` で `build/inkflow.ico` を生成する。
  3. Windows のバージョンリソースファイルを `inkflow.__version__` から生成する。実行ファイルのプロパティに版が出るようにするため。
  4. PyInstaller を**サブプロセス**で起動する（`PyInstaller.__main__.run()` を同一プロセスで呼ぶと、解析対象のパッケージを import 済みの状態で走るため副作用が読みにくい）。
  5. 生成物のサイズを集計して表示する。
  6. 動作確認: 生成した CLI 実行ファイルを `layouts` 付きで起動し、既知の文字列が出るか確認する。**実際に起動して確かめる**のが、パッケージングで最も落ちやすい「隠れた依存の取りこぼし」を検出する唯一の方法。
  7. onedir なら ZIP にまとめる。
- 純粋な部分（バージョンリソースの文字列生成、成果物パスの決定、サイズの整形）は関数に切り出してテスト可能にする。ビルドそのものはテストで回さない（数分かかるため）。

### 4. inkflow/gui/app.py（変更）

- `QApplication` にウィンドウアイコンを設定する。`appicon.render_icon()` の PIL 画像を `QPixmap` 経由で `QIcon` にする。
- 変換に失敗しても起動は続行する。アイコンは装飾であり、これで落ちるのは割に合わないため。

## データフロー

### 配布物を作る
```
1. .venv\Scripts\python.exe packaging\build.py
2. PyInstaller の有無を確認
3. build/inkflow.ico を生成（appicon）
4. build/version_info.txt を生成（__version__ から）
5. pyinstaller packaging/inkflow.spec をサブプロセスで実行
   → dist/InkFlow/InkFlow.exe（GUI）
   → dist/InkFlow/InkFlow-cli.exe（CLI）
6. dist/InkFlow/InkFlow-cli.exe layouts を実行して動作確認
7. dist/InkFlow-<version>-win64.zip にまとめる
8. パスとサイズを表示
```

## エラーハンドリング戦略

新しい例外型は追加しない。`build.py` はアプリ本体ではなく開発用スクリプトなので、`InkFlowError` の体系には載せない。

- PyInstaller 未導入・ビルド失敗・動作確認の失敗は、日本語のメッセージを標準エラーへ出して**非ゼロ終了**する。CI やバッチから使えるようにするため。
- アイコン生成の失敗はビルドを止めない（アイコンなしで続行し、警告を出す）。

## テスト戦略

### ユニットテスト
- `inkflow/appicon.py`: 生成画像の寸法・モード、`.ico` が書き出せること、複数サイズが含まれること、極端に小さいサイズでも落ちないこと。
- `packaging/build.py` の純粋関数: バージョンリソース文字列に版が反映されること、成果物パスがモードによって変わること、サイズ整形。

### 統合テスト
- **実ビルドはテストに含めない**（数分かかるため）。代わりにフェーズ7で1回実行し、次を確認する。
  - CLI 実行ファイルで `layouts` / `devices` が動く
  - CLI 実行ファイルで合成PDFから EPUB を生成でき、**ソース実行の出力とページ画像が一致する**
  - GUI 実行ファイルが起動する
  - onedir と onefile の起動時間を実測する

### GUI テスト
- ウィンドウアイコンが設定されても既存のテストが壊れないこと。

## 依存ライブラリ

```
pyinstaller>=6.0    # ビルド時のみ。requirements.txt とは分けて requirements-dev.txt に置く
```

実行時の依存は増やさない。配布物に PyInstaller 自身は含まれない。

## ディレクトリ構造

```
InkFlow/
  packaging/
    build.py
    inkflow.spec
    entry_gui.py
    entry_cli.py
  inkflow/
    appicon.py          （新規）
    gui/app.py          （変更: ウィンドウアイコン）
  tests/
    test_appicon.py     （新規）
    test_packaging.py   （新規）
  requirements-dev.txt  （新規）
  build/                （生成物・.gitignore 済み）
  dist/                 （生成物・.gitignore 済み）
```

## 実装の順序

1. `inkflow/appicon.py` とテスト
2. `packaging/entry_gui.py` / `entry_cli.py`
3. `packaging/inkflow.spec`
4. `packaging/build.py` とテスト
5. `requirements-dev.txt`
6. GUI のウィンドウアイコン
7. 実ビルドと動作確認（起動時間・サイズの実測）
8. ドキュメント更新

## セキュリティ考慮事項

- コード署名は行わない。未署名の実行ファイルは Windows SmartScreen が警告するため、その回避方法（「詳細情報」→「実行」）をドキュメントに記す。
- 配布物にソースPDFやプロジェクトファイルを含めない。`dist/` に入るのはアプリのみ。
- ビルドスクリプトは勝手に `pip install` しない。仮想環境の変更はユーザーの判断に委ねる。

## パフォーマンス考慮事項

- onefile は起動のたびに一時ディレクトリへ全体を展開するため、PySide6 のような大きな依存では起動が目に見えて遅くなる。既定を onedir にするのはこのため。実測値をドキュメントに残す。
- 未使用の Qt モジュールを除外してサイズを削る。除外しすぎると実行時に落ちるので、**必ずビルド後の動作確認で検証する**。

## 将来の拡張性

- インストーラを作る場合、`dist/InkFlow/` をそのまま入力にできる。
- GitHub Actions でのリリース自動化を足す場合、`packaging/build.py` をそのまま呼べる（対話的な要素を持たせない設計にしてある）。
- 他プラットフォーム向けに広げる場合、spec の分岐で対応できる。アイコン生成はプラットフォーム非依存。
