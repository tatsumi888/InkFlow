"""固定レイアウトEPUB（EPUB3 pre-paginated）の書き出し。

仕様が単純な「1画像＝1ページ」しか扱わないので、外部ライブラリを使わず zipfile で
直接組み立てる。Kindle 固有メタデータを完全に制御したいのも理由のひとつ。

Send to Kindle の変換系は EPUB3 の nav.xhtml を見る場合と、旧来の toc.ncx を見る
場合があるため、目次は**両方**書き出す。
"""

from __future__ import annotations

import itertools
import uuid
import zipfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from PIL import Image

from . import imaging
from .devices import Device
from .errors import EpubWriteError
from .models import ImageOptions

MIMETYPE = "application/epub+zip"

CSS = """@page {{ margin: 0; padding: 0; }}
html, body {{
  margin: 0;
  padding: 0;
  background-color: #ffffff;
}}
div.page {{
  margin: 0;
  padding: 0;
  width: {width}px;
  height: {height}px;
}}
img.page-image {{
  margin: 0;
  padding: 0;
  display: block;
  width: {width}px;
  height: {height}px;
}}
"""

CONTAINER_XML = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

PAGE_XHTML = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" \
lang="{language}" xml:lang="{language}">
<head>
  <meta charset="utf-8"/>
  <title>{title}</title>
  <meta name="viewport" content="width={width}, height={height}"/>
  <link rel="stylesheet" type="text/css" href="../css/style.css"/>
</head>
<body>
  <div class="page"><img class="page-image" src="../images/{image_name}" alt="" \
