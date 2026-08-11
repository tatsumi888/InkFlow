# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## このプロジェクトは何か

雑誌記事PDF（B5〜A4、記事ごとに分冊）を、Kindle Paperwhite でパン操作なしに読める**固定レイアウトEPUB**へ再ページ化するWindowsデスクトップアプリ。原稿1ページを「俯瞰＋分割コマ」に展開し、1号分を1冊にまとめる。

詳細は [README.md](README.md)、設計の経緯は `.steering/` を参照。

## コマンド

すべてリポジトリルートで、仮想環境を**明示パス**で呼ぶ（activate に依存しない）。

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt

.venv\Scripts\python.exe -m inkflow              # GUI（コンソールあり）
.\run.bat                                        # GUI（pythonw、通常はこちら）
.venv\Scripts\python.exe -m inkflow.cli build .\articles -o out.epub

.venv\Scripts\python.exe -m pytest -q                          # 全テスト
.venv\Scripts\python.exe -m pytest tests/test_composer.py -q   # 単一ファイル
.venv\Scripts\python.exe -m pytest -k "overlap" -q             # 名前で絞る

.venv\Scripts\python.exe -m pip install -r requirements-dev.txt   # ビルド用（PyInstaller）
.venv\Scripts\python.exe packaging\build.py                       # 配布物（onedir・既定）
.venv\Scripts\python.exe packaging\build.py --onefile             # 配布物（onefile）
.venv\Scripts\python.exe -m inkflow.cli selftest                  # この環境で動くかの自己診断
```

配布物は `v*` タグを push すると `.github/workflows/build.yml` が GitHub Actions（windows-latest）上でビルドし、GitHub Release に添付する（`gh release` コマンドを使用、サードパーティActionは使わない）。タグと `inkflow.__version__` が一致しないと失敗する。手動実行（`workflow_dispatch`）はアーティファクトのみでRelease は作らない。push・PRごとに走る汎用CIは意図的に設けていない（ビルド自体がテストゲートを内蔵している）。

`pytest.ini` が `pythonpath = .` を前提にしているので、必ずリポジトリルートで実行する。lint / 型チェックのスクリプトは設けていない。**検証コマンドは `pytest` のみ**。

## アーキテクチャ

コア（純粋ロジック）と UI（PySide6 / CLI）を分離している。依存の向きは常に UI → アプリケーション → ドメイン/インフラ。

```
UI 層          inkflow/gui/          inkflow/cli.py
                        ↓ Project (dataclass)
アプリ層        composer.py（再ページ化）  builder.py（統合）
                        ↓
ドメイン/インフラ  models / layouts / devices     ← Pillow・PyMuPDF・Qt に依存しない
                 renderer（PyMuPDF）/ imaging・cover（Pillow）/ epub_writer（zipfile）
