"""本の設定（誌名・号・表紙・端末・画像品質）を編集するダイアログ。

ページごとに変えるものは右パネル、号ぜんぶに効くものはここ、という分担にしている。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .. import devices, layouts
from ..models import Project

CUSTOM_DEVICE_LABEL = "カスタム解像度"

# 実測（B5・40ページ・1236x1648・PNG）では 16階調で 33MB、4階調で 17MB。
# 文字主体の誌面では 4 まで落としても見た目はほとんど変わらない。
GRAY_LEVEL_CHOICES = (4, 8, 16, 32, 256)


class BookSettingsDialog(QDialog):
    """プロジェクト全体に効く設定。OK で ``apply_to()`` を呼ぶ。"""

    def __init__(self, project: Project, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("本の設定")
        self.setMinimumWidth(460)
        self._project = project

        layout = QVBoxLayout(self)
        layout.addWidget(self._build_book_group(project))
        layout.addWidget(self._build_device_group(project))
        layout.addWidget(self._build_split_group(project))
        layout.addWidget(self._build_image_group(project))

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._sync_enabled_states()

    # ---- 各グループ ---------------------------------------------------

    def _build_book_group(self, project: Project) -> QGroupBox:
        group = QGroupBox("本")
        form = QFormLayout(group)

        self.title_edit = QLineEdit(project.title)
        self.issue_edit = QLineEdit(project.issue)
        form.addRow("雑誌名", self.title_edit)
        form.addRow("号", self.issue_edit)

        self.cover_edit = QLineEdit(str(project.cover_image) if project.cover_image else "")
        self.cover_edit.setPlaceholderText("未指定なら誌名＋号から自動生成します")
        browse = QPushButton("参照…")
        browse.clicked.connect(self._choose_cover)
        clear = QPushButton("クリア")
        clear.clicked.connect(lambda: self.cover_edit.setText(""))

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(self.cover_edit, 1)
        row_layout.addWidget(browse)
        row_layout.addWidget(clear)
        form.addRow("表紙画像", row)
        return group

    def _build_device_group(self, project: Project) -> QGroupBox:
        group = QGroupBox("出力先の端末")
        form = QFormLayout(group)

        self.device_combo = QComboBox()
        for device in devices.DEVICES:
            self.device_combo.addItem(device.label, device.id)
        self.device_combo.addItem(CUSTOM_DEVICE_LABEL, "custom")

        self.custom_width = QSpinBox()
        self.custom_width.setRange(200, 4000)
        self.custom_height = QSpinBox()
        self.custom_height.setRange(200, 4000)

        current = project.device()
        self.custom_width.setValue(current.width)
        self.custom_height.setValue(current.height)
        index = self.device_combo.findData(project.device_id)
        self.device_combo.setCurrentIndex(index if index >= 0 else self.device_combo.count() - 1)
        self.device_combo.currentIndexChanged.connect(self._sync_enabled_states)

        size_row = QWidget()
        size_layout = QHBoxLayout(size_row)
        size_layout.setContentsMargins(0, 0, 0, 0)
        size_layout.addWidget(self.custom_width)
        size_layout.addWidget(QLabel("×"))
        size_layout.addWidget(self.custom_height)
        size_layout.addStretch(1)

        form.addRow("端末", self.device_combo)
        form.addRow("解像度", size_row)
        return group

    def _build_split_group(self, project: Project) -> QGroupBox:
        group = QGroupBox("分割")
        form = QFormLayout(group)

        self.trim_check = QCheckBox("周囲の白余白を自動で取り除く")
        self.trim_check.setChecked(project.defaults.auto_trim)
        self.trim_check.toggled.connect(self._sync_enabled_states)

        self.trim_threshold = QSpinBox()
        self.trim_threshold.setRange(100, 255)
        self.trim_threshold.setValue(project.defaults.trim_threshold)
        self.trim_threshold.setToolTip("この明るさ以上を余白とみなす（大きいほど控えめにトリム）")

        self.overlap_spin = QDoubleSpinBox()
        self.overlap_spin.setRange(0.0, layouts.MAX_OVERLAP)
        self.overlap_spin.setSingleStep(0.01)
        self.overlap_spin.setDecimals(2)
        self.overlap_spin.setValue(project.defaults.overlap)
        self.overlap_spin.setToolTip("分割線上の行が読めるよう、隣のコマと重ねる割合")

        form.addRow(self.trim_check)
        form.addRow("余白のしきい値", self.trim_threshold)
        form.addRow("コマの重なり", self.overlap_spin)
        return group

    def _build_image_group(self, project: Project) -> QGroupBox:
        group = QGroupBox("画像")
        form = QFormLayout(group)

        self.format_combo = QComboBox()
        self.format_combo.addItem("PNG（文字に強い・既定）", "png")
        self.format_combo.addItem("JPEG（写真が主体の号だけ）", "jpeg")
        self.format_combo.setToolTip(
            "文字主体の誌面では JPEG の方が大きくなる（実測で3倍以上）。"
            "サイズを詰めたいときは階調数を下げる方が効く。"
        )
        index = self.format_combo.findData(project.image.format)
        self.format_combo.setCurrentIndex(max(0, index))
        self.format_combo.currentIndexChanged.connect(self._sync_enabled_states)

        self.jpeg_quality = QSpinBox()
        self.jpeg_quality.setRange(30, 100)
        self.jpeg_quality.setValue(project.image.jpeg_quality)

        self.gray_levels = QComboBox()
        for level in GRAY_LEVEL_CHOICES:
            self.gray_levels.addItem(f"{level} 階調", level)
        level_index = self.gray_levels.findData(project.image.gray_levels)
        self.gray_levels.setCurrentIndex(level_index if level_index >= 0 else 0)

        self.gamma_spin = QDoubleSpinBox()
        self.gamma_spin.setRange(0.1, 3.0)
        self.gamma_spin.setSingleStep(0.05)
        self.gamma_spin.setValue(project.image.gamma)
        self.gamma_spin.setToolTip("1.0 で無変換。大きくすると全体が濃くなる")

        self.contrast_spin = QDoubleSpinBox()
        self.contrast_spin.setRange(0.0, 20.0)
        self.contrast_spin.setSingleStep(0.5)
        self.contrast_spin.setValue(project.image.contrast_cutoff)
        self.contrast_spin.setToolTip("0 でコントラスト補正なし")

        self.sharpen_check = QCheckBox("縮小後にシャープをかける")
        self.sharpen_check.setChecked(project.image.sharpen)

        form.addRow("形式", self.format_combo)
        form.addRow("JPEG品質", self.jpeg_quality)
        form.addRow("階調数", self.gray_levels)
        form.addRow("ガンマ", self.gamma_spin)
        form.addRow("コントラスト補正", self.contrast_spin)
        form.addRow(self.sharpen_check)
        return group

    # ---- 反映 ---------------------------------------------------------

    def _sync_enabled_states(self) -> None:
        is_custom = self.device_combo.currentData() == "custom"
        self.custom_width.setEnabled(is_custom)
        self.custom_height.setEnabled(is_custom)

        is_jpeg = self.format_combo.currentData() == "jpeg"
        self.jpeg_quality.setEnabled(is_jpeg)
        self.gray_levels.setEnabled(not is_jpeg)

        self.trim_threshold.setEnabled(self.trim_check.isChecked())

    def device_id(self) -> str:
        data = self.device_combo.currentData()
        if data == "custom":
            return f"custom:{self.custom_width.value()}x{self.custom_height.value()}"
        return data

    def apply_to(self, project: Project) -> None:
        project.title = self.title_edit.text().strip() or "無題"
        project.issue = self.issue_edit.text().strip()

        cover_text = self.cover_edit.text().strip()
        project.cover_image = Path(cover_text) if cover_text else None

        project.device_id = self.device_id()

        project.defaults.auto_trim = self.trim_check.isChecked()
        project.defaults.trim_threshold = self.trim_threshold.value()
        project.defaults.overlap = layouts.clamp_overlap(self.overlap_spin.value())

        project.image.format = self.format_combo.currentData()
        project.image.jpeg_quality = self.jpeg_quality.value()
        project.image.gray_levels = self.gray_levels.currentData()
        project.image.gamma = self.gamma_spin.value()
        project.image.contrast_cutoff = self.contrast_spin.value()
        project.image.sharpen = self.sharpen_check.isChecked()

    def _choose_cover(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "表紙画像を選ぶ", "", "画像 (*.png *.jpg *.jpeg *.webp *.bmp)"
        )
        if path:
            self.cover_edit.setText(path)
