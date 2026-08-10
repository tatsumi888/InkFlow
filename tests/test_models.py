import json
from pathlib import Path

import pytest

from inkflow import layouts
from inkflow.errors import ProjectFormatError
from inkflow.models import (
    ROTATION_CCW,
    ROTATION_CW,
    ROTATION_NONE,
    Article,
    ImageOptions,
    PageDefaults,
    PageSpec,
    Project,
    normalize_rotation,
)


def make_project(tmp_path: Path) -> Project:
    pdf_a = tmp_path / "articles" / "01_特集.pdf"
    pdf_b = tmp_path / "articles" / "02_連載.pdf"
    pdf_a.parent.mkdir(parents=True, exist_ok=True)
    pdf_a.write_bytes(b"%PDF-1.4 dummy")
    pdf_b.write_bytes(b"%PDF-1.4 dummy")

    defaults = PageDefaults()
    project = Project(
        title="テストマガジン",
        issue="2026年8月号",
        articles=[
            Article.create(pdf_a, 3, defaults),
            Article.create(pdf_b, 2, defaults),
        ],
    )
    return project


# ---- PageSpec ---------------------------------------------------------


def test_page_spec_output_count_default():
    # 俯瞰1枚 + 4分割 = 5枚
    assert PageSpec("quad_2col", include_overview=True).output_page_count() == 5


def test_page_spec_output_count_without_overview():
    assert PageSpec("quad_2col", include_overview=False).output_page_count() == 4


def test_page_spec_full_layout_collapses_to_one_page():
    """full は俯瞰と分割が同じ絵なので、俯瞰ONでも1枚。"""
    assert PageSpec("full", include_overview=True).output_page_count() == 1
    assert PageSpec("full", include_overview=False).output_page_count() == 1


def test_page_spec_six_split():
    assert PageSpec("six_2col", include_overview=True).output_page_count() == 7


def test_page_spec_from_dict_falls_back_on_unknown_layout():
    spec = PageSpec.from_dict({"layout": "存在しない", "overview": False})
    assert spec.layout_id == layouts.DEFAULT_LAYOUT_ID
    assert spec.include_overview is False


def test_page_spec_from_dict_uses_fallback_for_missing_keys():
    fallback = PageSpec("half_v", include_overview=False)
    spec = PageSpec.from_dict({}, fallback)
    assert spec == fallback


# ---- 回転 -------------------------------------------------------------


def test_page_spec_defaults_to_no_rotation():
    assert PageSpec().rotate == ROTATION_NONE


def test_rotation_does_not_change_output_page_count():
    """回転は見た目の向きだけを変える。枚数には影響しない。"""
    for rotation in (ROTATION_NONE, ROTATION_CW, ROTATION_CCW):
        assert PageSpec("half_v", rotate=rotation).output_page_count() == 3


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, ROTATION_NONE),
        (90, ROTATION_CW),
        (270, ROTATION_CCW),
        (-90, ROTATION_CCW),  # 負の角度も正規化する
        (450, ROTATION_CW),  # 360を超える角度も
        (180, ROTATION_NONE),  # 扱わない角度は既定へ
        ("cw", ROTATION_NONE),
        (None, ROTATION_NONE),
    ],
)
def test_normalize_rotation(value, expected):
    assert normalize_rotation(value) == expected


def test_normalize_rotation_uses_fallback():
    assert normalize_rotation("bogus", fallback=ROTATION_CW) == ROTATION_CW


def test_page_spec_from_dict_normalizes_rotation():
    assert PageSpec.from_dict({"rotate": 90}).rotate == ROTATION_CW
    assert PageSpec.from_dict({"rotate": 45}).rotate == ROTATION_NONE


def test_page_spec_without_rotate_key_reads_as_none():
    """回転を持たない旧プロジェクトが読める。"""
    spec = PageSpec.from_dict({"layout": "half_v", "overview": True})
    assert spec.rotate == ROTATION_NONE


def test_page_spec_rotation_label():
    assert PageSpec(rotate=ROTATION_NONE).rotation_label() == "なし"
    assert PageSpec(rotate=ROTATION_CW).rotation_label() == "右90°"
    assert PageSpec(rotate=ROTATION_CCW).rotation_label() == "左90°"


