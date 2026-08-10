# 設計書

## アーキテクチャ概要

新しいモジュールは作らない。`MainWindow` に `new_project()` を1つ追加し、既存の `open_project()` と同じ骨格（確認 → 状態の入れ替え → 画面更新）に乗せる。設定入力は新しいダイアログを作らず、既存の `BookSettingsDialog` をそのまま流用する。

```
new_project()
  ├─ _confirm_discard_changes()      既存（open_project と共有）
  ├─ Project()                       白紙のプロジェクト
  ├─ BookSettingsDialog(blank, self) 既存ダイアログをそのまま使う
  │    └─ exec() が Rejected なら、ここで中断（現在のプロジェクトは無傷）
  └─ 状態の入れ替え                   open_project() と同じ手順
       ├─ preview_cache.invalidate()
       ├─ self.project = blank
       ├─ self._current = 0
       ├─ _mark_dirty(False)
       └─ refresh_all()
```

## 実装の要点

### `MainWindow.new_project()`

`open_project()` の実装をほぼそのままなぞる。違いは「ファイルから読む」代わりに「白紙のプロジェクトを作り、本の設定ダイアログで内容を決める」点だけ。

```python
def new_project(self) -> None:
    if not self._confirm_discard_changes():
        return
    project = Project()
    dialog = BookSettingsDialog(project, self)
    if dialog.exec() != BookSettingsDialog.DialogCode.Accepted:
        return
    dialog.apply_to(project)

    self.preview_cache.invalidate()
    self.project = project
    self._current = 0
    self._mark_dirty(False)
    self.refresh_all()
    self.statusBar().showMessage("新規プロジェクトを作成しました", 4000)
```

- ダイアログを**先にキャンセルできる**ようにするため、`self.project` を書き換えるのはダイアログが Accepted を返した後にする。ここを早めると、キャンセル時に空プロジェクトが残ってしまう。
- `Project()` は `articles=[]`・`project_path=None` が既定なので、追加の後始末は不要。
- `_mark_dirty(False)` にするのは、アプリ起動直後の空プロジェクトが「未保存」扱いにならないのと同じ理由。

### メニュー

`_build_menu()` の File メニュー、「PDFを追加…」の**前**に置く。「まず新しい本を用意してから記事を足す」という操作順に合わせるため。

```python
self._add_action(file_menu, "新規プロジェクト…", self.new_project, QKeySequence.StandardKey.New)
file_menu.addSeparator()
self._add_action(file_menu, "PDFを追加…", self.add_pdfs, QKeySequence.StandardKey.Open)
```

`QKeySequence.StandardKey.New` は環境依存で `Ctrl+N`（Windows既定）に解決される。既存のショートカット（`Ctrl+O` 系）と衝突しない。

## テスト戦略

`BookSettingsDialog.exec` をモンキーパッチしてモーダルループを避ける。既存テストにあるダイアログ操作（`QInputDialog.getText` や `QMessageBox.question` のパッチ）と同じ手法。`exec` の差し替え先で `self`（実際のダイアログインスタンス）のウィジェットを直接操作すれば、ユーザーが入力してOKを押した状態を模倣できる。

```python
def fake_exec(self):
    self.title_edit.setText("新しい雑誌")
    return BookSettingsDialog.DialogCode.Accepted
monkeypatch.setattr(BookSettingsDialog, "exec", fake_exec)
```

検証する項目:
- 確認ガード（キャンセル／破棄／保存の3分岐）
- 設定ダイアログのキャンセルで現在のプロジェクトが無傷
- 設定ダイアログの内容が新プロジェクトへ反映される
- ページ位置・記事一覧・`project_path`・`_dirty` のリセット
- 空プロジェクトからの実行でも例外が出ない
- メニューのショートカットが `Ctrl+N` に解決される

## 将来の拡張性

「最近使ったプロジェクト」を足す場合、`new_project()` や `open_project()` の骨格には手を入れず、メニューに `QMenu` を追加するだけで済む。今回はスコープ外。
