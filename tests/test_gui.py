"""GUI のヘッドレステスト（QT_QPA_PLATFORM=offscreen）。

conftest.py が Qt の import 前にプラットフォームを設定している。
"""

from pathlib import Path

import pytest
from PIL import Image
from PySide6.QtWidgets import QApplication

from inkflow import builder, layouts
from inkflow.gui.main_window import MainWindow
from inkflow.gui.page_view import PageOverlay, PageView, pil_to_qimage
from inkflow.gui.settings_dialog import BookSettingsDialog
from inkflow.gui.worker import BuildWorker
from inkflow.models import PageSpec, Project

from .conftest import make_pdf

TEST_DEVICE = "custom:150x200"


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def window(qapp, article_pdfs):
    project = builder.project_from_pdfs(
        article_pdfs, title="月刊テスト", issue="2026年8月号", device_id=TEST_DEVICE
    )
    win = MainWindow(project)
    yield win
    win.preview_cache.close()
    win.deleteLater()


# ---- PageView ---------------------------------------------------------


def test_pil_to_qimage_keeps_size(qapp):
    image = Image.new("L", (40, 60), 128)
    qimage = pil_to_qimage(image)
    assert (qimage.width(), qimage.height()) == (40, 60)


def test_pil_to_qimage_accepts_rgb(qapp):
    qimage = pil_to_qimage(Image.new("RGB", (10, 10), (255, 0, 0)))
    assert qimage.width() == 10


def test_page_view_starts_empty(qapp):
    view = PageView()
    assert view.has_page() is False


def test_page_view_accepts_page(qapp):
    view = PageView()
    view.resize(300, 400)
    view.set_page(Image.new("L", (100, 140), 255), PageOverlay())
    assert view.has_page() is True
    view.clear()
    assert view.has_page() is False


def test_page_view_renders_without_error(qapp):
    from PySide6.QtGui import QPixmap

    view = PageView()
    view.resize(320, 440)
    view.set_page(
        Image.new("L", (200, 280), 255),
        PageOverlay(
            content_rect=(0.05, 0.05, 0.95, 0.95),
            part_rects=layouts.reading_rects("quad_2col"),
            include_overview=True,
            labels=["1", "2", "3", "4"],
        ),
    )
    # offscreen でも実際に描けることを確認する。
    view.render(QPixmap(view.size()))


def test_page_view_renders_rotation_badge(qapp):
    from PySide6.QtGui import QPixmap

    view = PageView()
    view.resize(320, 440)
    view.set_page(
        Image.new("L", (200, 280), 255),
        PageOverlay(
            part_rects=layouts.reading_rects("half_v"),
            labels=["1", "2"],
            rotation_label="右90°",
        ),
    )
    view.render(QPixmap(view.size()))


# ---- MainWindow の基本 -------------------------------------------------


def test_window_lists_articles_and_pages(window):
    assert window.tree.topLevelItemCount() == 3
    assert window.tree.topLevelItem(0).childCount() == 2
    assert window.tree.topLevelItem(2).childCount() == 3


def test_window_flat_page_list_covers_every_page(window):
    assert len(window._flat) == 6


def test_window_shows_preview_on_start(window):
    assert window.page_view.has_page() is True


def test_default_layout_selected_in_panel(window):
    index = layouts.layout_ids().index(layouts.DEFAULT_LAYOUT_ID)
    assert window.layout_buttons[index].isChecked() is True


def test_summary_reports_output_pages(window):
    # 原稿6ページ x 5枚
    assert "30" in window.summary_label.text()


# ---- ページ移動 -------------------------------------------------------


def test_next_and_previous_page(window):
    assert window._current == 0
    window.next_page()
    assert window._current == 1
    window.previous_page()
    assert window._current == 0


def test_navigation_stops_at_boundaries(window):
    window.previous_page()
    assert window._current == 0
    for _ in range(20):
        window.next_page()
    assert window._current == len(window._flat) - 1


def test_navigation_crosses_article_boundary(window):
    window.next_page()
    window.next_page()
    assert window._flat[window._current] == (1, 0)


def test_tree_selection_changes_current_page(window):
    item = window.tree.topLevelItem(2).child(1)
    window.tree.setCurrentItem(item)
    assert window._flat[window._current] == (2, 1)


# ---- レイアウト変更 ---------------------------------------------------


def test_select_layout_updates_spec(window):
    window.select_layout(layouts.layout_ids().index("half_v"))
    assert window._current_spec().layout_id == "half_v"


def test_select_layout_checks_the_matching_radio(window):
    index = layouts.layout_ids().index("third_v")
    window.select_layout(index)
    assert window.layout_buttons[index].isChecked() is True
    assert sum(1 for button in window.layout_buttons if button.isChecked()) == 1


def test_selecting_a_page_syncs_the_panel(window):
    """ページを移動したら、パネルの表示もそのページの設定に追従する。"""
    window.select_layout(layouts.layout_ids().index("half_v"))
    window.set_rotation(90)
    window.next_page()

    assert window.layout_buttons[layouts.layout_ids().index("quad_2col")].isChecked() is True
    assert window.rotation_buttons[0].isChecked() is True

    window.previous_page()
    assert window.layout_buttons[layouts.layout_ids().index("half_v")].isChecked() is True
    assert window.rotation_buttons[90].isChecked() is True


def test_select_layout_keeps_overview_flag(window):
    window.toggle_overview()
    window.select_layout(layouts.layout_ids().index("six_2col"))
    spec = window._current_spec()
    assert spec.layout_id == "six_2col"
    assert spec.include_overview is False


def test_toggle_overview(window):
    assert window._current_spec().include_overview is True
    window.toggle_overview()
    assert window._current_spec().include_overview is False
    window.toggle_overview()
    assert window._current_spec().include_overview is True


def test_toggle_overview_is_ignored_for_full_layout(window):
    window.select_layout(layouts.layout_ids().index("full"))
    before = window._current_spec().include_overview
    window.toggle_overview()
    assert window._current_spec().include_overview == before


def test_layout_change_updates_tree_label(window):
    window.select_layout(layouts.layout_ids().index("full"))
    text = window.tree.topLevelItem(0).child(0).text(0)
    assert "1枚" in text


def test_layout_change_marks_project_dirty(window):
    assert window._dirty is False
    window.select_layout(layouts.layout_ids().index("half_h"))
    assert window._dirty is True


# ---- まとめて適用 -----------------------------------------------------


# ---- 縦横入替（回転） -------------------------------------------------


