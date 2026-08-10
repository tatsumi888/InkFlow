"""EPUB 出力をバックグラウンドで行うワーカー。

200ページ規模の生成には時間がかかるので、UIスレッドで回すとウィンドウが固まる。
進捗と結果はシグナルで UI スレッドへ返す。
"""

from __future__ import annotations

import copy
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from .. import builder
from ..epub_writer import EpubWriteSummary
from ..models import Project


class _Cancelled(Exception):
    """ユーザーによる中断。進捗コールバックから送出する。"""


class BuildWorker(QThread):
    """プロジェクトから EPUB を書き出すスレッド。"""

    progress = Signal(int, int)
    succeeded = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, project: Project, output_path: Path, parent=None) -> None:
        super().__init__(parent)
        # 生成中に UI 側で編集されても影響を受けないよう、複製を持つ。
        self._project = copy.deepcopy(project)
        self._output_path = Path(output_path)
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    def run(self) -> None:  # noqa: D102 - QThread の規約
        try:
            summary: EpubWriteSummary = builder.build_epub(
                self._project, self._output_path, on_progress=self._on_progress
            )
        except _Cancelled:
            self._remove_partial_output()
            self.cancelled.emit()
        except Exception as e:  # noqa: BLE001 - どんな失敗もUIへ届ける
            self._remove_partial_output()
            self.failed.emit(str(e))
        else:
            self.succeeded.emit(summary)

    def _on_progress(self, done: int, total: int) -> None:
        if self._cancel_requested:
            raise _Cancelled
        self.progress.emit(done, total)

    def _remove_partial_output(self) -> None:
        """中断・失敗時に、書きかけのEPUBを残さない。"""
        try:
            if self._output_path.is_file():
                self._output_path.unlink()
        except OSError:
            pass
