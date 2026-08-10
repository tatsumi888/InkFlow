"""プロジェクトモデルと、その JSON シリアライズ。

1記事 = PDF 1ファイル = しおり1項目。記事の並び順がそのまま本の順序になる。
PDFパスはプロジェクトファイルからの相対パスで保存し、読み込み時に絶対化する。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from . import devices, layouts
from .errors import ProjectFormatError

PROJECT_VERSION = 1
PROJECT_SUFFIX = ".inkflow.json"

IMAGE_FORMATS = ("png", "jpeg")

# 出力コマの回転（時計回りの角度）。
#
# 横長のコマ（上下2分割・上中下3分割など）は、縦長の画面にそのまま収めると上下が
# 大きく余って文字が小さくなる。90°回して端末を横向きに持てば画面をほぼ使い切れる。
# B5の上下2分割なら、画面使用率 53% → 94%（文字は1.33倍）。
# 逆に縦長のコマ（二段組4分割など）では回すと不利になるため、ページ単位の選択にする。
#
# 180° は「縦横入替」という目的に対して意味がないので扱わない。
ROTATION_NONE = 0
ROTATION_CW = 90
ROTATION_CCW = 270
ROTATIONS = (ROTATION_NONE, ROTATION_CW, ROTATION_CCW)
ROTATION_LABELS = {
    ROTATION_NONE: "なし",
    ROTATION_CW: "右90°",
    ROTATION_CCW: "左90°",
}


# 俯瞰ページの回転で「分割コマと同じ」を表す値。
ROTATION_SAME_AS_PARTS = None
ROTATION_SAME_LABEL = "分割と同じ"


def normalize_rotation(value: Any, fallback: int = ROTATION_NONE) -> int:
    """回転値を正規化する。扱えない値は既定へ落とす（例外にしない）。"""
    try:
        rotation = int(value) % 360
    except (TypeError, ValueError):
        return fallback
    return rotation if rotation in ROTATIONS else fallback


def normalize_optional_rotation(value: Any) -> int | None:
    """俯瞰用の回転を正規化する。``None`` は「分割コマと同じ」の意味。

    キーが無い／``null``／扱えない値は、いずれも ``None``（＝分割コマに従う）に
    落とす。既存プロジェクトを読み込んでも挙動が変わらないようにするため。
    """
    if value is None:
        return None
    try:
        rotation = int(value) % 360
    except (TypeError, ValueError):
        return None
    return rotation if rotation in ROTATIONS else None


def _as_bool(value: Any, fallback: bool) -> bool:
    return bool(value) if isinstance(value, bool) else fallback


def _as_float(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _as_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _as_str(value: Any, fallback: str) -> str:
    return value if isinstance(value, str) else fallback


@dataclass
class PageSpec:
    """原稿1ページぶんの分割設定。"""

    layout_id: str = layouts.DEFAULT_LAYOUT_ID
    include_overview: bool = True
    rotate: int = ROTATION_NONE
    # None は「分割コマと同じ向き」。俯瞰と分割コマで望ましい向きが逆になる誌面
    # （A4横を左右に割る場合など）があるため、別々に指定できるようにしている。
    rotate_overview: int | None = ROTATION_SAME_AS_PARTS

    def to_dict(self) -> dict[str, Any]:
        return {
            "layout": self.layout_id,
            "overview": self.include_overview,
            "rotate": self.rotate,
            "rotate_overview": self.rotate_overview,
        }

    @classmethod
    def from_dict(cls, data: Any, fallback: "PageSpec | None" = None) -> "PageSpec":
        base = fallback or cls()
        if not isinstance(data, dict):
            return replace(base)
        layout_id = _as_str(data.get("layout"), base.layout_id)
        if layout_id not in layouts.layout_ids():
            layout_id = base.layout_id
        return cls(
            layout_id=layout_id,
            include_overview=_as_bool(data.get("overview"), base.include_overview),
            rotate=normalize_rotation(data.get("rotate"), base.rotate),
            rotate_overview=(
                normalize_optional_rotation(data["rotate_overview"])
                if "rotate_overview" in data
                else base.rotate_overview
            ),
        )

    def effective_overview_rotation(self) -> int:
        """俯瞰ページに実際に適用される回転角。"""
        return self.rotate if self.rotate_overview is None else self.rotate_overview

    def rotation_label(self) -> str:
        return ROTATION_LABELS.get(self.rotate, ROTATION_LABELS[ROTATION_NONE])

    def overview_rotation_label(self) -> str:
        if self.rotate_overview is None:
            return ROTATION_SAME_LABEL
        return ROTATION_LABELS.get(self.rotate_overview, ROTATION_LABELS[ROTATION_NONE])

    def output_page_count(self) -> int:
        """このページが何枚の出力ページになるか。"""
        layout = layouts.get_layout(self.layout_id)
        if layout.id == "full":
            # 俯瞰と分割が同じ絵になるので1枚に畳む。
            return 1
        return layout.part_count + (1 if self.include_overview else 0)


@dataclass
class PageDefaults:
    """新規ページに適用される既定設定と、分割の共通パラメータ。"""

    layout_id: str = layouts.DEFAULT_LAYOUT_ID
    include_overview: bool = True
    rotate: int = ROTATION_NONE
    rotate_overview: int | None = ROTATION_SAME_AS_PARTS
    overlap: float = layouts.DEFAULT_OVERLAP
    auto_trim: bool = True
    trim_threshold: int = 245

    def to_page_spec(self) -> PageSpec:
        return PageSpec(
            layout_id=self.layout_id,
            include_overview=self.include_overview,
            rotate=self.rotate,
            rotate_overview=self.rotate_overview,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "layout": self.layout_id,
            "overview": self.include_overview,
            "rotate": self.rotate,
            "rotate_overview": self.rotate_overview,
            "overlap": self.overlap,
            "auto_trim": self.auto_trim,
            "trim_threshold": self.trim_threshold,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "PageDefaults":
        base = cls()
        if not isinstance(data, dict):
            return base
        layout_id = _as_str(data.get("layout"), base.layout_id)
        if layout_id not in layouts.layout_ids():
            layout_id = base.layout_id
        return cls(
            layout_id=layout_id,
            include_overview=_as_bool(data.get("overview"), base.include_overview),
            rotate=normalize_rotation(data.get("rotate"), base.rotate),
            rotate_overview=normalize_optional_rotation(data.get("rotate_overview")),
            overlap=layouts.clamp_overlap(_as_float(data.get("overlap"), base.overlap)),
            auto_trim=_as_bool(data.get("auto_trim"), base.auto_trim),
            trim_threshold=min(
                255, max(0, _as_int(data.get("trim_threshold"), base.trim_threshold))
            ),
        )


@dataclass
class ImageOptions:
    """電子ペーパー向けの画像整形パラメータ。

    ``contrast_cutoff`` は自動コントラストで切り捨てるヒストグラムの割合(%)で、
    ``0`` はコントラスト補正の無効を意味する。``gamma`` は 1.0 で無変換、
    1.0 より大きいと全体が濃くなる。
    """

    format: str = "png"
    jpeg_quality: int = 85
    gray_levels: int = 16
    gamma: float = 1.0
    contrast_cutoff: float = 0.5
    sharpen: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "jpeg_quality": self.jpeg_quality,
            "gray_levels": self.gray_levels,
            "gamma": self.gamma,
            "contrast_cutoff": self.contrast_cutoff,
            "sharpen": self.sharpen,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "ImageOptions":
        base = cls()
        if not isinstance(data, dict):
            return base
        fmt = _as_str(data.get("format"), base.format).lower()
        if fmt == "jpg":
            fmt = "jpeg"
        if fmt not in IMAGE_FORMATS:
            fmt = base.format
        return cls(
            format=fmt,
            jpeg_quality=min(100, max(30, _as_int(data.get("jpeg_quality"), base.jpeg_quality))),
            gray_levels=min(256, max(2, _as_int(data.get("gray_levels"), base.gray_levels))),
            gamma=max(0.1, min(3.0, _as_float(data.get("gamma"), base.gamma))),
            contrast_cutoff=max(
                0.0, min(20.0, _as_float(data.get("contrast_cutoff"), base.contrast_cutoff))
            ),
            sharpen=_as_bool(data.get("sharpen"), base.sharpen),
        )


@dataclass
class Article:
    """記事1本（= PDF 1ファイル = しおり1項目）。"""

    path: Path
    title: str
    pages: list[PageSpec] = field(default_factory=list)

    @classmethod
    def create(cls, path: Path, page_count: int, defaults: PageDefaults) -> "Article":
        path = Path(path)
        return cls(
            path=path,
            title=path.stem,
            pages=[defaults.to_page_spec() for _ in range(page_count)],
        )

    def sync_page_count(self, page_count: int, defaults: PageDefaults) -> None:
        """実PDFのページ数に合わせて PageSpec の数をそろえる。"""
        while len(self.pages) < page_count:
            self.pages.append(defaults.to_page_spec())
        del self.pages[page_count:]

    def output_page_count(self) -> int:
        return sum(page.output_page_count() for page in self.pages)

    def to_dict(self, base_dir: Path) -> dict[str, Any]:
        return {
            "path": _relative_path(self.path, base_dir),
            "title": self.title,
            "pages": [page.to_dict() for page in self.pages],
        }

    @classmethod
    def from_dict(cls, data: Any, base_dir: Path, defaults: PageDefaults) -> "Article":
        if not isinstance(data, dict):
            raise ProjectFormatError("記事の定義がオブジェクトではありません。")
        raw_path = data.get("path")
        if not isinstance(raw_path, str) or not raw_path:
            raise ProjectFormatError("記事に 'path' がありません。")
        path = Path(raw_path)
        if not path.is_absolute():
            path = (base_dir / path).resolve()
        raw_pages = data.get("pages")
        fallback = defaults.to_page_spec()
        pages = (
            [PageSpec.from_dict(item, fallback) for item in raw_pages]
            if isinstance(raw_pages, list)
            else []
        )
        return cls(
            path=path,
            title=_as_str(data.get("title"), path.stem),
            pages=pages,
        )


@dataclass
class Project:
    """1号ぶんの編集内容。"""

    title: str = "無題"
    issue: str = ""
    device_id: str = devices.DEFAULT_DEVICE_ID
    defaults: PageDefaults = field(default_factory=PageDefaults)
    image: ImageOptions = field(default_factory=ImageOptions)
    articles: list[Article] = field(default_factory=list)
    cover_image: Path | None = None
    project_path: Path | None = None

    # ---- 便利メソッド -------------------------------------------------

    @property
    def base_dir(self) -> Path:
        return self.project_path.parent if self.project_path else Path.cwd()

    def device(self) -> devices.Device:
        return devices.get_device(self.device_id)

    def book_title(self) -> str:
        """本のタイトル（雑誌名＋号）。"""
        return f"{self.title} {self.issue}".strip() if self.issue else self.title

    def output_page_count(self) -> int:
        """表紙を除いた総出力ページ数。"""
        return sum(article.output_page_count() for article in self.articles)

    def apply_layout_to_all(self, spec: PageSpec) -> None:
        for article in self.articles:
            for index in range(len(article.pages)):
                article.pages[index] = replace(spec)

    def apply_layout_to_article(self, article_index: int, spec: PageSpec) -> None:
        article = self.articles[article_index]
        for index in range(len(article.pages)):
            article.pages[index] = replace(spec)

    # ---- 永続化 -------------------------------------------------------

    def to_dict(self, base_dir: Path | None = None) -> dict[str, Any]:
        base = base_dir or self.base_dir
        return {
            "version": PROJECT_VERSION,
            "title": self.title,
            "issue": self.issue,
            "device": self.device_id,
            "cover_image": _relative_path(self.cover_image, base) if self.cover_image else None,
            "defaults": self.defaults.to_dict(),
            "image": self.image.to_dict(),
            "articles": [article.to_dict(base) for article in self.articles],
        }

    def save(self, path: Path) -> None:
        path = Path(path)
        base = path.parent
        try:
            base.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(self.to_dict(base), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            raise ProjectFormatError(f"プロジェクトを保存できません: {path}") from e
        self.project_path = path

    @classmethod
    def load(cls, path: Path) -> "Project":
        path = Path(path)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as e:
            raise ProjectFormatError(f"プロジェクトファイルを読み込めません: {path}") from e
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ProjectFormatError(f"プロジェクトファイルのJSONが不正です: {path}") from e
        if not isinstance(data, dict):
            raise ProjectFormatError(f"プロジェクトファイルの構造が不正です: {path}")

        base_dir = path.parent
        defaults = PageDefaults.from_dict(data.get("defaults"))

        device_id = _as_str(data.get("device"), devices.DEFAULT_DEVICE_ID)
        try:
            devices.get_device(device_id)
        except Exception:  # noqa: BLE001 - 未知IDは既定に落として編集を継続させる
            device_id = devices.DEFAULT_DEVICE_ID

        raw_articles = data.get("articles")
        if raw_articles is not None and not isinstance(raw_articles, list):
            raise ProjectFormatError("'articles' は配列である必要があります。")
        articles = [
            Article.from_dict(item, base_dir, defaults) for item in (raw_articles or [])
        ]

        raw_cover = data.get("cover_image")
        cover_image: Path | None = None
        if isinstance(raw_cover, str) and raw_cover:
            cover_path = Path(raw_cover)
            cover_image = cover_path if cover_path.is_absolute() else (base_dir / cover_path)

        return cls(
            title=_as_str(data.get("title"), "無題"),
            issue=_as_str(data.get("issue"), ""),
            device_id=device_id,
            defaults=defaults,
            image=ImageOptions.from_dict(data.get("image")),
            articles=articles,
            cover_image=cover_image,
            project_path=path,
        )

    def validate_sources(self) -> None:
        """参照している PDF がすべて存在するか確認する。"""
        missing = [str(a.path) for a in self.articles if not a.path.is_file()]
        if missing:
            listed = "\n  - ".join(missing)
            raise ProjectFormatError(f"参照先のPDFが見つかりません:\n  - {listed}")


def _relative_path(path: Path, base_dir: Path) -> str:
    """可能なら base_dir からの相対パス、無理なら絶対パスを返す。"""
    path = Path(path)
    try:
        return Path(os.path.relpath(str(path), str(base_dir))).as_posix()
    except ValueError:
        # 別ドライブなど相対化できない場合。
        return path.as_posix()
