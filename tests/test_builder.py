import io
import xml.etree.ElementTree as ET
import zipfile

import pytest
from PIL import Image

from inkflow import builder, composer
from inkflow.errors import InkFlowError, PdfLoadError, ProjectFormatError
from inkflow.models import PageDefaults, PageSpec, Project

from .conftest import make_pdf

OPF_NS = {"opf": "http://www.idpf.org/2007/opf"}
XHTML_NS = {"x": "http://www.w3.org/1999/xhtml"}

# テストを軽くするための小さな端末プロファイル。
TEST_DEVICE = "custom:150x200"


def make_project(pdfs, **kwargs) -> Project:
    project = builder.project_from_pdfs(
        pdfs, title="月刊テスト", issue="2026年8月号", device_id=TEST_DEVICE, **kwargs
    )
    return project


# ---- PDF の収集 --------------------------------------------------------


def test_collect_pdfs_sorts_numerically(tmp_path):
    for name in ("10_last.pdf", "2_second.pdf", "01_first.pdf"):
        make_pdf(tmp_path / name, page_count=1)
    names = [p.name for p in builder.collect_pdfs(tmp_path)]
    assert names == ["01_first.pdf", "2_second.pdf", "10_last.pdf"]


def test_collect_pdfs_missing_folder(tmp_path):
    with pytest.raises(InkFlowError, match="フォルダが見つかりません"):
        builder.collect_pdfs(tmp_path / "nope")