width="{width}" height="{height}"/></div>
</body>
</html>
"""


@dataclass(frozen=True)
class _PageEntry:
    page_id: str
    image_id: str
    xhtml_href: str
    image_href: str
    media_type: str


@dataclass
class _Bookmark:
    """目次の1項目。記事しおりは俯瞰ページの子しおりを持つことがある（1階層のみ）。"""

    label: str
    href: str
    children: list[tuple[str, str]] = field(default_factory=list)


class EpubWriteSummary:
    """書き出し結果の要約。"""

    def __init__(self, path: Path, page_count: int, bookmark_count: int, size_bytes: int):
        self.path = path
        self.page_count = page_count
        self.bookmark_count = bookmark_count
        self.size_bytes = size_bytes

    @property
    def size_mb(self) -> float:
        return self.size_bytes / (1024 * 1024)

    def __repr__(self) -> str:  # pragma: no cover - デバッグ用
        return (
            f"EpubWriteSummary(path={self.path!s}, pages={self.page_count}, "
            f"bookmarks={self.bookmark_count}, size_mb={self.size_mb:.1f})"
        )


def write_epub(
    output_path: Path,
    title: str,
    device: Device,
    options: ImageOptions,
    cover_image: Image.Image,
    pages: Iterable[tuple[Image.Image, str | None, str | None]],
    *,
    language: str = "ja",
    author: str = "InkFlow",
    identifier: str | None = None,
    modified: datetime | None = None,
) -> EpubWriteSummary:
    """固定レイアウトEPUBを書き出す。

    ``pages`` は ``(画像, 記事しおり名 or None, 俯瞰しおり名 or None)`` の列。
    記事しおり名が入っている要素がその記事の先頭ページになり、目次のトップ
    レベル項目になる。俯瞰しおり名が入っている要素は、直近の記事しおりの
    子項目（1階層のみ）として目次に現れる。
    """
    output_path = Path(output_path)
    identifier = identifier or f"urn:uuid:{uuid.uuid4()}"
    modified = modified or datetime.now(timezone.utc)

    extension = imaging.extension_for(options)
    media_type = imaging.media_type_for(options)

    entries: list[_PageEntry] = []
    bookmarks: list[_Bookmark] = []

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as archive:
            # mimetype は必ず先頭・無圧縮で置く（EPUB の要件）。
            archive.writestr(
                zipfile.ZipInfo("mimetype"), MIMETYPE, compress_type=zipfile.ZIP_STORED
            )
            archive.writestr("META-INF/container.xml", CONTAINER_XML)
            archive.writestr(
                "OEBPS/css/style.css",
                CSS.format(width=device.width, height=device.height),
            )

            cover_name = f"cover{extension}"
            _write_image(archive, f"OEBPS/images/{cover_name}", cover_image, options)
            archive.writestr(
                "OEBPS/text/cover.xhtml",
                PAGE_XHTML.format(
                    language=language,
                    title=escape("表紙"),
                    width=device.width,
                    height=device.height,
                    image_name=cover_name,
                ),
            )
            entries.append(
                _PageEntry(
                    page_id="page-cover",
                    image_id="cover-image",
                    xhtml_href="text/cover.xhtml",
                    image_href=f"images/{cover_name}",
                    media_type=media_type,
                )
            )

            for index, (image, article_bookmark, overview_bookmark) in enumerate(pages):
                name = f"p{index:04d}"
                image_name = f"{name}{extension}"
                _write_image(archive, f"OEBPS/images/{image_name}", image, options)
                archive.writestr(
                    f"OEBPS/text/{name}.xhtml",
                    PAGE_XHTML.format(
                        language=language,
                        title=escape(name),
                        width=device.width,
                        height=device.height,
                        image_name=image_name,
                    ),
                )
                entries.append(
                    _PageEntry(
                        page_id=f"page-{name}",
                        image_id=f"img-{name}",
                        xhtml_href=f"text/{name}.xhtml",
                        image_href=f"images/{image_name}",
                        media_type=media_type,
                    )
                )
                href = f"text/{name}.xhtml"
                if article_bookmark:
                    bookmarks.append(_Bookmark(article_bookmark, href))
                if overview_bookmark:
                    # 記事しおりより前に俯瞰しおりが来ることは無いはずだが、安全側
                    # として、その場合はトップレベル項目として取りこぼさない。
                    if bookmarks:
                        bookmarks[-1].children.append((overview_bookmark, href))
                    else:
                        bookmarks.append(_Bookmark(overview_bookmark, href))

            if not bookmarks:
                bookmarks.append(_Bookmark(title, "text/cover.xhtml"))

            archive.writestr(
                "OEBPS/content.opf",
                _build_opf(
                    title=title,
                    language=language,
                    author=author,
                    identifier=identifier,
                    modified=modified,
                    device=device,
                    entries=entries,
                ),
            )
            archive.writestr("OEBPS/nav.xhtml", _build_nav(title, language, bookmarks))
            archive.writestr("OEBPS/toc.ncx", _build_ncx(title, identifier, bookmarks))
    except OSError as e:
        raise EpubWriteError(f"EPUBを書き出せません: {output_path}（{e}）") from e

    return EpubWriteSummary(
        path=output_path,
        page_count=len(entries),
        bookmark_count=sum(1 + len(b.children) for b in bookmarks),
        size_bytes=output_path.stat().st_size,
    )


def _write_image(
    archive: zipfile.ZipFile,
    name: str,
    image: Image.Image,
    options: ImageOptions,
) -> None:
    """PNG/JPEG は既に圧縮済みなので、ZIP 側では再圧縮しない。"""
    archive.writestr(
        zipfile.ZipInfo(name),
        imaging.encode_image(image, options),
        compress_type=zipfile.ZIP_STORED,
    )


def _build_opf(
    *,
    title: str,
    language: str,
    author: str,
    identifier: str,
    modified: datetime,
    device: Device,
    entries: list[_PageEntry],
) -> str:
    manifest_lines = [
        '    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>',
        '    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" '
        'properties="nav"/>',
        '    <item id="css" href="css/style.css" media-type="text/css"/>',
    ]
    spine_lines: list[str] = []
    for index, entry in enumerate(entries):
        properties = ' properties="cover-image"' if index == 0 else ""
        manifest_lines.append(
            f'    <item id="{entry.image_id}" href="{entry.image_href}" '
            f'media-type="{entry.media_type}"{properties}/>'
        )
        manifest_lines.append(
            f'    <item id="{entry.page_id}" href="{entry.xhtml_href}" '
            'media-type="application/xhtml+xml"/>'
        )
        spine_lines.append(
            f'    <itemref idref="{entry.page_id}" linear="yes" '
            'properties="rendition:layout-pre-paginated"/>'
        )

    timestamp = modified.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest = "\n".join(manifest_lines)
    spine = "\n".join(spine_lines)

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="BookId"
         prefix="rendition: http://www.idpf.org/vocab/rendition/#">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="BookId">{escape(identifier)}</dc:identifier>
    <dc:title>{escape(title)}</dc:title>
    <dc:language>{escape(language)}</dc:language>
    <dc:creator>{escape(author)}</dc:creator>
    <meta property="dcterms:modified">{timestamp}</meta>
    <meta property="rendition:layout">pre-paginated</meta>
    <meta property="rendition:spread">none</meta>
    <meta property="rendition:orientation">portrait</meta>
    <meta name="cover" content="cover-image"/>
    <meta name="fixed-layout" content="true"/>
    <meta name="original-resolution" content="{device.width}x{device.height}"/>
    <meta name="book-type" content="comic"/>
    <meta name="zero-gutter" content="true"/>
    <meta name="zero-margin" content="true"/>
    <meta name="region-mag" content="false"/>
    <meta name="primary-writing-mode" content="horizontal-lr"/>
  </metadata>
  <manifest>
{manifest}
  </manifest>
  <spine toc="ncx" page-progression-direction="ltr">
{spine}
  </spine>
</package>
"""


