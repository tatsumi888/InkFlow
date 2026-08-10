"""InkFlow が送出する例外。

下位モジュールは PyMuPDF / Pillow / OS の例外をここで定義した型へ変換し、
UI 層（CLI / GUI）が扱う例外を限定する。
"""


class InkFlowError(Exception):
    """InkFlow の全例外の基底クラス。"""


class PdfLoadError(InkFlowError):
    """PDF を開けない（存在しない・破損・暗号化されている）。"""


class ProjectFormatError(InkFlowError):
    """プロジェクトファイルの構造が不正、または参照先PDFが見つからない。"""


class RenderError(InkFlowError):
    """ページのラスタライズに失敗した。"""


class EpubWriteError(InkFlowError):
    """EPUB を書き出せない（出力先に書き込めない・容量不足など）。"""
