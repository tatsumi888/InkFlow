"""InkFlow のメインウィンドウ。

40ページぶんを流し見て、**例外ページだけ触る**運用を想定している。そのため
既定レイアウトは追加時に全ページへ適用済みで、ユーザーの操作は
「ページを送る」「たまにレイアウトを変える」の2つに収束する。
キーボードだけで一周できるようにしてあるのはそのため。
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QRadioButton,
    QSplitter,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, builder, composer, layouts, renderer
from ..errors import InkFlowError
from ..models import (
    PROJECT_SUFFIX,
    ROTATION_LABELS,
    ROTATION_NONE,
    ROTATIONS,
    PageSpec,
    Project,
)
from .page_view import PageOverlay, PageView
from .settings_dialog import BookSettingsDialog
from .worker import BuildWorker

PREVIEW_DPI = 110

# Send to Kindle のメール添付の上限と、超えたときの対処。
SIZE_WARNING_MB = 50
SIZE_ADVICE = (
    "50MB を超えました。Send to Kindle のメール添付では送れません。\n"
    "USB接続で転送するか、［本の設定］で階調数を4に下げてください"
    "（文字主体ならほぼ見た目は変わらず、サイズは半分程度になります）。\n"
    "俯瞰ページを外すのも約25%の削減になります。"
)

ROLE_KIND = Qt.ItemDataRole.UserRole
ROLE_ARTICLE = Qt.ItemDataRole.UserRole + 1
ROLE_PAGE = Qt.ItemDataRole.UserRole + 2

PDF_FILTER = "PDF ファイル (*.pdf)"
PROJECT_FILTER = f"InkFlow プロジェクト (*{PROJECT_SUFFIX});;JSON (*.json)"

SHORTCUT_HELP = """\
←  /  Backspace    前のページ
→  /  Space        次のページ
1 〜 7             分割レイアウトを選ぶ
Enter              前ページと同じ設定にして次へ
O                  ページ全体（俯瞰）の有無を切り替え
R                  縦横入替（なし → 右90° → 左90°）
Ctrl+O             PDFを追加
Ctrl+S             プロジェクトを保存
Ctrl+E             EPUBを出力
"""


class MainWindow(QMainWindow):
    def __init__(self, project: Project | None = None) -> None:
        super().__init__()
        self.project = project or Project()
        self.preview_cache = renderer.PreviewCache()
        self._flat: list[tuple[int, int]] = []
        self._current = 0
        self._dirty = False
        self._worker: BuildWorker | None = None
        self._progress_dialog: QProgressDialog | None = None

        self.setWindowTitle(APP_NAME)
        self.resize(1180, 820)
        self.setAcceptDrops(True)

        self._build_ui()
        self._build_menu()
        self._build_shortcuts()
        self.refresh_all()

    # ---- UI 構築 ------------------------------------------------------

    def _build_ui(self) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_center_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([280, 620, 280])
        self.setCentralWidget(splitter)
        self.statusBar().showMessage("PDFを追加してください")

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 4, 8)
        layout.addWidget(QLabel("<b>記事（この順で1冊になります）</b>"))

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setItemsExpandable(False)
        self.tree.setRootIsDecorated(False)
        self.tree.setIndentation(14)
        self.tree.currentItemChanged.connect(self._on_tree_current_changed)
        self.tree.itemDoubleClicked.connect(self._on_tree_double_clicked)
        layout.addWidget(self.tree, 1)

        buttons = QHBoxLayout()
        for text, tooltip, slot in (
            ("追加", "PDFを記事として追加", self.add_pdfs),
            ("削除", "選択中の記事を取り除く", self.remove_article),
            ("↑", "記事を前へ", lambda: self.move_article(-1)),
            ("↓", "記事を後ろへ", lambda: self.move_article(1)),
            ("名前", "しおり名（記事タイトル）を変える", self.rename_article),
        ):
            button = QToolButton()
            button.setText(text)
            button.setToolTip(tooltip)
            button.clicked.connect(slot)
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        return panel

    def _build_center_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(4, 8, 4, 8)

        self.page_label = QLabel("—")
        self.page_label.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.page_label)

        self.page_view = PageView()
        layout.addWidget(self.page_view, 1)

        nav = QHBoxLayout()
        previous_button = QPushButton("◀ 前のページ")
        previous_button.clicked.connect(self.previous_page)
        next_button = QPushButton("次のページ ▶")
        next_button.clicked.connect(self.next_page)
        self.position_label = QLabel("0 / 0")
        nav.addWidget(previous_button)
        nav.addStretch(1)
        nav.addWidget(self.position_label)
        nav.addStretch(1)
        nav.addWidget(next_button)
        layout.addLayout(nav)
        return panel

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(4, 8, 8, 8)

        group = QGroupBox("このページの分割")
        group_layout = QVBoxLayout(group)
        self.layout_group = QButtonGroup(self)
        self.layout_buttons: list[QRadioButton] = []
        for index, layout_def in enumerate(layouts.LAYOUTS):
            hint = f"  [{index + 1}]" if index < 9 else ""
            button = QRadioButton(f"{layout_def.label}{hint}")
            button.setToolTip(layout_def.hint)
            self.layout_group.addButton(button, index)
            self.layout_buttons.append(button)
            group_layout.addWidget(button)
        self.layout_group.idToggled.connect(self._on_layout_selected)

        self.overview_check = QCheckBox("ページ全体（俯瞰）も出力する  [O]")
        self.overview_check.setToolTip(
            "分割コマの前に、ページ全体を1枚入れる。誌面の構成を把握してから読める。"
        )
        self.overview_check.toggled.connect(self._on_overview_toggled)
        group_layout.addSpacing(6)
        group_layout.addWidget(self.overview_check)

        group_layout.addSpacing(6)
        group_layout.addWidget(QLabel("縦横入替  [R]"))
        rotation_row = QWidget()
        rotation_layout = QHBoxLayout(rotation_row)
        rotation_layout.setContentsMargins(0, 0, 0, 0)
        self.rotation_group = QButtonGroup(self)
        self.rotation_buttons: dict[int, QRadioButton] = {}
        for rotation in ROTATIONS:
            button = QRadioButton(ROTATION_LABELS[rotation])
            button.setToolTip(
                "上下2分割など横長のコマは、回して端末を横向きに持つと文字が大きくなる。"
                "縦長のコマ（二段組4分割など）では逆に小さくなる。"
            )
            self.rotation_group.addButton(button, rotation)
            self.rotation_buttons[rotation] = button
            rotation_layout.addWidget(button)
        rotation_layout.addStretch(1)
        self.rotation_group.idToggled.connect(self._on_rotation_selected)
        group_layout.addWidget(rotation_row)
        layout.addWidget(group)

        apply_group = QGroupBox("まとめて適用")
        apply_layout = QVBoxLayout(apply_group)
        for text, tooltip, slot in (
            ("前ページと同じ  [Enter]", "ひとつ前のページの設定を複製して次へ進む",
             self.apply_same_as_previous),
            ("この記事の全ページに適用", "現在の設定を、この記事の全ページへ広げる",
             self.apply_to_article),
            ("全ページに適用", "現在の設定を、すべての記事の全ページへ広げる",
             self.apply_to_all),
        ):
            button = QPushButton(text)
            button.setToolTip(tooltip)
            button.clicked.connect(slot)
            apply_layout.addWidget(button)
        layout.addWidget(apply_group)

        self.summary_label = QLabel("—")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)
        layout.addStretch(1)

        export_button = QPushButton("EPUBを出力  [Ctrl+E]")
        export_button.clicked.connect(self.export_epub)
        layout.addWidget(export_button)
        return panel

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("ファイル(&F)")
        self._add_action(file_menu, "PDFを追加…", self.add_pdfs, QKeySequence.StandardKey.Open)
        file_menu.addSeparator()
        self._add_action(file_menu, "プロジェクトを開く…", self.open_project, "Ctrl+Shift+O")
        self._add_action(file_menu, "プロジェクトを保存", self.save_project, QKeySequence.StandardKey.Save)
        self._add_action(file_menu, "名前を付けて保存…", self.save_project_as, "Ctrl+Shift+S")
        file_menu.addSeparator()
        self._add_action(file_menu, "EPUBを出力…", self.export_epub, "Ctrl+E")
        file_menu.addSeparator()
        self._add_action(file_menu, "終了", self.close, QKeySequence.StandardKey.Quit)

        edit_menu = self.menuBar().addMenu("編集(&E)")
        self._add_action(edit_menu, "本の設定…", self.open_settings, "Ctrl+,")
        edit_menu.addSeparator()
        self._add_action(edit_menu, "前ページと同じ", self.apply_same_as_previous, "Return")
        self._add_action(edit_menu, "この記事の全ページに適用", self.apply_to_article)
        self._add_action(edit_menu, "全ページに適用", self.apply_to_all)

        go_menu = self.menuBar().addMenu("移動(&G)")
        self._add_action(go_menu, "前のページ", self.previous_page, "Left")
        self._add_action(go_menu, "次のページ", self.next_page, "Right")

        help_menu = self.menuBar().addMenu("ヘルプ(&H)")
        self._add_action(help_menu, "キー操作…", self.show_shortcut_help, "F1")

    def _build_shortcuts(self) -> None:
        """メニューに載せないキー（数字キーなど）。"""
        for index in range(min(9, len(layouts.LAYOUTS))):
            action = QAction(self)
            action.setShortcut(str(index + 1))
            action.triggered.connect(lambda _=False, i=index: self.select_layout(i))
            self.addAction(action)

        for key, slot in (
            ("Space", self.next_page),
            ("Backspace", self.previous_page),
            ("O", self.toggle_overview),
            ("R", self.cycle_rotation),
            ("Enter", self.apply_same_as_previous),
        ):
            action = QAction(self)
            action.setShortcut(key)
            action.triggered.connect(slot)
            self.addAction(action)

    def _add_action(self, menu, text: str, slot, shortcut=None) -> QAction:
        action = QAction(text, self)
        if shortcut is not None:
            action.setShortcut(shortcut)
        action.triggered.connect(slot)
        menu.addAction(action)
        return action

    # ---- 状態の更新 ---------------------------------------------------

    def refresh_all(self) -> None:
        self._rebuild_flat()
        self._rebuild_tree()
        self._update_preview()
        self._update_side_panel()
        self._update_summary()

    def _rebuild_flat(self) -> None:
        self._flat = [
            (article_index, page_index)
            for article_index, article in enumerate(self.project.articles)
            for page_index in range(len(article.pages))
        ]
        self._current = max(0, min(self._current, len(self._flat) - 1))

    def _rebuild_tree(self) -> None:
        self.tree.blockSignals(True)
        self.tree.clear()
        for article_index, article in enumerate(self.project.articles):
            parent = QTreeWidgetItem(self.tree)
            parent.setText(0, f"{article_index + 1}. {article.title}（{len(article.pages)}ページ）")
            parent.setData(0, ROLE_KIND, "article")
            parent.setData(0, ROLE_ARTICLE, article_index)
            for page_index, spec in enumerate(article.pages):
                child = QTreeWidgetItem(parent)
                child.setText(0, self._page_item_text(page_index, spec))
                child.setData(0, ROLE_KIND, "page")
                child.setData(0, ROLE_ARTICLE, article_index)
                child.setData(0, ROLE_PAGE, page_index)
            parent.setExpanded(True)
        self.tree.blockSignals(False)
        self._select_current_in_tree()

    @staticmethod
    def _page_item_text(page_index: int, spec: PageSpec) -> str:
        layout_def = layouts.get_layout(spec.layout_id)
        overview = "＋全体" if spec.include_overview and layout_def.id != "full" else ""
        rotation = f"・{spec.rotation_label()}" if spec.rotate != ROTATION_NONE else ""
        return (
            f"　{page_index + 1}ページ目 — {layout_def.label.split('（')[0]}{overview}"
            f"{rotation}（{spec.output_page_count()}枚）"
        )

    def _select_current_in_tree(self) -> None:
        if not self._flat:
            return
        article_index, page_index = self._flat[self._current]
        parent = self.tree.topLevelItem(article_index)
        if parent is None:
            return
        item = parent.child(page_index)
        if item is None:
            return
        self.tree.blockSignals(True)
        self.tree.setCurrentItem(item)
        self.tree.blockSignals(False)

    def _current_article_index(self) -> int | None:
        if not self._flat:
            return None
        return self._flat[self._current][0]

    def _current_spec(self) -> PageSpec | None:
        if not self._flat:
            return None
        article_index, page_index = self._flat[self._current]
        return self.project.articles[article_index].pages[page_index]

    def _set_current_spec(self, spec: PageSpec) -> None:
        if not self._flat:
            return
        article_index, page_index = self._flat[self._current]
        self.project.articles[article_index].pages[page_index] = spec
        self._mark_dirty()
        self._refresh_current_tree_item()
        self._update_preview()
        self._update_side_panel()
        self._update_summary()

    def _refresh_current_tree_item(self) -> None:
        if not self._flat:
            return
        article_index, page_index = self._flat[self._current]
        parent = self.tree.topLevelItem(article_index)
        if parent is None:
            return
        item = parent.child(page_index)
        if item is not None:
            spec = self.project.articles[article_index].pages[page_index]
            item.setText(0, self._page_item_text(page_index, spec))

    def _update_preview(self) -> None:
        if not self._flat:
            self.page_view.clear("PDFを追加してください（ドラッグ＆ドロップでも追加できます）")
            self.page_label.setText("—")
            self.position_label.setText("0 / 0")
            return

        article_index, page_index = self._flat[self._current]
        article = self.project.articles[article_index]
        spec = article.pages[page_index]

        rotation_note = (
            f"　縦横入替: {spec.rotation_label()}" if spec.rotate != ROTATION_NONE else ""
        )
        self.page_label.setText(
            f"<b>{article.title}</b>　"
            f"（記事 {article_index + 1}/{len(self.project.articles)}・"
            f"{page_index + 1}/{len(article.pages)} ページ目）{rotation_note}"
        )
        self.position_label.setText(f"{self._current + 1} / {len(self._flat)}")

        try:
            image = self.preview_cache.render(article.path, page_index, PREVIEW_DPI)
            content_rect = composer.content_rect_for(
                self.preview_cache, article.path, page_index, self.project.defaults
            )
        except InkFlowError as e:
            self.page_view.clear(f"プレビューを表示できません\n{e}")
            return

        rects = composer.preview_rects(spec, self.project.defaults)
        is_full = spec.layout_id == "full"
        self.page_view.set_page(
            image,
            PageOverlay(
                content_rect=content_rect,
                part_rects=rects,
                include_overview=spec.include_overview and not is_full,
                show_trim=self.project.defaults.auto_trim,
                labels=[str(index + 1) for index in range(len(rects))],
                rotation_label=(
                    spec.rotation_label() if spec.rotate != ROTATION_NONE else ""
                ),
            ),
        )

    def _update_side_panel(self) -> None:
        spec = self._current_spec()
        enabled = spec is not None
        for button in self.layout_buttons:
            button.setEnabled(enabled)
        for button in self.rotation_buttons.values():
            button.setEnabled(enabled)
        self.overview_check.setEnabled(enabled)
        if spec is None:
            return

        index = layouts.layout_ids().index(spec.layout_id)
        self.layout_group.blockSignals(True)
        self.layout_buttons[index].setChecked(True)
        self.layout_group.blockSignals(False)

        self.overview_check.blockSignals(True)
        self.overview_check.setChecked(spec.include_overview)
        self.overview_check.setEnabled(spec.layout_id != "full")
        self.overview_check.blockSignals(False)

        self.rotation_group.blockSignals(True)
        self.rotation_buttons[spec.rotate].setChecked(True)
        self.rotation_group.blockSignals(False)

    def _update_summary(self) -> None:
        source_pages = sum(len(a.pages) for a in self.project.articles)
        output_pages = self.project.output_page_count()
        self.summary_label.setText(
            f"<b>{self.project.book_title()}</b><br>"
            f"記事 {len(self.project.articles)} 本 / 原稿 {source_pages} ページ<br>"
            f"出力 {output_pages} ページ（表紙を含めて {output_pages + 1}）<br>"
            f"端末 {self.project.device().width}×{self.project.device().height}"
        )
        self.statusBar().showMessage(
            f"{self.project.book_title()}　—　出力 {output_pages} ページ"
            + ("　*未保存" if self._dirty else "")
        )

    def _mark_dirty(self, dirty: bool = True) -> None:
        self._dirty = dirty
        title = f"{APP_NAME} — {self.project.book_title()}"
        self.setWindowTitle(title + (" *" if dirty else ""))

    # ---- ページ操作 ---------------------------------------------------

    def next_page(self) -> None:
        if self._flat and self._current < len(self._flat) - 1:
            self._current += 1
            self._select_current_in_tree()
            self._update_preview()
            self._update_side_panel()

    def previous_page(self) -> None:
        if self._flat and self._current > 0:
            self._current -= 1
            self._select_current_in_tree()
            self._update_preview()
            self._update_side_panel()

    def select_layout(self, index: int) -> None:
        if not self._flat or not 0 <= index < len(layouts.LAYOUTS):
            return
        spec = self._current_spec()
        assert spec is not None
        # replace() を使うのは、設定項目が増えたときに取りこぼさないため。
        self._set_current_spec(replace(spec, layout_id=layouts.LAYOUTS[index].id))

    def toggle_overview(self) -> None:
        spec = self._current_spec()
        if spec is None or spec.layout_id == "full":
            return
        self._set_current_spec(replace(spec, include_overview=not spec.include_overview))

    def set_rotation(self, rotation: int) -> None:
        spec = self._current_spec()
        if spec is None or rotation not in ROTATIONS or spec.rotate == rotation:
            return
        self._set_current_spec(replace(spec, rotate=rotation))

    def cycle_rotation(self) -> None:
        """なし → 右90° → 左90° → なし と巡回する。"""
        spec = self._current_spec()
        if spec is None:
            return
        position = ROTATIONS.index(spec.rotate) if spec.rotate in ROTATIONS else 0
        self.set_rotation(ROTATIONS[(position + 1) % len(ROTATIONS)])

    def apply_same_as_previous(self) -> None:
        """ひとつ前のページの設定を複製して、次のページへ進む。"""
        if not self._flat:
            return
        if self._current == 0:
            self.next_page()
            return
        previous_article, previous_page = self._flat[self._current - 1]
        previous = self.project.articles[previous_article].pages[previous_page]
        self._set_current_spec(replace(previous))
        self.next_page()

    def apply_to_article(self) -> None:
        spec = self._current_spec()
        article_index = self._current_article_index()
        if spec is None or article_index is None:
            return
        self.project.apply_layout_to_article(article_index, spec)
        self._mark_dirty()
        self._rebuild_tree()
        self._update_summary()

    def apply_to_all(self) -> None:
        spec = self._current_spec()
        if spec is None:
            return
        self.project.apply_layout_to_all(spec)
        self._mark_dirty()
        self._rebuild_tree()
        self._update_summary()

    def _on_layout_selected(self, index: int, checked: bool) -> None:
        if checked:
            self.select_layout(index)

    def _on_rotation_selected(self, rotation: int, checked: bool) -> None:
        if checked:
            self.set_rotation(rotation)

    def _on_overview_toggled(self, checked: bool) -> None:
        spec = self._current_spec()
        if spec is None or spec.include_overview == checked:
            return
        self._set_current_spec(replace(spec, include_overview=checked))

    def _on_tree_current_changed(self, item: QTreeWidgetItem | None, _previous) -> None:
        if item is None:
            return
        article_index = item.data(0, ROLE_ARTICLE)
        page_index = item.data(0, ROLE_PAGE) or 0
        if article_index is None:
            return
        try:
            self._current = self._flat.index((article_index, page_index))
        except ValueError:
            return
        self._update_preview()
        self._update_side_panel()

    def _on_tree_double_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        if item.data(0, ROLE_KIND) == "article":
            self.rename_article()

    # ---- 記事の操作 ---------------------------------------------------

    def add_pdfs(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "記事PDFを選ぶ", "", PDF_FILTER)
        if paths:
            self.add_pdf_paths([Path(p) for p in paths])

    def add_pdf_paths(self, paths: list[Path]) -> None:
        added = 0
        errors: list[str] = []
        for path in paths:
            try:
                builder.add_article(self.project, path)
                added += 1
            except InkFlowError as e:
                errors.append(str(e))
        if added:
            self._mark_dirty()
            self.refresh_all()
        if errors:
            QMessageBox.warning(self, "追加できないPDFがありました", "\n".join(errors))

    def remove_article(self) -> None:
        index = self._current_article_index()
        if index is None:
            return
        article = self.project.articles[index]
        answer = QMessageBox.question(
            self,
            "記事を取り除く",
            f"「{article.title}」を一覧から取り除きます。PDFファイル自体は削除しません。",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.preview_cache.invalidate(article.path)
        del self.project.articles[index]
        self._mark_dirty()
        self.refresh_all()

    def move_article(self, delta: int) -> None:
        index = self._current_article_index()
        if index is None:
            return
        target = index + delta
        if not 0 <= target < len(self.project.articles):
            return
        articles = self.project.articles
        articles[index], articles[target] = articles[target], articles[index]
        self._mark_dirty()
        self._rebuild_flat()
        # 移動した記事の先頭ページへ追従する。
        self._current = self._flat.index((target, 0))
        self._rebuild_tree()
        self._update_preview()
        self._update_side_panel()
        self._update_summary()

    def rename_article(self) -> None:
        index = self._current_article_index()
        if index is None:
            return
        article = self.project.articles[index]
        title, ok = QInputDialog.getText(
            self, "しおり名を変える", "記事タイトル（目次に出ます）", text=article.title
        )
        if ok and title.strip():
            article.title = title.strip()
            self._mark_dirty()
            self._rebuild_tree()
            self._update_preview()

    # ---- プロジェクト -------------------------------------------------

    def open_settings(self) -> None:
        dialog = BookSettingsDialog(self.project, self)
        if dialog.exec() != BookSettingsDialog.DialogCode.Accepted:
            return
        dialog.apply_to(self.project)
        self._mark_dirty()
        self.preview_cache.invalidate()
        self._update_preview()
        self._update_summary()

    def open_project(self) -> None:
        if not self._confirm_discard_changes():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "プロジェクトを開く", "", PROJECT_FILTER
        )
        if not path:
            return
        try:
            project = Project.load(Path(path))
            composer.sync_page_counts(project)
        except InkFlowError as e:
            QMessageBox.critical(self, "開けません", str(e))
            return
        self.project = project
        self.preview_cache.invalidate()
        self._current = 0
        self._mark_dirty(False)
        self.refresh_all()

    def save_project(self) -> bool:
        if self.project.project_path is None:
            return self.save_project_as()
        return self._save_to(self.project.project_path)

    def save_project_as(self) -> bool:
        suggested = self.project.project_path or Path(
            f"{self.project.book_title() or 'inkflow'}{PROJECT_SUFFIX}"
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "プロジェクトを保存", str(suggested), PROJECT_FILTER
        )
        if not path:
            return False
        return self._save_to(Path(path))

    def _save_to(self, path: Path) -> bool:
        try:
            self.project.save(path)
        except InkFlowError as e:
            QMessageBox.critical(self, "保存できません", str(e))
            return False
        self._mark_dirty(False)
        self._update_summary()
        self.statusBar().showMessage(f"保存しました: {path}", 4000)
        return True

    # ---- EPUB 出力 ----------------------------------------------------

    def export_epub(self) -> None:
        if not self.project.articles:
            QMessageBox.information(self, "出力できません", "先に記事PDFを追加してください。")
            return
        if self._worker is not None:
            return

        suggested = builder.default_output_path(self.project)
        path, _ = QFileDialog.getSaveFileName(
            self, "EPUBの保存先", str(suggested), "EPUB (*.epub)"
        )
        if not path:
            return

        total = self.project.output_page_count()
        dialog = QProgressDialog("EPUBを生成しています…", "中止", 0, total, self)
        dialog.setWindowTitle("EPUB出力")
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.setMinimumDuration(0)
        self._progress_dialog = dialog

        worker = BuildWorker(self.project, Path(path), self)
        worker.progress.connect(self._on_build_progress)
        worker.succeeded.connect(self._on_build_succeeded)
        worker.failed.connect(self._on_build_failed)
        worker.cancelled.connect(self._on_build_cancelled)
        worker.finished.connect(self._on_build_finished)
        dialog.canceled.connect(worker.cancel)
        self._worker = worker
        worker.start()

    def _on_build_progress(self, done: int, total: int) -> None:
        if self._progress_dialog is not None:
            self._progress_dialog.setMaximum(total)
            self._progress_dialog.setValue(done)
            self._progress_dialog.setLabelText(f"EPUBを生成しています…  {done} / {total} ページ")

    def _on_build_succeeded(self, summary) -> None:
        self._close_progress()
        message = (
            f"{summary.path}\n\n"
            f"ページ数: {summary.page_count}（表紙を含む）\n"
            f"しおり  : {summary.bookmark_count} 件\n"
            f"サイズ  : {summary.size_mb:.1f} MB"
        )
        if summary.size_mb > SIZE_WARNING_MB:
            message += f"\n\n{SIZE_ADVICE}"
        QMessageBox.information(self, "EPUBを生成しました", message)

    def _on_build_failed(self, message: str) -> None:
        self._close_progress()
        QMessageBox.critical(self, "生成に失敗しました", message)

    def _on_build_cancelled(self) -> None:
        self._close_progress()
        self.statusBar().showMessage("EPUBの生成を中止しました", 4000)

    def _on_build_finished(self) -> None:
        self._worker = None

    def _close_progress(self) -> None:
        if self._progress_dialog is not None:
            self._progress_dialog.close()
            self._progress_dialog = None

    # ---- ヘルプ・終了 -------------------------------------------------

    def show_shortcut_help(self) -> None:
        QMessageBox.information(self, "キー操作", SHORTCUT_HELP)

    def _confirm_discard_changes(self) -> bool:
        if not self._dirty:
            return True
        answer = QMessageBox.question(
            self,
            "保存しますか？",
            "変更が保存されていません。保存しますか？",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Save:
            return self.save_project()
        return answer == QMessageBox.StandardButton.Discard

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt の命名規則
        if self._worker is not None:
            self._worker.cancel()
            self._worker.wait(3000)
        if not self._confirm_discard_changes():
            event.ignore()
            return
        self.preview_cache.close()
        event.accept()

    # ---- ドラッグ＆ドロップ -------------------------------------------

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if self._pdf_paths_from(event) :
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        paths = self._pdf_paths_from(event)
        if paths:
            self.add_pdf_paths(paths)
            event.acceptProposedAction()

    @staticmethod
    def _pdf_paths_from(event) -> list[Path]:
        mime = event.mimeData()
        if not mime.hasUrls():
            return []
        paths = [Path(url.toLocalFile()) for url in mime.urls() if url.isLocalFile()]
        return [p for p in paths if p.suffix.lower() == ".pdf"]