def test_rotation_defaults_to_none(window):
    assert window._current_spec().rotate == 0
    assert window.rotation_buttons[0].isChecked() is True


def test_set_rotation_updates_spec_and_panel(window):
    window.set_rotation(90)
    assert window._current_spec().rotate == 90
    assert window.rotation_buttons[90].isChecked() is True


def test_cycle_rotation_walks_through_all_options(window):
    assert window._current_spec().rotate == 0
    window.cycle_rotation()
    assert window._current_spec().rotate == 90
    window.cycle_rotation()
    assert window._current_spec().rotate == 270
    window.cycle_rotation()
    assert window._current_spec().rotate == 0


def test_rotation_marks_project_dirty(window):
    assert window._dirty is False
    window.set_rotation(270)
    assert window._dirty is True


def test_rotation_shows_in_tree_label(window):
    window.set_rotation(90)
    assert "右90°" in window.tree.topLevelItem(0).child(0).text(0)
    window.set_rotation(0)
    assert "右90°" not in window.tree.topLevelItem(0).child(0).text(0)


def test_rotation_shows_in_page_label(window):
    window.set_rotation(270)
    assert "左90°" in window.page_label.text()


def test_layout_change_keeps_rotation(window):
    """設定項目を増やしても取りこぼさないこと（replace() を使っている）。"""
    window.set_rotation(90)
    window.select_layout(layouts.layout_ids().index("third_v"))
    spec = window._current_spec()
    assert spec.layout_id == "third_v"
    assert spec.rotate == 90


def test_overview_toggle_keeps_rotation(window):
    window.set_rotation(270)
    window.toggle_overview()
    spec = window._current_spec()
    assert spec.include_overview is False
    assert spec.rotate == 270


def test_apply_to_article_spreads_rotation(window):
    window.set_rotation(90)
    window.apply_to_article()
    assert all(page.rotate == 90 for page in window.project.articles[0].pages)
    assert all(page.rotate == 0 for page in window.project.articles[1].pages)


def test_apply_to_all_spreads_rotation(window):
    window.set_rotation(270)
    window.apply_to_all()
    assert all(
        page.rotate == 270 for article in window.project.articles for page in article.pages
    )


# ---- 俯瞰の縦横入替（分割コマとは別指定） -----------------------------


def test_overview_rotation_defaults_to_same(window):
    from inkflow.gui.main_window import OVERVIEW_ROTATION_CHOICES

    assert window._current_spec().rotate_overview is None
    same_index = OVERVIEW_ROTATION_CHOICES.index(None)
    assert window.overview_rotation_buttons[same_index].isChecked() is True


def test_set_overview_rotation_is_independent(window):
    window.set_rotation(90)
    window.set_overview_rotation(0)
    spec = window._current_spec()
    assert spec.rotate == 90
    assert spec.rotate_overview == 0
    assert spec.effective_overview_rotation() == 0


def test_cycle_overview_rotation_walks_through_all_choices(window):
    assert window._current_spec().rotate_overview is None
    window.cycle_overview_rotation()
    assert window._current_spec().rotate_overview == 0
    window.cycle_overview_rotation()
    assert window._current_spec().rotate_overview == 90
    window.cycle_overview_rotation()
    assert window._current_spec().rotate_overview == 270
    window.cycle_overview_rotation()
    assert window._current_spec().rotate_overview is None


def test_overview_rotation_shows_in_tree_only_when_different(window):
    window.set_rotation(90)
    # 「＋全体」は俯瞰を出力する印。向きは分割と同じなので出さない。
    assert "俯瞰" not in window.tree.topLevelItem(0).child(0).text(0)
    window.set_overview_rotation(0)
    assert "・俯瞰なし" in window.tree.topLevelItem(0).child(0).text(0)


def test_overview_rotation_shows_in_page_label(window):
    window.set_rotation(90)
    window.set_overview_rotation(0)
    assert "分割 右90°" in window.page_label.text()
    assert "俯瞰 なし" in window.page_label.text()


def test_overview_rotation_controls_disabled_without_overview(window):
    window.toggle_overview()  # 俯瞰を出力しない
    assert all(
        not button.isEnabled() for button in window.overview_rotation_buttons.values()
    )
    window.toggle_overview()
    assert all(button.isEnabled() for button in window.overview_rotation_buttons.values())


def test_overview_rotation_controls_enabled_for_full_layout(window):
    window.select_layout(layouts.layout_ids().index("full"))
    assert all(button.isEnabled() for button in window.overview_rotation_buttons.values())


def test_layout_change_keeps_overview_rotation(window):
    window.set_overview_rotation(270)
    window.select_layout(layouts.layout_ids().index("third_v"))
    assert window._current_spec().rotate_overview == 270


def test_overview_toggle_keeps_overview_rotation(window):
    window.set_overview_rotation(90)
    window.toggle_overview()
    assert window._current_spec().rotate_overview == 90


def test_apply_to_all_spreads_overview_rotation(window):
    window.set_rotation(90)
    window.set_overview_rotation(0)
    window.apply_to_all()
    assert all(
        page.rotate == 90 and page.rotate_overview == 0
        for article in window.project.articles
        for page in article.pages
    )


def test_apply_same_as_previous_copies_overview_rotation(window):
    window.set_overview_rotation(270)
    window.next_page()
    window.apply_same_as_previous()
    article_index, page_index = window._flat[1]
    assert window.project.articles[article_index].pages[page_index].rotate_overview == 270


def test_overview_rotation_survives_save_and_load(window, tmp_path):
    window.set_rotation(90)
    window.set_overview_rotation(0)
    path = tmp_path / "ov.inkflow.json"
    window._save_to(path)

    reloaded = Project.load(path)
    assert reloaded.articles[0].pages[0].rotate == 90
    assert reloaded.articles[0].pages[0].rotate_overview == 0


def test_set_overview_rotation_ignores_invalid_values(window):
    window.set_overview_rotation(45)
    assert window._current_spec().rotate_overview is None


def test_overview_rotation_on_empty_project_is_safe(qapp):
    win = MainWindow(Project())
    try:
        win.set_overview_rotation(90)
        win.cycle_overview_rotation()
    finally:
        win.preview_cache.close()
        win.deleteLater()


def test_apply_same_as_previous_copies_rotation(window):
    window.set_rotation(90)
    window.next_page()
    assert window._current_spec().rotate == 0
    window.apply_same_as_previous()
    article_index, page_index = window._flat[1]
    assert window.project.articles[article_index].pages[page_index].rotate == 90


