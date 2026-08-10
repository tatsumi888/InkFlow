# 設計書

## 構成

`.github/workflows/build.yml` の1ファイルのみ。ローカルの `packaging/build.py` をそのまま呼び出すだけで、ビルドの実体（PyInstaller の呼び方・除外設定・動作確認）はワークフロー側に持たせない。CIとローカルで手順が分岐しないようにするため。

```
.github/workflows/build.yml
  trigger: push tags 'v*' / workflow_dispatch
    ↓
  windows-latest ランナー
    ↓
  actions/checkout → actions/setup-python(3.12)
    ↓
  pip install -r requirements-dev.txt      （requirements.txt + pyinstaller）
    ↓
  [タグ起動のときのみ] タグとバージョンの整合確認
    ↓
  pytest -q                                 ← ここで落ちたらビルドしない
    ↓
  packaging/build.py --onedir
  packaging/build.py --onefile
    ↓
  actions/upload-artifact                   （常に）
  gh release create/upload                  （タグ起動のときのみ）
```

## 決定事項と理由

### Windows ランナーのみ

`packaging/inkflow.spec` は Windows 向け実行ファイル（`.exe`）を作る。PyInstaller はクロスコンパイルできないため、ビルドは対象OS上で行う必要がある。`windows-latest` 一択。

### テストをワークフロー内に内蔵する（別ファイルにしない）

push・PR ごとに走る汎用CI（`ci.yml`）は今回のスコープ外にした（要求時点でユーザーが求めたのは「配布ファイルを作る」ことで、汎用CIは別の意思決定）。ただし、**壊れたビルドを配布してしまうことは避けたい**ため、ビルド work flow自身に `pytest -q` のゲートを内蔵する。タグ push はブランチ push とは別のイベントであり、仮に `ci.yml` があったとしてもタグでは走らない（`push.branches` フィルタはタグにマッチしない）ので、どのみち自前でテストを回す必要がある。

### タグとバージョンの整合確認

`packaging/build.py` が作るZIPのファイル名は `inkflow.__version__` から決まる（`InkFlow-<version>-win64.zip`）。タグ `v1.2.3` を打ったのに `__version__` が `"1.0.0"` のままだと、Release名とファイル名の版がずれて紛らわしい。タグ起動のときだけ、両者が一致することを確認して不一致なら失敗させる。

PowerShell で次のように比較する（Windows ランナーの既定シェルは PowerShell）。

```powershell
$tagVersion = "${{ github.ref_name }}" -replace '^v', ''
$pkgVersion = python -c "from inkflow import __version__; print(__version__, end='')"
if ($tagVersion -ne $pkgVersion) {
  Write-Error "タグ($tagVersion)と inkflow.__version__($pkgVersion) が一致しません"
  exit 1
}
```

### onedir と onefile を両方作る

`packaging/build.py` が両方をサポートしているので、CIでも両方作る。onedir はZIPに、onefile はそのまま2つの `.exe` になる。1ジョブの中で `--onedir` → `--onefile` の順に**逐次**呼ぶ（別ジョブ・マトリクスに分けない）。両方を1ジョブにまとめる理由は、チェックアウト・依存インストール・テスト実行を2回行う無駄を避けるため。ローカルで既に確認済みの通り、同一 `dist/` に対して onedir → onefile の順で呼んでも出力パスが衝突しない（`dist/InkFlow/`フォルダ vs `dist/InkFlow.exe`）。

### アーティファクトの内容

`dist/*.zip`・`dist/InkFlow.exe`・`dist/InkFlow-cli.exe` の3種類のみをアップロードする。onedir の展開済みフォルダ（`dist/InkFlow/`、124MB）はZIPの中身と重複するため含めない。

### リリースへの添付は `gh` CLI で行う

サードパーティの Marketplace Action（`softprops/action-gh-release` 等）を追加せず、GitHub-hosted ランナーに標準搭載されている `gh` CLI をそのまま使う。追加の依存を増やさず、権限は `permissions: contents: write` で `GITHUB_TOKEN` に与えるだけで済む。

同じタグでワークフローを再実行しても失敗しないよう、Release が無ければ作成、あれば `--clobber` で成果物を上書きする2段構えにする。

```powershell
$tag = "${{ github.ref_name }}"
if (-not (gh release view $tag 2>$null)) {
  gh release create $tag --title "InkFlow $tag" --generate-notes
}
gh release upload $tag dist/*.zip dist/InkFlow.exe dist/InkFlow-cli.exe --clobber
```

### 動作確認は `packaging/build.py` に既に内蔵されている

`build.py` はビルド後に生成した実行ファイルを実際に起動して `selftest` を走らせる（`verify_executables()`）。ワークフロー側で追加の検証は行わない。二重にする意味が薄く、ローカルと同じ経路を通すという設計方針にも合う。

## テスト戦略

ワークフロー自体をローカルで実行するテストは書かない（GitHub Actions固有の実行環境に依存するため）。YAML構文の妥当性と、埋め込んだPowerShellスクリプトの断片が構文として壊れていないことを、実際にタグを push して確認する（本タスクの最終検証はCI上での実行そのもの）。
