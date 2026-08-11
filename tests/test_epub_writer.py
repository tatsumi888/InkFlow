import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone

import pytest
from PIL import Image

from inkflow import devices, epub_writer
from inkflow.errors import EpubWriteError
from inkflow.models import ImageOptions

OPF_NS = {"opf": "http://www.idpf.org/2007/opf", "dc": "http://purl.org/dc/elements/1.1/"}
NCX_NS = {"ncx": "http://www.daisy.org/z3986/2005/ncx/"}
XHTML_NS = {"x": "http://www.w3.org/1999/xhtml"}

DEVICE = devices.get_device("custom:120x160")


def make_pages(
    count: int,
    bookmarks: dict[int, str] | None = None,
    overview_bookmarks: dict[int, str] | None = None,
):
    bookmarks = bookmarks or {}
    overview_bookmarks = overview_bookmarks or {}
    for index in range(count):
        image = Image.new("L", DEVICE.size, 255 - index)
        yield (image, bookmarks.get(index), overview_bookmarks.get(index))


def write(
    tmp_path,
    page_count=4,
    bookmarks=None,
    overview_bookmarks=None,
    options=None,
    **kwargs,
):
    output = tmp_path / "book.epub"
    summary = epub_writer.write_epub(
        output,
        title="月刊テスト 2026年8月号",
        device=DEVICE,
        options=options or ImageOptions(),
        cover_image=Image.new("L", DEVICE.size, 200),
        pages=make_pages(page_count, bookmarks, overview_bookmarks),
        identifier="urn:uuid:00000000-0000-0000-0000-000000000000",
        modified=datetime(2026, 8, 10, tzinfo=timezone.utc),
        **kwargs,
    )
    return output, summary


# ---- ZIP 構造 ---------------------------------------------------------


def test_mimetype_is_first_entry_and_stored(tmp_path):
    output, _ = write(tmp_path)
    with zipfile.ZipFile(output) as archive:
        infos = archive.infolist()
        assert infos[0].filename == "mimetype"
        assert infos[0].compress_type == zipfile.ZIP_STORED
        assert archive.read("mimetype") == b"application/epub+zip"


def test_archive_is_valid_zip(tmp_path):
    output, _ = write(tmp_path)
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None


def test_container_points_at_content_opf(tmp_path):
    output, _ = write(tmp_path)
    with zipfile.ZipFile(output) as archive:
        container = archive.read("META-INF/container.xml").decode("utf-8")
    assert 'full-path="OEBPS/content.opf"' in container


def test_all_declared_files_exist(tmp_path):
    output, _ = write(tmp_path, page_count=3)
    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        opf = ET.fromstring(archive.read("OEBPS/content.opf"))
    for item in opf.findall("opf:manifest/opf:item", OPF_NS):
        assert f"OEBPS/{item.get('href')}" in names


def test_images_are_stored_without_recompression(tmp_path):
    output, _ = write(tmp_path)
    with zipfile.ZipFile(output) as archive:
        for info in archive.infolist():
            if info.filename.startswith("OEBPS/images/"):
                assert info.compress_type == zipfile.ZIP_STORED


# ---- content.opf ------------------------------------------------------


def test_opf_declares_fixed_layout(tmp_path):
    output, _ = write(tmp_path)
    with zipfile.ZipFile(output) as archive:
        opf = archive.read("OEBPS/content.opf").decode("utf-8")
    assert '<meta property="rendition:layout">pre-paginated</meta>' in opf
    assert '<meta name="fixed-layout" content="true"/>' in opf
    assert '<meta name="original-resolution" content="120x160"/>' in opf
    assert '<meta name="book-type" content="comic"/>' in opf
    assert '<meta name="region-mag" content="false"/>' in opf


def test_opf_metadata_values(tmp_path):
    output, _ = write(tmp_path)
    with zipfile.ZipFile(output) as archive:
        opf = ET.fromstring(archive.read("OEBPS/content.opf"))
    assert opf.find("opf:metadata/dc:title", OPF_NS).text == "月刊テスト 2026年8月号"
    assert opf.find("opf:metadata/dc:language", OPF_NS).text == "ja"
    assert (
        opf.find("opf:metadata/dc:identifier", OPF_NS).text
        == "urn:uuid:00000000-0000-0000-0000-000000000000"
    )