def test_page_defaults_carries_rotation_to_new_pages():
    defaults = PageDefaults(layout_id="half_v", rotate=ROTATION_CW)
    assert defaults.to_page_spec() == PageSpec("half_v", include_overview=True, rotate=90)


def test_page_defaults_normalizes_rotation():
    assert PageDefaults.from_dict({"rotate": -90}).rotate == ROTATION_CCW
    assert PageDefaults.from_dict({"rotate": 33}).rotate == ROTATION_NONE


# ---- ImageOptions / PageDefaults --------------------------------------


def test_image_options_clamps_values():
    opts = ImageOptions.from_dict(
        {"format": "jpg", "jpeg_quality": 500, "gray_levels": 1, "gamma": 99.0}
    )
    assert opts.format == "jpeg"
    assert opts.jpeg_quality == 100
    assert opts.gray_levels == 2
    assert opts.gamma == pytest.approx(3.0)


def test_image_options_unknown_format_falls_back_to_png():
    assert ImageOptions.from_dict({"format": "webp"}).format == "png"


def test_page_defaults_clamps_overlap():
    assert PageDefaults.from_dict({"overlap": 10.0}).overlap == layouts.MAX_OVERLAP
    assert PageDefaults.from_dict({"overlap": -1.0}).overlap == 0.0


def test_page_defaults_from_garbage_returns_defaults():
    assert PageDefaults.from_dict("not a dict") == PageDefaults()


# ---- Article ----------------------------------------------------------


def test_article_create_uses_stem_as_title(tmp_path):
    pdf = tmp_path / "巻頭特集.pdf"
    pdf.write_bytes(b"x")
    article = Article.create(pdf, 4, PageDefaults())
    assert article.title == "巻頭特集"
    assert len(article.pages) == 4


def test_article_sync_page_count_grows_and_shrinks(tmp_path):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"x")
    article = Article.create(pdf, 2, PageDefaults())
    article.sync_page_count(5, PageDefaults())
    assert len(article.pages) == 5
    article.sync_page_count(1, PageDefaults())
    assert len(article.pages) == 1


def test_article_output_page_count(tmp_path):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"x")
    article = Article.create(pdf, 3, PageDefaults())
    article.pages[1] = PageSpec("full")
    # 5 + 1 + 5
    assert article.output_page_count() == 11


# ---- Project ラウンドトリップ -------------------------------------------


def test_project_round_trip_preserves_everything(tmp_path):
    project = make_project(tmp_path)
    project.articles[0].title = "巻頭インタビュー"
    project.articles[0].pages[1] = PageSpec("full", include_overview=False)
    project.articles[1].pages[0] = PageSpec("six_2col", include_overview=True)
    project.image = ImageOptions(format="jpeg", jpeg_quality=70)
    project.defaults = PageDefaults(
        layout_id="half_v", rotate=ROTATION_CW, overlap=0.05, auto_trim=False
    )

    path = tmp_path / "book.inkflow.json"
    project.save(path)
    loaded = Project.load(path)

    assert loaded.title == "テストマガジン"
    assert loaded.issue == "2026年8月号"
    assert [a.title for a in loaded.articles] == ["巻頭インタビュー", "02_連載"]
    assert loaded.articles[0].pages[1] == PageSpec("full", include_overview=False)
    assert loaded.articles[1].pages[0] == PageSpec("six_2col", include_overview=True)
    assert loaded.image == project.image
    assert loaded.defaults == project.defaults
    assert loaded.articles[0].path == project.articles[0].path


def test_project_round_trip_preserves_per_page_rotation(tmp_path):
    project = make_project(tmp_path)
    project.articles[0].pages[0] = PageSpec("half_v", rotate=ROTATION_CW)
    project.articles[0].pages[2] = PageSpec("third_v", rotate=ROTATION_CCW)

    path = tmp_path / "rotated.inkflow.json"
    project.save(path)
    loaded = Project.load(path)

    assert loaded.articles[0].pages[0].rotate == ROTATION_CW
    assert loaded.articles[0].pages[1].rotate == ROTATION_NONE
    assert loaded.articles[0].pages[2].rotate == ROTATION_CCW