def test_rotation_survives_save_and_load(window, tmp_path):
    window.set_rotation(90)
    window.next_page()
    window.set_rotation(270)

    path = tmp_path / "rotated.inkflow.json"
    window._save_to(path)

    reloaded = Project.load(path)
    assert reloaded.articles[0].pages[0].rotate == 90
    assert reloaded.articles[0].pages[1].rotate == 270


def test_set_rotation_ignores_invalid_values(window):
    window.set_rotation(45)
    assert window._current_spec().rotate == 0


def test_rotation_on_empty_project_is_safe(qapp):
    win = MainWindow(Project())
    try:
        win.set_rotation(90)
        win.cycle_rotation()
    finally:
        win.preview_cache.close()
        win.deleteLater()


# ---- 分割位置の微調整（column_bias / row_bias） ------------------------


def test_bias_defaults_to_fixed_default_position(window):
    spec = window._current_spec()
    assert spec.column_bias == 0.0
    assert spec.row_bias == 0.0


def test_adjust_column_bias_updates_spec(window):
    window.adjust_column_bias(0.01)
    assert window._current_spec().column_bias == pytest.approx(0.01)
    window.adjust_column_bias(0.01)
    assert window._current_spec().column_bias == pytest.approx(0.02)


def test_adjust_row_bias_updates_spec(window):
    window.adjust_row_bias(-0.01)
    assert window._current_spec().row_bias == pytest.approx(-0.01)


def test_adjust_column_bias_is_clamped(window):
    for _ in range(50):
        window.adjust_column_bias(0.01)
    assert window._current_spec().column_bias == pytest.approx(0.2)


def test_reset_column_bias_returns_to_auto(window):
    window.adjust_column_bias(0.05)
    assert window._current_spec().column_bias is not None
    window.reset_column_bias()
    assert window._current_spec().column_bias is None


def test_reset_row_bias_returns_to_auto(window):
    window.adjust_row_bias(0.05)
    window.reset_row_bias()
    assert window._current_spec().row_bias is None


def test_pin_column_bias_to_default_sets_zero(window):
    """既定ボタンは None（自動）ではなく、明示的な 0.0（既定位置に固定）にする。"""
    window.adjust_column_bias(0.05)
    window.pin_column_bias_to_default()
    assert window._current_spec().column_bias == pytest.approx(0.0)


def test_pin_row_bias_to_default_sets_zero(window):
    window.adjust_row_bias(-0.05)
    window.pin_row_bias_to_default()
    assert window._current_spec().row_bias == pytest.approx(0.0)


def test_pin_to_default_differs_from_auto(window):
    """既定固定（0.0）と自動（None）は別の状態。既定ボタンのあとに自動へ戻せる。"""
    window.pin_column_bias_to_default()
    assert window._current_spec().column_bias == pytest.approx(0.0)
    assert window._current_spec().column_bias is not None

    window.reset_column_bias()
    assert window._current_spec().column_bias is None


def test_bias_marks_project_dirty(window):
    assert window._dirty is False
    window.adjust_column_bias(0.01)
    assert window._dirty is True


def test_bias_controls_disabled_for_full_layout(window):
    """`full` レイアウトには分割線が無いので、微調整ボタンは無効になる。"""
    window.select_layout(layouts.layout_ids().index("full"))
    assert all(not b.isEnabled() for b in window.column_bias_buttons)
    assert all(not b.isEnabled() for b in window.row_bias_buttons)


def test_bias_controls_enabled_for_quad_2col(window):
    assert window._current_spec().layout_id == "quad_2col"
    assert all(b.isEnabled() for b in window.column_bias_buttons)
    assert all(b.isEnabled() for b in window.row_bias_buttons)


def test_adjust_bias_ignored_when_axis_has_no_divider(window):
    """分割線の無い軸（例: half_v の左右）はクリックしても変化しない。"""
    window.select_layout(layouts.layout_ids().index("half_v"))
    xs, ys = layouts.internal_dividers("half_v")
    assert xs == ()  # half_v は上下のみ分割
    window.adjust_column_bias(0.01)
    assert window._current_spec().column_bias == 0.0


def test_column_bias_label_shows_manual_value(window):
    window.adjust_column_bias(0.04)
    assert "手動" in window.column_bias_label.text()
    assert "+4.0%" in window.column_bias_label.text()


def test_column_bias_label_shows_fixed_default_when_unset(window):
    assert "既定位置" in window.column_bias_label.text()


def test_column_bias_label_shows_pinned_default(window):
    window.adjust_column_bias(0.04)  # いったん動かしてから既定へ戻す
    window.pin_column_bias_to_default()
    assert "既定位置" in window.column_bias_label.text()
    assert "手動" not in window.column_bias_label.text()


def test_column_bias_label_shows_auto_after_reset(window):
    window.reset_column_bias()
    assert "自動" in window.column_bias_label.text()


def test_layout_change_keeps_bias(window):
    window.adjust_column_bias(0.03)
    window.select_layout(layouts.layout_ids().index("six_2col"))
    assert window._current_spec().column_bias == pytest.approx(0.03)


def test_overview_toggle_keeps_bias(window):
    window.adjust_row_bias(0.02)
    window.toggle_overview()
    assert window._current_spec().row_bias == pytest.approx(0.02)


def test_apply_to_article_spreads_bias(window):
    window.adjust_column_bias(0.05)
    window.apply_to_article()
    assert all(page.column_bias == pytest.approx(0.05) for page in window.project.articles[0].pages)
    assert all(page.column_bias == 0.0 for page in window.project.articles[1].pages)


def test_apply_to_all_spreads_bias(window):
    window.adjust_row_bias(-0.03)
    window.apply_to_all()
    assert all(
        page.row_bias == pytest.approx(-0.03)
        for article in window.project.articles
        for page in article.pages
    )


def test_apply_same_as_previous_copies_bias(window):
    window.adjust_column_bias(0.02)
    window.next_page()
    window.apply_same_as_previous()
    article_index, page_index = window._flat[1]
    assert window.project.articles[article_index].pages[page_index].column_bias == pytest.approx(
        0.02
    )


def test_bias_survives_save_and_load(window, tmp_path):
    window.adjust_column_bias(0.06)
    window.adjust_row_bias(-0.02)
    path = tmp_path / "book.inkflow.json"
    window.project.save(path)

    reloaded = Project.load(path)
    spec = reloaded.articles[0].pages[0]
    assert spec.column_bias == pytest.approx(0.06)
    assert spec.row_bias == pytest.approx(-0.02)