def test_spine_counts_cover_plus_pages(tmp_path):
    output, summary = write(tmp_path, page_count=7)
    with zipfile.ZipFile(output) as archive:
        opf = ET.fromstring(archive.read("OEBPS/content.opf"))
    itemrefs = opf.findall("opf:spine/opf:itemref", OPF_NS)
    assert len(itemrefs) == 8  # 表紙1 + 本文7
    assert summary.page_count == 8


def test_every_itemref_is_pre_paginated(tmp_path):
    output, _ = write(tmp_path)
    with zipfile.ZipFile(output) as archive:
        opf = ET.fromstring(archive.read("OEBPS/content.opf"))
    for itemref in opf.findall("opf:spine/opf:itemref", OPF_NS):
        assert itemref.get("properties") == "rendition:layout-pre-paginated"


def test_spine_direction_is_left_to_right(tmp_path):
    output, _ = write(tmp_path)
    with zipfile.ZipFile(output) as archive:
        opf = ET.fromstring(archive.read("OEBPS/content.opf"))
    assert opf.find("opf:spine", OPF_NS).get("page-progression-direction") == "ltr"


def test_cover_is_declared_and_first(tmp_path):
    output, _ = write(tmp_path)
    with zipfile.ZipFile(output) as archive:
        opf = ET.fromstring(archive.read("OEBPS/content.opf"))
    cover_items = [
        item
        for item in opf.findall("opf:manifest/opf:item", OPF_NS)
        if item.get("properties") == "cover-image"
    ]
    assert len(cover_items) == 1
    assert cover_items[0].get("id") == "cover-image"
    assert opf.find("opf:spine/opf:itemref", OPF_NS).get("idref") == "page-cover"


# ---- 目次（しおり） ----------------------------------------------------


def test_nav_and_ncx_contain_every_bookmark(tmp_path):
    bookmarks = {0: "巻頭特集", 2: "インタビュー", 5: "連載"}
    output, summary = write(tmp_path, page_count=8, bookmarks=bookmarks)
    with zipfile.ZipFile(output) as archive:
        nav = ET.fromstring(archive.read("OEBPS/nav.xhtml"))
        ncx = ET.fromstring(archive.read("OEBPS/toc.ncx"))

    nav_labels = [a.text for a in nav.findall(".//x:nav/x:ol/x:li/x:a", XHTML_NS)]
    ncx_labels = [t.text for t in ncx.findall(".//ncx:navLabel/ncx:text", NCX_NS)]
    assert nav_labels == ["巻頭特集", "インタビュー", "連載"]
    assert ncx_labels == nav_labels
    assert summary.bookmark_count == 3


def test_bookmark_links_to_the_right_page(tmp_path):
    output, _ = write(tmp_path, page_count=8, bookmarks={0: "A", 3: "B"})
    with zipfile.ZipFile(output) as archive:
        nav = ET.fromstring(archive.read("OEBPS/nav.xhtml"))
    hrefs = [a.get("href") for a in nav.findall(".//x:nav/x:ol/x:li/x:a", XHTML_NS)]
    assert hrefs == ["text/p0000.xhtml", "text/p0003.xhtml"]


def test_bookmark_targets_exist_in_archive(tmp_path):
    output, _ = write(tmp_path, page_count=4, bookmarks={1: "記事"})
    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        nav = ET.fromstring(archive.read("OEBPS/nav.xhtml"))
    for anchor in nav.findall(".//x:nav/x:ol/x:li/x:a", XHTML_NS):
        assert f"OEBPS/{anchor.get('href')}" in names