def test_collect_pdfs_empty_folder(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(InkFlowError, match="PDFが1件も見つかりません"):
        builder.collect_pdfs(empty)


def test_natural_key_orders_mixed_names(tmp_path):
    from pathlib import Path

    names = ["b2.pdf", "a10.pdf", "a2.pdf", "a1.pdf"]
    ordered = sorted((Path(n) for n in names), key=builder.natural_key)
    assert [p.name for p in ordered] == ["a1.pdf", "a2.pdf", "a10.pdf", "b2.pdf"]


# ---- プロジェクトの組み立て --------------------------------------------


def test_project_from_pdfs_reads_real_page_counts(article_pdfs):
    project = make_project(article_pdfs)
    assert [len(a.pages) for a in project.articles] == [2, 1, 3]
    assert [a.title for a in project.articles] == [
        "01_巻頭特集",
        "02_インタビュー",
        "03_連載",
    ]


def test_project_from_pdfs_applies_defaults(article_pdfs):
    defaults = PageDefaults(layout_id="half_v", include_overview=False)
    project = make_project(article_pdfs, defaults=defaults)
    assert all(
        page == PageSpec("half_v", include_overview=False)
        for article in project.articles
        for page in article.pages
    )


def test_add_article_at_index(article_pdfs):
    project = make_project(article_pdfs[:2])
    builder.add_article(project, article_pdfs[2], index=0)
    assert project.articles[0].title == "03_連載"
    assert len(project.articles) == 3


def test_add_article_rejects_non_pdf(tmp_path, article_pdfs):
    project = make_project(article_pdfs[:1])
    bogus = tmp_path / "notes.pdf"
    bogus.write_text("not a pdf", encoding="utf-8")
    with pytest.raises(PdfLoadError):
        builder.add_article(project, bogus)


def test_default_output_path_uses_book_title(tmp_path, article_pdfs):
    project = make_project(article_pdfs)
    assert builder.default_output_path(project, tmp_path).name == "月刊テスト 2026年8月号.epub"


def test_default_output_path_sanitizes_illegal_characters(tmp_path):
    project = Project(title='A/B:C*D?"', issue="<E>")
    assert "/" not in builder.default_output_path(project, tmp_path).name


# ---- EPUB 生成（統合） -------------------------------------------------


def build(tmp_path, project, name="out.epub"):
    output = tmp_path / name
    summary = builder.build_epub(project, output)
    return output, summary


def test_build_epub_page_count_matches_composer(tmp_path, article_pdfs):
    project = make_project(article_pdfs)
    expected = composer.total_output_pages(project)
    output, summary = build(tmp_path, project)
    assert summary.page_count == expected + 1  # 表紙のぶん
    assert output.is_file()


def test_build_epub_default_layout_gives_five_pages_per_source_page(tmp_path, article_pdfs):
    project = make_project(article_pdfs)
    _, summary = build(tmp_path, project)
    # 原稿 2+1+3 = 6ページ x 5枚 + 表紙1
    assert summary.page_count == 31


def test_build_epub_bookmarks_one_per_article(tmp_path, article_pdfs):
    project = make_project(article_pdfs)
    output, summary = build(tmp_path, project)
    assert summary.bookmark_count == 3

    with zipfile.ZipFile(output) as archive:
        nav = ET.fromstring(archive.read("OEBPS/nav.xhtml"))
    labels = [a.text for a in nav.findall(".//x:nav/x:ol/x:li/x:a", XHTML_NS)]
    assert labels == ["01_巻頭特集", "02_インタビュー", "03_連載"]


def test_build_epub_bookmark_points_at_article_first_page(tmp_path, article_pdfs):
    project = make_project(article_pdfs)
    output, _ = build(tmp_path, project)
    with zipfile.ZipFile(output) as archive:
        nav = ET.fromstring(archive.read("OEBPS/nav.xhtml"))
    hrefs = [a.get("href") for a in nav.findall(".//x:nav/x:ol/x:li/x:a", XHTML_NS)]
    # 2ページ記事=10枚、1ページ記事=5枚
    assert hrefs == ["text/p0000.xhtml", "text/p0010.xhtml", "text/p0015.xhtml"]


def test_build_epub_images_match_device_resolution(tmp_path, article_pdfs):
    project = make_project(article_pdfs[:1])
    output, _ = build(tmp_path, project)
    with zipfile.ZipFile(output) as archive:
        image_names = [n for n in archive.namelist() if n.startswith("OEBPS/images/")]
        assert image_names
        for name in image_names:
            with Image.open(io.BytesIO(archive.read(name))) as image:
                assert image.size == (150, 200)


def test_build_epub_respects_per_page_layout(tmp_path, article_pdfs):
    project = make_project(article_pdfs[:1])
    project.articles[0].pages[0] = PageSpec("full")
    project.articles[0].pages[1] = PageSpec("six_2col", include_overview=True)
    _, summary = build(tmp_path, project)
    assert summary.page_count == 1 + 1 + 7


def test_build_epub_progress_reaches_total(tmp_path, article_pdfs):
    project = make_project(article_pdfs)
    events: list[tuple[int, int]] = []
    builder.build_epub(project, tmp_path / "p.epub", on_progress=lambda d, t: events.append((d, t)))
    assert events[-1][0] == events[-1][1] == composer.total_output_pages(project)


def test_build_epub_without_articles(tmp_path):
    project = Project(title="空", device_id=TEST_DEVICE)
    with pytest.raises(InkFlowError, match="記事が1件も登録されていません"):
        builder.build_epub(project, tmp_path / "empty.epub")


def test_build_epub_with_missing_source(tmp_path, article_pdfs):
    project = make_project(article_pdfs)
    article_pdfs[1].unlink()
    with pytest.raises(ProjectFormatError, match="見つかりません"):
        builder.build_epub(project, tmp_path / "broken.epub")


def test_build_epub_creates_missing_output_directory(tmp_path, article_pdfs):
    project = make_project(article_pdfs[:1])
    output = tmp_path / "deep" / "nested" / "out.epub"
    builder.build_epub(project, output)
    assert output.is_file()


def test_build_epub_from_saved_project_round_trip(tmp_path, article_pdfs):
    project = make_project(article_pdfs)
    project.articles[1].title = "特別インタビュー"
    project_path = tmp_path / "book.inkflow.json"
    project.save(project_path)

    reloaded = Project.load(project_path)
    output, summary = build(tmp_path, reloaded, name="reloaded.epub")
    with zipfile.ZipFile(output) as archive:
        nav = ET.fromstring(archive.read("OEBPS/nav.xhtml"))
    labels = [a.text for a in nav.findall(".//x:nav/x:ol/x:li/x:a", XHTML_NS)]
    assert labels[1] == "特別インタビュー"
    assert summary.page_count == 31


def test_build_epub_uses_generated_cover(tmp_path, article_pdfs):
    project = make_project(article_pdfs[:1])
    output, _ = build(tmp_path, project)
    with zipfile.ZipFile(output) as archive:
        with Image.open(io.BytesIO(archive.read("OEBPS/images/cover.png"))) as cover_img:
            assert cover_img.size == (150, 200)
            assert cover_img.convert("L").getextrema()[0] < 128  # 何か描かれている