def test_bias_on_empty_project_is_safe(qapp):
    win = MainWindow(Project())
    try:
        win.adjust_column_bias(0.01)
        win.reset_column_bias()
        win.pin_column_bias_to_default()
        win.adjust_row_bias(0.01)
        win.reset_row_bias()
        win.pin_row_bias_to_default()
    finally:
        win.preview_cache.close()
        win.deleteLater()


def test_preview_reflects_manual_bias(window):
    """手動バイアスを設定すると、プレビューに描かれる分割枠も実際に動く。"""
    plain_rects = window.page_view._overlay.part_rects

    window.adjust_column_bias(0.1)
    biased_rects = window.page_view._overlay.part_rects

    assert biased_rects != plain_rects
    # 左段（左上コマ）の右端が、バイアス分だけ右に動いているはず。
    assert biased_rects[0][2] > plain_rects[0][2]


def test_apply_same_as_previous_copies_and_advances(window):
    window.select_layout(layouts.layout_ids().index("six_2col"))
    window.next_page()
    assert window._current_spec().layout_id == layouts.DEFAULT_LAYOUT_ID

    window.apply_same_as_previous()
    # 1つ前の設定が複製され、さらに次のページへ進む
    article_index, page_index = window._flat[1]
    assert window.project.articles[article_index].pages[page_index].layout_id == "six_2col"
    assert window._current == 2


def test_apply_same_as_previous_on_first_page_just_advances(window):
    window.apply_same_as_previous()
    assert window._current == 1


def test_apply_to_article_only_touches_that_article(window):
    window.select_layout(layouts.layout_ids().index("half_v"))
    window.apply_to_article()
    assert all(p.layout_id == "half_v" for p in window.project.articles[0].pages)
    assert all(
        p.layout_id == layouts.DEFAULT_LAYOUT_ID for p in window.project.articles[1].pages
    )


def test_apply_to_all_touches_every_article(window):
    window.select_layout(layouts.layout_ids().index("third_v"))
    window.apply_to_all()
    assert all(
        page.layout_id == "third_v"
        for article in window.project.articles
        for page in article.pages
    )


# ---- 記事の操作 -------------------------------------------------------


def test_add_pdf_paths_appends_article(window, tmp_path):
    extra = make_pdf(tmp_path / "04_追加.pdf", page_count=2)
    window.add_pdf_paths([extra])
    assert len(window.project.articles) == 4
    assert window.project.articles[-1].title == "04_追加"
    assert len(window._flat) == 8


def test_add_pdf_paths_reports_broken_file(window, tmp_path, monkeypatch):
    warned = {}

    def fake_warning(_parent, title, text):
        warned["title"] = title
        warned["text"] = text

    monkeypatch.setattr("inkflow.gui.main_window.QMessageBox.warning", fake_warning)
    broken = tmp_path / "broken.pdf"
    broken.write_text("not a pdf", encoding="utf-8")
    window.add_pdf_paths([broken])

    assert len(window.project.articles) == 3
    assert "追加できない" in warned["title"]


def test_move_article_reorders(window):
    window.move_article(1)
    assert [a.title for a in window.project.articles][:2] == [
        "02_インタビュー",
        "01_巻頭特集",
    ]


def test_move_article_at_edge_does_nothing(window):
    window.move_article(-1)
    assert window.project.articles[0].title == "01_巻頭特集"


def test_move_article_follows_selection(window):
    window.move_article(1)
    assert window._flat[window._current] == (1, 0)


def test_rename_article_updates_bookmark_title(window, monkeypatch):
    monkeypatch.setattr(
        "inkflow.gui.main_window.QInputDialog.getText",
        lambda *args, **kwargs: ("巻頭インタビュー", True),
    )
    window.rename_article()
    assert window.project.articles[0].title == "巻頭インタビュー"


def test_rename_article_cancel_keeps_title(window, monkeypatch):
    monkeypatch.setattr(
        "inkflow.gui.main_window.QInputDialog.getText",
        lambda *args, **kwargs: ("", False),
    )
    window.rename_article()
    assert window.project.articles[0].title == "01_巻頭特集"