def test_project_saves_relative_paths(tmp_path):
    project = make_project(tmp_path)
    path = tmp_path / "book.inkflow.json"
    project.save(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    stored = data["articles"][0]["path"]
    assert not Path(stored).is_absolute()
    assert stored == "articles/01_特集.pdf"


def test_project_survives_directory_move(tmp_path):
    """プロジェクトごと別ディレクトリへ移しても参照が壊れない。"""
    import shutil

    project = make_project(tmp_path)
    path = tmp_path / "book.inkflow.json"
    project.save(path)

    moved = tmp_path.parent / (tmp_path.name + "_moved")
    shutil.copytree(tmp_path, moved)

    loaded = Project.load(moved / "book.inkflow.json")
    loaded.validate_sources()
    assert loaded.articles[0].path.parent == moved / "articles"


def test_project_load_invalid_json(tmp_path):
    path = tmp_path / "broken.inkflow.json"
    path.write_text("{ not json", encoding="utf-8")
    with pytest.raises(ProjectFormatError, match="JSONが不正"):
        Project.load(path)


def test_project_load_missing_file(tmp_path):
    with pytest.raises(ProjectFormatError, match="読み込めません"):
        Project.load(tmp_path / "nope.inkflow.json")


def test_project_load_non_object(tmp_path):
    path = tmp_path / "list.inkflow.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(ProjectFormatError, match="構造が不正"):
        Project.load(path)


def test_project_load_article_without_path(tmp_path):
    path = tmp_path / "p.inkflow.json"
    path.write_text(json.dumps({"articles": [{"title": "x"}]}), encoding="utf-8")
    with pytest.raises(ProjectFormatError, match="'path' がありません"):
        Project.load(path)


def test_project_load_fills_missing_keys_with_defaults(tmp_path):
    path = tmp_path / "minimal.inkflow.json"
    path.write_text(json.dumps({"title": "最小"}), encoding="utf-8")
    loaded = Project.load(path)
    assert loaded.title == "最小"
    assert loaded.defaults == PageDefaults()
    assert loaded.image == ImageOptions()
    assert loaded.articles == []


def test_project_load_ignores_unknown_keys(tmp_path):
    path = tmp_path / "future.inkflow.json"
    path.write_text(
        json.dumps({"title": "未来版", "未知フィールド": {"a": 1}, "version": 99}),
        encoding="utf-8",
    )
    assert Project.load(path).title == "未来版"


def test_project_load_unknown_device_falls_back(tmp_path):
    path = tmp_path / "d.inkflow.json"
    path.write_text(json.dumps({"device": "kobo-libra"}), encoding="utf-8")
    assert Project.load(path).device().id == "paperwhite_11"


def test_project_validate_sources_reports_missing(tmp_path):
    project = make_project(tmp_path)
    project.articles[1].path.unlink()
    with pytest.raises(ProjectFormatError, match="見つかりません"):
        project.validate_sources()


def test_project_book_title():
    assert Project(title="A", issue="2026年8月号").book_title() == "A 2026年8月号"
    assert Project(title="A", issue="").book_title() == "A"


def test_project_output_page_count(tmp_path):
    project = make_project(tmp_path)
    # 3ページ + 2ページ、すべて既定（5枚）
    assert project.output_page_count() == 25


def test_apply_layout_to_all(tmp_path):
    project = make_project(tmp_path)
    project.apply_layout_to_all(PageSpec("half_v", include_overview=False))
    assert all(
        page == PageSpec("half_v", include_overview=False)
        for article in project.articles
        for page in article.pages
    )


def test_apply_layout_to_article_only(tmp_path):
    project = make_project(tmp_path)
    project.apply_layout_to_article(0, PageSpec("full"))
    assert all(page.layout_id == "full" for page in project.articles[0].pages)
    assert all(page.layout_id == "quad_2col" for page in project.articles[1].pages)


def test_apply_layout_creates_independent_copies(tmp_path):
    project = make_project(tmp_path)
    project.apply_layout_to_all(PageSpec("half_v"))
    project.articles[0].pages[0].layout_id = "full"
    assert project.articles[0].pages[1].layout_id == "half_v"