def test_falls_back_to_title_when_no_bookmarks(tmp_path):
    output, summary = write(tmp_path, page_count=3, bookmarks={})
    with zipfile.ZipFile(output) as archive:
        nav = ET.fromstring(archive.read("OEBPS/nav.xhtml"))
    labels = [a.text for a in nav.findall(".//x:nav/x:ol/x:li/x:a", XHTML_NS)]
    assert labels == ["月刊テスト 2026年8月号"]
    assert summary.bookmark_count == 1


# ---- 俯瞰しおり（記事しおりの子項目） -------------------------------------


def test_overview_bookmark_nests_under_article_in_nav(tmp_path):
    output, summary = write(
        tmp_path,
        page_count=5,
        bookmarks={0: "巻頭特集"},
        overview_bookmarks={0: "1ページ目", 2: "3ページ目"},
    )
    with zipfile.ZipFile(output) as archive:
        nav = ET.fromstring(archive.read("OEBPS/nav.xhtml"))

    # トップレベルは記事しおりだけ（既存の挙動を壊していないこと）。
    top_labels = [a.text for a in nav.findall(".//x:nav/x:ol/x:li/x:a", XHTML_NS)]
    assert top_labels == ["巻頭特集"]

    # 俯瞰しおりは、その記事の <li> の中の入れ子 <ol> に入る。
    nested_anchors = nav.findall(".//x:nav/x:ol/x:li/x:ol/x:li/x:a", XHTML_NS)
    nested = [(a.text, a.get("href")) for a in nested_anchors]
    assert nested == [
        ("1ページ目", "text/p0000.xhtml"),
        ("3ページ目", "text/p0002.xhtml"),
    ]


def test_overview_bookmark_nests_under_article_in_ncx(tmp_path):
    output, _ = write(
        tmp_path,
        page_count=3,
        bookmarks={0: "巻頭特集"},
        overview_bookmarks={0: "1ページ目", 1: "2ページ目"},
    )
    with zipfile.ZipFile(output) as archive:
        ncx = ET.fromstring(archive.read("OEBPS/toc.ncx"))

    top_points = ncx.findall("ncx:navMap/ncx:navPoint", NCX_NS)
    assert len(top_points) == 1
    assert top_points[0].find("ncx:navLabel/ncx:text", NCX_NS).text == "巻頭特集"

    child_points = top_points[0].findall("ncx:navPoint", NCX_NS)
    child_labels = [p.find("ncx:navLabel/ncx:text", NCX_NS).text for p in child_points]
    assert child_labels == ["1ページ目", "2ページ目"]

    # playOrder は親→子の順で連番になっていること。
    play_orders = [p.get("playOrder") for p in (top_points[0], *child_points)]
    assert play_orders == ["1", "2", "3"]

    assert ncx.find("ncx:head/ncx:meta[@name='dtb:depth']", NCX_NS).get("content") == "2"


def test_bookmark_count_includes_nested_overview_bookmarks(tmp_path):
    _, summary = write(
        tmp_path,
        page_count=4,
        bookmarks={0: "記事1", 2: "記事2"},
        overview_bookmarks={0: "1ページ目", 1: "2ページ目", 2: "3ページ目"},
    )
    # 記事しおり2件 + 俯瞰しおり3件 = 5件。
    assert summary.bookmark_count == 5


def test_dtb_depth_stays_one_without_overview_bookmarks(tmp_path):
    output, _ = write(tmp_path, page_count=3, bookmarks={0: "記事1"})
    with zipfile.ZipFile(output) as archive:
        ncx = ET.fromstring(archive.read("OEBPS/toc.ncx"))
    assert ncx.find("ncx:head/ncx:meta[@name='dtb:depth']", NCX_NS).get("content") == "1"


def test_overview_bookmark_without_preceding_article_becomes_top_level(tmp_path):
    """記事しおりより前に俯瞰しおりが来る想定外のケースでも取りこぼさない。"""
    output, summary = write(tmp_path, page_count=2, overview_bookmarks={0: "1ページ目"})
    with zipfile.ZipFile(output) as archive:
        nav = ET.fromstring(archive.read("OEBPS/nav.xhtml"))
    top_labels = [a.text for a in nav.findall(".//x:nav/x:ol/x:li/x:a", XHTML_NS)]
    assert top_labels == ["1ページ目"]
    assert summary.bookmark_count == 1