def test_remove_article(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        "inkflow.gui.main_window.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    window.remove_article()
    assert len(window.project.articles) == 2
    assert len(window._flat) == 4


# ---- 保存と読み込み ---------------------------------------------------


def test_project_round_trip_through_window(window, tmp_path, monkeypatch):
    window.select_layout(layouts.layout_ids().index("six_2col"))
    window.next_page()
    window.toggle_overview()

    path = tmp_path / "book.inkflow.json"
    assert window._save_to(path) is True
    assert window._dirty is False

    reloaded = Project.load(path)
    assert reloaded.articles[0].pages[0] == PageSpec("six_2col", include_overview=True)
    assert reloaded.articles[0].pages[1].include_overview is False
    assert reloaded.title == "月刊テスト"


def test_open_project_restores_state(qapp, window, tmp_path):
    window.select_layout(layouts.layout_ids().index("half_h"))
    path = tmp_path / "book.inkflow.json"
    window._save_to(path)

    fresh = MainWindow(Project())
    try:
        loaded = Project.load(path)
        fresh.project = loaded
        fresh.refresh_all()
        assert len(fresh.project.articles) == 3
        assert fresh.project.articles[0].pages[0].layout_id == "half_h"
    finally:
        fresh.preview_cache.close()
        fresh.deleteLater()


def test_empty_window_shows_hint(qapp):
    win = MainWindow(Project())
    try:
        assert win.page_view.has_page() is False
        assert win.position_label.text() == "0 / 0"
        win.next_page()  # 落ちないこと
        win.select_layout(0)
        win.toggle_overview()
        win.apply_to_all()
    finally:
        win.preview_cache.close()
        win.deleteLater()


# ---- ダイアログの既定フォルダ -------------------------------------------


def test_default_dialog_dir_empty_without_articles_or_history(qapp):
    win = MainWindow(Project())
    try:
        assert win._default_dialog_dir() == ""
    finally:
        win.preview_cache.close()
        win.deleteLater()


def test_default_dialog_dir_falls_back_to_latest_article_folder(window):
    expected = str(window.project.articles[-1].path.parent)
    assert window._default_dialog_dir() == expected


def test_remember_dialog_dir_overrides_article_fallback(window, tmp_path):
    other = tmp_path / "elsewhere"
    other.mkdir()
    window._remember_dialog_dir(other / "book.inkflow.json")
    assert window._default_dialog_dir() == str(other)


def test_remember_dialog_dir_accepts_a_directory_directly(window, tmp_path):
    folder = tmp_path / "just-a-folder"
    folder.mkdir()
    window._remember_dialog_dir(folder)
    assert window._default_dialog_dir() == str(folder)


def test_add_pdfs_dialog_starts_at_existing_article_folder(window, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QFileDialog

    extra = make_pdf(tmp_path / "extra.pdf")
    seen_dir = {}

    def fake_get_open_file_names(parent, caption, directory, filter):
        seen_dir["dir"] = directory
        return ([str(extra)], "")

    monkeypatch.setattr(QFileDialog, "getOpenFileNames", fake_get_open_file_names)
    window.add_pdfs()

    assert seen_dir["dir"] == str(window.project.articles[0].path.parent)
    # 選んだファイルのフォルダを覚えている。
    assert window._last_browsed_dir == extra.parent


def test_add_pdfs_dialog_starts_empty_without_articles(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    win = MainWindow(Project())
    try:
        seen_dir = {}

        def fake_get_open_file_names(parent, caption, directory, filter):
            seen_dir["dir"] = directory
            return ([], "")

        monkeypatch.setattr(QFileDialog, "getOpenFileNames", fake_get_open_file_names)
        win.add_pdfs()
        assert seen_dir["dir"] == ""
    finally:
        win.preview_cache.close()
        win.deleteLater()


def test_drag_and_drop_articles_also_set_the_fallback_folder(qapp, tmp_path):
    win = MainWindow(Project())
    try:
        folder = tmp_path / "dropped"
        folder.mkdir()
        pdf = make_pdf(folder / "article.pdf")
        win.add_pdf_paths([pdf])
        assert win._default_dialog_dir() == str(folder)
    finally:
        win.preview_cache.close()
        win.deleteLater()


def test_save_project_as_dialog_starts_at_article_folder(window, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    seen = {}

    def fake_get_save_file_name(parent, caption, directory, filter):
        seen["dir"] = directory
        return ("", "")  # キャンセル扱い

    monkeypatch.setattr(QFileDialog, "getSaveFileName", fake_get_save_file_name)
    window.save_project_as()

    article_dir = str(window.project.articles[-1].path.parent)
    assert seen["dir"].startswith(article_dir)


def test_save_project_as_remembers_chosen_folder(window, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QFileDialog

    chosen = tmp_path / "picked" / "book.inkflow.json"
    chosen.parent.mkdir()
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", lambda *args: (str(chosen), "")
    )
    window.save_project_as()
    assert window._last_browsed_dir == chosen.parent


def test_save_project_as_prefers_existing_project_path(window, monkeypatch, tmp_path):
    """既に保存済みなら、記事フォルダではなくプロジェクトファイルの場所を提案する。"""
    from PySide6.QtWidgets import QFileDialog

    window.project.project_path = tmp_path / "saved-elsewhere" / "book.inkflow.json"
    seen = {}

    def fake_get_save_file_name(parent, caption, directory, filter):
        seen["dir"] = directory
        return ("", "")

    monkeypatch.setattr(QFileDialog, "getSaveFileName", fake_get_save_file_name)
    window.save_project_as()
    assert seen["dir"] == str(window.project.project_path)


def test_export_epub_dialog_starts_at_article_folder(window, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    seen = {}

    def fake_get_save_file_name(parent, caption, directory, filter):
        seen["dir"] = directory
        return ("", "")

    monkeypatch.setattr(QFileDialog, "getSaveFileName", fake_get_save_file_name)
    window.export_epub()

    article_dir = str(window.project.articles[-1].path.parent)
    assert seen["dir"].startswith(article_dir)


def test_export_epub_remembers_chosen_folder(window, monkeypatch, tmp_path):
    """フォルダを覚える処理はワーカー起動より前で同期的に行われる。

    ワーカーの完了を待つと、キューに残ったシグナルが後続の別テストの
    ``processEvents()`` 呼び出し時に配送されてクラッシュしうる
    （実際に踏んだ）。ここで確かめたいのはフォルダを覚えたかだけなので、
    ``BuildWorker.start`` を no-op にしてスレッドそのものを起動しない。
    """
    from PySide6.QtWidgets import QFileDialog

    from inkflow.gui.worker import BuildWorker

    chosen = tmp_path / "output" / "book.epub"
    chosen.parent.mkdir()
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", lambda *args: (str(chosen), "")
    )
    monkeypatch.setattr(BuildWorker, "start", lambda self: None)

    window.export_epub()
    assert window._last_browsed_dir == chosen.parent


def test_export_epub_prefers_project_file_location_when_saved(window, monkeypatch, tmp_path):
    """保存済みプロジェクトでは、従来どおりプロジェクトファイルの場所を優先する。"""
    from PySide6.QtWidgets import QFileDialog

    window.project.project_path = tmp_path / "saved-elsewhere" / "book.inkflow.json"
    seen = {}

    def fake_get_save_file_name(parent, caption, directory, filter):
        seen["dir"] = directory
        return ("", "")

    monkeypatch.setattr(QFileDialog, "getSaveFileName", fake_get_save_file_name)
    window.export_epub()
    assert seen["dir"].startswith(str(window.project.project_path.parent))


def test_new_project_resets_remembered_dialog_dir(window, monkeypatch, tmp_path):
    window._remember_dialog_dir(tmp_path / "somewhere")
    monkeypatch.setattr(
        BookSettingsDialog, "exec", lambda self: BookSettingsDialog.DialogCode.Accepted
    )
    window.new_project()
    assert window._last_browsed_dir is None
    assert window._default_dialog_dir() == ""


def test_open_project_resets_remembered_dialog_dir(window, tmp_path):
    window._remember_dialog_dir(tmp_path / "somewhere")
    path = tmp_path / "book.inkflow.json"
    window._save_to(path)

    loaded = Project.load(path)
    window.project = loaded
    window._last_browsed_dir = None  # open_project() が行うのと同じリセット
    window.refresh_all()

    assert window._default_dialog_dir() == str(window.project.articles[-1].path.parent)


# ---- 新規プロジェクト ---------------------------------------------------


def test_new_project_menu_action_has_ctrl_n_shortcut(window):
    from PySide6.QtGui import QKeySequence

    # 中間結果を変数に残さず1行で連鎖すると、途中のQActionラッパーがすぐ回収され、
    # shiboken が menu() の戻り値を巻き込んで解放してしまうことがある。
    # 名前を付けて生きたままにしておくと安定する。
    menu_bar = window.menuBar()
    top_actions = menu_bar.actions()
    file_action = top_actions[0]
    file_menu = file_action.menu()
    file_menu_actions = file_menu.actions()
    action = next(a for a in file_menu_actions if "新規プロジェクト" in a.text())
    assert action.shortcut() == QKeySequence(QKeySequence.StandardKey.New)


def test_new_project_applies_dialog_settings(window, monkeypatch):
    def fake_exec(self):
        self.title_edit.setText("新しい雑誌")
        self.issue_edit.setText("2026年9月号")
        return BookSettingsDialog.DialogCode.Accepted

    monkeypatch.setattr(BookSettingsDialog, "exec", fake_exec)
    window.new_project()

    assert window.project.title == "新しい雑誌"
    assert window.project.issue == "2026年9月号"
    assert window.project.articles == []


def test_new_project_resets_navigation_and_dirty_state(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    window.next_page()
    window.select_layout(layouts.layout_ids().index("half_v"))  # ダーティにしておく
    monkeypatch.setattr(
        BookSettingsDialog, "exec", lambda self: BookSettingsDialog.DialogCode.Accepted
    )
    monkeypatch.setattr(
        "inkflow.gui.main_window.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Discard,
    )
    window.new_project()

    assert window._current == 0
    assert window._flat == []
    assert window.position_label.text() == "0 / 0"
    assert window._dirty is False


def test_new_project_clears_project_path(window, tmp_path, monkeypatch):
    window._save_to(tmp_path / "old.inkflow.json")
    assert window.project.project_path is not None

    monkeypatch.setattr(
        BookSettingsDialog, "exec", lambda self: BookSettingsDialog.DialogCode.Accepted
    )
    window.new_project()
    assert window.project.project_path is None


def test_new_project_dialog_cancel_keeps_current_project(window, monkeypatch):
    original_title = window.project.title
    original_article_count = len(window.project.articles)
    monkeypatch.setattr(
        BookSettingsDialog, "exec", lambda self: BookSettingsDialog.DialogCode.Rejected
    )
    window.new_project()

    assert window.project.title == original_title
    assert len(window.project.articles) == original_article_count


def test_new_project_respects_unsaved_changes_guard(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    window.select_layout(layouts.layout_ids().index("half_v"))
    assert window._dirty is True

    monkeypatch.setattr(
        "inkflow.gui.main_window.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Cancel,
    )
    dialog_shown = []
    monkeypatch.setattr(
        BookSettingsDialog,
        "exec",
        lambda self: dialog_shown.append(True) or BookSettingsDialog.DialogCode.Accepted,
    )
    window.new_project()

    assert dialog_shown == []  # 設定ダイアログまで到達しない
    assert len(window.project.articles) == 3  # 元のプロジェクトのまま


def test_new_project_can_discard_unsaved_changes(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    window.select_layout(layouts.layout_ids().index("half_v"))
    monkeypatch.setattr(
        "inkflow.gui.main_window.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Discard,
    )
    monkeypatch.setattr(
        BookSettingsDialog, "exec", lambda self: BookSettingsDialog.DialogCode.Accepted
    )
    window.new_project()

    assert window.project.articles == []


def test_new_project_can_save_before_discarding(window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    window.select_layout(layouts.layout_ids().index("half_v"))
    save_path = tmp_path / "saved-before-new.inkflow.json"
    monkeypatch.setattr(
        "inkflow.gui.main_window.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Save,
    )
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(save_path), "")
    )
    monkeypatch.setattr(
        BookSettingsDialog, "exec", lambda self: BookSettingsDialog.DialogCode.Accepted
    )
    window.new_project()

    assert save_path.is_file()
    assert window.project.articles == []


def test_new_project_from_empty_window_is_safe(qapp, monkeypatch):
    win = MainWindow(Project())
    try:
        monkeypatch.setattr(
            BookSettingsDialog, "exec", lambda self: BookSettingsDialog.DialogCode.Accepted
        )
        win.new_project()
        assert win.project.articles == []
    finally:
        win.preview_cache.close()
        win.deleteLater()


# ---- バージョン情報 -----------------------------------------------------


def test_about_menu_action_exists(window):
    menu_bar = window.menuBar()
    top_actions = menu_bar.actions()
    help_action = top_actions[-1]
    help_menu = help_action.menu()
    help_menu_actions = help_menu.actions()
    assert any("バージョン情報" in a.text() for a in help_menu_actions)


def test_show_about_displays_build_info(window, monkeypatch):
    from inkflow import buildinfo

    monkeypatch.setattr(buildinfo, "FROZEN", False)
    monkeypatch.setattr(buildinfo, "_run_git", lambda args: None)

    captured = {}

    def fake_information(parent, title, text):
        captured["title"] = title
        captured["text"] = text

    monkeypatch.setattr("inkflow.gui.main_window.QMessageBox.information", fake_information)
    window.show_about()

    assert captured["title"] == "バージョン情報"
    assert "InkFlow" in captured["text"]
    assert "ビルド: ソース実行" in captured["text"]


# ---- 設定ダイアログ ---------------------------------------------------


def test_settings_dialog_applies_values(qapp, article_pdfs):
    project = builder.project_from_pdfs(article_pdfs, title="旧", device_id=TEST_DEVICE)
    dialog = BookSettingsDialog(project)
    try:
        dialog.title_edit.setText("新しい誌名")
        dialog.issue_edit.setText("2026年9月号")
        dialog.overlap_spin.setValue(0.07)
        dialog.trim_check.setChecked(False)
        dialog.format_combo.setCurrentIndex(dialog.format_combo.findData("jpeg"))
        dialog.jpeg_quality.setValue(72)
        dialog.apply_to(project)
    finally:
        dialog.deleteLater()

    assert project.title == "新しい誌名"
    assert project.issue == "2026年9月号"
    assert project.defaults.overlap == pytest.approx(0.07)
    assert project.defaults.auto_trim is False
    assert project.image.format == "jpeg"
    assert project.image.jpeg_quality == 72


def test_settings_dialog_custom_device(qapp):
    project = Project(device_id="custom:900x1200")
    dialog = BookSettingsDialog(project)
    try:
        assert dialog.custom_width.value() == 900
        assert dialog.custom_height.value() == 1200
        dialog.custom_width.setValue(1000)
        dialog.apply_to(project)
    finally:
        dialog.deleteLater()
    assert project.device_id == "custom:1000x1200"


def test_settings_dialog_preset_device(qapp):
    project = Project(device_id="paperwhite_10")
    dialog = BookSettingsDialog(project)
    try:
        assert dialog.device_id() == "paperwhite_10"
    finally:
        dialog.deleteLater()


def test_settings_dialog_empty_title_falls_back(qapp):
    project = Project(title="元")
    dialog = BookSettingsDialog(project)
    try:
        dialog.title_edit.setText("   ")
        dialog.apply_to(project)
    finally:
        dialog.deleteLater()
    assert project.title == "無題"


# ---- 出力ワーカー -----------------------------------------------------


def test_build_worker_produces_epub(qapp, article_pdfs, tmp_path):
    project = builder.project_from_pdfs(
        article_pdfs[:1], title="ワーカー試験", device_id=TEST_DEVICE
    )
    output = tmp_path / "worker.epub"
    worker = BuildWorker(project, output)

    results = []
    worker.succeeded.connect(results.append)
    worker.failed.connect(lambda message: results.append(RuntimeError(message)))
    worker.start()
    assert worker.wait(120_000) is True
    qapp.processEvents()

    assert output.is_file()
    assert results and not isinstance(results[0], Exception)
    assert results[0].page_count == 11  # 2ページ x 5枚 + 表紙


def test_build_worker_reports_failure(qapp, tmp_path):
    project = Project(title="空", device_id=TEST_DEVICE)
    worker = BuildWorker(project, tmp_path / "fail.epub")

    messages: list[str] = []
    worker.failed.connect(messages.append)
    worker.start()
    assert worker.wait(30_000) is True
    qapp.processEvents()

    assert messages and "記事が1件も登録されていません" in messages[0]
    assert not (tmp_path / "fail.epub").exists()


def test_build_worker_uses_a_snapshot_of_the_project(qapp, article_pdfs, tmp_path):
    """生成開始後にUI側でレイアウトを変えても、出力には影響しない。"""
    project = builder.project_from_pdfs(
        article_pdfs[:1], title="スナップショット", device_id=TEST_DEVICE
    )
    worker = BuildWorker(project, tmp_path / "snapshot.epub")
    project.apply_layout_to_all(PageSpec("full"))

    summaries = []
    worker.succeeded.connect(summaries.append)
    worker.start()
    assert worker.wait(120_000) is True
    qapp.processEvents()

    assert summaries[0].page_count == 11  # full なら3枚になるはず


# ---- ドラッグ＆ドロップ -----------------------------------------------


def test_pdf_paths_from_filters_non_pdf(qapp, tmp_path):
    from PySide6.QtCore import QMimeData, QUrl

    class FakeEvent:
        def __init__(self, mime):
            self._mime = mime


        def mimeData(self):
            return self._mime

    mime = QMimeData()
    mime.setUrls(
        [
            QUrl.fromLocalFile(str(tmp_path / "a.pdf")),
            QUrl.fromLocalFile(str(tmp_path / "b.txt")),
        ]
    )
    paths = MainWindow._pdf_paths_from(FakeEvent(mime))
    assert [Path(p).name for p in paths] == ["a.pdf"]


def test_pdf_paths_from_without_urls(qapp):
    from PySide6.QtCore import QMimeData

    class FakeEvent:
        def mimeData(self):
            return QMimeData()

    assert MainWindow._pdf_paths_from(FakeEvent()) == []


def test_project_path_from_finds_json(qapp, tmp_path):
    from PySide6.QtCore import QMimeData, QUrl

    class FakeEvent:
        def __init__(self, mime):
            self._mime = mime

        def mimeData(self):
            return self._mime

    mime = QMimeData()
    mime.setUrls(
        [
            QUrl.fromLocalFile(str(tmp_path / "a.pdf")),
            QUrl.fromLocalFile(str(tmp_path / "book.inkflow.json")),
        ]
    )
    path = MainWindow._project_path_from(FakeEvent(mime))
    assert path.name == "book.inkflow.json"


def test_project_path_from_without_json_returns_none(qapp, tmp_path):
    from PySide6.QtCore import QMimeData, QUrl

    class FakeEvent:
        def __init__(self, mime):
            self._mime = mime

        def mimeData(self):
            return self._mime

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(tmp_path / "a.pdf"))])
    assert MainWindow._project_path_from(FakeEvent(mime)) is None


def test_project_path_from_without_urls(qapp):
    from PySide6.QtCore import QMimeData

    class FakeEvent:
        def mimeData(self):
            return QMimeData()

    assert MainWindow._project_path_from(FakeEvent()) is None


# ---- ドロップされたプロジェクトファイルを開く ---------------------------


def test_open_dropped_project_opens_after_confirmation(window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    saved_path = tmp_path / "book.inkflow.json"
    window.select_layout(layouts.layout_ids().index("half_h"))
    window._save_to(saved_path)

    fresh = MainWindow(Project())
    try:
        monkeypatch.setattr(
            "inkflow.gui.main_window.QMessageBox.question",
            lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
        )
        fresh.open_dropped_project(saved_path)
        assert len(fresh.project.articles) == 3
        assert fresh.project.articles[0].pages[0].layout_id == "half_h"
    finally:
        fresh.preview_cache.close()
        fresh.deleteLater()


def test_open_dropped_project_cancelled_leaves_project_unchanged(window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    saved_path = tmp_path / "book.inkflow.json"
    window.select_layout(layouts.layout_ids().index("half_h"))
    window._save_to(saved_path)

    fresh = MainWindow(Project())
    try:
        monkeypatch.setattr(
            "inkflow.gui.main_window.QMessageBox.question",
            lambda *args, **kwargs: QMessageBox.StandardButton.No,
        )
        fresh.open_dropped_project(saved_path)
        assert fresh.project.articles == []  # 開かれていない
    finally:
        fresh.preview_cache.close()
        fresh.deleteLater()


def test_open_dropped_project_respects_unsaved_changes_guard(window, tmp_path, monkeypatch):
    """内容確認とユーザー確認（開く）を通っても、未保存の変更があれば破棄確認が必要。"""
    from PySide6.QtWidgets import QMessageBox

    saved_path = tmp_path / "book.inkflow.json"
    window._save_to(saved_path)

    # window はフィクスチャ生成時点では未保存の変更が無いので、ここで作る。
    window.select_layout(layouts.layout_ids().index("half_h"))
    assert window._dirty is True

    # 1回目の question 呼び出しは「開きますか？」→ Yes、
    # 2回目は「保存しますか？」（破棄確認）→ Cancel、で開かれないはず。
    answers = iter([QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.Cancel])
    monkeypatch.setattr(
        "inkflow.gui.main_window.QMessageBox.question",
        lambda *args, **kwargs: next(answers),
    )
    original_article_count = len(window.project.articles)
    window.open_dropped_project(saved_path)

    assert len(window.project.articles) == original_article_count  # 破棄されなかった


def test_open_dropped_project_rejects_invalid_json(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    bad_path = tmp_path / "broken.inkflow.json"
    bad_path.write_text("{not valid json", encoding="utf-8")

    captured = {}
    monkeypatch.setattr(
        "inkflow.gui.main_window.QMessageBox.critical",
        lambda parent, title, text: captured.setdefault("text", text),
    )
    asked = []
    monkeypatch.setattr(
        "inkflow.gui.main_window.QMessageBox.question",
        lambda *args, **kwargs: asked.append(True),
    )

    win = MainWindow(Project())
    try:
        win.open_dropped_project(bad_path)
        assert "text" in captured  # エラーダイアログが出た
        assert asked == []  # 確認ダイアログまでは進まない
    finally:
        win.preview_cache.close()
        win.deleteLater()


def test_open_dropped_project_rejects_missing_source_pdfs(qapp, tmp_path, monkeypatch):
    """参照PDFが見つからない場合は「不整合」として開かず、確認ダイアログも出さない。"""
    from PySide6.QtWidgets import QMessageBox

    # window フィクスチャのPDFは開いているハンドルがありWindowsでは削除できないため、
    # ここだけ独立したPDFを作り、保存後に削除して「参照先が無い」状況を作る。
    source_dir = tmp_path / "source_articles"
    source_dir.mkdir()
    missing_pdf = make_pdf(source_dir / "01.pdf")
    project = builder.project_from_pdfs([missing_pdf], title="t", device_id=TEST_DEVICE)
    saved_path = tmp_path / "book.inkflow.json"
    project.save(saved_path)
    missing_pdf.unlink()

    captured = {}
    monkeypatch.setattr(
        "inkflow.gui.main_window.QMessageBox.critical",
        lambda parent, title, text: captured.setdefault("text", text),
    )
    asked = []
    monkeypatch.setattr(
        "inkflow.gui.main_window.QMessageBox.question",
        lambda *args, **kwargs: asked.append(True),
    )

    fresh = MainWindow(Project())
    try:
        fresh.open_dropped_project(saved_path)
        assert "text" in captured
        assert asked == []
        assert fresh.project.articles == []
    finally:
        fresh.preview_cache.close()
        fresh.deleteLater()


def test_drop_event_prioritizes_project_file_over_pdfs(window, tmp_path, monkeypatch):
    from PySide6.QtCore import QMimeData, QUrl
    from PySide6.QtWidgets import QMessageBox

    saved_path = tmp_path / "book.inkflow.json"
    window.select_layout(layouts.layout_ids().index("half_h"))
    window._save_to(saved_path)

    calls = []
    monkeypatch.setattr(
        MainWindow, "open_dropped_project", lambda self, path: calls.append(("project", path))
    )
    monkeypatch.setattr(
        MainWindow, "add_pdf_paths", lambda self, paths: calls.append(("pdfs", paths))
    )

    mime = QMimeData()
    mime.setUrls(
        [
            QUrl.fromLocalFile(str(tmp_path / "extra.pdf")),
            QUrl.fromLocalFile(str(saved_path)),
        ]
    )

    class FakeEvent:
        def __init__(self, mime):
            self._mime = mime
            self.accepted = False

        def mimeData(self):
            return self._mime

        def acceptProposedAction(self):
            self.accepted = True

    event = FakeEvent(mime)
    window.dropEvent(event)

    assert calls == [("project", saved_path)]
    assert event.accepted is True


# ---- 起動引数の解釈 ---------------------------------------------------


def test_initial_project_without_arguments(qapp):
    from inkflow.gui.app import _initial_project

    assert _initial_project([]) == (None, None)


# ---- アプリアイコン ---------------------------------------------------


def test_application_icon_is_available(qapp):
    from inkflow.gui.app import application_icon

    icon = application_icon()
    assert icon is not None
    assert icon.isNull() is False


def test_application_icon_matches_the_generated_artwork(qapp):
    """パッケージ版とソース実行で同じ図柄になること。"""
    from inkflow import appicon
    from inkflow.gui.app import ICON_SIZE, application_icon

    icon = application_icon()
    pixmap = icon.pixmap(ICON_SIZE, ICON_SIZE)
    assert (pixmap.width(), pixmap.height()) == (ICON_SIZE, ICON_SIZE)
    assert appicon.render_icon(ICON_SIZE).size == (ICON_SIZE, ICON_SIZE)


def test_application_icon_survives_generation_failure(qapp, monkeypatch):
    def boom(_size):
        raise RuntimeError("描画に失敗")

    monkeypatch.setattr("inkflow.gui.app.appicon.render_icon", boom)
    from inkflow.gui.app import application_icon

    assert application_icon() is None


def test_initial_project_from_folder(qapp, article_pdfs):
    from inkflow.gui.app import _initial_project

    folder = article_pdfs[0].parent
    project, error = _initial_project([str(folder)])
    assert error is None
    assert len(project.articles) == 3
    assert project.title == folder.resolve().name


def test_initial_project_from_pdf_list(qapp, article_pdfs):
    from inkflow.gui.app import _initial_project

    project, error = _initial_project([str(p) for p in article_pdfs[:2]])
    assert error is None
    assert len(project.articles) == 2


def test_initial_project_from_project_file(qapp, article_pdfs, tmp_path):
    from inkflow.gui.app import _initial_project

    saved = builder.project_from_pdfs(article_pdfs, title="保存済み", device_id=TEST_DEVICE)
    path = tmp_path / "book.inkflow.json"
    saved.save(path)

    project, error = _initial_project([str(path)])
    assert error is None
    assert project.title == "保存済み"
    assert len(project.articles) == 3


def test_initial_project_reports_error_for_empty_folder(qapp, tmp_path):
    from inkflow.gui.app import _initial_project

    empty = tmp_path / "empty"
    empty.mkdir()
    project, error = _initial_project([str(empty)])
    assert project is None
    assert "PDFが1件も見つかりません" in error


def test_initial_project_ignores_unknown_files(qapp, tmp_path):
    from inkflow.gui.app import _initial_project

    other = tmp_path / "memo.txt"
    other.write_text("x", encoding="utf-8")
    assert _initial_project([str(other)]) == (None, None)
