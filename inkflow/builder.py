"""再ページ化と EPUB 書き出しを繋ぐ層。

CLI と GUI はどちらもここを呼ぶ。両者で出力が食い違わないようにするため、
経路を1本に絞っている。
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from pathlib import Path

from . import composer, cover, epub_writer, renderer
from .errors import InkFlowError
from .models import Article, PageDefaults, Project

ProgressCallback = Callable[[int, int], None]

PDF_GLOB = "*.pdf"

# ファイル名を人間の期待どおり（1, 2, 10 の順）に並べるための分割パターン。
_NUMBER_CHUNK = re.compile(r"(\d+)")


def natural_key(path: Path) -> tuple:
    """`01_`, `2.`, `10-` のような接頭辞を数値として扱う並び順キー。"""
    parts = _NUMBER_CHUNK.split(path.name.lower())
    return tuple(int(part) if part.isdigit() else part for part in parts)


def collect_pdfs(folder: Path) -> list[Path]:
    """フォルダ直下のPDFを自然順で集める。"""
    folder = Path(folder)
    if not folder.is_dir():
        raise InkFlowError(f"フォルダが見つかりません: {folder}")
    pdfs = sorted(folder.glob(PDF_GLOB), key=natural_key)
    if not pdfs:
        raise InkFlowError(f"PDFが1件も見つかりません: {folder}")
    return pdfs


def project_from_pdfs(
    paths: Sequence[Path],
    *,
    title: str = "無題",
    issue: str = "",
    device_id: str | None = None,
    defaults: PageDefaults | None = None,
) -> Project:
    """PDF の並びからプロジェクトを組み立てる。"""
    project = Project(title=title, issue=issue, defaults=defaults or PageDefaults())
    if device_id:
        project.device_id = device_id
    for path in paths:
        add_article(project, Path(path))
    return project


def add_article(project: Project, path: Path, index: int | None = None) -> Article:
    """PDF を記事として追加する。ページ数は実ファイルから読む。"""
    page_count = renderer.probe_page_count(path)
    article = Article.create(Path(path), page_count, project.defaults)
    if index is None:
        project.articles.append(article)
    else:
        project.articles.insert(index, article)
    return article


def default_output_path(project: Project, folder: Path | None = None) -> Path:
    """既定の出力ファイル名（`誌名 号.epub`）。"""
    base = folder or project.base_dir
    stem = _sanitize_filename(project.book_title()) or "inkflow"
    return Path(base) / f"{stem}.epub"


def build_epub(
    project: Project,
    output_path: Path,
    on_progress: ProgressCallback | None = None,
) -> epub_writer.EpubWriteSummary:
    """プロジェクトから固定レイアウトEPUBを生成する。"""
    if not project.articles:
        raise InkFlowError("記事が1件も登録されていません。PDFを追加してください。")
    project.validate_sources()

    device = project.device()
    options = project.image
    cover_image = cover.build_cover(project, device, options)
    composed = composer.compose(project, on_progress)

    return epub_writer.write_epub(
        Path(output_path),
        title=project.book_title(),
        device=device,
        options=options,
        cover_image=cover_image,
        pages=epub_writer.pages_with_bookmarks(composed),
    )


_INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]')


def _sanitize_filename(name: str) -> str:
    cleaned = _INVALID_FILENAME_CHARS.sub("_", name).strip().strip(".")
    return cleaned[:120]