def test_special_characters_are_escaped(tmp_path):
    output, _ = write(tmp_path, page_count=2, bookmarks={0: 'A & B <C> "D"'})
    with zipfile.ZipFile(output) as archive:
        nav = ET.fromstring(archive.read("OEBPS/nav.xhtml"))
        ET.fromstring(archive.read("OEBPS/toc.ncx"))  # 壊れていないこと
    assert nav.find(".//x:nav/x:ol/x:li/x:a", XHTML_NS).text == 'A & B <C> "D"'


# ---- ページXHTML ------------------------------------------------------


def test_page_xhtml_declares_viewport_and_image(tmp_path):
    output, _ = write(tmp_path, page_count=1)
    with zipfile.ZipFile(output) as archive:
        page = archive.read("OEBPS/text/p0000.xhtml").decode("utf-8")
    assert 'content="width=120, height=160"' in page
    assert 'src="../images/p0000.png"' in page
    assert 'width="120" height="160"' in page


def test_page_xhtml_is_well_formed(tmp_path):
    output, _ = write(tmp_path, page_count=2)
    with zipfile.ZipFile(output) as archive:
        for name in ("OEBPS/text/cover.xhtml", "OEBPS/text/p0001.xhtml"):
            ET.fromstring(archive.read(name))


def test_css_matches_device_size(tmp_path):
    output, _ = write(tmp_path)
    with zipfile.ZipFile(output) as archive:
        css = archive.read("OEBPS/css/style.css").decode("utf-8")
    assert "width: 120px;" in css
    assert "height: 160px;" in css
    assert "margin: 0;" in css


# ---- 出力形式・エラー --------------------------------------------------


def test_jpeg_output_uses_jpg_extension(tmp_path):
    output, _ = write(tmp_path, page_count=2, options=ImageOptions(format="jpeg"))
    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        opf = archive.read("OEBPS/content.opf").decode("utf-8")
    assert "OEBPS/images/p0000.jpg" in names
    assert 'media-type="image/jpeg"' in opf


def test_summary_reports_file_size(tmp_path):
    output, summary = write(tmp_path, page_count=3)
    assert summary.size_bytes == output.stat().st_size
    assert summary.size_mb > 0


def test_write_to_unwritable_path_raises(tmp_path):
    directory = tmp_path / "as-directory"
    directory.mkdir()
    with pytest.raises(EpubWriteError, match="書き出せません"):
        epub_writer.write_epub(
            directory,
            title="x",
            device=DEVICE,
            options=ImageOptions(),
            cover_image=Image.new("L", DEVICE.size, 255),
            pages=make_pages(1),
        )


def test_pages_with_bookmarks_maps_article_starts():
    class Fake:
        def __init__(self, title, start, source_page_index=0, is_overview=False):
            self.image = title
            self.article_title = title
            self.is_article_start = start
            self.source_page_index = source_page_index
            self.is_overview = is_overview

    result = list(
        epub_writer.pages_with_bookmarks(
            [Fake("A", True), Fake("A", False), Fake("B", True)]
        )
    )
    assert result == [("A", "A", None), ("A", None, None), ("B", "B", None)]


def test_pages_with_bookmarks_maps_overview_pages():
    """俯瞰ページには、原稿ページ番号（1始まり）をタイトルにした俯瞰しおりが付く。"""

    class Fake:
        def __init__(self, title, start, source_page_index, is_overview):
            self.image = title
            self.article_title = title
            self.is_article_start = start
            self.source_page_index = source_page_index
            self.is_overview = is_overview

    result = list(
        epub_writer.pages_with_bookmarks(
            [
                Fake("A", True, source_page_index=0, is_overview=True),
                Fake("A", False, source_page_index=0, is_overview=False),
                Fake("A", False, source_page_index=1, is_overview=True),
            ]
        )
    )
    assert result == [
        ("A", "A", "1ページ目"),
        ("A", None, None),
        ("A", None, "2ページ目"),
    ]
