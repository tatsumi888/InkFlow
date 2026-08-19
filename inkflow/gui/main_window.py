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

from .. import APP_NAME, builder, buildinfo, composer, imaging, layouts, renderer
from ..errors import InkFlowError
from ..models import (
    PROJECT_SUFFIX,
    ROTATION_LABELS,
    ROTATION_NONE,
    ROTATION_SAME_LABEL,
    ROTATIONS,
    PageSpec,
    Project,
    normalize_optional_bias,
)

# 俯瞰の向きの選択肢。None は「分割コマと同じ」。
OVERVIEW_ROTATION_CHOICES: tuple[int | None, ...] = (None, *ROTATIONS)
from . import shortcut_presets
from .page_view import PageOverlay, PageView
from .settings_dialog import BookSettingsDialog
from .worker import BuildWorker

PREVIEW_DPI = 110

# 分割位置の微調整パネルで、[－]/[＋] 1クリックあたり動かす量。
DIVIDER_BIAS_STEP = 0.01

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
R                  分割コマの縦横入替（なし → 右90° → 左90°）
Shift+R            ページ全体（俯瞰）の縦横入替（分割と同じ → なし → 右90° → 左90°）
A S D F G          ショートカットプリセットを適用（右パネルに内容を常時表示）
Z X C V B          いまのページの設定をショートカットプリセットへ保存（同じ列がA↔Z等の対）
Ctrl+N             新規プロジェクト
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
        # ファイル選択ダイアログで最後に実際に使われたフォルダ。
        # 記事PDF追加・プロジェクト保存・EPUB出力の3つで共有する。
        self._last_browsed_dir: Path | None = None
        # 直近のプレビューで実際に使われた分割線オフセット（自動検出結果を含む）。
        # サイドパネルのラベル表示に使う。_update_preview() の直後に必ず更新される。
        self._current_divider_offsets: tuple[dict[float, float], dict[float, float]] = ({}, {})
        # ショートカットプリセット（キー → 保存済みの分割設定）。アプリ全体の設定
        # として %APPDATA%\InkFlow\config.json から読み込む（プロジェクトとは無関係）。
        self._shortcut_presets: dict[str, PageSpec | None] = shortcut_presets.load_presets()

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
        group_layout.addWidget(QLabel("縦横入替 — 分割コマ  [R]"))
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

        group_layout.addWidget(QLabel("縦横入替 — ページ全体（俯瞰）  [Shift+R]"))
        overview_row = QWidget()
        overview_layout = QHBoxLayout(overview_row)
        overview_layout.setContentsMargins(0, 0, 0, 0)
        self.overview_rotation_group = QButtonGroup(self)
        self.overview_rotation_buttons: dict[int, QRadioButton] = {}
        for index, rotation in enumerate(OVERVIEW_ROTATION_CHOICES):
            label = (
                ROTATION_SAME_LABEL if rotation is None else ROTATION_LABELS[rotation]
            )
            button = QRadioButton(label)
            button.setToolTip(
                "俯瞰と分割コマで望ましい向きが逆になる誌面がある"
                "（A4横を左右に割ると、俯瞰は回した方が大きく、コマは回さない方が大きい）。"
            )
            # QButtonGroup の id は int しか使えないので、選択肢の並び順を id にする。
            self.overview_rotation_group.addButton(button, index)
            self.overview_rotation_buttons[index] = button
            overview_layout.addWidget(button)
        overview_layout.addStretch(1)
        self.overview_rotation_group.idToggled.connect(self._on_overview_rotation_selected)
        group_layout.addWidget(overview_row)

        group_layout.addSpacing(6)
        group_layout.addWidget(QLabel("分割位置の微調整"))
        self.column_bias_row, self.column_bias_buttons, self.column_bias_label = (
            self._build_bias_row(
                "左右",
                "2段組などの分割線が本文の途中を切ってしまう場合に使う（既定は既定位置に固定）。"
                "［自動］を押すとそのページだけ余白の自動検出を試す。"
                "［既定］は自動検出を止めて既定位置に固定し直す。",
                lambda: self.adjust_column_bias(-DIVIDER_BIAS_STEP),
                self.reset_column_bias,
                self.pin_column_bias_to_default,
                lambda: self.adjust_column_bias(DIVIDER_BIAS_STEP),
            )
        )
        group_layout.addWidget(self.column_bias_row)
        self.row_bias_row, self.row_bias_buttons, self.row_bias_label = self._build_bias_row(
            "上下",
            "上下2分割・3分割などの分割線がずれる場合に使う。",
            lambda: self.adjust_row_bias(-DIVIDER_BIAS_STEP),
            self.reset_row_bias,
            self.pin_row_bias_to_default,
            lambda: self.adjust_row_bias(DIVIDER_BIAS_STEP),
        )
        group_layout.addWidget(self.row_bias_row)
        layout.addWidget(group)

        preset_group = QGroupBox("ショートカットプリセット")
        preset_layout = QVBoxLayout(preset_group)
        self.shortcut_preset_labels: dict[str, QLabel] = {}
        for apply_key, save_key in zip(
            shortcut_presets.APPLY_KEYS, shortcut_presets.SAVE_KEYS
        ):
            label = QLabel("—")
            label.setWordWrap(True)
            label.setToolTip(
                f"適用: {apply_key}　保存: {save_key}（いまのページの設定で上書き）"
            )
            self.shortcut_preset_labels[apply_key] = label
            preset_layout.addWidget(label)
        layout.addWidget(preset_group)

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

    @staticmethod
    def _build_bias_row(
        axis_label: str,
        tooltip: str,
        on_minus,
        on_auto,
        on_default,
        on_plus,
    ) -> tuple[QWidget, tuple[QToolButton, QToolButton, QToolButton, QToolButton], QLabel]:
        """「左右」「上下」の分割位置微調整に使う [－][自動][既定][＋] + 現在値ラベルの1行。"""
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(QLabel(axis_label))

        minus_button = QToolButton()
        minus_button.setText("－")
        minus_button.setToolTip(tooltip)
        minus_button.clicked.connect(on_minus)
        auto_button = QToolButton()
        auto_button.setText("自動")
        auto_button.setToolTip("余白の自動検出を有効にする（見つかればそこへ寄せる）")
        auto_button.clicked.connect(on_auto)
        default_button = QToolButton()
        default_button.setText("既定")
        default_button.setToolTip("既定位置（オフセット無し）に固定する")
        default_button.clicked.connect(on_default)
        plus_button = QToolButton()
        plus_button.setText("＋")
        plus_button.setToolTip(tooltip)
        plus_button.clicked.connect(on_plus)
        for button in (minus_button, auto_button, default_button, plus_button):
            row_layout.addWidget(button)

        label = QLabel("—")
        row_layout.addWidget(label)
        row_layout.addStretch(1)
        return row, (minus_button, auto_button, default_button, plus_button), label

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("ファイル(&F)")
        self._add_action(file_menu, "新規プロジェクト…", self.new_project, QKeySequence.StandardKey.New)
        file_menu.addSeparator()
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
        self._add_action(help_menu, "バージョン情報…", self.show_about)

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
            ("Shift+R", self.cycle_overview_rotation),
            ("Enter", self.apply_same_as_previous),
        ):
            action = QAction(self)
            action.setShortcut(key)
            action.triggered.connect(slot)
            self.addAction(action)

        for apply_key in shortcut_presets.APPLY_KEYS:
            action = QAction(self)
            action.setShortcut(apply_key)
            action.triggered.connect(lambda _=False, k=apply_key: self.apply_shortcut_preset(k))
            self.addAction(action)
        # 保存キーは、同じ列の適用キー（＝スロットの識別子）へ紐付ける。
        # 例: Z を押したら "Z" ではなく対応するスロット "A" へ保存する。
        for slot_key, save_key in zip(shortcut_presets.APPLY_KEYS, shortcut_presets.SAVE_KEYS):
            action = QAction(self)
            action.setShortcut(save_key)
            action.triggered.connect(lambda _=False, k=slot_key: self.save_shortcut_preset(k))
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
        self._update_shortcut_preset_panel()

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
        # 俯瞰の向きは、分割コマと違うときだけ出す（行が長くなりすぎないように）。
        # 「＋全体」は俯瞰を出す印なので、向きの方は「俯瞰」と書いて区別する。
        if spec.rotate_overview is not None and spec.rotate_overview != spec.rotate:
            rotation += f"・俯瞰{spec.overview_rotation_label()}"
        return (
            f"　{page_index + 1}ページ目 — {layout_def.label.split('（')[0]}{overview}"
            f"{rotation}（{spec.output_page_count()}枚）"
        )

    @staticmethod
    def _preset_summary_text(spec: PageSpec) -> str:
        """ショートカットプリセットの内容を1行で表す（ページ番号や枚数は含めない）。"""
        layout_def = layouts.get_layout(spec.layout_id)
        overview = "＋俯瞰" if spec.include_overview and layout_def.id != "full" else ""
        rotation = f"・{spec.rotation_label()}" if spec.rotate != ROTATION_NONE else ""
        return f"{layout_def.label.split('（')[0]}{overview}{rotation}"

    def _update_shortcut_preset_panel(self) -> None:
        for apply_key, save_key in zip(shortcut_presets.APPLY_KEYS, shortcut_presets.SAVE_KEYS):
            spec = self._shortcut_presets.get(apply_key)
            summary = self._preset_summary_text(spec) if spec is not None else "未設定"
            self.shortcut_preset_labels[apply_key].setText(f"{apply_key}: {summary}")

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
            self._current_divider_offsets = ({}, {})
            return

        article_index, page_index = self._flat[self._current]
        article = self.project.articles[article_index]
        spec = article.pages[page_index]

        overview_rotation = spec.effective_overview_rotation()
        rotation_note = ""
        if spec.rotate != ROTATION_NONE or overview_rotation != ROTATION_NONE:
            if overview_rotation == spec.rotate:
                rotation_note = f"　縦横入替: {spec.rotation_label()}"
            else:
                rotation_note = (
                    f"　縦横入替: 分割 {spec.rotation_label()} / "
                    f"俯瞰 {ROTATION_LABELS[overview_rotation]}"
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
            self._current_divider_offsets = ({}, {})
            return

        # 実際の出力と同じ resolve_divider_offsets() を通す。プレビューの枠と
        # 出力結果が一致することを保証するため（自動検出の結果もここで分かる）。
        content_image = imaging.crop_relative(image, content_rect)
        x_offsets, y_offsets = composer.resolve_divider_offsets(
            content_image, spec.layout_id, spec.column_bias, spec.row_bias
        )
        self._current_divider_offsets = (x_offsets, y_offsets)

        rects = composer.preview_rects(spec, self.project.defaults, x_offsets, y_offsets)
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
                overview_rotation_label=(
                    ROTATION_LABELS[overview_rotation]
                    if (spec.include_overview or is_full)
                    and overview_rotation != spec.rotate
                    else ""
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
        for button in self.overview_rotation_buttons.values():
            button.setEnabled(enabled)
        self.overview_check.setEnabled(enabled)
        for button in (*self.column_bias_buttons, *self.row_bias_buttons):
            button.setEnabled(enabled)
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

        # 俯瞰を出力しないページでは、俯瞰の向きは効かないので触れないようにする。
        shows_overview = spec.include_overview or spec.layout_id == "full"
        overview_index = (
            OVERVIEW_ROTATION_CHOICES.index(spec.rotate_overview)
            if spec.rotate_overview in OVERVIEW_ROTATION_CHOICES
            else 0
        )
        self.overview_rotation_group.blockSignals(True)
        self.overview_rotation_buttons[overview_index].setChecked(True)
        self.overview_rotation_group.blockSignals(False)
        for button in self.overview_rotation_buttons.values():
            button.setEnabled(shows_overview)

        xs, ys = layouts.internal_dividers(spec.layout_id)
        x_offsets, y_offsets = self._current_divider_offsets
        for button in self.column_bias_buttons:
            button.setEnabled(bool(xs))
        self.column_bias_label.setText(self._bias_label_text(spec.column_bias, xs, x_offsets))
        for button in self.row_bias_buttons:
            button.setEnabled(bool(ys))
        self.row_bias_label.setText(self._bias_label_text(spec.row_bias, ys, y_offsets))

    @staticmethod
    def _bias_label_text(
        bias: float | None, dividers: tuple[float, ...], offsets: dict[float, float]
    ) -> str:
        """分割位置微調整の現在値ラベル。手動値、または自動検出の結果を表示する。

        複数の分割線を持つレイアウト（six_2col など）でも、手動値は全線に一律
        適用されるので代表として先頭の分割線だけを見れば足りる。自動検出も、
        各線が同じ余白帯を見つけていることが多いページ想定で先頭を代表値とする。
        """
        if not dividers:
            return "—"
        if bias is not None:
            if bias == 0.0:
                return "既定位置に固定"
            return f"手動 {bias * 100:+.1f}%"
        detected = offsets.get(dividers[0])
        if detected is None:
            return "自動（既定位置）"
        return f"自動（{detected * 100:+.1f}%）"

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

    def set_overview_rotation(self, rotation: int | None) -> None:
        spec = self._current_spec()
        if spec is None or rotation not in OVERVIEW_ROTATION_CHOICES:
            return
        if spec.rotate_overview == rotation and (
            spec.rotate_overview is not None or rotation is None
        ):
            return
        self._set_current_spec(replace(spec, rotate_overview=rotation))

    def cycle_overview_rotation(self) -> None:
        """分割と同じ → なし → 右90° → 左90° → 分割と同じ と巡回する。"""
        spec = self._current_spec()
        if spec is None:
            return
        current = spec.rotate_overview
        position = (
            OVERVIEW_ROTATION_CHOICES.index(current)
            if current in OVERVIEW_ROTATION_CHOICES
            else 0
        )
        self.set_overview_rotation(
            OVERVIEW_ROTATION_CHOICES[(position + 1) % len(OVERVIEW_ROTATION_CHOICES)]
        )

    def adjust_column_bias(self, delta: float) -> None:
        spec = self._current_spec()
        if spec is None:
            return
        xs, _ = layouts.internal_dividers(spec.layout_id)
        if not xs:
            return
        base = spec.column_bias if spec.column_bias is not None else 0.0
        self._set_current_spec(replace(spec, column_bias=normalize_optional_bias(base + delta)))

    def reset_column_bias(self) -> None:
        spec = self._current_spec()
        if spec is None or spec.column_bias is None:
            return
        self._set_current_spec(replace(spec, column_bias=None))

    def pin_column_bias_to_default(self) -> None:
        """自動検出も行わず、レイアウトの既定位置（オフセット無し）に固定する。"""
        spec = self._current_spec()
        if spec is None or spec.column_bias == 0.0:
            return
        self._set_current_spec(replace(spec, column_bias=0.0))

    def adjust_row_bias(self, delta: float) -> None:
        spec = self._current_spec()
        if spec is None:
            return
        _, ys = layouts.internal_dividers(spec.layout_id)
        if not ys:
            return
        base = spec.row_bias if spec.row_bias is not None else 0.0
        self._set_current_spec(replace(spec, row_bias=normalize_optional_bias(base + delta)))

    def reset_row_bias(self) -> None:
        spec = self._current_spec()
        if spec is None or spec.row_bias is None:
            return
        self._set_current_spec(replace(spec, row_bias=None))

    def pin_row_bias_to_default(self) -> None:
        """自動検出も行わず、レイアウトの既定位置（オフセット無し）に固定する。"""
        spec = self._current_spec()
        if spec is None or spec.row_bias == 0.0:
            return
        self._set_current_spec(replace(spec, row_bias=0.0))

    def apply_shortcut_preset(self, key: str) -> None:
        """キーに保存済みの分割設定を、いま見ているページへ適用する。"""
        spec = self._current_spec()
        if spec is None:
            return
        preset = self._shortcut_presets.get(key)
        if preset is None:
            self.statusBar().showMessage(f"プリセット {key} には設定が保存されていません", 3000)
            return
        self._set_current_spec(replace(preset))
        self.statusBar().showMessage(f"プリセット {key} の設定を適用しました", 2000)

    def save_shortcut_preset(self, key: str) -> None:
        """いま見ているページの分割設定を、プリセットスロットへ上書き保存する。

        ``key`` は保存キー自体（Z等）ではなく、対応する適用キー（A等）で
        呼ばれる想定。呼び出し元（_build_shortcuts）でその対応付けをしている。
        """
        spec = self._current_spec()
        if spec is None:
            return
        self._shortcut_presets[key] = replace(spec)
        shortcut_presets.save_presets(self._shortcut_presets)
        self._update_shortcut_preset_panel()
        self.statusBar().showMessage(f"現在の設定をプリセット {key} に保存しました", 3000)

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

    def _on_overview_rotation_selected(self, index: int, checked: bool) -> None:
        if checked and 0 <= index < len(OVERVIEW_ROTATION_CHOICES):
            self.set_overview_rotation(OVERVIEW_ROTATION_CHOICES[index])

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

    def add_pdfs(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "記事PDFを選ぶ", self._default_dialog_dir(), PDF_FILTER
        )
        if paths:
            self._remember_dialog_dir(paths[0])
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

    def new_project(self) -> None:
        """作業中のプロジェクトを、次の号のために白紙へ作り直す。

        「本の設定」ダイアログをそのまま流用する。専用ダイアログを別に作らないのは、
        雑誌名・号・端末の入力欄が既にそこに揃っているため。ダイアログをキャンセル
        したときに現在のプロジェクトを壊さないよう、``self.project`` を差し替える
        のは Accepted を確認した後にする。
        """
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
        self._last_browsed_dir = None
        self._mark_dirty(False)
        self.refresh_all()
        self.statusBar().showMessage("新規プロジェクトを作成しました", 4000)

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
        self._activate_project(project)

    def open_dropped_project(self, path: Path) -> None:
        """D&D で渡されたプロジェクトファイルを、内容確認とユーザー確認を経て開く。

        ドラッグ＆ドロップは［プロジェクトを開く］メニューより誤操作が起きやすい
        ジェスチャーなので、まず内容（JSON構造・参照PDFの存在）を検証し、問題が
        無ければタイトルや記事数を示して改めて確認を取ってから開く。
        """
        try:
            project = Project.load(path)
            project.validate_sources()
            composer.sync_page_counts(project)
        except InkFlowError as e:
            QMessageBox.critical(self, "開けません", str(e))
            return

        page_count = sum(len(a.pages) for a in project.articles)
        answer = QMessageBox.question(
            self,
            "プロジェクトを開く",
            f"「{project.book_title()}」を開きますか？\n"
            f"（記事 {len(project.articles)} 本 / 原稿 {page_count} ページ）",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if not self._confirm_discard_changes():
            return
        self._activate_project(project)

    def _activate_project(self, project: Project) -> None:
        """読み込んだプロジェクトを現在のプロジェクトとして差し替え、画面を更新する。"""
        self.project = project
        self.preview_cache.invalidate()
        self._current = 0
        self._last_browsed_dir = None
        self._mark_dirty(False)
        self.refresh_all()

    def save_project(self) -> bool:
        if self.project.project_path is None:
            return self.save_project_as()
        return self._save_to(self.project.project_path)

    def save_project_as(self) -> bool:
        if self.project.project_path:
            suggested = self.project.project_path
        else:
            filename = f"{self.project.book_title() or 'inkflow'}{PROJECT_SUFFIX}"
            default_dir = self._default_dialog_dir()
            suggested = Path(default_dir) / filename if default_dir else Path(filename)
        path, _ = QFileDialog.getSaveFileName(
            self, "プロジェクトを保存", str(suggested), PROJECT_FILTER
        )
        if not path:
            return False
        self._remember_dialog_dir(path)
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

        if self.project.project_path:
            suggested = builder.default_output_path(self.project)
        else:
            default_dir = self._default_dialog_dir()
            suggested = builder.default_output_path(
                self.project, Path(default_dir) if default_dir else None
            )
        path, _ = QFileDialog.getSaveFileName(
            self, "EPUBの保存先", str(suggested), "EPUB (*.epub)"
        )
        if not path:
            return
        self._remember_dialog_dir(path)

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

    def show_about(self) -> None:
        QMessageBox.information(self, "バージョン情報", buildinfo.describe())

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
        if self._pdf_paths_from(event) or self._project_path_from(event) is not None:
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        # プロジェクトファイルを優先する。PDFと同時にドロップされた場合、
        # プロジェクトを開くと現在の内容ごと差し替わるので、PDF追加は意味を失う。
        project_path = self._project_path_from(event)
        if project_path is not None:
            self.open_dropped_project(project_path)
            event.acceptProposedAction()
            return
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

    @staticmethod
    def _project_path_from(event) -> Path | None:
        mime = event.mimeData()
        if not mime.hasUrls():
            return None
        for url in mime.urls():
            if not url.isLocalFile():
                continue
            path = Path(url.toLocalFile())
            if path.suffix.lower() == ".json":
                return path
        return None
