# 設計書

## 方針

`MainWindow` に「最後にファイル選択ダイアログで実際に使われたフォルダ」を1つだけ覚えるインスタンス変数 `_last_browsed_dir: Path | None` を持たせる。ダイアログ種別ごとに別々に覚えず、共有の1つにする。プロジェクト保存・EPUB出力・PDF追加は同じ「このプロジェクトの作業フォルダ」を指すことがほとんどで、種別ごとに分ける利点が薄いため。

```python
def _default_dialog_dir(self) -> str:
    """ファイル選択ダイアログの既定フォルダ。

    ユーザーが既にこのプロジェクトでフォルダを選んでいればそこを優先する。
    まだ無ければ、直近に追加した記事PDFのフォルダを使う（保存・出力を、
    記事PDFと同じ場所から始められるように）。ドラッグ＆ドロップで追加した
    記事も対象になる（記事の実パスから求めるため、追加経路を問わない）。
    """
    if self._last_browsed_dir is not None:
        return str(self._last_browsed_dir)
    if self.project.articles:
        return str(self.project.articles[-1].path.parent)
    return ""

def _remember_dialog_dir(self, chosen_path: str | Path) -> None:
    path = Path(chosen_path)
    self._last_browsed_dir = path if path.is_dir() else path.parent
```

## 適用箇所

- `add_pdfs()`: `getOpenFileNames` の `dir` 引数に `_default_dialog_dir()` を渡す。選択後に `_remember_dialog_dir(paths[0])`。
- `save_project_as()`: `project_path` が無いときの `suggested` を `Path(_default_dialog_dir()) / ファイル名` に変える（現状はファイル名のみでフォルダ指定が無い）。保存後に `_remember_dialog_dir(path)`。
- `export_epub()`: `project_path` が無いときだけ `builder.default_output_path(project, Path(_default_dialog_dir()))` を使う。既に保存済みなら、従来どおり `project.base_dir`（＝プロジェクトファイルの場所）を優先する。選択後に `_remember_dialog_dir(path)`。

## リセット

`new_project()` と `open_project()` で `self.project` を差し替える箇所に `self._last_browsed_dir = None` を追加する。既に他の状態（`preview_cache` など）もそこでリセットしているのと同じタイミング。

`open_project()` は読み込んだプロジェクトに記事があれば、リセット後すぐに `_default_dialog_dir()` がその記事フォルダへフォールバックするため、追加の処理は不要。

## テスト戦略

`QFileDialog` の静的メソッドを monkeypatch し、渡された `dir` 引数を記録して検証する。

- 記事が無い状態で各ダイアログを開くと `dir` が空文字である。
- 記事を追加した後は、記事PDFのフォルダが `dir` に渡る。
- ダイアログで実際に選んだ後は、次回以降そのフォルダが優先される（記事PDFのフォルダより優先）。
- `new_project()` / `open_project()` 後にリセットされる。
- `export_epub()` は、プロジェクトが保存済みならプロジェクトファイルの場所を優先し続ける（今回の変更で壊れないことを確認）。
