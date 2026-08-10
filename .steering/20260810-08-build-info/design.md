# 設計書

## アーキテクチャ概要

```
packaging/build.py
  └─ write_build_info()  ビルド直前に inkflow/_generated_build_info.py を生成
                          （git commit / dirty / build time を埋め込む）
                          PyInstaller実行後に削除（ソースツリーに残さない）

inkflow/buildinfo.py（新規）
  ├─ sys.frozen で「パッケージ版か」を判定
  ├─ パッケージ版: _generated_build_info から読む
  └─ ソース実行: その場で git に問い合わせる

inkflow/cli.py       --version / selftest で buildinfo.describe() を使う
inkflow/gui/main_window.py   ヘルプメニュー「バージョン情報…」で表示
```

## なぜ `inkflow/` 配下に生成ファイルを置くか

`_generated_build_info.py` を `inkflow/` パッケージ内に生成し、`buildinfo.py` からPythonの `import` で読む。PyInstallerは静的にimportを解析して自動的に同梱するため、`spec` の `datas` にパスを追加する必要がなく、onedir/onefileの実行時パス差異（`sys._MEIPASS` の有無）を気にしなくて済む。

生成は `packaging/build.py` が PyInstaller 実行の直前に行い、**実行後に削除する**。理由は2つ:
- PyInstallerは実行時点でファイルをバイトコードごと埋め込むため、ビルド完了後にソースツリーへ残す必要がない。
- 残しておくと、ビルド直後に `python -m inkflow` で**ソース実行**したとき、`inkflow/_generated_build_info.py` が実在してimportに成功してしまい、**パッケージ版のビルド情報を誤って表示する**事故が起きる。

## フリーズ判定は `sys.frozen` で行う（ファイルの有無で判定しない）

`_generated_build_info.py` の**有無**ではなく、PyInstallerのブートローダーが設定する `sys.frozen` 属性の有無で「パッケージ版かどうか」を判定する。ビルド直後に生成ファイルが（削除し忘れなどで）残っていても、ソース実行時は必ず `sys.frozen` が無いため、誤ってパッケージ版扱いにならない。

```python
FROZEN = getattr(sys, "frozen", False)

if FROZEN:
    try:
        from ._generated_build_info import BUILD_COMMIT, BUILD_DIRTY, BUILD_TIME
    except ImportError:
        BUILD_COMMIT = BUILD_DIRTY = BUILD_TIME = None
else:
    BUILD_COMMIT = BUILD_DIRTY = BUILD_TIME = None
```

## `buildinfo.py` のインターフェース

```python
def source_commit() -> str | None:
    """フリーズ時はビルド時に埋め込んだ値、ソース実行時はその場でgitに聞く。"""

def source_dirty() -> bool | None:
    """作業ツリーに未コミットの変更があるか。分からなければ None。"""

def build_time() -> str | None:
    """パッケージ版のビルド日時（ISO8601、UTC）。ソース実行なら None。"""

def describe() -> str:
    """GUI/CLI共通の表示文言（複数行）。"""
```

`source_commit()` / `source_dirty()` がソース実行時に呼ぶ `git` コマンドは、失敗（gitが無い・`.git`が無い・タイムアウト）しても例外を投げず `None` を返す。診断用の付加情報のためにアプリを落とすのは割に合わない。

## `packaging/build.py` への追加

```python
def git_commit_hash() -> str | None: ...   # git rev-parse --short HEAD
def git_is_dirty() -> bool | None: ...     # git status --porcelain の有無
def write_build_info() -> Path: ...        # inkflow/_generated_build_info.py を書く
```

`main()` で `generate_icon()` / `write_version_files()` と並べて呼ぶ。生成に失敗しても（アイコン生成の失敗と同様）警告のみでビルドは継続する。PyInstaller実行後、成功・失敗に関わらず `finally` でこの生成ファイルを削除する。

## 表示文言の例

```
InkFlow 1.0.0
ソース: 554c82e（未コミットの変更あり）
ビルド: ソース実行（パッケージ版ではない）
```

```
InkFlow 1.0.0
ソース: 554c82e
ビルド: 2026-08-10 16:32 UTC
```

## テスト戦略

### ユニットテスト（`tests/test_buildinfo.py`）
- `describe()` をフリーズ/非フリーズ、コミット取得可否、dirty有無の組み合わせで検証する。実際の `git` には依存させず、`buildinfo` モジュールの `BUILD_COMMIT` 等のモジュール変数や `_run_git` を monkeypatch する。
- `format_build_time()` のISO8601整形。
- `source_commit()` / `source_dirty()` が git 失敗時に `None` を返す（`subprocess.run` を monkeypatch）。

### `packaging/build.py` の追加テスト
- `git_commit_hash()` / `git_is_dirty()` の成功・失敗パス（`subprocess.run` を monkeypatch）。
- `write_build_info()` が構文的に妥当なPythonファイルを書き、`BUILD_TIME`/`BUILD_COMMIT`/`BUILD_DIRTY` を含むことを確認する。

### GUIテスト
- ヘルプメニューに「バージョン情報…」がある。
- クリックすると `buildinfo.describe()` の内容を含むダイアログが出る（`QMessageBox.information` を monkeypatch して呼び出し引数を検証）。

### 実ビルドでの確認
- `packaging/build.py` を実行し、`selftest` の出力にビルド時刻・コミットが含まれることを確認する。
- ビルド直後に `python -m inkflow.cli --version` を**ソースから**実行し、パッケージ版の情報が混入していない（「ソース実行」表示になる）ことを確認する。