```

| モジュール | 責務 |
|---|---|
| `layouts.py` | 分割レイアウト＝「相対矩形の**読み順リスト**」。内部分割線位置の逆算（`internal_dividers`）とオフセット適用（`apply_divider_offsets`）も含む。純粋関数のみ |
| `models.py` | `PageSpec` / `Article` / `Project` と JSON 永続化 |
| `devices.py` | 端末解像度のプリセット |
| `renderer.py` | PDF → PIL画像（PyMuPDF）。必要DPIの算出、プレビュー用LRUキャッシュ |
| `imaging.py` | 余白トリム・クロップ・正規化・階調調整・量子化・分割線（ノド）の自動検出（`find_divider_offset`） |
| `cover.py` | 表紙生成 |
| `composer.py` | `Project` → 出力ページ列（ジェネレータ）。分割線オフセットの自動検出/手動指定の統合（`resolve_divider_offsets`） |
| `epub_writer.py` | 固定レイアウトEPUB（zipfile で直接組み立て） |
| `builder.py` | composer と epub_writer を繋ぐ。**CLI と GUI の共通経路** |
| `buildinfo.py` | バージョン・ビルド日時・ソースコミットの表示文言（`--version` / `selftest` / GUIの「バージョン情報」） |

CLI と GUI が同じ出力になるのは `builder.build_epub()` を共有しているため。ここを迂回する経路を新設しないこと（`tests/test_cli.py::test_cli_and_gui_paths_produce_identical_pages` が守っている）。

## 踏み抜きやすい落とし穴

### 1. オーバーラップは「軸ごと」

分割線上の行が読めなくなるのを防ぐため隣のコマと重ねるが、**行を断つ向きにだけ**効かせる。2段組（`quad_2col` など）で段間の向き＝横に広げると、隣の段の文字が混ざって画面が無駄になる。`Layout.overlap_axes` がこれを制御している。新しいレイアウトを足すときは必ず設定する。

### 2. サイズを詰めたいときに JPEG は逆効果

文字の輪郭が多い誌面では JPEG が PNG の**3倍以上**に膨らむ（実測: 32MB → 106MB）。効くのは階調数を下げること（16→4 でほぼ半分）と、俯瞰ページを外すこと（約25%減）。UI の案内文もこの実測に合わせてある。

### 3. レンダリングは1ページ1回

高解像度レンダリングはコストが高いので、俯瞰も各コマも**同じラスタからのクロップ**で賄う（`composer._compose_page`）。ただし必要DPIは余白トリム**後**のサイズから決めるため、72dpi の下見レンダリングを先に1回だけ挟む。この二段構えを崩さないこと。

### 3-2. `required_dpi()` は `min` であって `max` ではない

コマは縦横比を保ったまま画面に収める（contain）ので、実際に効くのは縦横どちらか一方の制約だけ。`max` にすると使われない解像度まで刻むことになり、無駄なうえ縮小の再サンプリングでぼける。`min` を採ると収めたあとの倍率がちょうど 1.0 になり、リサイズ自体が起きない。

### 3-3. 回転は `finalize_page()` の**前**

`imaging.rotate_image()` はクロップ直後に掛ける。あとから回すと白パディング込みで回ってしまい、端末解像度に収まらなくなる。回転時は `required_dpi(rotated=True)` で端末の幅と高さを入れ替えるのも忘れないこと。

### 3-4. `PageSpec` を組み立てるときは `replace()`

GUI でレイアウトや俯瞰を変える処理は `dataclasses.replace(spec, ...)` を使う。`PageSpec(...)` と手で組み立てると、フィールドを増やしたときに設定（現状は `rotate`）が黙って初期値へ戻る。

### 3-5. 分割線の自動検出は「探索窓の外」を見ない／手動指定は上書きであって加算ではない

`imaging.find_divider_offset()` は既定位置の**前後12%だけ**を探す（`DEFAULT_DIVIDER_SEARCH_RATIO`）。窓を外れた位置に本当のノドがあっても検出しない（＝既定位置のまま）。「レイアウト選択という既存の意図を尊重したうえでの微修正」という設計判断なので、ズレの大きいページは `column_bias`/`row_bias` の手動指定で救う想定。テストで大きな非対称PDFを作るときは、この12%窓に収まる程度のズレにしないと「検出できて当然」の期待が外れる（実際にこれで一度テストを書き間違えた）。

`PageSpec.column_bias`/`row_bias` が `None` でなければ、その軸は自動検出を**一切行わず**、指定値をすべての分割線に一律適用する（`composer.resolve_divider_offsets`）。「自動検出結果に手動値を足し込む」ではない。

### 3-6. `column_bias`/`row_bias` の既定値は `0.0`（既定位置固定）であって `None`（自動検出）ではない

実運用で自動検出が過大な補正をしてしまうページが無視できない頻度であったため、既定は自動検出を**無効**にしてある。`PageSpec`/`PageDefaults` の `column_bias`/`row_bias` の既定値は `0.0`（オフセット無し＝既定位置に固定）で、`None`（自動検出に任せる）は GUIの「分割位置の微調整」で `[自動]` を明示的に押したときだけ入る値。逆に `[既定]` を押すと `0.0` に戻る（`[自動]` の「戻す」ではなく `[既定]` の「戻す」が既定値側）。

`PageDefaults.from_dict()` は `PageSpec.from_dict()` と同じ「キーが無ければ `base`（dataclassの既定値）を使う」パターンにしてある（`data.get(...)` だけで済ませると、キー欠落時に常に `None` へ落ちてしまい、既定値が `0.0` の意味をなさない）。新しいフィールドを `PageDefaults` に足すときはこのパターンを踏襲すること。

### 4. `composer.compose()` はジェネレータ

200ページぶんの生画像（1枚約2MB）を同時に抱えないための設計。`list()` で受けるのはテストだけにする。

### 5. `mimetype` は ZIP の先頭・無圧縮

EPUB の要件。`epub_writer.write_epub()` の最初の `writestr` を動かさないこと。画像は既に圧縮済みなので `ZIP_STORED` で入れている。

### 6. PyMuPDF は `import pymupdf`

`import fitz` は非推奨警告が出る。

### 6-2. パッケージングで踏んだ落とし穴

`packaging/` に閉じている（本体は PyInstaller を知らない）が、次は実際に踏んだもの。

- **`packaging/entry.py` で「同名のパスが存在するか」を見てはいけない。** CLI/GUI の振り分けを `Path(argv[1]).exists()` で判定すると、カレントに PyInstaller の作業用 `build/` があるだけで `InkFlow-cli.exe build ...` が GUI 起動に化ける。パス区切りの有無で判定する。
- **CLI用/GUI用の実行ファイルは実行ファイル名でも振り分ける。** 引数だけで決めると `InkFlow-cli.exe` を引数なしで起動したときに GUI が立ち上がる。
- **凍結した実行ファイルは `PYTHONIOENCODING` を無視する。** 日本語Windowsのコンソールは cp932 なので、表現できない文字（em dash など）を print すると落ちる。`cli._make_output_robust()` が `errors=backslashreplace` に再設定している。子プロセスの出力を読む側も cp932 で復号する必要がある。
- **`packaging/` に `__init__.py` を置かない。** PyPI の `packaging`（PyInstaller の依存）と衝突する。
- **spec の除外リストは必ず実起動で検証する。** 未使用 Qt DLL を落としてサイズを 170MB → 124MB にしているが、落としすぎは起動するまで分からない。`build.py` の動作確認が `selftest` を走らせるのはこのため。

### 6-3. Qt オブジェクトはチェーン呼び出しで取得しない

`window.menuBar().actions()[0].menu()` のように1行で連鎖して書くと、中間の無名オブジェクト（`.actions()` が返す一時リストなど）が式の評価直後にGCされ、shiboken の所有権判定を巻き込んで**本来は生きているはずのオブジェクトまで解放される**ことがある（`RuntimeError: libshiboken: Internal C++ object ... already deleted`）。offscreen・実プラットフォームの両方で再現する。テストでメニューやアクションを辿るときは、必ず中間結果を名前付き変数に分ける。

```python
# 落ちることがある
action = window.menuBar().actions()[0].menu().actions()[0]

