# 要求内容

## 概要

ドキュメント一式を整備する。具体的には、これまで未作成だった `docs/functional-design.md` `docs/repository-structure.md` `docs/glossary.md` を専用スキルで作成し、今回の一連の変更（縦横入替の俯瞰別指定、単独実行パッケージング、新規プロジェクト機能、GitHub Actionsビルド）を既存ドキュメントへ反映する。

## 背景

`docs/product-requirements.md` `docs/architecture.md` `docs/development-guidelines.md` の3つは初回実装時に作成済みだが、リポジトリのCLAUDE.mdが定める永続ドキュメント一式（6種類）のうち残り3つ（機能設計書・リポジトリ構造定義書・用語集）が未作成のままだった。また、直近3回の機能追加（回転の俯瞰別指定・パッケージング・新規プロジェクト・GitHub Actions）で `README.md` と `CLAUDE.md` は都度更新してきたが、全体を通したドキュメントの整合性確認は行っていなかった。

## 実装対象

### 1. 不足ドキュメントの作成

- `docs/functional-design.md`（`functional-design` スキル使用）
- `docs/repository-structure.md`（`repository-structure` スキル使用）
- `docs/glossary.md`（`glossary-creation` スキル使用）

### 2. 既存ドキュメントの整合性確認

- `README.md` に永続ドキュメント一式へのリンクを追加する。
- `CLAUDE.md` の記載が現状と食い違っていないか確認する（発見した齟齬: 「このディレクトリはGitリポジトリではない」という記述が、実際にはGit初期化・GitHub push済みで誤りになっていた）。
- ルートの `d:\ClaudeCode\CLAUDE.md`（プロジェクト索引）が、InkFlowに追加されたCI構成（`build.yml`）を反映しているか確認する。

## 受け入れ条件

- [ ] `docs/functional-design.md` `docs/repository-structure.md` `docs/glossary.md` が存在する。
- [ ] 3つとも、プロジェクトの実際の構成（Python単一パッケージ、PySide6 GUI、テストのフラット配置など）を反映しており、テンプレートのプレースホルダーが残っていない。
- [ ] `README.md` から6種類のドキュメントすべてにリンクが張られている。
- [ ] `CLAUDE.md` に事実と異なる記述が残っていない。
- [ ] ルートの `CLAUDE.md` がInkFlowの `build.yml` の存在を反映している。

## スコープ外

- 既存3ドキュメント（PRD・architecture・development-guidelines）の全面書き直し。今回は新規3点の作成と、直近の変更点の反映に留める。

## 参照ドキュメント

- `docs/product-requirements.md` `docs/architecture.md` `docs/development-guidelines.md`
- `d:\ClaudeCode\CLAUDE.md`（プロジェクト索引）
