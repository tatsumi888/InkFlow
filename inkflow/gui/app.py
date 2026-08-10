"""GUI の起動。"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import QApplication, QMessageBox

from .. import APP_NAME, __version__, appicon, builder, composer
from ..errors import InkFlowError
from ..models import Project
from .main_window import MainWindow

ICON_SIZE = 256


def _initial_project(argv: list[str]) -> tuple[Project | None, str | None]:
    """起動引数からプロジェクトを組み立てる。

    プロジェクトファイル、PDFを並べたフォルダ、PDF そのもの（複数可）を受け付ける。
    エクスプローラからのドロップ起動でも動くようにするため。
    """
    paths = [Path(arg) for arg in argv]
    if not paths:
        return (None, None)

    try:
        if len(paths) == 1 and paths[0].is_file() and paths[0].suffix.lower() == ".json":
            project = Project.load(paths[0])
            composer.sync_page_counts(project)
            return (project, None)

        if len(paths) == 1 and paths[0].is_dir():
            pdfs = builder.collect_pdfs(paths[0])
            return (
                builder.project_from_pdfs(pdfs, title=paths[0].resolve().name),
                None,
            )

        pdfs = [p for p in paths if p.suffix.lower() == ".pdf"]
        if pdfs:
            return (builder.project_from_pdfs(pdfs), None)
    except InkFlowError as e:
        return (None, str(e))

    return (None, None)


def application_icon() -> QIcon | None:
    """アプリアイコンを QIcon にする。

    アイコンは装飾なので、生成や変換に失敗しても起動は続ける。パッケージ版でも
    ソース実行でも同じ図柄になるよう、実行ファイルに埋めたものではなく
    `appicon` から描き起こす。
    """
    try:
        image = appicon.render_icon(ICON_SIZE).convert("RGBA")
        qimage = QImage(
            image.tobytes("raw", "RGBA"),
            image.width,
            image.height,
            image.width * 4,
            QImage.Format.Format_RGBA8888,
        )
        # QImage は渡したバッファを参照するだけなので、コピーして寿命を切り離す。
        return QIcon(QPixmap.fromImage(qimage.copy()))
    except Exception:  # noqa: BLE001 - アイコンのために起動を失敗させない
        return None


def run(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)

    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)

    icon = application_icon()
    if icon is not None:
        app.setWindowIcon(icon)

    project, error = _initial_project(arguments)
    window = MainWindow(project)
    window.show()
    if error:
        QMessageBox.warning(window, "起動時の読み込みに失敗しました", error)

    return app.exec()
