"""GUI の起動。"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from .. import APP_NAME, __version__, builder, composer
from ..errors import InkFlowError
from ..models import Project
from .main_window import MainWindow


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


def run(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)

    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)

    project, error = _initial_project(arguments)
    window = MainWindow(project)
    window.show()
    if error:
        QMessageBox.warning(window, "起動時の読み込みに失敗しました", error)

    return app.exec()