def _build_nav(title: str, language: str, bookmarks: list[_Bookmark]) -> str:
    def render(entry: _Bookmark) -> str:
        anchor = f'<a href={quoteattr(entry.href)}>{escape(entry.label)}</a>'
        if not entry.children:
            return f'      <li>{anchor}</li>'
        children = "\n".join(
            f'          <li><a href={quoteattr(href)}>{escape(label)}</a></li>'
            for label, href in entry.children
        )
        return f'      <li>{anchor}\n        <ol>\n{children}\n        </ol>\n      </li>'

    items = "\n".join(render(entry) for entry in bookmarks)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"
      lang="{escape(language)}" xml:lang="{escape(language)}">
<head>
  <meta charset="utf-8"/>
  <title>{escape(title)}</title>
</head>
<body>
  <nav epub:type="toc" id="toc">
    <h1>目次</h1>
    <ol>
{items}
    </ol>
  </nav>
</body>
</html>
"""


def _build_ncx(title: str, identifier: str, bookmarks: list[_Bookmark]) -> str:
    order = itertools.count(1)

    def render(label: str, href: str, children: list[tuple[str, str]]) -> str:
        point_id = next(order)
        lines = [
            f'    <navPoint id="navpoint-{point_id}" playOrder="{point_id}">',
            f'      <navLabel><text>{escape(label)}</text></navLabel>',
            f'      <content src={quoteattr(href)}/>',
        ]
        lines.extend(render(child_label, child_href, []) for child_label, child_href in children)
        lines.append('    </navPoint>')
        return "\n".join(lines)

    points = "\n".join(render(entry.label, entry.href, entry.children) for entry in bookmarks)
    depth = 2 if any(entry.children for entry in bookmarks) else 1
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE ncx PUBLIC "-//NISO//DTD ncx 2005-1//EN"
  "http://www.daisy.org/z3986/2005/ncx-2005-1.dtd">
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head>
    <meta name="dtb:uid" content="{escape(identifier)}"/>
    <meta name="dtb:depth" content="{depth}"/>
    <meta name="dtb:totalPageCount" content="0"/>
    <meta name="dtb:maxPageNumber" content="0"/>
  </head>
  <docTitle><text>{escape(title)}</text></docTitle>
  <navMap>
{points}
  </navMap>
</ncx>
"""


def pages_with_bookmarks(
    composed: Iterable["object"],
) -> Iterator[tuple[Image.Image, str | None, str | None]]:
    """ComposedPage の列を ``(画像, 記事しおり名 or None, 俯瞰しおり名 or None)`` に変換する。

    記事しおりはその記事の先頭出力ページに付く。俯瞰しおり（原稿ページ番号を
    タイトルにしたもの）は俯瞰ページ（``full`` レイアウトの1枚だけの出力も含む）
    に付き、``write_epub()`` 側で直近の記事しおりの子項目として目次に現れる。
    """
    for page in composed:
        article_bookmark = page.article_title if page.is_article_start else None
        overview_bookmark = f"{page.source_page_index + 1}ページ目" if page.is_overview else None
        yield (page.image, article_bookmark, overview_bookmark)