# 安定する
menu_bar = window.menuBar()
file_menu = menu_bar.actions()[0].menu()
action = file_menu.actions()[0]
```

### 6-4. `BuildWorker` を実際に起動するテストは後始末を徹底する

GUIテストで `export_epub()` 等を通して本物の `BuildWorker`（`QThread`）を起動すると、`worker.wait()` でスレッドの終了は待てても、`succeeded`/`finished` シグナルの配送（キュー投函されたイベント）は**そのテストの中では処理されない**。処理されないまま `window` が破棄（`deleteLater()`）されると、シグナルは配送先を失ったままイベントキューに残り、**後続の別テストが `qapp.processEvents()` を呼んだ瞬間に配送されて `Windows fatal exception: code 0xc0000374`（ヒープ破損）でプロセスごと落ちる**。実際に踏んだ。

- ワーカーの完了そのものを検証したいテストは、`worker.wait()` の後に必ず `qapp.processEvents()` を呼んでキューを空にする（`test_build_worker_produces_epub` を参照）。
- 完了までは不要で「呼び出した時点の同期的な副作用」だけを見たいテストは、`monkeypatch.setattr(BuildWorker, "start", lambda self: None)` でスレッド自体を起動しない。

### 7. GUI に入力ウィジェットを置かない

数字キー（`1`〜`7`）をレイアウト選択のショートカットに割り当てているため、メインウィンドウに `QLineEdit` を置くと入力を奪われる。テキスト入力は必ずモーダルダイアログ（`BookSettingsDialog` / `QInputDialog`）側に置く。

## テスト

- 実物の雑誌PDFは持ち込まない。`tests/conftest.py` の `make_pdf()` が PyMuPDF で2段組ページを合成する。
- GUIテストは `conftest.py` が Qt の import 前に `QT_QPA_PLATFORM=offscreen` を設定するのでヘッドレスで走る。
- **offscreen プラットフォームではフォントが1つも読まれず、全文字が豆腐（□）になる。** UI を画像に描いて確認したいときは `QT_QPA_PLATFORM` を外し、`show()` せずに `widget.render(QPixmap(...))` する（ウィンドウは出ない）。豆腐を日本語表示の不具合と誤診しないこと。
- 重い統合テストは `custom:150x200` の小さな端末プロファイルを使って高速化している。実解像度が必要なテストだけ `paperwhite_11` を使う。

## ドキュメント

`docs/` に永続ドキュメント一式がある。`docs/development-guidelines.md` の検証コマンドが他のガイドより優先する。

| ファイル | 内容 |
|---|---|
| `docs/product-requirements.md` | プロダクト要求定義書 |
| `docs/functional-design.md` | 機能設計書（画面遷移・データ構造・アルゴリズム） |
| `docs/architecture.md` | アーキテクチャ設計書（レイヤ構成・依存関係） |
| `docs/repository-structure.md` | リポジトリ構造定義書 |
| `docs/development-guidelines.md` | 開発ガイドライン |
| `docs/glossary.md` | 用語集 |

## 作業の進め方

- 作業単位のステアリングは `.steering/[YYYYMMDD]-[NN]-[機能名]/`。`tasklist.md` が進捗の正で、`[ ]` → `[x]` は1タスクずつ即時更新する。
- ユーザーへの応答・ドキュメントはすべて日本語で書く。
- **このディレクトリはGitリポジトリであり、リモート（`origin` = `github.com/tatsumi888/InkFlow`）を持つ**。`main` ブランチで作業する。push はユーザーの指示があってから行う。
