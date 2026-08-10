"""コマンドラインからの EPUB 生成。

GUI と同じ ``builder.build_epub()`` を呼ぶので、出力は GUI と一致する。
毎月の運用が固まったあと、フォルダに記事PDFを置いて一発で回すための入口。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, builder, composer, devices, layouts
from .errors import InkFlowError
from .models import (
    ROTATION_CCW,
    ROTATION_CW,
    ROTATION_NONE,
    ImageOptions,
    PageDefaults,
    Project,
)

ROTATE_CHOICES = {"none": ROTATION_NONE, "cw": ROTATION_CW, "ccw": ROTATION_CCW}

PROGRESS_WIDTH = 28

# Send to Kindle のメール添付の上限。
SIZE_WARNING_MB = 50

# 実測（B5・40ページ・1236x1648）では、階調数を 16→4 にするとサイズがほぼ半分になり、
# 俯瞰ページを外すと約25%減る。JPEG は文字主体の誌面ではむしろ3倍以上に膨らむため勧めない。
SIZE_ADVICE = (
    "50MB を超えました。Send to Kindle のメール添付では送れません。"
    "USB接続で転送するか、階調数を4に下げる（--gray-levels 4）か、"
    "俯瞰ページを外す（--no-overview）とサイズを減らせます。"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="inkflow",
        description="雑誌記事PDFをKindle向けに再ページ化して固定レイアウトEPUBを作る。",
    )
    parser.add_argument("--version", action="version", version=f"InkFlow {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_cmd = subparsers.add_parser(
        "build",
        help="EPUBを生成する（入力はPDFフォルダ、またはプロジェクトファイル）",
    )
    build_cmd.add_argument(
        "input",
        type=Path,
        help="記事PDFを並べたフォルダ、または .inkflow.json",
    )
    build_cmd.add_argument("-o", "--output", type=Path, help="出力EPUBのパス")
    _add_project_options(build_cmd)
    _add_common_options(build_cmd)
    build_cmd.set_defaults(handler=_command_build)

    init_cmd = subparsers.add_parser(
        "init", help="PDFフォルダからプロジェクトファイルを作る（GUIで開いて調整できる）"
    )
    init_cmd.add_argument("folder", type=Path, help="記事PDFを並べたフォルダ")
    init_cmd.add_argument("-o", "--output", type=Path, help="出力する .inkflow.json のパス")
    _add_project_options(init_cmd)
    _add_common_options(init_cmd)
    init_cmd.set_defaults(handler=_command_init)

    layouts_cmd = subparsers.add_parser("layouts", help="利用できる分割レイアウトを一覧する")
    layouts_cmd.set_defaults(handler=_command_layouts)

    devices_cmd = subparsers.add_parser("devices", help="利用できる端末プリセットを一覧する")
    devices_cmd.set_defaults(handler=_command_devices)

    return parser


def _add_project_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--title", default=None, help="雑誌名（表紙とタイトルに使う）")
    parser.add_argument("--issue", default=None, help="号（例: 2026年8月号）")
    parser.add_argument("--cover", type=Path, default=None, help="表紙に使う画像ファイル")
    parser.add_argument(
        "--device",
        default=None,
        help=f"端末プリセットID（既定: {devices.DEFAULT_DEVICE_ID}、custom:WxH も可）",
    )
    parser.add_argument(
        "--layout",
        default=None,
        choices=list(layouts.layout_ids()),
        help=f"既定の分割レイアウト（既定: {layouts.DEFAULT_LAYOUT_ID}）",
    )
    parser.add_argument(
        "--no-overview",
        action="store_true",
        help="ページ全体（俯瞰）のページを出力しない",
    )
    parser.add_argument(
        "--rotate",
        choices=list(ROTATE_CHOICES),
        default=None,
        help="出力コマを90°回す（cw=右90°, ccw=左90°）。"
        "上下2分割など横長のコマで、端末を横向きに持つと文字が大きくなる",
    )
    parser.add_argument(
        "--overlap",
        type=float,
        default=None,
        help=f"コマ間の重なり（0〜{layouts.MAX_OVERLAP}、既定: {layouts.DEFAULT_OVERLAP}）",
    )
    parser.add_argument("--no-trim", action="store_true", help="余白の自動トリムを行わない")
    parser.add_argument(
        "--format", dest="image_format", choices=["png", "jpeg"], default=None,
        help="ページ画像の形式（既定: png）",
    )
    parser.add_argument("--jpeg-quality", type=int, default=None, help="JPEG品質（30〜100）")
    parser.add_argument(
        "--gray-levels",
        type=int,
        default=None,
        help="グレーの階調数（既定: 16。4まで下げるとサイズがほぼ半分になる）",
    )
    parser.add_argument("--gamma", type=float, default=None, help="ガンマ補正（1.0で無変換）")


def _add_common_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-q", "--quiet", action="store_true", help="進捗を表示しない")
    parser.add_argument(
        "--verbose", action="store_true", help="エラー時にスタックトレースも表示する"
    )


# ---- サブコマンド -------------------------------------------------------


def _command_build(args: argparse.Namespace) -> int:
    project = _load_or_create_project(args)
    output = args.output or builder.default_output_path(
        project, args.input if args.input.is_dir() else args.input.parent
    )

    if not args.quiet:
        total = composer.total_output_pages(project)
        print(f"記事 {len(project.articles)} 本 / 出力 {total} ページ（表紙を除く）")

    reporter = _ProgressReporter(enabled=not args.quiet)
    summary = builder.build_epub(project, output, on_progress=reporter)
    reporter.finish()

    print(
        f"生成しました: {summary.path}\n"
        f"  ページ数: {summary.page_count}（表紙を含む）\n"
        f"  しおり  : {summary.bookmark_count} 件\n"
        f"  サイズ  : {summary.size_mb:.1f} MB"
    )
    if summary.size_mb > SIZE_WARNING_MB:
        print(f"  注意: {SIZE_ADVICE}", file=sys.stderr)
    return 0


def _command_init(args: argparse.Namespace) -> int:
    pdfs = builder.collect_pdfs(args.folder)
    project = builder.project_from_pdfs(
        pdfs,
        title=args.title or args.folder.resolve().name,
        issue=args.issue or "",
        device_id=args.device,
        defaults=_defaults_from_args(args),
    )
    _apply_image_options(project, args)
    if args.cover:
        project.cover_image = args.cover

    output = args.output or (args.folder / f"{args.folder.resolve().name}.inkflow.json")
    project.save(output)
    print(f"プロジェクトを作成しました: {output}")
    print(f"  記事 {len(project.articles)} 本 / 原稿 {sum(len(a.pages) for a in project.articles)} ページ")
    return 0


def _command_layouts(_: argparse.Namespace) -> int:
    for layout in layouts.LAYOUTS:
        marker = "*" if layout.id == layouts.DEFAULT_LAYOUT_ID else " "
        print(f"{marker} {layout.id:<10} {layout.label}")
        print(f"             {layout.hint}")
    print("\n* = 既定")
    return 0


def _command_devices(_: argparse.Namespace) -> int:
    for device in devices.DEVICES:
        marker = "*" if device.id == devices.DEFAULT_DEVICE_ID else " "
        print(f"{marker} {device.id:<16} {device.label}")
    print("  custom:WxH       任意解像度\n\n* = 既定")
    return 0


# ---- 補助 ---------------------------------------------------------------


def _load_or_create_project(args: argparse.Namespace) -> Project:
    source: Path = args.input
    if source.is_dir():
        project = builder.project_from_pdfs(
            builder.collect_pdfs(source),
            title=args.title or source.resolve().name,
            issue=args.issue or "",
            device_id=args.device,
            defaults=_defaults_from_args(args),
        )
    elif source.is_file():
        project = Project.load(source)
        _override_project(project, args)
    else:
        raise InkFlowError(f"入力が見つかりません: {source}")

    _apply_image_options(project, args)
    if args.cover:
        project.cover_image = args.cover
    composer.sync_page_counts(project)
    return project


def _defaults_from_args(args: argparse.Namespace) -> PageDefaults:
    defaults = PageDefaults()
    if args.layout:
        defaults.layout_id = args.layout
    if args.no_overview:
        defaults.include_overview = False
    if args.rotate is not None:
        defaults.rotate = ROTATE_CHOICES[args.rotate]
    if args.overlap is not None:
        defaults.overlap = layouts.clamp_overlap(args.overlap)
    if args.no_trim:
        defaults.auto_trim = False
    return defaults


def _override_project(project: Project, args: argparse.Namespace) -> None:
    """プロジェクトファイルの内容を、明示されたオプションだけ上書きする。"""
    if args.title:
        project.title = args.title
    if args.issue:
        project.issue = args.issue
    if args.device:
        project.device_id = args.device
    if args.layout:
        project.defaults.layout_id = args.layout
        project.apply_layout_to_all(project.defaults.to_page_spec())
    if args.no_overview:
        project.defaults.include_overview = False
        for article in project.articles:
            for page in article.pages:
                page.include_overview = False
    if args.rotate is not None:
        rotation = ROTATE_CHOICES[args.rotate]
        project.defaults.rotate = rotation
        for article in project.articles:
            for page in article.pages:
                page.rotate = rotation
    if args.overlap is not None:
        project.defaults.overlap = layouts.clamp_overlap(args.overlap)
    if args.no_trim:
        project.defaults.auto_trim = False


def _apply_image_options(project: Project, args: argparse.Namespace) -> None:
    options: ImageOptions = project.image
    if args.image_format:
        options.format = args.image_format
    if args.jpeg_quality is not None:
        options.jpeg_quality = max(30, min(100, args.jpeg_quality))
    if args.gray_levels is not None:
        options.gray_levels = max(2, min(256, args.gray_levels))
    if args.gamma is not None:
        options.gamma = max(0.1, min(3.0, args.gamma))


class _ProgressReporter:
    """1行で上書き更新する簡易プログレスバー。"""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self._last_percent = -1
        self._wrote = False

    def __call__(self, done: int, total: int) -> None:
        if not self.enabled or total <= 0:
            return
        percent = int(done * 100 / total)
        if percent == self._last_percent and done != total:
            return
        self._last_percent = percent
        filled = int(PROGRESS_WIDTH * done / total)
        bar = "#" * filled + "-" * (PROGRESS_WIDTH - filled)
        sys.stderr.write(f"\r[{bar}] {percent:3d}%  {done}/{total}")
        sys.stderr.flush()
        self._wrote = True

    def finish(self) -> None:
        if self._wrote:
            sys.stderr.write("\n")
            sys.stderr.flush()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except InkFlowError as e:
        if getattr(args, "verbose", False):
            raise
        print(f"エラー: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n中断しました。", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
